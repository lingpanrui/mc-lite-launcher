# -*- coding: utf-8 -*-
"""中英双语文案表（v2）

用法：
    from mclite.i18n import t, set_lang, get_lang
    t("nav.home")
    t("poll.rank", n=3)

每个键对应 (中文, English)。缺失键直接返回键名，便于发现漏翻译。
"""
import os

from . import util

LANGS = ("zh", "en")
LANG_NAMES = {"zh": "中文", "en": "English"}

_current = "zh"


def set_lang(lang):
    global _current
    if lang in LANGS:
        _current = lang


def get_lang():
    return _current


def load_lang():
    """从配置里读界面语言，失败则中文"""
    try:
        cfg = util.load_config()
        lang = cfg.get("language") or "zh"
        if lang in LANGS:
            set_lang(lang)
    except Exception:
        pass
    return _current


def save_lang(lang):
    try:
        cfg = util.load_config()
        cfg["language"] = lang
        util.save_config(cfg)
    except Exception:
        pass
    set_lang(lang)


def font_family():
    """英文用 Segoe UI，中文用微软雅黑，保证字形清晰"""
    return "Segoe UI" if _current == "en" else "Microsoft YaHei UI"


def t(key, **kw):
    pair = STRINGS.get(key)
    if not pair:
        return key
    s = pair[0] if _current == "zh" else pair[1]
    try:
        return s.format(**kw) if kw else s
    except Exception:
        return s


STRINGS = {
    # ---------------------------------------------------------------- 通用
    "app.name": ("MC Lite", "MC Lite"),
    "app.tagline": (
        "Java 版 + 基岩版 · 模组光影 · 免注册联机",
        "Java & Bedrock · Mods & Shaders · Zero-signup multiplayer",
    ),
    "common.version": ("版本", "Version"),
    "common.copy": ("复制", "Copy"),
    "common.copied": ("已复制", "Copied"),
    "common.open": ("打开", "Open"),
    "common.close": ("关闭", "Close"),
    "common.save": ("保存", "Save"),
    "common.refresh": ("刷新", "Refresh"),
    "common.launch": ("启动", "Launch"),
    "common.download": ("下载", "Download"),
    "common.preview": ("提示", "Notice"),
    "common.unpublished": ("尚未发布", "Unpublished"),

    # ---------------------------------------------------------------- 侧边栏
    "nav.home": ("首页", "Home"),
    "nav.versions": ("版本", "Versions"),
    "nav.instances": ("实例", "Instances"),
    "nav.accounts": ("账户", "Accounts"),
    "nav.content": ("内容", "Content"),
    "nav.online": ("联机", "Multiplayer"),
    "nav.poll": ("投票", "Vote"),
    "nav.settings": ("设置", "Settings"),

    # ---------------------------------------------------------------- 首页
    "home.title": ("欢迎回来", "Welcome back"),
    "home.sub": (
        "统一管理 Java 版与基岩版，下载模组光影，一键联机。",
        "Manage Java and Bedrock, grab mods and shaders, host a LAN in one click.",
    ),
    "home.stat.java": ("Java 版本", "Java versions"),
    "home.stat.installed": ("已安装", "Installed"),
    "home.stat.platform": ("模组平台", "Mod platform"),
    "home.stat.votes": ("社区票数", "Community votes"),
    "home.quick": ("快速开始", "Quick start"),
    "home.card.play.title": ("启动游戏", "Play"),
    "home.card.play.desc": (
        "选一个已安装版本，直接进入游戏。",
        "Pick an installed version and jump straight in.",
    ),
    "home.card.content.title": ("找模组光影", "Find mods"),
    "home.card.content.desc": (
        "来自 Modrinth，自动装进对应版本。",
        "Powered by Modrinth; files land in the right version folder.",
    ),
    "home.card.online.title": ("联机开房", "Host a LAN"),
    "home.card.online.desc": (
        "免费隧道，好友填地址即可加入。",
        "Free bore tunnel — friends just paste the address.",
    ),
    "home.news": ("最近版本", "Latest release"),
    "home.tip": (
        "提示：这个 App 负责版本与资源管理；在手机上真正运行 Java 版仍需 PojavLauncher 之类的方案。",
        "Note: this app manages versions and resources; running Java Edition on a phone still needs PojavLauncher or similar.",
    ),

    # ---------------------------------------------------------------- 版本
    "versions.title": ("版本管理", "Versions"),
    "versions.sub": (
        "安装、切换、启动 Java 版实例。",
        "Install, switch and launch Java instances.",
    ),
    "versions.installed": ("已安装版本", "Installed versions"),
    "versions.empty": (
        "还没有安装任何版本，去“安装新版本”里挑一个。",
        "No versions installed yet — grab one from Install new version.",
    ),
    "versions.install": ("安装新版本", "Install new version"),
    "versions.install.title": ("安装新版本", "Install a new version"),
    "versions.install.sub": (
        "选一个游戏版本和加载器，装完直接在版本列表里点启动。",
        "Pick a game version and a loader; launch it from the list when done.",
    ),
    "versions.install.mc": ("游戏版本", "Game version"),
    "versions.install.vanilla": ("原版", "Vanilla"),
    "versions.install.start": ("开始安装", "Install"),
    "versions.install.busy": ("正在安装…", "Installing…"),
    "versions.install.close": ("关闭", "Close"),
    "versions.install.done": ("%s 安装完成，已加入版本列表", "%s installed — added to the list"),
    "versions.install.fail": ("安装失败：%s", "Install failed: %s"),
    "versions.install.note": (
        "原版 / Fabric / Quilt 纯 HTTP 拼装；Forge / NeoForge 运行官方安装器（需 Java），官方源失败自动换 BMCL 镜像。",
        "Vanilla/Fabric/Quilt are assembled over HTTP; Forge/NeoForge run the official installer (Java required), with BMCL mirror fallback.",
    ),
    "versions.current": ("当前使用", "In use"),
    "versions.loader": ("加载器", "Loader"),
    "versions.dir": ("版本目录", "Version folder"),
    "versions.install.loaderver": ("加载器版本", "Loader version"),
    "versions.install.loadingvers": ("正在获取加载器版本…", "Fetching loader versions…"),
    "versions.install.refresh": ("刷新版本列表", "Refresh versions"),
    "versions.install.beta": ("包含测试版（-beta/-rc）", "Include pre-releases (-beta/-rc)"),
    "versions.install.localjar": ("选择本地 installer.jar（官方/镜像都失败时的兜底）", "Pick local installer.jar (fallback when online sources fail)"),
    "versions.install.localjar.pick": ("选择 Forge/NeoForge installer.jar", "Select Forge/NeoForge installer.jar"),
    "versions.install.localjar.set": ("已选本地安装器：%s", "Local installer selected: %s"),
    "versions.install.neo.warn": (
        "提示：NeoForge 官方 maven 在部分网络下会超时，本向导会自动改用 BMCL 镜像；若两者都失败，可从官网下载 installer 后用下方“本地 installer”安装。",
        "Note: the NeoForge official maven may time out on some networks; the wizard falls back to the BMCL mirror. If both fail, download the installer from the official site and use the local installer below.",
    ),
    "versions.install.quilt.none": ("该 MC 版本在 Quilt Meta 上暂无可用加载器（可勾选包含测试版再试）。",
                                    "No Quilt loader available for this MC version yet (try including pre-releases)."),
    "versions.install.forge.hint": ("Forge 安装器会下载依赖库并写入版本 json，可能需要几分钟；需要本机 Java。",
                                     "The Forge installer downloads libraries and writes the version json; it may take a few minutes and needs Java."),
    "versions.install.neo.hint": ("NeoForge 安装器流程与 Forge 相同；官方源 + BMCL 镜像双兜底。",
                                  "NeoForge works like Forge; official source plus BMCL mirror fallback."),
    "versions.install.quilt.hint": ("Quilt 纯 HTTP 拼装（mainClass=KnotClient），无需运行 GUI 安装器。",
                                    "Quilt is assembled over HTTP (mainClass=KnotClient); no GUI installer needed."),
    "versions.install.fabric.hint": ("Fabric 自动选择最新稳定 loader。", "Fabric picks the latest stable loader automatically."),
    "versions.install.vanilla.hint": ("从 Mojang 官方源下载客户端、依赖库与资源。",
                                      "Downloads client, libraries and assets from Mojang."),
    "versions.install.needjava": ("安装 Forge/NeoForge 需要 Java，但没找到可用 Java；请先在设置里指定 javaw.exe。",
                                  "Forge/NeoForge install needs Java, but none was found; set javaw.exe in Settings first."),
    "versions.install.manualver": ("手动输入加载器版本号", "Enter loader version manually"),

    # ---------------------------------------------------------------- 实例系统
    "instances.title": ("实例管理", "Instances"),
    "instances.sub": (
        "多套独立游戏目录与启动参数，一键切换，互不干扰。",
        "Separate game folders and launch settings — switch in one click.",
    ),
    "inst.new": ("新建实例", "New instance"),
    "inst.import": ("导入实例", "Import instance"),
    "inst.current": ("当前", "Current"),
    "inst.switch": ("切换", "Switch"),
    "inst.manage": ("管理实例", "Manage instances"),
    "inst.count": ("{n} 个版本", "{n} versions"),
    "inst.empty": ("还没有实例，点右上角「新建实例」创建第一个。",
                    "No instances yet — click New instance to create one."),
    "inst.detail": ("实例属性", "Instance settings"),
    "inst.basic": ("基本信息", "General"),
    "inst.name": ("实例名称", "Name"),
    "inst.icon": ("图标（单个字符）", "Icon (one character)"),
    "inst.dir": ("游戏目录", "Game folder"),
    "inst.browse": ("浏览", "Browse"),
    "inst.open": ("打开目录", "Open folder"),
    "inst.launch": ("启动参数", "Launch settings"),
    "inst.java": ("Java 路径", "Java path"),
    "inst.memory": ("内存 (MB)", "Memory (MB)"),
    "inst.width": ("窗口宽", "Window width"),
    "inst.height": ("窗口高", "Window height"),
    "inst.jvm": ("额外 JVM 参数（空格分隔）", "Extra JVM args (space separated)"),
    "inst.save": ("保存属性", "Save settings"),
    "inst.saved": ("实例属性已保存", "Instance settings saved"),
    "inst.backup": ("存档备份 / 恢复", "Saves backup / restore"),
    "inst.backup.now": ("立即备份存档", "Back up saves now"),
    "inst.restore": ("恢复存档", "Restore saves"),
    "inst.backup.opts": ("备份时包含 options.txt", "Include options.txt"),
    "inst.backup.config": ("备份时包含 config 目录", "Include config folder"),
    "inst.backup.nosaves": ("该实例还没有 saves 目录，无法备份。",
                            "This instance has no saves folder yet."),
    "inst.backup.done": ("备份完成：%s", "Backup created: %s"),
    "inst.restore.confirm": (
        "恢复前会先自动备份当前存档，再把压缩包解压回实例目录（同名文件会被覆盖）。继续？",
        "Current saves are auto-backed up first, then the zip is extracted over the folder. Continue?",
    ),
    "inst.restore.done": ("恢复完成：解压 %d 个文件；恢复前备份：%s",
                          "Restored %d file(s); pre-restore backup: %s"),
    "inst.restore.pick": ("选择备份 zip", "Choose backup zip"),
    "inst.actions": ("实例操作", "Actions"),
    "inst.duplicate": ("复制实例", "Duplicate"),
    "inst.export": ("导出配置", "Export config"),
    "inst.delete": ("删除实例", "Delete instance"),
    "inst.duplicate.done": ("已复制为「%s」。新实例使用独立空目录，不含版本库与存档。",
                            "Duplicated as \"%s\". The new instance uses a fresh empty folder; versions and saves are not copied."),
    "inst.export.done": ("实例配置已导出：%s", "Instance config exported: %s"),
    "inst.import.done": ("已导入实例「%s」", "Imported instance \"%s\""),
    "inst.import.missing.title": ("版本未安装", "Version not installed"),
    "inst.import.missing": (
        "导入的实例记录了版本 %s，但新实例目录里还没有安装。是否现在去安装？",
        "The imported instance references %s, which is not installed in the new folder. Install it now?",
    ),
    "inst.delete.confirm": (
        "确定删除实例「%s」吗？\n将只删除它自己的目录：\n%s\n此操作不可恢复。",
        "Delete instance \"%s\"?\nOnly its own folder is removed:\n%s\nThis cannot be undone.",
    ),
    "inst.delete.default": (
        "默认实例承载原有游戏目录与已装版本，不能删除；可以重命名或复制它。",
        "The default instance holds the original game folder and installed versions and cannot be deleted; rename or duplicate it instead.",
    ),
    "inst.delete.done": ("实例已删除", "Instance deleted"),
    "inst.new.title": ("新建实例", "New instance"),
    "inst.new.name": ("名称", "Name"),
    "inst.new.dir": ("游戏目录（留空自动创建）", "Game folder (blank = auto-create)"),
    "inst.new.dirhint": ("留空则在实例根目录下自动新建独立文件夹；填写已存在目录则直接使用。",
                         "Leave blank to create a separate folder under the instance root; pick an existing folder to use it directly."),
    "inst.rename.title": ("重命名实例", "Rename instance"),
    "inst.rename.prompt": ("新名称", "New name"),
    "inst.switch.done": ("已切换到实例「%s」", "Switched to \"%s\""),
    "inst.noselect": ("在左侧选择一个实例，查看并编辑它的属性。",
                      "Select an instance on the left to view and edit its settings."),
    "inst.default_name": ("默认实例", "Default"),
    "inst.root": ("实例根目录", "Instance root"),
    "inst.backups": ("备份目录", "Backups folder"),
    "inst.backup.list": ("最近备份", "Recent backups"),
    "inst.restore.none": ("没有找到备份 zip，请先备份一次。", "No backup zip found — back up first."),
    "inst.import.pick": ("选择实例配置 JSON", "Choose instance JSON"),
    "inst.export.pick": ("导出实例配置到…", "Export instance config to…"),
    "inst.import.bad": ("不是有效的 MC Lite 实例配置文件。", "Not a valid MC Lite instance config file."),
    "inst.mem.bad": ("内存需为不小于 1024 的整数（MB）。", "Memory must be an integer >= 1024 MB."),
    "inst.wh.bad": ("窗口宽高需为正整数。", "Window width and height must be positive integers."),
    "inst.java.browse": ("选择 javaw.exe", "Select javaw.exe"),
    "inst.current.label": ("当前实例", "Current instance"),
    "inst.home.bar": ("当前实例：%s · %s", "Current instance: %s · %s"),
    "inst.settings.note": (
        "以下设置作用于当前实例；多个实例请在「实例」页分别配置。",
        "Settings below apply to the current instance; configure each one on the Instances page.",
    ),
    "inst.dup.note": ("复制只包含配置与启动参数，不复制版本库和存档（体积大）。",
                      "Duplicate copies settings only, not versions or saves (large)."),
    "inst.backup.empty": ("暂无备份", "No backups yet"),

    # ---------------------------------------------------------------- 账户系统
    "accounts.title": ("账户", "Accounts"),
    "accounts.sub": ("离线、外置登录（authlib-injector）与微软正版账户并存，一键切换当前账户。",
                     "Offline, authlib-injector and Microsoft accounts side by side — switch in one click."),
    "acc.current.label": ("当前账户", "Current account"),
    "acc.list.title": ("账户列表", "Accounts"),
    "acc.empty": ("还没有账户，先在下方新增一个离线账户。", "No accounts yet — add an offline account below."),
    "acc.mode.offline": ("离线", "Offline"),
    "acc.mode.authlib": ("外置登录", "Yggdrasil"),
    "acc.mode.msa": ("微软正版", "Microsoft"),
    "acc.uuid": ("UUID", "UUID"),
    "acc.skin.site": ("皮肤站点", "Skin site"),
    "acc.set_current": ("设为当前", "Use"),
    "acc.rename": ("改名", "Rename"),
    "acc.delete": ("删除", "Delete"),
    "acc.switch.done": ("已切换到账户「%s」", "Switched to account \"%s\""),
    "acc.added": ("已新增离线账户「%s」", "Added offline account \"%s\""),
    "acc.renamed": ("账户已改名", "Account renamed"),
    "acc.deleted": ("账户已删除", "Account deleted"),
    "acc.delete.confirm": ("确定删除账户「%s」吗？\n该账户的本地登录信息会被移除（不影响游戏文件）。",
                           "Delete account \"%s\"?\nIts local login info is removed (game files are untouched)."),
    "acc.delete.last": ("至少保留一个账户；可先新增另一个账户再删除。",
                        "Keep at least one account; add another before deleting."),
    "acc.offline.title": ("新增离线账户", "New offline account"),
    "acc.offline.name": ("玩家名（3–16 位，仅字母/数字/下划线）", "Player name (3–16 chars, letters/digits/underscore)"),
    "acc.offline.add": ("新增", "Add"),
    "acc.offline.dup": ("已存在同名离线账户：%s", "An offline account with this name already exists: %s"),
    "acc.offline.badname": ("玩家名需为 3–16 位字母、数字或下划线。",
                             "Player name must be 3–16 letters, digits or underscores."),
    "acc.rename.title": ("重命名离线账户", "Rename offline account"),
    "acc.rename.prompt": ("新玩家名", "New player name"),
    "acc.online.title": ("外置登录（authlib-injector + Yggdrasil）", "External login (authlib-injector + Yggdrasil)"),
    "acc.authlib.api": ("API 根地址", "API root URL"),
    "acc.authlib.api.default": ("默认 LittleSkin，可换成任意兼容 Yggdrasil 的皮肤站",
                                "Defaults to LittleSkin; any Yggdrasil-compatible skin site works"),
    "acc.test": ("测试连接", "Test connection"),
    "acc.testing": ("正在连接…", "Connecting…"),
    "acc.test.ok": ("连接成功：%s", "Connection OK: %s"),
    "acc.test.fail": ("连接失败：%s", "Connection failed: %s"),
    "acc.authlib.user": ("用户名 / 邮箱", "Username / email"),
    "acc.authlib.pass": ("密码", "Password"),
    "acc.login": ("登录并设为当前", "Log in and use"),
    "acc.logging": ("正在登录…", "Logging in…"),
    "acc.authlib.note": ("外置账户需先在对应皮肤站免费注册（启动器不代注册、不内置账号）；密码仅用于向你填写的 API 服务器发起认证。",
                         "Register for free on the skin site yourself (the launcher does not register accounts or bundle credentials); the password is only sent to the API server you specify."),
    "acc.authlib.success": ("登录成功：角色「%s」 · 皮肤站点 %s", "Logged in: character \"%s\" · skin site %s"),
    "acc.authlib.inject": ("启动时会自动下载 authlib-injector 并加入 -javaagent 注入参数。",
                           "On launch, authlib-injector is downloaded automatically and added via -javaagent."),
    "acc.msa.title": ("微软正版登录（设备码流程）", "Microsoft login (device code)"),
    "acc.msa.clientid": ("Azure 应用 Client ID", "Azure app Client ID"),
    "acc.msa.save": ("保存 Client ID", "Save Client ID"),
    "acc.msa.saved": ("Client ID 已保存", "Client ID saved"),
    "acc.msa.disabled": ("未配置 Client ID，微软登录已禁用。需自行在 Azure 免费注册一个“公共客户端 + 设备码流”应用，启动器不内置公共 ID。",
                         "No Client ID configured — Microsoft login is disabled. Register a free public-client app with device-code flow in Azure; this launcher ships no shared ID."),
    "acc.msa.howto": ("免费注册步骤（无需付费订阅）：打开 Entra 管理中心 → 应用注册 → 新建应用 → 认证 → 高级设置 → 允许公共客户端流=是 → 复制应用程序(客户端)ID 填到上方。",
                      "Free setup (no paid subscription): Entra admin center → App registrations → New registration → Authentication → Advanced settings → Allow public client flows = Yes → copy the Application (client) ID above."),
    "acc.msa.howto.link": ("打开微软设备码文档", "Open device-code docs"),
    "acc.msa.login": ("获取设备码并登录", "Get device code & log in"),
    "acc.msa.logging": ("等待微软登录…", "Waiting for Microsoft sign-in…"),
    "acc.msa.code": ("请在浏览器打开：%s ，输入设备码：%s", "Open %s in a browser and enter code: %s"),
    "acc.msa.copy": ("复制设备码", "Copy code"),
    "acc.msa.copied": ("设备码已复制", "Code copied"),
    "acc.msa.failed": ("微软登录失败：%s", "Microsoft login failed: %s"),
    "acc.msa.needid": ("请先填写并保存自己的 Azure Client ID", "Fill in and save your own Azure Client ID first"),
    "acc.msa.fakehint": ("若提示 AADSTS700038，说明 Client ID 无效；请确认是“公共客户端”应用且已开启设备码流。",
                         "AADSTS700038 means the Client ID is invalid; make sure it is a public-client app with device-code flow enabled."),

    # ---------------------------------------------------------------- 内容
    "content.title": ("内容库", "Content"),
    "content.sub": (
        "模组、光影、资源包，直接来自 Modrinth。",
        "Mods, shaders and resource packs straight from Modrinth.",
    ),
    "content.tab.mod": ("模组", "Mods"),
    "content.tab.shader": ("光影", "Shaders"),
    "content.project": ("项目页", "Project page"),
    "content.search": ("搜索模组…", "Search mods…"),
    "content.recommend": ("推荐", "Recommended"),
    "content.requires": ("前置", "Requires"),

    # ---------------------------------------------------------------- 联机
    "online.title": ("联机", "Multiplayer"),
    "online.sub": (
        "开一条免费隧道，把地址发给好友。",
        "Open a free tunnel and hand the address to your friends.",
    ),
    "online.port": ("游戏端口", "Game port"),
    "online.detect": ("检测端口", "Detect port"),
    "online.start": ("开启隧道", "Start tunnel"),
    "online.stop": ("关闭隧道", "Stop tunnel"),
    "online.address": ("联机地址", "Address"),
    "online.copy": ("复制地址", "Copy address"),
    "online.hint": (
        "使用 bore 公共服务器，无需注册；延迟取决于线路质量。",
        "Public bore servers, no signup required; latency depends on the route.",
    ),

    # ---------------------------------------------------------------- 投票
    "poll.title": ("功能投票", "Feature voting"),
    "poll.sub": (
        "下个版本先做什么？由你决定，每个功能可投一票。",
        "What should ship next? You decide — one vote per feature.",
    ),
    "poll.total": ("累计票数", "Total votes"),
    "poll.mine": ("我已投", "My votes"),
    "poll.vote": ("投票", "Vote"),
    "poll.voted": ("已投", "Voted"),
    "poll.reset": ("重置我的投票", "Reset my votes"),
    "poll.rank": ("第 {n} 名", "#{n}"),
    "poll.share": ("领先", "Leading"),
    "poll.note": (
        "票数保存在本机，用来确定开发优先级；公开投票会随 v2 正式发布接入。",
        "Votes are stored locally to set priorities; public voting ships with the real v2 release.",
    ),

    # ---------------------------------------------------------------- 功能项
    "f.version.title": ("版本管理", "Version manager"),
    "f.version.desc": (
        "官方稳定版、快照和历史版本统一列出，支持多版本并存隔离。",
        "Stable, snapshot and legacy builds listed together, side by side.",
    ),
    "f.loader.title": ("Forge / NeoForge 安装", "Forge / NeoForge installer"),
    "f.loader.desc": (
        "一键安装 Forge 或 NeoForge，自动处理好依赖与启动配置。",
        "Install Forge or NeoForge in one click, dependencies handled.",
    ),
    "f.launch.title": ("一键启动游戏", "One-click launch"),
    "f.launch.desc": (
        "选好版本点一下就进游戏，启动参数自动配好。",
        "Pick a version and jump in — launch args handled for you.",
    ),
    "f.memory.title": ("内存与参数分配", "Memory and JVM args"),
    "f.memory.desc": (
        "手动指定运行内存和 JVM 参数，避免卡顿和闪退。",
        "Set RAM and JVM args by hand to avoid stutters and crashes.",
    ),
    "f.modpack.title": ("整合包一键安装", "One-click modpack install"),
    "f.modpack.desc": (
        "选整合包，自动装好模组、配置和版本隔离。",
        "Pick a modpack and get mods, configs and version isolation handled.",
    ),
    "f.mod.title": ("模组下载", "Mod downloads"),
    "f.mod.desc": (
        "按加载器和游戏版本筛选 Modrinth 模组，一键安装。",
        "Filter Modrinth mods by loader and game version, install in one click.",
    ),
    "f.shader.title": ("光影下载", "Shader downloads"),
    "f.shader.desc": (
        "按游戏版本和显卡档位挑光影，自动装好所需前置。",
        "Pick shaders by game version and GPU tier, prerequisites handled.",
    ),
    "f.datapack.title": ("数据包下载", "Datapack downloads"),
    "f.datapack.desc": (
        "浏览并安装数据包，不用手动解压。",
        "Browse and install datapacks without manual unzipping.",
    ),
    "f.resource.title": ("资源包下载", "Resource pack downloads"),
    "f.resource.desc": (
        "一键下载并启用资源包，材质与字体随装随用。",
        "Grab and enable resource packs — textures and fonts ready to go.",
    ),
    "f.tunnel.title": ("一键联机", "One-click online play"),
    "f.tunnel.desc": (
        "bore 隧道直连，朋友不装客户端也能进来。",
        "bore tunneling lets friends join without any client install.",
    ),
    "f.account.title": ("账号登录与切换", "Accounts and switching"),
    "f.account.desc": (
        "离线、微软、外置账号并存，一键切换。",
        "Offline, Microsoft and authlib accounts side by side, switch fast.",
    ),
    "f.i18n.title": ("界面中英文切换", "Chinese / English UI"),
    "f.i18n.desc": (
        "整站一键切换中英文，所有文案同步更新。",
        "Flip the whole UI between Chinese and English in one tap.",
    ),
    "f.dldetail.title": ("下载详情与筛选", "Download details and filters"),
    "f.dldetail.desc": (
        "每个资源显示图标、简介、版本和更新时间，下载前看清楚。",
        "Icons, descriptions, versions and update times — know before you download.",
    ),

    # ---------------------------------------------------------------- 设置
    "settings.title": ("设置", "Settings"),
    "settings.sub": ("偏好与路径", "Preferences and paths"),
    "settings.open": ("打开目录", "Open folder"),
    "settings.language": ("界面语言", "Language"),
    "settings.memory": ("内存分配", "Memory"),
    "settings.java": ("Java 路径", "Java path"),
    "settings.datadir": ("数据目录", "Data folder"),
    "settings.about": ("关于", "About"),
    "settings.about.text": (
        "MC Lite 正式版 v1.5.0 · MIT 协议 · 开源在 GitHub",
        "MC Lite Official v1.5.0 · MIT licensed · open source on GitHub",
    ),
    "settings.autodetect": (
        "留空时启动器会自动探测本机 Java。",
        "Leave empty and the launcher auto-detects local Java.",
    ),
    "settings.pickjava": ("选择 javaw.exe", "Select javaw.exe"),
    "settings.appearance": ("外观", "Appearance"),
    "settings.theme": ("主题", "Theme"),
    "settings.accent": ("强调色", "Accent color"),
    "theme.dark": ("深色", "Dark"),
    "theme.light": ("浅色", "Light"),
    "theme.midnight": ("夜色蓝", "Midnight"),
    "theme.system": ("跟随系统", "Follow system"),

    # ---------------------------------------------------------------- 补全
    "common.v2badge": ("正式版 v1.5.0", "Official v1.5.0"),
    "common.browse": ("浏览", "Browse"),
    "common.saved": ("已保存", "Saved"),
    "common.badinput": ("输入无效", "Invalid input"),

    "versions.notready": (
        "安装流程还在接入中，可以先用 v1 安装，或等后续版本。",
        "The installer is still being wired up — use v1 for now, or wait for a later build.",
    ),
    "versions.vanilla": ("原版", "Vanilla"),
    "versions.launching": ("正在启动 %s…", "Launching %s…"),
    "versions.launched": ("已启动 %s", "Launched %s"),
    "versions.nojava": (
        "没找到可用的 Java，请到设置里指定 javaw.exe。",
        "No usable Java found — point Settings at javaw.exe.",
    ),

    # ---------------------------------------------------------------- 体检 / 崩溃
    "launch.checking": ("正在检查游戏文件…", "Checking game files…"),
    "launch.fixing": ("缺少 %s，正在自动补齐…", "Missing %s — repairing automatically…"),
    "launch.fixed": ("文件已补齐，正在启动", "Files repaired, launching"),
    "launch.repairfail": ("自动补齐失败：%s", "Auto-repair failed: %s"),
    "settings.diag": ("启动与诊断", "Launch and diagnostics"),
    "settings.autorepair": ("启动前自动补齐缺失文件", "Auto-repair missing files before launch"),
    "settings.autorepair.desc": (
        "每次启动前对比官方清单，缺的库和资源自动补上；不足 1 秒，不会重下已有文件。",
        "Checks the install against the official manifest before every launch and fetches only what is missing.",
    ),
    "settings.crashdesc": (
        "游戏崩溃后自动读 crash-reports 与 latest.log，给出人话原因和修复建议，可一键补齐重试。",
        "When the game crashes, it reads crash-reports and latest.log, explains the cause and offers a one-click repair.",
    ),
    "settings.on": ("已开启", "On"),
    "settings.off": ("已关闭", "Off"),
    "crash.title": ("游戏崩了，已自动分析", "The game crashed — analysis ready"),
    "crash.sub": ("退出码 %s · 找到 %d 条可能原因", "Exit code %s · %d probable cause(s)"),
    "crash.none": (
        "没匹配到明确原因，先看日志末尾这几行。",
        "No known pattern matched — check the last lines of the log.",
    ),
    "crash.tail": ("日志末尾", "End of log"),
    "crash.repair": ("自动补齐并重试", "Repair and retry"),
    "crash.openlogs": ("打开日志目录", "Open log folder"),
    "crash.save": ("保存诊断报告", "Save report"),
    "crash.saved": ("诊断报告已保存：%s", "Report saved to %s"),
    "crash.close": ("关闭", "Close"),
    "crash.retrying": ("正在补齐文件…", "Repairing files…"),
    "crash.repaired": ("补齐完成，再点一次启动就行", "Repaired — hit Launch again"),
    "crash.fixlabel": ("怎么办", "What to do"),

    "content.types": ("资源类型", "Resource type"),
    "content.tab.pack": ("整合包", "Modpacks"),
    "content.tab.res": ("资源包", "Resource packs"),
    "content.tab.data": ("数据包", "Data packs"),
    "content.filter.name": ("名称", "Name"),
    "content.filter.source": ("来源", "Source"),
    "content.filter.version": ("游戏版本", "Game version"),
    "content.filter.loader": ("加载器", "Loader"),
    "content.filter.sort": ("排序", "Sort"),
    "sort.relevance": ("相关度", "Relevance"),
    "sort.downloads": ("下载量", "Downloads"),
    "sort.newest": ("最新发布", "Newest"),
    "sort.updated": ("最近更新", "Recently updated"),
    "content.all": ("全部", "All"),
    "content.search.btn": ("搜索", "Search"),
    "content.reset": ("重置条件", "Reset"),
    "content.loading": ("正在加载…", "Loading…"),
    "content.fail": (
        "请求失败，检查网络后重试。",
        "Request failed — check your network and retry.",
    ),
    "content.count": ("{n} 个结果", "{n} results"),
    "content.get": ("下载", "Get"),
    "content.downloads": ("次下载", "downloads"),
    "content.detail.sub": ("项目详情", "Project details"),
    "content.detail.back": ("← 返回列表", "← Back to list"),
    "content.detail.desc": ("简介", "Description"),
    "content.detail.versions": ("可用版本", "Available versions"),
    "content.novers": (
        "没有匹配当前筛选条件的版本",
        "No versions match the current filters",
    ),
    "content.downloading": ("正在下载 %s", "Downloading %s"),
    "content.done": ("完成，安装了 %d 个文件", "Done — %d file(s) installed"),
    "content.done.pack": ("整合包已保存到 %s", "Modpack saved to %s"),

    # ---- 批次3 资源中心扩展 ----
    "content.tab.world": ("世界", "Worlds"),
    "content.tab.cf": ("CurseForge", "CurseForge"),
    "content.more": ("加载更多", "Load more"),
    "content.loading_more": ("正在加载更多…", "Loading more…"),
    "content.no_more": ("已加载全部结果", "All results loaded"),
    "content.install": ("安装", "Install"),
    "content.install_pack": ("安装到实例", "Install to instance"),
    "content.installing": ("正在安装…", "Installing…"),
    "content.install_done": ("安装完成，已装入当前实例。", "Installed into the current instance."),
    "content.install_fail": ("安装失败：%s", "Install failed: %s"),
    "content.shader.hint": ("光影已装入 shaderpacks/。光影需要 Iris 或 OptiFine 才能生效，本启动器不会自动安装光影加载器。",
                            "Shader installed to shaderpacks/. It needs Iris or OptiFine to take effect; the launcher does not install a shader loader automatically."),
    "content.resource.hint": ("资源包已装入 resourcepacks/。进游戏后在「选项 → 资源包」中启用。",
                              "Resource pack installed to resourcepacks/. Enable it in Options → Resource Packs in game."),
    "content.datapack.hint": ("数据包已装入实例级 datapacks/ 目录。若要按某个存档启用，可在后续「本地内容管理」中处理。",
                               "Data pack installed to the instance-level datapacks/ folder. Per-world enabling will be available in local content management later."),
    "content.world.honest": ("在线世界存档库暂无免费可用源：Modrinth 不托管世界存档（project_type:world 为 0 条），Planet Minecraft 本机网络被 Cloudflare 拦截。这里提供本地存档入口；在线世界请用浏览器自行查找并注意版权与安全。",
                              "No free online world-save source is available: Modrinth hosts no worlds (project_type:world returns 0), and Planet Minecraft is blocked by Cloudflare on this network. Use the local saves entry below; for online worlds, browse manually and mind copyright/safety."),
    "content.world.open_saves": ("打开当前实例 saves 目录", "Open current instance saves folder"),
    "content.world.ext_pm": ("浏览器打开 Planet Minecraft", "Open Planet Minecraft in browser"),
    "content.world.ext_gh": ("浏览器搜索 GitHub 存档", "Search GitHub for world saves"),
    "content.world.thirdparty": ("第三方站点内容与安全性由其各自负责，启动器不内置下载、不做绕过。",
                                  "Third-party sites are responsible for their own content and safety; the launcher does not bundle downloads or bypass restrictions."),
    "content.cf.title": ("CurseForge 内容源（未接入）", "CurseForge source (not connected)"),
    "content.cf.body": ("CurseForge 官方 API 需要免费申请的 API Key（需 CurseForge 账号），本启动器不内置 Key，也不绕过其下载限制或 CDN 访问控制。你可以在浏览器打开 CurseForge 手动下载 .jar/.mrpack，再通过「本地导入」安装（本地导入将在批次4 提供）。在线模组/整合包请使用左侧 Modrinth 源（免费、匿名、无需 Key）。",
                         "The official CurseForge API requires a free API key (CurseForge account); this launcher does not embed a key and does not bypass its download/CDN controls. Open CurseForge in a browser to download .jar/.mrpack manually, then use local import (coming in batch 4). For online mods/modpacks use the Modrinth source on the left (free, anonymous, no key)."),
    "content.cf.open_web": ("打开 CurseForge 网页", "Open CurseForge website"),
    "content.cf.guide": ("合规路径：浏览器下载 → 本地导入（批次4）→ 进入对应目录或走 .mrpack 安装器。",
                         "Compliant path: download in browser → local import (batch 4) → place in the right folder or run the .mrpack installer."),
    "content.pack.meta": ("MC %s · %s %s · %d 个文件 · 约 %s · overrides %d 项",
                          "MC %s · %s %s · %d files · ~%s · %d overrides"),
    "content.pack.meta_noloader": ("MC %s · %d 个文件 · 约 %s · overrides %d 项",
                                   "MC %s · %d files · ~%s · %d overrides"),
    "content.pack.updated": ("更新于 %s", "Updated %s"),
    "content.pack.target": ("安装到实例", "Target instance"),
    "content.pack.new_inst": ("＋ 新建实例…", "＋ New instance…"),
    "content.pack.new_name_title": ("新建实例", "New instance"),
    "content.pack.new_name_prompt": ("输入新实例名称：", "New instance name:"),
    "content.pack.start": ("开始安装", "Install"),
    "content.pack.retry": ("重试失败文件", "Retry failed files"),
    "content.pack.close": ("关闭", "Close"),
    "content.pack.ready": ("整合包已就绪，选择目标实例后开始安装。", "Pack ready. Pick a target instance and start."),
    "content.pack.downloading_pack": ("正在下载整合包本体并解析清单…", "Downloading pack and reading index…"),
    "content.pack.parse_fail": ("整合包清单解析失败，安装时会重新下载校验。", "Failed to parse pack index; it will be re-downloaded during install."),
    "content.pack.summary": ("完成：成功 %d/%d，跳过 %d，失败 %d，overrides %d 项，共约 %s。",
                             "Done: %d/%d ok, %d skipped, %d failed, %d overrides, ~%s total."),
    "content.pack.failed_title": ("以下文件下载失败，可点「重试失败文件」：", "Failed files (click Retry to try again):"),
    "content.pack.stage.runtime": ("阶段 1/3：安装原版与加载器", "Stage 1/3: install vanilla & loader"),
    "content.pack.stage.files": ("阶段 2/3：下载整合包文件", "Stage 2/3: download pack files"),
    "content.pack.stage.overrides": ("阶段 3/3：拷贝 overrides 配置", "Stage 3/3: copy overrides"),
    "content.pack.stage.done": ("安装结束", "Finished"),
    "content.pack.need_java": ("安装 Forge/NeoForge 加载器需要本机 Java，请先在设置中配置 Java 路径。",
                                "Installing Forge/NeoForge requires local Java; configure the Java path in Settings first."),
    "content.pack.installed_to": ("已安装到实例「%s」。可在版本页选择对应加载器版本启动。",
                                   "Installed into instance “%s”. Select the matching loader version on the Versions page to launch."),
    "content.pack.detail_loading": ("正在读取整合包清单（下载 .mrpack 本体）…", "Reading pack index (downloading .mrpack)…"),
    "content.pack.detail_fail": ("整合包清单暂不可读，可直接点「安装到实例」，安装时会重新下载。",
                                  "Pack index unavailable; click Install to instance — it re-downloads during install."),
    "content.detail.install_pack": ("安装到实例", "Install to instance"),

    "online.portfound": ("检测到端口 %s", "Detected port %s"),
    "online.portmissing": (
        "没读到端口，请先在游戏里对局域网开放。",
        "No port found — open the world to LAN first.",
    ),
    "online.stopped": ("隧道已关闭", "Tunnel closed"),
    "online.badport": ("端口格式不对", "Invalid port"),
    "online.connecting": ("正在连接 bore 服务器…", "Connecting to bore…"),
    "online.connected": ("隧道已就绪，把地址发给好友。", "Tunnel ready — send the address out."),

    "poll.thanks": ("已记录你的一票", "Vote recorded"),
    "poll.already": ("这个功能你已经投过了", "You already voted for this one"),
    "poll.resetdone": ("已重置我的投票", "My votes were reset"),

    "time.today": ("今天", "today"),
    "time.days": ("{n} 天前", "{n} days ago"),
    "time.months": ("{n} 个月前", "{n} months ago"),
    "time.years": ("{n} 年前", "{n} years ago"),

    "f.version.icon": ("版", "V"),
    "f.loader.icon": ("加", "L"),
    "f.launch.icon": ("启", "S"),
    "f.memory.icon": ("存", "M"),
    "f.modpack.icon": ("包", "P"),
    "f.mod.icon": ("模", "M"),
    "f.shader.icon": ("光", "S"),
    "f.datapack.icon": ("数", "D"),
    "f.resource.icon": ("材", "R"),
    "f.tunnel.icon": ("联", "O"),
    "f.account.icon": ("号", "A"),
    "f.i18n.icon": ("语", "I"),
    "f.dldetail.icon": ("详", "D"),
}




