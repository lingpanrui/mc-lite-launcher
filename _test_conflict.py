# -*- coding: utf-8 -*-
"""批次6 冲突预检 + 迁移后端自测（headless，不弹窗、不联网）。

覆盖：
- 版本约束表达式（^ / ~ / >= / maven 区间 / 通配 / 精确）；
- 重复 id（启用冲突 / 禁用副本降级）；
- 缺失前置、依赖版本不满足、加载器不匹配、Java 不足、MC 版本不符；
- 一键禁用修复后复检；
- 迁移目录扫描（模拟 HMCL/PCL2 结构）、copy/reference 导入、源目录零改动快照。
"""
import json
import os
import shutil
import sys
import tempfile
import zipfile

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

from mclite import conflictcheck as cc  # noqa: E402
from mclite import migration as mig  # noqa: E402
from mclite import instances  # noqa: E402

PASS = 0
FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  [PASS]", name)
    else:
        FAIL += 1
        print("  [FAIL]", name, detail)


def make_zip(path, entries):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for arc, data in entries.items():
            zf.writestr(arc, data)


def make_mod_jar(path, mod_id, version="1.0.0", loader="fabric", depends=None,
                 java=None, mc=None):
    entries = {}
    if loader == "fabric":
        fm = {"id": mod_id, "name": mod_id, "version": version}
        deps = {}
        for d in (depends or []):
            deps[d["id"]] = d.get("range") or "*"
        if java:
            deps["java"] = java
        if mc:
            deps["minecraft"] = mc
        if deps:
            fm["depends"] = deps
        entries["fabric.mod.json"] = json.dumps(fm)
    else:
        lines = ['modLoader="javafml"', 'loaderVersion="[47,)"', '[[mods]]',
                 'modId="%s"' % mod_id, 'version="%s"' % version]
        for d in (depends or []):
            lines += ['[[dependencies.%s]]' % d["id"], 'modId="%s"' % d["id"],
                      'mandatory=true', 'versionRange="%s"' % (d.get("range") or ""),
                      'ordering="NONE"', 'side="BOTH"']
        entries["META-INF/mods.toml"] = "\n".join(lines)
    make_zip(path, entries)


def codes(report):
    return {i["code"] for i in report["issues"]}


def main():
    tmp = tempfile.mkdtemp(prefix="mclite_conflict_test_")
    try:
        # ------------------------------------------------ 1. 版本约束
        check("^ 兼容主版本内", cc.satisfies("1.9.0", "^1.2.3") and not cc.satisfies("2.0.0", "^1.2.3"))
        check("~ 兼容次版本内", cc.satisfies("1.2.9", "~1.2.3") and not cc.satisfies("1.3.0", "~1.2.3"))
        check(">= 比较", cc.satisfies("17.0.1", ">=17") and not cc.satisfies("16.0.0", ">=17"))
        check("maven 区间 [a,b)", cc.satisfies("1.5.0", "[1.0,2.0)") and not cc.satisfies("2.0.0", "[1.0,2.0)"))
        check("maven 区间 [a,b]", cc.satisfies("2.0.0", "[1.0,2.0]"))
        check("通配 1.x", cc.satisfies("1.20.1", "1.x") and not cc.satisfies("2.0.0", "1.x"))
        check("精确版本", cc.satisfies("1.2.3", "1.2.3") and not cc.satisfies("1.2.4", "1.2.3"))
        check("空约束视为满足", cc.satisfies("9.9.9", None) and cc.satisfies("9.9.9", ""))
        check("Java 主版本抽取 1.8", cc.java_major_required(">=1.8") == 8)
        check("Java 主版本抽取 21", cc.java_major_required(">=21") == 21)
        check("MC 版本从 id 抽取", cc.mc_version_from_id("1.20.1-Forge") == "1.20.1"
              and cc.mc_version_from_id("26.2-Fabric") == "26.2")

        # ------------------------------------------------ 2. 重复 id
        game = os.path.join(tmp, "inst_dup")
        mods = os.path.join(game, "mods")
        os.makedirs(mods, exist_ok=True)
        make_mod_jar(os.path.join(mods, "a.jar"), "dup", "1.0.0")
        make_mod_jar(os.path.join(mods, "b.jar"), "dup", "2.0.0")
        rep = cc.scan_instance(game, inst_loader="fabric", mc_version="1.20.1", java_major=17)
        check("重复 id 检出 duplicate_id", "duplicate_id" in codes(rep), str(codes(rep)))
        dup = next(i for i in rep["issues"] if i["code"] == "duplicate_id")
        check("重复问题报出两个文件", len(dup["files"]) == 2, str(dup["files"]))
        check("重复问题带 disable 修复", dup["fix"] and dup["fix"]["type"] == "disable"
              and len(dup["fix"]["paths"]) == 1)
        # 一键禁用修复
        cc.apply_fix(game, dup)
        rep2 = cc.scan_instance(game, inst_loader="fabric", mc_version="1.20.1", java_major=17)
        dup_err = [i for i in rep2["issues"] if i["code"] == "duplicate_id" and i["sev"] == "error"]
        check("禁用后复检无重复错误（禁用副本仅 info）", not dup_err, str(codes(rep2)))
        disabled_exists = any(f.endswith(".disabled") for f in os.listdir(mods))
        check("禁用后文件确实变成 .disabled", disabled_exists)

        # 禁用副本降级为 info
        game_d = os.path.join(tmp, "inst_dup_dis")
        mods_d = os.path.join(game_d, "mods")
        os.makedirs(mods_d, exist_ok=True)
        make_mod_jar(os.path.join(mods_d, "a.jar"), "dup2", "1.0.0")
        make_mod_jar(os.path.join(mods_d, "b.jar.disabled"), "dup2", "2.0.0")
        rep_d = cc.scan_instance(game_d, inst_loader="fabric")
        di = [i for i in rep_d["issues"] if i["code"] == "duplicate_id"]
        check("一启用一禁用仅 info 不报错", len(di) == 1 and di[0]["sev"] == "info", str(di))

        # ------------------------------------------------ 3. 缺依赖
        game_m = os.path.join(tmp, "inst_dep")
        mods_m = os.path.join(game_m, "mods")
        os.makedirs(mods_m, exist_ok=True)
        make_mod_jar(os.path.join(mods_m, "main.jar"), "mainmod", "1.0.0",
                     depends=[{"id": "sodium", "range": ">=0.5.0"}])
        rep_m = cc.scan_instance(game_m, inst_loader="fabric", mc_version="1.20.1", java_major=17)
        check("缺失前置检出 missing_dep", "missing_dep" in codes(rep_m), str(codes(rep_m)))
        md = next(i for i in rep_m["issues"] if i["code"] == "missing_dep")
        check("缺依赖报出 mod id", "sodium" in md["mod_ids"])
        check("缺依赖带 install_dep 修复", md["fix"]["type"] == "install_dep"
              and md["fix"]["mod_id"] == "sodium")

        # ------------------------------------------------ 4. 依赖版本不满足
        game_v = os.path.join(tmp, "inst_ver")
        mods_v = os.path.join(game_v, "mods")
        os.makedirs(mods_v, exist_ok=True)
        make_mod_jar(os.path.join(mods_v, "main.jar"), "main2", "1.0.0",
                     depends=[{"id": "libx", "range": "^2.0.0"}])
        make_mod_jar(os.path.join(mods_v, "libx.jar"), "libx", "1.5.0")
        rep_v = cc.scan_instance(game_v, inst_loader="fabric", mc_version="1.20.1", java_major=17)
        check("版本区间不满足检出 dep_version", "dep_version" in codes(rep_v), str(codes(rep_v)))

        # 满足时不误报
        game_ok = os.path.join(tmp, "inst_ok")
        mods_ok = os.path.join(game_ok, "mods")
        os.makedirs(mods_ok, exist_ok=True)
        make_mod_jar(os.path.join(mods_ok, "main.jar"), "main3", "1.0.0",
                     depends=[{"id": "libx", "range": "^2.0.0"}])
        make_mod_jar(os.path.join(mods_ok, "libx.jar"), "libx", "2.3.1")
        rep_ok = cc.scan_instance(game_ok, inst_loader="fabric", mc_version="1.20.1", java_major=17)
        check("依赖满足时无 dep/missing",
              "dep_version" not in codes(rep_ok) and "missing_dep" not in codes(rep_ok),
              str(codes(rep_ok)))

        # ------------------------------------------------ 5. 加载器不匹配
        game_l = os.path.join(tmp, "inst_loader")
        mods_l = os.path.join(game_l, "mods")
        os.makedirs(mods_l, exist_ok=True)
        make_mod_jar(os.path.join(mods_l, "fabricmod.jar"), "fmod", "1.0.0", loader="fabric")
        rep_l = cc.scan_instance(game_l, inst_loader="forge", mc_version="1.20.1", java_major=17)
        check("fabric 进 forge 检出 loader_mismatch", "loader_mismatch" in codes(rep_l), str(codes(rep_l)))
        rep_l2 = cc.scan_instance(game_l, inst_loader="fabric", mc_version="1.20.1", java_major=17)
        check("fabric 进 fabric 不误报", "loader_mismatch" not in codes(rep_l2))

        # forge 进 neoforge 也算不匹配
        game_n = os.path.join(tmp, "inst_neo")
        mods_n = os.path.join(game_n, "mods")
        os.makedirs(mods_n, exist_ok=True)
        make_mod_jar(os.path.join(mods_n, "forgemod.jar"), "fmod2", "1.0.0", loader="forge")
        rep_n = cc.scan_instance(game_n, inst_loader="neoforge", mc_version="1.20.1", java_major=17)
        check("forge 进 neoforge 检出 loader_mismatch", "loader_mismatch" in codes(rep_n))

        # ------------------------------------------------ 6. Java 不足
        game_j = os.path.join(tmp, "inst_java")
        mods_j = os.path.join(game_j, "mods")
        os.makedirs(mods_j, exist_ok=True)
        make_mod_jar(os.path.join(mods_j, "jmod.jar"), "jmod", "1.0.0", java=">=21")
        rep_j = cc.scan_instance(game_j, inst_loader="fabric", mc_version="1.20.1", java_major=17)
        check("Java 不足检出 java_version", "java_version" in codes(rep_j), str(codes(rep_j)))
        rep_j2 = cc.scan_instance(game_j, inst_loader="fabric", mc_version="1.20.1", java_major=21)
        check("Java 满足不误报", "java_version" not in codes(rep_j2))

        # ------------------------------------------------ 7. MC 版本不符
        game_mc = os.path.join(tmp, "inst_mc")
        mods_mc = os.path.join(game_mc, "mods")
        os.makedirs(mods_mc, exist_ok=True)
        make_mod_jar(os.path.join(mods_mc, "mcmod.jar"), "mcmod", "1.0.0", mc=">=1.21")
        rep_mc = cc.scan_instance(game_mc, inst_loader="fabric", mc_version="1.20.1", java_major=17)
        check("MC 版本不符检出 mc_version", "mc_version" in codes(rep_mc), str(codes(rep_mc)))

        # ------------------------------------------------ 8. 迁移扫描（模拟目录）
        fake = os.path.join(tmp, "fake_minecraft")
        vdir = os.path.join(fake, "versions", "1.20.1-Forge")
        os.makedirs(vdir, exist_ok=True)
        with open(os.path.join(vdir, "1.20.1-Forge.json"), "w", encoding="utf-8") as f:
            json.dump({"id": "1.20.1-Forge", "mainClass": "cpw.mods.bootstraplauncher.BootstrapLauncher"}, f)
        with open(os.path.join(vdir, "1.20.1-Forge.jar"), "wb") as f:
            f.write(b"PK\x03\x04fake")
        os.makedirs(os.path.join(fake, "mods"), exist_ok=True)
        make_mod_jar(os.path.join(fake, "mods", "fabric-api.jar"), "fabric-api", "0.161.0")
        wdir = os.path.join(fake, "saves", "WorldA")
        os.makedirs(wdir, exist_ok=True)
        with open(os.path.join(wdir, "level.dat"), "wb") as f:
            f.write(b"fake-nbt")
        os.makedirs(os.path.join(fake, "libraries", "x"), exist_ok=True)
        with open(os.path.join(fake, "libraries", "x", "a.jar"), "wb") as f:
            f.write(b"lib")
        os.makedirs(os.path.join(fake, "assets", "indexes"), exist_ok=True)
        with open(os.path.join(fake, "assets", "indexes", "1.20.json"), "w") as f:
            f.write("{}")

        cands = mig.enumerate_versions(fake, "pcl2", "PCL2")
        check("扫描到 1 个可导入版本", len(cands) == 1, str(len(cands)))
        c = cands[0]
        check("识别 MC 版本 1.20.1", c["mc_version"] == "1.20.1", c["mc_version"])
        check("识别加载器 forge", c["loader"] == "forge", c["loader"])
        check("统计 mods=1", c["mods_count"] == 1, str(c["mods_count"]))
        check("统计 saves=1", c["saves_count"] == 1, str(c["saves_count"]))

        # 五家启动器都如实列出（未安装也返回 installed=False，绝不造假）
        launchers = mig.detect_launchers()
        check("返回 HMCL/PCL2/BHL/Prism/FCL 五家",
              {l["key"] for l in launchers} == {"hmcl", "pcl2", "bhl", "prism", "fcl"})
        check("每家都有 installed 布尔与 note", all("installed" in l and l["note"] for l in launchers))

        # ------------------------------------------------ 9. copy 导入 + 源零改动
        before = mig.snapshot(fake)
        cfg = {"instance_root": os.path.join(tmp, "instroot"), "instances": [], "current_instance": "default"}
        instances._save = lambda c: None  # 测试不落真实 config.json
        res = mig.import_candidate(cfg, c, mode="copy", new_name="迁移测试Forge",
                                   copy_big_shared=False, status=lambda s: None)
        check("copy 导入返回实例", res["inst"] and res["inst"]["game_dir"])
        dst = res["inst"]["game_dir"]
        check("新实例含版本目录", os.path.isfile(os.path.join(dst, "versions", "1.20.1-Forge", "1.20.1-Forge.json")))
        check("新实例 mods 已复制", os.path.isfile(os.path.join(dst, "mods", "fabric-api.jar")))
        check("新实例 saves 已复制", os.path.isfile(os.path.join(dst, "saves", "WorldA", "level.dat")))
        check("libraries 以 junction 或复制复用",
              os.path.exists(os.path.join(dst, "libraries")) and
              (res["junctions"] or "libraries" in res["copied"]))
        saved_inst = instances.get_instance(cfg, res["inst"]["id"])
        check("实例记录 last_version", saved_inst and saved_inst.get("last_version") == "1.20.1-Forge",
              str(saved_inst and saved_inst.get("last_version")))
        after = mig.snapshot(fake)
        diff = mig.diff_snapshot(before, after)
        check("源目录导入前后零改动", diff["unchanged"], str(diff["diffs"]))

        # ------------------------------------------------ 10. reference 导入
        res_ref = mig.import_candidate(cfg, c, mode="reference", new_name="引用测试",
                                       status=lambda s: None)
        check("reference 模式 game_dir 指向源目录",
              os.path.normcase(res_ref["inst"]["game_dir"]) == os.path.normcase(fake))
        check("reference 模式不产生复制统计", res_ref["stats"]["files"] == 0
              and not res_ref["copied"])

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("=" * 50)
    print("CONFLICT TEST: %d passed, %d failed" % (PASS, FAIL))
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
