# -*- coding: utf-8 -*-
"""游戏文件体检 + 崩溃自动分析

两个能力：
1. inspect() / repair()  启动前检查版本文件是否齐全，缺了就用 Mojang 官方源补
2. analyze()            游戏非正常退出后，读 crash-reports / latest.log，按规则给出人话结论
"""
import glob
import os
import re
import time

from . import util
from .i18n import get_lang


def _en():
    return get_lang() == "en"


def _txt(pair):
    return pair[1] if _en() else pair[0]


# ---------------------------------------------------------------- 文件体检
def inspect(game_dir, vid):
    """检查一个版本能不能正常启动，返回缺失统计（不做下载）"""
    from . import mojang

    res = {
        "ok": True,
        "version_missing": False,
        "missing_jar": False,
        "missing_libs": 0,
        "missing_assets": 0,
        "total_assets": 0,
        "natives_empty": False,
        "missing_lib_names": [],
        "error": "",
        "checked": 0,
    }
    vdir = os.path.join(game_dir, "versions", vid)
    jpath = os.path.join(vdir, vid + ".json")
    if not os.path.isfile(jpath):
        res.update(ok=False, version_missing=True)
        res["error"] = "版本文件缺失：versions\\%s\\%s.json" % (vid, vid)
        return res

    try:
        vj, root = mojang.resolve_version(game_dir, vid)
    except Exception as e:
        res.update(ok=False, error=str(e))
        return res

    # 1) 客户端核心 jar
    root_jar = os.path.join(game_dir, "versions", root, root + ".jar")
    local_jar = os.path.join(vdir, vid + ".jar")
    dl = (vj.get("downloads") or {}).get("client") or {}
    if os.path.isfile(root_jar):
        size = dl.get("size")
        if size and os.path.getsize(root_jar) != size:
            res["missing_jar"] = True
    elif os.path.isfile(local_jar):
        pass
    elif dl.get("url") or root in {v for v in [vid]}:
        # 1.20 之后的版本一定有 client jar；老版本同目录也可能没有
        res["missing_jar"] = bool(dl.get("url"))

    # 2) 依赖库
    libs_dir = os.path.join(game_dir, "libraries")
    missing = []
    checked = 0
    for lib in vj.get("libraries") or []:
        if not mojang.rules_allow(lib.get("rules")):
            continue
        art = (lib.get("downloads") or {}).get("artifact") or {}
        rel = art.get("path") or (mojang.maven_to_path(lib["name"]) if lib.get("name") else "")
        if not rel:
            continue
        checked += 1
        p = os.path.join(libs_dir, rel.replace("/", os.sep))
        if not os.path.isfile(p):
            missing.append(os.path.basename(rel))
    res["missing_libs"] = len(missing)
    res["missing_lib_names"] = missing[:5]
    res["checked"] = checked

    # 3) 资源文件
    ai = vj.get("assetIndex") or {}
    idx_id = str(ai.get("id") or vj.get("assets") or "legacy")
    idx_path = os.path.join(game_dir, "assets", "indexes", idx_id + ".json")
    if os.path.isfile(idx_path):
        try:
            objects = (util.read_json(idx_path, {}) or {}).get("objects") or {}
        except Exception:
            objects = {}
        if objects:
            obj_dir = os.path.join(game_dir, "assets", "objects")
            miss = 0
            for _name, o in objects.items():
                h = str((o or {}).get("hash") or "")
                if len(h) >= 2 and not os.path.isfile(os.path.join(obj_dir, h[:2], h)):
                    miss += 1
            res["missing_assets"] = miss
            res["total_assets"] = len(objects)

    # 4) 原生库（老版本才需要解压到 natives 目录）
    nat_dir = os.path.join(game_dir, "versions", root, "natives")
    has_native_decl = any((lib.get("natives") or {}) for lib in (vj.get("libraries") or []))
    if has_native_decl:
        try:
            files = os.listdir(nat_dir)
        except Exception:
            files = []
        if not any(f.lower().endswith((".dll", ".so", ".dylib")) for f in files):
            res["natives_empty"] = True

    res["ok"] = not (
        res["missing_jar"] or res["missing_libs"] or res["missing_assets"] or res["natives_empty"]
    )
    return res


def describe_missing(info):
    """把 inspect 结果翻译成一句人话"""
    parts = []
    if info.get("version_missing"):
        return _txt(("版本文件本身都不在了，得重新安装这个版本",
                     "The version files themselves are gone — reinstall it"))
    if info.get("missing_jar"):
        parts.append(_txt(("客户端核心 jar", "client jar")))
    if info.get("missing_libs"):
        parts.append(_txt(("%d 个依赖库" % info["missing_libs"], "%d libraries" % info["missing_libs"])))
    if info.get("missing_assets"):
        parts.append(_txt(("%d 个游戏资源" % info["missing_assets"], "%d assets" % info["missing_assets"])))
    if info.get("natives_empty"):
        parts.append(_txt(("原生库（natives）", "native libraries")))
    if not parts:
        return ""
    return _txt(("缺少 %s" % "、".join(parts), "missing " + ", ".join(parts)))


def repair(game_dir, vid, status=None, progress=None):
    """按官方清单补齐缺失文件（幂等，已存在且校验通过的不会重下）"""
    from . import mojang

    manifest = {}
    try:
        manifest = mojang.manifest_map(mojang.get_manifest())
    except Exception:
        manifest = {}
    ins = mojang.Installer(game_dir, manifest, status=status, progress=progress)
    ins.install(vid)
    return True


# ---------------------------------------------------------------- 日志定位
def _read_text(path, limit=300000):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()[:limit]
    except Exception:
        return ""


def latest_crash(game_dir, max_age=1800):
    """最近半小时内的崩溃报告（没有就返回 None）"""
    d = os.path.join(game_dir, "crash-reports")
    try:
        files = glob.glob(os.path.join(d, "crash-*.txt"))
    except Exception:
        return None
    if not files:
        return None
    newest = max(files, key=lambda p: os.path.getmtime(p))
    if time.time() - os.path.getmtime(newest) > max_age:
        return None
    return newest


def latest_log(game_dir):
    p = os.path.join(game_dir, "logs", "latest.log")
    return p if os.path.isfile(p) else None


def crash_description(text):
    """从崩溃报告里抽 Description 段落和第一行异常"""
    desc = ""
    m = re.search(r"Description:\s*(.+?)\n\s*\n", text)
    if m:
        desc = " ".join(m.group(1).split())
    exc = ""
    for line in text.splitlines():
        if re.match(r"^(java\.|net\.|com\.|org\.|net\.minecraft)\S*(Exception|Error)", line.strip()) \
                or "Exception in thread" in line:
            exc = line.strip()
            break
    return desc, exc


# ---------------------------------------------------------------- 规则库
def _rule(code, pat, sev, action, zh, en):
    return {
        "code": code,
        "pat": re.compile(pat),
        "sev": sev,
        "action": action,
        "zh": zh,
        "en": en,
    }


RULES = [
    _rule(
        "oom", r"OutOfMemoryError|Java heap space|GC overhead limit exceeded",
        "error", "memory",
        ("内存被撑爆了",
         "游戏分配到的堆内存不够，日志里出现 java.lang.OutOfMemoryError。",
         "到设置里把内存调到 4096 MB 以上，16G 内存的机器可以给 6144；"
         "装了大整合包或高清材质再加 2048。顺手把渲染距离降两格、关掉超高清材质，见效最快。"),
        ("Out of memory",
         "The game ran out of heap memory (java.lang.OutOfMemoryError).",
         "Raise memory in Settings to 4096 MB or more (6144 MB on a 16 GB machine). "
         "Add another 2048 MB for big modpacks or HD textures, and lower render distance a bit.")),
    _rule(
        "heap_bad", r"Invalid maximum heap size|Invalid initial heap size|Could not reserve enough space",
        "error", "memory",
        ("启动参数里的内存值不合理",
         "Java 拒绝了这个内存参数，通常是数值超过了物理内存，或者用的是 32 位 Java。",
         "把内存改小到物理内存的一半以内（比如 8G 机器给 4096），并确认用的是 64 位 Java。"),
        ("Invalid memory setting",
         "Java rejected the heap size — it is larger than physical RAM, or you are on 32-bit Java.",
         "Set memory below half of your RAM (4096 on an 8 GB machine) and make sure the Java is 64-bit.")),
    _rule(
        "javaver", r"UnsupportedClassVersionError|Unsupported major\.minor|requires Java \d"
        r"|compiled by a more recent version of the Java|class file version \d+\.\d+",
        "error", "java",
        ("Java 版本对不上",
         "这个版本要的 Java 比你当前用的新（或旧），类文件根本没法加载。",
         "1.17 及以上用 Java 17 或 21，1.16.5 及以下用 Java 8。到设置里把 Java 路径换成对应的 javaw.exe，"
         "不确定的话点「自动检测」让启动器自己挑。"),
        ("Wrong Java version",
         "The Java you are using is too old or too new for this game version.",
         "Use Java 17/21 for 1.17+ and Java 8 for 1.16.5 and below. Point Settings at the matching javaw.exe.")),
    _rule(
        "opengl", r"Failed to create window|GLFW error|Pixel format not accelerated|LWJGLException"
        r"|does not support OpenGL|Couldn't set pixel format|Unable to initialize GLFW|GL_OUT_OF_MEMORY"
        r"|OpenGL 3\.2|Failed to initialize GLFW",
        "error", "driver",
        ("显卡或驱动卡在了图形初始化这一步",
         "游戏在创建窗口/初始化 OpenGL 时就挂了，跟模组和内存都无关。",
         "先更新显卡驱动（NVIDIA/AMD 官方驱动，不要用系统自带的通用驱动）；"
         "笔记本要确认游戏跑在独显上；还不行就在启动参数里加 -Dfml.earlyprogresswindow=false 试试。"),
        ("Graphics / OpenGL failure",
         "The game died while creating its window or initialising OpenGL — not a mod or memory problem.",
         "Update the GPU driver from NVIDIA/AMD directly, make sure the laptop uses the discrete GPU, "
         "and try adding -Dfml.earlyprogresswindow=false.")),
    _rule(
        "mixin", r"MixinTransformerError|Mixin apply|Critical injection failure|MixinApplyError"
        r"|InvalidMixinException|MixinConfig",
        "error", "mod",
        ("模组的注入（Mixin）崩了",
         "某个模组在改写游戏代码时失败，日志里是 Mixin 相关异常。",
         "看崩溃报告里紧跟的模组名，先把最新的那个模组单独移出 mods 目录试；"
         "同一功能装了两个模组（比如两个优化模组）也常这样，留一个就行。"),
        ("Mixin injection crash",
         "A mod failed while patching game code (Mixin error).",
         "Check the mod name right after the exception, remove that mod and test. "
         "Two mods doing the same job (e.g. two optimisers) also triggers this.")),
    _rule(
        "dep_missing", r"Missing or unsupported mandatory dependencies|Mod resolution failed"
        r"|Incompatible mod set|which is missing|Missing dependencies|requires .* version",
        "error", "mod",
        ("模组缺前置或版本不兼容",
         "加载器明确说某些模组缺少前置，或者互相要求的版本打架。",
         "按报告里列的模组名去内容页搜同名前置（Fabric API、Architectury 这类最常见），"
         "或者把不兼容的那个卸掉。装模组时优先选和游戏版本、加载器完全对得上的。"),
        ("Missing mod dependency",
         "The loader says a mod is missing a dependency, or the mod set is incompatible.",
         "Install the listed dependency (Fabric API / Architectury are the usual suspects) "
         "or remove the incompatible mod. Match game version and loader exactly.")),
    _rule(
        "nomethod", r"NoSuchMethodError|NoSuchFieldError|AbstractMethodError|ClassCastException.*mod",
        "error", "mod",
        ("模组和游戏版本不匹配",
         "模组按旧版本的接口去调用，结果方法签名变了 —— 典型的下错版本模组。",
         "把报错里点名的模组换成对应游戏版本的构建；同一模组的 Forge 版别丢进 Fabric 的 mods 里。"),
        ("Mod built for another version",
         "A mod calls an API that changed — the classic symptom of a mismatched mod build.",
         "Replace the named mod with the build for your exact game version, "
         "and never drop a Forge jar into a Fabric mods folder.")),
    _rule(
        "missing_files", r"FileNotFoundException|Couldn't download|Failed to download|assets/indexes"
        r"|Unable to access|NoSuchFileException|Missing file|invalid or corrupted",
        "error", "repair",
        ("游戏文件缺了或被改坏",
         "日志里是文件找不到 / 下载失败，本地资源不完整。",
         "点下面的「自动补齐」就行，启动器会按官方清单把缺的库和资源重新拉一遍，已有的会跳过。"),
        ("Game files missing or corrupted",
         "Logs show missing files or failed downloads — the local install is incomplete.",
         "Hit Repair below: it re-fetches only the missing libraries and assets from the official source.")),
    _rule(
        "natives", r"UnsatisfiedLinkError|no lwjgl|lwjgl64|Failed to load natives|native library",
        "error", "repair",
        ("原生库没解压出来",
         "LWJGL 的 dll 没找到，游戏一启动就报 UnsatisfiedLinkError。",
         "点「自动补齐」重新解压原生库；如果是被杀毒软件删了 dll，把游戏目录加进白名单。"),
        ("Native libraries missing",
         "LWJGL DLLs were not found (UnsatisfiedLinkError).",
         "Use Repair to re-extract them; if antivirus deleted the DLLs, whitelist the game folder.")),
    _rule(
        "mainclass", r"Could not find or load main class|ClassNotFoundException",
        "error", "repair",
        ("客户端核心缺失",
         "找不到主类，通常就是版本 jar 被删了或下载没下完。",
         "点「自动补齐」重新下载核心 jar；还不行就在版本页把这个版本删掉重装。"),
        ("Client jar missing",
         "The main class can't be found — the version jar is gone or half-downloaded.",
         "Use Repair to re-download it; if that fails, reinstall the version.")),
    _rule(
        "auth", r"Failed to login|AuthenticationException|Invalid credentials|authlib|401 Unauthorized",
        "warn", "auth",
        ("登录被拒了",
         "账号认证这一步失败，可能是会话过期或者外置登录地址不对。",
         "重新登录一次；用外置登录（LittleSkin 之类）的话，去设置确认认证地址还通着，"
         "顺便试试离线模式能不能进 —— 能进就说明是账号问题不是游戏问题。"),
        ("Login rejected",
         "Authentication failed — expired session or a wrong auth server.",
         "Log in again; if you use an external auth (LittleSkin etc.), check the URL in Settings. "
         "Try offline mode once — if it launches, it's an account issue, not the game.")),
    _rule(
        "shader", r"OptiFine|shadersmod|ShaderPack|Iris.*Exception|Complementary",
        "warn", "mod",
        ("光影相关的兼容问题",
         "光影模组（OptiFine / Iris）在加载着色器时报错。",
         "换成 Iris + Sodium 这套组合，别和 OptiFine 混用；光影包要选对应游戏版本的。"),
        ("Shader compatibility issue",
         "OptiFine / Iris failed while loading shaders.",
         "Use Iris + Sodium instead of OptiFine, and pick shader packs built for your version.")),
]

TAIL_RULES = [
    _rule(
        "crash_generic", r"Exception in thread \"main\"|The game crashed|A fatal error has been detected",
        "error", "none",
        ("游戏抛异常退出了",
         "游戏线程出现异常直接结束，具体原因要看下面的原文。",
         "先看「更多信息」里的第一行异常；不确定的话把完整报告发到视频评论区，"
         "或者去 GitHub 提个 issue，把 crash-reports 里最新的文件带上。"),
        ("The game threw an exception and quit",
         "A fatal exception ended the game thread.",
         "Check the first exception line under Details. If unsure, post the crash report on GitHub issues.")),
]


def _tail_records(game_dir, limit=60):
    """从 latest.log 末尾找 ERROR / FATAL 行"""
    out = []
    p = latest_log(game_dir)
    if not p:
        return out
    text = _read_text(p, 400000)
    for line in text.splitlines()[-1200:]:
        if "ERROR" in line or "FATAL" in line or "Exception" in line or "Caused by" in line:
            if len(line) < 400:
                out.append(line.strip())
    return out[-limit:]


def analyze(game_dir, vid, exit_code=0, output_lines=None):
    """分析一次异常退出，返回结论列表（每条含 code/sev/title/detail/fix/action/evidence）"""
    texts = []
    source = ""

    crash = latest_crash(game_dir)
    if crash:
        texts.append(_read_text(crash))
        source = crash
    log = latest_log(game_dir)
    if log:
        texts.append(_read_text(log, 400000)[-200000:])
        source = source or log
    if output_lines:
        texts.append("\n".join(output_lines[-400:]))

    blob = "\n".join(texts)
    lower = blob  # 保留大小写，规则里自己处理

    hits = []
    for r in RULES:
        if r["pat"].search(lower):
            hits.append(r)
    if not hits and exit_code not in (0, None):
        for r in TAIL_RULES:
            if r["pat"].search(lower):
                hits.append(r)
        if not hits:
            hits.append(TAIL_RULES[0])

    desc, exc = crash_description(blob) if crash else ("", "")
    tail = _tail_records(game_dir)

    sev_rank = {"error": 0, "warn": 1}
    hits.sort(key=lambda r: sev_rank.get(r["sev"], 2))

    results = []
    for r in hits[:4]:
        body = r["en"] if _en() else r["zh"]
        title, detail, fix = body
        if not detail and exc:
            detail = exc
        results.append({
            "code": r["code"],
            "sev": r["sev"],
            "title": title,
            "detail": detail,
            "fix": fix,
            "action": r["action"],
            "evidence": exc or (tail[-1] if tail else ""),
        })

    if desc:
        results.insert(0, {
            "code": "summary",
            "sev": "info",
            "title": _txt(("崩溃报告摘要", "Crash report summary")),
            "detail": desc,
            "fix": "",
            "action": "none",
            "evidence": "",
        })

    return {
        "findings": results,
        "source": source,
        "exit_code": exit_code,
        "tail": tail[-6:],
        "crash": crash or "",
        "log": log or "",
    }


def save_report(game_dir, result, vid=""):
    """把一次分析结果落盘，方便用户自己发出去"""
    path = os.path.join(game_dir, "mclite-diagnose-%s.txt" % time.strftime("%Y%m%d-%H%M%S"))
    lines = [
        "MC Lite 崩溃诊断报告",
        "时间: %s" % time.strftime("%Y-%m-%d %H:%M:%S"),
        "版本: %s" % vid,
        "退出码: %s" % result.get("exit_code"),
        "崩溃报告: %s" % (result.get("crash") or "无"),
        "最新日志: %s" % (result.get("log") or "无"),
        "",
        "== 结论 ==",
    ]
    for f in result.get("findings") or []:
        lines += ["[%s] %s" % (f["sev"], f["title"]), "  原因: %s" % f["detail"],
                  "  建议: %s" % f["fix"], ""]
    if result.get("tail"):
        lines += ["== 日志末尾 =="] + list(result["tail"])
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
    except Exception:
        return ""
    return path
