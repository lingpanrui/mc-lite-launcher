# -*- coding: utf-8 -*-
"""联机：局域网端口检测 + bore 免费公网隧道（Java 版）"""
import os
import re
import socket
import subprocess
import sys
import threading

from . import util

BORE_API = "https://api.github.com/repos/ekzhang/bore/releases/latest"
BORE_SERVER = "bore.pub"


def bore_path():
    return os.path.join(util.app_root(), "tools", "bore", "bore.exe")


def ensure_bore(status=None, progress=None):
    """确保 bore.exe 存在，缺失则从 GitHub 下载（约 0.7MB）"""
    status = status or (lambda s: None)
    progress = progress or (lambda f: None)
    exe = bore_path()
    if os.path.isfile(exe):
        return exe
    status("下载联机组件 bore")
    release = util.http_json(BORE_API)
    asset = None
    for item in release.get("assets") or []:
        if "x86_64-pc-windows-msvc.zip" in (item.get("name") or ""):
            asset = item
            break
    if not asset:
        raise IOError("没有找到适用于 Windows 的 bore 发布包")
    target_dir = os.path.dirname(exe)
    os.makedirs(target_dir, exist_ok=True)
    archive = os.path.join(target_dir, "bore.zip")
    util.download_file(asset["browser_download_url"], archive,
                       on_bytes=lambda got, total: progress(min(0.9, got / total) if total else 0.4),
                       desc="联机组件")
    util.safe_extract_zip(archive, target_dir, skip_prefix=())
    if not os.path.isfile(exe):
        for root, _, files in os.walk(target_dir):
            if "bore.exe" in files:
                exe = os.path.join(root, "bore.exe")
                break
    if not os.path.isfile(exe):
        raise IOError("联机组件解压失败：找不到 bore.exe")
    progress(1.0)
    status("联机组件已就绪")
    return exe


def detect_lan_port(game_dir):
    """从游戏日志里读“对局域网开放”的端口"""
    logs_dir = os.path.join(game_dir, "logs")
    candidates = []
    latest = os.path.join(logs_dir, "latest.log")
    if os.path.isfile(latest):
        candidates.append(latest)
    if os.path.isdir(logs_dir):
        others = []
        for name in os.listdir(logs_dir):
            if name.endswith(".log") or name.endswith(".log.gz"):
                p = os.path.join(logs_dir, name)
                others.append((os.path.getmtime(p), p))
        others.sort(reverse=True)
        candidates += [p for _, p in others[:5]]
    for path in candidates:
        if path.endswith(".gz"):
            continue
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                f.seek(0, os.SEEK_END)
                size = f.tell()
                f.seek(max(0, size - 300 * 1024))
                text = f.read()
        except Exception:
            continue
        ports = re.findall(r"Local game hosted on port (\d{2,5})", text)
        if ports:
            return int(ports[-1]), path
    return None, None


def local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def start_bore(port, on_line, on_address=None):
    """启动 bore 隧道，返回 Popen；on_address 收到 bore.pub:端口"""
    exe = ensure_bore()
    flags = 0x08000000 if sys.platform.startswith("win") else 0
    proc = subprocess.Popen(
        [exe, "local", str(int(port)), "--to", BORE_SERVER],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
        text=True, encoding="utf-8", errors="replace", creationflags=flags,
    )

    def reader():
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            if on_line:
                on_line(line)
            m = re.search(r"listening at ([A-Za-z0-9._-]+:\d+)", line)
            if m and on_address:
                on_address(m.group(1))
    threading.Thread(target=reader, daemon=True).start()
    return proc


def stop_bore(proc):
    if not proc:
        return
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def udp_note():
    return "bore 只支持 TCP：Java 版可用；基岩版联机需要 UDP，请用同一局域网或专用服务器。"
