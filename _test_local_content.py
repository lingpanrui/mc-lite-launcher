# -*- coding: utf-8 -*-
"""批次4 本地内容管理后端自测（headless，不弹窗）。

覆盖：
- 启用/禁用后缀切换幂等、多点文件名、同名冲突；
- 删除安全（只删单文件、拒目录、路径越界归一化）；
- 归档分类识别（jar/资源包/数据包/光影/未知）；
- .jar 模组元数据识别与加载器不匹配提示；
- 导入复制 + 来源清单 + 重名避让 + 跳过；
- 扫描（启用/禁用/来源）；
- 存档 NBT 世界名读取；
- Windows DROPFILES 构造/解码往返。
"""
import gzip
import json
import os
import shutil
import struct
import sys
import tempfile
import zipfile

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

from mclite import localcontent as lc  # noqa: E402

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
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for arc, data in entries.items():
            zf.writestr(arc, data)


def nbt_string(s):
    b = s.encode("utf-8")
    return struct.pack(">H", len(b)) + b


def build_level_dat(world_name):
    """构造最小 gzip NBT：Compound(root) -> Compound(Data) -> String(Name)。"""
    out = b""
    out += bytes([10]) + nbt_string("")          # 根 compound + 根名
    out += bytes([10]) + nbt_string("Data")      # Data compound
    out += bytes([8]) + nbt_string("Name") + nbt_string(world_name)
    out += bytes([0])                            # Data end
    out += bytes([0])                            # root end
    return gzip.compress(out)


def main():
    tmp = tempfile.mkdtemp(prefix="mclite_local_test_")
    try:
        game = os.path.join(tmp, "inst")
        os.makedirs(game, exist_ok=True)

        # ------------------------------------------------ 1. 启停切换
        mods = lc.category_dir(game, "mod")
        os.makedirs(mods, exist_ok=True)
        a = os.path.join(mods, "foo.bar.baz.jar")
        with open(a, "wb") as f:
            f.write(b"PK\x03\x04fake")
        target, enabling = lc.toggle_enabled(a)
        check("禁用后生成 .disabled", os.path.isfile(target) and target.endswith("foo.bar.baz.jar.disabled"))
        check("禁用后原文件消失", not os.path.exists(a))
        check("禁用返回 enabling=False", enabling is False)
        target2, enabling2 = lc.toggle_enabled(target)
        check("启用还原多点文件名", os.path.isfile(target2) and os.path.basename(target2) == "foo.bar.baz.jar")
        check("启用返回 enabling=True", enabling2 is True)

        # 幂等
        p_dis, _ = lc.disable_path(a)
        p_dis2, _ = lc.disable_path(p_dis)
        check("重复禁用幂等", p_dis == p_dis2 and os.path.basename(p_dis).endswith(".disabled"))
        p_en, _ = lc.enable_path(p_dis)
        p_en2, _ = lc.enable_path(p_en)
        check("重复启用幂等", p_en == p_en2 and os.path.basename(p_en) == "foo.bar.baz.jar")

        # 同名冲突：启用时目标已存在
        dis = a + ".disabled"
        shutil.copy2(a, dis)
        try:
            lc.enable_path(dis)
            check("启用遇同名冲突抛错", False)
        except lc.ConflictError:
            check("启用遇同名冲突抛 ConflictError", True)
        # 禁用时目标已存在
        try:
            lc.disable_path(a)
            check("禁用遇同名冲突抛错", False)
        except lc.ConflictError:
            check("禁用遇同名冲突抛 ConflictError", True)
        os.remove(dis)

        # ------------------------------------------------ 2. 删除安全
        other = os.path.join(mods, "other.jar")
        with open(other, "wb") as f:
            f.write(b"other")
        removed = lc.delete_content_file(game, "mod", "foo.bar.baz.jar")
        check("删除只删选中文件", not os.path.exists(removed) and os.path.exists(other))
        try:
            lc.delete_content_file(game, "mod", ".")
            check("删除目录被拒", False)
        except lc.LocalContentError:
            check("删除目录被拒", True)
        # 路径越界名被归一化到目录内，不会跑到上级
        resolved = lc._resolve_in_dir(mods, "../evil.jar")
        check("越界名归一化到目录内", resolved.startswith(os.path.abspath(mods) + os.sep)
              and os.path.basename(resolved) == "evil.jar")
        try:
            lc.delete_content_file(game, "saves", "any")
            check("存档整目录删除被拒", False)
        except lc.LocalContentError:
            check("存档整目录删除被拒", True)

        # ------------------------------------------------ 3. 分类识别
        rp = os.path.join(tmp, "rp.zip")
        make_zip(rp, {"pack.mcmeta": '{"pack":{"pack_format":1}}', "assets/x.png": b"x"})
        check("资源包识别", lc.classify_archive(rp) == "resourcepack")
        dp = os.path.join(tmp, "dp.zip")
        make_zip(dp, {"pack.mcmeta": '{"pack":{"pack_format":1}}', "data/x.json": b"{}"})
        check("数据包识别", lc.classify_archive(dp) == "datapack")
        sh = os.path.join(tmp, "sh.zip")
        make_zip(sh, {"shaders.properties": "x=1", "shaders/a.vsh": b"x"})
        check("光影识别", lc.classify_archive(sh) == "shader")
        mj = os.path.join(tmp, "m.jar")
        make_zip(mj, {"fabric.mod.json": '{"id":"x"}'})
        check("jar 识别为模组", lc.classify_archive(mj) == "mod")
        txt = os.path.join(tmp, "a.txt")
        with open(txt, "wb") as f:
            f.write(b"x")
        check("未知类型返回 None", lc.classify_archive(txt) is None)

        # ------------------------------------------------ 4. 模组元数据 + 加载器提示
        probe = os.path.join(BASE, "_probe", "probe_mod.jar")
        if os.path.isfile(probe):
            info = lc.detect_mod_info(probe)
            check("probe_mod.jar 识别为 fabric", "fabric" in info["loaders"], str(info)[:120])
            check("probe_mod.jar 读到 mod id", bool(info["ids"]), str(info["ids"]))
        else:
            check("probe_mod.jar 存在（跳过）", True)
        info_fabric = {"loaders": ["fabric"], "ids": ["x"], "name": "X", "version": "1"}
        check("fabric 模组 vs forge 实例告警", lc.loader_warning(info_fabric, "forge") is not None)
        check("fabric 模组 vs fabric 实例不告警", lc.loader_warning(info_fabric, "fabric") is None)
        check("未知实例加载器不告警", lc.loader_warning(info_fabric, "") is None)

        # ------------------------------------------------ 5. 导入 + 清单 + 重名
        src_mod = os.path.join(tmp, "imported.jar")
        make_zip(src_mod, {"fabric.mod.json": '{"id":"importedmod","name":"Imported","version":"1.0"}'})
        res = lc.import_files(game, "mod", [src_mod])
        check("导入模组成功", len(res) == 1 and not res[0]["skipped"] and os.path.isfile(res[0]["dest"]))
        check("导入写来源清单", lc.source_of(game, "imported.jar") == "本地导入")
        # 再次导入同大小 -> 跳过
        res2 = lc.import_files(game, "mod", [src_mod])
        check("重复导入同大小跳过", res2[0]["skipped"] is True)
        # 不同内容同名 -> 避让改名
        src_mod2 = os.path.join(tmp, "imported2.jar")
        make_zip(src_mod2, {"fabric.mod.json": '{"id":"importedmod2"}', "extra.bin": b"different-bytes"})
        res3 = lc.import_files(game, "mod", [src_mod2])
        check("重名不同内容自动避让", os.path.basename(res3[0]["dest"]) != "imported.jar"
              and os.path.isfile(res3[0]["dest"]))
        # 资源包导入到 resourcepacks
        res_rp = lc.import_files(game, "resourcepack", [rp])
        check("资源包导入到 resourcepacks", res_rp[0]["category"] == "resourcepack"
              and os.path.isfile(os.path.join(game, "resourcepacks", "rp.zip")))

        # ------------------------------------------------ 6. 扫描（启用/禁用/来源）
        items = lc.scan_category(game, "mod")
        names = {i["name"]: i for i in items}
        check("扫描到导入模组", "imported.jar" in names)
        check("扫描项含大小/时间/来源", all(i["size"] > 0 and i["source"] for i in items))
        # 禁用后扫描为 disabled
        lc.disable_path(os.path.join(mods, "imported.jar"))
        items2 = lc.scan_category(game, "mod")
        dis_item = next((i for i in items2 if i["name"] == "imported.jar.disabled"), None)
        check("禁用后扫描到 .disabled 且 enabled=False", dis_item is not None and dis_item["enabled"] is False)
        check("禁用态仍能查到来源", dis_item is not None and dis_item["source"] == "本地导入")
        lc.enable_path(os.path.join(mods, "imported.jar.disabled"))

        # ------------------------------------------------ 7. 存档 NBT
        saves = lc.category_dir(game, "saves")
        world = os.path.join(saves, "MyWorld")
        os.makedirs(world, exist_ok=True)
        with open(os.path.join(world, "level.dat"), "wb") as f:
            f.write(build_level_dat("测试世界"))
        saves_items = lc.scan_saves(game)
        check("存档扫描列出世界", any(w["world_name"] == "测试世界" for w in saves_items),
              str([w["world_name"] for w in saves_items]))
        check("存档大小/时间字段", all(w["size"] >= 0 and w["mtime"] > 0 for w in saves_items))

        # ------------------------------------------------ 8. 拖放 DROPFILES 往返
        hdrop = lc.build_dropfiles([src_mod, rp])
        paths = lc.decode_dropfiles(hdrop)
        check("DROPFILES 构造/解码往返", paths == [os.path.abspath(src_mod), os.path.abspath(rp)], str(paths))

        # ------------------------------------------------ 9. 实例加载器读取
        vdir = os.path.join(game, "versions", "1.20.1")
        os.makedirs(vdir, exist_ok=True)
        with open(os.path.join(vdir, "1.20.1.json"), "w", encoding="utf-8") as f:
            json.dump({"id": "1.20.1-fabric", "mainClass": "net.fabricmc.loader.impl.launch.knot.KnotClient"}, f)
        check("instance_loader 识别 fabric", lc.instance_loader(game, "1.20.1") == "fabric")
        check("空版本返回空加载器", lc.instance_loader(game, "") == "")

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("=" * 50)
    print("LOCAL_CONTENT TEST: %d passed, %d failed" % (PASS, FAIL))
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
