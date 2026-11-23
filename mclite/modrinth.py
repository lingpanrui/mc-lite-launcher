# -*- coding: utf-8 -*-
"""Modrinth 内容检索与下载（模组 / 光影 / 资源包 / 整合包）"""
import json
import os
import urllib.parse

from . import util

API = "https://api.modrinth.com/v2"

PROJECT_TYPES = {
    "mod": "模组",
    "shader": "光影",
    "resourcepack": "资源包",
    "modpack": "整合包",
    "datapack": "数据包",
}

# Modrinth 项目页 URL 前缀
_TYPE_SEGMENT = {
    "mod": "mod",
    "shader": "shader",
    "resourcepack": "resourcepack",
    "modpack": "modpack",
    "datapack": "datapack",
}


def project_url(project_type, slug):
    """根据 slug 拼出 Modrinth 项目页网址"""
    seg = _TYPE_SEGMENT.get(project_type or "mod", "mod")
    return "https://modrinth.com/%s/%s" % (seg, slug)

LOADERS = ["fabric", "quilt", "forge", "neoforge"]


def _get(path, params=None):
    url = API + path
    if params:
        url += "?" + urllib.parse.urlencode(params, doseq=True)
    return util.http_json(url)


def search(query="", project_type=None, loader=None, game_version=None, limit=20, offset=0, sort="relevance"):
    facets = []
    if project_type:
        facets.append(["project_type:%s" % project_type])
    if loader:
        facets.append(["categories:%s" % loader])
    if game_version:
        facets.append(["versions:%s" % game_version])
    params = {"limit": limit, "offset": offset, "index": sort}
    if query:
        params["query"] = query
    if facets:
        params["facets"] = json.dumps(facets)
    data = _get("/search", params)
    return data.get("hits", []), data.get("total_hits", 0)


def get_versions(project_id, game_version=None, loader=None):
    params = {}
    if game_version:
        params["game_versions"] = json.dumps([game_version])
    if loader:
        params["loaders"] = json.dumps([loader])
    return _get("/project/%s/version" % project_id, params) or []


def get_version(version_id):
    return _get("/version/%s" % version_id)


def primary_file(version):
    files = version.get("files") or []
    if not files:
        return None
    for f in files:
        if f.get("primary"):
            return f
    return files[0]


def _download_file_entry(entry, folder, status=None):
    status = status or (lambda s: None)
    os.makedirs(folder, exist_ok=True)
    dest = os.path.join(folder, entry["filename"])
    expected = (entry.get("hashes") or {}).get("sha1")
    if util.file_ok(dest, entry.get("size"), expected):
        status("已存在，跳过 %s" % entry["filename"])
        return dest, False
    status("下载 %s" % entry["filename"])
    util.download_file(entry["url"], dest, expected_sha1=expected, desc=entry["filename"])
    return dest, True


def download_project(project_id, folder, game_version=None, loader=None, status=None, with_deps=True):
    """下载项目主文件（可自动补齐必需依赖），返回 [(项目名, 文件路径)]"""
    status = status or (lambda s: None)
    versions = get_versions(project_id, game_version, loader)
    if not versions:
        raise ValueError("没有找到匹配 %s%s 的版本" % (game_version or "任意游戏版本", (" / " + loader) if loader else ""))
    version = versions[0]
    entry = primary_file(version)
    if not entry:
        raise ValueError("该版本没有可下载文件")
    saved = []
    dest, _ = _download_file_entry(entry, folder, status)
    saved.append((version.get("name") or entry["filename"], dest))

    if with_deps:
        for dep in version.get("dependencies") or []:
            if dep.get("dependency_type") != "required":
                continue
            try:
                if dep.get("version_id"):
                    dv = get_version(dep["version_id"])
                elif dep.get("project_id"):
                    dvs = get_versions(dep["project_id"], game_version, loader)
                    if not dvs:
                        continue
                    dv = dvs[0]
                else:
                    continue
                de = primary_file(dv)
                if not de:
                    continue
                status("安装前置依赖 %s" % de["filename"])
                p, _ = _download_file_entry(de, folder, status)
                saved.append((dv.get("name") or de["filename"], p))
            except Exception as e:
                status("依赖下载失败：%s" % e)
    return saved


def download_pack(project_id, game_dir, game_version=None, loader=None, status=None):
    versions = get_versions(project_id, game_version, loader)
    if not versions:
        raise ValueError("没有匹配的整合包版本")
    entry = primary_file(versions[0])
    if not entry:
        raise ValueError("整合包没有可下载文件")
    pack_dir = os.path.join(game_dir, "modpacks")
    dest, _ = _download_file_entry(entry, pack_dir, status)
    return dest
