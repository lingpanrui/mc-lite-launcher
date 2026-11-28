# -*- coding: utf-8 -*-
"""批次5 性能与入口 纯后端自测：分片下载/续传、共享池硬链接去重、预热缓存失效、CLI 解析、协议解析/单实例。

运行：python _test_perf.py
"""
import hashlib
import http.server
import os
import shutil
import socketserver
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mclite import downloader, sharedpool, prewarm, cli, protocol, util

PASSED = 0
FAILED = 0


def check(name, cond, extra=""):
    global PASSED, FAILED
    if cond:
        PASSED += 1
        print("  PASS", name)
    else:
        FAILED += 1
        print("  FAIL", name, extra)


# ---------------------------------------------------------------- 本地 Range 服务器
class RangeHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        path = self.translate_path(self.path)
        if os.path.isfile(path):
            size = os.path.getsize(path)
            rng = self.headers.get("Range")
            if rng and rng.startswith("bytes="):
                try:
                    spec = rng.split("=", 1)[1].split(",")[0]
                    a, b = spec.split("-")
                    start = int(a) if a else 0
                    end = int(b) if b else size - 1
                    end = min(end, size - 1)
                    length = end - start + 1
                    with open(path, "rb") as f:
                        f.seek(start)
                        data = f.read(length)
                    self.send_response(206)
                    self.send_header("Content-Type", "application/octet-stream")
                    self.send_header("Content-Length", str(length))
                    self.send_header("Content-Range", "bytes %d-%d/%d" % (start, end, size))
                    self.end_headers()
                    self.wfile.write(data)
                    return
                except Exception:
                    pass
        super().do_GET()

    def log_message(self, *a):
        pass


class Server:
    def __init__(self, root):
        self.httpd = socketserver.ThreadingTCPServer(("127.0.0.1", 0), RangeHandler)
        self.httpd.daemon_threads = True
        self.root = root
        os.chdir(root)
        self.port = self.httpd.server_address[1]
        self.t = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.t.start()

    def url(self, name):
        return "http://127.0.0.1:%d/%s" % (self.port, name)

    def stop(self):
        self.httpd.shutdown()


def sha1_file(p):
    h = hashlib.sha1()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def test_downloader(tmp):
    print("[downloader]")
    srv_root = os.path.join(tmp, "srv")
    os.makedirs(srv_root, exist_ok=True)
    payload = os.urandom(3 * 1024 * 1024 + 123)  # >2MB 触发分片
    src = os.path.join(srv_root, "big.bin")
    with open(src, "wb") as f:
        f.write(payload)
    want = hashlib.sha1(payload).hexdigest()
    srv = Server(srv_root)
    try:
        url = srv.url("big.bin")
        sup, total = downloader.range_probe(url)
        check("range_probe 支持且总大小正确", sup and total == len(payload), "sup=%s total=%s" % (sup, total))

        # 分片并发下载
        d1 = os.path.join(tmp, "sharded.bin")
        downloader.fetch(url, d1, expected_sha1=want, threads=4, source="official")
        check("8/4 分片下载 sha1 一致", sha1_file(d1) == want)
        check("分片临时文件已清理", not os.path.exists(d1 + ".parts.json") and not any(
            n.startswith("sharded.bin.part") for n in os.listdir(tmp)))

        # 单流断点续传：先写前 1MB 的 .part，再 threads=1 续传
        d2 = os.path.join(tmp, "resume.bin")
        with open(d2 + ".part", "wb") as f:
            f.write(payload[:1024 * 1024])
        downloader.fetch(url, d2, expected_sha1=want, threads=1, source="official")
        check("单流断点续传 sha1 一致", sha1_file(d2) == want)

        # 候选源顺序与去重
        c = downloader.candidate_urls("https://o/x", "auto", "https://b/x")
        check("auto 候选官方优先+BMCL回退", c == ["https://o/x", "https://b/x"], str(c))
        c2 = downloader.candidate_urls("https://o/x", "bmcl", "https://b/x")
        check("bmcl 强制源", c2 == ["https://b/x"], str(c2))
        c3 = downloader.candidate_urls("https://o/x", "official", None)
        check("official 单源", c3 == ["https://o/x"])

        # BMCL 映射
        check("bmcl asset 映射", downloader.bmcl_asset_url(
            "https://resources.download.minecraft.net/ab/abc123") ==
            "https://bmclapi2.bangbang93.com/assets/ab/abc123")
        check("bmcl maven 映射", downloader.bmcl_maven_url(
            "https://libraries.minecraft.net/com/x/y/1/y-1.jar") ==
            "https://bmclapi2.bangbang93.com/maven/com/x/y/1/y-1.jar")
        check("bmcl client 模板", downloader.bmcl_client_url("1.20.1").endswith("/version/1.20.1/client"))
    finally:
        srv.stop()


def test_sharedpool(tmp):
    print("[sharedpool]")
    # 隔离 app_root 到临时目录
    fake_app = os.path.join(tmp, "appdata")
    os.makedirs(fake_app, exist_ok=True)
    orig_app_root = util.app_root
    util.app_root = lambda: fake_app
    try:
        game = os.path.join(tmp, "inst1")
        os.makedirs(os.path.join(game, "assets", "objects", "ab"))
        os.makedirs(os.path.join(game, "libraries", "com"))
        with open(os.path.join(game, "assets", "objects", "ab", "a.bin"), "wb") as f:
            f.write(b"asset-data" * 100)
        with open(os.path.join(game, "libraries", "com", "x.jar"), "wb") as f:
            f.write(b"lib-data" * 100)

        # 入池硬链接（不删源）
        pool_a = sharedpool.pool_dir("assets")
        ing = sharedpool.ingest_dir(os.path.join(game, "assets"), pool_a)
        check("ingest 计数与硬链接", ing["files"] == 1 and ing["linked"] == 1, str(ing))
        check("入池不删源文件", os.path.isfile(os.path.join(game, "assets", "objects", "ab", "a.bin")))
        src_ino = os.stat(os.path.join(game, "assets", "objects", "ab", "a.bin")).st_ino
        pool_ino = os.stat(os.path.join(pool_a, "objects", "ab", "a.bin")).st_ino
        check("同卷硬链接 inode 相同", src_ino == pool_ino)

        # 正式 join：junction + 备份清理
        rep = sharedpool.join_instance(game, kinds=("assets", "libraries"))
        check("assets 接入模式为 junction", rep["kinds"]["assets"]["mode"] == "junction",
              str(rep["kinds"]["assets"]))
        check("libraries 接入模式为 junction", rep["kinds"]["libraries"]["mode"] == "junction",
              str(rep["kinds"]["libraries"]))
        check("assets 是 junction", sharedpool.is_junction(os.path.join(game, "assets")))
        check("junction 可穿透读文件",
              open(os.path.join(game, "assets", "objects", "ab", "a.bin"), "rb").read() == b"asset-data" * 100)
        leftovers = [n for n in os.listdir(game) if n.startswith("assets.__old_") or n.startswith("libraries.__old_")]
        check("备份已在校验后清理", not leftovers, str(leftovers))

        # 再次 join 幂等
        rep2 = sharedpool.join_instance(game, kinds=("assets", "libraries"))
        check("重复 join 标记 already",
              rep2["kinds"]["assets"]["mode"] == "already" and rep2["kinds"]["libraries"]["mode"] == "already")

        # 测量与节省口径：3 个实例共享同一池，无池口径=3 份独立副本
        cmp = sharedpool.compare({}, [game, game, game])
        check("有池物理占用 < 无池独立口径", cmp["with_pool_physical_bytes"] < cmp["no_pool_independent_bytes"],
              "%s vs %s" % (cmp["with_pool_physical_bytes"], cmp["no_pool_independent_bytes"]))
        check("节省百分比为正", cmp["saved_percent"] > 0, str(cmp["saved_percent"]))
        check("池唯一 inode 去重字节>0", cmp["pool_physical_unique"] > 0)
    finally:
        util.app_root = orig_app_root


def test_prewarm(tmp):
    print("[prewarm]")
    game = os.path.join(tmp, "pw")
    vdir = os.path.join(game, "versions", "1.20.1")
    os.makedirs(vdir, exist_ok=True)
    with open(os.path.join(vdir, "1.20.1.json"), "w", encoding="utf-8") as f:
        import json
        json.dump({"id": "1.20.1", "mainClass": "net.minecraft.client.main.Main"}, f)
    with open(os.path.join(vdir, "1.20.1.jar"), "wb") as f:
        f.write(b"jar" * 100)
    os.makedirs(os.path.join(game, "mods"), exist_ok=True)

    info1, cached1 = prewarm.inspect_cached(game, "1.20.1", "")
    check("首次冷算 cached=False", cached1 is False)
    check("缓存文件已写入", os.path.isfile(prewarm.cache_path(game)))
    info2, cached2 = prewarm.inspect_cached(game, "1.20.1", "")
    check("第二次命中 cached=True", cached2 is True)

    # 内容增删（mods 目录变化）→ 失效
    with open(os.path.join(game, "mods", "new.jar"), "wb") as f:
        f.write(b"x")
    info3, cached3 = prewarm.inspect_cached(game, "1.20.1", "")
    check("mods 增删后缓存失效", cached3 is False)

    # 显式 invalidate
    prewarm.invalidate(game, "1.20.1")
    check("invalidate 删除缓存", not os.path.isfile(prewarm.cache_path(game)))


def test_cli():
    print("[cli]")
    o = cli.parse_args(["--list-instances"])
    check("list 解析", o["command"] == "list")
    o2 = cli.parse_args(["--launch", "默认实例", "--memory", "2048", "--width", "1280", "--height", "720"])
    check("launch 解析与整数", o2["command"] == "launch" and o2["instance"] == "默认实例"
          and o2["memory"] == 2048 and o2["width"] == 1280)
    try:
        cli.parse_args(["--launch"])
        check("缺实例报错", False)
    except cli.CliError:
        check("缺实例报错", True)
    try:
        cli.parse_args(["--memory", "abc"])
        check("非法整数报错", False)
    except cli.CliError:
        check("非法整数报错", True)
    try:
        cli.parse_args(["--bogus"])
        check("未知参数报错", False)
    except cli.CliError:
        check("未知参数报错", True)

    cfg = {"instances": [{"id": "default", "name": "默认实例", "game_dir": "C:/tmp/x",
                         "last_version": "1.20.1", "loader_hint": ""}]}
    out = cli.cmd_list_instances(cfg)
    check("list 输出含实例名", "默认实例" in out and "default" in out)


def test_protocol():
    print("[protocol]")
    p = protocol.parse_url("mclite://launch?instance=default")
    check("launch 解析", p["action"] == "launch" and p["instance"] == "default")
    p2 = protocol.parse_url("mclite://join?host=127.0.0.1&port=25565")
    check("join 解析", p2["action"] == "join" and p2["host"] == "127.0.0.1" and p2["port"] == "25565")
    for bad in ["https://x", "mclite://foo?x=1", "mclite://launch", "mclite://join?host="]:
        try:
            protocol.parse_url(bad)
            check("非法 URL 拒绝: %s" % bad, False)
        except ValueError:
            check("非法 URL 拒绝: %s" % bad, True)

    # 单实例 socket + 消息投递
    sock, primary = protocol.acquire_single_instance(port=47991)
    check("首个实例成为主实例", primary and sock is not None)
    sock2, primary2 = protocol.acquire_single_instance(port=47991)
    check("第二个实例绑定失败", (not primary2) and sock2 is None)
    protocol.start_listener(sock)
    ok = protocol.notify_primary("mclite://launch?instance=default", port=47991)
    check("第二实例投递成功", ok)
    time.sleep(0.4)
    msg = protocol.pop_pending()
    check("主实例收到消息", msg == "mclite://launch?instance=default", str(msg))
    sock.close()


def main():
    tmp = tempfile.mkdtemp(prefix="mclite_perf_test_")
    print("TMP", tmp)
    try:
        test_downloader(tmp)
        test_sharedpool(tmp)
        test_prewarm(tmp)
        test_cli()
        test_protocol()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("=" * 50)
    print("PERF TEST: %d passed, %d failed" % (PASSED, FAILED))
    sys.exit(1 if FAILED else 0)


if __name__ == "__main__":
    main()
