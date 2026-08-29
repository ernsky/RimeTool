"""新建编码对话框：选规则 + 输入词组（单条/批量）+ 预览 + 入库。"""

from __future__ import annotations

import os
from typing import Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLineEdit, QComboBox, QPushButton, QTextEdit, QTableWidget,
    QTableWidgetItem, QHeaderView, QMessageBox, QCheckBox, QLabel,
)

from ..core.models import WordRecord, CATEGORY_CHOICES
from ..core import wubi
from ..ui.builders.toolbar_builder import GroupCombo


class NewCodeDialog(QDialog):
    """新建编码弹窗：规则 + 词组 + 预览 + 保存。"""

    def __init__(self, parent, monitor, config: Dict[str, object]) -> None:
        super().__init__(parent)
        self.monitor = monitor
        self.config = config
        self.project_root = os.path.normpath(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        )

        self.setWindowTitle("新建编码")
        self.resize(520, 560)
        self.setAttribute(Qt.WA_StyledBackground, True)

        # 图标
        icon_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "resources", "app_icon.ico"
        )
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        # ① 编码规则
        self.rule_combo = QComboBox()
        for rid, name in wubi.RULE_NAMES.items():
            self.rule_combo.addItem(name, rid)
        self.rule_combo.currentIndexChanged.connect(self._on_rule_changed)

        # ② 词组输入
        self.phrase_edit = QTextEdit()
        self.phrase_edit.setPlaceholderText("输入词组，每行一个；或粘贴多行批量")
        self.phrase_edit.setMinimumHeight(56)
        self.phrase_edit.setMaximumHeight(56)
        self.phrase_edit.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        # ③ 自由编码（仅规则5，多行）
        self.free_edit = QTextEdit()
        self.free_edit.setPlaceholderText("仅规则5自由编码时填写，每行一个编码")
        self.free_edit.setMinimumHeight(56)
        self.free_edit.setMaximumHeight(56)
        self.free_edit.setEnabled(False)
        self.free_edit.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        # ④ 分类 / 分组 / 启用
        row_extra = QHBoxLayout()
        row_extra.setSpacing(8)

        self.cat_combo = QComboBox()
        self.cat_combo.addItems([""] + CATEGORY_CHOICES)
        self.cat_combo.setMinimumWidth(90)
        self.cat_combo.setCurrentText(self.monitor.in_category.currentText())

        self.group_combo = GroupCombo()
        self.group_combo.setMinimumWidth(120)
        # 填充分组下拉项
        self.group_combo.addItem("", "")
        for p in sorted(self.monitor.ds.group_tree().keys()):
            if p:
                depth = p.count("/")
                last = p.split("/")[-1]
                self.group_combo.addItem("    " * depth + last, p)
        cur = self.monitor.in_group.full_path()
        if cur:
            self.group_combo.set_path(cur)

        self.chk_enabled = QCheckBox("启用")
        self.chk_enabled.setChecked(self.monitor.in_enabled.isChecked())

        row_extra.addWidget(QLabel("分类:"))
        row_extra.addWidget(self.cat_combo)
        row_extra.addWidget(QLabel("分组:"))
        row_extra.addWidget(self.group_combo)
        row_extra.addStretch(1)
        row_extra.addWidget(self.chk_enabled)

        # ⑤ 预览表格（与主表样式一致，6 列）
        self.preview_table = QTableWidget(0, 6)
        self.preview_table.setHorizontalHeaderLabels(["词组", "编码", "权重", "分类", "分组", "状态"])
        self.preview_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.preview_table.setColumnWidth(0, 80)
        for col in range(1, 6):
            self.preview_table.horizontalHeader().setSectionResizeMode(col, QHeaderView.Stretch)
        self.preview_table.setMinimumHeight(150)
        self.preview_table.setMaximumHeight(300)
        self.preview_table.verticalHeader().setDefaultSectionSize(28)
        self.preview_table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        btn_preview = QPushButton("预览")
        btn_preview.setFixedHeight(28)
        btn_preview.clicked.connect(self._refresh_preview)

        # ⑥ 操作按钮
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        btn_cancel = QPushButton("取消")
        btn_save = QPushButton("生成并保存")
        btn_cancel.clicked.connect(self.reject)
        btn_save.clicked.connect(self._on_save)
        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(btn_save)

        # 组装
        fl = QFormLayout()
        fl.setSpacing(8)
        fl.addRow("编码规则:", self.rule_combo)
        fl.addRow("词组输入:", self.phrase_edit)
        fl.addRow("自由编码:", self.free_edit)

        root.addLayout(fl)
        root.addLayout(row_extra)
        root.addWidget(QLabel("预览:"))
        root.addWidget(self.preview_table)
        root.addWidget(btn_preview)
        root.addLayout(btn_row)

    # ---------------- 数据 ----------------
    def _resolve(self, p: str) -> str:
        p = (p or "").strip()
        if not p:
            return ""
        if os.path.isabs(p):
            return os.path.normpath(p)
        return os.path.normpath(os.path.join(self.project_root, p))

    def _get_char_codes(self) -> Dict[str, str]:
        char_table = self.config.get("wubi_char_table", "") or self._find_ref_char_table()
        return wubi.read_single_char_codes(self._resolve(char_table) if char_table else "")

    def _find_ref_char_table(self) -> str:
        d = self.config.get("newcode_ref_dir", "")
        if not d:
            return ""
        d = self._resolve(d)
        if not os.path.isdir(d):
            return ""
        for name in sorted(os.listdir(d)):
            if name.endswith(".txt") or name.endswith(".dict.yaml"):
                return os.path.join(d, name)
        return ""

    def _read_weight_table(self) -> Dict[str, int]:
        p = self._resolve(self.config.get("weight_table", "data/weight.txt"))
        table: Dict[str, int] = {}
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                for ln in f:
                    ln = ln.strip()
                    if not ln:
                        continue
                    parts = ln.split("\t")
                    if len(parts) >= 2 and parts[1].strip().isdigit():
                        table[parts[0].strip()] = int(parts[1].strip())
        return table

    # ---------------- 事件 ----------------
    def _on_rule_changed(self, idx: int) -> None:
        rule = self.rule_combo.currentData()
        self.free_edit.setEnabled(rule == 5)

    def _refresh_preview(self) -> None:
        rule = self.rule_combo.currentData()
        free_code = self.free_edit.toPlainText().strip()
        if rule == 5 and not wubi.validate_code(free_code):
            QMessageBox.warning(self, "错误", f"自由编码无效：{free_code}")
            return
        char_codes = self._get_char_codes()
        weights = self._read_weight_table()
        group_path = self.group_combo.full_path()
        lines = [l.strip() for l in self.phrase_edit.toPlainText().splitlines() if l.strip()]
        self.preview_table.setRowCount(0)
        for phrase in lines:
            if rule == 5:
                code = free_code
            else:
                code = wubi.generate(phrase, char_codes, rule)
            weight = weights.get(phrase, 1)
            row = self.preview_table.rowCount()
            self.preview_table.insertRow(row)
            self.preview_table.setItem(row, 0, QTableWidgetItem(phrase))
            self.preview_table.setItem(row, 1, QTableWidgetItem(code))
            self.preview_table.setItem(row, 2, QTableWidgetItem(str(weight)))
            self.preview_table.setItem(row, 3, QTableWidgetItem(self.cat_combo.currentText()))
            self.preview_table.setItem(row, 4, QTableWidgetItem(group_path))
            self.preview_table.setItem(row, 5, QTableWidgetItem("✓"))

    def _on_save(self) -> None:
        rule = self.rule_combo.currentData()
        free_code = self.free_edit.toPlainText().strip()
        if rule == 5 and not wubi.validate_code(free_code):
            QMessageBox.warning(self, "错误", f"自由编码无效：{free_code}")
            return
        char_codes = self._get_char_codes()
        weights = self._read_weight_table()
        lines = [l.strip() for l in self.phrase_edit.toPlainText().splitlines() if l.strip()]
        if not lines:
            QMessageBox.warning(self, "提示", "请输入至少一个词组。")
            return
        category = self.cat_combo.currentText()
        group_path = self.group_combo.full_path()
        enabled = self.chk_enabled.isChecked()
        added = 0
        for phrase in lines:
            if rule == 5:
                code = free_code
            else:
                code = wubi.generate(phrase, char_codes, rule)
            rec = WordRecord(
                key=phrase, code=code,
                weight=weights.get(phrase, 1),
                category=category,
                group=group_path.strip("/"),
                enabled=enabled,
            )
            self.monitor.ds.upsert(rec)
            added += 1
        self.monitor.refresh_all()
        self.monitor._set_status(f"新建编码完成，已添加 {added} 条")
        QMessageBox.information(self, "新建编码", f"已添加 {added} 条。")
        self.accept()
