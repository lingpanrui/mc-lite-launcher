# -*- coding: utf-8 -*-
"""Mojang 版本清单、原版 / Fabric 安装、启动参数构建"""
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor

from . import util

MANIFEST_URL = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
FABRIC_META = "https://meta.fabricmc.net/v2"


# --------------------------------------------------------------------------- #
# 运行环境判断
# --------------------------------------------------------------------------- #
def os_name():
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "osx"
    return "linux"


def os_arch():
    m = platform.machine().lower()
    if m in ("amd64", "x86_64", "x64"):
        return "x86_64"
    if m in ("arm64", "aarch64"):
        return "arm64"
    return "x86"


def os_version():
    # Mojang 规则用的是系统版本号（Windows 下形如 10.0.19045）
    return platform.version()


def rules_allow(rules, features=None):
    if not rules:
        return True
    features = features or {}
    allowed = False
    for rule in rules:
        ok = True
        o = rule.get("os") or {}
        if "name" in o and o["name"] != os_name():
            ok = False
        if "arch" in o and o["arch"] != os_arch():
            ok = False
        if "version" in o:
            try:
                if not re.fullmatch(o["version"], os_version()):
                    ok = False
            except Exception:
                ok = False
        for k, v in (rule.get("features") or {}).items():
            if bool(features.get(k)) != bool(v):
                ok = False
        if ok:
            allowed = rule.get("action", "allow") == "allow"
    return allowed


# --------------------------------------------------------------------------- #
# 清单
# --------------------------------------------------------------------------- #
def get_manifest():
    return util.http_json(MANIFEST_URL)


def manifest_map(manifest):
    out = {}
    for v in (manifest or {}).get("versions", []):
        out[v["id"]] = {"url": v["url"], "type": v.get("type"), "releaseTime": v.get("releaseTime")}
    return out


def maven_to_path(name):
    """net.fabricmc:fabric-loader:0.16.9[:classifier][@jar] -> 仓库相对路径"""
    ext = "jar"
    if "@" in name:
        name, ext = name.split("@", 1)
    parts = name.split(":")
    group, artifact, version = parts[0], parts[1], parts[2]
    classifier = parts[3] if len(parts) > 3 else None
    rel = "/".join(group.split(".")) + "/" + artifact + "/" + version + "/" + artifact + "-" + version
    if classifier:
        rel += "-" + classifier
    return rel + "." + ext


def offline_uuid(username):
    data = hashlib.md5(("OfflinePlayer:" + username).encode("utf-8")).digest()
    return str(uuid.UUID(bytes=data, version=3))


# --------------------------------------------------------------------------- #
# 安装
# --------------------------------------------------------------------------- #
class Installer:
    """下载并安装一个 Java 版（原版或带 inheritsFrom 的 Fabric 版本）"""

    def __init__(self, game_dir, manifest=None, status=None, progress=None):
        self.game_dir = game_dir
        self.manifest = manifest or {}
        self.status = status or (lambda s: None)
        self.progress = progress or (lambda f: None)
        self._lock = threading.Lock()

    # -- 路径 ---------------------------------------------------------------
    def _vdir(self, vid):
        return os.path.join(self.game_dir, "versions", vid)

    @property
    def assets_dir(self):
        return os.path.join(self.game_dir, "assets")

    @property
    def libs_dir(self):
        return os.path.join(self.game_dir, "libraries")

    # -- 主流程 -------------------------------------------------------------
    def install(self, version_id):
        self.status("准备安装 %s" % version_id)
        vdir = self._vdir(version_id)
        jpath = os.path.join(vdir, version_id + ".json")

        if not os.path.isfile(jpath):
            info = self.manifest.get(version_id) or {}
            url = info.get("url")
            if not url:
                raise ValueError("找不到版本 %s 的下载地址" % version_id)
            self.status("获取版本信息 %s" % version_id)
            data = util.http_json(url)
            os.makedirs(vdir, exist_ok=True)
            util.write_json(jpath, data)

        with open(jpath, "r", encoding="utf-8") as f:
            vj = json.load(f)

        parent = vj.get("inheritsFrom")
        if parent:
            self.install(parent)

        self._install_files(version_id, vj)
        self.status("%s 安装完成" % version_id)
        self.progress(1.0)
        return version_id, jpath

    def _install_files(self, vid, vj):
        vdir = self._vdir(vid)
        os.makedirs(vdir, exist_ok=True)
        os.makedirs(self.libs_dir, exist_ok=True)
        os.makedirs(self.assets_dir, exist_ok=True)

        # 1) 客户端主 jar --------------------------------------------------
        dl = (vj.get("downloads") or {}).get("client")
        if dl:
            jar = os.path.join(vdir, vid + ".jar")
            if not util.file_ok(jar, dl.get("size"), dl.get("sha1")):
                self.status("下载客户端核心 %s" % vid)
                util.download_file(dl["url"], jar, expected_sha1=dl.get("sha1"), desc="客户端核心")
            self.progress(0.08)

        # 2) 依赖库 + 原生库 ------------------------------------------------
        libs = vj.get("libraries") or []
        plan = []
        natives_dir = os.path.join(vdir, "natives")
        for lib in libs:
            if not rules_allow(lib.get("rules")):
                continue
            name = lib.get("name") or ""
            art = (lib.get("downloads") or {}).get("artifact")
            if art and art.get("path"):
                plan.append(("lib", art, name))
            elif name and lib.get("url"):
                rel = maven_to_path(name)
                plan.append(("lib", {"path": rel, "url": lib["url"].rstrip("/") + "/" + rel, "sha1": None}, name))
            nat_map = lib.get("natives") or {}
            cls = nat_map.get(os_name())
            if cls:
                cls = cls.replace("${arch}", "64" if os_arch() == "x86_64" else "32")
                a = (lib.get("downloads") or {}).get("classifiers", {}).get(cls)
                if a and a.get("path"):
                    plan.append(("native", a, name))

        if plan:
            self.status("下载依赖库 %d 个" % len(plan))
            done = [0]
            total = [len(plan)]
            self.progress(0.10)

            def one(item):
                kind, info, name = item
                dest = os.path.join(self.libs_dir, info["path"].replace("/", os.sep))
                if not util.file_ok(dest, info.get("size"), info.get("sha1")):
                    util.download_file(
                        info["url"], dest, expected_sha1=info.get("sha1"), desc=os.path.basename(info["path"])
                    )
                if kind == "native" or "-natives-" in name:
                    try:
                        util.safe_extract_zip(dest, natives_dir)
                    except Exception:
                        pass
                with self._lock:
                    done[0] += 1
                    if done[0] % 5 == 0 or done[0] == total[0]:
                        self.progress(0.10 + 0.12 * done[0] / total[0])

            with ThreadPoolExecutor(max_workers=16) as ex:
                list(ex.map(one, plan))

        # 3) 资源索引 + 资源文件 --------------------------------------------
        ai = vj.get("assetIndex")
        if ai and ai.get("url"):
            idx_path = os.path.join(self.assets_dir, "indexes", str(ai["id"]) + ".json")
            if not util.file_ok(idx_path, ai.get("size"), ai.get("sha1")):
                self.status("下载资源索引 %s" % ai["id"])
                util.download_file(ai["url"], idx_path, expected_sha1=ai.get("sha1"), desc="资源索引")
            index = util.read_json(idx_path, {}) or {}
            objects = index.get("objects") or {}
            if objects:
                self._download_objects(objects, ai["id"], index.get("virtual"))
            self.progress(0.95)

        # 4) 日志配置 --------------------------------------------------------
        log_cfg = ((vj.get("logging") or {}).get("client") or {}).get("file")
        if log_cfg and log_cfg.get("url"):
            dest = os.path.join(self.assets_dir, "log_configs", log_cfg.get("id", "client.xml"))
            if not util.file_ok(dest, log_cfg.get("size"), log_cfg.get("sha1")):
                util.download_file(log_cfg["url"], dest, expected_sha1=log_cfg.get("sha1"), desc="日志配置")

        util.write_json(
            os.path.join(vdir, ".installed.json"),
            {"id": vid, "installed_at": time.time()},
        )

    def _download_objects(self, objects, index_id, virtual):
        total = len(objects)
        self.status("下载游戏资源（%d 个文件）" % total)
        self.progress(0.22)
        done = [0]
        obj_root = os.path.join(self.assets_dir, "objects")

        def one(item):
            path_name, o = item
            dest = os.path.join(obj_root, o["hash"][:2], o["hash"])
            if not util.file_ok(dest, o.get("size"), o.get("sha1")):
                url = o.get("url") or "https://resources.download.minecraft.net/%s/%s" % (
                    o["hash"][:2], o["hash"])
                util.download_file(url, dest, expected_sha1=o.get("sha1"), desc="资源")
            with self._lock:
                done[0] += 1
                if done[0] % 40 == 0 or done[0] == total:
                    self.progress(0.22 + 0.70 * done[0] / total)
                    self.status("下载游戏资源 %d/%d" % (done[0], total))

        with ThreadPoolExecutor(max_workers=24) as ex:
            list(ex.map(one, objects.items()))

        if virtual:
            target = os.path.join(self.assets_dir, "virtual", str(index_id))
            self.status("生成旧版资源目录")
            for name, o in objects.items():
                src = os.path.join(obj_root, o["hash"][:2], o["hash"])
                dst = os.path.join(target, name.replace("/", os.sep))
                if not os.path.exists(dst):
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    try:
                        shutil.copyfile(src, dst)
                    except Exception:
                        pass


def install_fabric(game_dir, mc_version, loader_version=None, status=None, progress=None, manifest=None):
    """安装 Fabric 加载器（自动选择最新稳定 loader），返回 Fabric 版本 id"""
    status = status or (lambda s: None)
    manifest = manifest or manifest_map(get_manifest())
    status("获取 Fabric 加载器列表")
    loaders = util.http_json("%s/versions/loader/%s" % (FABRIC_META, mc_version))
    if not loaders:
        raise ValueError("%s 没有可用的 Fabric 加载器" % mc_version)
    if not loader_version:
        for item in loaders:
            lv = (item.get("loader") or {}).get("version")
            if lv and item.get("intermediary"):
                loader_version = lv
                break
        loader_version = loader_version or loaders[0]["loader"]["version"]

    status("获取 Fabric 安装配置")
    profile = util.http_json(
        "%s/versions/loader/%s/%s/profile/json" % (FABRIC_META, mc_version, loader_version)
    )
    vid = profile.get("id") or ("fabric-loader-%s-%s" % (loader_version, mc_version))
    vdir = os.path.join(game_dir, "versions", vid)
    os.makedirs(vdir, exist_ok=True)
    util.write_json(os.path.join(vdir, vid + ".json"), profile)

    # 先装原版基础版本，Fabric 依赖它
    Installer(game_dir, manifest, status=status, progress=progress).install(mc_version)
    status("Fabric %s 已就绪" % vid)
    return vid


# --------------------------------------------------------------------------- #
# 版本合并 + 启动
# --------------------------------------------------------------------------- #
def _merge(parent, child):
    out = json.loads(json.dumps(parent))
    for k, v in child.items():
        if k in ("libraries", "arguments", "minecraftArguments", "inheritsFrom", "id"):
            continue
        out[k] = v

    # 依赖库：子版本优先，按名称去重
    libs = {}
    order = []
    for lib in list(child.get("libraries") or []) + list(parent.get("libraries") or []):
        key = lib.get("name") or lib.get("path") or json.dumps(lib, sort_keys=True)[:80]
        if key in libs:
            continue
        libs[key] = lib
        order.append(key)
    out["libraries"] = [libs[k] for k in order]

    # 参数：父在前、子在后
    pa = parent.get("arguments") or {}
    ca = child.get("arguments") or {}
    merged_args = {}
    merged_args["jvm"] = list(pa.get("jvm") or []) + list(ca.get("jvm") or [])
    merged_args["game"] = list(pa.get("game") or []) + list(ca.get("game") or [])
    if merged_args["jvm"] or merged_args["game"]:
        out["arguments"] = merged_args
    if child.get("minecraftArguments"):
        out["minecraftArguments"] = child["minecraftArguments"]
    elif parent.get("minecraftArguments"):
        out["minecraftArguments"] = parent["minecraftArguments"]
    return out


def resolve_version(game_dir, version_id):
    """解析 inheritsFrom 链，返回 (合并后的版本 json, 根版本 id)"""
    chain = []
    vid = version_id
    guard = 0
    while vid:
        if guard > 8:
            raise ValueError("版本依赖链异常：%s" % version_id)
        jp = os.path.join(game_dir, "versions", vid, vid + ".json")
        if not os.path.isfile(jp):
            raise FileNotFoundError("版本 %s 未安装，请先在“版本与安装”里安装" % vid)
        chain.append((vid, util.read_json(jp, {}) or {}))
        vid = chain[-1][1].get("inheritsFrom")
        guard += 1

    root_id = chain[-1][0]
    merged = json.loads(json.dumps(chain[-1][1]))
    for cid, cj in reversed(chain[:-1]):
        merged = _merge(merged, cj)
    merged["id"] = version_id
    return merged, root_id


def guess_java_major(vj):
    major = (vj.get("javaVersion") or {}).get("majorVersion")
    if major:
        try:
            return int(major)
        except Exception:
            pass
    m = re.match(r"1\.(\d+)", str(vj.get("id", "")))
    if m:
        n = int(m.group(1))
        if n <= 16:
            return 8
        if n == 17:
            return 16
        if n <= 20:
            return 17
        return 21
    return 21


def _render(text, params):
    for k, v in params.items():
        text = text.replace("${%s}" % k, str(v))
    if "${" in text:
        return None
    return text


def _arg_value(item, params):
    if isinstance(item, str):
        s = item
    elif isinstance(item, dict):
        if not rules_allow(item.get("rules")):
            return None
        val = item.get("value")
        s = "".join(val) if isinstance(val, list) else val
        if not isinstance(s, str):
            return None
    else:
        return None
    return _render(s, params)


def build_command(game_dir, version_id, java_exe, username, memory_mb, width=854, height=480,
                  launcher_name="MCLite", launcher_version="1.5.0", auth=None, extra_jvm=None):
    vj, root_id = resolve_version(game_dir, version_id)
    assets_dir = os.path.join(game_dir, "assets")
    libs_dir = os.path.join(game_dir, "libraries")
    natives_dir = os.path.join(game_dir, "versions", root_id, "natives")
    os.makedirs(natives_dir, exist_ok=True)

    cp = []
    seen = set()
    missing = 0
    for lib in vj.get("libraries") or []:
        if not rules_allow(lib.get("rules")):
            continue
        art = (lib.get("downloads") or {}).get("artifact")
        rel = art.get("path") if art and art.get("path") else None
        if not rel and lib.get("name"):
            rel = maven_to_path(lib["name"])
        if not rel:
            continue
        p = os.path.join(libs_dir, rel.replace("/", os.sep))
        key = os.path.normcase(os.path.abspath(p))
        if os.path.isfile(p):
            if key not in seen:
                seen.add(key)
                cp.append(p)
        else:
            missing += 1
    main_class = vj.get("mainClass") or "net.minecraft.client.main.Main"
    needs_vanilla = not ("bootstraplauncher" in main_class.lower() or "modlauncher" in main_class.lower())
    jar = os.path.join(game_dir, "versions", root_id, root_id + ".jar")
    if needs_vanilla and os.path.isfile(jar):
        key = os.path.normcase(os.path.abspath(jar))
        if key not in seen:
            seen.add(key)
            cp.append(jar)

    asset_index = (vj.get("assetIndex") or {}).get("id") or vj.get("assets") or "legacy"
    params = {
        "auth_player_name": (auth or {}).get("name") or username,
        "version_name": vj.get("id") or version_id,
        "game_directory": game_dir,
        "assets_root": assets_dir,
        "game_assets": os.path.join(assets_dir, "virtual", str(asset_index)),
        "assets_index_name": asset_index,
        "auth_uuid": (auth or {}).get("uuid") or offline_uuid(username),
        "auth_access_token": (auth or {}).get("token") or "0" * 32,
        "auth_session": (auth or {}).get("token") or "0" * 32,
        "user_type": (auth or {}).get("user_type") or (
            "msa" if str(vj.get("releaseTime", "")).startswith(("2021", "2022", "2023", "2024", "2025", "2026")) else "legacy"),
        "version_type": vj.get("type") or "release",
        "natives_directory": natives_dir,
        "launcher_name": launcher_name,
        "launcher_version": launcher_version,
        "classpath": os.pathsep.join(cp),
        "classpath_separator": os.pathsep,
        "library_directory": libs_dir,
        "user_properties": "{}",
        "clientid": "",
        "auth_xuid": "",
        "resolution_width": int(width),
        "resolution_height": int(height),
    }

    memory = max(512, int(memory_mb))
    cmd = [java_exe]
    if str(vj.get("releaseTime", "")) < "2021-12":
        cmd.append("-Dlog4j2.formatMsgNoLookups=true")
    cmd += ["-Xmx%dM" % memory, "-Xms%dM" % min(memory, 1024)]
    for extra in (extra_jvm or []):
        if extra:
            cmd.append(extra)

    args = vj.get("arguments")
    if args:
        for item in args.get("jvm") or []:
            v = _arg_value(item, params)
            if v:
                cmd.append(v)
    cmd += ["-Djava.library.path=%s" % natives_dir, "-Dfile.encoding=UTF-8", "-cp", params["classpath"]]

    main_class = vj.get("mainClass") or "net.minecraft.client.main.Main"
    cmd.append(main_class)

    if args:
        for item in args.get("game") or []:
            v = _arg_value(item, params)
            if v:
                cmd.append(v)
    else:
        legacy = vj.get("minecraftArguments") or ""
        for token in legacy.split():
            v = _render(token, params)
            if v:
                cmd.append(v)

    if missing:
        pass  # 缺失依赖不会致命，但由 UI 记录提示
    return cmd, vj, root_id, missing


def _write_argfile(path, args):
    """把启动参数写入 Java @argfile，避免 Windows 32767 字符命令行上限"""
    lines = []
    for a in args:
        a = a.replace("\\", "/")
        if any(c in a for c in ' \t;'):
            a = '"' + a.replace('"', "") + '"'
        lines.append(a)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return path


def launch(cmd, game_dir, on_output=None):
    """启动游戏进程，返回 Popen"""
    os.makedirs(game_dir, exist_ok=True)
    total = sum(len(str(a)) + 3 for a in cmd)
    if total > 20000:
        argfile = _write_argfile(os.path.join(game_dir, ".mclite-args.txt"), cmd[1:])
        cmd = [cmd[0], "@" + argfile]
    flags = 0x08000000 if os_name() == "windows" else 0  # CREATE_NO_WINDOW
    proc = subprocess.Popen(
        cmd,
        cwd=game_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=flags,
    )
    if on_output:
        def reader():
            try:
                for line in proc.stdout:
                    on_output(line.rstrip("\n"))
            except Exception:
                pass
        threading.Thread(target=reader, daemon=True).start()
    return proc
