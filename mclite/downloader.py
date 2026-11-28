# -*- coding: utf-8 -*-
"""多线程分片下载 + 官方 / BMCLAPI 双源 + 断点续传（批次5）

设计要点（均为实测口径，见 _progress.md 批次5）：
- 官方源：piston-data.mojang.com / resources.download.minecraft.net / libraries.minecraft.net
- BMCLAPI2 实测可用模板（2026-11 本机探测，均支持 Range 206）：
  * 客户端 jar：https://bmclapi2.bangbang93.com/version/{mc_version}/client
  * Maven 库：  https://bmclapi2.bangbang93.com/maven/{maven 相对路径}
  * 资源对象：  https://bmclapi2.bangbang93.com/assets/{hash 前两位}/{hash}
  * 版本 json：https://bmclapi2.bangbang93.com/version/{mc_version}/json
  版本清单 /mc/game/version_manifest_v2.json 本机偶发 ConnectionReset，故清单仍走官方，
  文件下载在 auto 模式下官方失败自动回退 BMCL。
- 分片：Range 并发（线程池），每片落 dest.part{i}，片段清单 dest.parts.json；
  重启进程后已完成且大小正确的片段直接跳过（断点续传），全部完成后顺序拼接 + sha1 校验。
- 不支持 Range 或文件过小则退化为单流下载（.part 追加续传，尽力而为）。
"""
import hashlib
import json
import os
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from . import util

BMCL_BASE = "https://bmclapi2.bangbang93.com"
CHUNK_MIN = 2 * 1024 * 1024      # 小于 2MB 不分片
DEFAULT_THREADS = 8
_CHUNK_RETRIES = 5


# ---------------------------------------------------------------- 源映射
def bmcl_asset_url(official_url):
    """resources.download.minecraft.net/{hh}/{hash} -> BMCL /assets/{hh}/{hash}"""
    u = str(official_url or "")
    if "resources.download.minecraft.net" in u:
        tail = u.split("resources.download.minecraft.net", 1)[1].lstrip("/")
        if tail:
            return BMCL_BASE + "/assets/" + tail
    if "piston-data.mojang.com" in u and "/objects/" in u:
        # piston 对象 URL 末段即 hash，资源对象也可走 /assets/
        h = u.rstrip("/").split("/")[-1]
        if len(h) >= 2:
            return BMCL_BASE + "/assets/%s/%s" % (h[:2], h)
    return None


def bmcl_maven_url(official_url):
    """libraries.minecraft.net/{path} -> BMCL /maven/{path}"""
    u = str(official_url or "")
    if "libraries.minecraft.net" in u and "/maven/" not in u:
        tail = u.split("libraries.minecraft.net", 1)[1].lstrip("/")
        return BMCL_BASE + "/maven/" + tail
    if "libraries.minecraft.net" in u and "/maven/" in u:
        tail = u.split("/maven/", 1)[1]
        return BMCL_BASE + "/maven/" + tail
    return None


def bmcl_client_url(mc_version):
    return "%s/version/%s/client" % (BMCL_BASE, mc_version)


def candidate_urls(url, source="auto", bmcl_url=None):
    """按 source 生成有序候选 URL（去重）。source: official / bmcl / auto。"""
    url = str(url or "")
    bmcl_url = bmcl_url or None
    if source == "official":
        out = [url]
    elif source == "bmcl":
        out = [bmcl_url or url]
    else:  # auto：官方优先，失败回退 BMCL
        out = [url]
        if bmcl_url and bmcl_url != url:
            out.append(bmcl_url)
    seen, res = set(), []
    for u in out:
        if u and u not in seen:
            seen.add(u)
            res.append(u)
    return res


# ---------------------------------------------------------------- 探测
def _open_range(url, start, end, timeout=30):
    req = urllib.request.Request(
        url, headers={"User-Agent": util.USER_AGENT, "Range": "bytes=%d-%d" % (start, end)}
    )
    return urllib.request.urlopen(req, timeout=timeout)


def range_probe(url, timeout=30):
    """返回 (supported, total_size)。supported=True 表示服务器接受 Range 并返回 206。"""
    try:
        with _open_range(url, 0, 0, timeout) as resp:
            if getattr(resp, "status", 200) != 206:
                return False, 0
            cr = resp.headers.get("Content-Range") or ""
            total = 0
            if "/" in cr:
                try:
                    total = int(cr.rsplit("/", 1)[1])
                except ValueError:
                    total = 0
            if not total:
                cl = resp.headers.get("Content-Length")
                total = int(cl) if cl else 0
            return True, total
    except Exception:
        return False, 0


# ---------------------------------------------------------------- 分片
def _read_manifest(manifest_path):
    return util.read_json(manifest_path, {}) or {}


def _write_manifest(manifest_path, data):
    util.write_json(manifest_path, data)


def _download_chunk(url, idx, start, end, part_path, lock, done_bytes, total, on_progress, timeout):
    expect_len = end - start + 1
    if os.path.isfile(part_path) and os.path.getsize(part_path) == expect_len:
        with lock:
            done_bytes[0] += expect_len
            if on_progress:
                on_progress(done_bytes[0], total)
        return idx, True
    last_err = None
    for attempt in range(_CHUNK_RETRIES):
        try:
            with _open_range(url, start, end, timeout) as resp, open(part_path, "wb") as f:
                while True:
                    buf = resp.read(256 * 1024)
                    if not buf:
                        break
                    f.write(buf)
            if os.path.getsize(part_path) != expect_len:
                raise IOError("片段大小不符：%d != %d" % (os.path.getsize(part_path), expect_len))
            with lock:
                done_bytes[0] += expect_len
                if on_progress:
                    on_progress(done_bytes[0], total)
            return idx, True
        except Exception as e:  # 重试该片段
            last_err = e
            msg = str(e)
            # 429/5xx 退避更久并加抖动，避免并发分片同时重试打爆源站
            base = 2.0 if ("429" in msg or "503" in msg or "502" in msg) else 0.6
            time.sleep(base * (attempt + 1) + (idx % 3) * 0.25)
    raise IOError("分片 %d 下载失败：%s" % (idx, last_err))


def _sharded(url, dest, total, threads, on_progress, timeout):
    threads = max(1, int(threads or DEFAULT_THREADS))
    n = min(threads, max(1, (total + CHUNK_MIN - 1) // CHUNK_MIN))
    chunk = (total + n - 1) // n
    ranges = []
    for i in range(n):
        s = i * chunk
        e = min(total - 1, s + chunk - 1)
        ranges.append([s, e])

    manifest_path = dest + ".parts.json"
    man = _read_manifest(manifest_path)
    if man.get("url") != url or int(man.get("total") or 0) != total or len(man.get("ranges") or []) != n:
        man = {"url": url, "total": total, "ranges": ranges, "threads": threads}
        _write_manifest(manifest_path, man)

    done_bytes = [0]
    # 已存在片段计入进度
    for i, (s, e) in enumerate(ranges):
        pp = "%s.part%d" % (dest, i)
        if os.path.isfile(pp) and os.path.getsize(pp) == (e - s + 1):
            done_bytes[0] += (e - s + 1)
    if on_progress:
        on_progress(done_bytes[0], total)

    lock = threading.Lock()
    with ThreadPoolExecutor(max_workers=n) as ex:
        futs = [
            ex.submit(_download_chunk, url, i, s, e, "%s.part%d" % (dest, i),
                      lock, done_bytes, total, on_progress, timeout)
            for i, (s, e) in enumerate(ranges)
        ]
        for f in futs:
            f.result()  # 抛错即整体失败

    # 顺序拼接
    tmp = dest + ".tmp"
    with open(tmp, "wb") as out:
        for i in range(n):
            pp = "%s.part%d" % (dest, i)
            with open(pp, "rb") as src:
                while True:
                    buf = src.read(1024 * 1024)
                    if not buf:
                        break
                    out.write(buf)
    os.replace(tmp, dest)
    for i in range(n):
        try:
            os.remove("%s.part%d" % (dest, i))
        except OSError:
            pass
    try:
        os.remove(manifest_path)
    except OSError:
        pass
    return dest


def _single(url, dest, on_progress, timeout):
    """单流下载，.part 断点追加（服务器支持 Range 时）。"""
    part = dest + ".part"
    have = os.path.getsize(part) if os.path.isfile(part) else 0
    headers = {"User-Agent": util.USER_AGENT}
    if have:
        headers["Range"] = "bytes=%d-" % have
    req = urllib.request.Request(url, headers=headers)
    mode = "ab" if have else "wb"
    with urllib.request.urlopen(req, timeout=timeout) as resp, open(part, mode) as f:
        total = int(resp.headers.get("Content-Length") or 0) + have
        got = have
        if on_progress:
            on_progress(got, total)
        while True:
            buf = resp.read(256 * 1024)
            if not buf:
                break
            f.write(buf)
            got += len(buf)
            if on_progress:
                on_progress(got, total)
    os.replace(part, dest)
    return dest


def _fetch_one(url, dest, expected_sha1, threads, on_progress, timeout):
    os.makedirs(os.path.dirname(os.path.abspath(dest)) or ".", exist_ok=True)
    supported, total = range_probe(url, timeout=timeout)
    if supported and total >= CHUNK_MIN and threads > 1:
        _sharded(url, dest, total, threads, on_progress, timeout)
    else:
        _single(url, dest, on_progress, timeout)
    if expected_sha1:
        h = hashlib.sha1()
        with open(dest, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        if h.hexdigest().lower() != str(expected_sha1).lower():
            raise IOError("sha1 校验失败：%s" % dest)
    return dest


def fetch(url, dest, expected_sha1=None, threads=DEFAULT_THREADS, source="auto",
          bmcl_url=None, on_progress=None, timeout=30, desc=""):
    """按 source 选源并下载；auto 模式官方失败自动回退 BMCL。全部候选失败抛最后一个异常。"""
    candidates = candidate_urls(url, source=source, bmcl_url=bmcl_url)
    last_err = None
    for i, cand in enumerate(candidates):
        try:
            return _fetch_one(cand, dest, expected_sha1, threads, on_progress, timeout)
        except Exception as e:
            last_err = e
            # 失败源的半成品片段保留，便于换源/重试续传；继续下一个候选
            if on_progress:
                on_progress(0, 0)
    raise IOError("下载失败 %s%s：%s" % (desc and desc + " ", url, last_err))


def benchmark(url, dest, threads=1, expected_sha1=None, timeout=60):
    """真实测速：单线程 vs 多线程。返回耗时/字节/吞吐。"""
    t0 = time.time()
    fetch(url, dest, expected_sha1=expected_sha1, threads=threads, source="official",
          on_progress=None, timeout=timeout)
    secs = time.time() - t0
    size = os.path.getsize(dest)
    return {"threads": threads, "seconds": round(secs, 3), "bytes": size,
            "mbps": round(size / 1024 / 1024 / max(secs, 1e-6), 2)}
