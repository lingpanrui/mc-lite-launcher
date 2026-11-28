# -*- coding: utf-8 -*-
"""功能投票（v2 本地版）

票数保存在 %APPDATA%\\MCLite\\poll_votes.json。
没有后端，seed 票数只是让界面看起来接近真实社区数据；
正式版会把这些票数接到 GitHub Discussion / 自建接口。
"""
import os
import time

from . import util

# 把启动器现有功能全部放上去，一共 13 项。
FEATURES = [
    "version",
    "loader",
    "launch",
    "memory",
    "modpack",
    "mod",
    "shader",
    "datapack",
    "resource",
    "tunnel",
    "account",
    "i18n",
    "dldetail",
]

# 初始社区票数（模拟历史累积）
SEED_COUNTS = {
    "version": 421,
    "loader": 356,
    "launch": 382,
    "memory": 189,
    "modpack": 328,
    "mod": 447,
    "shader": 254,
    "datapack": 176,
    "resource": 305,
    "tunnel": 512,
    "account": 138,
    "i18n": 92,
    "dldetail": 234,
}

PATH = os.path.join(util.app_root(), "poll_votes.json")


def _default_state():
    return {
        "counts": dict(SEED_COUNTS),
        "mine": [],
        "updated": int(time.time()),
    }


def _normalize(data):
    state = _default_state()
    counts = data.get("counts") or {}
    for k in FEATURES:
        try:
            state["counts"][k] = max(0, int(counts.get(k, SEED_COUNTS[k])))
        except Exception:
            state["counts"][k] = SEED_COUNTS[k]
    mine = data.get("mine") or []
    state["mine"] = [m for m in mine if m in FEATURES]
    return state


def state():
    raw = util.read_json(PATH, None)
    if not isinstance(raw, dict):
        raw = _default_state()
        _save(raw)
    return _normalize(raw)


def _save(data):
    util.write_json(PATH, data)


def vote(fid):
    """返回 (成功?, 当前票数)"""
    if fid not in FEATURES:
        return False, 0
    raw = util.read_json(PATH, None)
    if not isinstance(raw, dict):
        raw = _default_state()
    data = _normalize(raw)
    if fid in data["mine"]:
        return False, data["counts"][fid]
    data["mine"].append(fid)
    data["counts"][fid] += 1
    data["updated"] = int(time.time())
    _save(data)
    return True, data["counts"][fid]


def reset_mine():
    """撤销自己投过的票（票数相应减 1），用于预览测试"""
    raw = util.read_json(PATH, None)
    if not isinstance(raw, dict):
        return
    data = _normalize(raw)
    for fid in list(data["mine"]):
        data["counts"][fid] = max(0, data["counts"][fid] - 1)
    data["mine"] = []
    data["updated"] = int(time.time())
    _save(data)


def total_votes(data=None):
    data = data or state()
    return sum(data["counts"].values())


def ranking(data=None):
    data = data or state()
    return sorted(FEATURES, key=lambda f: data["counts"][f], reverse=True)
