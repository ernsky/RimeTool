"""数据源抽象：隔离数据访问与 UI。当前实现为 SQLite。"""

from __future__ import annotations

from typing import List

from ..core.models import WordRecord
from ..core.repository import Repository


class DataSource:
    """对 Repository 的轻量封装，便于将来替换为其它后端。"""

    def __init__(self, repo: Repository) -> None:
        self.repo = repo
        # 缓存分组树，避免重复查询
        self._group_tree_cache = None

    def all(self) -> List[WordRecord]:
        return self.repo.get_all()

    def upsert(self, rec: WordRecord) -> None:
        self.repo.upsert(rec)
        self._group_tree_cache = None  # 失效缓存

    def delete(self, key: str) -> None:
        self.repo.delete_by_key(key)
        self._group_tree_cache = None

    def delete_by_key_and_code(self, key: str, code: str) -> None:
        """按 词组+编码 精确删除一行。"""
        self.repo.delete_by_key_and_code(key, code)
        self._group_tree_cache = None

    def delete_by_filter(self, group: str = "", category: str = "", enabled: str = "") -> int:
        """按条件批量删除，返回删除条数。"""
        count = self.repo.delete_by_filter(group=group, category=category, enabled=enabled)
        self._group_tree_cache = None
        return count

    def batch_update(self, group: str = "", category: str = "", enabled: str = "",
                     new_group: str = "", new_category: str = "", new_enabled: bool = None,
                     new_weight: int = None, new_code: str = "") -> int:
        """按条件批量更新，返回更新条数。"""
        count = self.repo.batch_update(group=group, category=category, enabled=enabled,
                                       new_group=new_group, new_category=new_category,
                                       new_enabled=new_enabled, new_weight=new_weight,
                                       new_code=new_code)
        self._group_tree_cache = None
        return count

    def count_by_filter(self, group: str = "", category: str = "", enabled: str = "") -> int:
        """按条件统计记录数。"""
        return self.repo.count_by_filter(group=group, category=category, enabled=enabled)

    def query(self, **kwargs) -> List[WordRecord]:
        return self.repo.query(**kwargs)

    def count(self) -> int:
        return self.repo.count()

    def group_tree(self) -> dict:
        """带缓存的分组树（返回副本，避免外部修改内部缓存）。"""
        if self._group_tree_cache is None:
            self._group_tree_cache = self.repo.group_tree()
        return self._group_tree_cache.copy()

    def group_tree_l1(self) -> List[str]:
        """一级分组（树根）名称列表。"""
        paths = [p for p in self.group_tree().keys() if p]
        return sorted({p.split("/", 1)[0] for p in paths})

    def distinct_group_levels(self, parent_path: str = "") -> List[str]:
        """给定父路径，返回其直接子级名称集合（去重）。"""
        paths = [p for p in self.group_tree().keys() if p]
        out = set()
        for p in paths:
            parts = p.split("/")
            if parent_path == "":
                if len(parts) >= 1:
                    out.add(parts[0])
            else:
                pp = parent_path.split("/")
                if p.startswith(parent_path + "/") and len(parts) == len(pp) + 1:
                    out.add(parts[-1])
        return sorted(out)

    def invalidate_cache(self) -> None:
        """手动失效缓存。"""
        self._group_tree_cache = None

    def close(self) -> None:
        self.repo.close()
