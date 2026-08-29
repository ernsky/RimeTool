"""顶部工具栏 builder：配置 / 部署 / 保存 + 六输入框(无标签,placeholder提示) + 搜索 / 删除 / 交换权重。

分组输入框为单个下拉框（项文本带层级缩进、框内仅显示最后一级）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QLabel, QLineEdit, QSpinBox, QComboBox, QPushButton, QCheckBox,
    QAbstractSpinBox, QWidget, QHBoxLayout, QSizePolicy,
)
from PySide6.QtCore import Qt

from design_system import style_toolbar

if TYPE_CHECKING:
    from ...app import RimeDictApp

GROUP_SEP = "/"


class GroupCombo(QComboBox):
    """分组下拉（单框）：项文本带层级缩进，userData 存完整 path，框内仅显示最后一级。"""

    INDENT = "    "

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.InsertAtBottom)
        self.setMinimumWidth(120)
        self.setFixedHeight(28)
        # 下拉三角已被 QSS 隐藏，点击文本区也要能展开下拉
        self.lineEdit().installEventFilter(self)

    def eventFilter(self, obj, event) -> bool:
        from PySide6.QtCore import QEvent
        if obj is self.lineEdit() and event.type() == QEvent.MouseButtonPress:
            self.showPopup()
            return True
        return super().eventFilter(obj, event)

    def full_path(self) -> str:
        idx = self.currentIndex()
        text = self.currentText().strip()
        if idx < 0:
            # 用户手动输入的值
            return text
        # 检查当前文本是否与 itemData 匹配
        data = self.itemData(idx)
        if data and text == data:
            return data
        # 文本被修改了，返回文本本身
        return text

    def last_level(self) -> str:
        t = self.currentText().strip()
        return t

    def set_path(self, path: str) -> None:
        """回填：找到 userData == path 的项并选中（框内显示末级）。"""
        self.blockSignals(True)
        try:
            for i in range(self.count()):
                if (self.itemData(i) or "") == path:
                    self.setCurrentIndex(i)
                    return
            # 如果找不到，添加新项并选中
            self.addItem(path, path)
            self.setCurrentIndex(self.count() - 1)
        finally:
            self.blockSignals(False)


class ToolbarBuilder:
    """构建顶部工具栏并暴露控件引用到 app。"""

    @staticmethod
    def build(monitor: "RimeDictApp") -> QWidget:
        bar = QWidget()
        bar.setObjectName("TopBar")
        tb = QHBoxLayout(bar)
        tb.setContentsMargins(8, 3, 8, 3)   # 上下仅 3px，避免顶栏过高
        tb.setSpacing(8)

        def _sep() -> QWidget:
            s = QWidget(); s.setFixedSize(1, 22)
            s.setObjectName("TopBarSeparator")
            return s

        # 动作按钮（左）
        monitor.btn_config = QPushButton("配置")
        monitor.btn_config.setToolTip("打开设置：Rime 目录、备份、单字编码表、主题")
        monitor.btn_deploy = QPushButton("部署")
        monitor.btn_deploy.setToolTip("将启用记录导出到 Rime 并触发重新部署")
        monitor.btn_save = QPushButton("保存")
        monitor.btn_save.setToolTip("将当前六输入框内容写入数据库（词组为空则为新增）")
        for b in (monitor.btn_config, monitor.btn_deploy, monitor.btn_save):
            b.setFixedHeight(28)   # 与输入框等高
            tb.addWidget(b)
        tb.addWidget(_sep())

        # 六输入框（无标签，placeholder 提示）：统一固定高 28
        monitor.in_key = QLineEdit(); monitor.in_key.setPlaceholderText("词组")
        monitor.in_key.setMinimumWidth(110)   # 词组列：最小宽，窗口拉大时随 spacer 拉伸
        monitor.in_key.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        monitor.in_key.setToolTip("词组（主键，唯一）；选中列表中行会回填此处")
        monitor.in_code = QLineEdit(); monitor.in_code.setPlaceholderText("编码")
        monitor.in_code.setToolTip("五笔编码（纯英文小写）；自动生成或手填")
        monitor.in_weight = QSpinBox()
        monitor.in_weight.setRange(1, 999999)
        monitor.in_weight.setValue(1)
        monitor.in_weight.setButtonSymbols(QAbstractSpinBox.NoButtons)  # 权重无上下键
        monitor.in_weight.setMinimumWidth(80)    # 权重列：交换后更窄
        monitor.in_weight.setToolTip("权重（正整数，默认1，越大候选越靠前）")
        monitor.in_category = QComboBox(); monitor.in_category.addItems([""] + monitor.CATEGORY_CHOICES)
        monitor.in_category.setMinimumWidth(90)   # 分类框固定宽度，避免下拉项被裁成 ...
        monitor.in_category.setFixedHeight(28)
        monitor.in_category.setToolTip("分类：单字/常用/用户/多码/英语/符号")

        monitor.in_group = GroupCombo()
        monitor.in_group.setToolTip("分组（层级用 / 分隔，框内仅显示最后一级）")

        monitor.in_enabled = QCheckBox("启用"); monitor.in_enabled.setChecked(True)
        monitor.in_enabled.setToolTip("是否启用：导出到 Rime 时仅导出启用=是的记录")

        # 统一固定高度（不再依赖 QSS min-height）
        for w in (monitor.in_key, monitor.in_code, monitor.in_weight,
                  monitor.in_category, monitor.in_group, monitor.in_enabled):
            w.setFixedHeight(28)

        # 需求：窗口放大时输入框按比例放大，按钮保持原宽不变。
        # 做法：输入框统一 Expanding 水平策略，并按"基数宽度"分配 stretch 权重，
        # 自由空间按权重比例分给他们；按钮/分隔条不设 stretch，宽度恒定。
        for w in (monitor.in_key, monitor.in_code, monitor.in_weight,
                  monitor.in_category, monitor.in_group):
            w.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        tb.addWidget(monitor.in_key, 4)        # 词组（基数最大）
        tb.addWidget(monitor.in_code, 3)       # 编码
        tb.addWidget(monitor.in_weight, 2)     # 权重（基数最小）
        tb.addWidget(monitor.in_category, 3)   # 分类
        tb.addWidget(monitor.in_group, 4)      # 分组
        tb.addWidget(monitor.in_enabled)        # 启用（勾选框，固定宽）
        tb.addWidget(_sep())

        # 右侧动作（搜索 / 删除 / 交换权重）：固定宽，不随窗口拉伸
        monitor.btn_search = QPushButton("搜索")
        monitor.btn_search.setToolTip("按六输入框中已填字段（空字段忽略）进行 AND 筛选")
        monitor.btn_delete = QPushButton("删除")
        monitor.btn_delete.setObjectName("DangerButton")
        monitor.btn_delete.setToolTip("删除中栏当前选中的行（危险操作）")
        monitor.btn_swap = QPushButton("交换权重")
        monitor.btn_swap.setToolTip("交换中栏选中的两行的权重值")
        for b in (monitor.btn_search, monitor.btn_delete, monitor.btn_swap):
            b.setFixedHeight(28)   # 与输入框等高
            tb.addWidget(b)

        bar.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        return bar

    @staticmethod
    def fill_group_combo(monitor: "RimeDictApp") -> None:
        """填充分组下拉：项文本=层级缩进+末级（下拉逐级缩进），userData=完整 path。"""
        combo = monitor.in_group
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("", "")
        paths = [p for p in monitor.ds.group_tree().keys() if p]
        for p in sorted(set(paths)):
            depth = p.count(GROUP_SEP)
            last = p.split(GROUP_SEP)[-1]
            combo.addItem(GroupCombo.INDENT * depth + last, p)
        combo.blockSignals(False)
