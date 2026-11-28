# -*- coding: utf-8 -*-
"""第 7 批：跨启动器联机后端。

设计前提（见 _ROADMAP_B5-B7.md 第 7 批）：
- Minecraft Java 版联机只认 TCP 的 IP:端口，与启动器品牌无关，协议层可行。
- 零成本做不到的只有「输 6 位房间码就进」那一类（需要中转信令服务器），本模块明确不做。

本模块只做无界面、可单测的部分：
1. servers.dat 的最小 NBT 读写（根 Compound -> list servers -> name/ip/hidden），gzip 压缩，
   与 Java 版 servers.dat 格式一致；写完用同一解析器读回校验。
2. 集成服务端：下载官方 server.jar、EULA 闸门（必须界面显式同意才写 eula.txt）、
   生成 server.properties、后台启动、等 Done、socket 探活、优雅停服。
3. 客户端局域网端口检测（netstat -ano + tasklist 识别 java 监听端口）与多网卡内网 IP。
4. 加入卡片（IP:端口 / 版本 / 加载器 / mods 短哈希 / online-mode）与连接前一致性校验。
5. HMCL / PCL2 / BHL / FCL 跨启动器指引与免费虚拟局域网（ZeroTier/Tailscale/Radmin）说明。
"""
from __future__ import annotations

import gzip
import hashlib
import os
import re
import socket
import struct
import subprocess
import time

from . import util

# ---------------------------------------------------------------------------
# NBT（最小实现，覆盖 servers.dat 所需类型，读取侧覆盖 0-12 全类型以便健壮解析）
# ---------------------------------------------------------------------------
TAG_END = 0
TAG_BYTE = 1
TAG_SHORT = 2
TAG_INT = 3
TAG_LONG = 4
TAG_FLOAT = 5
TAG_DOUBLE = 6
TAG_BYTE_ARRAY = 7
TAG_STRING = 8
TAG_LIST = 9
TAG_COMPOUND = 10
TAG_INT_ARRAY = 11
TAG_LONG_ARRAY = 12


class _NBTWriter:
    def __init__(self):
        self.b = bytearray()

    def u8(self, v):
        self.b.append(int(v) & 0xFF)

    def i16(self, v):
        self.b += struct.pack(">h", int(v))

    def i32(self, v):
        self.b += struct.pack(">i", int(v))

    def i64(self, v):
        self.b += struct.pack(">q", int(v))

    def f32(self, v):
        self.b += struct.pack(">f", float(v))

    def f64(self, v):
        self.b += struct.pack(">d", float(v))

    def string(self, s):
        raw = str(s).encode("utf-8")
        self.i16(len(raw))
        self.b += raw

    def payload(self, typ, val):
        if typ == TAG_BYTE:
            self.u8(val)
        elif typ == TAG_SHORT:
            self.i16(val)
        elif typ == TAG_INT:
            self.i32(val)
        elif typ == TAG_LONG:
            self.i64(val)
        elif typ == TAG_FLOAT:
            self.f32(val)
        elif typ == TAG_DOUBLE:
            self.f64(val)
        elif typ == TAG_STRING:
            self.string(val)
        elif typ == TAG_BYTE_ARRAY:
            self.i32(len(val))
            self.b += bytes(val)
        elif typ == TAG_INT_ARRAY:
            self.i32(len(val))
            self.b += b"".join(struct.pack(">i", int(x)) for x in val)
        elif typ == TAG_LONG_ARRAY:
            self.i32(len(val))
            self.b += b"".join(struct.pack(">q", int(x)) for x in val)
        elif typ == TAG_LIST:
            etype, items = val
            self.u8(etype)
            self.i32(len(items))
            for it in items:
                self.payload(etype, it)
        elif typ == TAG_COMPOUND:
            for name, pair in val.items():
                t, v = pair
                self.u8(t)
                self.string(name)
                self.payload(t, v)
            self.u8(TAG_END)
        else:
            raise ValueError("不支持的 NBT 类型: %s" % typ)

    def root(self, name, compound):
        self.u8(TAG_COMPOUND)
        self.string(name)
        self.payload(TAG_COMPOUND, compound)
        return bytes(self.b)


class _NBTReader:
    def __init__(self, data):
        self.d = data
        self.i = 0

    def u8(self):
        v = self.d[self.i]
        self.i += 1
        return v

    def i16(self):
        v = struct.unpack(">h", self.d[self.i:self.i + 2])[0]
        self.i += 2
        return v

    def i32(self):
        v = struct.unpack(">i", self.d[self.i:self.i + 4])[0]
        self.i += 4
        return v

    def i64(self):
        v = struct.unpack(">q", self.d[self.i:self.i + 8])[0]
        self.i += 8
        return v

    def f32(self):
        v = struct.unpack(">f", self.d[self.i:self.i + 4])[0]
        self.i += 4
        return v

    def f64(self):
        v = struct.unpack(">d", self.d[self.i:self.i + 8])[0]
        self.i += 8
        return v

    def string(self):
        n = self.i16()
        s = self.d[self.i:self.i + n].decode("utf-8", errors="replace")
        self.i += n
        return s

    def payload(self, typ):
        if typ == TAG_BYTE:
            return self.u8()
        if typ == TAG_SHORT:
            return self.i16()
        if typ == TAG_INT:
            return self.i32()
        if typ == TAG_LONG:
            return self.i64()
        if typ == TAG_FLOAT:
            return self.f32()
        if typ == TAG_DOUBLE:
            return self.f64()
        if typ == TAG_STRING:
            return self.string()
        if typ == TAG_BYTE_ARRAY:
            n = self.i32()
            v = self.d[self.i:self.i + n]
            self.i += n
            return bytes(v)
        if typ == TAG_INT_ARRAY:
            n = self.i32()
            v = list(struct.unpack(">%di" % n, self.d[self.i:self.i + 4 * n])) if n else []
            self.i += 4 * n
            return v
        if typ == TAG_LONG_ARRAY:
            n = self.i32()
            v = list(struct.unpack(">%dq" % n, self.d[self.i:self.i + 8 * n])) if n else []
            self.i += 8 * n
            return v
        if typ == TAG_LIST:
            etype = self.u8()
            n = self.i32()
            return [self.payload(etype) for _ in range(n)]
        if typ == TAG_COMPOUND:
            return self.compound()
        raise ValueError("不支持的 NBT 类型: %s" % typ)

    def compound(self):
        out = {}
        while True:
            t = self.u8()
            if t == TAG_END:
                break
            name = self.string()
            out[name] = self.payload(t)
        return out

    def root(self):
        t = self.u8()
        name = self.string()
        return name, self.payload(t)


def write_servers_dat(path, servers, gzip_compress=True):
    """把服务器列表写成 Java 版 servers.dat（gzip NBT）。

    servers: [{"name": str, "ip": "host:port", "hidden": bool}, ...]
    """
    entries = []
    for s in servers or []:
        entries.append({
            "name": (TAG_STRING, str(s.get("name") or "MCLite Server")),
            "ip": (TAG_STRING, str(s.get("ip") or "")),
            "hidden": (TAG_BYTE, 1 if s.get("hidden") else 0),
        })
    root = {"servers": (TAG_LIST, (TAG_COMPOUND, entries))}
    data = _NBTWriter().root("", root)
    if gzip_compress:
        data = gzip.compress(data)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    return path


def read_servers_dat(path):
    """读取 servers.dat，返回 [{"name","ip","hidden"}]；兼容 gzip 与裸 NBT。"""
    with open(path, "rb") as f:
        raw = f.read()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    _name, root = _NBTReader(raw).root()
    servers = root.get("servers") if isinstance(root, dict) else None
    out = []
    for item in servers or []:
        if not isinstance(item, dict):
            continue
        out.append({
            "name": str(item.get("name", "")),
            "ip": str(item.get("ip", "")),
            "hidden": bool(item.get("hidden", 0)),
        })
    return out


def export_servers_dat(game_dir, host, port, name="MCLite 联机服务器"):
    """写到当前实例根目录 servers.dat，并用同一解析器读回校验。"""
    ip = "%s:%s" % (host, port)
    path = os.path.join(game_dir, "servers.dat")
    write_servers_dat(path, [{"name": name, "ip": ip, "hidden": False}])
    back = read_servers_dat(path)
    ok = len(back) == 1 and back[0].get("ip") == ip
    return {
        "path": path,
        "ip": ip,
        "entries": back,
        "readback_ok": ok,
    }


# ---------------------------------------------------------------------------
# 集成服务端（1.20.1 官方 server.jar）
# ---------------------------------------------------------------------------
DEFAULT_SERVER_VERSION = "1.20.1"
SERVER_PORT_DEFAULT = 25565


def server_dir(game_dir):
    return os.path.join(game_dir, "server")


def server_jar_path(game_dir, version=DEFAULT_SERVER_VERSION):
    return os.path.join(server_dir(game_dir), "server-%s.jar" % version)


def server_jar_info(version=DEFAULT_SERVER_VERSION):
    """从 Mojang 版本清单取 server.jar 下载信息；失败回退 BMCLAPI 镜像。"""
    from . import mojang
    manifest = util.http_json(mojang.MANIFEST_URL, timeout=30)
    hit = None
    for v in manifest.get("versions", []):
        if v.get("id") == version:
            hit = v
            break
    if not hit:
        raise ValueError("版本清单中找不到 %s" % version)
    vj = util.http_json(hit["url"], timeout=30)
    dl = (vj.get("downloads") or {}).get("server")
    if not dl or not dl.get("url"):
        raise ValueError("%s 没有服务端下载项" % version)
    return {
        "url": dl["url"],
        "sha1": dl.get("sha1"),
        "size": dl.get("size"),
        "bmcl": "https://bmclapi2.bangbang93.com/version/%s/server" % version,
    }


def ensure_server_jar(game_dir, version=DEFAULT_SERVER_VERSION, status=None, progress=None):
    """确保 server.jar 已下载到实例 server/ 目录；已存在且校验通过则直接复用。"""
    def say(m):
        if status:
            try:
                status(m)
            except Exception:
                pass

    jar = server_jar_path(game_dir, version)
    info = None
    try:
        info = server_jar_info(version)
    except Exception as e:
        say("官方清单获取失败，尝试镜像：%s" % e)
    if util.file_ok(jar, (info or {}).get("size"), (info or {}).get("sha1")):
        return jar
    os.makedirs(server_dir(game_dir), exist_ok=True)

    def _on_bytes(g, t):
        if progress and t:
            try:
                progress(g / t)
            except Exception:
                pass

    last = None
    if info:
        try:
            say("下载官方服务端 %s（约 40-50MB）" % version)
            util.download_file(
                info["url"], jar, expected_sha1=info.get("sha1"),
                on_bytes=_on_bytes, desc="server.jar", timeout=60)
            return jar
        except Exception as e:
            last = e
            say("官方源下载失败，改用 BMCLAPI 镜像：%s" % e)
    bmcl = (info or {}).get("bmcl") or ("https://bmclapi2.bangbang93.com/version/%s/server" % version)
    util.download_file(bmcl, jar, on_bytes=_on_bytes, desc="server.jar(BMCL)", timeout=60)
    if not os.path.isfile(jar) or os.path.getsize(jar) < 1_000_000:
        raise IOError("服务端 jar 下载不完整：%s" % (last or "镜像失败"))
    return jar


def eula_path(game_dir):
    return os.path.join(server_dir(game_dir), "eula.txt")


def eula_accepted(game_dir):
    try:
        with open(eula_path(game_dir), "r", encoding="utf-8", errors="ignore") as f:
            return "eula=true" in f.read().lower()
    except Exception:
        return False


def accept_eula(game_dir):
    """仅在用户于界面显式点击同意后调用：写 eula=true。绝不静默代同意。"""
    sdir = server_dir(game_dir)
    os.makedirs(sdir, exist_ok=True)
    with open(eula_path(game_dir), "w", encoding="utf-8") as f:
        f.write("# 由 MC Lite 在用户点击「我已阅读并同意 EULA」后写入\n")
        f.write("eula=true\n")
    return eula_path(game_dir)


def write_server_properties(game_dir, port=SERVER_PORT_DEFAULT, online_mode=False,
                            motd="MCLite LAN Server", max_players=20):
    """生成一份可直接启动的 server.properties（离线服 online-mode=false）。"""
    sdir = server_dir(game_dir)
    os.makedirs(sdir, exist_ok=True)
    props = {
        "accepts-transfers": "false",
        "allow-flight": "false",
        "allow-nether": "true",
        "broadcast-console-to-ops": "true",
        "broadcast-rcon-to-ops": "true",
        "debug": "false",
        "difficulty": "easy",
        "enable-command-block": "false",
        "enable-jmx-monitoring": "false",
        "enable-query": "false",
        "enable-rcon": "false",
        "enable-status": "true",
        "enforce-secure-profile": "true",
        "enforce-whitelist": "false",
        "entity-broadcast-range-percentage": "100",
        "force-gamemode": "false",
        "function-permission-level": "2",
        "gamemode": "survival",
        "generate-structures": "true",
        "generator-settings": "{}",
        "hardcore": "false",
        "level-name": "world",
        "level-seed": "",
        "level-type": "minecraft:normal",
        "max-chained-neighbor-updates": "1000000",
        "max-players": str(max_players),
        "max-tick-time": "60000",
        "max-world-size": "29999984",
        "motd": motd,
        "network-compression-threshold": "256",
        "online-mode": "true" if online_mode else "false",
        "op-permission-level": "4",
        "player-idle-timeout": "0",
        "prevent-proxy-connections": "false",
        "pvp": "true",
        "query.port": str(port),
        "rate-limit": "0",
        "rcon.password": "",
        "rcon.port": "25575",
        "require-resource-pack": "false",
        "resource-pack": "",
        "resource-pack-prompt": "",
        "resource-pack-sha1": "",
        "server-ip": "",
        "server-port": str(port),
        "simulation-distance": "10",
        "spawn-monsters": "true",
        "spawn-protection": "16",
        "sync-chunk-writes": "true",
        "use-native-transport": "true",
        "view-distance": "10",
        "white-list": "false",
    }
    path = os.path.join(sdir, "server.properties")
    with open(path, "w", encoding="utf-8") as f:
        for k in sorted(props):
            f.write("%s=%s\n" % (k, props[k]))
    return path


def start_server(game_dir, java_exe, port=SERVER_PORT_DEFAULT, memory_mb=1024,
                 version=DEFAULT_SERVER_VERSION, on_line=None, on_done=None):
    """后台启动 `java -Xmx -jar server.jar nogui`，返回 Popen。

    on_line(line) 每行日志回调；出现 `Done (` 时回调 on_done(line)。
    """
    jar = server_jar_path(game_dir, version)
    if not os.path.isfile(jar):
        raise FileNotFoundError("服务端 jar 不存在：%s" % jar)
    if not eula_accepted(game_dir):
        raise PermissionError("尚未同意 EULA，拒绝启动（必须由用户在界面显式同意）")
    sdir = server_dir(game_dir)
    cmd = [java_exe, "-Xmx%dM" % memory_mb, "-Xms%dM" % min(memory_mb, 1024),
           "-jar", jar, "nogui"]
    creationflags = 0
    if os.name == "nt":
        creationflags = 0x08000000  # CREATE_NO_WINDOW
    proc = subprocess.Popen(
        cmd, cwd=sdir, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
        creationflags=creationflags, bufsize=1)

    def _reader():
        try:
            for line in proc.stdout:
                line = line.rstrip("\r\n")
                if on_line:
                    try:
                        on_line(line)
                    except Exception:
                        pass
                if "Done (" in line and on_done:
                    try:
                        on_done(line)
                    except Exception:
                        pass
        except Exception:
            pass

    import threading
    threading.Thread(target=_reader, daemon=True).start()
    return proc


def stop_server(proc, timeout=25):
    """优雅停服：先向 stdin 发 stop，超时再 terminate/kill。返回退出码。"""
    if proc is None:
        return None
    try:
        if proc.poll() is None and proc.stdin:
            proc.stdin.write("stop\n")
            proc.stdin.flush()
    except Exception:
        pass
    try:
        return proc.wait(timeout=timeout)
    except Exception:
        pass
    try:
        proc.terminate()
        proc.wait(timeout=8)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
    try:
        return proc.wait(timeout=5)
    except Exception:
        return None


def wait_port_open(host, port, timeout=60, interval=1.0):
    """轮询 TCP 连接，成功返回 True。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, int(port)), timeout=2):
                return True
        except OSError:
            time.sleep(interval)
    return False


# ---------------------------------------------------------------------------
# 局域网端口 / 多网卡
# ---------------------------------------------------------------------------
_NETSTAT_RE = re.compile(
    r"^\s*TCP\s+\[?([0-9a-fA-F:.]+)\]?:(\d+)\s+\[?[0-9a-fA-F:.]+\]?:\d+\s+LISTENING\s+(\d+)\s*$")


def parse_netstat_listening(text, java_pids=None):
    """解析 `netstat -ano -p tcp` 文本，返回 [{port,pid,local}]；可按 java PID 过滤。"""
    java_pids = set(int(p) for p in (java_pids or []))
    out = []
    for line in (text or "").splitlines():
        m = _NETSTAT_RE.match(line)
        if not m:
            continue
        local, port, pid = m.group(1), int(m.group(2)), int(m.group(3))
        if java_pids and pid not in java_pids:
            continue
        if port <= 0 or port >= 65535:
            continue
        out.append({"port": port, "pid": pid, "local": local})
    # 去重（同一端口可能 IPv4/IPv6 各一行）
    seen, uniq = set(), []
    for item in out:
        key = (item["port"], item["pid"])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(item)
    return uniq


def _java_pids():
    """返回本机 java.exe / javaw.exe 的 PID 集合（Windows tasklist）。"""
    if os.name != "nt":
        return set()
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq java.exe", "/FO", "CSV", "/NH"],
                             capture_output=True, text=True, errors="replace", timeout=15)
        pids = set()
        for line in out.stdout.splitlines():
            parts = [p.strip('"') for p in line.split('","')]
            if len(parts) >= 2 and parts[0].lower().startswith("java"):
                try:
                    pids.add(int(parts[1]))
                except ValueError:
                    pass
        out2 = subprocess.run(["tasklist", "/FI", "IMAGENAME eq javaw.exe", "/FO", "CSV", "/NH"],
                              capture_output=True, text=True, errors="replace", timeout=15)
        for line in out2.stdout.splitlines():
            parts = [p.strip('"') for p in line.split('","')]
            if len(parts) >= 2 and parts[0].lower().startswith("java"):
                try:
                    pids.add(int(parts[1]))
                except ValueError:
                    pass
        return pids
    except Exception:
        return set()


def list_java_listening_ports():
    """扫本机 java 进程的 TCP 监听端口（netstat -ano + tasklist 关联）。"""
    if os.name != "nt":
        return []
    try:
        out = subprocess.run(["netstat", "-ano", "-p", "tcp"], capture_output=True,
                             text=True, errors="replace", timeout=15)
        pids = _java_pids()
        return parse_netstat_listening(out.stdout, pids or None)
    except Exception:
        return []


def list_local_ips():
    """枚举本机所有非环回 IPv4（多网卡候选都列出）。"""
    ips = set()
    try:
        host = socket.gethostname()
        for info in socket.getaddrinfo(host, None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127.") and not ip.startswith("169.254."):
                ips.add(ip)
    except Exception:
        pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            if not ip.startswith("127."):
                ips.add(ip)
        finally:
            s.close()
    except Exception:
        pass
    return sorted(ips)


def lan_candidates(port):
    """同 WiFi/局域网下所有候选 `IP:端口`。"""
    return [{"ip": ip, "address": "%s:%s" % (ip, port)} for ip in list_local_ips()]


# ---------------------------------------------------------------------------
# 加入卡片 / 一致性校验
# ---------------------------------------------------------------------------
def mods_short_hash(game_dir):
    """对启用中的 mod jar（排除 .disabled）按 文件名|大小 排序求 sha1 前 8 位。"""
    mods_dir = os.path.join(game_dir, "mods")
    names = []
    if os.path.isdir(mods_dir):
        for n in os.listdir(mods_dir):
            if n.lower().endswith(".jar") and not n.lower().endswith(".disabled"):
                try:
                    size = os.path.getsize(os.path.join(mods_dir, n))
                except OSError:
                    size = 0
                names.append("%s|%d" % (n, size))
    names.sort()
    digest = hashlib.sha1("\n".join(names).encode("utf-8")).hexdigest()[:8]
    return {"hash": digest, "count": len(names), "files": names}


def normalize_loader(loader):
    l = (loader or "").strip().lower()
    if l in ("", "vanilla", "原版", "none"):
        return "vanilla"
    if "fabric" in l:
        return "fabric"
    if "forge" in l:
        return "forge"
    if "neoforge" in l:
        return "neoforge"
    if "quilt" in l:
        return "quilt"
    return l


def build_join_card(host, port, mc_version="", loader="", mods_hash="",
                    online_mode=False, instance_name=""):
    addr = "%s:%s" % (host, port)
    lines = [
        "【MC Lite 联机加入卡片】",
        "服务器地址：%s" % addr,
        "目标版本：%s" % (mc_version or "未知（请与房主确认）"),
        "加载器：%s" % (loader or "原版/未知"),
        "模组清单短哈希：%s" % (mods_hash or "无模组/未计算"),
        "离线模式 online-mode：%s" % ("false（离线服，无需正版账号）" if not online_mode else "true（正版验证服务器）"),
    ]
    if instance_name:
        lines.append("来源实例：%s" % instance_name)
    lines.append("加入方式：多人游戏 → 添加服务器（或直接连接）→ 粘贴地址 %s" % addr)
    return "\n".join(lines)


def consistency_check(local, card):
    """比对本地实例与加入卡片的 版本/加载器/mods 哈希，返回差异项。

    local/card: {"mc_version","loader","mods_hash"}；任一为空则跳过该项（不臆断）。
    """
    issues = []
    lv, cv = (local or {}).get("mc_version"), (card or {}).get("mc_version")
    if lv and cv and str(lv) != str(cv):
        issues.append({"field": "mc_version", "local": lv, "card": cv,
                       "msg": "MC 版本不一致：本地 %s / 房间 %s，连上会被拒绝或崩溃" % (lv, cv)})
    ll, cl = normalize_loader((local or {}).get("loader")), normalize_loader((card or {}).get("loader"))
    if ll != "vanilla" and cl != "vanilla" and ll != cl:
        issues.append({"field": "loader", "local": ll, "card": cl,
                       "msg": "加载器不一致：本地 %s / 房间 %s，模组无法互通" % (ll, cl)})
    lh, ch = (local or {}).get("mods_hash"), (card or {}).get("mods_hash")
    if lh and ch and lh != ch:
        issues.append({"field": "mods_hash", "local": lh, "card": ch,
                       "msg": "模组清单不一致（短哈希 %s vs %s），你俩模组不一样，连上会崩" % (lh, ch)})
    return {"ok": not issues, "issues": issues}


# ---------------------------------------------------------------------------
# 跨启动器兼容指引（HMCL / PCL2 / BHL / FCL）
# ---------------------------------------------------------------------------
LAUNCHER_GUIDES = [
    {
        "key": "hmcl",
        "name": "HMCL（Hello Minecraft! Launcher）",
        "steps_zh": [
            "启动 HMCL，选择与房主完全一致的 MC 版本与加载器（Forge/Fabric）。",
            "进入「多人游戏」→ 点击「添加服务器」。",
            "服务器名称随意填；服务器地址填房主给的 IP:端口（如 192.168.1.10:25565）。",
            "点击「完成」，双击该服务器即可加入。",
            "若房主是离线服（online-mode=false），HMCL 用离线账号即可，无需正版。",
        ],
        "steps_en": [
            "Launch HMCL and pick the exact same MC version and loader as the host.",
            "Go to Multiplayer -> Add Server.",
            "Name it freely; paste the host's IP:port (e.g. 192.168.1.10:25565).",
            "Click Done, then double-click the server to join.",
            "For an offline server (online-mode=false), an offline account works; no premium account needed.",
        ],
    },
    {
        "key": "pcl2",
        "name": "PCL2（Plain Craft Launcher 2）",
        "steps_zh": [
            "启动 PCL2，在「版本选择」里选与房主一致的版本（如 1.20.1-Forge / 26.2-Fabric）。",
            "进入游戏后点「多人游戏」→「添加服务器」。",
            "服务器地址粘贴房主给的 IP:端口，点「完成」。",
            "双击服务器加入；提示版本/模组不符时，按房主卡片补齐同版本同模组。",
            "离线服（online-mode=false）可直接用离线昵称进入。",
        ],
        "steps_en": [
            "In PCL2 select the exact same version (e.g. 1.20.1-Forge / 26.2-Fabric).",
            "In-game go to Multiplayer -> Add Server.",
            "Paste the host's IP:port and click Done.",
            "Double-click to join; if version/mods mismatch, align them to the host card.",
            "Offline servers (online-mode=false) accept an offline nickname.",
        ],
    },
    {
        "key": "bhl",
        "name": "BHL（BakaXL / 其他 Java 启动器）",
        "steps_zh": [
            "在 BHL 中选择与房主一致的 MC 版本与加载器并启动。",
            "主菜单进入「多人游戏」→「添加服务器」（部分版本叫「直接连接」）。",
            "地址栏粘贴 IP:端口，确认后加入。",
            "确保与房主在同一 WiFi/同一虚拟局域网，或使用房主提供的公网中转地址。",
        ],
        "steps_en": [
            "In BHL choose the same MC version and loader, then launch.",
            "Main menu -> Multiplayer -> Add Server (or Direct Connect).",
            "Paste IP:port and join.",
            "Be on the same WiFi/VPN as the host, or use the host's public relay address.",
        ],
    },
    {
        "key": "fcl",
        "name": "FCL（Fold Craft Launcher，安卓手机）",
        "steps_zh": [
            "FCL 与电脑端必须是完全一致的 MC 版本与加载器（如都是 1.20.1 + Fabric），模组也要一致，否则会被踢或崩溃。",
            "手机与房主电脑连同一个 WiFi；异地时双方都加入同一个免费虚拟局域网（ZeroTier/Tailscale/Radmin）。",
            "启动游戏 →「多人游戏」→「添加服务器」。",
            "服务器地址填房主的内网 IP:端口（同 WiFi）或虚拟局域网 IP:端口（异地）。",
            "离线服必须由房主把 server.properties 的 online-mode 设为 false，FCL 用离线账号即可进入，无需正版验证。",
            "若提示「无法连接」，先确认手机能 ping 通房主 IP、端口未被防火墙拦截、房主已在游戏内「对局域网开放」或集成服务端已启动。",
        ],
        "steps_en": [
            "FCL must use the exact same MC version and loader (e.g. 1.20.1 + Fabric) and matching mods, or it will be kicked/crash.",
            "Join the same WiFi as the host PC; remotely, both join the same free virtual LAN (ZeroTier/Tailscale/Radmin).",
            "Launch the game -> Multiplayer -> Add Server.",
            "Enter the host's LAN IP:port (same WiFi) or virtual-LAN IP:port (remote).",
            "For offline servers the host must set online-mode=false; FCL offline account works, no premium required.",
            "If connection fails, verify reachability, firewall, and that the host opened to LAN or the integrated server is running.",
        ],
    },
]

# 免费虚拟局域网方案（只给免费方案，不推销付费）
VIRTUAL_LAN_GUIDES = [
    {
        "key": "zerotier",
        "name": "ZeroTier（免费，跨平台）",
        "url": "https://www.zerotier.com/download/",
        "steps_zh": [
            "房主与好友都从官网下载安装 ZeroTier One（Windows/安卓均可，个人免费）。",
            "房主在 my.zerotier.com 注册免费账号并创建一个 Network，记下 16 位 Network ID。",
            "双方在客户端加入该 Network ID；房主在网页后台勾选授权新设备（Auth 列打勾）。",
            "双方获得同一网段的 10.x.x.x 虚拟 IP，房主把该 IP:端口 发给好友即可。",
        ],
        "steps_en": [
            "Both host and friends install ZeroTier One from the official site (Windows/Android, free personal use).",
            "Host signs up free at my.zerotier.com, creates a Network, copies the 16-char Network ID.",
            "Everyone joins that Network ID; host authorizes new devices in the web console.",
            "All get 10.x.x.x virtual IPs; host shares that IP:port.",
        ],
    },
    {
        "key": "tailscale",
        "name": "Tailscale（免费个人版，跨平台）",
        "url": "https://tailscale.com/download",
        "steps_zh": [
            "双方从官网下载安装 Tailscale（Windows/安卓均可），用免费账号登录同一 tailnet。",
            "登录后在 Tailscale 客户端查看本机 100.x.x.x 地址。",
            "房主把自己的 100.x.x.x:端口 发给好友；好友在同一 tailnet 内可直接连接。",
            "无需公网 IP、无需端口映射，流量经加密点对点通道。",
        ],
        "steps_en": [
            "Both install Tailscale from the official site and sign in to the same tailnet (free personal plan).",
            "Check your 100.x.x.x address in the Tailscale client.",
            "Host shares 100.x.x.x:port; friends connect inside the same tailnet.",
            "No public IP or port forwarding needed; encrypted peer-to-peer traffic.",
        ],
    },
    {
        "key": "radmin",
        "name": "Radmin VPN（免费，Windows 为主）",
        "url": "https://www.radmin-vpn.com/",
        "steps_zh": [
            "房主与好友都安装 Radmin VPN（免费），房主创建网络并设置网络名/密码。",
            "好友输入网络名与密码加入同一网络。",
            "双方获得 26.x.x.x 虚拟 IP，房主把 26.x.x.x:端口 发给好友。",
            "适合 Windows 电脑之间联机；安卓 FCL 建议优先 ZeroTier/Tailscale。",
        ],
        "steps_en": [
            "Both install Radmin VPN (free); host creates a network with name/password.",
            "Friends join with the network name and password.",
            "Everyone gets a 26.x.x.x virtual IP; host shares 26.x.x.x:port.",
            "Best for Windows-to-Windows; for Android FCL prefer ZeroTier/Tailscale.",
        ],
    },
]


def launcher_guides(lang="zh"):
    key = "steps_zh" if lang.startswith("zh") else "steps_en"
    return [{"key": g["key"], "name": g["name"], "steps": g[key]} for g in LAUNCHER_GUIDES]


def virtual_lan_guides(lang="zh"):
    key = "steps_zh" if lang.startswith("zh") else "steps_en"
    return [{"key": g["key"], "name": g["name"], "url": g["url"], "steps": g[key]}
            for g in VIRTUAL_LAN_GUIDES]
