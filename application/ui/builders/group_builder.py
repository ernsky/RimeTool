"""左栏分组树 builder：由记录的 分组 path 实时聚合生成可展开树。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Dict

from PySide6.QtWidgets import QWidget, QVBoxLayout, QTreeWidget, QTreeWidgetItem

if TYPE_CHECKING:
    from ...app import RimeDictApp

# 树节点存于 item.data(0, Qt.UserRole) 的全 path
from PySide6.QtCore import Qt
from ...core.models import CATEGORY_CHOICES


class GroupBuilder:
    """构建左栏分组树。"""

    @staticmethod
    def build(monitor: "RimeDictApp") -> QTreeWidget:
        tree = QTreeWidget()
        tree.setHeaderLabel("分组")
        tree.header().setFixedHeight(28)       # 与表格表头/内行高一致
        tree.header().setMinimumHeight(28)
        tree.header().setStretchLastSection(True)  # 标签项拉伸到全宽
        tree.setUniformRowHeights(True)
        # 分组标题向右缩进 15px
        tree.setIndentation(15)
        # 左缩进 8px：与顶栏首个按钮(配置)的左边框对齐（顶栏左 margin 同为 8px）。
        # 影响表头"分组"标签与下方各级条目的左起位置，使其与顶栏按钮左缘一致。
        tree.setContentsMargins(8, 6, 6, 6)
        monitor.group_tree = tree
        tree.itemClicked.connect(monitor.on_group_selected)
        return tree

    @staticmethod
    def refresh(monitor: "RimeDictApp") -> None:
        """根据 repository.group_tree() 重建树。"""
        tree = monitor.group_tree
        tree.clear()
        counts: Dict[str, int] = monitor.ds.group_tree()
        # 获取每个分组对应的分类（一个分组可能对应多个分类，取排序最前的）
        cat_index = {cat: i for i, cat in enumerate(CATEGORY_CHOICES)}
        # 查询每个分组的分类
        group_cat: Dict[str, str] = {}
        try:
            cur = monitor.ds.repo.conn.execute("SELECT grp, category FROM words WHERE grp != ''")
            for grp, cat in cur.fetchall():
                if grp not in group_cat or cat_index.get(cat, 99) < cat_index.get(group_cat[grp], 99):
                    group_cat[grp] = cat
        except Exception:
            pass

        def sort_key(path: str) -> tuple:
            """排序键：分类顺序 > 路径字母"""
            # 查找该路径及其所有前缀的分类
            parts = path.split("/")
            for i in range(len(parts), 0, -1):
                prefix = "/".join(parts[:i])
                if prefix in group_cat:
                    return (cat_index.get(group_cat[prefix], 99), path)
            return (99, path)

        # 建节点映射：全 path -> QTreeWidgetItem
        nodes: Dict[str, QTreeWidgetItem] = {}
        # 根节点（空分组计数）
        for path in sorted(counts.keys(), key=sort_key):
            if path == "":
                continue
            parts = path.split("/")
            parent = None
            acc = ""
            for i, part in enumerate(parts):
                acc = "/".join(parts[: i + 1])
                if acc in nodes:
                    parent = nodes[acc]
                    continue
                item = QTreeWidgetItem(parent if parent else tree)
                item.setText(0, f"{part} ({counts.get(acc, 0)})")
                item.setData(0, Qt.UserRole, acc)
                nodes[acc] = item
                parent = item
