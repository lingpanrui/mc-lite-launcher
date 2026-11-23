# -*- coding: utf-8 -*-
"""Forge / NeoForge 安装

官方 maven 在国内经常超时或被污染，因此统一采用「官方优先、BMCLAPI 镜像兜底」。
"""
import os
import re
import subprocess
import sys
import time

from . import util

FORGE_BASE = "https://maven.minecraftforge.net/net/minecraftforge/forge"
FORGE_MIRROR = "https://bmclapi2.bangbang93.com/maven/net/minecraftforge/forge"
NEO_BASE = "https://maven.neoforged.net/releases/net/neoforged/neoforge"
NEO_MIRROR = "https://bmclapi2.bangbang93.com/maven/net/neoforged/neoforge"

_meta_cache = {}


def _ver_key(ver):
    parts = re.findall(r"\d+", ver)
    return tuple(int(x) for x in parts[:4]) if parts else (0,)


def _maven_text(path, bases, timeout=25):
    """依次尝试各 maven 源，返回第一份可用文本"""
    last = None
    for base in bases:
        try:
            return util.http_text(base + path, timeout=timeout)
        except Exception as e:
            last = e
    raise IOError("maven 源不可用：%s" % last)


def list_forge(mc_version):
    """该游戏版本可用的 Forge 版本（新到旧）"""
    key = ("forge", mc_version)
    if key not in _meta_cache:
        xml = _maven_text("/maven-metadata.xml", (FORGE_BASE, FORGE_MIRROR))
        vers = re.findall(r"<version>%s-([^<]+)</version>" % re.escape(mc_version), xml)
        _meta_cache[key] = sorted(set(vers), key=_ver_key, reverse=True)
    return list(_meta_cache[key])


def neo_prefix(mc_version):
    """1.20.4 -> 20.4. / 1.21 -> 21.0. / 1.21.1 -> 21.1."""
    if not mc_version.startswith("1."):
        raise ValueError("NeoForge 只支持 1.20.2 及以后的版本")
    rest = mc_version.split(".")[1:]
    if not rest:
        raise ValueError("版本号无法解析：%s" % mc_version)
    if len(rest) == 1:
        return rest[0] + ".0."
    return rest[0] + "." + rest[1] + "."


def list_neoforge(mc_version):
    prefix = neo_prefix(mc_version)
    key = ("neoforge", prefix)
    if key not in _meta_cache:
        try:
            xml = _maven_text("/maven-metadata.xml", (NEO_BASE, NEO_MIRROR), timeout=12)
            vers = re.findall(r"<version>([^<]+)</version>", xml)
            _meta_cache[key] = sorted({v for v in vers if v.startswith(prefix)}, key=_ver_key, reverse=True)
        except Exception:
            # 元数据拿不到（常见于 maven.neoforged.net 被污染），返回空表，由 UI 提示手填版本号
            _meta_cache[key] = []
    return list(_meta_cache[key])


def _installer_urls(loader, mc_version, loader_version):
    if loader == "forge":
        lv = loader_version
        if lv.startswith(mc_version + "-"):
            lv = lv[len(mc_version) + 1:]
        full = "%s-%s" % (mc_version, lv)
        name = "forge-%s-installer.jar" % full
        sub = "/%s/%s" % (full, name)
    else:
        name = "neoforge-%s-installer.jar" % loader_version
        sub = "/%s/%s" % (loader_version, name)
    if loader == "forge":
        bases = (FORGE_BASE, FORGE_MIRROR)
    else:
        bases = (NEO_BASE, NEO_MIRROR)
    return [b + sub for b in bases], name


def _download_installer(loader, mc_version, loader_version, status):
    urls, name = _installer_urls(loader, mc_version, loader_version)
    cache_dir = os.path.join(util.app_root(), "cache")
    os.makedirs(cache_dir, exist_ok=True)
    dest = os.path.join(cache_dir, name)
    size = 0
    for url in urls:
        try:
            status("下载安装器：%s" % url.split("/")[2])
            util.download_file(url, dest, retries=1, timeout=45, desc="安装器")
            size = os.path.getsize(dest)
            break
        except Exception:
            continue
    if not size:
        raise IOError("安装器下载失败，请检查网络（已尝试官方与 BMCLAPI 镜像）")
    return dest


def _ensure_launcher_profiles(game_dir):
    path = os.path.join(game_dir, "launcher_profiles.json")
    if not os.path.isfile(path):
        util.write_json(path, {
            "profiles": {},
            "settings": {"language": "zh_CN", "gameDir": game_dir},
            "version": 3,
        })


def _find_new_version(game_dir, mc_version, started, loader):
    best = None
    vdir = os.path.join(game_dir, "versions")
    if not os.path.isdir(vdir):
        return None
    for name in os.listdir(vdir):
        jp = os.path.join(vdir, name, name + ".json")
        if not os.path.isfile(jp):
            continue
        try:
            if os.path.getmtime(jp) < started - 5:
                continue
            data = util.read_json(jp, {}) or {}
        except Exception:
            continue
        if data.get("inheritsFrom") != mc_version:
            continue
        if loader == "forge" and "forge" not in name.lower():
            continue
        if loader == "neoforge" and "neoforge" not in name.lower():
            continue
        best = name
    return best


def install_loader(game_dir, mc_version, loader, loader_version, java_exe, status=None, progress=None):
    """运行官方安装器，返回安装出的版本 id"""
    status = status or (lambda s: None)
    progress = progress or (lambda f: None)
    _ensure_launcher_profiles(game_dir)
    jar = _download_installer(loader, mc_version, loader_version, status)
    progress(0.25)

    status("运行 %s 安装器（会下载依赖库，可能需要几分钟）" % loader.capitalize())
    flags = 0x08000000 if sys.platform.startswith("win") else 0
    proc = subprocess.Popen(
        [java_exe, "-jar", jar, "--installClient", game_dir],
        cwd=game_dir, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace",
        creationflags=flags,
    )
    started = time.time()
    last_report = 0.0
    tail = []
    for line in proc.stdout:
        line = line.strip()
        if not line:
            continue
        tail.append(line)
        tail = tail[-6:]
        now = time.time()
        if now - last_report > 1.5:
            status("%s 安装器：%s" % (loader.capitalize(), line[:110]))
            last_report = now
    code = proc.wait()
    if code != 0:
        raise IOError("%s 安装器退出码 %s\n%s" % (loader.capitalize(), code, "\n".join(tail)))

    vid = _find_new_version(game_dir, mc_version, started, loader)
    if not vid:
        raise IOError("安装器运行完成，但没有找到生成的 %s 版本" % loader)
    progress(1.0)
    status("%s 安装完成：%s" % (loader.capitalize(), vid))
    return vid


def detect_loader(version_json):
    """从版本 json 判断加载器类型，返回 fabric / forge / neoforge / quilt / vanilla"""
    name = str((version_json or {}).get("id", "")).lower()
    main = str((version_json or {}).get("mainClass", "")).lower()
    if "quilt" in name:
        return "quilt"
    if "fabric" in name or "knotclient" in main:
        return "fabric"
    if "neoforge" in name or "bootstraplauncher" in main and "neo" in name:
        return "neoforge"
    if "forge" in name:
        return "forge"
    return "vanilla"
