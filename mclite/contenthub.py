# -*- coding: utf-8 -*-
"""资源中心后端（批次3，v1.5.0）

全部走 Modrinth 公开 API（免费、匿名、无需 key）：
- 分类 facet 构造与内容落盘目录映射；
- .mrpack 整合包：下载校验 → 解析 modrinth.index.json → 依赖映射
  （原版 / fabric / quilt / forge / neoforge）→ 逐文件下载校验 → 拷 overrides；
- 路径穿越防护（files[].path 与 overrides/ 都要过 safe_join）。

设计要点（见 _feasibility.md 第 3 节实测）：
- mrpack 的 files[].path 已含 ``mods/``、``resourcepacks/`` 等前缀，**不要再拼一次**；
- overrides/ 下条目要去掉 ``overrides/`` 前缀后按相对路径落到实例根；
- env.client == "unsupported" 的文件（纯服务端）不装进客户端实例；
- 安装幂等：目标已存在且 sha1/size 一致则跳过，失败文件可直接重跑本函数重试。
"""
import json
import os
import re
import shutil
import time
import zipfile

from . import modrinth, util

# 分类 -> 实例内目标目录（整合包走 mrpack 安装器，不在此表）
CATEGORY_DIRS = {
    "mod": "mods",
    "shader": "shaderpacks",
    "resourcepack": "resourcepacks",
    "datapack": "datapacks",
}

# 只有模组需要自动补必需依赖；光影/资源包/数据包不把依赖塞进同一目录
WITH_DEPS = {"mod": True}

# 整合包缓存目录（下载的 .mrpack 本体，供详情预览与安装复用）
CACHE_SUBDIR = os.path.join("cache", "mrpack")


# ---------------------------------------------------------------- 检索 facet
def build_facets(project_type=None, loader=None, game_version=None):
    """构造 Modrinth /v2/search 的 facets（纯函数，便于自测）。

    内层多元素表示 AND，例如 [["project_type:mod"], ["versions:1.20.1"]]。
    """
    facets = []
    if project_type:
        facets.append(["project_type:%s" % project_type])
    if loader:
        facets.append(["categories:%s" % loader])
    if game_version:
        facets.append(["versions:%s" % game_version])
    return facets


def cache_dir():
    d = os.path.join(util.app_root(), CACHE_SUBDIR)
    os.makedirs(d, exist_ok=True)
    return d


# ---------------------------------------------------------------- 路径安全
def safe_join(base, rel):
    """把压缩包内相对路径安全地拼到 base 下；拒绝绝对路径 / 盘符 / ``..`` 穿越。

    返回规范化后的绝对路径；非法时返回 None。
    """
    if rel is None:
        return None
    rel = str(rel).replace("\\", "/").strip()
    if not rel or rel.startswith("/"):
        # 前导斜杠视为绝对路径，拒绝（Windows 盘符另判）
        if rel.startswith("/"):
            return None
    if re.match(r"^[a-zA-Z]:", rel):
        return None
    parts = []
    for p in rel.split("/"):
        if p in ("", "."):
            continue
        if p == "..":
            return None
        parts.append(p)
    if not parts:
        return None
    base_abs = os.path.abspath(base)
    target = os.path.abspath(os.path.join(base_abs, *parts))
    if target != base_abs and not target.startswith(base_abs + os.sep):
        return None
    return target


# ---------------------------------------------------------------- 普通内容安装
def install_content(project_id, game_dir, project_type, game_version=None, loader=None,
                    status=None):
    """把单个 Modrinth 项目主文件（模组可带依赖）装进实例对应目录。

    返回 {"folder", "dir", "files": [(名称, 路径)]}。
    """
    status = status or (lambda s: None)
    folder = CATEGORY_DIRS.get(project_type)
    if not folder:
        raise ValueError("该分类不支持直接安装：%s" % project_type)
    target_dir = os.path.join(game_dir, folder)
    with_deps = bool(WITH_DEPS.get(project_type, False))
    saved = modrinth.download_project(
        project_id, target_dir, game_version=game_version, loader=loader,
        status=status, with_deps=with_deps,
    )
    return {"folder": folder, "dir": target_dir, "files": saved}


# ---------------------------------------------------------------- mrpack 解析
def parse_mrpack(pack_path):
    """解压读取 modrinth.index.json，返回 (index_dict, overrides_条目名列表)。

    overrides 条目保留 zip 内原始名（以 ``overrides/`` 开头），拷贝时再去前缀。
    """
    pack_path = os.path.abspath(pack_path)
    if not os.path.isfile(pack_path):
        raise FileNotFoundError("整合包文件不存在：%s" % pack_path)
    with zipfile.ZipFile(pack_path) as zf:
        names = zf.namelist()
        idx_name = None
        for n in names:
            if n.replace("\\", "/").endswith("modrinth.index.json"):
                idx_name = n
                break
        if not idx_name:
            raise ValueError("不是有效的 .mrpack：缺少 modrinth.index.json")
        index = json.loads(zf.read(idx_name).decode("utf-8"))
        overrides = [
            n for n in names
            if n.replace("\\", "/").startswith("overrides/") and not n.endswith("/")
        ]
    if not isinstance(index, dict) or not isinstance(index.get("files"), list):
        raise ValueError("modrinth.index.json 缺少 files 清单")
    return index, overrides


def map_dependencies(index):
    """把 index.dependencies 映射成 {minecraft, loader, loader_version}。

    支持 fabric-loader / quilt-loader / forge / neoforge 四种键（实测都可能出现）。
    """
    deps = (index or {}).get("dependencies") or {}
    out = {
        "minecraft": str(deps.get("minecraft") or ""),
        "loader": None,
        "loader_version": "",
    }
    if deps.get("fabric-loader"):
        out["loader"] = "fabric"
        out["loader_version"] = str(deps["fabric-loader"])
    elif deps.get("quilt-loader"):
        out["loader"] = "quilt"
        out["loader_version"] = str(deps["quilt-loader"])
    elif deps.get("neoforge"):
        out["loader"] = "neoforge"
        out["loader_version"] = str(deps["neoforge"])
    elif deps.get("forge"):
        out["loader"] = "forge"
        out["loader_version"] = str(deps["forge"])
    return out


def file_installable(entry, include_optional=False):
    """按 env.client 过滤：纯服务端（unsupported）不装；optional 默认跳过。"""
    env = entry.get("env") or {}
    client = env.get("client", "required")
    if client == "unsupported":
        return False
    if client == "optional" and not include_optional:
        return False
    return True


def pack_summary(pack_path):
    """供详情页展示：不下载清单文件，只解析已下载的 .mrpack。"""
    index, overrides = parse_mrpack(pack_path)
    dep = map_dependencies(index)
    files = index.get("files") or []
    total_bytes = 0
    for f in files:
        try:
            total_bytes += int(f.get("fileSize") or 0)
        except (TypeError, ValueError):
            pass
    return {
        "name": index.get("name") or "",
        "version_id": index.get("versionId") or "",
        "summary": index.get("summary") or "",
        "minecraft": dep["minecraft"],
        "loader": dep["loader"],
        "loader_version": dep["loader_version"],
        "file_count": len(files),
        "total_bytes": total_bytes,
        "override_count": len(overrides),
    }


def download_mrpack(project_id, dest_dir, game_version=None, loader=None,
                   version_id=None, status=None):
    """下载整合包主文件（.mrpack），返回 (本地路径, 版本元数据)。

    version_id 非空时直接取指定版本（详情页「安装此版本」）；否则按 MC/加载器筛选。
    """
    status = status or (lambda s: None)
    if version_id:
        ver = modrinth.get_version(version_id)
        vers = [ver] if ver else []
    else:
        vers = modrinth.get_versions(project_id, game_version, loader)
    if not vers:
        raise ValueError("没有匹配的整合包版本")

    entry = None
    chosen = None
    for v in vers:
        f = modrinth.primary_file(v)
        if f and str(f.get("filename", "")).lower().endswith(".mrpack"):
            entry, chosen = f, v
            break
    if entry is None:
        chosen = vers[0]
        entry = modrinth.primary_file(chosen)
    if not entry or not entry.get("url"):
        raise ValueError("整合包版本没有可下载文件")

    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, entry["filename"])
    sha1 = (entry.get("hashes") or {}).get("sha1")
    if not util.file_ok(dest, entry.get("size"), sha1):
        status("下载整合包 %s" % entry.get("filename"))
        util.download_file(entry["url"], dest, expected_sha1=sha1,
                           desc=entry.get("filename"), retries=3, timeout=60)
    return dest, chosen


# ---------------------------------------------------------------- 运行环境安装
def _mc_major(mc_version):
    m = re.match(r"1\.(\d+)(?:\.(\d+))?", str(mc_version or ""))
    if not m:
        return 17
    minor, patch = int(m.group(1)), int(m.group(2) or 0)
    if minor <= 16:
        return 8
    if minor == 17:
        return 17
    if minor <= 20:
        return 17 if not (minor == 20 and patch >= 5) else 21
    return 21


def install_runtime(game_dir, dep, status=None, progress=None, manifest=None,
                    java_exe=None):
    """按依赖映射安装原版 + 加载器，返回安装出的版本 id（纯原版返回 mc 版本号）。"""
    status = status or (lambda s: None)
    progress = progress or (lambda f: None)
    mc = dep.get("minecraft")
    if not mc:
        return None
    from . import forge, java as jm, mojang, quilt

    mm = manifest or mojang.manifest_map(mojang.get_manifest())
    ld = dep.get("loader")
    lv = dep.get("loader_version") or ""

    if ld == "fabric":
        return mojang.install_fabric(game_dir, mc, loader_version=lv or None,
                                     status=status, progress=progress, manifest=mm)
    if ld == "quilt":
        return quilt.install_quilt(game_dir, mc, loader_version=lv or None,
                                   status=status, progress=progress, manifest=mm)
    if ld in ("forge", "neoforge"):
        exe = java_exe or jm.pick_java(_mc_major(mc), all_javas=jm.find_javas())
        if not exe:
            raise RuntimeError("安装 %s 加载器需要本机 Java（未找到匹配版本）" % ld)
        return forge.install_loader(game_dir, mc, ld, lv, exe,
                                    status=status, progress=progress)
    # 无加载器：只装原版
    return mojang.Installer(game_dir, mm, status=status, progress=progress).install(mc)[0]


# ---------------------------------------------------------------- 整合包一键安装
def install_mrpack(pack_path, game_dir, status=None, progress=None,
                   install_runtime_flag=True, java_exe=None, manifest=None,
                   include_optional=False):
    """把已下载的 .mrpack 安装进指定实例目录。

    阶段：解析 → 装运行环境（原版/加载器）→ 逐文件下载校验 → 拷 overrides → 写安装清单。
    返回结果 dict（success/skipped/failed_files/bytes/overrides/runtime_vid 等）。
    幂等：已存在且校验通过的文件会跳过；失败文件重跑本函数即可重试。
    """
    status = status or (lambda s: None)
    progress = progress or (lambda f: None)
    pack_path = os.path.abspath(pack_path)
    game_dir = os.path.abspath(game_dir)
    os.makedirs(game_dir, exist_ok=True)

    index, overrides = parse_mrpack(pack_path)
    dep = map_dependencies(index)
    files = index.get("files") or []

    result = {
        "pack_name": index.get("name") or "",
        "version_id": index.get("versionId") or "",
        "mc": dep["minecraft"],
        "loader": dep["loader"],
        "loader_version": dep["loader_version"],
        "total": len(files),
        "success": 0,
        "skipped": 0,
        "failed_files": [],
        "bytes": 0,
        "overrides": 0,
        "runtime_vid": None,
    }

    # 1) 运行环境（原版 / 加载器）
    if install_runtime_flag and dep.get("minecraft"):
        progress(0.04)
        label = dep["minecraft"]
        if dep.get("loader"):
            label += " + %s %s" % (dep["loader"], dep.get("loader_version") or "")
        status("安装运行环境：%s" % label)
        result["runtime_vid"] = install_runtime(
            game_dir, dep, status=status, progress=progress,
            manifest=manifest, java_exe=java_exe,
        )
        progress(0.30)

    # 2) 逐文件下载到 index 声明的 path（已含 mods/ 等前缀）
    total = max(1, len(files))
    done = 0
    for entry in files:
        path = entry.get("path") or ""
        if not file_installable(entry, include_optional=include_optional):
            result["skipped"] += 1
            done += 1
            continue
        target = safe_join(game_dir, path)
        if target is None:
            result["failed_files"].append({"path": path, "error": "非法路径（穿越/绝对路径）"})
            done += 1
            continue
        downloads = entry.get("downloads") or []
        url = downloads[0] if downloads else None
        if not url:
            result["failed_files"].append({"path": path, "error": "缺少下载地址"})
            done += 1
            continue
        sha1 = (entry.get("hashes") or {}).get("sha1")
        size = entry.get("fileSize")
        try:
            if util.file_ok(target, size, sha1):
                result["success"] += 1
                result["bytes"] += int(size or 0)
            else:
                os.makedirs(os.path.dirname(target), exist_ok=True)
                util.download_file(url, target, expected_sha1=sha1,
                                   desc=os.path.basename(path), retries=2, timeout=45)
                result["success"] += 1
                result["bytes"] += int(size or 0)
        except Exception as e:
            result["failed_files"].append({"path": path, "error": str(e)})
        done += 1
        progress(0.30 + 0.55 * done / total)
        status("下载文件 %d/%d：%s" % (done, len(files), os.path.basename(path)))

    # 3) 拷贝 overrides/（去掉前缀，按相对路径落盘）
    if overrides:
        with zipfile.ZipFile(pack_path) as zf:
            for name in overrides:
                norm = name.replace("\\", "/")
                rel = norm[len("overrides/"):] if norm.startswith("overrides/") else norm
                target = safe_join(game_dir, rel)
                if target is None:
                    continue
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with zf.open(name) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                result["overrides"] += 1

    progress(0.97)

    # 4) 写安装清单（供批次4 本地内容管理识别）
    try:
        record = {
            "format": "mclite-modpack-install",
            "pack_name": result["pack_name"],
            "version_id": result["version_id"],
            "mc": result["mc"],
            "loader": result["loader"],
            "loader_version": result["loader_version"],
            "installed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "files": result["success"],
            "overrides": result["overrides"],
            "failed": len(result["failed_files"]),
        }
        util.write_json(os.path.join(game_dir, "mclite-modpack.json"), record)
    except Exception:
        pass

    progress(1.0)
    status("整合包安装结束：成功 %d / 跳过 %d / 失败 %d / overrides %d" % (
        result["success"], result["skipped"], len(result["failed_files"]), result["overrides"]))
    return result
