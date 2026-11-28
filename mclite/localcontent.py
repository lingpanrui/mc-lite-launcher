# -*- coding: utf-8 -*-
"""本地内容管理后端（批次4，v1.6.0）

全部按「当前实例」的 game_dir 工作，纯本地文件操作，不联网、不占位：

- 四类内容扫描：模组 mods/、资源包 resourcepacks/、光影 shaderpacks/、数据包 datapacks/，
  以及存档 saves/（世界名 / 大小 / 最后修改时间）；
- 启用 / 禁用：``xxx.jar`` <-> ``xxx.jar.disabled``（只改后缀，保留多点文件名，
  已存在同名目标时抛 ConflictError，绝不覆盖）；
- 删除：只删选中的那一个文件，绝不整目录删除；
- 本地导入：复制进对应目录、重名安全避让、写 ``mclite-local-manifest.json`` 来源清单；
- .jar 轻量识别：fabric.mod.json / META-INF/neoforge.mods.toml / META-INF/mods.toml / mcmod.info，
  输出归一化信息，供界面做加载器不匹配黄色提示（不阻断），并为批次6 冲突预检预留结构；
- Windows 拖放：ctypes 构造 / 解码 DROPFILES（WM_DROPFILES），不依赖 tkdnd。

设计约束见 _CONVENTIONS.md 与 _progress.md 批次4 条目。
"""
import ctypes
import ctypes.wintypes as wt
import datetime
import gzip
import json
import os
import shutil
import struct
import zipfile

from . import util

# 内容分类 -> 实例内目录（与 contenthub.CATEGORY_DIRS 保持一致，单独定义避免循环导入）
FILE_CATEGORIES = {
    "mod": "mods",
    "resourcepack": "resourcepacks",
    "shader": "shaderpacks",
    "datapack": "datapacks",
}
SAVES_CATEGORY = "saves"
ALL_CATEGORIES = list(FILE_CATEGORIES.keys()) + [SAVES_CATEGORY]

DISABLED_SUFFIX = ".disabled"
MANIFEST_NAME = "mclite-local-manifest.json"
MANIFEST_FORMAT = "mclite-local-manifest"

# 各分类允许识别的启用文件扩展名（禁用态在其后再追加 .disabled）
CATEGORY_EXTS = {
    "mod": (".jar",),
    "resourcepack": (".zip", ".jar"),
    "shader": (".zip",),
    "datapack": (".zip",),
}

WM_DROPFILES = 0x0233
GWLP_WNDPROC = -4
GMEM_MOVEABLE = 0x0002
GMEM_ZEROINIT = 0x0040


class LocalContentError(Exception):
    """本地内容操作通用错误（界面捕获后友好提示）。"""


class ConflictError(LocalContentError):
    """目标文件已存在，拒绝覆盖。"""


# ================================================================ 路径安全
def category_dir(game_dir, category):
    """返回某分类在实例目录下的绝对路径；非法分类抛错。"""
    if category == SAVES_CATEGORY:
        folder = SAVES_CATEGORY
    else:
        folder = FILE_CATEGORIES.get(category)
    if not folder:
        raise LocalContentError("未知内容分类：%s" % category)
    return os.path.abspath(os.path.join(os.path.abspath(game_dir), folder))


def _safe_name(name):
    """清洗文件名：去路径分隔与控制字符，拒绝 .. 与空名。"""
    name = str(name or "").replace("\\", "/").split("/")[-1].strip()
    name = "".join("_" if ord(ch) < 32 else ch for ch in name)
    if not name or name in (".", "..") or ".." in name:
        raise LocalContentError("非法文件名：%r" % name)
    return name


def _resolve_in_dir(dir_path, name):
    """把文件名限定在 dir_path 内，返回绝对路径；越界 / 目录一律拒绝。"""
    name = _safe_name(name)
    base = os.path.abspath(dir_path)
    target = os.path.abspath(os.path.join(base, name))
    if target != base and not target.startswith(base + os.sep):
        raise LocalContentError("路径越界，拒绝操作：%s" % name)
    return target


# ================================================================ 来源清单
def load_manifest(game_dir):
    """读取实例级本地导入清单；不存在 / 损坏返回空结构。"""
    path = os.path.join(os.path.abspath(game_dir), MANIFEST_NAME)
    data = util.read_json(path, default=None)
    if not isinstance(data, dict) or not isinstance(data.get("files"), dict):
        return {"format": MANIFEST_FORMAT, "files": {}}
    return data


def save_manifest(game_dir, manifest):
    path = os.path.join(os.path.abspath(game_dir), MANIFEST_NAME)
    util.write_json(path, manifest)


def _manifest_key(name):
    """清单以「启用态基础文件名」为键，禁用/启用切换后仍能查到来源。"""
    n = str(name or "")
    if n.endswith(DISABLED_SUFFIX):
        n = n[: -len(DISABLED_SUFFIX)]
    return n


def source_of(game_dir, name):
    """按文件名（启用或禁用态均可）查来源；查不到返回「本地文件」。"""
    manifest = load_manifest(game_dir)
    rec = manifest.get("files", {}).get(_manifest_key(name))
    if isinstance(rec, dict) and rec.get("source"):
        return str(rec["source"])
    return "本地文件"


def record_import(game_dir, category, dest_name, source="本地导入", project_id=None, size=None):
    manifest = load_manifest(game_dir)
    key = _manifest_key(dest_name)
    manifest["files"][key] = {
        "source": source,
        "category": category,
        "project_id": project_id or "",
        "size": int(size or 0),
        "imported_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    save_manifest(game_dir, manifest)


# ================================================================ 启用 / 禁用
def is_disabled(filename):
    return str(filename or "").lower().endswith(DISABLED_SUFFIX)


def toggle_enabled(path):
    """在 启用 <-> .disabled 之间切换，返回 (新路径, 切换后是否启用)。

    - 禁用：``x.jar`` -> ``x.jar.disabled``；
    - 启用：``x.jar.disabled`` -> ``x.jar``；
    - 只在同目录改名，保留文件名中的多个点（仅追加/剥离末尾后缀）；
    - 目标已存在时抛 ConflictError，绝不覆盖。
    """
    p = os.path.abspath(str(path))
    if not os.path.isfile(p):
        raise LocalContentError("文件不存在：%s" % p)
    name = os.path.basename(p)
    if is_disabled(name):
        target = p[: -len(DISABLED_SUFFIX)]
        enabling = True
    else:
        target = p + DISABLED_SUFFIX
        enabling = False
    if os.path.exists(target):
        raise ConflictError("目标文件已存在，为避免覆盖已取消：%s" % os.path.basename(target))
    os.rename(p, target)
    return target, enabling


def disable_path(path):
    """显式禁用（幂等：已是禁用态直接返回原路径）。"""
    p = os.path.abspath(str(path))
    if is_disabled(os.path.basename(p)):
        return p, False
    return toggle_enabled(p)


def enable_path(path):
    """显式启用（幂等：已是启用态直接返回原路径）。"""
    p = os.path.abspath(str(path))
    if not is_disabled(os.path.basename(p)):
        return p, True
    return toggle_enabled(p)


# ================================================================ 删除
def delete_content_file(game_dir, category, name):
    """只删除选中的那一个文件（绝不删目录、绝不连带删同名对端）。"""
    if category == SAVES_CATEGORY:
        raise LocalContentError("存档是文件夹，本批不提供整目录删除；请在游戏内或备份后处理。")
    d = category_dir(game_dir, category)
    target = _resolve_in_dir(d, name)
    if os.path.isdir(target):
        raise LocalContentError("拒绝删除目录：%s" % name)
    if not os.path.isfile(target):
        raise LocalContentError("文件不存在：%s" % name)
    os.remove(target)
    return target


# ================================================================ 扫描
def _mtime_ts(path):
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


def _scan_file_category(game_dir, category, inst_loader=""):
    d = category_dir(game_dir, category)
    items = []
    if not os.path.isdir(d):
        return items
    exts = CATEGORY_EXTS.get(category, (".jar", ".zip"))
    for fn in sorted(os.listdir(d)):
        full = os.path.join(d, fn)
        if not os.path.isfile(full):
            continue
        low = fn.lower()
        disabled = is_disabled(low)
        base_low = low[: -len(DISABLED_SUFFIX)] if disabled else low
        if not any(base_low.endswith(ext) for ext in exts):
            continue
        try:
            size = os.path.getsize(full)
        except OSError:
            size = 0
        info = {"loaders": [], "ids": [], "name": None, "version": None,
                "dependencies": {}, "java": None}
        warning = None
        if category == "mod" and base_low.endswith(".jar"):
            info = detect_mod_info(full)
            warning = loader_warning(info, inst_loader)
        items.append({
            "category": category,
            "name": fn,
            "base_name": fn[: -len(DISABLED_SUFFIX)] if disabled else fn,
            "path": full,
            "size": size,
            "mtime": _mtime_ts(full),
            "enabled": not disabled,
            "source": source_of(game_dir, fn),
            "loader": (info.get("loaders") or [None])[0],
            "mod_name": info.get("name"),
            "mod_version": info.get("version"),
            "warning": warning,
        })
    return items


def _dir_size(path):
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def scan_saves(game_dir):
    """扫描 saves/ 下的世界目录（含 level.dat），返回世界名/大小/修改时间。"""
    d = category_dir(game_dir, SAVES_CATEGORY)
    items = []
    if not os.path.isdir(d):
        return items
    for fn in sorted(os.listdir(d)):
        full = os.path.join(d, fn)
        if not os.path.isdir(full):
            continue
        level_dat = os.path.join(full, "level.dat")
        if not os.path.isfile(level_dat):
            continue
        world_name = read_world_name(level_dat) or fn
        items.append({
            "category": SAVES_CATEGORY,
            "name": fn,
            "world_name": world_name,
            "path": full,
            "size": _dir_size(full),
            "mtime": _mtime_ts(level_dat) or _mtime_ts(full),
            "enabled": True,
            "source": "本地存档",
        })
    return items


def scan_category(game_dir, category, inst_loader=""):
    if category == SAVES_CATEGORY:
        return scan_saves(game_dir)
    if category not in FILE_CATEGORIES:
        raise LocalContentError("未知内容分类：%s" % category)
    return _scan_file_category(game_dir, category, inst_loader=inst_loader)


def scan_all(game_dir, inst_loader=""):
    out = {}
    for cat in ALL_CATEGORIES:
        out[cat] = scan_category(game_dir, cat, inst_loader=inst_loader)
    return out


# ================================================================ .jar 轻量识别
def _read_zip_text(zf, name):
    try:
        return zf.read(name).decode("utf-8", "ignore")
    except KeyError:
        return None
    except Exception:
        return None


def detect_mod_info(jar_path):
    """读取 jar 内元数据，归一化为模组信息（不抛异常，损坏文件返回空结构）。

    返回：{loaders:[...], ids:[...], name, version, dependencies:{}, java}
    为批次6 冲突预检预留：ids / dependencies / java 已按统一结构给出。
    """
    empty = {"loaders": [], "ids": [], "name": None, "version": None,
             "dependencies": {}, "java": None}
    try:
        with zipfile.ZipFile(jar_path) as zf:
            names = set(zf.namelist())
            # 1) Fabric
            if "fabric.mod.json" in names:
                try:
                    data = json.loads(_read_zip_text(zf, "fabric.mod.json") or "{}")
                except Exception:
                    data = {}
                deps = data.get("depends") if isinstance(data.get("depends"), dict) else {}
                java = deps.get("java") if isinstance(deps, dict) else None
                return {
                    "loaders": ["fabric"],
                    "ids": [str(data.get("id"))] if data.get("id") else [],
                    "name": data.get("name"),
                    "version": str(data.get("version")) if data.get("version") is not None else None,
                    "dependencies": deps if isinstance(deps, dict) else {},
                    "java": str(java) if java else None,
                }
            # 2) NeoForge（优先于 Forge，二者都用 mods.toml 时以 neoforge.mods.toml 为准）
            if "META-INF/neoforge.mods.toml" in names:
                return _parse_mods_toml(_read_zip_text(zf, "META-INF/neoforge.mods.toml"),
                                       loader="neoforge")
            # 3) Forge
            if "META-INF/mods.toml" in names:
                return _parse_mods_toml(_read_zip_text(zf, "META-INF/mods.toml"),
                                       loader="forge")
            # 4) 旧版 Forge mcmod.info（JSON 数组）
            if "mcmod.info" in names:
                try:
                    arr = json.loads(_read_zip_text(zf, "mcmod.info") or "[]")
                    if isinstance(arr, list) and arr and isinstance(arr[0], dict):
                        first = arr[0]
                        return {
                            "loaders": ["forge"],
                            "ids": [str(first.get("modid"))] if first.get("modid") else [],
                            "name": first.get("name"),
                            "version": str(first.get("version")) if first.get("version") is not None else None,
                            "dependencies": {},
                            "java": None,
                        }
                except Exception:
                    pass
    except Exception:
        return empty
    return empty


def _parse_mods_toml(text, loader):
    """从 Forge/NeoForge mods.toml 粗取 modId/displayName/version（不引入 TOML 依赖）。"""
    if not text:
        return {"loaders": [loader], "ids": [], "name": None, "version": None,
                "dependencies": {}, "java": None}
    mod_id = None
    display = None
    version = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if mod_id is None and line.startswith("modId") and "=" in line:
            mod_id = _toml_string(line.split("=", 1)[1])
        elif display is None and line.startswith("displayName") and "=" in line:
            display = _toml_string(line.split("=", 1)[1])
        elif version is None and line.startswith("version") and "=" in line:
            version = _toml_string(line.split("=", 1)[1])
    return {
        "loaders": [loader],
        "ids": [mod_id] if mod_id else [],
        "name": display,
        "version": version,
        "dependencies": {},
        "java": None,
    }


def _toml_string(v):
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in ('"', "'"):
        return v[1:-1]
    return v


def instance_loader(game_dir, last_version=""):
    """读当前实例最后使用版本的 version json，返回加载器键（vanilla/未知 -> ""）。"""
    if not last_version:
        return ""
    meta_path = os.path.join(os.path.abspath(game_dir), "versions", last_version, last_version + ".json")
    meta = util.read_json(meta_path, default=None)
    if not isinstance(meta, dict):
        return ""
    try:
        from . import forge
        ld = forge.detect_loader(meta)
        return "" if ld == "vanilla" else str(ld or "")
    except Exception:
        return ""


def loader_warning(info, inst_loader):
    """加载器不匹配的黄色提示（不阻断）；匹配 / 未知时返回 None。"""
    if not inst_loader or not info.get("loaders"):
        return None
    if inst_loader in info["loaders"]:
        return None
    return "加载器可能不匹配：该文件面向 %s，当前实例加载器为 %s；仍可放入，但游戏内可能无法加载。" % (
        " / ".join(info["loaders"]), inst_loader)


# ================================================================ 归档分类（拖放/导入）
def classify_archive(path):
    """按扩展名 + 压缩包内容判断本地文件应进哪个分类；无法判断返回 None。"""
    low = str(path).lower()
    try:
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
            has = lambda n: n in names
            if has("fabric.mod.json") or has("META-INF/mods.toml") or has("META-INF/neoforge.mods.toml") or has("mcmod.info"):
                return "mod"
            if any(n.startswith("shaders/") for n in names) or has("shaders.properties"):
                return "shader"
            if has("pack.mcmeta"):
                if any(n.startswith("assets/") for n in names):
                    return "resourcepack"
                if any(n.startswith("data/") for n in names):
                    return "datapack"
                return "resourcepack"
    except Exception:
        pass
    if low.endswith(".jar"):
        return "mod"
    if low.endswith(".zip"):
        return "resourcepack"
    return None


def _unique_dest(target_dir, filename):
    """目标已存在时安全避让：name.ext -> name (1).ext，绝不覆盖。"""
    base, ext = os.path.splitext(filename)
    candidate = os.path.join(target_dir, filename)
    n = 1
    while os.path.exists(candidate):
        candidate = os.path.join(target_dir, "%s (%d)%s" % (base, n, ext))
        n += 1
    return candidate


def import_files(game_dir, category, src_paths, status=None):
    """把本地文件复制进当前实例对应目录（不移动源文件）。

    category 为 "auto" 时按 classify_archive 逐个判定；否则用指定分类。
    返回结果列表：{src, dest, category, size, skipped, reason, info, warning}。
    """
    status = status or (lambda s: None)
    results = []
    for src in src_paths or []:
        src = os.path.abspath(str(src))
        item = {"src": src, "dest": None, "category": None, "size": 0,
                "skipped": False, "reason": "", "info": None, "warning": None}
        try:
            if not os.path.isfile(src):
                raise LocalContentError("源文件不存在")
            eff = category
            if eff in (None, "auto"):
                eff = classify_archive(src)
            if eff not in FILE_CATEGORIES:
                raise LocalContentError("无法识别为模组/资源包/光影/数据包（仅支持 .jar/.zip）")
            target_dir = category_dir(game_dir, eff)
            os.makedirs(target_dir, exist_ok=True)
            filename = _safe_name(os.path.basename(src))
            dest = os.path.join(target_dir, filename)
            size = os.path.getsize(src)
            if os.path.exists(dest) and os.path.getsize(dest) == size:
                item.update({"category": eff, "dest": dest, "size": size,
                             "skipped": True, "reason": "目标已存在且大小一致，跳过"})
                results.append(item)
                status("跳过已存在：%s" % filename)
                continue
            if os.path.exists(dest):
                dest = _unique_dest(target_dir, filename)
                filename = os.path.basename(dest)
            shutil.copy2(src, dest)
            info = None
            warning = None
            if eff == "mod" and dest.lower().endswith(".jar"):
                info = detect_mod_info(dest)
                warning = loader_warning(info, instance_loader(game_dir))
            record_import(game_dir, eff, filename, source="本地导入", size=size)
            item.update({"category": eff, "dest": dest, "size": size,
                         "info": info, "warning": warning})
            status("已导入 %s -> %s" % (filename, eff))
        except Exception as e:
            item.update({"skipped": True, "reason": str(e)})
            status("导入失败：%s（%s）" % (os.path.basename(src), e))
        results.append(item)
    return results


# ================================================================ 存档 NBT（最小读取）
class _NbtReader:
    def __init__(self, data):
        self.d = data
        self.i = 0

    def u8(self):
        v = self.d[self.i]; self.i += 1; return v

    def i16(self):
        v = struct.unpack_from(">h", self.d, self.i)[0]; self.i += 2; return v

    def i32(self):
        v = struct.unpack_from(">i", self.d, self.i)[0]; self.i += 4; return v

    def i64(self):
        v = struct.unpack_from(">q", self.d, self.i)[0]; self.i += 8; return v

    def f32(self):
        v = struct.unpack_from(">f", self.d, self.i)[0]; self.i += 4; return v

    def f64(self):
        v = struct.unpack_from(">d", self.d, self.i)[0]; self.i += 8; return v

    def string(self):
        n = self.i16()
        s = self.d[self.i:self.i + n].decode("utf-8", "ignore")
        self.i += n
        return s

    def payload(self, tag):
        if tag == 1:
            return self.u8()
        if tag == 2:
            return self.i16()
        if tag == 3:
            return self.i32()
        if tag == 4:
            return self.i64()
        if tag == 5:
            return self.f32()
        if tag == 6:
            return self.f64()
        if tag == 7:
            n = self.i32(); self.i += n; return self.d[self.i - n:self.i]
        if tag == 8:
            return self.string()
        if tag == 9:
            ct = self.u8(); n = self.i32()
            return [self.payload(ct) for _ in range(n)]
        if tag == 10:
            out = {}
            while True:
                t = self.u8()
                if t == 0:
                    break
                name = self.string()
                out[name] = self.payload(t)
            return out
        if tag == 11:
            n = self.i32(); self.i += 4 * n; return None
        if tag == 12:
            n = self.i32(); self.i += 8 * n; return None
        raise ValueError("未知 NBT 标签 %d" % tag)

    def root(self):
        tag = self.u8()
        if tag == 0:
            return {}
        self.string()  # 根名
        return self.payload(tag)


def read_world_name(level_dat_path):
    """从 level.dat（gzip NBT）读取 Data.Name；失败返回 None。"""
    try:
        with gzip.open(level_dat_path, "rb") as f:
            data = f.read()
        root = _NbtReader(data).root()
        data_tag = root.get("Data") if isinstance(root, dict) else None
        if isinstance(data_tag, dict):
            name = data_tag.get("Name")
            if isinstance(name, str) and name.strip():
                return name.strip()
    except Exception:
        return None
    return None


# ================================================================ Windows 拖放（WM_DROPFILES）
class DROPFILES(ctypes.Structure):
    _fields_ = [
        ("pFiles", wt.DWORD),
        ("pt", wt.POINT),
        ("fNC", wt.BOOL),
        ("fWide", wt.BOOL),
    ]


def _user32():
    u = ctypes.windll.user32
    u.GetWindowLongPtrW.restype = ctypes.c_void_p
    u.GetWindowLongPtrW.argtypes = [wt.HWND, ctypes.c_int]
    u.SetWindowLongPtrW.restype = ctypes.c_void_p
    u.SetWindowLongPtrW.argtypes = [wt.HWND, ctypes.c_int, ctypes.c_void_p]
    u.CallWindowProcW.restype = ctypes.c_long
    u.CallWindowProcW.argtypes = [ctypes.c_void_p, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
    return u


def _shell32():
    s = ctypes.windll.shell32
    s.DragQueryFileW.restype = wt.UINT
    s.DragQueryFileW.argtypes = [wt.HANDLE, wt.UINT, wt.LPWSTR, wt.UINT]
    s.DragFinish.argtypes = [wt.HANDLE]
    s.DragAcceptFiles.argtypes = [wt.HWND, wt.BOOL]
    return s


def decode_dropfiles(h_drop):
    """从 HDROP 解码出文件路径列表（解码后自动 DragFinish 释放）。"""
    s = _shell32()
    count = s.DragQueryFileW(h_drop, 0xFFFFFFFF, None, 0)
    paths = []
    for i in range(count):
        n = s.DragQueryFileW(h_drop, i, None, 0)
        buf = ctypes.create_unicode_buffer(n + 1)
        s.DragQueryFileW(h_drop, i, buf, n + 1)
        paths.append(buf.value)
    s.DragFinish(h_drop)
    return paths


def build_dropfiles(paths):
    """构造一个 HDROP（DROPFILES + 宽字符路径双零结尾），供 PostMessage 模拟拖放。

    返回 HGLOBAL（wParam）；接收方 decode_dropfiles 后由 DragFinish 释放。
    """
    payload = "".join(str(p) + "\0" for p in paths) + "\0"
    raw = payload.encode("utf-16-le")
    header_size = ctypes.sizeof(DROPFILES)
    total = header_size + len(raw)
    kernel32 = ctypes.windll.kernel32
    kernel32.GlobalAlloc.restype = wt.HGLOBAL
    kernel32.GlobalAlloc.argtypes = [wt.UINT, ctypes.c_size_t]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [wt.HGLOBAL]
    kernel32.GlobalUnlock.argtypes = [wt.HGLOBAL]
    h = kernel32.GlobalAlloc(GMEM_MOVEABLE | GMEM_ZEROINIT, total)
    if not h:
        raise MemoryError("GlobalAlloc 失败")
    ptr = kernel32.GlobalLock(h)
    try:
        df = DROPFILES()
        df.pFiles = header_size
        df.pt = wt.POINT(0, 0)
        df.fNC = 0
        df.fWide = 1
        ctypes.memmove(ptr, ctypes.byref(df), header_size)
        ctypes.memmove(ptr + header_size, raw, len(raw))
    finally:
        kernel32.GlobalUnlock(h)
    return h


def install_drop_target(hwnd, on_drop):
    """子类化窗口过程拦截 WM_DROPFILES，注册 DragAcceptFiles。

    返回 {"old_proc", "callback"}；调用方必须长期持有 callback 引用防止被 GC。
    on_drop(paths) 在窗口过程（UI 线程）被调用，内部应自行线程化耗时复制。
    """
    u = _user32()
    old_proc = u.GetWindowLongPtrW(hwnd, GWLP_WNDPROC)
    WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_long, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)

    def _proc(h, msg, w, l):
        if msg == WM_DROPFILES:
            try:
                paths = decode_dropfiles(w)
                if paths:
                    on_drop(paths)
            except Exception:
                pass
            return 0
        return u.CallWindowProcW(old_proc, h, msg, w, l)

    cb = WNDPROC(_proc)
    u.SetWindowLongPtrW(hwnd, GWLP_WNDPROC, ctypes.cast(cb, ctypes.c_void_p))
    _shell32().DragAcceptFiles(hwnd, True)
    return {"old_proc": old_proc, "callback": cb}
