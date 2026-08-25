# -*- coding: utf-8 -*-
"""统一备份模块（RimeTool 自包含，轻量 + 可回退）。

设计（用户方案：单基线）：
  - 落点：<RimeTool 目录>/Logs（与日志同目录）。
  - 每个被备份文件仅 1 份基线：<prefix><原名>.bak.gz，稳定文件名、跨会话持久、gzip 压缩。
  - 触发：在「打开/即将写回」时调用 open_snapshot；若基线已存在则直接复用，不重复生成
    -> 不频繁、不泛滥、体积小（Alamo.tsv 1.63M 行压缩后极小）。
  - 可回退：restore_snapshot(bak_gz, target) 解压写回；manifest.json 记录 备份名->目标绝对路径，
    供 UI「从备份恢复」列出与回退。
  - 仅备被操作的原文件：tsv 在加载时快照；Rime 词典/chaos 在写回前快照（前缀 Rime-）。
"""
import os
import shutil
import hashlib
import logging

_log = logging.getLogger(__name__)
import gzip
import json
from typing import Dict, List


def backup_dir() -> str:
    """备份目录：core/backup.py -> RimeTool/Logs（与日志同目录）。"""
    app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(app_dir, "Logs")


def ensure_backup_dir() -> None:
    os.makedirs(backup_dir(), exist_ok=True)


def _manifest_path() -> str:
    return os.path.join(backup_dir(), "manifest.json")


def _load_manifest() -> Dict[str, str]:
    try:
        with open(_manifest_path(), "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save_manifest(m: Dict[str, str]) -> None:
    ensure_backup_dir()
    try:
        with open(_manifest_path(), "w", encoding="utf-8") as f:
            json.dump(m, f, ensure_ascii=False, indent=2)
    except OSError:
        _log.debug("写入 manifest 失败", exc_info=True)


def _record_manifest(bp: str, target: str) -> None:
    m = _load_manifest()
    m[os.path.basename(bp)] = os.path.abspath(target)
    _save_manifest(m)


def _stable_backup_name(path: str, prefix: str) -> str:
    """稳定备份文件名：<Logs>/<abspath哈希>-<prefix><原名>.bak.gz（覆盖式、跨会话持久）。

    用 abspath 的稳定哈希前缀区分不同目录下的同名文件，避免跨目录同名互相覆盖
    （原实现仅取 basename 会导致 dirA/Alamo.tsv 与 dirB/Alamo.tsv 共用同一基线，
    恢复时把 A 的数据写回 B 目标——数据错乱，安全审查 F2）。
    manifest 键取该文件名，天然唯一。
    """
    ensure_backup_dir()
    base = os.path.basename(path)
    if prefix:
        base = prefix + base
    h = hashlib.sha1(os.path.abspath(path).encode("utf-8")).hexdigest()[:12]
    return os.path.join(backup_dir(), f"{h}-{base}.bak.gz")


# 会话级去重：同一 (路径, 前缀) 整会话只备一次（与跨会话持久基线配合，双保险）
_snapshotted: Dict[tuple, str] = {}


def open_snapshot(path: str, prefix: str = "") -> str:
    """在被操作前复制当前状态进 Logs（与日志同目录），作为可回退的基线（每文件仅 1 份，gzip 压缩）。

    基线已存在（本次会话或之前会话）则直接复用，不重复生成；仅首次捕获时写入
    -> 不频繁、不泛滥。返回备份路径（.bak.gz）；文件不存在/失败返回空串。
    同时在 manifest.json 记录 备份名->目标绝对路径，供回退使用。
    """
    if not path or not os.path.exists(path):
        return ""
    key = (os.path.abspath(path), prefix)
    if key in _snapshotted:
        return _snapshotted[key]
    bp = _stable_backup_name(path, prefix)
    if os.path.exists(bp):
        # 基线已存在：复用，仅刷新 manifest 映射（不重写，避免无谓 I/O 与泛滥）
        _record_manifest(bp, path)
        _snapshotted[key] = bp
        return bp
    # 首次捕获：gzip 压缩当前文件为基线
    try:
        with open(path, "rb") as src, gzip.open(bp, "wb", compresslevel=6) as dst:
            shutil.copyfileobj(src, dst)
    except OSError:
        _log.debug("创建备份快照失败", exc_info=True)
        return ""
    _record_manifest(bp, path)
    _snapshotted[key] = bp
    return bp


def list_backups() -> List[dict]:
    """列出当前可用的备份：[{'backup': 绝对路径, 'target': 目标绝对路径, 'name': 文件名}]。"""
    m = _load_manifest()
    out = []
    for name, target in m.items():
        bp = os.path.join(backup_dir(), name)
        if os.path.exists(bp):
            out.append({"backup": bp, "target": target, "name": name})
    return out


def restore_snapshot(backup_file: str, target: str, safe: bool = True) -> bool:
    """从压缩备份解压写回目标文件（退回备份时的状态）。

    safe=True 时先对当前目标做一次安全快照（<prefix><原名>.pre-restore.bak.gz，覆盖式），
    使本次回退本身也可再撤销。成功返回 True。
    """
    if not backup_file or not os.path.exists(backup_file):
        return False
    if safe:
        try:
            pre = os.path.join(
                backup_dir(),
                "pre-restore." + os.path.basename(backup_file),
            )
            with open(target, "rb") as src, gzip.open(pre, "wb", compresslevel=6) as dst:
                shutil.copyfileobj(src, dst)
        except OSError:
            _log.debug("安全快照失败，不阻断回退", exc_info=True)
    try:
        with gzip.open(backup_file, "rb") as src, open(target, "wb") as dst:
            shutil.copyfileobj(src, dst)
    except OSError:
        _log.debug("解压回退失败", exc_info=True)
        return False
    return True


def reset_session() -> None:
    """清空会话去重缓存（测试或重新打开软件时调用）。"""
    _snapshotted.clear()
