# -*- coding: utf-8 -*-
"""核心功能自检：不打开界面，检查接口、Java 与安装流程

用法：
    python selftest.py                 # 只做接口连通性检查
    python selftest.py --install 1.21.4  # 顺带真实安装一个版本（会下载数百 MB）
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mclite import bedrock, java as javamod, modrinth, mojang, util


def line(title):
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)


def check_manifest():
    line("1. Mojang 版本清单")
    t = time.time()
    m = mojang.get_manifest()
    latest = m["latest"]["release"]
    print("版本数量：%d，最新正式版：%s，耗时 %.1fs" % (len(m["versions"]), latest, time.time() - t))
    return m, latest


def check_fabric(latest):
    line("2. Fabric 加载器")
    loaders = util.http_json("%s/versions/loader/%s" % (mojang.FABRIC_META, latest))
    print("可用加载器 %d 个，最新：%s" % (len(loaders), loaders[0]["loader"]["version"]))
    profile = util.http_json("%s/versions/loader/%s/%s/profile/json"
                             % (mojang.FABRIC_META, latest, loaders[0]["loader"]["version"]))
    print("Fabric profile：%s（libraries %d 个）" % (profile["id"], len(profile.get("libraries", []))))
    return profile["id"]


def check_modrinth():
    line("3. Modrinth 内容接口")
    hits, total = modrinth.search("sodium", "mod", "fabric", None, limit=5)
    print("搜索 sodium：%d 个结果，首个：%s（%s）" % (total, hits[0]["title"], hits[0]["slug"]))
    vs = modrinth.get_versions(hits[0]["project_id"], None, "fabric")
    print("Sodium 可用文件版本 %d 个，首个：%s / %s"
          % (len(vs), vs[0]["version_number"], vs[0]["files"][0]["filename"]))
    sh, stotal = modrinth.search("", "shader", None, None, limit=5)
    print("光影项目总数：%s，首个：%s" % (stotal, sh[0]["title"] if sh else "-"))


def check_bedrock():
    line("4. 基岩版")
    clients = bedrock.installed_clients()
    print("本机基岩版客户端：%s" % (clients or "未安装（安装后可由启动器拉起）"))
    try:
        items = bedrock.available_versions()
        for it in items:
            print("服务端 %s（%s）%s" % (it["version"], it["kind"], it["url"]))
    except Exception as e:
        print("服务端版本列表获取失败：%s" % e)


def check_java():
    line("5. Java 运行时")
    javas = javamod.find_javas()
    for j in javas:
        print("Java %-3s %s" % (j["major"], j["path"]))
    if not javas:
        print("未检测到 Java（启动时会自动下载）")


def do_install(version):
    line("6. 真实安装 %s" % version)
    game_dir = os.path.join(util.app_root(), "game")
    m = mojang.get_manifest()
    inst = mojang.Installer(
        game_dir, mojang.manifest_map(m),
        status=lambda s: print("  [状态] %s" % s, flush=True),
        progress=lambda f: None,
    )
    t = time.time()
    vid, jpath = inst.install(version)
    print("安装完成：%s（%.1fs）" % (vid, time.time() - t))
    cmd, vj, root, missing = mojang.build_command(game_dir, vid, "java", "Steve", 4096)
    print("启动命令片段：%s ... 参数共 %d 个，缺失依赖 %d 个"
          % (" ".join(os.path.basename(x) if os.sep in x else x for x in cmd[:4]), len(cmd), missing))


def main():
    manifest, latest = check_manifest()
    check_fabric(latest)
    check_modrinth()
    check_bedrock()
    check_java()
    if "--install" in sys.argv:
        do_install(sys.argv[sys.argv.index("--install") + 1])
    print("\n自检结束")


if __name__ == "__main__":
    main()
