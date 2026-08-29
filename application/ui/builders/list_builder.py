"""中栏词组表 builder：QTableView + 自定义模型，六列显示。"""

from __future__ import annotations

from typing import TYPE_CHECKING, List

from PySide6.QtCore import Qt, QAbstractTableModel, QModelIndex
from PySide6.QtWidgets import QWidget, QVBoxLayout, QTableView, QHeaderView, QStyledItemDelegate

if TYPE_CHECKING:
    from ...app import RimeDictApp

from ...core.models import WordRecord, CATEGORY_CHOICES

COLUMNS = ["词组", "编码", "权重", "分类", "分组", "启用"]


class LeftPaddingDelegate(QStyledItemDelegate):
    """自定义 delegate：在单元格文本左侧留 2px 间距。"""

    def paint(self, painter, option, index):
        option.rect.adjust(2, 0, 0, 0)  # 左移 2px
        super().paint(painter, option, index)


class WordTableModel(QAbstractTableModel):
    """六列只读模型，承载 WordRecord 列表。"""

    def __init__(self, recs: List[WordRecord] = None) -> None:
        super().__init__()
        self.recs: List[WordRecord] = recs or []

    def set_records(self, recs: List[WordRecord]) -> None:
        self.beginResetModel()
        self.recs = recs
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self.recs)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return COLUMNS[section]
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        if role == Qt.TextAlignmentRole:
            return Qt.AlignLeft | Qt.AlignVCenter
        if role != Qt.DisplayRole:
            return None
        r = self.recs[index.row()]
        col = index.column()
        if col == 0:
            return r.词组
        if col == 1:
            return r.编码
        if col == 2:
            return r.权重
        if col == 3:
            return r.分类
        if col == 4:
            return r.分组
        if col == 5:
            return "是" if r.启用 else "否"
        return None


class WordTableView(QTableView):
    """中栏词组表：词组列随窗口拉伸，其余五列固定宽（由 caller 设置）。"""

    def __init__(self) -> None:
        super().__init__()
        self._fixed_cols = (1, 2, 3, 4, 5)

    def _fixed_total(self) -> int:
        return sum(self.columnWidth(c) for c in self._fixed_cols)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.model() is None:
            return
        avail = self.viewport().width()
        fixed = self._fixed_total()
        w0 = max(60, avail - fixed)
        self.setColumnWidth(0, w0)


class ListBuilder:
    """构建中栏词组表。"""

    @staticmethod
    def build(monitor: "RimeDictApp") -> QTableView:
        table = WordTableView()
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QTableView.SelectRows)
        # 隐藏左右（横向）滚动条
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # 设置 delegate 实现左间距
        table.setItemDelegate(LeftPaddingDelegate(table))
        hdr = table.horizontalHeader()
        hdr.setFixedHeight(28)   # 表头行高与内容行一致
        # 词组列(0) 随窗口拉伸；其余五列固定宽
        hdr.setStretchLastSection(False)
        hdr.setSectionResizeMode(0, QHeaderView.Interactive)
        monitor.word_model = WordTableModel([])
        table.setModel(monitor.word_model)
        # 固定列宽：分组列加宽 1/3（75→100），相应从词组列（可拉伸）扣减
        _FIXED = {1: 53, 2: 45, 3: 53, 4: 100, 5: 38}
        for col, w in _FIXED.items():
            hdr.setSectionResizeMode(col, QHeaderView.Fixed)
            table.setColumnWidth(col, w)
        table.clicked.connect(monitor.on_row_selected)
        monitor.word_table = table
        return table

    @staticmethod
    def refresh(monitor: "RimeDictApp", recs: List[WordRecord]) -> None:
        monitor.word_model.set_records(recs)
        # 大数据量时避免逐行 setRowHeight（162 万行会卡死），用默认行高一次性设置
        monitor.word_table.verticalHeader().setDefaultSectionSize(28)
