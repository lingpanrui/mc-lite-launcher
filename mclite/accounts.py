# -*- coding: utf-8 -*-
"""账户体系（批次2）：离线 / 外置登录（authlib-injector + Yggdrasil）/ 微软正版（设备码）

config.json 新增字段：
- accounts: list[dict]   账户列表（多账户并存）
- current_account: str    当前账户 id

账户字段：id / mode(offline|authlib|msa) / name / uuid / token / api /
client_token / user_type / skin / builtin / created_at

设计要点：
- 老配置只有顶层 username（默认 Steve），首次 migrate 时播种一个内置离线账户，
  不删除、不覆盖任何已有数据。
- 离线账户可新增 / 改名 / 删除 / 设为当前；同名（忽略大小写）拦截。
- 外置 / 微软登录成功后按 (mode, api, name)  upsert，重复登录刷新 token，不产生重复行。
- 启动时用 launch_auth() 组装 build_command 的 auth 参数；外置账户额外拼
  `-javaagent:authlib-injector.jar=<API>`。
- 微软登录必须由用户自备 Azure Client ID，本模块绝不内置公共 ID。
"""
import hashlib
import os
import time
import uuid

from . import auth, util

OFFLINE_DEFAULT_ID = "offline_default"
MODE_OFFLINE = "offline"
MODE_AUTHLIB = "authlib"
MODE_MSA = "msa"

ACCOUNT_FIELDS = (
    "id", "mode", "name", "uuid", "token", "api", "client_token",
    "user_type", "skin", "builtin", "created_at",
)


# ---------------------------------------------------------------- 工具
def offline_uuid(username):
    """与 Mojang 离线模式一致的 v3 UUID（md5("OfflinePlayer:<name>")）。"""
    data = hashlib.md5(("OfflinePlayer:" + str(username)).encode("utf-8")).digest()
    return str(uuid.UUID(bytes=data, version=3))


def _new_id(prefix):
    return prefix + "_" + uuid.uuid4().hex[:10]


def _save(cfg):
    util.save_config(cfg)


def _normalize(acc, cfg):
    out = {
        "id": str(acc.get("id") or _new_id("acc")),
        "mode": str(acc.get("mode") or MODE_OFFLINE),
        "name": str(acc.get("name") or "Steve"),
        "uuid": str(acc.get("uuid") or ""),
        "token": str(acc.get("token") or ""),
        "api": str(acc.get("api") or ""),
        "client_token": str(acc.get("client_token") or ""),
        "user_type": str(acc.get("user_type") or ("legacy" if acc.get("mode") == MODE_OFFLINE else "msa")),
        "skin": str(acc.get("skin") or ""),
        "builtin": bool(acc.get("builtin")),
        "created_at": acc.get("created_at") or time.time(),
    }
    if out["mode"] == MODE_OFFLINE and not out["uuid"]:
        out["uuid"] = offline_uuid(out["name"])
    return out


def migrate(cfg):
    """幂等迁移：保证 accounts 列表与 current_account 合法；返回 cfg 本身。"""
    if not isinstance(cfg.get("accounts"), list):
        cfg["accounts"] = []
    accounts = cfg["accounts"]

    if not accounts:
        seed_name = str(cfg.get("username") or "Steve").strip() or "Steve"
        accounts.append({
            "id": OFFLINE_DEFAULT_ID,
            "mode": MODE_OFFLINE,
            "name": seed_name,
            "uuid": offline_uuid(seed_name),
            "token": "",
            "api": "",
            "client_token": "",
            "user_type": "legacy",
            "skin": "",
            "builtin": True,
            "created_at": time.time(),
        })

    cfg["accounts"] = [_normalize(a, cfg) for a in accounts]

    cur = cfg.get("current_account")
    if not any(a["id"] == cur for a in cfg["accounts"]):
        cfg["current_account"] = cfg["accounts"][0]["id"]

    # 内联查找当前账户（这里不能调用 current()，否则 migrate→current→migrate 递归）
    cur_acc = next((a for a in cfg["accounts"] if a["id"] == cfg.get("current_account")), None)
    if cur_acc:
        cfg["username"] = cur_acc.get("name") or cfg.get("username") or "Steve"
    return cfg


# ---------------------------------------------------------------- 查询
def list_accounts(cfg):
    migrate(cfg)
    return list(cfg.get("accounts") or [])


def get_account(cfg, aid):
    for acc in list_accounts(cfg):
        if acc["id"] == aid:
            return acc
    return None


def current(cfg):
    migrate(cfg)
    aid = cfg.get("current_account")
    acc = get_account(cfg, aid)
    if acc is None:
        acc = (cfg.get("accounts") or [None])[0]
        if acc is not None:
            cfg["current_account"] = acc["id"]
    return acc


def current_name(cfg):
    acc = current(cfg)
    return (acc or {}).get("name") or cfg.get("username") or "Steve"


# ---------------------------------------------------------------- 离线账户
def add_offline(cfg, name, switch=True):
    """新增离线账户；同名（忽略大小写、去空白）拦截。"""
    migrate(cfg)
    name = str(name or "").strip()
    if not name:
        raise ValueError("账户名称不能为空")
    if len(name) > 32:
        raise ValueError("账户名称最长 32 个字符")
    low = name.lower()
    for acc in cfg["accounts"]:
        if acc.get("mode") == MODE_OFFLINE and str(acc.get("name", "")).strip().lower() == low:
            raise ValueError("已存在同名离线账户：%s" % name)
    acc = {
        "id": _new_id("off"),
        "mode": MODE_OFFLINE,
        "name": name,
        "uuid": offline_uuid(name),
        "token": "",
        "api": "",
        "client_token": "",
        "user_type": "legacy",
        "skin": "",
        "builtin": False,
        "created_at": time.time(),
    }
    cfg["accounts"].append(acc)
    if switch:
        cfg["current_account"] = acc["id"]
        cfg["username"] = name
    _save(cfg)
    return acc


def rename_offline(cfg, aid, new_name):
    """仅离线账户可改名；在线账户名称由服务器下发。"""
    acc = get_account(cfg, aid)
    if acc is None:
        raise KeyError("账户不存在：%s" % aid)
    if acc.get("mode") != MODE_OFFLINE:
        raise ValueError("在线账户的角色名由登录服务器下发，不能手动改名")
    new_name = str(new_name or "").strip()
    if not new_name:
        raise ValueError("账户名称不能为空")
    if len(new_name) > 32:
        raise ValueError("账户名称最长 32 个字符")
    low = new_name.lower()
    for other in cfg["accounts"]:
        if other["id"] != aid and other.get("mode") == MODE_OFFLINE \
                and str(other.get("name", "")).strip().lower() == low:
            raise ValueError("已存在同名离线账户：%s" % new_name)
    acc["name"] = new_name
    acc["uuid"] = offline_uuid(new_name)
    if cfg.get("current_account") == aid:
        cfg["username"] = new_name
    _save(cfg)
    return acc


def delete(cfg, aid):
    """删除账户；至少保留一个账户。删除当前账户后自动切到第一个。"""
    acc = get_account(cfg, aid)
    if acc is None:
        raise KeyError("账户不存在：%s" % aid)
    if len(cfg["accounts"]) <= 1:
        raise ValueError("至少需要保留一个账户；可先新增另一个账户再删除")
    cfg["accounts"] = [a for a in cfg["accounts"] if a["id"] != aid]
    if cfg.get("current_account") == aid:
        cfg["current_account"] = cfg["accounts"][0]["id"]
        cfg["username"] = cfg["accounts"][0].get("name") or "Steve"
    _save(cfg)
    return acc


def set_current(cfg, aid):
    acc = get_account(cfg, aid)
    if acc is None:
        raise KeyError("账户不存在：%s" % aid)
    cfg["current_account"] = aid
    cfg["username"] = acc.get("name") or "Steve"
    _save(cfg)
    return acc


# ---------------------------------------------------------------- 在线登录
def _upsert_online(cfg, data, switch=True):
    """登录成功后按 (mode, api, name) 去重写入；存在则刷新 token。"""
    mode = data.get("mode")
    name = data.get("name") or "?"
    api = data.get("api") or ""
    existing = None
    for acc in cfg["accounts"]:
        if acc.get("mode") == mode and str(acc.get("api") or "") == str(api or "") \
                and str(acc.get("name") or "") == str(name):
            existing = acc
            break
    if existing is None:
        existing = {
            "id": _new_id(mode[:3]),
            "mode": mode,
            "name": name,
            "uuid": data.get("uuid") or "",
            "token": data.get("token") or "",
            "api": api,
            "client_token": data.get("client_token") or "",
            "user_type": data.get("user_type") or ("msa" if mode != MODE_OFFLINE else "legacy"),
            "skin": data.get("skin") or api,
            "builtin": False,
            "created_at": time.time(),
        }
        cfg["accounts"].append(existing)
    else:
        existing.update({
            "uuid": data.get("uuid") or existing.get("uuid"),
            "token": data.get("token") or existing.get("token"),
            "client_token": data.get("client_token") or existing.get("client_token"),
            "user_type": data.get("user_type") or existing.get("user_type"),
            "skin": data.get("skin") or existing.get("skin") or api,
        })
    if switch:
        cfg["current_account"] = existing["id"]
        cfg["username"] = name
    _save(cfg)
    return existing


def login_authlib(cfg, api, username, password, status=None, switch=True):
    """外置登录（authlib-injector + Yggdrasil）。成功返回账户 dict。"""
    status = status or (lambda s: None)
    result = auth.yggdrasil_login(api, username, password, status=status)
    result["user_type"] = "msa"
    result["skin"] = result.get("api") or api
    return _upsert_online(cfg, result, switch=switch)


def login_msa(cfg, client_id, status=None, on_code=None, switch=True):
    """微软设备码登录。client_id 为空时直接抛 ValueError（UI 应提前禁用按钮）。"""
    status = status or (lambda s: None)
    client_id = (client_id or "").strip()
    if not client_id:
        raise ValueError("需要先填写自己的 Azure 应用 Client ID（免费注册，公共客户端 + 设备码流）")
    result = auth.msa_device_login(client_id, status=status, on_code=on_code)
    result["user_type"] = "msa"
    result["api"] = ""
    result["skin"] = "Microsoft"
    return _upsert_online(cfg, result, switch=switch)


def test_api(api):
    """测试外置登录 API 根地址，返回服务器名称（失败抛异常）。"""
    return auth.verify_authlib_api(api)


def ensure_authlib_jar(status=None, progress=None):
    """下载/复用 authlib-injector jar，返回本地路径。"""
    return auth.authlib_jar(status=status, progress=progress)


def javaagent_arg(account, jar_path):
    """拼出启动时真实加入命令行的 -javaagent 参数；非外置账户返回 None。"""
    if not account or account.get("mode") != MODE_AUTHLIB:
        return None
    api = (account.get("api") or "").strip()
    if not api or not jar_path or not os.path.isfile(jar_path):
        return None
    return "-javaagent:%s=%s" % (jar_path, api)


def launch_auth(account):
    """把账户转换成 mojang.build_command 的 auth 参数。"""
    account = account or {}
    mode = account.get("mode") or MODE_OFFLINE
    name = account.get("name") or "Steve"
    if mode == MODE_OFFLINE:
        return {
            "name": name,
            "uuid": account.get("uuid") or offline_uuid(name),
            "token": "0" * 32,
            "user_type": "legacy",
        }
    return {
        "name": name,
        "uuid": account.get("uuid") or "",
        "token": account.get("token") or "0" * 32,
        "user_type": "msa",
    }
