# -*- coding: utf-8 -*-
"""批次1 实例系统纯后端自测（headless，不弹窗）

覆盖：创建 / 改名 / 复制 / 删除 / 导出导入 / 默认实例映射 / 配置往返持久化 /
存档备份恢复 / 删除安全闸门。

运行：
    python _test_instances.py
所有数据写在临时 APPDATA，不碰真实 %APPDATA%\\MCLite。
"""
import json
import os
import shutil
import sys
import tempfile
import zipfile

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

# 必须在 import mclite.util 之前设置，CONFIG_PATH 在导入时按 APPDATA 计算
TMP = tempfile.mkdtemp(prefix="mclite-inst-test-")
os.environ["APPDATA"] = TMP

from mclite import util, instances  # noqa: E402

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


def section(title):
    print("\n== %s ==" % title)


# ---------------------------------------------------------------- 1. 默认映射
section("1. 老 game_dir 映射为 default 实例（不搬目录）")
legacy = os.path.join(TMP, "MCLite", "game")
vdir = os.path.join(legacy, "versions", "1.20.1")
os.makedirs(vdir, exist_ok=True)
with open(os.path.join(vdir, "1.20.1.json"), "w", encoding="utf-8") as f:
    json.dump({"id": "1.20.1", "type": "release"}, f)

cfg = util.load_config()
instances.migrate(cfg)
cur = instances.current(cfg)
check("当前实例为 default", cur["id"] == "default", cur.get("id"))
check("default.game_dir 指向老目录", os.path.normcase(cur["game_dir"]) == os.path.normcase(legacy),
      cur.get("game_dir"))
check("default 版本数=1", instances.version_count(cur["game_dir"]) == 1)
check("顶层 cfg.game_dir 已镜像", os.path.normcase(cfg["game_dir"]) == os.path.normcase(legacy))
check("老版本 json 原样存在", os.path.isfile(os.path.join(vdir, "1.20.1.json")))

# ---------------------------------------------------------------- 2. 新建
section("2. 新建实例（自动建独立目录并切换）")
a = instances.create(cfg, "测试实例A", memory_mb=2048, width=900, height=600,
                     jvm_args="-Dfoo=bar")
check("新实例 id 前缀", a["id"].startswith("inst_"), a["id"])
check("目录已创建", os.path.isdir(a["game_dir"]), a["game_dir"])
check("已切换为当前", cfg["current_instance"] == a["id"])
check("顶层 game_dir 跟随", os.path.normcase(cfg["game_dir"]) == os.path.normcase(a["game_dir"]))
check("内存字段", a["memory_mb"] == 2048)
check("JVM 参数", a["jvm_args"] == "-Dfoo=bar")

# ---------------------------------------------------------------- 3. 改名
section("3. 重命名")
instances.rename(cfg, a["id"], "改名后的实例")
a2 = instances.get_instance(cfg, a["id"])
check("名称已更新", a2["name"] == "改名后的实例", a2["name"])
try:
    instances.rename(cfg, a["id"], "   ")
    check("空名称被拒绝", False)
except ValueError:
    check("空名称被拒绝", True)

# ---------------------------------------------------------------- 4. 更新持久化
section("4. 属性更新 + 落盘往返")
instances.update(cfg, a["id"], memory_mb=3072, width=1024, height=768,
                  java_path=r"C:\fake\java.exe", jvm_args="-Xmx3G -Dtest=1")
cfg2 = util.load_config()
a3 = instances.get_instance(cfg2, a["id"])
check("重载后内存=3072", a3 and a3["memory_mb"] == 3072, str(a3 and a3.get("memory_mb")))
check("重载后宽=1024", a3 and a3["width"] == 1024)
check("重载后 java_path", a3 and a3["java_path"] == r"C:\fake\java.exe")
check("当前实例镜像到顶层 cfg", cfg2["memory_mb"] == 3072 and cfg2["width"] == 1024)
try:
    instances.update(cfg, a["id"], memory_mb="abc")
    check("非法内存被拒绝", False)
except ValueError:
    check("非法内存被拒绝", True)

# ---------------------------------------------------------------- 5. 复制
section("5. 复制实例（配置独立、目录独立）")
b = instances.duplicate(cfg, a["id"])
check("复制得到新 id", b["id"] != a["id"])
check("复制得到新目录", os.path.normcase(b["game_dir"]) != os.path.normcase(a["game_dir"]))
check("新目录已创建", os.path.isdir(b["game_dir"]))
check("复制内存一致", b["memory_mb"] == 3072)
check("复制 JVM 参数一致", b["jvm_args"] == "-Xmx3G -Dtest=1")
check("名称带副本", "副本" in b["name"], b["name"])
check("原实例仍在", instances.get_instance(cfg, a["id"]) is not None)

# ---------------------------------------------------------------- 6. 导出 / 导入
section("6. 导出 JSON 再导入为新实例")
exp_path = os.path.join(TMP, "exported-instance.json")
instances.export_instance(cfg, a["id"], exp_path)
check("导出文件存在", os.path.isfile(exp_path))
with open(exp_path, "r", encoding="utf-8") as f:
    payload = json.load(f)
check("导出格式标记", payload.get("format") == "mclite-instance")
check("导出含实例字段", payload["instance"]["memory_mb"] == 3072)

imp, missing = instances.import_instance(cfg, exp_path)
check("导入生成新 id", imp["id"] not in (a["id"], b["id"]))
check("导入目录已创建", os.path.isdir(imp["game_dir"]))
check("导入保留内存", imp["memory_mb"] == 3072)
check("导入保留 JVM", imp["jvm_args"] == "-Xmx3G -Dtest=1")
check("导入实例版本缺失提示为 None（无 last_version）", missing is None)

# 带 last_version 的导入 → 明确提示缺失
instances.update(cfg, a["id"], last_version="1.20.1")
exp2 = os.path.join(TMP, "exported-with-ver.json")
instances.export_instance(cfg, a["id"], exp2)
imp2, missing2 = instances.import_instance(cfg, exp2)
check("导入带版本记录时提示缺失", missing2 == "1.20.1", str(missing2))

bad = os.path.join(TMP, "bad.json")
with open(bad, "w", encoding="utf-8") as f:
    json.dump({"hello": "world"}, f)
try:
    instances.import_instance(cfg, bad)
    check("非法导出文件被拒绝", False)
except ValueError:
    check("非法导出文件被拒绝", True)

# ---------------------------------------------------------------- 7. 备份 / 恢复
section("7. saves 备份 zip 与恢复（含恢复前自动备份）")
gdir = b["game_dir"]
saves = os.path.join(gdir, "saves", "world1")
os.makedirs(saves, exist_ok=True)
with open(os.path.join(saves, "level.dat"), "w", encoding="utf-8") as f:
    f.write("LEVEL-V1")
with open(os.path.join(gdir, "options.txt"), "w", encoding="utf-8") as f:
    f.write("renderDistance:12")

zp, n = instances.backup_saves(gdir, include_options=True)
check("备份 zip 存在", os.path.isfile(zp), zp)
check("备份文件数>=2", n >= 2, str(n))
with zipfile.ZipFile(zp) as zf:
    names = zf.namelist()
check("zip 内含 saves/ 前缀", any(x.startswith("saves/") for x in names), str(names[:5]))
check("zip 内含 options.txt", "options.txt" in names)

# 篡改存档后恢复
with open(os.path.join(saves, "level.dat"), "w", encoding="utf-8") as f:
    f.write("LEVEL-V2-TAMPERED")
res = instances.restore_saves(gdir, zp)
with open(os.path.join(saves, "level.dat"), "r", encoding="utf-8") as f:
    restored = f.read()
check("恢复后内容回到 V1", restored == "LEVEL-V1", restored)
check("恢复前自动备份已生成", bool(res["pre_backup"]) and os.path.isfile(res["pre_backup"]),
      str(res.get("pre_backup")))
check("恢复解压文件数>0", res["extracted"] > 0, str(res["extracted"]))
backups = instances.list_backups(gdir)
check("备份列表按时间倒序", len(backups) >= 2)

# ---------------------------------------------------------------- 8. 删除安全
section("8. 删除实例（只删自己目录 + 默认实例保护 + 越界拦截）")
# 切到 imp2 再删，验证删除当前实例后回退 default
instances.switch(cfg, imp2["id"])
check("切换到 imp2", cfg["current_instance"] == imp2["id"])
removed_dir = instances.delete(cfg, imp2["id"])
check("删除返回目录", os.path.normcase(removed_dir) == os.path.normcase(imp2["game_dir"]))
check("实例目录已删除", not os.path.exists(imp2["game_dir"]))
check("删除后当前回退 default", cfg["current_instance"] == "default", cfg["current_instance"])
check("顶层 game_dir 回到老目录", os.path.normcase(cfg["game_dir"]) == os.path.normcase(legacy))

try:
    instances.delete(cfg, "default")
    check("默认实例禁止删除", False)
except ValueError:
    check("默认实例禁止删除", True)

# 越界目录（显式指定到实例根之外）拒绝删除
outside = os.path.join(TMP, "outside-instance-dir")
os.makedirs(outside, exist_ok=True)
c = instances.create(cfg, "越界实例", game_dir=outside, switch=False)
try:
    instances.delete(cfg, c["id"])
    check("实例根之外目录拒绝删除", False)
except ValueError:
    check("实例根之外目录拒绝删除", True)
check("越界目录仍然存在", os.path.isdir(outside))
# 清理这条测试记录（目录保留，手动删）
cfg["instances"] = [x for x in cfg["instances"] if x["id"] != c["id"]]
util.save_config(cfg)
shutil.rmtree(outside, ignore_errors=True)

# ---------------------------------------------------------------- 9. 配置往返
section("9. config.json 往返持久化")
util.save_config(cfg)
cfg3 = util.load_config()
check("instances 列表持久化", isinstance(cfg3.get("instances"), list) and len(cfg3["instances"]) >= 2)
check("current_instance 持久化", cfg3.get("current_instance") == "default")
check("instance_root 持久化", bool(cfg3.get("instance_root")))

# ---------------------------------------------------------------- 10. 老目录无损
section("10. 兼容底线：老游戏目录 5 版本场景不受影响")
check("老 default 目录仍在", os.path.isdir(legacy))
check("老版本 json 仍在", os.path.isfile(os.path.join(vdir, "1.20.1.json")))
check("default 实例仍在列表", instances.get_instance(cfg3, "default") is not None)

print("\n========================================")
print("RESULT: %d passed, %d failed" % (PASS, FAIL))
shutil.rmtree(TMP, ignore_errors=True)
sys.exit(1 if FAIL else 0)
