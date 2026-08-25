# -*- coding: utf-8 -*-
"""批量修改 TSV 权重：按 (词组, 编码) 匹配映射文件的最大权重，覆盖第 3 列（权重）。

移植自 Rime 工具箱 Python/features/feature_replace_weight_by_match.py，但做成 RimeTool
自包含的纯逻辑模块（不依赖 pandas），路径从用户文件夹配置读取，不硬编码。

行为：
  - 写入文件 = 配置的 tsv_path（Alamo.tsv）；
  - A-F 六个导出目标：仅按最大权重替换已有行第 3 列；缺失词按 A 备用/A 追加；
  - chaos（REFERENCE_DICTS，纯参考）特殊处理：其 (词组,编码) 在主表存在 -> 改权重=chaos
    权重、分组=B 青云、启用=A；主表不存在 -> 追加 [词组,编码,权重,B 青云,A]；处理完删除
    chaos 中已处理的词条（保留 ---/... 头与注释，删前先备份）；
  - (词组,编码) 对应多个权重时取最大；
  - 5 列 schema 下不再维护顺序码列（分组顺序码/全表顺序码）；
  - 直接覆盖写回原 tsv_path；写前经 core.backup 在 Logs/ 生成单基线快照
    （整会话仅一次、稳定文件名、gzip 压缩，非同目录时间戳备份），可由 UI「从备份恢复」回退。
"""
import os
import logging
from typing import Dict, List, Set, Tuple

from core.rime_export import read_tsv_rows, GROUP_TARGETS, REFERENCE_DICTS

_log = logging.getLogger(__name__)

# 5 列布局索引（与 core/rime_export 及 features 一致）
WORD_IDX = 0
CODE_IDX = 1
WEIGHT_IDX = 2
GROUP_IDX = 3
ENABLE_IDX = 4

DEFAULT_GROUP = "A 备用"
DEFAULT_ENABLE = "A"


# chaos 词条特殊处理：匹配主表行 -> 改分组=B 青云、启用=A、权重=chaos 值；
# 主表无 -> 追加（同分组/启用）；处理完删除 chaos 中已处理词条。
CHAOS_GROUP = "B 青云"
CHAOS_ENABLE = "A"


def _rewrite_chaos_drop(chaos_path: str, drop_keys: Set[Tuple[str, str]]) -> int:
    """回写 chaos 词典：删除 drop_keys 中的 (词组,编码) 数据行，保留 ---/... 头与注释/空行。

    返回删除行数。调用方负责先备份。数据行按 Tab 分隔（无 Tab 则按空白），至少 2 列；
    头部（'...' 之前）、'#'/'##' 注释行、空行均原样保留。
    """
    try:
        with open(chaos_path, "r", encoding="utf-8-sig", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return 0
    has_marker = any(ln.strip() == "..." for ln in lines)
    started = not has_marker
    out = []
    removed = 0
    for ln in lines:
        s = ln.strip()
        if not started:
            out.append(ln)
            if s == "...":
                started = True
            continue
        if not s or s.startswith("#"):
            out.append(ln)
            continue
        parts = ln.split("\t") if "\t" in ln else ln.split()
        if len(parts) < 2:
            out.append(ln)
            continue
        key = (parts[0].strip(), parts[1].strip())
        if key in drop_keys:
            removed += 1
            continue
        out.append(ln)
    try:
        with open(chaos_path, "w", encoding="utf-8") as f:
            f.writelines(out)
    except OSError:
        return 0
    return removed


def _parse_mapping_file(filepath: str) -> Dict[Tuple[str, str], int]:
    """解析单个映射文件，返回 (词组,编码)->最大权重。

    规则：忽略空行、# 注释行、'...' 之前内容；数据行至少 2 列；第 3 列权重缺失/非数字默认 1；
    同 (词组,编码) 取最大权重。
    """
    pair_weight: Dict[Tuple[str, str], int] = {}
    try:
        with open(filepath, "r", encoding="utf-8-sig", errors="replace") as f:
            raw = f.read().split("\n")
    except OSError:
        return pair_weight
    has_marker = any(ln.strip() == "..." for ln in raw)
    started = not has_marker
    for ln in raw:
        if not started:
            if ln.strip() == "...":
                started = True
            continue
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        parts = ln.split("\t") if "\t" in ln else ln.split()
        if len(parts) < 2:
            continue
        word = parts[0].strip()
        code = parts[1].strip()
        if not word:
            continue
        weight = 1
        if len(parts) >= 3:
            try:
                weight = int(float(parts[2].strip()))
            except ValueError:
                weight = 1
        key = (word, code)
        if key in pair_weight:
            if weight > pair_weight[key]:
                pair_weight[key] = weight
        else:
            pair_weight[key] = weight
    return pair_weight


def _head_before_marker(filepath: str) -> str:
    """返回 '...' 行及其之前的内容（含 '...'）；无 '...' 标记返回空串（避免把整文件当头）。"""
    try:
        with open(filepath, "r", encoding="utf-8-sig", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return ""
    out = []
    for ln in lines:
        out.append(ln)
        if ln.strip() == "...":
            return "".join(out)
    return ""


def replace_weights(tsv_path: str, rime_config_dir: str = None) -> dict:
    """按映射文件的最大权重覆盖 tsv_path 第 3 列权重；并特殊处理 chaos 词条。

    A-F 六个导出目标：仅按最大权重替换已有行第 3 列；缺失词按 A 备用/A 追加。
    chaos（REFERENCE_DICTS，纯参考）特殊处理：其 (词组,编码) 在主表存在 -> 改权重=chaos
        权重、分组=B 青云、启用=A；主表不存在 -> 追加 [词组,编码,权重,B 青云,A]；处理完
        删除 chaos 中已处理的词条（保留 ---/... 头与注释，删前先备份）。
    直接覆盖写回原 tsv_path；写前经 core.backup 在 Logs/ 生成单基线快照（非同目录时间戳备份）。

    返回 dict：{
      'ok': bool, 'message': str,
      'replaced': int, 'added': int, 'total': int,
      'output_path': str, 'backup': str,
      'used_files': [str...], 'missing_files': [str...],
      'chaos_updated': int, 'chaos_added': int, 'chaos_removed': int,
    }
    """
    if not tsv_path or not os.path.exists(tsv_path):
        return {
            "ok": False, "message": "写入文件不存在：%s" % tsv_path,
            "replaced": 0, "added": 0, "total": 0, "backup": "",
            "used_files": [], "missing_files": [],
            "chaos_updated": 0, "chaos_added": 0, "chaos_removed": 0,
        }

    d = rime_config_dir or ""
    af_files = [os.path.join(d, p) for p, _ in GROUP_TARGETS.values()]
    chaos_files = [os.path.join(d, r) for r in REFERENCE_DICTS]

    # 1. A-F 合并 -> (词组,编码)->最大权重
    af_weight: Dict[Tuple[str, str], int] = {}
    missing_files: List[str] = []
    used_files: List[str] = []
    for fp in af_files:
        if not os.path.exists(fp):
            missing_files.append(fp)
            continue
        used_files.append(fp)
        for key, w in _parse_mapping_file(fp).items():
            if key in af_weight:
                if w > af_weight[key]:
                    af_weight[key] = w
            else:
                af_weight[key] = w

    # 2. chaos 合并 -> (词组,编码)->权重（chaos 对其词权威，取最大即可）
    chaos_pairs: Dict[Tuple[str, str], int] = {}
    for fp in chaos_files:
        if not os.path.exists(fp):
            missing_files.append(fp)
            continue
        used_files.append(fp)
        for key, w in _parse_mapping_file(fp).items():
            if key in chaos_pairs:
                if w > chaos_pairs[key]:
                    chaos_pairs[key] = w
            else:
                chaos_pairs[key] = w

    if not af_weight and not chaos_pairs:
        return {
            "ok": False,
            "message": "没有可用的映射文件（A-F 与 chaos 均不存在）。\n%s" % "\n".join(missing_files),
            "replaced": 0, "added": 0, "total": 0, "backup": "",
            "used_files": [], "missing_files": missing_files,
            "chaos_updated": 0, "chaos_added": 0, "chaos_removed": 0,
        }

    # 3. 读写入文件（复用 rime_export.read_tsv_rows，跳过 ... 前/# /空行），补齐到 5 列
    rows = read_tsv_rows(tsv_path)
    norm_rows: List[List[str]] = []
    for r in rows:
        r = list(r)
        if len(r) < 5:
            r = r + [""] * (5 - len(r))
        else:
            r = r[:5]
        norm_rows.append(r)
    seen = {(r[WORD_IDX].strip(), r[CODE_IDX].strip())
            for r in norm_rows if r[WORD_IDX].strip()}

    replaced = 0
    added = 0

    # 4. A-F：替换已有行权重（取最大）；缺失词按 A 备用/A 追加
    for r in norm_rows:
        word = r[WORD_IDX].strip()
        code = r[CODE_IDX].strip()
        if not word:
            continue
        key = (word, code)
        if key in af_weight:
            r[WEIGHT_IDX] = str(af_weight[key])
            replaced += 1
    for (word, code), w in af_weight.items():
        if (word, code) not in seen:
            norm_rows.append([word, code, str(w), DEFAULT_GROUP, DEFAULT_ENABLE])
            seen.add((word, code))
            added += 1

    # 5. chaos 特殊处理：(词组,编码) 精确匹配
    #    - 主表存在 -> 改权重=chaos权重、分组=B 青云、启用=A
    #    - 主表不存在 -> 追加 [词组,编码,权重,B 青云,A]
    chaos_updated = 0
    chaos_added = 0
    for (word, code), w in chaos_pairs.items():
        key = (word, code)
        matched = False
        for r in norm_rows:
            if r[WORD_IDX].strip() == word and r[CODE_IDX].strip() == code:
                r[WEIGHT_IDX] = str(w)
                r[GROUP_IDX] = CHAOS_GROUP
                r[ENABLE_IDX] = CHAOS_ENABLE
                matched = True
                chaos_updated += 1
        if not matched:
            norm_rows.append([word, code, str(w), CHAOS_GROUP, CHAOS_ENABLE])
            seen.add(key)
            chaos_added += 1

    # 6. 写前快照（统一走 core.backup：Logs 目录，整会话仅一次，无 Rime- 前缀）
    #    tsv 通常已在加载时快照；此处再调一次仅取缓存路径，确保即使未走 UI 也有底。
    from core import backup as backup_mod
    from core.config import is_safe_target
    backup = backup_mod.open_snapshot(tsv_path)

    # 7. 覆盖写回（保留 ... 前头部，否则纯 5 列 TSV）
    if not is_safe_target(tsv_path):
        return {
            "ok": False, "message": "tsv_path 位于不允许的系统目录，已拒绝写回：%s" % tsv_path,
            "replaced": 0, "added": 0, "total": 0, "backup": backup,
            "used_files": used_files, "missing_files": missing_files,
            "chaos_updated": 0, "chaos_added": 0, "chaos_removed": 0,
        }
    head = _head_before_marker(tsv_path)
    try:
        with open(tsv_path, "w", encoding="utf-8") as f:
            if head:
                f.write(head)
                if not head.endswith("\n"):
                    f.write("\n")
            for r in norm_rows:
                f.write("\t".join(r) + "\n")
    except OSError as exc:
        return {
            "ok": False, "message": "写入失败：%s" % exc,
            "replaced": 0, "added": 0, "total": 0, "backup": backup,
            "used_files": used_files, "missing_files": missing_files,
            "chaos_updated": 0, "chaos_added": 0, "chaos_removed": 0,
        }

    # 8. 写回 chaos：删除已处理词条（删前先备份）。chaos_pairs 的键即本次全部处理的词条。
    chaos_removed = 0
    drop_keys = set(chaos_pairs.keys())
    for fp in chaos_files:
        if not os.path.exists(fp):
            continue
        if not is_safe_target(fp):
            _log.warning("跳过危险系统目录下的 chaos 文件：%s", fp)
            continue
        backup_mod.open_snapshot(fp, "Rime-")   # chaos 是 Rime 词典，备份加 Rime- 前缀
        chaos_removed += _rewrite_chaos_drop(fp, drop_keys)

    return {
        "ok": True, "message": "",
        "replaced": replaced + chaos_updated, "added": added + chaos_added,
        "total": len(norm_rows),
        "output_path": tsv_path, "backup": backup,
        "used_files": used_files, "missing_files": missing_files,
        "chaos_updated": chaos_updated, "chaos_added": chaos_added,
        "chaos_removed": chaos_removed,
    }
