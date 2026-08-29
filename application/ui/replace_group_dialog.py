"""替换分组对话框：选择源文件 + 设置替换分组 + 执行替换。"""

from __future__ import annotations

import os
from typing import Dict, List, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLineEdit, QComboBox, QPushButton, QFileDialog, QMessageBox, QLabel,
)

from ..core import rime_io
from ..core.replace_group import replace_group
from ..core.logger import get_logger
from ..ui.builders.toolbar_builder import GroupCombo


class ReplaceGroupDialog(QDialog):
    """替换分组弹窗：源文件 + 替换分组 + 确认/放弃。"""

    def __init__(self, parent, monitor, config: Dict[str, object]) -> None:
        super().__init__(parent)
        self.monitor = monitor
        self.config = config
        self.project_root = os.path.normpath(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        )

        self.setWindowTitle("替换分组")
        self.resize(480, 200)
        self.setAttribute(Qt.WA_StyledBackground, True)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        # ① 源文件
        self.edit_source = QLineEdit()
        self.edit_source.setPlaceholderText("选择源文件（Rime词典/词组文本）")
        # 默认源文件：Rime用户文件夹下 dict/wubi.chaos.dict.yaml
        default_source = os.path.join(self._rime_user_dir(), "dict", "wubi.chaos.dict.yaml")
        if os.path.exists(default_source):
            self.edit_source.setText(default_source)

        btn_browse = QPushButton("浏览")
        btn_browse.setFixedHeight(28)
        btn_browse.clicked.connect(self._browse_source)

        row_source = QHBoxLayout()
        row_source.setSpacing(8)
        row_source.addWidget(QLabel("源文件:"))
        row_source.addWidget(self.edit_source, 1)
        row_source.addWidget(btn_browse)

        # ② 替换分组为
        self.group_combo = GroupCombo()
        self.group_combo.setMinimumWidth(150)
        # 填充分组下拉项
        self.group_combo.addItem("", "")
        for p in sorted(self.monitor.ds.group_tree().keys()):
            if p:
                depth = p.count("/")
                last = p.split("/")[-1]
                self.group_combo.addItem("    " * depth + last, p)
        # 默认分组
        self.group_combo.set_path("青云")

        row_group = QHBoxLayout()
        row_group.setSpacing(8)
        row_group.addWidget(QLabel("替换分组为:"))
        row_group.addWidget(self.group_combo)
        row_group.addStretch(1)

        # ③ 操作按钮
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        btn_cancel = QPushButton("放弃")
        btn_ok = QPushButton("确认")
        btn_cancel.clicked.connect(self.reject)
        btn_ok.clicked.connect(self._on_ok)
        btn_row.addWidget(btn_ok)
        btn_row.addWidget(btn_cancel)

        root.addLayout(row_source)
        root.addLayout(row_group)
        root.addLayout(btn_row)

    def _rime_user_dir(self) -> str:
        d = self.config.get("rime_user_dir", "")
        if not d:
            d = os.path.expanduser("~/AppData/Roaming/Rime")
        return d

    def _browse_source(self) -> None:
        p, _ = QFileDialog.getOpenFileName(
            self, "选择源文件", "",
            "支持格式 (*.dict.yaml *.txt *.md *.scel);;所有文件 (*.*)"
        )
        if p:
            self.edit_source.setText(p)

    def _on_ok(self) -> None:
        """执行替换分组。"""
        source_path = self.edit_source.text().strip()
        if not source_path:
            QMessageBox.warning(self, "提示", "请选择源文件。")
            return

        if not os.path.exists(source_path):
            QMessageBox.warning(self, "提示", f"源文件不存在：{source_path}")
            return

        group_path = self.group_combo.full_path()
        if not group_path:
            QMessageBox.warning(self, "提示", "请设置替换分组。")
            return

        logger = get_logger("ReplaceGroup")
        logger.info("开始替换分组，文件: %s, 分组: %s", source_path, group_path)

        try:
            matched, updated, skipped = replace_group(
                self.monitor.ds.repo.conn,
                source_path,
                category="常用",
                group=group_path,
            )
            self.monitor.refresh_all()
            QMessageBox.information(
                self, "替换分组",
                f"匹配: {matched} 条\n更新: {updated} 条\n跳过: {skipped} 条"
            )
            self.monitor._set_status(f"替换分组完成，更新 {updated} 条")
            logger.info("替换分组完成，匹配 %d，更新 %d，跳过 %d", matched, updated, skipped)
            self.accept()
        except Exception as e:
            logger.error("替换分组失败: %s", e)
            QMessageBox.critical(self, "错误", f"替换分组失败：{e}")
