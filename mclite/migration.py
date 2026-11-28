# -*- coding: utf-8 -*-
"""跨启动器一键迁移（批次6，v1.8.0）

扫描 HMCL / PCL2 / BHL 的版本目录与配置，列出可导入实例（名称 / MC 版本 / 加载器 /
大小 / 来源启动器），勾选后导入为 MCLite 新实例：

- copy（默认）：把选中版本目录、mods/、saves/、config/ 等**真实拷贝**到新实例目录；
  libraries/assets 体积大，默认用目录联接（junction）复用原目录（不复制、不改原目录），
  可勾选「完全复制 libraries/assets」改为整目录拷贝。
- reference（引用）：新实例的 game_dir 直接指向原启动器游戏目录，不复制任何文件；
  MCLite 实例删除有安全闸门，拒绝删除实例根之外的目录，因此不会误删源目录。

硬边界：本模块对源目录**只读**，所有写操作都落在新建的 MCLite 实例目录内；
绝不删除 / 移动 / 覆盖源启动器目录。
"""
import hashlib
import json
import os
import shutil

from . import util, instances, forge
from .conflictcheck import mc_version_from_id
from .i18n import get_lang

# 拷贝模式下默认复制的实例级内容（相对游戏根目录）
COPY_DIRS = ("mods", "saves", "config", "resourcepacks", "shaderpacks", "datapacks")
COPY_FILES = ("options.txt", "servers.dat", "usercache.json", "usernamecache.json")
# 体积大、默认以 junction 复用的共享目录
SHARED_DIRS = ("libraries", "assets")

LAUNCHER_DEFS = [
    {
        "key": "pcl2",
        "name": "PCL2",
        "config_paths": [
            os.path.join(util.app_root(), "..", "PCL", "config.json"),
            os.path.join(os.environ.get("APPDATA", ""), "PCL", "config.json"),
        ],
        "default_roots": [
            os.path.join(os.environ.get("APPDATA", ""), ".minecraft"),
            os.path.join(os.path.expanduser("~"), ".minecraft"),
        ],
        "marker": "PCL.ini",
    },
    {
        "key": "hmcl",
        "name": "HMCL",
        "config_paths": [
            os.path.join(os.path.expanduser("~"), ".hmcl.json"),
            os.path.join(os.environ.get("APPDATA", ""), ".hmcl", "config.json"),
        ],
        "default_roots": [
            os.path.join(os.path.expanduser("~"), ".minecraft"),
            os.path.join(os.environ.get("APPDATA", ""), ".minecraft"),
        ],
        "marker": ".hmcl.json",
    },
    {
        "key": "bhl",
        "name": "BHL",
        "config_paths": [
            os.path.join(os.environ.get("APPDATA", ""), "BHL", "config.json"),
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "BHL", "config.json"),
            os.path.join(os.path.expanduser("~"), ".bhl", "config.json"),
        ],
        "default_roots": [
            os.path.join(os.environ.get("APPDATA", ""), ".minecraft"),
            os.path.join(os.path.expanduser("~"), ".minecraft"),
            os.path.join(os.environ.get("APPDATA", ""), "BHL", ".minecraft"),
        ],
        "marker": "",
    },
    {
        # PrismLauncher：实例在 instances/<名称>/.minecraft 下；本机未安装时如实显示未检测到
        "key": "prism",
        "name": "PrismLauncher",
        "config_paths": [
            os.path.join(os.environ.get("APPDATA", ""), "PrismLauncher", "prismlauncher.cfg"),
        ],
        "default_roots": [
            os.path.join(os.environ.get("APPDATA", ""), "PrismLauncher", "instances"),
        ],
        "marker": "prismlauncher.cfg",
    },
    {
        # FCL 主要是安卓启动器，Windows 上通常没有；保留检测位，未安装即如实提示
        "key": "fcl",
        "name": "FCL",
        "config_paths": [
            os.path.join(os.environ.get("APPDATA", ""), "FCL", "config.json"),
        ],
        "default_roots": [
            os.path.join(os.environ.get("APPDATA", ""), "FCL", ".minecraft"),
        ],
        "marker": "",
    },
]


def _L(zh, en):
    return en if get_lang() == "en" else zh


def _norm(path):
    return os.path.abspath(os.path.expandvars(os.path.expanduser(str(path or ""))))


def _read_json(path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return json.load(f)
    except Exception:
        return None


def _find_game_dir_in_obj(obj, depth=0):
    """在启动器配置 JSON 里递归找一个「含 versions/ 的游戏目录」字段。"""
    if depth > 5 or not isinstance(obj, dict):
        return ""
    for k, v in obj.items():
        if isinstance(v, str) and os.path.isdir(v):
            low = str(k).lower()
            if os.path.isdir(os.path.join(v, "versions")) and any(
                    token in low for token in ("game", "folder", "path", "dir", "minecraft", "root")):
                return _norm(v)
        if isinstance(v, dict):
            found = _find_game_dir_in_obj(v, depth + 1)
            if found:
                return found
    return ""


def _dir_size(path):
    total = 0
    try:
        for root, _dirs, files in os.walk(path):
            for f in files:
                try:
                    total += os.path.getsize(os.path.join(root, f))
                except OSError:
                    pass
    except OSError:
        pass
    return total


def _count_files(path):
    n = 0
    try:
        for _root, _dirs, files in os.walk(path):
            n += len(files)
    except OSError:
        pass
    return n


# 多个启动器共用的通用游戏根（PCL2/HMCL/BHL 默认都可能指向它）。
# 仅凭这个目录存在不能判定某家启动器已安装——必须有该家自己的配置/标记/专属根。
_GENERIC_SHARED_ROOTS = {
    _norm(os.path.join(os.environ.get("APPDATA", ""), ".minecraft")),
    _norm(os.path.join(os.path.expanduser("~"), ".minecraft")),
}


def detect_launchers():
    """返回五家启动器的检测状态（未安装也如实列出，绝不造假）。

    每项：{key, name, installed, config_path, roots:[...], note}
    判定口径：自有配置文件 / 配置内游戏目录 / 启动器专属根 / 专属标记 任一成立才算安装；
    通用 ``.minecraft`` 共享根只在该启动器已判定安装后作为回退枚举根，不单独触发 installed。
    """
    out = []
    for d in LAUNCHER_DEFS:
        config_path = ""
        cfg_data = None
        for cp in d["config_paths"]:
            cp = _norm(cp)
            if cp and os.path.isfile(cp):
                config_path = cp
                cfg_data = _read_json(cp)
                break
        cfg_root = _find_game_dir_in_obj(cfg_data) if cfg_data else ""
        specific_roots = []
        generic_roots = []
        for dr in d["default_roots"]:
            dr = _norm(dr)
            if not (dr and os.path.isdir(os.path.join(dr, "versions"))):
                continue
            if dr in _GENERIC_SHARED_ROOTS:
                generic_roots.append(dr)
            else:
                specific_roots.append(dr)
        marker = d.get("marker")
        marker_found = bool(marker and any(
            os.path.isfile(os.path.join(r, marker)) for r in specific_roots + generic_roots))
        installed = bool(config_path) or bool(cfg_root) or bool(specific_roots) or marker_found
        roots = []
        if cfg_root:
            roots.append(cfg_root)
        for r in specific_roots:
            if r not in roots:
                roots.append(r)
        if installed:
            # 已确认安装后，通用共享根可作为回退游戏目录参与枚举
            for r in generic_roots:
                if r not in roots:
                    roots.append(r)
        if installed and not roots:
            note = _L("检测到启动器配置，但没找到游戏目录（可在启动器设置里确认游戏文件夹）。",
                      "Launcher config found, but no game folder detected.")
        elif installed:
            note = _L("已检测到游戏目录。", "Game folder detected.")
        else:
            note = _L("未检测到安装；若装在非默认位置，可在启动器设置里查看游戏目录后用「引用原目录」。",
                      "Not detected. If installed elsewhere, point MCLite at the game folder via reference mode.")
        out.append({
            "key": d["key"], "name": d["name"], "installed": installed,
            "config_path": config_path, "roots": roots, "note": note,
        })
    return out


def enumerate_versions(game_root, launcher_key, launcher_name):
    """枚举某个游戏根目录下 versions/ 里的可导入版本。"""
    game_root = _norm(game_root)
    vdir = os.path.join(game_root, "versions")
    cands = []
    if not os.path.isdir(vdir):
        return cands
    for name in sorted(os.listdir(vdir)):
        vpath = os.path.join(vdir, name)
        jp = os.path.join(vpath, name + ".json")
        if not (os.path.isdir(vpath) and os.path.isfile(jp)):
            continue
        meta = _read_json(jp) or {}
        loader = forge.detect_loader(meta)
        if loader == "vanilla":
            loader = ""
        mc = str(meta.get("inheritsFrom") or "") or mc_version_from_id(meta.get("id") or name)
        mods_dir = os.path.join(game_root, "mods")
        saves_dir = os.path.join(game_root, "saves")
        mods_count = 0
        if os.path.isdir(mods_dir):
            mods_count = sum(1 for f in os.listdir(mods_dir)
                             if os.path.isfile(os.path.join(mods_dir, f)) and f.lower().endswith(".jar"))
        saves_count = 0
        if os.path.isdir(saves_dir):
            saves_count = sum(1 for w in os.listdir(saves_dir)
                              if os.path.isfile(os.path.join(saves_dir, w, "level.dat")))
        cands.append({
            "id": name,
            "name": name,
            "game_root": game_root,
            "launcher": launcher_key,
            "launcher_name": launcher_name,
            "mc_version": mc,
            "loader": loader,
            "version_size": _dir_size(vpath),
            "mods_count": mods_count,
            "saves_count": saves_count,
            "mods_dir": mods_dir if os.path.isdir(mods_dir) else "",
            "saves_dir": saves_dir if os.path.isdir(saves_dir) else "",
        })
    return cands


def scan_all():
    """扫描全部已知启动器，返回 {launchers, candidates, roots_scanned}。

    同一游戏根目录被多个启动器指向时按 PCL2→HMCL→BHL 优先级去重，避免重复候选。
    """
    launchers = detect_launchers()
    seen_roots = set()
    candidates = []
    roots_scanned = []
    for lp in launchers:
        for root in lp["roots"]:
            key = os.path.normcase(root)
            if key in seen_roots:
                continue
            seen_roots.add(key)
            roots_scanned.append(root)
            candidates.extend(enumerate_versions(root, lp["key"], lp["name"]))
    candidates.sort(key=lambda c: (c["launcher_name"], c["name"]))
    return {"launchers": launchers, "candidates": candidates, "roots_scanned": roots_scanned}


# ================================================================ 导入
def _copy_tree(src, dst, status=None, label=""):
    """真实拷贝目录（dst 已存在则合并），返回 (文件数, 字节数)。"""
    if not os.path.isdir(src):
        return 0, 0
    os.makedirs(dst, exist_ok=True)
    n = 0
    total = 0
    for root, _dirs, files in os.walk(src):
        rel = os.path.relpath(root, src)
        out_dir = os.path.join(dst, rel) if rel != "." else dst
        os.makedirs(out_dir, exist_ok=True)
        for f in files:
            s = os.path.join(root, f)
            d = os.path.join(out_dir, f)
            try:
                shutil.copy2(s, d)
                n += 1
                total += os.path.getsize(s)
            except OSError:
                pass
    if status and label:
        status(_L("已复制 %s（%d 个文件）" % (label, n), "Copied %s (%d files)" % (label, n)))
    return n, total


def _make_junction(link_path, target_path):
    """目录联接（复用 sharedpool 的实现，mklink /J 无需管理员）。"""
    from . import sharedpool
    return sharedpool._make_junction(link_path, target_path)


def import_candidate(cfg, cand, mode="copy", new_name=None, copy_big_shared=False, status=None):
    """把一个候选版本导入为 MCLite 新实例。

    mode="copy"：真实拷贝版本/模组/存档/配置；libraries/assets 默认 junction 复用。
    mode="reference"：新实例直接引用原游戏目录（不复制）。
    返回 {inst, mode, copied:{...}, junctions:[...], stats:{...}}。
    """
    status = status or (lambda s: None)
    root = _norm(cand["game_root"])
    vid = cand["name"]
    loader = cand.get("loader") or ""
    base_name = new_name or ("%s（%s）" % (vid, cand.get("launcher_name") or "迁移"))

    if mode == "reference":
        inst = instances.create(
            cfg, base_name, game_dir=root, icon="⇄", loader_hint=loader, switch=True)
        instances.update(cfg, inst["id"], last_version=vid, loader_hint=loader)
        status(_L("已建立引用实例：%s → %s" % (base_name, root),
                   "Reference instance created: %s → %s" % (base_name, root)))
        return {"inst": inst, "mode": "reference", "copied": {}, "junctions": [],
                "stats": {"files": 0, "bytes": 0}, "source_root": root}

    # copy 模式：在实例根下建独立新目录
    inst = instances.create(cfg, base_name, game_dir=None, icon="⇄",
                            loader_hint=loader, switch=True)
    dst = os.path.abspath(inst["game_dir"])
    copied = {}
    junctions = []
    total_files = 0
    total_bytes = 0

    # 1) 选中版本目录（json + jar + natives 等）
    src_ver = os.path.join(root, "versions", vid)
    dst_ver = os.path.join(dst, "versions", vid)
    n, b = _copy_tree(src_ver, dst_ver, status, _L("版本目录", "version folder"))
    copied["versions/" + vid] = {"files": n, "bytes": b}
    total_files += n
    total_bytes += b

    # 2) 实例级内容目录（mods/saves/config/...）
    for d in COPY_DIRS:
        src_d = os.path.join(root, d)
        if os.path.isdir(src_d):
            n, b = _copy_tree(src_d, os.path.join(dst, d), status, d)
            copied[d] = {"files": n, "bytes": b}
            total_files += n
            total_bytes += b

    # 3) 零散配置文件
    for f in COPY_FILES:
        src_f = os.path.join(root, f)
        if os.path.isfile(src_f):
            try:
                shutil.copy2(src_f, os.path.join(dst, f))
                total_files += 1
                total_bytes += os.path.getsize(src_f)
            except OSError:
                pass

    # 4) libraries / assets：默认 junction 复用（不复制、不改源），可选完全复制
    for d in SHARED_DIRS:
        src_d = os.path.join(root, d)
        if not os.path.isdir(src_d):
            continue
        dst_d = os.path.join(dst, d)
        if copy_big_shared:
            n, b = _copy_tree(src_d, dst_d, status, d)
            copied[d] = {"files": n, "bytes": b}
            total_files += n
            total_bytes += b
        else:
            if os.path.exists(dst_d):
                continue
            os.makedirs(dst, exist_ok=True)
            if _make_junction(dst_d, src_d):
                junctions.append({"link": dst_d, "target": src_d})
                status(_L("%s 以目录联接复用原目录（不复制、不改动）" % d,
                           "%s linked to source via junction (no copy, no change)" % d))
            else:
                # junction 失败则退化为复制，保证可用
                n, b = _copy_tree(src_d, dst_d, status, d)
                copied[d] = {"files": n, "bytes": b, "fallback": "copy"}
                total_files += n
                total_bytes += b

    instances.update(cfg, inst["id"], last_version=vid, loader_hint=loader)
    status(_L("导入完成：%s（%d 个文件，%s）" % (
        base_name, total_files, util.human_size(total_bytes)),
        "Import done: %s (%d files, %s)" % (base_name, total_files, util.human_size(total_bytes))))
    return {
        "inst": inst, "mode": "copy", "copied": copied, "junctions": junctions,
        "stats": {"files": total_files, "bytes": total_bytes}, "source_root": root,
    }


# ================================================================ 源目录零改动取证
def snapshot(root, sample_limit=300):
    """对源目录做只读快照：文件数 / 总字节 / 抽样 sha256（用于导入前后对比）。"""
    root = _norm(root)
    snap = {"root": root, "file_count": 0, "total_bytes": 0, "sample": {}}
    if not os.path.isdir(root):
        return snap
    sample = []
    for dirpath, _dirs, files in os.walk(root):
        for f in files:
            full = os.path.join(dirpath, f)
            try:
                size = os.path.getsize(full)
            except OSError:
                continue
            snap["file_count"] += 1
            snap["total_bytes"] += size
            rel = os.path.relpath(full, root)
            # 优先抽样 mods/ 与 saves 下的 level.dat，再补前若干个普通文件
            if rel.replace("\\", "/").startswith("mods/") or rel.endswith("level.dat"):
                sample.append((rel, full))
            elif len(sample) < sample_limit:
                sample.append((rel, full))
    for rel, full in sample[:sample_limit]:
        try:
            h = hashlib.sha256()
            with open(full, "rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    h.update(chunk)
            snap["sample"][rel] = h.hexdigest()
        except OSError:
            continue
    return snap


def diff_snapshot(before, after):
    """对比两次快照，返回是否零改动与差异明细（文件数/字节/抽样哈希）。"""
    diffs = []
    if before.get("file_count") != after.get("file_count"):
        diffs.append("file_count %s -> %s" % (before.get("file_count"), after.get("file_count")))
    if before.get("total_bytes") != after.get("total_bytes"):
        diffs.append("total_bytes %s -> %s" % (before.get("total_bytes"), after.get("total_bytes")))
    for rel, h in before.get("sample", {}).items():
        if rel not in after.get("sample", {}):
            diffs.append("missing sample: %s" % rel)
        elif after["sample"][rel] != h:
            diffs.append("hash changed: %s" % rel)
    for rel in after.get("sample", {}):
        if rel not in before.get("sample", {}):
            diffs.append("new sample: %s" % rel)
    return {"unchanged": not diffs, "diffs": diffs,
            "before_files": before.get("file_count"), "after_files": after.get("file_count"),
            "before_bytes": before.get("total_bytes"), "after_bytes": after.get("total_bytes")}
