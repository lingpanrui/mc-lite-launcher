# -*- coding: utf-8 -*-
"""批次3 资源中心后端纯自测（headless，不弹窗、不访问外网）。

覆盖：
1. build_facets 分类 facet 构造；
2. safe_join 路径穿越 / 绝对路径 / 盘符 / 反斜杠防护；
3. map_dependencies 四种加载器 + 纯原版映射；
4. file_installable 的 env.client 过滤；
5. parse_mrpack 解析与缺 index 报错；
6. install_mrpack 用 file:// 本地源跑通「下载→校验→落盘→overrides→清单」，
   并验证幂等重跑与非法路径失败留痕。

运行：python _test_content_hub.py
"""
import hashlib
import json
import os
import shutil
import sys
import tempfile
import zipfile

# 必须在 import mclite.util 之前隔离 APPDATA，避免污染真实 config
_TMP = tempfile.mkdtemp(prefix="mclite_test_ch_")
os.environ["APPDATA"] = _TMP

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

from mclite import contenthub  # noqa: E402

PASS = 0
FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  [PASS] %s" % name)
    else:
        FAIL += 1
        print("  [FAIL] %s  %s" % (name, detail))


def sha1_bytes(b):
    return hashlib.sha1(b).hexdigest()


# ---------------------------------------------------------------- 1 facet
print("== build_facets ==")
f = contenthub.build_facets("mod", "fabric", "1.20.1")
check("mod+loader+version 三层", f == [
    ["project_type:mod"], ["categories:fabric"], ["versions:1.20.1"]], f)
f0 = contenthub.build_facets()
check("空条件返回空列表", f0 == [], f0)
fp = contenthub.build_facets("modpack")
check("仅 project_type", fp == [["project_type:modpack"]], fp)

# ---------------------------------------------------------------- 2 路径
print("== safe_join ==")
base = os.path.abspath(os.path.join(_TMP, "game"))
os.makedirs(base, exist_ok=True)
check("正常相对路径", contenthub.safe_join(base, "mods/a.jar") ==
      os.path.abspath(os.path.join(base, "mods", "a.jar")))
check("反斜杠归一", contenthub.safe_join(base, "mods\\sub\\b.jar") ==
      os.path.abspath(os.path.join(base, "mods", "sub", "b.jar")))
check("拒绝 .. 穿越", contenthub.safe_join(base, "../evil.jar") is None)
check("拒绝深层 ..", contenthub.safe_join(base, "mods/../../x.jar") is None)
check("拒绝前导斜杠绝对路径", contenthub.safe_join(base, "/etc/passwd") is None)
check("拒绝 Windows 盘符", contenthub.safe_join(base, "C:\\Windows\\x.jar") is None)
check("拒绝空路径", contenthub.safe_join(base, "") is None)
check("点段被归一", contenthub.safe_join(base, "./mods/./a.jar") ==
      os.path.abspath(os.path.join(base, "mods", "a.jar")))

# ---------------------------------------------------------------- 3 依赖映射
print("== map_dependencies ==")
check("fabric", contenthub.map_dependencies(
    {"dependencies": {"minecraft": "1.20.1", "fabric-loader": "0.16.0"}}) ==
    {"minecraft": "1.20.1", "loader": "fabric", "loader_version": "0.16.0"})
check("quilt", contenthub.map_dependencies(
    {"dependencies": {"minecraft": "1.20.1", "quilt-loader": "0.24.0"}})["loader"] == "quilt")
check("forge", contenthub.map_dependencies(
    {"dependencies": {"minecraft": "1.20.1", "forge": "47.4.29"}})["loader"] == "forge")
check("neoforge", contenthub.map_dependencies(
    {"dependencies": {"minecraft": "1.21.1", "neoforge": "21.1.72"}})["loader"] == "neoforge")
van = contenthub.map_dependencies({"dependencies": {"minecraft": "1.20.4"}})
check("纯原版 loader=None", van["loader"] is None and van["minecraft"] == "1.20.4", van)
check("空 index 不炸", contenthub.map_dependencies({})["minecraft"] == "")

# ---------------------------------------------------------------- 4 env 过滤
print("== file_installable ==")
check("required 安装", contenthub.file_installable({"env": {"client": "required"}}) is True)
check("unsupported 跳过", contenthub.file_installable({"env": {"client": "unsupported"}}) is False)
check("optional 默认跳过", contenthub.file_installable({"env": {"client": "optional"}}) is False)
check("optional 显式包含", contenthub.file_installable(
    {"env": {"client": "optional"}}, include_optional=True) is True)
check("缺 env 视为 required", contenthub.file_installable({}) is True)

# ---------------------------------------------------------------- 5/6 mrpack
print("== parse_mrpack + install_mrpack（file:// 本地源） ==")
src = os.path.join(_TMP, "src")
os.makedirs(src, exist_ok=True)
a_bytes = b"PK\x03\x04 fake mod jar content A"
r_bytes = b"PK\x03\x04 fake resourcepack zip R"
with open(os.path.join(src, "a.jar"), "wb") as fh:
    fh.write(a_bytes)
with open(os.path.join(src, "r.zip"), "wb") as fh:
    fh.write(r_bytes)

index = {
    "formatVersion": 1,
    "game": "minecraft",
    "name": "自测整合包",
    "versionId": "1.0.0-test",
    "summary": "headless test",
    "dependencies": {"minecraft": "1.20.1", "fabric-loader": "0.16.0"},
    "files": [
        {"path": "mods/a.jar", "fileSize": len(a_bytes),
         "hashes": {"sha1": sha1_bytes(a_bytes)},
         "downloads": ["file:///%s" % os.path.join(src, "a.jar").replace("\\", "/")],
         "env": {"client": "required", "server": "required"}},
        {"path": "resourcepacks/r.zip", "fileSize": len(r_bytes),
         "hashes": {"sha1": sha1_bytes(r_bytes)},
         "downloads": ["file:///%s" % os.path.join(src, "r.zip").replace("\\", "/")],
         "env": {"client": "required", "server": "optional"}},
        {"path": "mods/server-only.jar", "fileSize": 1,
         "hashes": {"sha1": "x"}, "downloads": ["file:///none"],
         "env": {"client": "unsupported", "server": "required"}},
        {"path": "../evil.jar", "fileSize": 1, "hashes": {"sha1": "x"},
         "downloads": ["file:///none"], "env": {"client": "required"}},
    ],
}
pack_path = os.path.join(_TMP, "test.mrpack")
with zipfile.ZipFile(pack_path, "w", zipfile.ZIP_DEFLATED) as zf:
    zf.writestr("modrinth.index.json", json.dumps(index, ensure_ascii=False))
    zf.writestr("overrides/config/modmenu.json", json.dumps({"key": "value"}, ensure_ascii=False))
    zf.writestr("overrides/options.txt", "renderDistance:12\n")

# parse
parsed_index, overrides = contenthub.parse_mrpack(pack_path)
check("parse 读到 files=4", len(parsed_index["files"]) == 4)
check("parse 读到 2 个 overrides", len(overrides) == 2, overrides)
summary = contenthub.pack_summary(pack_path)
# total_bytes 按清单全量求和（含被跳过/非法的两条占位文件，各 fileSize=1）
check("pack_summary 名称/文件数/字节", summary["name"] == "自测整合包"
      and summary["file_count"] == 4
      and summary["total_bytes"] == len(a_bytes) + len(r_bytes) + 2, summary)

# 缺 index 报错
bad_pack = os.path.join(_TMP, "bad.mrpack")
with zipfile.ZipFile(bad_pack, "w") as zf:
    zf.writestr("readme.txt", "no index")
try:
    contenthub.parse_mrpack(bad_pack)
    check("缺 index 抛错", False)
except ValueError:
    check("缺 index 抛错", True)

# 安装（不装运行环境，纯文件/overrides 链路）
game_dir = os.path.join(_TMP, "game_inst")
os.makedirs(game_dir, exist_ok=True)
logs = []
res = contenthub.install_mrpack(
    pack_path, game_dir, status=lambda s: logs.append(s),
    progress=lambda f: None, install_runtime_flag=False)

check("成功下载 2 个文件", res["success"] == 2, res)
check("跳过 1 个纯服务端文件", res["skipped"] == 1, res)
check("非法路径记 1 个失败", len(res["failed_files"]) == 1
      and "evil.jar" in res["failed_files"][0]["path"], res["failed_files"])
check("overrides 拷贝 2 个", res["overrides"] == 2, res)
check("runtime_vid 为空（未装运行时）", res["runtime_vid"] is None)
check("mods/a.jar 落盘且内容一致",
      os.path.isfile(os.path.join(game_dir, "mods", "a.jar")) and
      open(os.path.join(game_dir, "mods", "a.jar"), "rb").read() == a_bytes)
check("resourcepacks/r.zip 落盘",
      os.path.isfile(os.path.join(game_dir, "resourcepacks", "r.zip")) and
      open(os.path.join(game_dir, "resourcepacks", "r.zip"), "rb").read() == r_bytes)
check("overrides 去前缀落到 config/modmenu.json",
      os.path.isfile(os.path.join(game_dir, "config", "modmenu.json")) and
      json.load(open(os.path.join(game_dir, "config", "modmenu.json"), encoding="utf-8"))["key"] == "value")
check("overrides/options.txt 落到实例根",
      os.path.isfile(os.path.join(game_dir, "options.txt")))
check("穿越文件未写到实例外", not os.path.exists(os.path.join(_TMP, "evil.jar")))
check("安装清单 mclite-modpack.json 写入",
      os.path.isfile(os.path.join(game_dir, "mclite-modpack.json")))
rec = json.load(open(os.path.join(game_dir, "mclite-modpack.json"), encoding="utf-8"))
check("清单记录成功数=2", rec["files"] == 2 and rec["overrides"] == 2, rec)

# 幂等重跑：已存在且校验通过的文件跳过，成功仍为 2，不重复下载
res2 = contenthub.install_mrpack(
    pack_path, game_dir, status=lambda s: None, progress=lambda f: None,
    install_runtime_flag=False)
check("重跑幂等：成功 2 / 跳过 1 / 失败 1",
      res2["success"] == 2 and res2["skipped"] == 1 and len(res2["failed_files"]) == 1, res2)

# 清理
shutil.rmtree(_TMP, ignore_errors=True)

print()
print("=" * 50)
print("CONTENT_HUB TEST: %d passed, %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
