# -*- coding: utf-8 -*-
"""基岩版：客户端检测 / 启动，基岩版专用服务器（BDS）多版本下载"""
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request

from . import util

BDS_PAGE = "https://www.minecraft.net/en-us/download/server/bedrock"
LINKS_API = "https://net-secondary.web.minecraft-services.net/api/v1.0/download/links"
BDS_BASE = "https://www.minecraft.net/bedrockdedicatedserver/bin-win/"


# --------------------------------------------------------------------------- #
# 客户端
# --------------------------------------------------------------------------- #
def _ps(command):
    flags = 0x08000000 if sys.platform.startswith("win") else 0
    out = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True, text=True, timeout=30, creationflags=flags,
        encoding="utf-8", errors="ignore",
    )
    return (out.stdout or "").strip()


def installed_clients():
    """返回已安装的基岩版客户端列表 [{"name","pfn","version"}]"""
    if not sys.platform.startswith("win"):
        return []
    try:
        raw = _ps(
            "Get-AppxPackage | Where-Object {$_.Name -like '*Minecraft*'} | "
            "Select-Object Name,PackageFamilyName,Version | ConvertTo-Json -Compress"
        )
        if not raw:
            return []
        data = json.loads(raw)
        if isinstance(data, dict):
            data = [data]
        result = []
        for item in data:
            pfn = item.get("PackageFamilyName") or ""
            if not pfn:
                continue
            result.append({
                "name": (item.get("Name") or ""),
                "label": "Minecraft 预览版" if "Beta" in (item.get("Name") or "") else "Minecraft 正式版",
                "preview": "Beta" in (item.get("Name") or ""),
                "pfn": pfn,
                "version": str(item.get("Version") or ""),
            })
        return result
    except Exception:
        return []


def protocol_registered():
    if not sys.platform.startswith("win"):
        return False
    try:
        import winreg
        winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "minecraft").Close()
        return True
    except Exception:
        return False


def launch_client(pfn=None):
    """启动基岩版：优先 AppsFolder，其次 URI 协议"""
    if pfn:
        try:
            subprocess.Popen(["explorer.exe", "shell:appsFolder\\%s!App" % pfn],
                             creationflags=0x08000000)
            return "appsFolder"
        except Exception:
            pass
    os.startfile("minecraft://")
    return "protocol"


# --------------------------------------------------------------------------- #
# 服务端版本
# --------------------------------------------------------------------------- #
def _ver_key(ver):
    parts = re.findall(r"\d+", ver)
    return tuple(int(x) for x in parts[:4]) if parts else (0,)


def _version_from_filename(name):
    m = re.search(r"bedrock-server-([0-9][0-9.]*)\.zip", name)
    return m.group(1) if m else name


def available_versions():
    """官方下载 API 里当前可用的服务端版本：[{version,kind,url,filename}]"""
    data = util.http_json(LINKS_API, timeout=30)
    items = []
    for link in (data.get("result") or {}).get("links") or []:
        dtype = link.get("downloadType")
        if dtype == "serverBedrockWindows":
            kind = "正式版"
        elif dtype == "serverBedrockPreviewWindows":
            kind = "预览版"
        else:
            continue
        url = link.get("downloadUrl") or ""
        name = url.rsplit("/", 1)[-1]
        items.append({
            "version": _version_from_filename(name),
            "kind": kind,
            "url": url,
            "filename": name,
        })
    items.sort(key=lambda x: (x["kind"] != "正式版", _ver_key(x["version"])), reverse=False)
    return items


def probe_version(version):
    """按版本号校验官方下载地址是否存在，返回 (url, filename, size)

    正式版在 bin-win，预览版在 bin-win-preview；两个位置都会尝试。
    """
    version = version.strip().lstrip("v")
    if not re.fullmatch(r"[0-9][0-9.]*", version):
        raise ValueError("版本号格式不正确，例如 1.21.51.02")
    last_err = None
    for base in (BDS_BASE, BDS_BASE.replace("bin-win/", "bin-win-preview/")):
        url = base + "bedrock-server-%s.zip" % version
        req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": util.USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=25) as resp:
                size = int(resp.headers.get("Content-Length") or 0)
                if resp.status == 200:
                    return url, "bedrock-server-%s.zip" % version, size
        except Exception as e:
            last_err = e
    raise IOError("官方没有找到该版本（%s）：%s" % (version, last_err))


def servers_root():
    return os.path.join(util.app_root(), "bedrock", "servers")


def server_dir(version):
    return os.path.join(servers_root(), version)


def download_server_version(version, url, filename, status=None, progress=None):
    """下载并解压指定版本 BDS，返回 bedrock_server.exe 路径"""
    status = status or (lambda s: None)
    progress = progress or (lambda f: None)
    target = server_dir(version)
    exe = os.path.join(target, "bedrock_server.exe")
    if os.path.isfile(exe):
        status("版本 %s 已存在，直接使用" % version)
        progress(1.0)
        return exe, version

    cache = os.path.join(util.app_root(), "bedrock", "cache")
    os.makedirs(cache, exist_ok=True)
    archive = os.path.join(cache, filename)
    if not os.path.isfile(archive) or os.path.getsize(archive) == 0:
        status("下载基岩版服务端 %s" % version)
        util.download_file(url, archive,
                           on_bytes=lambda got, total: progress(min(0.85, got / total) if total else 0.3),
                           desc="基岩版服务端 %s" % version)
    status("解压服务端 %s" % version)
    if os.path.isdir(target):
        shutil.rmtree(target, ignore_errors=True)
    os.makedirs(target, exist_ok=True)
    util.safe_extract_zip(archive, target, skip_prefix=())
    if not os.path.isfile(exe):
        raise IOError("解压后没有找到 bedrock_server.exe")
    util.write_json(os.path.join(target, "mclite-version.json"),
                    {"version": version, "url": url, "filename": filename, "time": time.time()})
    progress(1.0)
    status("服务端 %s 已就绪" % version)
    return exe, version


def list_installed_servers():
    root = servers_root()
    if not os.path.isdir(root):
        return []
    items = []
    for name in os.listdir(root):
        path = os.path.join(root, name)
        exe = os.path.join(path, "bedrock_server.exe")
        if os.path.isfile(exe):
            items.append({"version": name, "path": path, "exe": exe})
    items.sort(key=lambda x: _ver_key(x["version"]), reverse=True)
    return items


def remove_server(path):
    shutil.rmtree(path, ignore_errors=True)


def run_server(exe):
    """在新控制台窗口中启动 BDS（首次运行需在窗口里输入同意 EULA）"""
    subprocess.Popen(
        ["cmd", "/k", exe],
        cwd=os.path.dirname(exe),
        creationflags=0x00000010,  # CREATE_NEW_CONSOLE
    )
    return os.path.dirname(exe)
