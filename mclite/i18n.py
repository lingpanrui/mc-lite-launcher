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
    "versions.current": ("当前使用", "In use"),
    "versions.loader": ("加载器", "Loader"),
    "versions.dir": ("版本目录", "Version folder"),

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
        "MC Lite 正式版 v1.0 · MIT 协议 · 开源在 GitHub",
        "MC Lite Official v1.0 · MIT licensed · open source on GitHub",
    ),
    "settings.autodetect": (
        "留空时启动器会自动探测本机 Java。",
        "Leave empty and the launcher auto-detects local Java.",
    ),
    "settings.pickjava": ("选择 javaw.exe", "Select javaw.exe"),

    # ---------------------------------------------------------------- 补全
    "common.v2badge": ("正式版 v1.0", "Official v1.0"),
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



