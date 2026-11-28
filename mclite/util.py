# -*- coding: utf-8 -*-
"""通用工具：配置、HTTP、文件下载、校验"""
import hashlib
import json
import os
import shutil
import ssl
import time
import urllib.error
import urllib.request
import zipfile

USER_AGENT = "MCLite/1.0 (Minecraft Launcher; Windows)"
APP_NAME = "MC Lite 启动器"


def app_root():
    """启动器数据根目录（配置、Java、基岩服务端）"""
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, "MCLite")


CONFIG_PATH = os.path.join(app_root(), "config.json")

DEFAULT_CONFIG = {
    "game_dir": os.path.join(app_root(), "game"),
    "java_path": "",
    "memory_mb": 4096,
    "username": "Steve",
    "width": 854,
    "height": 480,
    "last_version": "",
    "close_after_launch": True,
    "authlib_api": "https://littleskin.cn/api/yggdrasil",
    "msa_client_id": "",
    # v1.3.0 实例系统（见 _CONVENTIONS.md §6）
    "instances": [],
    "current_instance": "default",
    "instance_root": os.path.join(app_root(), "instances"),
    "jvm_args": "",
    # v1.4.0 账户系统（离线 / 外置 / 微软）
    "accounts": [],
    "current_account": "",
    # v1.7.0 下载源：auto=官方优先失败回退 BMCL；official / bmcl 强制单源
    "download_source": "auto",
}


def load_config():
    os.makedirs(app_root(), exist_ok=True)
    cfg = dict(DEFAULT_CONFIG)
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f) or {}
        cfg.update(data)
    except Exception:
        pass
    for k, v in DEFAULT_CONFIG.items():
        cfg.setdefault(k, v)
    return cfg


def save_config(cfg):
    os.makedirs(app_root(), exist_ok=True)
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CONFIG_PATH)


def write_json(path, data):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def read_json(path, default=None):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def http_get(url, timeout=25, headers=None):
    req = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "*/*", **(headers or {})}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def http_text(url, timeout=25):
    raw = http_get(url, timeout)
    # 站点可能是 utf-8 或 gbk
    for enc in ("utf-8", "gbk"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "ignore")


def http_json(url, timeout=25):
    return json.loads(http_get(url, timeout).decode("utf-8"))


def file_ok(path, size=None, sha1=None):
    if not os.path.isfile(path):
        return False
    if size is not None and os.path.getsize(path) != int(size):
        return False
    if sha1:
        h = hashlib.sha1()
        try:
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(1024 * 1024), b""):
                    h.update(chunk)
        except Exception:
            return False
        return h.hexdigest().lower() == str(sha1).lower()
    return True


def download_file(url, dest, expected_sha1=None, on_bytes=None, retries=3, timeout=30, desc=""):
    """断点重下 + sha1 校验的下载函数"""
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    tmp = dest + ".part"
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            h = hashlib.sha1()
            got = 0
            with urllib.request.urlopen(req, timeout=timeout) as resp, open(tmp, "wb") as f:
                total = int(resp.headers.get("Content-Length") or 0)
                while True:
                    chunk = resp.read(1024 * 256)
                    if not chunk:
                        break
                    f.write(chunk)
                    h.update(chunk)
                    got += len(chunk)
                    if on_bytes:
                        on_bytes(got, total)
            if expected_sha1 and h.hexdigest().lower() != str(expected_sha1).lower():
                raise IOError("文件校验失败（sha1 不匹配）")
            os.replace(tmp, dest)
            return dest
        except Exception as e:
            last_err = e
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except Exception:
                pass
            if attempt < retries - 1:
                time.sleep(0.6 * (attempt + 1))
    raise IOError("下载失败 %s%s：%s" % (desc and desc + " ", url, last_err))


def safe_extract_zip(zip_path, target_dir, skip_prefix=("META-INF/",)):
    """安全解压（阻止路径穿越，可跳过部分前缀）"""
    base = os.path.abspath(target_dir)
    os.makedirs(base, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        for name in zf.namelist():
            if name.endswith("/"):
                continue
            if any(name.startswith(p) for p in skip_prefix):
                continue
            target = os.path.abspath(os.path.join(base, name))
            if not target.startswith(base + os.sep) and target != base:
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with zf.open(name) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)


def human_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return ("%.1f %s" % (n, unit)) if unit != "B" else ("%d B" % n)
        n /= 1024.0


def open_path(path):
    os.makedirs(path, exist_ok=True)
    os.startfile(path)  # noqa: 仅 Windows
