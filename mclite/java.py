# -*- coding: utf-8 -*-
"""Java 运行时检测与自动下载（Adoptium Temurin）"""
import glob
import os
import platform
import re
import shutil
import subprocess
import sys

from . import util


def _candidate_roots():
    roots = []
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    local = os.environ.get("LOCALAPPDATA", "")
    patterns = []
    if sys.platform.startswith("win"):
        patterns += [
            os.path.join(pf, "Java", "*"),
            os.path.join(pf86, "Java", "*"),
            os.path.join(pf, "Eclipse Adoptium", "*"),
            os.path.join(pf, "Eclipse Foundation", "*"),
            os.path.join(pf, "Microsoft", "jdk*"),
            os.path.join(pf, "Zulu", "*"),
            os.path.join(pf, "BellSoft", "*"),
            os.path.join(pf, "Amazon Corretto", "*"),
            os.path.join(pf, "Semeru", "*"),
            os.path.join(local, "Programs", "Eclipse Adoptium", "*"),
            os.path.join(local, "Programs", "Microsoft", "jdk*"),
            os.path.join(local, "Programs", "Java", "*"),
            os.path.join(os.path.expanduser("~"), ".jdks", "*"),
            os.path.join(util.app_root(), "java", "*"),
        ]
    else:
        patterns += [
            "/usr/lib/jvm/*",
            "/Library/Java/JavaVirtualMachines/*/Contents/Home",
            os.path.join(util.app_root(), "java", "*"),
        ]
    jh = os.environ.get("JAVA_HOME")
    if jh:
        roots.append(jh)
    for p in patterns:
        roots += [x for x in glob.glob(p) if os.path.isdir(x)]
    return roots


def _java_exe(root):
    if sys.platform.startswith("win"):
        p = os.path.join(root, "bin", "java.exe")
    else:
        p = os.path.join(root, "bin", "java")
    return p if os.path.isfile(p) else None


def java_major(exe):
    root = os.path.dirname(os.path.dirname(exe))
    release = os.path.join(root, "release")
    if os.path.isfile(release):
        try:
            with open(release, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if line.startswith("JAVA_VERSION="):
                        ver = line.split("=", 1)[1].strip().strip('"')
                        if ver.startswith("1."):
                            return int(ver.split(".")[1]), ver
                        return int(re.match(r"(\d+)", ver).group(1)), ver
        except Exception:
            pass
    try:
        out = subprocess.run([exe, "-version"], capture_output=True, text=True, timeout=15,
                             creationflags=0x08000000 if sys.platform.startswith("win") else 0)
        text = (out.stderr or "") + (out.stdout or "")
        m = re.search(r'version "([^"]+)"', text)
        if m:
            ver = m.group(1)
            if ver.startswith("1."):
                return int(ver.split(".")[1]), ver
            return int(re.match(r"(\d+)", ver).group(1)), ver
    except Exception:
        pass
    return 0, "?"


def find_javas():
    """扫描本机 Java，按主版本排序返回 [{"path","major","version","root"}]"""
    seen = set()
    result = []
    exe_which = shutil.which("java")
    if exe_which:
        roots = [os.path.dirname(os.path.dirname(exe_which))]
    else:
        roots = []
    roots += _candidate_roots()
    for root in roots:
        exe = _java_exe(root)
        if not exe:
            continue
        key = os.path.normcase(os.path.abspath(exe))
        if key in seen:
            continue
        seen.add(key)
        major, ver = java_major(exe)
        if major <= 0:
            continue
        result.append({"path": exe, "major": major, "version": ver, "root": root})
    result.sort(key=lambda x: (-x["major"], x["path"]))
    return result


def pick_java(required_major, all_javas=None, preferred=""):
    """按版本匹配 Java：优先精确匹配，其次 17+ 允许更高版本"""
    if preferred and os.path.isfile(preferred):
        maj, _ = java_major(preferred)
        if maj == required_major:
            return preferred
        if required_major >= 17 and maj >= required_major:
            return preferred
    javas = all_javas if all_javas is not None else find_javas()
    exact = [j for j in javas if j["major"] == required_major]
    if exact:
        return exact[0]["path"]
    if required_major >= 17:
        higher = sorted([j for j in javas if j["major"] >= required_major], key=lambda x: x["major"])
        if higher:
            return higher[0]["path"]
    return None


def _download_link(major):
    arch = "arm64" if platform.machine().lower() in ("arm64", "aarch64") else "x64"
    api = (
        "https://api.adoptium.net/v3/assets/latest/%s/hotspot?architecture=%s&image_type=jdk&os=%s&vendor=eclipse"
        % (major, arch, "windows" if sys.platform.startswith("win") else ("mac" if sys.platform == "darwin" else "linux"))
    )
    data = util.http_json(api)
    if not data:
        raise IOError("Adoptium 上没有 Java %s 的安装包" % major)
    pkg = (data[0].get("binary") or {}).get("package") or {}
    if not pkg.get("link"):
        raise IOError("没有找到 Java %s 的下载链接" % major)
    return pkg["link"], pkg.get("name") or ("jdk%s.zip" % major), pkg.get("size") or 0


def download_jdk(major, status=None, progress=None):
    """下载 Temurin JDK 并解压，返回 java 可执行文件路径"""
    status = status or (lambda s: None)
    progress = progress or (lambda f: None)
    status("正在获取 Java %s 下载地址" % major)
    link, name, size = _download_link(major)
    java_root = os.path.join(util.app_root(), "java")
    os.makedirs(java_root, exist_ok=True)
    archive = os.path.join(java_root, name)
    if not util.file_ok(archive, size or None, None):
        status("下载 Java %s（%s）" % (major, util.human_size(size) if size else "未知大小"))
        util.download_file(link, archive,
                           on_bytes=lambda got, total: progress(min(0.85, got / total) if total else 0.3),
                           desc="Java %s" % major)
    progress(0.9)
    status("解压 Java %s" % major)
    extract_root = os.path.join(java_root, "temurin-%s" % major)
    if os.path.isdir(extract_root):
        shutil.rmtree(extract_root, ignore_errors=True)
    os.makedirs(extract_root, exist_ok=True)
    util.safe_extract_zip(archive, extract_root, skip_prefix=())
    exe = _find_extracted_java(extract_root)
    if not exe:
        raise IOError("Java 解压后找不到 java 可执行文件")
    progress(1.0)
    status("Java %s 已安装" % major)
    return exe


def _find_extracted_java(root):
    direct = _java_exe(root)
    if direct:
        return direct
    for dirpath, dirnames, filenames in os.walk(root):
        if os.path.basename(dirpath) == "bin" and ("java.exe" in filenames or "java" in filenames):
            return os.path.join(dirpath, "java.exe" if sys.platform.startswith("win") else "java")
    return None


def ensure_java(required_major, preferred="", status=None, progress=None, allow_download=True):
    """保证有可用的 Java，返回 java.exe 路径"""
    status = status or (lambda s: None)
    found = pick_java(required_major, preferred=preferred)
    if found:
        return found
    if not allow_download:
        raise RuntimeError("需要 Java %s，但本机没有找到" % required_major)
    status("本机缺少 Java %s，准备自动下载" % required_major)
    return download_jdk(required_major, status=status, progress=progress)
