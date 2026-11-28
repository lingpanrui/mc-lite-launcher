# -*- coding: utf-8 -*-
"""实例（Instance）管理：多游戏目录隔离、配置持久化、存档备份恢复、导出导入

config.json 新增字段（见 _CONVENTIONS.md §6）：
- instances: list[dict]   实例列表
- current_instance: str   当前实例 id
- instance_root: str      新建实例的默认根目录（%APPDATA%\\MCLite\\instances）

兼容底线：老的顶层 game_dir 直接映射为 id="default" 的默认实例，
不搬目录、不删版本；默认实例禁止删除。

实例字段：id / name / icon / game_dir / java_path / memory_mb / width /
height / jvm_args / loader_hint / last_version / builtin
"""
import datetime
import json
import os
import shutil
import time
import uuid
import zipfile

from . import util

DEFAULT_ID = "default"
EXPORT_FORMAT = "mclite-instance"
EXPORT_VERSION = 1
LAUNCHER_VERSION = "1.9.0"

INSTANCE_FIELDS = (
    "id", "name", "icon", "game_dir", "java_path", "memory_mb", "width",
    "height", "jvm_args", "loader_hint", "last_version", "builtin",
)

# 允许通过 update() 写回的字段及类型
_INT_FIELDS = ("memory_mb", "width", "height")
_STR_FIELDS = ("name", "icon", "game_dir", "java_path", "jvm_args",
               "loader_hint", "last_version")


# ---------------------------------------------------------------- 基础路径
def instance_root(cfg):
    root = (cfg or {}).get("instance_root") or os.path.join(util.app_root(), "instances")
    return os.path.abspath(root)


def legacy_game_dir(cfg):
    """老配置里的全局 game_dir（默认实例目录）"""
    return os.path.abspath((cfg or {}).get("game_dir") or os.path.join(util.app_root(), "game"))


def default_instance(cfg):
    """把老 game_dir + 顶层启动参数映射成默认实例（不搬任何文件）"""
    cfg = cfg or {}
    return {
        "id": DEFAULT_ID,
        "name": "默认实例",
        "icon": "◈",
        "game_dir": legacy_game_dir(cfg),
        "java_path": cfg.get("java_path") or "",
        "memory_mb": int(cfg.get("memory_mb") or 4096),
        "width": int(cfg.get("width") or 854),
        "height": int(cfg.get("height") or 480),
        "jvm_args": cfg.get("jvm_args") or "",
        "loader_hint": "",
        "last_version": cfg.get("last_version") or "",
        "builtin": True,
    }


def _normalize(inst, cfg):
    """补齐实例缺失字段，类型兜底"""
    base = default_instance(cfg)
    out = dict(base)
    if isinstance(inst, dict):
        out.update({k: inst[k] for k in INSTANCE_FIELDS if k in inst})
    out["id"] = str(out.get("id") or DEFAULT_ID)
    out["name"] = str(out.get("name") or "未命名实例")
    out["icon"] = str(out.get("icon") or "◈")[:4]
    out["game_dir"] = str(out.get("game_dir") or legacy_game_dir(cfg))
    out["java_path"] = str(out.get("java_path") or "")
    out["jvm_args"] = str(out.get("jvm_args") or "")
    out["loader_hint"] = str(out.get("loader_hint") or "")
    out["last_version"] = str(out.get("last_version") or "")
    out["builtin"] = bool(out.get("builtin")) or out["id"] == DEFAULT_ID
    for k in _INT_FIELDS:
        try:
            out[k] = int(out.get(k) or base[k])
        except (TypeError, ValueError):
            out[k] = base[k]
    return out


def migrate(cfg):
    """首次运行 v1.3.0 时把老配置迁移成实例结构（幂等，不移动游戏目录）。

    返回 cfg 本身（原地修改）。
    """
    if not isinstance(cfg.get("instances"), list):
        cfg["instances"] = []
    instances = cfg["instances"]

    # 默认实例必须在列表里（老 game_dir 映射，绝不搬目录）
    if not any(isinstance(x, dict) and x.get("id") == DEFAULT_ID for x in instances):
        instances.insert(0, default_instance(cfg))

    # 全部规范化
    cfg["instances"] = [_normalize(x, cfg) for x in instances]

    # 当前实例合法性（这里不能调用 current()/get_instance()，它们会回调 migrate）
    cur = cfg.get("current_instance")
    if not any(x["id"] == cur for x in cfg["instances"]):
        cur = DEFAULT_ID if any(x["id"] == DEFAULT_ID for x in cfg["instances"]) else cfg["instances"][0]["id"]
        cfg["current_instance"] = cur

    try:
        os.makedirs(instance_root(cfg), exist_ok=True)
    except Exception:
        pass

    cur_inst = next((x for x in cfg["instances"] if x["id"] == cur), None)
    if cur_inst is not None:
        _sync_legacy(cfg, cur_inst)
    return cfg


def _sync_legacy(cfg, inst):
    """把当前实例的启动参数镜像回顶层 cfg，老代码（self.game_dir 等）自然跟随。"""
    if not inst:
        return
    cfg["game_dir"] = inst["game_dir"]
    cfg["java_path"] = inst.get("java_path") or ""
    cfg["memory_mb"] = int(inst.get("memory_mb") or 4096)
    cfg["width"] = int(inst.get("width") or 854)
    cfg["height"] = int(inst.get("height") or 480)
    cfg["jvm_args"] = inst.get("jvm_args") or ""
    if inst.get("last_version"):
        cfg["last_version"] = inst["last_version"]


def _save(cfg):
    util.save_config(cfg)


# ---------------------------------------------------------------- 查询
def list_instances(cfg):
    migrate(cfg)
    return list(cfg.get("instances") or [])


def get_instance(cfg, iid):
    for inst in list_instances(cfg):
        if inst["id"] == iid:
            return inst
    return None


def current(cfg):
    migrate(cfg)
    iid = cfg.get("current_instance")
    inst = get_instance(cfg, iid)
    if inst is None:
        inst = get_instance(cfg, DEFAULT_ID) or (cfg.get("instances") or [None])[0]
        if inst is not None:
            cfg["current_instance"] = inst["id"]
    return inst


def version_count(game_dir):
    """统计某实例目录下已安装版本数（与 ui_v2.installed_versions 同口径）"""
    vdir = os.path.join(game_dir or "", "versions")
    n = 0
    try:
        for name in os.listdir(vdir):
            if os.path.isfile(os.path.join(vdir, name, name + ".json")):
                n += 1
    except Exception:
        return 0
    return n


# ---------------------------------------------------------------- 增删改切
def _safe_folder_name(name):
    bad = '<>:"/\\|?*'
    out = "".join("_" if ch in bad else ch for ch in str(name or "").strip())
    return out.strip(" .") or "instance"


def _new_id():
    return "inst_" + uuid.uuid4().hex[:10]


def create(cfg, name, game_dir=None, icon="", java_path="", memory_mb=4096,
           width=854, height=480, jvm_args="", loader_hint="", switch=True):
    """新建实例；game_dir 留空则在 instance_root 下自动建独立目录。"""
    migrate(cfg)
    name = str(name or "").strip() or "新实例"
    root = instance_root(cfg)
    os.makedirs(root, exist_ok=True)

    if game_dir and str(game_dir).strip():
        gdir = os.path.abspath(str(game_dir).strip())
    else:
        base = os.path.join(root, _safe_folder_name(name))
        gdir = base
        n = 2
        while os.path.exists(gdir):
            gdir = os.path.join(root, "%s-%d" % (_safe_folder_name(name), n))
            n += 1
    os.makedirs(gdir, exist_ok=True)

    inst = {
        "id": _new_id(),
        "name": name,
        "icon": (str(icon or "").strip() or "◈")[:4],
        "game_dir": gdir,
        "java_path": str(java_path or "").strip(),
        "memory_mb": int(memory_mb or 4096),
        "width": int(width or 854),
        "height": int(height or 480),
        "jvm_args": str(jvm_args or ""),
        "loader_hint": str(loader_hint or ""),
        "last_version": "",
        "builtin": False,
    }
    cfg.setdefault("instances", []).append(inst)
    if switch:
        cfg["current_instance"] = inst["id"]
        _sync_legacy(cfg, inst)
    _save(cfg)
    return inst


def rename(cfg, iid, new_name):
    inst = get_instance(cfg, iid)
    if inst is None:
        raise KeyError("实例不存在：%s" % iid)
    new_name = str(new_name or "").strip()
    if not new_name:
        raise ValueError("实例名称不能为空")
    inst["name"] = new_name
    _save(cfg)
    return inst


def update(cfg, iid, **fields):
    """更新实例属性；当前实例的改动会镜像到顶层 cfg。"""
    inst = get_instance(cfg, iid)
    if inst is None:
        raise KeyError("实例不存在：%s" % iid)
    for k, v in fields.items():
        if k in _INT_FIELDS:
            try:
                inst[k] = max(512 if k == "memory_mb" else 1, int(v))
            except (TypeError, ValueError):
                raise ValueError("%s 必须是整数" % k)
        elif k in _STR_FIELDS:
            inst[k] = str(v or "").strip() if k != "jvm_args" else str(v or "")
        elif k == "icon":
            inst[k] = str(v or "◈").strip()[:4] or "◈"
    if inst.get("game_dir"):
        os.makedirs(inst["game_dir"], exist_ok=True)
    if cfg.get("current_instance") == iid:
        _sync_legacy(cfg, inst)
    _save(cfg)
    return inst


def switch(cfg, iid):
    inst = get_instance(cfg, iid)
    if inst is None:
        raise KeyError("实例不存在：%s" % iid)
    cfg["current_instance"] = iid
    _sync_legacy(cfg, inst)
    _save(cfg)
    return inst


def delete(cfg, iid):
    """删除实例：只删它自己的 game_dir；默认实例与越界目录一律拒绝。"""
    inst = get_instance(cfg, iid)
    if inst is None:
        raise KeyError("实例不存在：%s" % iid)
    if iid == DEFAULT_ID or inst.get("builtin"):
        raise ValueError("默认实例承载原有游戏目录与已装版本，不能删除；可重命名或复制。")

    gdir = os.path.abspath(inst.get("game_dir") or "")
    root = os.path.abspath(instance_root(cfg))
    # 默认实例目录以其自身记录为准（cfg.game_dir 会随切换变化，不能拿来当保护基准）
    default_inst = get_instance(cfg, DEFAULT_ID)
    legacy = os.path.abspath(default_inst["game_dir"]) if default_inst else legacy_game_dir(cfg)
    app_root = os.path.abspath(util.app_root())

    # 安全闸门：必须在实例根目录内，且绝不能是老全局目录 / 启动器根 / 盘根 / 用户目录
    if not gdir or gdir in (root, legacy, app_root, os.path.expanduser("~"),
                           os.path.splitdrive(gdir)[0] + os.sep):
        raise ValueError("实例目录不在安全范围内，拒绝删除：%s" % gdir)
    if not gdir.lower().startswith(root.lower() + os.sep):
        raise ValueError("实例目录不在实例根目录内，拒绝删除：%s" % gdir)

    shutil.rmtree(gdir, ignore_errors=False)

    cfg["instances"] = [x for x in cfg.get("instances", []) if x["id"] != iid]
    if cfg.get("current_instance") == iid:
        cfg["current_instance"] = DEFAULT_ID
        _sync_legacy(cfg, current(cfg))
    _save(cfg)
    return gdir


def duplicate(cfg, iid, new_name=None, switch_to=True):
    """复制实例配置与启动参数到一个全新的独立空目录（不复制版本库/存档等大文件）。"""
    src = get_instance(cfg, iid)
    if src is None:
        raise KeyError("实例不存在：%s" % iid)
    name = str(new_name or "").strip() or ("%s 副本" % src["name"])
    return create(
        cfg, name, game_dir=None, icon=src.get("icon") or "◈",
        java_path=src.get("java_path") or "", memory_mb=src.get("memory_mb") or 4096,
        width=src.get("width") or 854, height=src.get("height") or 480,
        jvm_args=src.get("jvm_args") or "", loader_hint=src.get("loader_hint") or "",
        switch=switch_to,
    )


# ---------------------------------------------------------------- 导出 / 导入
def export_instance(cfg, iid, dest_path):
    inst = get_instance(cfg, iid)
    if inst is None:
        raise KeyError("实例不存在：%s" % iid)
    payload = {
        "format": EXPORT_FORMAT,
        "format_version": EXPORT_VERSION,
        "exported_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "launcher": "MCLite",
        "launcher_version": LAUNCHER_VERSION,
        "instance": {k: inst.get(k) for k in INSTANCE_FIELDS},
    }
    dest_path = os.path.abspath(dest_path)
    os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)
    with open(dest_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return dest_path


def import_instance(cfg, src_path, new_name=None, switch_to=True):
    """从导出 json 生成新实例；目录缺失则创建。返回 (inst, missing_version)。"""
    with open(src_path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    if not isinstance(payload, dict) or payload.get("format") != EXPORT_FORMAT:
        raise ValueError("不是有效的 MC Lite 实例配置文件")
    data = payload.get("instance") or {}
    if not isinstance(data, dict) or not data.get("name"):
        raise ValueError("实例配置缺少 name 字段")

    name = str(new_name or data.get("name") or "导入的实例").strip()
    inst = create(
        cfg, name, game_dir=None, icon=data.get("icon") or "◈",
        java_path=data.get("java_path") or "", memory_mb=data.get("memory_mb") or 4096,
        width=data.get("width") or 854, height=data.get("height") or 480,
        jvm_args=data.get("jvm_args") or "", loader_hint=data.get("loader_hint") or "",
        switch=switch_to,
    )
    # 保留导出时记录的最后版本，用于缺失提示
    lv = str(data.get("last_version") or "")
    if lv:
        inst["last_version"] = lv
        _save(cfg)

    missing_version = None
    if lv and not os.path.isfile(os.path.join(inst["game_dir"], "versions", lv, lv + ".json")):
        missing_version = lv
    return inst, missing_version


# ---------------------------------------------------------------- 备份 / 恢复
def backups_dir(game_dir):
    return os.path.join(game_dir, "backups")


def backup_saves(game_dir, dest_dir=None, include_options=True, include_config=False,
                 prefix="saves-"):
    """把 saves（可选 options.txt / config）打包成带时间戳的 zip，放到 backups 子目录。

    prefix 用于区分普通备份（saves-）与恢复前自动备份（pre-restore-），避免同秒覆盖。
    返回 (zip_path, 文件数)。
    """
    game_dir = os.path.abspath(game_dir)
    saves_dir = os.path.join(game_dir, "saves")
    if not os.path.isdir(saves_dir):
        raise FileNotFoundError("saves 目录不存在：%s" % saves_dir)

    out_dir = dest_dir or backups_dir(game_dir)
    os.makedirs(out_dir, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    zip_path = os.path.join(out_dir, "%s%s.zip" % (prefix, stamp))
    # 同秒多次备份时加序号，绝不覆盖已有备份
    seq = 1
    while os.path.exists(zip_path):
        zip_path = os.path.join(out_dir, "%s%s-%d.zip" % (prefix, stamp, seq))
        seq += 1
    n = 0
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _dirs, files in os.walk(saves_dir):
            for fn in files:
                full = os.path.join(root, fn)
                arc = os.path.relpath(full, game_dir).replace(os.sep, "/")
                zf.write(full, arc)
                n += 1
        if include_options:
            opt = os.path.join(game_dir, "options.txt")
            if os.path.isfile(opt):
                zf.write(opt, "options.txt")
                n += 1
        if include_config and os.path.isdir(os.path.join(game_dir, "config")):
            cfg_dir = os.path.join(game_dir, "config")
            for root, _dirs, files in os.walk(cfg_dir):
                for fn in files:
                    full = os.path.join(root, fn)
                    arc = os.path.relpath(full, game_dir).replace(os.sep, "/")
                    zf.write(full, arc)
                    n += 1
    return zip_path, n


def restore_saves(game_dir, zip_path):
    """恢复前先把当前 saves 自动备份一次，再把 zip 安全解压回实例目录。

    返回 dict(pre_backup=路径或None, extracted=文件数, zip=路径)。
    """
    game_dir = os.path.abspath(game_dir)
    zip_path = os.path.abspath(zip_path)
    if not os.path.isfile(zip_path):
        raise FileNotFoundError("备份压缩包不存在：%s" % zip_path)

    pre_backup = None
    saves_dir = os.path.join(game_dir, "saves")
    if os.path.isdir(saves_dir) and any(os.scandir(saves_dir)):
        # 用独立前缀，避免与正在恢复的 zip 同秒同名而覆盖它
        pre_backup, _n = backup_saves(game_dir, include_options=True, include_config=False,
                                      prefix="pre-restore-")

    # 统计 zip 内实际文件数（覆盖写也算恢复成功）
    extracted = 0
    try:
        with zipfile.ZipFile(zip_path) as zf:
            extracted = sum(1 for n in zf.namelist() if not n.endswith("/"))
    except Exception:
        extracted = 0

    util.safe_extract_zip(zip_path, game_dir, skip_prefix=())
    return {"pre_backup": pre_backup, "extracted": extracted, "zip": zip_path}


def list_backups(game_dir):
    d = backups_dir(game_dir)
    try:
        files = [os.path.join(d, f) for f in os.listdir(d) if f.lower().endswith(".zip")]
    except Exception:
        return []
    files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return files
