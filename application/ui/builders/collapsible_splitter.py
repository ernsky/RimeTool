"""可点击折叠的 QSplitter：点击分隔条手柄折叠/展开，禁止拖拽调宽。

实现：在 QSplitter 上装事件过滤器，仅响应 MouseButtonPress（命中手柄区域时
切换对应面板可见性），拦截 MouseMove 以禁用拖拽调宽。
折叠前记录尺寸，展开时恢复，避免 StretchFactor 分配失衡。
不重写 createHandle，规避子类化 handle 在某些平台下的崩溃。
"""

from __future__ import annotations

from typing import Dict

from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtWidgets import QSplitter


class CollapsibleSplitter(QSplitter):
    def __init__(self, orientation: Qt.Orientation = Qt.Horizontal, parent=None) -> None:
        super().__init__(orientation, parent)
        self.installEventFilter(self)
        # 记录折叠前的尺寸，展开时恢复，避免尺寸失衡
        self._collapsed_sizes: Dict[int, list] = {}

    def _handle_index_at(self, pos: QPoint) -> int:
        """返回鼠标位置落在哪个手柄上（手柄处于 widget(i-1) 与 widget(i) 之间）。"""
        for i in range(1, self.count()):
            h = self.handle(i)
            if h is not None and h.geometry().contains(pos):
                return i
        return 0

    def eventFilter(self, obj, event) -> bool:
        if obj is not self:
            return super().eventFilter(obj, event)
        etype = event.type()
        # 仅在手柄区域内拦截 MouseMove（拖拽调宽），其它区域正常响应
        if etype == QEvent.MouseMove:
            idx = self._handle_index_at(event.pos())
            if idx > 0:
                return True
            return False
        # 点击手柄 → 折叠/展开对应面板
        if etype == QEvent.MouseButtonPress:
            idx = self._handle_index_at(event.pos())
            if idx > 0:
                self.toggle_panel(idx)
                return True
        return super().eventFilter(obj, event)

    def toggle_panel(self, handle_index: int) -> None:
        count = self.count()
        if handle_index >= count:
            target = count - 1
        elif handle_index <= 1:
            target = 0
        else:
            target = handle_index
        widget = self.widget(target)
        if widget is None:
            return
        if widget.isVisible():
            # 折叠前记录当前所有尺寸
            self._collapsed_sizes[target] = self.sizes()
            widget.setVisible(False)
        else:
            # 展开时恢复折叠前的尺寸，避免 StretchFactor 分配失衡
            prev = self._collapsed_sizes.get(target)
            if prev is not None and len(prev) == count:
                self.setSizes(prev)
            widget.setVisible(True)
