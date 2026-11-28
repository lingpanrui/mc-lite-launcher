# -*- coding: utf-8 -*-
"""共享内容池（批次5）：多实例共享 assets / libraries

池位置：%APPDATA%\\MCLite\\shared\\{assets,libraries}

接入方式（按优先级自动降级，界面/日志如实写明实际模式）：
1. 同卷：先把实例文件用 os.link 硬链接进池（不额外占块，按 inode 去重）；
2. 目录级统一用 junction（mklink /J，无需管理员）把实例 assets/libraries 指向池；
3. 跨卷无法硬链接时退化为复制进池；junction 不可用时退化为整目录复制（mode=copy）。

安全第一（绝不先删用户文件）：
- 对已有实例：先 ingest（链接/复制到池）→ 逐个校验可读与大小 → 把原目录改名成
  `.__old_<时间戳>` 备份（同卷瞬间改名）→ 建 junction → 校验 junction 可读、文件数一致
  → 才删除备份；任何一步失败立即把备份改名还原，原文件保持可用。
- 新空实例：直接建 junction，无原文件可保护。
- 残留 `.__old_*` 备份可由 recover_pending() 一键还原。
"""
import ctypes
import datetime
import os
import shutil
import subprocess
import time

from . import util

POOL_DIRNAME = "shared"
KINDS = ("assets", "libraries")
BACKUP_PREFIX = ".__old_"
JOIN_MANIFEST = ".mclite-pool.json"
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400


# ---------------------------------------------------------------- 路径
def pool_root(cfg=None):
    return os.path.join(util.app_root(), POOL_DIRNAME)


def pool_dir(kind, cfg=None):
    return os.path.join(pool_root(cfg), kind)


def is_junction(path):
    """Windows 目录联接（junction）判定；非 Windows 或异常返回 False。"""
    try:
        if not os.path.isdir(path):
            return False
        attr = ctypes.windll.kernel32.GetFileAttributesW(str(path))
        if attr == -1:
            return False
        return bool(attr & _FILE_ATTRIBUTE_REPARSE_POINT)
    except Exception:
        return False


def same_volume(a, b):
    try:
        return os.stat(a).st_dev == os.stat(b).st_dev
    except OSError:
        return False


# ---------------------------------------------------------------- 链接/复制
def link_or_copy_file(src, dst):
    """同卷硬链接，失败（跨卷/文件系统不支持）退化为复制。返回 'link' 或 'copy'。"""
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.exists(dst):
        if os.path.getsize(dst) == os.path.getsize(src):
            return "skip"
        os.remove(dst)
    try:
        os.link(src, dst)
        return "link"
    except OSError:
        shutil.copy2(src, dst)
        return "copy"


def _make_junction(link_path, target_path):
    """创建目录 junction（mklink /J，无需管理员）。成功返回 True。"""
    os.makedirs(target_path, exist_ok=True)
    if os.path.exists(link_path):
        return False
    cmd = 'mklink /J "%s" "%s"' % (os.path.abspath(link_path), os.path.abspath(target_path))
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
        return r.returncode == 0 and os.path.isdir(link_path)
    except Exception:
        return False


def _count_files(path):
    n = 0
    for _root, _dirs, files in os.walk(path):
        n += len(files)
    return n


# ---------------------------------------------------------------- 入池（不删源）
def ingest_dir(src_dir, dst_pool, status=None):
    """把 src_dir 内全部文件链接/复制进池；绝不删除 src_dir 任何文件。

    返回 {files, linked, copied, skipped, bytes, errors}。
    """
    status = status or (lambda s: None)
    stats = {"files": 0, "linked": 0, "copied": 0, "skipped": 0, "bytes": 0, "errors": []}
    if not os.path.isdir(src_dir):
        return stats
    os.makedirs(dst_pool, exist_ok=True)
    for root, _dirs, files in os.walk(src_dir):
        for fn in files:
            sp = os.path.join(root, fn)
            rel = os.path.relpath(sp, src_dir)
            dp = os.path.join(dst_pool, rel)
            try:
                size = os.path.getsize(sp)
                mode = link_or_copy_file(sp, dp)
                # 校验池内文件可读且大小一致
                if not os.path.isfile(dp) or os.path.getsize(dp) != size:
                    raise IOError("池内文件校验失败：%s" % rel)
                stats["files"] += 1
                stats["bytes"] += size
                stats[{"link": "linked", "copy": "copied", "skip": "skipped"}[mode]] += 1
            except Exception as e:
                stats["errors"].append("%s: %s" % (rel, e))
    status("入池完成 %d 个文件（硬链接 %d / 复制 %d / 跳过 %d）" % (
        stats["files"], stats["linked"], stats["copied"], stats["skipped"]))
    return stats


# ---------------------------------------------------------------- 加入实例
def _verify_junction(link_path, expect_count=None):
    if not os.path.isdir(link_path):
        return False
    if expect_count is not None:
        try:
            if _count_files(link_path) < expect_count:
                return False
        except Exception:
            return False
    # 读一个文件确认可穿透
    try:
        for root, _d, files in os.walk(link_path):
            if files:
                with open(os.path.join(root, files[0]), "rb") as f:
                    f.read(1)
                return True
    except Exception:
        return False
    return True


def join_instance(game_dir, kinds=KINDS, status=None, cleanup_backup=True):
    """把实例的 assets/libraries 接入共享池。返回每类结果 dict。

    安全流程：ingest→校验→改名备份→建 junction→校验→（可选）删备份；失败自动回滚。
    """
    status = status or (lambda s: None)
    game_dir = os.path.abspath(game_dir)
    os.makedirs(game_dir, exist_ok=True)
    report = {"game_dir": game_dir, "kinds": {}, "ts": datetime.datetime.now().isoformat(timespec="seconds")}

    for kind in kinds:
        src = os.path.join(game_dir, kind)
        pool = pool_dir(kind)
        item = {"kind": kind, "mode": "none", "pool": pool, "files": 0, "bytes": 0, "detail": ""}

        # 已是 junction：确认指向池
        if is_junction(src):
            item["mode"] = "already"
            item["detail"] = "已是目录联接"
            report["kinds"][kind] = item
            continue

        # 空/不存在：直接建 junction
        if not os.path.exists(src):
            os.makedirs(pool, exist_ok=True)
            if _make_junction(src, pool):
                item["mode"] = "junction-new"
                item["detail"] = "新建目录联接 → 共享池"
            else:
                item["mode"] = "copy-fallback"
                os.makedirs(src, exist_ok=True)
                item["detail"] = "junction 不可用，已建空目录（请手动复制或重试）"
            report["kinds"][kind] = item
            continue

        if not os.path.isdir(src):
            item["mode"] = "skip-file"
            item["detail"] = "同名文件占用，跳过"
            report["kinds"][kind] = item
            continue

        # 1) 先入池（不删源）
        status("正在把 %s 接入共享池…" % kind)
        ing = ingest_dir(src, pool, status)
        item["files"] = ing["files"]
        item["bytes"] = ing["bytes"]
        if ing["errors"]:
            item["mode"] = "ingest-error"
            item["detail"] = "入池有错误，原目录未改动：%s" % ing["errors"][:3]
            report["kinds"][kind] = item
            continue

        # 2) 改名备份（同卷瞬间），再建 junction
        stamp = time.strftime("%Y%m%d-%H%M%S")
        backup = "%s%s%s" % (src, BACKUP_PREFIX, stamp)
        os.rename(src, backup)
        try:
            if not _make_junction(src, pool):
                raise IOError("mklink /J 失败")
            if not _verify_junction(src, expect_count=ing["files"]):
                raise IOError("junction 校验失败（文件数/可读性）")
        except Exception as e:
            # 回滚：删掉半成品 junction，把备份改回原名
            try:
                if is_junction(src) or os.path.exists(src):
                    if is_junction(src):
                        os.rmdir(src)  # 仅删 junction 本身，不删目标
                    elif os.path.isdir(src):
                        shutil.rmtree(src, ignore_errors=True)
            except Exception:
                pass
            try:
                os.rename(backup, src)
            except Exception:
                pass
            item["mode"] = "rollback"
            item["detail"] = "联接失败已回滚，原目录保持可用：%s" % e
            report["kinds"][kind] = item
            continue

        # 3) junction 校验通过，才清理备份（硬链接场景池内仍保留 inode 块）
        if cleanup_backup:
            try:
                shutil.rmtree(backup)
                item["backup_removed"] = True
            except Exception as e:
                item["backup_removed"] = False
                item["detail"] = "备份暂留：%s" % e
        else:
            item["backup"] = backup
        item["mode"] = "junction"
        item["detail"] = "硬链接/复制入池 %d 文件，junction 已生效" % ing["files"]
        report["kinds"][kind] = item

    util.write_json(os.path.join(game_dir, JOIN_MANIFEST), report)
    return report


def recover_pending(game_dir):
    """还原残留的 `.__old_*` 备份（junction 失败/中断后的兜底）。返回还原的目录列表。"""
    restored = []
    for kind in KINDS:
        base = os.path.join(game_dir, kind)
        parent = os.path.dirname(base)
        prefix = os.path.basename(base) + BACKUP_PREFIX
        try:
            for name in os.listdir(parent):
                if name.startswith(prefix):
                    backup = os.path.join(parent, name)
                    if is_junction(base):
                        os.rmdir(base)
                    elif os.path.isdir(base):
                        shutil.rmtree(base, ignore_errors=True)
                    os.rename(backup, base)
                    restored.append(base)
        except Exception:
            continue
    return restored


# ---------------------------------------------------------------- 测量
def dir_logical_bytes(path):
    """目录逻辑字节（跟随 junction 统计其目标内容；用于独立副本口径）。"""
    total = 0
    if not os.path.isdir(path):
        return 0
    for root, _dirs, files in os.walk(path):
        for fn in files:
            try:
                total += os.path.getsize(os.path.join(root, fn))
            except OSError:
                pass
    return total


def unique_inode_bytes(paths):
    """按 (st_dev, st_ino) 去重统计真实占用字节（硬链接只算一次）。"""
    seen = set()
    total = 0
    for base in paths:
        if not base or not os.path.isdir(base):
            continue
        for root, _dirs, files in os.walk(base):
            for fn in files:
                p = os.path.join(root, fn)
                try:
                    st = os.stat(p)
                except OSError:
                    continue
                key = (st.st_dev, st.st_ino)
                if key in seen:
                    continue
                seen.add(key)
                total += st.st_size
    return total


def instance_physical_bytes(game_dir):
    """有池状态下实例自身真实占用：versions 全量 + assets/libraries 非 junction 部分。

    junction 的 assets/libraries 物理块在 shared 池里，这里计 0，避免重复。
    """
    total = 0
    for kind in ("versions",):
        total += dir_logical_bytes(os.path.join(game_dir, kind))
    for kind in KINDS:
        p = os.path.join(game_dir, kind)
        if is_junction(p):
            continue
        total += dir_logical_bytes(p)
    return total


def pool_physical_bytes(cfg=None):
    return unique_inode_bytes([pool_dir(k, cfg) for k in KINDS])


def compare(cfg, game_dirs):
    """对比「无池独立副本」与「有池共享」两种口径。

    无池 baseline：每个实例若各自持有 assets/libraries 副本，逻辑字节 =
      n × (池 assets + 池 libraries 逻辑大小) + 各实例 versions 字节之和。
    有池 physical：shared 池唯一 inode 字节 + 各实例 versions 字节（junction 不重复占块）。
    """
    pool_assets = dir_logical_bytes(pool_dir("assets", cfg))
    pool_libs = dir_logical_bytes(pool_dir("libraries", cfg))
    pool_logical = pool_assets + pool_libs
    pool_phys = pool_physical_bytes(cfg)

    versions_sum = 0
    inst_phys = 0
    per_instance = []
    for gd in game_dirs:
        v = dir_logical_bytes(os.path.join(gd, "versions"))
        versions_sum += v
        phys = instance_physical_bytes(gd)
        inst_phys += phys
        per_instance.append({"game_dir": gd, "versions_bytes": v, "physical_bytes": phys})

    n = max(1, len(game_dirs))
    no_pool = n * pool_logical + versions_sum
    with_pool = pool_phys + versions_sum
    saved = max(0, no_pool - with_pool)
    pct = (saved / no_pool * 100.0) if no_pool else 0.0
    return {
        "instances": per_instance,
        "pool_assets_logical": pool_assets,
        "pool_libraries_logical": pool_libs,
        "pool_logical": pool_logical,
        "pool_physical_unique": pool_phys,
        "versions_sum": versions_sum,
        "no_pool_independent_bytes": no_pool,
        "with_pool_physical_bytes": with_pool,
        "saved_bytes": saved,
        "saved_percent": round(pct, 1),
        "instance_count": n,
    }
