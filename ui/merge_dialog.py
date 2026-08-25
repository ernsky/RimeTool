# -*- coding: utf-8 -*-
"""重复词条合并对话框（模态）：显示重复组数量，选择合并策略并执行。

- key = (词组, 编码)，不同编码视为不同词条，绝不被误并。
- 保留每组首次出现的一行，其余冗余行删除；词频按“最高”或“相加”合并到保留行。
- 数据算法走 core.dict_model.merge_duplicates，本类只负责展示与策略选择。
"""
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QRadioButton,
    QPushButton, QButtonGroup, QMessageBox,
)
from ui.msgbox import info, warning, critical

from ui.config_dialog import apply_dark_title


def _set_btn_class(btn, cls):
    """设置按钮动态 class 属性并刷新样式（让 style.qss 的 [class=...] 选择器生效）。"""
    btn.setProperty("class", cls)
    btn.style().unpolish(btn)
    btn.style().polish(btn)


class MergeDialog(QDialog):
    def __init__(self, parent, model):
        super().__init__(parent)
        self._model = model
        self._groups = model.find_duplicate_groups()

        self.setWindowTitle("重复词条合并")
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self._build_ui()
        # 原生标题栏随主题配色（浅=深蓝底白字 / 深=#1C1F24 底白字）
        _cfg = getattr(parent, "_config", None) or {}
        apply_dark_title(self, _cfg.get("theme", "auto"))

    def _build_ui(self):
        layout = QVBoxLayout(self)

        if not self._groups:
            layout.addWidget(QLabel("未发现重复词条（key = 词组 + 编码）。"))
            btn = QPushButton("关闭")
            btn.clicked.connect(self.reject)
            _set_btn_class(btn, "btn-red")   # 关闭按钮：红（#ef4444）
            layout.addWidget(btn)
            return

        total_rows = sum(len(v) for v in self._groups.values())
        info = QLabel(
            f"发现 {len(self._groups)} 组重复词条，涉及 {total_rows} 行。\n"
            "合并将保留每组首次出现的一行，其余冗余行删除。"
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        # 合并策略
        self.rb_max = QRadioButton("保留词频最高的一行")
        self.rb_sum = QRadioButton("词频相加（合并到保留行）")
        self.rb_max.setChecked(True)
        grp = QButtonGroup(self)
        grp.addButton(self.rb_max)
        grp.addButton(self.rb_sum)
        layout.addWidget(self.rb_max)
        layout.addWidget(self.rb_sum)

        # 操作按钮
        row = QHBoxLayout()
        btn_ok = QPushButton("执行合并")
        btn_ok.setObjectName("btnMain")
        _set_btn_class(btn_ok, "btn-green")   # 执行：绿（#10b981，确认/同意/执行语义）
        btn_cancel = QPushButton("取消")
        row.addWidget(btn_ok)
        row.addWidget(btn_cancel)
        layout.addLayout(row)

        btn_ok.clicked.connect(self.on_merge)
        btn_cancel.clicked.connect(self.reject)

    def on_merge(self):
        strategy = "sum" if self.rb_sum.isChecked() else "max_freq"
        removed = self._model.merge_duplicates(self._groups, strategy)
        # 合并已修改数据（内部置脏），刷新主窗口标题与状态栏
        viewer = self.parent()
        if hasattr(viewer, "_refresh_title"):
            viewer._refresh_title()
        if hasattr(viewer, "_update_status"):
            viewer._update_status()
        info(self, "完成", f"已合并，删除冗余行 {removed} 条。")
        self.accept()
