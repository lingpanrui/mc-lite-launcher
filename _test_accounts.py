# -*- coding: utf-8 -*-
"""批次2 账户系统 + 加载器元数据解析 纯后端自测（headless，不弹窗、不联网）

覆盖：
- 账户迁移/默认离线账户映射、增删改切、同名拦截、持久化往返
- 在线账户 upsert（重复登录刷新 token 不产生重复行）
- launch_auth 组装、authlib javaagent 参数
- Forge/NeoForge 版本前缀与加载器识别、Quilt 稳定版选择/测试版回退/无可用报错

运行：python _test_accounts.py
所有数据写在临时 APPDATA，不碰真实 %APPDATA%\\MCLite。
"""
import os
import sys
import tempfile

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

TMP = tempfile.mkdtemp(prefix="mclite-acc-test-")
os.environ["APPDATA"] = TMP

from mclite import util, accounts, forge, quilt  # noqa: E402

PASS = 0
FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  [PASS] %s" % name)
    else:
        FAIL += 1
        print("  [FAIL] %s  %s" % (name, detail))


def section(title):
    print("\n== %s ==" % title)


# ---------------------------------------------------------------- 1. 迁移与默认账户
section("1. 首次迁移：老 config.username 播种为默认离线账户")
cfg = util.load_config()
check("初始无 accounts 键", not cfg.get("accounts"))
accounts.migrate(cfg)
accs = accounts.list_accounts(cfg)
check("播种 1 个账户", len(accs) == 1, len(accs))
check("默认账户为 offline", accs[0]["mode"] == "offline")
check("默认账户名取 username=Steve", accs[0]["name"] == "Steve", accs[0]["name"])
check("默认账户 id 稳定", accs[0]["id"] == accounts.OFFLINE_DEFAULT_ID, accs[0]["id"])
check("当前账户指向默认", accounts.current(cfg)["id"] == accounts.OFFLINE_DEFAULT_ID)
check("离线 UUID 为 v3", len(accs[0]["uuid"]) == 36 and accs[0]["uuid"].count("-") == 4)
check("顶层 username 镜像", cfg["username"] == "Steve")

# 幂等：再次 migrate 不重复播种
accounts.migrate(cfg)
check("重复 migrate 不产生重复账户", len(accounts.list_accounts(cfg)) == 1)

# ---------------------------------------------------------------- 2. 新增/重复/切换
section("2. 新增离线账户、同名拦截、切换")
alice = accounts.add_offline(cfg, "Alice")
check("新增后自动切换", cfg["current_account"] == alice["id"])
check("当前账户名=Alice", accounts.current(cfg)["name"] == "Alice")
check("顶层 username 跟随", cfg["username"] == "Alice")

try:
    accounts.add_offline(cfg, "alice")  # 忽略大小写
    check("同名（忽略大小写）被拦截", False)
except ValueError:
    check("同名（忽略大小写）被拦截", True)

try:
    accounts.add_offline(cfg, "  ")
    check("空名被拦截", False)
except ValueError:
    check("空名被拦截", True)

bob = accounts.add_offline(cfg, "Bob", switch=False)
check("switch=False 不改变当前", cfg["current_account"] == alice["id"])
accounts.set_current(cfg, bob["id"])
check("set_current 切到 Bob", accounts.current(cfg)["id"] == bob["id"])
check("切换后 username=Bob", cfg["username"] == "Bob")

# ---------------------------------------------------------------- 3. 改名
section("3. 离线账户改名与冲突")
accounts.rename_offline(cfg, alice["id"], "Alice2")
check("改名生效", accounts.get_account(cfg, alice["id"])["name"] == "Alice2")
try:
    accounts.rename_offline(cfg, alice["id"], "bob")
    check("改成已存在名字被拦截", False)
except ValueError:
    check("改成已存在名字被拦截", True)

# 在线账户不能手动改名
online = accounts._upsert_online(cfg, {
    "mode": "authlib", "name": "SkinUser", "uuid": "abc", "token": "t1",
    "api": "https://example/api/yggdrasil"}, switch=False)
try:
    accounts.rename_offline(cfg, online["id"], "X")
    check("在线账户改名被拒绝", False)
except ValueError:
    check("在线账户改名被拒绝", True)

# ---------------------------------------------------------------- 4. 删除
section("4. 删除账户与最后一个保护")
accounts.set_current(cfg, bob["id"])
accounts.delete(cfg, bob["id"])
check("Bob 已删除", accounts.get_account(cfg, bob["id"]) is None)
check("删除当前账户后自动切到第一个(默认 Steve)",
      accounts.current(cfg)["id"] == accounts.OFFLINE_DEFAULT_ID)
# 最后一个账户保护：用独立 mini 配置验证，不破坏主配置里的 Alice2
mini = {"accounts": [{"id": "x", "mode": "offline", "name": "S", "uuid": "u", "token": "",
                      "api": "", "client_token": "", "user_type": "legacy", "skin": "",
                      "builtin": True, "created_at": 0}], "current_account": "x"}
try:
    accounts.delete(mini, "x")
    check("至少保留一个账户", False)
except ValueError:
    check("至少保留一个账户", True)

# ---------------------------------------------------------------- 5. 在线 upsert
section("5. 外置/微软账户 upsert 与重复登录刷新 token")
a1 = accounts._upsert_online(cfg, {
    "mode": "authlib", "name": "SkinUser", "uuid": "u1", "token": "tok-1",
    "api": "https://example/api/yggdrasil"})
n_after_first = len(accounts.list_accounts(cfg))
a2 = accounts._upsert_online(cfg, {
    "mode": "authlib", "name": "SkinUser", "uuid": "u1", "token": "tok-2",
    "api": "https://example/api/yggdrasil"})
check("同模式+API+角色名不产生重复行", len(accounts.list_accounts(cfg)) == n_after_first)
check("重复登录刷新 token", a2["token"] == "tok-2" and a2["id"] == a1["id"])
msa = accounts._upsert_online(cfg, {"mode": "msa", "name": "MSUser", "uuid": "m1", "token": "mt"})
check("微软账户可并存", accounts.get_account(cfg, msa["id"])["mode"] == "msa")
check("在线账户 user_type=msa", a2["user_type"] == "msa")

# ---------------------------------------------------------------- 6. launch_auth / javaagent
section("6. 启动 auth 组装与 authlib 注入参数")
off_acc = next(a for a in accounts.list_accounts(cfg) if a["mode"] == "offline" and a["name"] == "Alice2")
off = accounts.launch_auth(off_acc)
check("离线 auth token 为 32 个 0", off["token"] == "0" * 32 and off["user_type"] == "legacy")
check("离线 auth name/uuid", off["name"] == "Alice2" and len(off["uuid"]) == 36)
au = accounts.launch_auth(a2)
check("外置 auth 透传 token 与 msa 类型", au["token"] == "tok-2" and au["user_type"] == "msa")
jar_path = os.path.join(TMP, "authlib-injector.jar")
with open(jar_path, "wb") as f:
    f.write(b"PK\x03\x04 dummy")
agent = accounts.javaagent_arg(a2, jar_path)
expect_agent = "-javaagent:%s=%s" % (jar_path, "https://example/api/yggdrasil")
check("外置 javaagent 含 jar 与 API", agent == expect_agent, agent)
check("离线账户不产生 javaagent", accounts.javaagent_arg(off, jar_path) is None)
check("缺 jar 文件时不产生 javaagent", accounts.javaagent_arg(a2, os.path.join(TMP, "nope.jar")) is None)

# ---------------------------------------------------------------- 7. 持久化往返
section("7. 配置持久化往返（重新从磁盘加载）")
util.save_config(cfg)
cfg2 = util.load_config()
accounts.migrate(cfg2)
names = sorted(a["name"] for a in accounts.list_accounts(cfg2))
check("重载后账户仍在", "Alice2" in names and "SkinUser" in names and "MSUser" in names, names)
check("重载后 current_account 保留", cfg2["current_account"] == cfg["current_account"])
check("重载后外置 token 保留", any(a.get("token") == "tok-2" for a in accounts.list_accounts(cfg2)))

# ---------------------------------------------------------------- 8. 加载器元数据解析
section("8. 加载器元数据解析（纯函数，不联网）")
check("neo_prefix 1.20.4", forge.neo_prefix("1.20.4") == "20.4.")
check("neo_prefix 1.21.1", forge.neo_prefix("1.21.1") == "21.1.")
check("neo_prefix 1.21", forge.neo_prefix("1.21") == "21.0.")
check("neo_prefix 1.20.2", forge.neo_prefix("1.20.2") == "20.2.")
check("detect quilt", forge.detect_loader({"id": "quilt-loader-0.20-1.20.1", "mainClass": "org.quiltmc.loader.impl.launch.knot.KnotClient"}) == "quilt")
check("detect fabric", forge.detect_loader({"id": "fabric-loader-0.16-1.20.1", "mainClass": "net.fabricmc.loader.impl.launch.knot.KnotClient"}) == "fabric")
check("detect neoforge", forge.detect_loader({"id": "neoforge-20.4.237", "mainClass": "cpw.mods.bootstraplauncher.BootstrapLauncher"}) == "neoforge")
check("detect forge", forge.detect_loader({"id": "1.20.1-forge-47.4.29", "mainClass": "cpw.mods.bootstraplauncher.BootstrapLauncher"}) == "forge")
check("detect vanilla", forge.detect_loader({"id": "1.20.1", "mainClass": "net.minecraft.client.main.Main"}) == "vanilla")
check("quilt 预发布识别 beta", quilt._is_prerelease("0.20.0-beta.9"))
check("quilt 预发布识别 rc", quilt._is_prerelease("1.0.0-rc.1"))
check("quilt 稳定版不判预发布", not quilt._is_prerelease("0.19.4"))

# Quilt 选择逻辑：monkeypatch list_loaders，不发网络
orig_list = quilt.list_loaders
try:
    quilt.list_loaders = lambda mc, include_beta=False, timeout=25: (
        ["0.20.0-beta.9", "0.19.4"] if include_beta else ["0.19.4"]
    )
    check("默认选稳定版", quilt.select_loader("1.20.1") == "0.19.4")
    check("显式指定优先", quilt.select_loader("1.20.1", "0.20.0-beta.9") == "0.20.0-beta.9")
    quilt.list_loaders = lambda mc, include_beta=False, timeout=25: (
        ["0.20.0-beta.9"] if include_beta else []
    )
    try:
        quilt.select_loader("1.20.1")
        check("无稳定版且未开 beta 应报错", False)
    except ValueError:
        check("无稳定版且未开 beta 应报错", True)
    check("开启 beta 后回退首个", quilt.select_loader("1.20.1", include_beta=True) == "0.20.0-beta.9")
finally:
    quilt.list_loaders = orig_list

# Forge 版本排序键
check("forge 版本键排序", forge._ver_key("47.4.29") > forge._ver_key("47.2.36"))

print("\n========================================")
print("RESULT: %d passed, %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
