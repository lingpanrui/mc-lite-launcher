# -*- coding: utf-8 -*-
"""装前模组冲突预检 + 崩后归因 + 一键修复（批次6，v1.8.0）

复用批次4 ``localcontent.detect_mod_info`` 的解析结果（含本批扩展的 ``dep_list``），
不重写 jar 解析器。扫描目标实例 ``mods/`` 下启用中与 ``.disabled`` 的全部 jar，检出：

- duplicate_id   重复 mod id（报出哪两个文件冲突）
- missing_dep    缺失前置依赖（报出缺哪个 mod id）
- dep_version    依赖版本区间不满足
- mc_version     模组声明的 Minecraft 版本与实例不符（如 1.21.x 模组进 1.20.1）
- loader_mismatch 加载器不匹配（fabric 进 forge、forge/neoforge 混装）
- java_version   模组要求的 Java 高于实例实际 Java
- unreadable     无法读取元数据（可能不是有效模组 jar）

每条问题带「人话结论 + 可执行建议 + 可选 fix 动作」。一键修复支持：
- disable / enable：调用批次4 的 .disabled 后缀切换（幂等、不覆盖）；
- install_dep：经 Modrinth 公开 API 解析并补装缺失依赖到 mods/（免费、无需 key）。

纯本地扫描不联网；只有「查可用版本 / 补装依赖」才走网络，失败如实返回。
"""
import os
import re

from . import localcontent, util
from .i18n import get_lang

# 平台自身 id，不作为「缺失模组依赖」处理
PLATFORM_IDS = {
    "minecraft", "java", "fabricloader", "fabric-loader", "forge", "neoforge",
    "fml", "quilt_loader", "quilt-loader", "quilt", "minecraftforge",
}

SEV_RANK = {"error": 0, "warn": 1, "info": 2}


def _L(zh, en):
    return en if get_lang() == "en" else zh


# ================================================================ 版本约束
def vparts(v):
    """把版本号拆成整数元组（忽略 +build 与非数字前缀），无法解析返回 ()。"""
    if v is None:
        return ()
    s = str(v).strip().split("+", 1)[0].lstrip("vV")
    nums = re.findall(r"\d+", s)
    return tuple(int(x) for x in nums[:4]) if nums else ()


def cmp_version(a, b):
    pa, pb = vparts(a), vparts(b)
    n = max(len(pa), len(pb))
    pa = pa + (0,) * (n - len(pa))
    pb = pb + (0,) * (n - len(pb))
    return (pa > pb) - (pa < pb)


def _bump(v, idx):
    p = list(vparts(v))
    while len(p) <= idx:
        p.append(0)
    p[idx] += 1
    for i in range(idx + 1, len(p)):
        p[i] = 0
    return ".".join(str(x) for x in p)


def _cmp_op(ver, op, target):
    c = cmp_version(ver, target)
    return {
        "=": c == 0, "==": c == 0, ">": c > 0, "<": c < 0,
        ">=": c >= 0, "<=": c <= 0,
    }.get(op, c == 0)


def _token_satisfies(ver, tok):
    tok = (tok or "").strip()
    if not tok or tok == "*":
        return True
    # 通配：1.x / 1.2.x
    if tok.endswith(".x"):
        pre = tok[:-2]
        return str(ver).startswith(pre + ".") or str(ver) == pre
    for op in (">=", "<=", "==", ">", "<", "=", "^", "~"):
        if tok.startswith(op):
            target = tok[len(op):].strip()
            if not target:
                return True
            if op == "^":
                if cmp_version(ver, target) < 0:
                    return False
                p = vparts(target)
                idx = 0 if (p and p[0] > 0) else 1
                return cmp_version(ver, _bump(target, idx)) < 0
            if op == "~":
                if cmp_version(ver, target) < 0:
                    return False
                p = vparts(target)
                idx = 1 if len(p) > 1 else 0
                return cmp_version(ver, _bump(target, idx)) < 0
            return _cmp_op(ver, op, target)
    return cmp_version(ver, tok) == 0


def _maven_interval(ver, c):
    """Maven 区间：[1.0,2.0) / [1.0,] / (,2.0] 等。"""
    lo_inc = c[0] == "["
    hi_inc = c[-1] == "]"
    inner = c[1:-1]
    parts = inner.split(",")
    lo = parts[0].strip()
    hi = parts[1].strip() if len(parts) > 1 else ""
    if lo:
        if cmp_version(ver, lo) < 0:
            return False
        if not lo_inc and cmp_version(ver, lo) == 0:
            return False
    if hi:
        if cmp_version(ver, hi) > 0:
            return False
        if not hi_inc and cmp_version(ver, hi) == 0:
            return False
    return True


def satisfies(version, constraint):
    """判断 ``version`` 是否满足约束表达式；约束为空 / 无法解析时按满足处理（不误报）。"""
    if constraint is None:
        return True
    c = str(constraint).strip()
    if not c or c in ("*", "latest", "any"):
        return True
    try:
        if c[0] in "[(":
            return _maven_interval(version, c)
        for tok in c.replace(",", " ").split():
            if not _token_satisfies(version, tok):
                return False
        return True
    except Exception:
        return True


def java_major_required(constraint):
    """从 ``>=17`` / ``>=1.8`` 这类 Java 约束里取主版本号；取不到返回 0。"""
    if not constraint:
        return 0
    m = re.search(r"(\d+)(?:\.(\d+))?", str(constraint))
    if not m:
        return 0
    first = int(m.group(1))
    second = int(m.group(2)) if m.group(2) else 0
    if first == 1 and second:
        return second
    return first


def mc_version_from_id(vid):
    """从版本 id / 目录名抽 MC 版本：1.20.1-Forge -> 1.20.1；26.2-Fabric -> 26.2。"""
    m = re.search(r"(\d+\.\d+(?:\.\d+)?)", str(vid or ""))
    return m.group(1) if m else ""


# ================================================================ 实例上下文
def instance_context(game_dir, last_version="", java_path=""):
    """汇总预检所需的加载器 / MC 版本 / Java 主版本（读不到给空值，不报错）。"""
    game_dir = os.path.abspath(game_dir)
    loader = localcontent.instance_loader(game_dir, last_version)
    mc_version = ""
    if last_version:
        jp = os.path.join(game_dir, "versions", last_version, last_version + ".json")
        meta = util.read_json(jp, default=None) or {}
        mc_version = str(meta.get("inheritsFrom") or "") or mc_version_from_id(
            meta.get("id") or last_version)
    java_major = 0
    if java_path and os.path.isfile(java_path):
        try:
            from . import java as jm
            java_major, _v = jm.java_major(java_path)
        except Exception:
            java_major = 0
    return {"loader": loader, "mc_version": mc_version, "java_major": int(java_major or 0)}


# ================================================================ 扫描
def _mod_record(it):
    info = it.get("info") or localcontent.detect_mod_info(it["path"])
    return {
        "name": it.get("name"),
        "base_name": it.get("base_name"),
        "path": it.get("path"),
        "enabled": bool(it.get("enabled")),
        "size": it.get("size") or 0,
        "loaders": list(info.get("loaders") or []),
        "ids": list(info.get("ids") or []),
        "mod_name": info.get("name"),
        "version": info.get("version"),
        "java": info.get("java"),
        "dep_list": list(info.get("dep_list") or []),
    }


def _issue(code, sev, title, detail, suggestion, files=None, mod_ids=None, fix=None, enabled=True):
    return {
        "code": code, "sev": sev, "title": title, "detail": detail,
        "suggestion": suggestion, "files": files or [], "mod_ids": mod_ids or [],
        "fix": fix, "enabled": enabled,
    }


def scan_instance(game_dir, inst_loader="", mc_version="", java_major=None):
    """扫描当前实例 mods/，返回结构化预检报告（不做任何修改）。

    返回：{game_dir, loader, mc_version, java_major, mod_count, enabled_count,
           issues, summary, ok, mods}
    """
    game_dir = os.path.abspath(game_dir)
    if java_major is None:
        java_major = 0
    items = localcontent.scan_category(game_dir, "mod", inst_loader=inst_loader)
    mods = [_mod_record(it) for it in items]

    by_id = {}
    for m in mods:
        for mid in m["ids"]:
            by_id.setdefault(mid, []).append(m)

    issues = []

    # 1) 重复 mod id
    for mid, recs in by_id.items():
        if len(recs) < 2:
            continue
        active = [r for r in recs if r["enabled"]]
        names = "、".join(os.path.basename(r["path"]) for r in recs)
        if len(active) >= 2:
            def score(r):
                s = 0
                if inst_loader and inst_loader in r["loaders"]:
                    s += 10
                if r.get("version"):
                    s += max(0, cmp_version(r["version"], "0.0.0"))
                return s
            keeper = max(active, key=score)
            losers = [r for r in active if r is not keeper]
            issues.append(_issue(
                "duplicate_id", "error",
                _L("检测到重复模组 id：%s" % mid, "Duplicate mod id: %s" % mid),
                _L("以下文件都声明了同一个 mod id「%s」，同时启用会冲突：%s。"
                   % (mid, names),
                   "These files all declare mod id \"%s\" and enabling them together conflicts: %s."
                   % (mid, names)),
                _L("建议保留与当前加载器匹配、版本较新的「%s」，禁用其余 %d 个（可一键禁用）。"
                   % (os.path.basename(keeper["path"]), len(losers)),
                   "Keep the loader-matching, newer \"%s\" and disable the other %d (one-click)."
                   % (os.path.basename(keeper["path"]), len(losers))),
                files=[r["path"] for r in recs], mod_ids=[mid],
                fix={"type": "disable", "paths": [r["path"] for r in losers]}))
        elif active:
            issues.append(_issue(
                "duplicate_id", "info",
                _L("重复 id「%s」但其余副本已禁用" % mid, "Duplicate id \"%s\" but others disabled" % mid),
                _L("文件：%s；当前只有一个启用，不会同时加载。" % names,
                   "Files: %s; only one is enabled, so they won't load together." % names),
                _L("无需处理；若确认不再需要，可在「已安装」里删除多余副本。",
                   "No action needed; delete extra copies in Installed if unwanted."),
                files=[r["path"] for r in recs], mod_ids=[mid], enabled=False))
        else:
            issues.append(_issue(
                "duplicate_id", "info",
                _L("重复 id「%s」的副本均已禁用" % mid, "Duplicate id \"%s\" copies all disabled" % mid),
                _L("文件：%s。" % names, "Files: %s." % names),
                _L("不会加载，可忽略或删除多余文件。", "Not loaded; ignore or delete extras."),
                files=[r["path"] for r in recs], mod_ids=[mid], enabled=False))

    # 2) 依赖 / 版本 / 加载器 / Java（只对启用中的模组做强制判定）
    for m in mods:
        if not m["enabled"]:
            continue
        fname = os.path.basename(m["path"])
        mlabel = m.get("mod_name") or (m["ids"][0] if m["ids"] else fname)

        # 2a) 加载器不匹配
        if inst_loader and m["loaders"] and inst_loader not in m["loaders"]:
            issues.append(_issue(
                "loader_mismatch", "error",
                _L("加载器不匹配：%s" % fname, "Loader mismatch: %s" % fname),
                _L("「%s」面向 %s，当前实例加载器是 %s；强行放入可能无法加载或直接崩溃。"
                   % (mlabel, " / ".join(m["loaders"]), inst_loader),
                   "\"%s\" is built for %s, but this instance uses %s; it may fail to load or crash."
                   % (mlabel, " / ".join(m["loaders"]), inst_loader)),
                _L("换成与 %s 匹配的版本，或先禁用该文件（可一键禁用）。" % inst_loader,
                   "Use a %s build, or disable this file (one-click)." % inst_loader),
                files=[m["path"]], mod_ids=m["ids"],
                fix={"type": "disable", "paths": [m["path"]]}))

        # 2b) 依赖声明（含 minecraft / java 平台约束，统一在下面的循环里判定，避免重复）
        for dep in m.get("dep_list") or []:
            did = str(dep.get("mod_id") or "").strip()
            rng = dep.get("range")
            if not did:
                continue

            if did == "minecraft":
                if mc_version and rng and not satisfies(mc_version, rng):
                    issues.append(_issue(
                        "mc_version", "error",
                        _L("模组与游戏版本不符：%s" % fname, "Mod vs game version mismatch: %s" % fname),
                        _L("「%s」要求 Minecraft %s，当前实例是 %s。"
                           % (mlabel, rng, mc_version),
                           "\"%s\" requires Minecraft %s, but this instance is %s."
                           % (mlabel, rng, mc_version)),
                        _L("下载对应 %s 的模组构建，或把实例切到匹配的 MC 版本。" % mc_version,
                           "Download a build for %s, or switch the instance to a matching MC version."
                           % mc_version),
                        files=[m["path"]], mod_ids=m["ids"]))
                continue

            if did == "java":
                if java_major and rng:
                    req = java_major_required(rng)
                    if req and java_major < req:
                        issues.append(_issue(
                            "java_version", "error",
                            _L("前置要求 Java 版本不足：%s" % fname, "Dependency Java too old: %s" % fname),
                            _L("「%s」依赖 java %s，当前 Java %d。" % (mlabel, rng, java_major),
                               "\"%s\" depends on java %s, current Java %d." % (mlabel, rng, java_major)),
                            _L("在设置里换成更高版本 Java。", "Switch to a newer Java in Settings."),
                            files=[m["path"]], mod_ids=m["ids"]))
                continue

            if did in PLATFORM_IDS:
                continue

            providers = by_id.get(did, [])
            active_prov = [p for p in providers if p["enabled"]]
            if not providers:
                issues.append(_issue(
                    "missing_dep", "error",
                    _L("缺少前置模组：%s" % did, "Missing dependency: %s" % did),
                    _L("「%s」需要前置 mod id「%s」%s，但 mods/ 里没有任何文件提供它。"
                       % (mlabel, did, ("（要求版本 " + rng + "）") if rng else ""),
                       "\"%s\" requires mod id \"%s\"%s, but no file in mods/ provides it."
                       % (mlabel, did, (" (range " + rng + ")") if rng else "")),
                    _L("可一键从 Modrinth 补装「%s」（免费、无需登录）；或手动放入对应前置 jar。" % did,
                       "One-click install \"%s\" from Modrinth (free, no login), or add the jar manually." % did),
                    files=[m["path"]], mod_ids=[did],
                    fix={"type": "install_dep", "mod_id": did, "range": rng,
                         "game_version": mc_version, "loader": inst_loader}))
            elif not active_prov:
                disabled = providers[0]
                issues.append(_issue(
                    "missing_dep", "warn",
                    _L("前置「%s」存在但已被禁用" % did, "Dependency \"%s\" present but disabled" % did),
                    _L("提供「%s」的文件 %s 当前是 .disabled 状态，不会加载。"
                       % (did, os.path.basename(disabled["path"])),
                       "The provider %s is currently .disabled and won't load."
                       % os.path.basename(disabled["path"])),
                    _L("启用该前置文件（可一键启用），或补装一份启用的副本。",
                       "Enable the provider file (one-click), or install an enabled copy."),
                    files=[m["path"], disabled["path"]], mod_ids=[did],
                    fix={"type": "enable", "path": disabled["path"]}))
            elif rng:
                ok = any(p.get("version") and satisfies(p["version"], rng) for p in active_prov)
                if not ok:
                    have = "、".join(str(p.get("version") or "?") for p in active_prov)
                    issues.append(_issue(
                        "dep_version", "error",
                        _L("前置版本不满足：%s" % did, "Dependency version mismatch: %s" % did),
                        _L("「%s」要求「%s」版本 %s，当前提供的是 %s。"
                           % (mlabel, did, rng, have),
                           "\"%s\" requires \"%s\" %s, but installed is %s."
                           % (mlabel, did, rng, have)),
                        _L("一键从 Modrinth 安装满足 %s 的「%s」，或升级/降级现有前置。" % (rng, did),
                           "One-click install a \"%s\" build satisfying %s, or adjust the existing one."
                           % (did, rng)),
                        files=[m["path"]] + [p["path"] for p in active_prov], mod_ids=[did],
                        fix={"type": "install_dep", "mod_id": did, "range": rng,
                             "game_version": mc_version, "loader": inst_loader}))

        # 2d) 无法读取元数据
        if not m["ids"] and not m["loaders"]:
            issues.append(_issue(
                "unreadable", "warn",
                _L("无法识别的模组文件：%s" % fname, "Unreadable mod file: %s" % fname),
                _L("没能从 jar 里读到 fabric.mod.json / mods.toml / mcmod.info，可能不是有效模组或已损坏。",
                   "No fabric.mod.json / mods.toml / mcmod.info found; it may be invalid or corrupted."),
                _L("确认文件来源；若不是模组请移出 mods/。",
                   "Verify the source; move it out of mods/ if it is not a mod."),
                files=[m["path"]]))

    issues.sort(key=lambda x: (SEV_RANK.get(x["sev"], 3), x["code"]))
    summary = {
        "errors": sum(1 for i in issues if i["sev"] == "error"),
        "warnings": sum(1 for i in issues if i["sev"] == "warn"),
        "infos": sum(1 for i in issues if i["sev"] == "info"),
    }
    return {
        "game_dir": game_dir,
        "loader": inst_loader,
        "mc_version": mc_version,
        "java_major": java_major,
        "mod_count": len(mods),
        "enabled_count": sum(1 for m in mods if m["enabled"]),
        "issues": issues,
        "summary": summary,
        "ok": summary["errors"] == 0,
        "mods": mods,
    }


# ================================================================ Modrinth 补装
def find_dep_candidate(mod_id, game_version="", loader=""):
    """按 mod id/slug 在 Modrinth 解析一个匹配版本；失败返回 None（不抛异常）。

    先按 project id/slug 直查，再退到搜索；优先匹配 game_version + loader，
    匹配不到加载器时放宽加载器（仍尽量限定 MC 版本）。
    """
    from . import modrinth
    pid = None
    title = None
    try:
        p = modrinth._get("/project/" + str(mod_id))
        if isinstance(p, dict) and p.get("project_type") == "mod":
            pid = p.get("id")
            title = p.get("title")
    except Exception:
        pid = None
    if not pid:
        try:
            hits, _total = modrinth.search(
                query=str(mod_id), project_type="mod",
                loader=loader or None, game_version=game_version or None, limit=5)
            if hits:
                pid = hits[0].get("project_id")
                title = hits[0].get("title")
        except Exception:
            return None
    if not pid:
        return None
    versions = []
    try:
        versions = modrinth.get_versions(pid, game_version or None, loader or None)
    except Exception:
        versions = []
    if not versions and loader:
        try:
            versions = modrinth.get_versions(pid, game_version or None, None)
        except Exception:
            versions = []
    if not versions:
        return {"project_id": pid, "title": title or mod_id, "version": None,
                "file": None, "version_id": None}
    v = versions[0]
    f = modrinth.primary_file(v)
    return {
        "project_id": pid,
        "title": title or v.get("name") or mod_id,
        "version": v.get("version_number"),
        "version_id": v.get("id"),
        "file": f,
    }


def apply_fix(game_dir, issue, status=None, mc_version="", loader=""):
    """执行一条问题的 fix 动作，返回结果 dict；失败抛异常由 UI 捕获。

    - disable/enable：走批次4 后缀切换（幂等、同名冲突不覆盖）；
    - install_dep：Modrinth 解析并下载到 mods/，写本地来源清单。
    执行后调用方应重新 scan_instance 复检。
    """
    status = status or (lambda s: None)
    fix = issue.get("fix") or {}
    ftype = fix.get("type")
    if ftype == "disable":
        done = []
        for p in fix.get("paths") or []:
            _new, enabling = localcontent.disable_path(p)
            done.append({"path": p, "enabling": enabling})
            status(_L("已禁用：%s" % os.path.basename(p), "Disabled: %s" % os.path.basename(p)))
        return {"action": "disable", "done": done}
    if ftype == "enable":
        p = fix.get("path")
        _new, enabling = localcontent.enable_path(p)
        status(_L("已启用：%s" % os.path.basename(p), "Enabled: %s" % os.path.basename(p)))
        return {"action": "enable", "path": p, "enabling": enabling}
    if ftype == "install_dep":
        did = fix.get("mod_id") or issue.get("mod_ids", [None])[0]
        gv = fix.get("game_version") or mc_version
        ld = fix.get("loader") or loader
        status(_L("正在从 Modrinth 查找 %s…" % did, "Looking up %s on Modrinth…" % did))
        cand = find_dep_candidate(did, gv, ld)
        if not cand or not cand.get("file"):
            raise RuntimeError(_L("Modrinth 上没找到匹配 %s%s 的 %s，请手动下载放入 mods/。"
                                   % (gv or "任意版本", (" / " + ld) if ld else "", did),
                                   "No matching %s on Modrinth for %s%s; add it manually."
                                   % (did, gv or "any version", (" / " + ld) if ld else "")))
        mods_dir = localcontent.category_dir(game_dir, "mod")
        status(_L("正在下载 %s %s…" % (cand["title"], cand.get("version") or ""),
                   "Downloading %s %s…" % (cand["title"], cand.get("version") or "")))
        from . import modrinth
        saved = modrinth.download_project(
            cand["project_id"], mods_dir, game_version=gv or None, loader=ld or None,
            status=status, with_deps=False)
        installed = []
        for name, path in saved:
            try:
                localcontent.record_import(
                    game_dir, "mod", os.path.basename(path),
                    source="Modrinth 补装依赖", project_id=cand["project_id"],
                    size=os.path.getsize(path))
            except Exception:
                pass
            installed.append({"name": name, "path": path})
        status(_L("已补装 %s" % os.path.basename(installed[-1]["path"]),
                   "Installed %s" % os.path.basename(installed[-1]["path"])))
        return {"action": "install_dep", "candidate": cand, "installed": installed}
    raise RuntimeError(_L("未知修复动作：%s" % ftype, "Unknown fix action: %s" % ftype))
