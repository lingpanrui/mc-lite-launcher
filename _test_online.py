# -*- coding: utf-8 -*-
"""第 7 批联机后端测试：NBT 往返 / servers.dat 兼容 / 端口解析 / 一致性哈希 / URL 解析 / EULA 闸门。

运行：python _test_online.py
"""
import os
import socket
import tempfile
import threading
import time

from mclite import online, protocol

PASS = 0
FAIL = 0


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  [PASS] %s" % name)
    else:
        FAIL += 1
        print("  [FAIL] %s %s" % (name, extra))


def test_nbt_roundtrip(tmp):
    print("[1] servers.dat NBT 写入-读回往返")
    p = os.path.join(tmp, "servers.dat")
    servers = [
        {"name": "主服务器", "ip": "192.168.1.10:25565", "hidden": False},
        {"name": "备用", "ip": "10.0.0.2:25566", "hidden": True},
    ]
    online.write_servers_dat(p, servers)
    raw = open(p, "rb").read()
    check("gzip 魔数 1f8b", raw[:2] == b"\x1f\x8b", raw[:2].hex())
    back = online.read_servers_dat(p)
    check("条目数=2", len(back) == 2, str(len(back)))
    check("首条 name/ip", back[0]["name"] == "主服务器" and back[0]["ip"] == "192.168.1.10:25565", str(back[0]))
    check("hidden 布尔", back[1]["hidden"] is True and back[0]["hidden"] is False, str(back))

    # 裸 NBT（不 gzip）也应能读
    p2 = os.path.join(tmp, "raw.dat")
    online.write_servers_dat(p2, [{"name": "x", "ip": "127.0.0.1:25565"}], gzip_compress=False)
    back2 = online.read_servers_dat(p2)
    check("裸 NBT 兼容读取", len(back2) == 1 and back2[0]["ip"] == "127.0.0.1:25565", str(back2))

    # export_servers_dat 读回校验
    d = os.path.join(tmp, "inst")
    os.makedirs(d, exist_ok=True)
    res = online.export_servers_dat(d, "127.0.0.1", 25565, name="测试")
    check("export readback_ok", res["readback_ok"] is True, str(res))
    check("export 路径在实例根", os.path.normcase(res["path"]) == os.path.normcase(os.path.join(d, "servers.dat")))


def test_netstat_parse():
    print("[2] netstat 监听端口解析")
    sample = (
        "\n".join([
            "Active Connections",
            "  Proto  Local Address          Foreign Address        State           PID",
            "  TCP    0.0.0.0:25565          0.0.0.0:0              LISTENING       1234",
            "  TCP    [::]:25565             [::]:0                 LISTENING       1234",
            "  TCP    0.0.0.0:47821          0.0.0.0:0              LISTENING       9999",
            "  TCP    127.0.0.1:5000         0.0.0.0:0              LISTENING       1234",
            "  TCP    0.0.0.0:25565          192.168.1.1:51000      ESTABLISHED     1234",
        ])
    )
    all_rows = online.parse_netstat_listening(sample)
    check("不过滤时含 3 个唯一端口", len(all_rows) == 3, str(all_rows))
    java_rows = online.parse_netstat_listening(sample, java_pids=[1234])
    ports = sorted(r["port"] for r in java_rows)
    check("按 java PID 过滤=25565,5000", ports == [5000, 25565], str(ports))
    check("去重 IPv4/IPv6 同端口", sum(1 for r in java_rows if r["port"] == 25565) == 1)
    check("ESTABLISHED 不入选", all(r["port"] != 51000 for r in all_rows))


def test_mods_hash(tmp):
    print("[3] mods 短哈希确定性 + 排除 .disabled")
    mods = os.path.join(tmp, "mods")
    os.makedirs(mods, exist_ok=True)
    open(os.path.join(mods, "a.jar"), "wb").write(b"AAAA")
    open(os.path.join(mods, "b.jar"), "wb").write(b"BBBB")
    open(os.path.join(mods, "c.jar.disabled"), "wb").write(b"CCCC")
    h1 = online.mods_short_hash(tmp)
    h2 = online.mods_short_hash(tmp)
    check("哈希稳定", h1["hash"] == h2["hash"] and len(h1["hash"]) == 8, h1["hash"])
    check("只计启用 jar=2", h1["count"] == 2, str(h1["count"]))
    check("disabled 被排除", all("c.jar" not in f for f in h1["files"]))
    # 改内容哈希变化
    open(os.path.join(mods, "a.jar"), "wb").write(b"AAAA-changed")
    h3 = online.mods_short_hash(tmp)
    check("内容变化哈希变化", h3["hash"] != h1["hash"])


def test_consistency():
    print("[4] 连接前一致性校验")
    local = {"mc_version": "1.20.1", "loader": "fabric", "mods_hash": "abc12345"}
    ok = online.consistency_check(local, {"mc_version": "1.20.1", "loader": "fabric", "mods_hash": "abc12345"})
    check("完全一致 ok", ok["ok"] is True)
    v = online.consistency_check(local, {"mc_version": "1.21.1", "loader": "fabric", "mods_hash": "abc12345"})
    check("版本不一致告警", v["ok"] is False and any(i["field"] == "mc_version" for i in v["issues"]))
    l = online.consistency_check(local, {"mc_version": "1.20.1", "loader": "forge", "mods_hash": "abc12345"})
    check("加载器不一致告警", l["ok"] is False and any(i["field"] == "loader" for i in l["issues"]))
    m = online.consistency_check(local, {"mc_version": "1.20.1", "loader": "fabric", "mods_hash": "deadbeef"})
    check("mods 哈希不一致告警", m["ok"] is False and any(i["field"] == "mods_hash" for i in m["issues"]))
    # 空字段跳过（不臆断）
    e = online.consistency_check({}, {"mc_version": "1.20.1", "loader": "fabric", "mods_hash": "x"})
    check("本地为空时跳过", e["ok"] is True)
    check("loader 归一化 vanilla", online.normalize_loader("Vanilla") == "vanilla"
          and online.normalize_loader("") == "vanilla" and online.normalize_loader("Forge") == "forge")


def test_join_card():
    print("[5] 加入卡片文本")
    card = online.build_join_card("192.168.1.5", 25565, "1.20.1", "fabric", "abc12345", False, "测试实例")
    for token in ["192.168.1.5:25565", "1.20.1", "fabric", "abc12345", "online-mode", "false", "多人游戏"]:
        check("卡片含 %s" % token, token in card)
    card2 = online.build_join_card("h", 25565, online_mode=True)
    check("正版服标注 true", "true" in card2 and "正版" in card2)


def test_protocol_join():
    print("[6] mclite://join URL 解析")
    p = protocol.parse_url("mclite://join?host=127.0.0.1&port=25565")
    check("action=join", p["action"] == "join")
    check("host/port", p["host"] == "127.0.0.1" and p["port"] == "25565", str(p))
    p2 = protocol.parse_url("mclite://join?host=10.0.0.1")
    check("port 缺省为空串", p2["port"] == "")
    try:
        protocol.parse_url("mclite://join?port=25565")
        check("缺 host 抛错", False)
    except ValueError:
        check("缺 host 抛错", True)
    try:
        protocol.parse_url("mclite://launch?instance=x")
        check("launch 仍可解析", True)
    except Exception as e:
        check("launch 仍可解析", False, str(e))


def test_eula_gate_and_props(tmp):
    print("[7] EULA 闸门 + server.properties")
    gd = os.path.join(tmp, "srvinst")
    os.makedirs(online.server_dir(gd), exist_ok=True)
    # 放假 jar 让 jar 存在检查通过，聚焦 EULA 闸门
    jar = online.server_jar_path(gd, "1.20.1")
    open(jar, "wb").write(b"fake")
    check("未同意 EULA", online.eula_accepted(gd) is False)
    try:
        online.start_server(gd, "java-does-not-exist", port=25565, version="1.20.1")
        check("未同意时拒绝启动(PermissionError)", False)
    except PermissionError:
        check("未同意时拒绝启动(PermissionError)", True)
    except FileNotFoundError:
        check("未同意时拒绝启动(PermissionError)", False, "先命中了 jar/java 检查")
    online.accept_eula(gd)
    check("同意后 eula=true", online.eula_accepted(gd) is True)
    props = online.write_server_properties(gd, port=25599, online_mode=False)
    txt = open(props, "r", encoding="utf-8").read()
    check("properties 含 server-port=25599", "server-port=25599" in txt)
    check("properties 含 online-mode=false", "online-mode=false" in txt)
    check("properties 含 motd", "motd=" in txt)


def test_port_probe():
    print("[8] wait_port_open 连通性探测")
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    check("监听端口可连", online.wait_port_open("127.0.0.1", port, timeout=3) is True)
    srv.close()
    t0 = time.time()
    ok = online.wait_port_open("127.0.0.1", port, timeout=1)
    check("关闭端口超时返回 False", ok is False and time.time() - t0 < 4)


def test_guides():
    print("[9] 跨启动器指引与虚拟局域网")
    g = online.launcher_guides("zh")
    keys = {x["key"] for x in g}
    check("四家齐全 HMCL/PCL2/BHL/FCL", {"hmcl", "pcl2", "bhl", "fcl"} <= keys, str(keys))
    fcl = next(x for x in g if x["key"] == "fcl")
    joined = " ".join(fcl["steps"])
    check("FCL 含同 WiFi/虚拟局域网/online-mode", "WiFi" in joined and "虚拟局域网" in joined and "online-mode" in joined)
    v = online.virtual_lan_guides("zh")
    vk = {x["key"] for x in v}
    check("三家免费虚拟局域网", {"zerotier", "tailscale", "radmin"} <= vk, str(vk))
    check("均带官网 URL", all(x["url"].startswith("https://") for x in v))


def main():
    tmp = tempfile.mkdtemp(prefix="mclite_online_test_")
    print("临时目录：", tmp)
    test_nbt_roundtrip(tmp)
    test_netstat_parse()
    test_mods_hash(tmp)
    test_consistency()
    test_join_card()
    test_protocol_join()
    test_eula_gate_and_props(tmp)
    test_port_probe()
    test_guides()
    print("\n==== %d passed, %d failed ====" % (PASS, FAIL))
    raise SystemExit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
