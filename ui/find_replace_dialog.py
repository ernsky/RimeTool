# -*- coding: utf-8 -*-
"""查找 / 替换对话框（非模态）：Ctrl+F 弹出，悬浮在主窗口上方。

- 查找下一个：从当前命中处继续向下（到底循环回顶部），命中后定位并高亮。
- 替换：替换当前命中单元格中匹配的部分，并自动跳到下一处。
- 全部替换：作用整张 _all_data（含筛选隐藏行），返回替换处数。
数据算法全部走 core.dict_model，本类只负责控件与交互。
"""
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QComboBox, QCheckBox, QPushButton, QMessageBox,
)
from ui.msgbox import info, warning, critical

from core.config import HEADERS
from ui.config_dialog import apply_dark_title


class FindReplaceDialog(QDialog):
    def __init__(self, viewer, model):
        super().__init__(viewer)
        self._viewer = viewer
        self._model = model
        self._last = None   # (view_row, col) 最近一次命中位置

        self.setWindowTitle("查找 / 替换")
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self._build_ui()
        # 原生标题栏随主题配色（浅=深蓝底白字 / 深=#1C1F24 底白字）
        apply_dark_title(self, (viewer._config.get("theme", "auto")
                                 if hasattr(viewer, "_config") else "auto"))

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # 查找内容
        row_find = QHBoxLayout()
        row_find.addWidget(QLabel("查找:"))
        self.edit_find = QLineEdit()
        self.edit_find.setClearButtonEnabled(True)
        row_find.addWidget(self.edit_find, 1)
        layout.addLayout(row_find)

        # 替换为
        row_repl = QHBoxLayout()
        row_repl.addWidget(QLabel("替换为:"))
        self.edit_repl = QLineEdit()
        self.edit_repl.setClearButtonEnabled(True)
        row_repl.addWidget(self.edit_repl, 1)
        layout.addLayout(row_repl)

        # 范围 + 正则
        row_opt = QHBoxLayout()
        row_opt.addWidget(QLabel("范围:"))
        self.combo_col = QComboBox()
        self.combo_col.addItem("全部列")
        for h in HEADERS:
            self.combo_col.addItem(h)
        row_opt.addWidget(self.combo_col, 1)
        self.chk_regex = QCheckBox("使用正则")
        row_opt.addWidget(self.chk_regex)
        layout.addLayout(row_opt)

        # 按钮区
        row_btn = QHBoxLayout()
        self.btn_find = QPushButton("查找下一个")
        self.btn_repl = QPushButton("替换")
        self.btn_repl_all = QPushButton("全部替换")
        row_btn.addWidget(self.btn_find)
        row_btn.addWidget(self.btn_repl)
        row_btn.addWidget(self.btn_repl_all)
        layout.addLayout(row_btn)

        # 信号
        self.btn_find.clicked.connect(self.on_find_next)
        self.edit_find.returnPressed.connect(self.on_find_next)
        self.btn_repl.clicked.connect(self.on_replace)
        self.btn_repl_all.clicked.connect(self.on_replace_all)

    def _col(self):
        """当前选定列：0 号项“全部列”→ None，否则对应列索引。"""
        idx = self.combo_col.currentIndex()
        return None if idx == 0 else idx - 1

    def _needle(self):
        return self.edit_find.text()

    def on_find_next(self):
        needle = self._needle()
        if not needle:
            info(self, "提示", "请先输入查找内容")
            return
        start = 0 if self._last is None else self._last[0] + 1
        res = self._model.find_next(start, needle, self._col(), self.chk_regex.isChecked())
        if res is None:
            self._last = None
            info(self, "查找", "已查找到末尾，未找到匹配项")
            return
        view_row, col = res
        self._last = (view_row, col)
        self._model.ensure_row_loaded(view_row)
        self._viewer.select_and_show(view_row, col)

    def on_replace(self):
        needle = self._needle()
        if not needle:
            info(self, "提示", "请先输入查找内容")
            return
        if self._last is None:
            self.on_find_next()
            if self._last is None:
                return
        view_row, col = self._last
        changed = self._model.replace_cell(
            view_row, col, needle, self.edit_repl.text(), self.chk_regex.isChecked()
        )
        if not changed:
            info(self, "提示", "当前位置未发生变化")
            return
        self._model.ensure_row_loaded(view_row)
        self._viewer.select_and_show(view_row, col)
        self.on_find_next()   # 替换后自动跳到下一处

    def on_replace_all(self):
        needle = self._needle()
        if not needle:
            info(self, "提示", "请先输入查找内容")
            return
        n = self._model.replace_all(
            needle, self.edit_repl.text(), self._col(), self.chk_regex.isChecked()
        )
        self._last = None
        self._viewer._update_status()
        if n == 0:
            info(self, "全部替换", "未找到可替换的内容")
        else:
            info(self, "全部替换", f"共替换 {n} 处（含隐藏/未加载行）")
