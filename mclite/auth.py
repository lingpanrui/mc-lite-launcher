# -*- coding: utf-8 -*-
"""账号体系：离线 / 外置登录（authlib-injector + Yggdrasil）/ 微软正版（设备码）

微软登录需要自备 Azure 应用 Client ID（公开客户端、允许设备码流程），
在「账号」页填写后即可使用；不填写则只能用离线或外置登录。
"""
import json
import os
import random
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from . import util

AUTHLIB_API = "https://api.github.com/repos/yushijinhun/authlib-injector/releases/latest"

MSA_DEVICE_URL = "https://login.microsoftonline.com/consumers/oauth2/v2.0/devicecode"
MSA_TOKEN_URL = "https://login.microsoftonline.com/consumers/oauth2/v2.0/token"
XBL_URL = "https://user.auth.xboxlive.com/user/authenticate"
XSTS_URL = "https://xsts.auth.xboxlive.com/xsts/authorize"
MC_LOGIN_URL = "https://api.minecraftservices.com/authentication/login_with_xbox"
MC_PROFILE_URL = "https://api.minecraftservices.com/minecraft/profile"
MSA_SCOPE = "XboxLive.signin offline_access"


def _request(url, data=None, headers=None, method=None, timeout=30):
    body = None
    h = {"User-Agent": util.USER_AGENT, "Accept": "application/json"}
    h.update(headers or {})
    if isinstance(data, dict):
        body = json.dumps(data).encode("utf-8")
        h.setdefault("Content-Type", "application/json")
    elif data is not None:
        body = data
    req = urllib.request.Request(url, data=body, headers=h, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", "replace")
    return json.loads(raw) if raw.strip().startswith(("{", "[")) else raw


def _post_json(url, payload, headers=None, timeout=30):
    return _request(url, payload, headers=headers, method="POST", timeout=timeout)


def _post_form(url, payload, timeout=30):
    body = urllib.parse.urlencode(payload).encode("utf-8")
    return _request(url, body, headers={"Content-Type": "application/x-www-form-urlencoded"},
                    method="POST", timeout=timeout)


# --------------------------------------------------------------------------- #
# 外置登录（authlib-injector）
# --------------------------------------------------------------------------- #
def authlib_jar(status=None, progress=None):
    status = status or (lambda s: None)
    progress = progress or (lambda f: None)
    path = os.path.join(util.app_root(), "tools", "authlib-injector.jar")
    if os.path.isfile(path):
        return path
    status("下载 authlib-injector")
    release = util.http_json(AUTHLIB_API)
    asset = next((a for a in release.get("assets", []) if a.get("name", "").endswith(".jar")), None)
    if not asset:
        raise IOError("authlib-injector 发布页里没有 jar 文件")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    util.download_file(asset["browser_download_url"], path,
                       on_bytes=lambda got, total: progress(min(0.9, got / total) if total else 0.4),
                       desc="authlib-injector")
    progress(1.0)
    return path


def normalize_api(api):
    api = (api or "").strip().rstrip("/")
    if not api:
        raise ValueError("请填写外置登录服务器地址")
    if not re.match(r"https?://", api):
        api = "https://" + api
    if not api.endswith("/api/yggdrasil") and "/api/" not in api:
        if api.rstrip("/").endswith("/authserver") or api.rstrip("/").endswith("/sessionserver"):
            raise ValueError("请填写 API 根地址，例如 https://example.com/api/yggdrasil")
    return api


def yggdrasil_login(api, username, password, status=None):
    """外置登录：返回 {mode,name,uuid,token,api}"""
    status = status or (lambda s: None)
    api = normalize_api(api)
    if not username or not password:
        raise ValueError("请填写用户名与密码")
    status("正在向 %s 验证账号" % api)
    payload = {
        "agent": {"name": "Minecraft", "version": 1},
        "username": username,
        "password": password,
        "clientToken": uuid_hex(32),
        "requestUser": False,
    }
    try:
        resp = _post_json(api + "/authserver/authenticate", payload)
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read().decode("utf-8", "replace"))
            msg = detail.get("errorMessage") or detail.get("error") or str(e)
        except Exception:
            msg = str(e)
        raise IOError("外置登录失败：%s" % msg)
    if not isinstance(resp, dict) or "accessToken" not in resp:
        raise IOError("外置登录失败：服务器返回内容异常")
    profile = resp.get("selectedProfile") or {}
    if not profile:
        raise IOError("该账号没有可用的角色（请先在服务器皮肤站创建角色）")
    return {
        "mode": "authlib",
        "name": profile.get("name"),
        "uuid": profile.get("id"),
        "token": resp.get("accessToken"),
        "api": api,
        "client_token": resp.get("clientToken"),
    }


# --------------------------------------------------------------------------- #
# 微软正版登录（设备码流程）
# --------------------------------------------------------------------------- #
def uuid_hex(n=32):
    return "%0*x" % (n, random.getrandbits(n * 4))


def _msa_poll(client_id, device, status, on_code, deadline=900):
    interval = int(device.get("interval") or 5)
    on_code(device.get("user_code"), device.get("verification_uri") or device.get("verification_url"))
    end = time.time() + min(int(device.get("expires_in") or deadline), deadline)
    last_err = None
    while time.time() < end:
        time.sleep(interval)
        try:
            tok = _post_form(MSA_TOKEN_URL, {
                "client_id": client_id,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "device_code": device.get("device_code"),
            })
        except urllib.error.HTTPError as e:
            try:
                tok = json.loads(e.read().decode("utf-8", "replace"))
            except Exception:
                continue
        if isinstance(tok, dict) and tok.get("access_token"):
            return tok["access_token"]
        err = (tok or {}).get("error") if isinstance(tok, dict) else None
        if err == "authorization_pending":
            continue
        if err == "slow_down":
            interval += 5
            continue
        last_err = (tok or {}).get("error_description") or err or last_err
        if err in ("expired_token", "authorization_declined", "bad_verification_code"):
            break
    raise IOError("微软登录失败：%s" % (last_err or "超时未完成登录"))


def msa_device_login(client_id, status=None, on_code=None):
    """微软设备码登录：返回 {mode,name,uuid,token}"""
    status = status or (lambda s: None)
    on_code = on_code or (lambda code, uri: None)
    client_id = (client_id or "").strip()
    if not client_id:
        raise ValueError("需要在设置里填写自己的 Azure 应用 Client ID")
    status("向微软申请设备码")
    device = _post_form(MSA_DEVICE_URL, {"client_id": client_id, "scope": MSA_SCOPE})
    if not isinstance(device, dict) or not device.get("user_code"):
        raise IOError("微软设备码获取失败：%s" % device)
    status("等待在浏览器中完成微软登录")
    msa_token = _msa_poll(client_id, device, status, on_code)

    status("验证 Xbox Live")
    xbl = _post_json(XBL_URL, {
        "Properties": {
            "AuthMethod": "RPS",
            "SiteName": "user.auth.xboxlive.com",
            "RpsTicket": "d=" + msa_token,
        },
        "RpsTicket": "d=" + msa_token,
        "TokenType": "JWT",
    })
    if "Token" not in xbl:
        raise IOError("Xbox Live 验证失败")

    status("验证 XSTS")
    try:
        xsts = _post_json(XSTS_URL, {
            "Properties": {"SandboxId": "RETAIL", "UserTokens": [xbl["Token"]]},
            "RpsTicket": "r=",
            "TokenType": "JWT",
        })
    except urllib.error.HTTPError as e:
        code = ""
        try:
            code = str(json.loads(e.read().decode("utf-8", "replace")).get("XErr"))
        except Exception:
            pass
        hint = {
            "2148916233": "该微软账号还没有 Xbox 档案，请先登录一次 Xbox 官网创建档案",
            "2148916235": "该账号所在地区不支持 Xbox Live",
            "2148916238": "未成年账号需要在家庭组中由家长批准",
        }.get(code, "XSTS 验证失败（%s）" % code)
        raise IOError(hint)
    claims = (xsts.get("DisplayClaims") or {}).get("xui") or [{}]
    uhs = claims[0].get("uhs")
    if not uhs:
        raise IOError("XSTS 返回内容缺少用户标识")

    status("登录 Minecraft 服务")
    mc = _post_json(MC_LOGIN_URL, {"identityToken": "XBL3.0 x=%s;%s" % (uhs, xsts.get("Token"))})
    token = mc.get("access_token")
    if not token:
        raise IOError("Minecraft 登录失败：该账号可能没有购买 Java 版")

    profile = _request(MC_PROFILE_URL, headers={"Authorization": "Bearer " + token})
    if not isinstance(profile, dict) or not profile.get("id"):
        raise IOError("获取 Minecraft 档案失败")
    return {
        "mode": "msa",
        "name": profile.get("name"),
        "uuid": profile.get("id"),
        "token": token,
    }


def verify_authlib_api(api):
    """校验外置登录地址是否可用，返回服务器名称"""
    api = normalize_api(api)
    try:
        meta = _request(api, timeout=20)
    except Exception as e:
        raise IOError("无法访问该 API：%s" % e)
    if isinstance(meta, dict):
        sign = (meta.get("meta") or {}).get("serverName") or (meta.get("meta") or {}).get("implementationName")
        return sign or api
    return api
