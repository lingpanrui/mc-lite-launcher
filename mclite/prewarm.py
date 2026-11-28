# -*- coding: utf-8 -*-
"""启动预热缓存（批次5）

上次退出后异步跑 doctor.inspect 并把结果缓存到实例目录 `.mclite-prewarm.json`；
点启动时优先读缓存，命中即跳过现算体检。

缓存结构：
{
  "cache_version": 1,
  "launcher": "1.7.0",
  "vid": "1.20.1",
  "cached_at": 1795...,
  "fingerprint": { ... 关键文件/目录的 mtime+size/计数 ... },
  "inspect": { ...doctor.inspect 结果... }
}

失效条件（fingerprint 任一变化即失效，另提供显式 invalidate）：
- 版本 json（versions/<vid>/<vid>.json）mtime/size 变化；
- 根客户端 jar（versions/<root>/<root>.jar）mtime/size 变化；
- 资源索引 json mtime/size 变化；
- Java 可执行文件路径/大小/mtime 变化（不可执行也记入）；
- mods / resourcepacks / shaderpacks / datapacks / saves 目录文件数、最大 mtime、总大小变化
  （内容增删、启用禁用改名都会改变目录项或 mtime）；
- libraries 目录文件数、最大 mtime、总大小变化（缺库/补库即变）。
实例切换按 game_dir 隔离缓存，不会串用；重装版本、内容增删后调用 invalidate() 显式清缓存。
"""
import json
import os
import threading
import time

from . import util

CACHE_NAME = ".mclite-prewarm.json"
CACHE_VERSION = 1
WATCH_DIRS = ("mods", "resourcepacks", "shaderpacks", "datapacks", "saves", "libraries")


def cache_path(game_dir):
    return os.path.join(game_dir, CACHE_NAME)


def _file_sig(path):
    try:
        st = os.stat(path)
        return {"mtime": int(st.st_mtime), "size": st.st_size}
    except OSError:
        return None


def _dir_sig(path):
    """目录摘要：文件数 + 最大 mtime + 总大小（轻量遍历，不读文件内容）。"""
    count = 0
    max_mtime = 0
    total = 0
    if not os.path.isdir(path):
        return {"count": 0, "max_mtime": 0, "total": 0, "exists": False}
    for root, _dirs, files in os.walk(path):
        for fn in files:
            try:
                st = os.stat(os.path.join(root, fn))
            except OSError:
                continue
            count += 1
            total += st.st_size
            if st.st_mtime > max_mtime:
                max_mtime = st.st_mtime
    return {"count": count, "max_mtime": int(max_mtime), "total": total, "exists": True}


def fingerprint(game_dir, vid, java_path=""):
    """计算启动前关键状态指纹（纯文件系统，不做体检）。"""
    from . import mojang

    fp = {"vid": vid, "files": {}, "dirs": {}, "java": None, "root_id": ""}
    vj_path = os.path.join(game_dir, "versions", vid, vid + ".json")
    fp["files"]["version_json"] = _file_sig(vj_path)

    root_id = vid
    asset_index_id = ""
    try:
        vj, root_id = mojang.resolve_version(game_dir, vid)
        fp["root_id"] = root_id
        asset_index_id = (vj.get("assetIndex") or {}).get("id") or vj.get("assets") or ""
    except Exception:
        pass

    root_jar = os.path.join(game_dir, "versions", root_id, root_id + ".jar")
    fp["files"]["client_jar"] = _file_sig(root_jar)

    if asset_index_id:
        idx = os.path.join(game_dir, "assets", "indexes", asset_index_id + ".json")
        fp["files"]["asset_index"] = _file_sig(idx)

    if java_path:
        fp["java"] = _file_sig(java_path)
        fp["java_exists"] = os.path.isfile(java_path)

    for d in WATCH_DIRS:
        fp["dirs"][d] = _dir_sig(os.path.join(game_dir, d))
    return fp


def _read_cache(game_dir):
    return util.read_json(cache_path(game_dir), {}) or {}


def _write_cache(game_dir, vid, fp, info):
    payload = {
        "cache_version": CACHE_VERSION,
        "launcher": "1.7.0",
        "vid": vid,
        "cached_at": time.time(),
        "fingerprint": fp,
        "inspect": info,
    }
    try:
        util.write_json(cache_path(game_dir), payload)
        return True
    except Exception:
        return False


def inspect_cached(game_dir, vid, java_path="", force=False):
    """返回 (info, cached)。命中缓存 cached=True；否则现算 doctor.inspect 并写缓存。"""
    from . import doctor

    fp = fingerprint(game_dir, vid, java_path)
    if not force:
        cache = _read_cache(game_dir)
        if (cache.get("cache_version") == CACHE_VERSION and cache.get("vid") == vid
                and cache.get("fingerprint") == fp and isinstance(cache.get("inspect"), dict)):
            info = dict(cache["inspect"])
            info["cached"] = True
            info["cached_at"] = cache.get("cached_at")
            return info, True

    info = doctor.inspect(game_dir, vid)
    info["cached"] = False
    _write_cache(game_dir, vid, fp, info)
    return info, False


def invalidate(game_dir, vid=None):
    """显式失效：删除预热缓存（vid 仅用于日志/未来按版本细分）。"""
    p = cache_path(game_dir)
    try:
        if os.path.isfile(p):
            os.remove(p)
            return True
    except OSError:
        pass
    return False


def warm_async(game_dir, vid, java_path=""):
    """后台线程异步预热（上次退出后 / 启动后调用），不阻塞 UI。返回线程对象。"""
    if not game_dir or not vid:
        return None

    def _job():
        try:
            inspect_cached(game_dir, vid, java_path, force=True)
        except Exception:
            pass

    th = threading.Thread(target=_job, daemon=True)
    th.start()
    return th
