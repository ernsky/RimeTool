"""SQLite 数据访问层：词组记录的增删改查 + 分组聚合 + 叠加筛选。

数据库文件由 config.json 的 db_path 决定（绝对或相对项目根）。
表 words: 词组+编码 复合主键, 权重, 分类, 分组, 启用。
"""

from __future__ import annotations

import os
import sqlite3
from typing import Dict, List, Optional

from .models import WordRecord, GROUP_SEP


class Repository:
    """词组记录仓库。每个实例持有一个 SQLite 连接。"""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self.conn.execute("PRAGMA synchronous=NORMAL;")
        self._init_schema()

    def _init_schema(self) -> None:
        # 检查现有表结构，若主键不是复合键则重建（迁移到词组+编码复合主键）
        cur = self.conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='words'")
        row = cur.fetchone()
        if row and "PRIMARY KEY (key, code)" not in (row[0] or ""):
            self.conn.execute("DROP TABLE IF EXISTS words")
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS words (
                key  TEXT,
                code TEXT NOT NULL DEFAULT '',
                weight INTEGER NOT NULL DEFAULT 1,
                category TEXT NOT NULL DEFAULT '',
                grp  TEXT NOT NULL DEFAULT '',
                enabled INTEGER NOT NULL DEFAULT 1,
                PRIMARY KEY (key, code)
            )
            """
        )
        # 加速查询的索引
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_words_grp ON words(grp)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_words_category ON words(category)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_words_enabled ON words(enabled)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_words_key ON words(key)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_words_weight ON words(weight DESC)")
        # 更新统计信息，帮助查询优化器选择最优执行计划
        self.conn.execute("ANALYZE words")
        self.conn.commit()

    def import_from_tsv(self, path: str, batch_size: int = 10000, progress_cb=None) -> int:
        """从 TSV 文件批量导入。格式: 词组\\t编码\\t权重\\t分类\\t分组\\t启用。"""
        batch = []
        imported = 0
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                parts = line.split("\t")
                if len(parts) >= 6:
                    batch.append((parts[0], parts[1], int(parts[2] or 1), parts[3], parts[4], 1 if parts[5] == "A" else 0))
                elif len(parts) >= 2:
                    batch.append((parts[0], parts[1], int(parts[2] or 1) if len(parts) > 2 else 1, parts[3] if len(parts) > 3 else "", parts[4] if len(parts) > 4 else "", 1 if len(parts) > 5 and parts[5] == "A" else 0))
                if len(batch) >= batch_size:
                    self.conn.executemany("INSERT INTO words(key,code,weight,category,grp,enabled) VALUES(?,?,?,?,?,?) ON CONFLICT(key,code) DO UPDATE SET weight=excluded.weight, category=excluded.category, grp=excluded.grp, enabled=excluded.enabled", batch)
                    imported += len(batch)
                    batch = []
                    if progress_cb:
                        progress_cb(imported, imported)  # 总数未知，用 imported 占位
            if batch:
                self.conn.executemany("INSERT INTO words(key,code,weight,category,grp,enabled) VALUES(?,?,?,?,?,?) ON CONFLICT(key,code) DO UPDATE SET weight=excluded.weight, category=excluded.category, grp=excluded.grp, enabled=excluded.enabled", batch)
                imported += len(batch)
                if progress_cb:
                    progress_cb(imported, imported)
        self.conn.commit()
        self.conn.execute("ANALYZE words")
        return imported

    def close(self) -> None:
        self.conn.close()

    # ---------- 写 ----------
    def upsert(self, rec: WordRecord) -> None:
        """插入或更新一条记录（以 词组+编码 为复合主键）。"""
        self.conn.execute(
            "INSERT INTO words(key, code, weight, category, grp, enabled) "
            "VALUES(?,?,?,?,?,?) ON CONFLICT(key, code) DO UPDATE SET "
            "weight=excluded.weight, category=excluded.category, "
            "grp=excluded.grp, enabled=excluded.enabled",
            (rec.词组, rec.编码, rec.权重, rec.分类, rec.分组, 1 if rec.启用 else 0),
        )
        self.conn.commit()

    def delete_by_key(self, key: str) -> None:
        """按词组删除（删除该词组所有编码记录）。"""
        self.conn.execute("DELETE FROM words WHERE key=?", (key,))
        self.conn.commit()

    def delete_by_key_and_code(self, key: str, code: str) -> None:
        """按 词组+编码 精确删除一行。"""
        self.conn.execute("DELETE FROM words WHERE key=? AND code=?", (key, code))
        self.conn.commit()

    def delete_by_filter(self, group: str = "", category: str = "", enabled: str = "") -> int:
        """按条件批量删除，返回删除条数。"""
        sql = "DELETE FROM words WHERE 1=1"
        args: List = []
        if group:
            sql += " AND (grp = ? OR grp LIKE ?)"; args.append(group); args.append(f"{group}/%")
        if category:
            sql += " AND category = ?"; args.append(category)
        if enabled in ("1", "0"):
            sql += " AND enabled = ?"; args.append(int(enabled))
        cur = self.conn.execute(sql, args)
        self.conn.commit()
        return cur.rowcount

    def batch_update(self, group: str = "", category: str = "", enabled: str = "",
                     new_group: str = "", new_category: str = "", new_enabled: bool = None,
                     new_weight: int = None, new_code: str = "") -> int:
        """按条件批量更新，返回更新条数。"""
        sql = "UPDATE words SET "
        sets: List[str] = []
        args: List = []
        if new_group:
            sets.append("grp = ?"); args.append(new_group)
        if new_category:
            sets.append("category = ?"); args.append(new_category)
        if new_enabled is not None:
            sets.append("enabled = ?"); args.append(1 if new_enabled else 0)
        if new_weight is not None:
            sets.append("weight = ?"); args.append(new_weight)
        if new_code:
            sets.append("code = ?"); args.append(new_code)
        if not sets:
            return 0
        sql += ", ".join(sets) + " WHERE 1=1"
        if group:
            sql += " AND (grp = ? OR grp LIKE ?)"; args.append(group); args.append(f"{group}/%")
        if category:
            sql += " AND category = ?"; args.append(category)
        if enabled in ("1", "0"):
            sql += " AND enabled = ?"; args.append(int(enabled))
        cur = self.conn.execute(sql, args)
        self.conn.commit()
        return cur.rowcount

    def count_by_filter(self, group: str = "", category: str = "", enabled: str = "") -> int:
        """按条件统计记录数。"""
        sql = "SELECT COUNT(*) FROM words WHERE 1=1"
        args: List = []
        if group:
            sql += " AND (grp = ? OR grp LIKE ?)"; args.append(group); args.append(f"{group}/%")
        if category:
            sql += " AND category = ?"; args.append(category)
        if enabled in ("1", "0"):
            sql += " AND enabled = ?"; args.append(int(enabled))
        return self.conn.execute(sql, args).fetchone()[0]

    def delete_row(self, key: str, code: str) -> None:
        """按 词组+编码 精确删除一行。"""
        self.conn.execute("DELETE FROM words WHERE key=? AND code=?", (key, code))
        self.conn.commit()

    def delete_by_keys(self, keys: List[str]) -> int:
        """批量按词组删除，返回删除条数。"""
        if not keys:
            return 0
        self.conn.executemany("DELETE FROM words WHERE key=?", [(k,) for k in keys])
        self.conn.commit()
        return len(keys)

    def import_replace(self, recs: List[WordRecord]) -> None:
        """用给定记录集整体替换（先清空再插入）。"""
        self.conn.execute("DELETE FROM words")
        self.conn.executemany(
            "INSERT INTO words(key,code,weight,category,grp,enabled) VALUES(?,?,?,?,?,?)",
            [r.as_tuple() for r in recs],
        )
        self.conn.commit()

    # ---------- 读 ----------
    def get_all(self) -> List[WordRecord]:
        cur = self.conn.execute("SELECT key,code,weight,category,grp,enabled FROM words")
        return [WordRecord.from_row(r) for r in cur.fetchall()]

    def get_by_key(self, key: str) -> Optional[WordRecord]:
        cur = self.conn.execute(
            "SELECT key,code,weight,category,grp,enabled FROM words WHERE key=?", (key,)
        )
        row = cur.fetchone()
        return WordRecord.from_row(row) if row else None

    def get_by_key_and_code(self, key: str, code: str) -> Optional[WordRecord]:
        """按 词组+编码 精确查询（复合主键）。"""
        cur = self.conn.execute(
            "SELECT key,code,weight,category,grp,enabled FROM words WHERE key=? AND code=?", (key, code)
        )
        row = cur.fetchone()
        return WordRecord.from_row(row) if row else None

    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM words").fetchone()[0]

    def count_fast(self) -> int:
        """快速估算记录数（从 sqlite_stat1 读取，可能略过期）。"""
        try:
            cur = self.conn.execute("SELECT stat FROM sqlite_stat1 WHERE tbl='words' AND idx IS NOT NULL")
            row = cur.fetchone()
            if row:
                return int(row[0].split()[0])
        except Exception:
            pass
        return self.count()

    # ---------- 分组聚合（左栏树）----------
    def group_tree(self) -> Dict[str, int]:
        """返回 {分组path: 该组及子孙组的记录数}。使用 GROUP BY 加速。"""
        result: Dict[str, int] = {}
        cur = self.conn.execute("SELECT grp, COUNT(*) FROM words GROUP BY grp")
        for grp, cnt in cur.fetchall():
            p = grp or ""
            if not p:
                result[""] = result.get("", 0) + cnt
                continue
            parts = p.split(GROUP_SEP)
            for i in range(1, len(parts) + 1):
                prefix = GROUP_SEP.join(parts[:i])
                result[prefix] = result.get(prefix, 0) + cnt
        return result

    # ---------- 叠加筛选 ----------
    def query(
        self,
        key: str = "",
        code: str = "",
        weight: str = "",
        category: str = "",
        group: str = "",
        enabled: str = "",
        length_bucket: str = "",
        only_multi_code: bool = False,
        only_duplicate: bool = False,
        only_missing: bool = False,
        limit: int = 0,
        offset: int = 0,
    ) -> List[WordRecord]:
        """按非空条件 AND 筛选。"""
        sql = "SELECT key,code,weight,category,grp,enabled FROM words WHERE 1=1"
        args: List = []

        if key:
            sql += " AND key LIKE ?"; args.append(f"%{key}%")
        if code:
            sql += " AND code LIKE ?"; args.append(f"%{code}%")
        if weight:
            sql += " AND weight = ?"; args.append(int(weight))
        if category:
            sql += " AND category = ?"; args.append(category)
        if group:
            sql += " AND (grp = ? OR grp LIKE ?)"; args.append(group); args.append(f"{group}/%")
        if enabled in ("1", "0"):
            sql += " AND enabled = ?"; args.append(int(enabled))
        if length_bucket:
            if length_bucket == "无":
                sql += " AND length(key)=0"
            elif length_bucket == "多":
                sql += " AND length(key)>=5"
            else:
                n = "一二三四".index(length_bucket) + 1
                sql += f" AND length(key)={n}"
        if only_missing:
            sql += " AND (category IS NULL OR category='' OR grp IS NULL OR grp='')"

        # 按词组字数升序 → 编码字母升序 → 权重降序
        sql += " ORDER BY length(key) ASC, code ASC, weight DESC"

        if limit > 0:
            sql += f" LIMIT {limit}"
        if offset > 0:
            sql += f" OFFSET {offset}"

        cur = self.conn.execute(sql, args)
        recs = [WordRecord.from_row(r) for r in cur.fetchall()]

        if only_multi_code:
            seen: Dict[str, set] = {}
            for r in recs:
                seen.setdefault(r.词组, set()).add(r.编码)
            multi = {k for k, v in seen.items() if len(v) >= 2}
            recs = [r for r in recs if r.词组 in multi]

        if only_duplicate:
            seen = set()
            dups = set()
            for r in recs:
                sig = (r.词组, r.编码)
                if sig in seen:
                    dups.add(sig)
                seen.add(sig)
            recs = [r for r in recs if (r.词组, r.编码) in dups]

        return recs

    def duplicate_groups(self) -> List[List[WordRecord]]:
        """返回 词组+编码 相同的冗余组（每组 >=2 条）。"""
        cur = self.conn.execute(
            "SELECT key,code,weight,category,grp,enabled FROM words ORDER BY key,code"
        )
        all_recs = [WordRecord.from_row(r) for r in cur.fetchall()]
        groups: Dict[tuple, List[WordRecord]] = {}
        for r in all_recs:
            groups.setdefault((r.词组, r.编码), []).append(r)
        return [g for g in groups.values() if len(g) >= 2]

    def merge_duplicates(self) -> int:
        """每组(词组+编码相同)保留权重最大的一条，删其余。返回删除条数。"""
        # 使用 SQL 直接删除，避免一次性加载全部记录到内存
        cur = self.conn.execute("""
            SELECT key, code, weight FROM words
            WHERE (key, code) IN (
                SELECT key, code FROM words GROUP BY key, code HAVING COUNT(*) >= 2
            )
            ORDER BY key, code, weight DESC
        """)
        rows = cur.fetchall()
        # 每组保留第一条（权重最大），删除其余
        seen = set()
        removed = 0
        for key, code, weight in rows:
            sig = (key, code)
            if sig in seen:
                self.conn.execute("DELETE FROM words WHERE key=? AND code=? AND weight=?", (key, code, weight))
                removed += 1
            else:
                seen.add(sig)
        self.conn.commit()
        return removed
