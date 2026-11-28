# -*- coding: utf-8 -*-
"""Quilt 加载器安装（纯 HTTP 拼装，不需要 GUI installer）

实测（2026-11-28，湖州网络）：
- 列表   GET https://meta.quiltmc.org/v3/versions/loader/<mc>            200
- profile GET .../loader/<mc>/<loader>/profile/json                     200（mainClass=KnotClient）
- loader maven jar / 各 library 均 206

流程与 mojang.install_fabric 同构：取 profile JSON → 写 versions/<id>/<id>.json
→ 下载 profile.libraries（含 quilt-loader 本体）→ 可选安装原版基础版本。
默认过滤 -beta/-rc，稳定版优先；UI 可显式开启「包含测试版」。
"""
import os
from concurrent.futures import ThreadPoolExecutor

from . import mojang, util

QUILT_META = "https://meta.quiltmc.org/v3"
QUILT_MAVEN = "https://maven.quiltmc.org/repository/release"


def _is_prerelease(version):
    v = str(version).lower()
    return ("-beta" in v) or ("-rc" in v) or ("-alpha" in v)


def list_loaders(mc_version, include_beta=False, timeout=25):
    """返回该 MC 版本可用的 Quilt loader 版本列表（新到旧）。

    include_beta=False 时只返回稳定版；若该版本没有稳定版则返回空表，
    由 UI 提示「暂无稳定加载器，可勾选包含测试版」。
    """
    data = util.http_json("%s/versions/loader/%s" % (QUILT_META, mc_version), timeout=timeout)
    all_versions = []
    for item in data or []:
        lv = (item.get("loader") or {}).get("version")
        if lv:
            all_versions.append(str(lv))
    if include_beta:
        return all_versions
    return [v for v in all_versions if not _is_prerelease(v)]


def select_loader(mc_version, loader_version=None, include_beta=False):
    """选定 loader 版本：显式指定优先，否则取稳定版首个；无稳定版且允许 beta 时取首个。"""
    if loader_version:
        return str(loader_version)
    stable = list_loaders(mc_version, include_beta=False)
    if stable:
        return stable[0]
    if include_beta:
        allv = list_loaders(mc_version, include_beta=True)
        if allv:
            return allv[0]
    raise ValueError("该版本 Quilt 暂无可用的稳定加载器（可勾选“包含测试版”后重试）")


def _library_plan(lib):
    """把 profile 里的一条 library 转成 (相对路径, 完整 URL, 名称)。"""
    name = lib.get("name") or ""
    art = (lib.get("downloads") or {}).get("artifact")
    if art and art.get("path"):
        rel = art["path"]
        url = art.get("url") or ""
    elif name:
        rel = mojang.maven_to_path(name)
        base = (lib.get("url") or QUILT_MAVEN).rstrip("/")
        url = base + "/" + rel
    else:
        return None
    if not rel or not url:
        return None
    return rel, url, name


def install_quilt(game_dir, mc_version, loader_version=None, status=None, progress=None,
                   manifest=None, include_beta=False, install_base=True):
    """安装 Quilt 加载器，返回版本 id（quilt-loader-<lv>-<mc>）。

    install_base=True（UI 默认）会顺带安装原版基础版本（客户端/库/资源）；
    纯 loader 校验场景可置 False，但此时需保证 versions/<mc>/<mc>.json 已存在，
    否则 build_command 的 inheritsFrom 链无法解析。
    """
    status = status or (lambda s: None)
    progress = progress or (lambda f: None)

    loader_version = select_loader(mc_version, loader_version, include_beta=include_beta)
    status("获取 Quilt 安装配置：%s" % loader_version)
    profile = util.http_json(
        "%s/versions/loader/%s/%s/profile/json" % (QUILT_META, mc_version, loader_version),
        timeout=25,
    )
    vid = profile.get("id") or ("quilt-loader-%s-%s" % (loader_version, mc_version))
    vdir = os.path.join(game_dir, "versions", vid)
    os.makedirs(vdir, exist_ok=True)
    util.write_json(os.path.join(vdir, vid + ".json"), profile)
    progress(0.15)

    # 下载 profile 声明的依赖库（含 quilt-loader 本体）
    plan = []
    for lib in profile.get("libraries") or []:
        item = _library_plan(lib)
        if item:
            plan.append(item)

    libs_dir = os.path.join(game_dir, "libraries")
    os.makedirs(libs_dir, exist_ok=True)
    total = max(1, len(plan))
    done = [0]

    def one(item):
        rel, url, name = item
        dest = os.path.join(libs_dir, rel.replace("/", os.sep))
        if not util.file_ok(dest):
            util.download_file(url, dest, desc=os.path.basename(rel), retries=1, timeout=45)
        done[0] += 1
        progress(0.15 + 0.55 * done[0] / total)
        status("Quilt 依赖 %d/%d：%s" % (done[0], total, name or os.path.basename(rel)))

    if plan:
        with ThreadPoolExecutor(max_workers=8) as ex:
            list(ex.map(one, plan))

    # 安装原版基础版本（Quilt 版本 json 通过 inheritsFrom 依赖它）
    if install_base:
        status("安装原版基础版本 %s" % mc_version)
        mm = manifest or mojang.manifest_map(mojang.get_manifest())
        mojang.Installer(game_dir, mm, status=status, progress=progress).install(mc_version)

    progress(1.0)
    status("Quilt %s 安装完成：%s" % (loader_version, vid))
    return vid
