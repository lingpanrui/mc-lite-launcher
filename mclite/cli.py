# -*- coding: utf-8 -*-
"""命令行入口（批次5）

支持：
  MCLite-v2.exe --list-instances
  MCLite-v2.exe --launch <实例名或id> [--java <路径>] [--memory <MB>]
                [--width <px>] [--height <px>] [--jvm-args "<args>"] [--version <vid>]
  MCLite-v2.exe --help

PyInstaller --windowed 下没有控制台，所有结果同时写入
%APPDATA%\\MCLite\\logs\\cli.log；参数错误返回非零退出码（2）。
"""
import datetime
import os
import sys

from . import util, instances, accounts, mojang, java as jm

LOG_DIR = os.path.join(util.app_root(), "logs")
LOG_PATH = os.path.join(LOG_DIR, "cli.log")

USAGE = """MC Lite CLI
  --list-instances
  --launch <实例名或id> [--java <javaw.exe>] [--memory <MB>] [--width <px>] [--height <px>]
                        [--jvm-args "<args>"] [--version <版本id>]
  --help
"""


class CliError(Exception):
    def __init__(self, msg, code=2):
        super().__init__(msg)
        self.code = code


def log(msg):
    line = "[%s] %s" % (datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg)
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
    try:
        print(line)
    except Exception:
        pass


# ---------------------------------------------------------------- 参数解析
def parse_args(argv):
    """返回 dict；未知参数/缺值抛 CliError。"""
    opts = {"command": None, "instance": None, "java": "", "memory": None,
            "width": None, "height": None, "jvm_args": "", "version": ""}
    args = list(argv or [])
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("--help", "-h"):
            opts["command"] = "help"
            i += 1
            continue
        if a == "--list-instances":
            opts["command"] = "list"
            i += 1
            continue
        if a == "--launch":
            opts["command"] = "launch"
            if i + 1 >= len(args) or args[i + 1].startswith("--"):
                raise CliError("--launch 后需要实例名或 id")
            opts["instance"] = args[i + 1]
            i += 2
            continue
        if a in ("--java", "--memory", "--width", "--height", "--jvm-args", "--version"):
            if i + 1 >= len(args):
                raise CliError("参数 %s 缺少值" % a)
            val = args[i + 1]
            key = {"--java": "java", "--memory": "memory", "--width": "width",
                   "--height": "height", "--jvm-args": "jvm_args", "--version": "version"}[a]
            opts[key] = val
            i += 2
            continue
        if a.startswith("--"):
            raise CliError("未知参数：%s" % a)
        # 兼容裸实例名（等价 --launch）
        if opts["command"] is None:
            opts["command"] = "launch"
            opts["instance"] = a
            i += 1
            continue
        raise CliError("无法识别的参数：%s" % a)

    if opts["command"] == "launch" and not opts["instance"]:
        raise CliError("--launch 需要实例名或 id")
    for k in ("memory", "width", "height"):
        if opts[k] not in (None, ""):
            try:
                opts[k] = int(opts[k])
            except (TypeError, ValueError):
                raise CliError("%s 必须是整数，收到：%r" % (k, opts[k]))
    return opts


# ---------------------------------------------------------------- 命令
def cmd_list_instances(cfg):
    insts = instances.list_instances(cfg)
    lines = ["共 %d 个实例：" % len(insts)]
    for it in insts:
        n = instances.version_count(it["game_dir"])
        lines.append("  - id=%s 名称=%s 版本数=%d 最后版本=%s 加载器=%s 目录=%s" % (
            it.get("id"), it.get("name"), n, it.get("last_version") or "-",
            it.get("loader_hint") or "-", it.get("game_dir")))
    out = "\n".join(lines)
    log(out)
    return out


def _pick_version(game_dir, preferred=""):
    """选一个可启动版本：优先指定，其次实例 last_version，再次 1.20.1，最后排序首个。"""
    vdir = os.path.join(game_dir, "versions")
    installed = []
    try:
        for name in os.listdir(vdir):
            if os.path.isfile(os.path.join(vdir, name, name + ".json")):
                installed.append(name)
    except OSError:
        installed = []
    if not installed:
        return None
    for cand in (preferred, "1.20.1"):
        if cand and cand in installed:
            return cand
    return sorted(installed)[0]


def cmd_launch(cfg, opts):
    inst = instances.get_instance(cfg, opts["instance"])
    if inst is None:
        # 按名称忽略大小写匹配
        for it in instances.list_instances(cfg):
            if str(it.get("name", "")).lower() == str(opts["instance"]).lower():
                inst = it
                break
    if inst is None:
        raise CliError("找不到实例：%s（用 --list-instances 查看）" % opts["instance"])

    game_dir = inst["game_dir"]
    vid = opts["version"] or inst.get("last_version") or cfg.get("last_version") or ""
    if not vid or not os.path.isfile(os.path.join(game_dir, "versions", vid, vid + ".json")):
        vid = _pick_version(game_dir, vid)
    if not vid:
        raise CliError("实例 %s 没有已安装版本，无法启动" % inst.get("name"))

    # Java：CLI 显式 > 实例 > 全局 > 自动探测
    exe = opts["java"] or inst.get("java_path") or cfg.get("java_path") or ""
    if not exe or not os.path.isfile(exe):
        try:
            vj, _root = mojang.resolve_version(game_dir, vid)
            major = mojang.guess_java_major(vj)
        except Exception:
            major = 17
        javas = jm.find_javas() or []
        exe = jm.pick_java(major, all_javas=javas) or (javas[0]["path"] if javas else "")
    if not exe or not os.path.isfile(exe):
        raise CliError("找不到可用 Java，请用 --java 指定 javaw.exe 路径")

    memory = opts["memory"] or int(inst.get("memory_mb") or cfg.get("memory_mb") or 4096)
    width = opts["width"] or int(inst.get("width") or cfg.get("width") or 854)
    height = opts["height"] or int(inst.get("height") or cfg.get("height") or 480)
    jvm = []
    if opts["jvm_args"]:
        import shlex
        try:
            jvm = [a for a in shlex.split(opts["jvm_args"], posix=True) if a]
        except Exception:
            jvm = opts["jvm_args"].split()
    elif inst.get("jvm_args"):
        from .ui_v2 import parse_jvm_args
        jvm = parse_jvm_args(inst.get("jvm_args"))

    acc = accounts.current(cfg)
    auth = accounts.launch_auth(acc)
    cmd, _vj, _root, _missing = mojang.build_command(
        game_dir, vid, exe, auth.get("name") or cfg.get("username") or "Steve",
        memory, width, height, extra_jvm=jvm, auth=auth)
    proc = mojang.launch(cmd, game_dir)
    try:
        inst["last_version"] = vid
        instances.update(cfg, inst["id"], last_version=vid)
    except Exception:
        pass
    log("LAUNCH instance=%s(%s) version=%s java=%s memory=%d pid=%d" % (
        inst.get("name"), inst.get("id"), vid, exe, memory, proc.pid))
    return proc.pid


def main(argv):
    """返回进程退出码。"""
    try:
        opts = parse_args(argv)
    except CliError as e:
        log("参数错误：%s" % e)
        return e.code

    if opts["command"] == "help":
        log(USAGE)
        return 0
    if opts["command"] is None:
        # 无参数：交给 GUI
        return None

    cfg = util.load_config()
    instances.migrate(cfg)
    try:
        if opts["command"] == "list":
            cmd_list_instances(cfg)
            return 0
        if opts["command"] == "launch":
            pid = cmd_launch(cfg, opts)
            log("启动成功，游戏进程 PID=%s（启动器 CLI 即将退出，游戏独立运行）" % pid)
            return 0
    except CliError as e:
        log("错误：%s" % e)
        return e.code
    except Exception as e:
        log("CLI 异常：%r" % e)
        return 1
    return 0
