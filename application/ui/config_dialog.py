"""配置对话框：半屏弹窗，7 项路径/外观设置，样式与主窗体一致。

尺寸：宽高各为主窗体的一半。
样式：内部容器借用对象名 "TopBar"，直接复用 design_system.THEME_QSS 中
      #TopBar 的输入框/按钮/标签规则，使字体、字号、颜色、背景与主窗体顶栏
      完全一致。
路径显示：项目内文件 → 显示相对路径；项目外文件 → 显示绝对路径。
"""

from __future__ import annotations

import json
import os
from typing import Dict

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLineEdit, QComboBox, QPushButton, QFileDialog, QMessageBox, QLabel,
)


class ConfigDialog(QDialog):
    """配置弹窗：数据库 / Rime 用户目录 / 外观 / 语音词组 / 输出 / 参考目录 / 备份。"""

    # (标签, 配置键, 选择器类型)
    ROWS = [
        ("数据库位置", "db_path", "file_db"),
        ("Rime 用户配置文件夹", "rime_user_dir", "dir"),
        ("语音词组文件", "voice_word_file", "file_any"),
        ("默认输出文件夹（导出位置）", "export_dir", "dir"),
        ("新建编码参考目录", "newcode_ref_dir", "dir"),
        ("备份文件位置", "backup_dir", "dir"),
        ("日志目录", "log_dir", "dir"),
        ("部署器路径", "rime_deployer_path", "file_any"),
    ]

    def __init__(self, parent, config: Dict[str, object], config_path: str,
                 on_theme_changed=None) -> None:
        super().__init__(parent)
        self.config = config
        self.config_path = config_path
        self._old_db = config.get("db_path", "")
        self._on_theme_changed = on_theme_changed

        # 项目根目录（application/ui/ → 上溯两级）
        self.project_root = os.path.normpath(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        )

        self.setWindowTitle("配置")
        self.setAttribute(Qt.WA_StyledBackground, True)

        container = QWidget()
        container.setObjectName("ConfigPanel")
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(container)

        fl = QFormLayout(container)
        fl.setContentsMargins(16, 16, 16, 16)
        fl.setSpacing(10)
        fl.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        self._edits: Dict[str, QLineEdit] = {}
        for label, key, kind in self.ROWS:
            self._add_path_row(fl, label, key, kind)

        # 外观选择
        self.theme_combo = QComboBox()
        self.theme_combo.addItem("深色", "dark")
        self.theme_combo.addItem("浅色", "light")
        idx = self.theme_combo.findData(config.get("theme", "dark"))
        self.theme_combo.setCurrentIndex(idx if idx >= 0 else 0)
        fl.addRow("外观", self.theme_combo)

        # 操作按钮
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        btn_cancel = QPushButton("取消")
        btn_save = QPushButton("保存")
        btn_cancel.clicked.connect(self.reject)
        btn_save.clicked.connect(self._on_save)
        btn_row.addWidget(btn_save)
        btn_row.addWidget(btn_cancel)
        fl.addRow(btn_row)

        if parent is not None:
            self.resize(parent.width() // 2, parent.height() // 2)

    # ---------------- 路径显示/存储转换 ----------------
    def _resolve(self, p: str) -> str:
        """把路径转为绝对路径（相对路径基于项目根解析）。"""
        p = (p or "").strip()
        if not p:
            return ""
        if os.path.isabs(p):
            return os.path.normpath(p)
        return os.path.normpath(os.path.join(self.project_root, p))

    def _display_path(self, raw: str) -> str:
        """显示用：项目内 → 相对路径；项目外 → 绝对路径。"""
        raw = (raw or "").strip()
        if not raw:
            return ""
        abs_p = self._resolve(raw)
        try:
            rel = os.path.relpath(abs_p, self.project_root)
        except Exception:
            return abs_p
        if rel.startswith("..") or os.path.isabs(rel):
            return abs_p
        return rel  # 项目内相对路径

    def _store_path(self, raw: str) -> str:
        """存储用：项目内 → 相对路径；项目外 → 绝对路径。"""
        return self._display_path(raw)

    # ---------------- UI 构建 ----------------
    def _add_path_row(self, fl: QFormLayout, label: str, key: str, kind: str) -> None:
        edit = QLineEdit()
        edit.setPlaceholderText("未设置（使用默认）")
        edit.setText(self._display_path(str(self.config.get(key, "") or "")))
        browse = QPushButton("浏览")
        browse.setFixedHeight(28)
        browse.clicked.connect(lambda _=False, k=key, e=edit, t=kind: self._browse(k, e, t))
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(edit, 1)
        row.addWidget(browse)
        # 为「数据库位置」标签添加圆角背景
        if label == "数据库位置":
            lbl = QLabel(label)
            lbl.setObjectName("RoundedLabel")
            lbl.setAutoFillBackground(True)
            fl.addRow(lbl, row)
        else:
            fl.addRow(label, row)
        self._edits[key] = edit

    def _browse(self, key: str, edit: QLineEdit, kind: str) -> None:
        cur = self._resolve(edit.text().strip()) or self.project_root
        if kind == "dir":
            p = QFileDialog.getExistingDirectory(self, f"选择{key}", cur)
        elif kind == "file_db":
            p, _ = QFileDialog.getSaveFileName(self, "选择数据库文件", cur, "SQLite 数据库 (*.db)")
        else:  # file_any
            p, _ = QFileDialog.getOpenFileName(self, "选择文件", cur, "所有文件 (*.*)")
        if p:
            edit.setText(self._display_path(p))

    def _on_save(self) -> None:
        for key, edit in self._edits.items():
            self.config[key] = self._store_path(edit.text())
        old_theme = self.config.get("theme", "dark")
        self.config["theme"] = self.theme_combo.currentData()

        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            QMessageBox.critical(self, "错误", f"写入配置失败：{exc}")
            return

        notes = []
        new_theme = self.config["theme"]
        if new_theme != old_theme:
            notes.append(f"主题已切换为：{'浅色' if new_theme == 'light' else '深色'}")
            # 立即应用新主题
            if self._on_theme_changed:
                self._on_theme_changed(new_theme)
        if self.config.get("theme") == "light":
            notes.append("浅色主题将在下次启动时生效（当前骨架仅暗色）")
        if self.config.get("db_path", "") != self._old_db:
            notes.append("数据库位置将在下次启动时生效")
        msg = f"配置已写入：\n{self.config_path}"
        if notes:
            msg += "\n\n" + "\n".join(f"· {n}" for n in notes)
        QMessageBox.information(self, "配置已保存", msg)
        self.accept()
