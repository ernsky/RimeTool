"""替换分组：将指定词库与数据库匹配，更新分组。"""

from __future__ import annotations

import os
import sqlite3
from typing import Callable, Dict, Tuple

from . import rime_io


def parse_source_file(path: str) -> Tuple[list, str]:
    """解析源文件，返回 (匹配项列表, 格式类型)。
    
    支持的格式：
    1. Rime 词典格式 (.yaml/.dict.yaml)：... 以下，词组\t编码\t权重
    2. 搜狗词库转换格式 (.txt)：词频\t拼音\t词组（三列），取第3列作为词组
    3. 词组+权重格式 (.txt)：词组\t权重（两列），取第1列作为词组
    4. 纯词组格式 (.txt/.md)：每行一个词组（一列）
    
    返回的匹配项：
      - 格式为 'dict' 时：[(key, code), ...]
      - 格式为 'single' 时：[(key, None), ...]
    """
    ext = os.path.splitext(path)[1].lower()
    
    # 尝试按 Rime 词典格式解析
    if ext in ('.yaml', '.dict.yaml'):
        weights = rime_io.parse_dict_weights(path)
        if weights:
            # 有数据，格式为 dict
            return [(key, code) for (key, code) in weights.keys()], 'dict'
    
    # 尝试按纯文本格式解析
    items = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split("\t")
                if len(parts) >= 3:
                    # 三列格式：词频、拼音、词组 → 取第3列作为词组
                    word = parts[2].strip()
                    if word:
                        items.append((word, None))
                elif len(parts) >= 2:
                    # 两列格式：词组、权重 → 取第1列作为词组
                    word = parts[0].strip()
                    if word:
                        items.append((word, None))
                elif len(parts) == 1 and parts[0].strip():
                    # 一列格式：只有词组
                    items.append((parts[0].strip(), None))
    except Exception:
        pass
    
    if items:
        return items, 'single'
    
    return [], 'unknown'


def replace_group(
    conn: sqlite3.Connection,
    source_path: str,
    category: str = "常用",
    group: str = "青云",
    progress_cb: Callable[[int, int], None] = None,
) -> Tuple[int, int, int]:
    """将源文件与数据库匹配，更新分组。

    Args:
        conn: SQLite 连接
        source_path: 源文件路径（Rime词典/词组文本）
        category: 目标分类（默认"常用"）
        group: 目标分组（默认"青云"）
        progress_cb: 进度回调 (当前, 总数)

    Returns:
        (匹配数, 更新数, 跳过数)
    """
    items, fmt = parse_source_file(source_path)
    if not items:
        return 0, 0, 0

    total = len(items)
    matched = 0
    updated = 0
    skipped = 0

    if fmt == 'dict':
        # Rime 词典格式：按 词组+编码 匹配
        for key, code in items:
            cur = conn.execute(
                "SELECT key, code, category, grp FROM words WHERE key=? AND code=?",
                (key, code),
            )
            row = cur.fetchone()
            if row:
                matched += 1
                old_category = row[2]
                old_group = row[3]
                if old_category == category and old_group == group:
                    skipped += 1
                else:
                    conn.execute(
                        "UPDATE words SET category=?, grp=? WHERE key=? AND code=?",
                        (category, group, key, code),
                    )
                    updated += 1
            else:
                skipped += 1

            if progress_cb:
                progress_cb(matched + skipped, total)
    else:
        # 单列词组格式：按 词组 匹配
        for key, _ in items:
            cur = conn.execute(
                "SELECT key, code, category, grp FROM words WHERE key=?",
                (key,),
            )
            rows = cur.fetchall()
            if rows:
                for row in rows:
                    matched += 1
                    old_category = row[2]
                    old_group = row[3]
                    if old_category == category and old_group == group:
                        skipped += 1
                    else:
                        conn.execute(
                            "UPDATE words SET category=?, grp=? WHERE key=?",
                            (category, group, key),
                        )
                        updated += 1
            else:
                skipped += 1

            if progress_cb:
                progress_cb(matched + skipped, total)

    conn.commit()
    return matched, updated, skipped
