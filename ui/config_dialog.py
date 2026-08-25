# -*- coding: utf-8 -*-
"""配置模块对话框：指定左栏文件来源。

两个子模块：
  1) 指定 tsv 文件 —— 直接选定某个 .tsv 文件（左栏「TSV 文件」组只列它）；
  2) 指定 Rime 配置文件夹 —— 选定后扫描该文件夹下所有 *.dict.yaml，罗列在左栏「Dict 文件」组。

配置持久化到 RimeTool/workspace_config.json：{tsv_path, rime_config_dir}。
"""
import logging
import os
import json

from PyQt5.QtCore import QSettings
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel,
    QLineEdit, QPushButton, QFileDialog, QDialogButtonBox, QComboBox,
    QListWidget, QMessageBox,
)
from ui.msgbox import info, warning, critical
from core import backup as backup_mod
from core.config import THEME_CHOICES, SINGLE_CHAR_FILE, is_safe_target
from ui.confirm import ConfirmBox

_log = logging.getLogger(__name__)


CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "workspace_config.json")

# 出厂默认：Alamo.tsv + RimeConfig 目录（首次运行即可用）
# 路径按安装根目录推导，随程序位置移动自适应（不再写死绝对路径）
_RIME_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_CONFIG = {
    "tsv_path": os.path.join(_RIME_ROOT, "Python", "Alamo.tsv"),
    "rime_config_dir": os.path.join(_RIME_ROOT, "RimeConfig"),
    "theme": "auto",
    # 语音词组查漏：SayIt 语音导出 JSON（空则运行时弹窗选择）
    "voice_file": "",
    # 默认输出文件夹：新增 4 个功能模块（语音/English/去重/排序）的产物统一落此；
    # 现有「导出到Rime」「批量修改权重」仍原位写回，不受影响。
    "output_dir": os.path.join(_RIME_ROOT, "RimeTool", "Outputs"),
    # 单字编码表（五笔编码生成读取；默认 resources/word.txt，可指向其它单字表）
    "single_char_file": SINGLE_CHAR_FILE,
}


def load_config():
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return dict(DEFAULT_CONFIG)
    cfg = {
        "tsv_path": data.get("tsv_path", DEFAULT_CONFIG["tsv_path"]),
        "rime_config_dir": data.get("rime_config_dir", DEFAULT_CONFIG["rime_config_dir"]),
        "theme": data.get("theme", DEFAULT_CONFIG["theme"]),
        "voice_file": data.get("voice_file", DEFAULT_CONFIG["voice_file"]),
        "output_dir": data.get("output_dir", DEFAULT_CONFIG["output_dir"]),
        "single_char_file": data.get("single_char_file", DEFAULT_CONFIG["single_char_file"]),
    }
    # 防御性校验：路径类配置若指向危险系统目录（如 C:\Windows\System32），直接回退默认，
    # 避免误配 / 篡改经 is_safe_target 之外的写回点造成越权写（安全审查 F3，F1 之外的纵深防御）。
    for key in ("tsv_path", "rime_config_dir", "output_dir", "single_char_file", "voice_file"):
        val = cfg.get(key, "")
        if val and not is_safe_target(val):
            _log.warning("配置项 %s 指向不安全路径，已回退默认：%s", key, val)
            cfg[key] = DEFAULT_CONFIG[key]
    return cfg


def save_config(config):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        return True
    except OSError:
        return False


def _set_btn_class(btn, cls):
    """设置按钮动态 class 属性并刷新样式（让 style.qss 的 [class=...] 选择器生效）。"""
    btn.setProperty("class", cls)
    btn.style().unpolish(btn)
    btn.style().polish(btn)


def apply_dark_title(win, theme_name):
    """让弹出的子对话框原生标题栏随主题配色（与主窗口 main 同款）。

    主窗口已用 DWM 把标题栏背景/文字按主题上色；子对话框（如「从备份恢复」、五笔编码）
    需各自套一次，否则在深色主题下标题栏仍是系统浅色，与主题不一致。
    （全局弹窗过滤器也会兜底，这里保留显式调用以确保时序。）
    offscreen 或任何异常静默忽略。"""
    try:
        from main import title_colors_for, _set_dark_title_bar
        win.winId()   # 强制创建原生窗口句柄，确保 DWM 属性可写入
        cap, txt, drk = title_colors_for(theme_name)
        _set_dark_title_bar(win, drk, cap, txt)
    except Exception:  # noqa: BLE001 - 设置暗色标题栏失败静默忽略
        _log.debug("设置子对话框暗色标题栏失败", exc_info=True)


class ConfigDialog(QDialog):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.setWindowTitle("配置模块")
        self.resize(620, 200)
        self._restore_geometry()       # 恢复上次弹窗大小/位置
        self._config = dict(config)

        layout = QVBoxLayout(self)

        # 子模块 1：tsv 文件
        g1 = QGroupBox("指定 tsv 文件")
        h1 = QHBoxLayout(g1)
        self.edit_tsv = QLineEdit(self._config.get("tsv_path", ""))
        btn_tsv = QPushButton("浏览...")
        btn_tsv.clicked.connect(self._pick_tsv)
        h1.addWidget(QLabel("文件:"), 0)
        h1.addWidget(self.edit_tsv, 1)
        h1.addWidget(btn_tsv, 0)
        layout.addWidget(g1)

        # 子模块 2：Rime 配置文件夹
        g2 = QGroupBox("指定 Rime 配置文件夹")
        h2 = QHBoxLayout(g2)
        self.edit_dir = QLineEdit(self._config.get("rime_config_dir", ""))
        btn_dir = QPushButton("浏览...")
        btn_dir.clicked.connect(self._pick_dir)
        h2.addWidget(QLabel("文件夹:"), 0)
        h2.addWidget(self.edit_dir, 1)
        h2.addWidget(btn_dir, 0)
        layout.addWidget(g2)

        # 外观：主题（自动 / 浅色 / 深色）
        g3 = QGroupBox("外观")
        h3 = QHBoxLayout(g3)
        self.comboTheme = QComboBox()
        for val, label in THEME_CHOICES:
            self.comboTheme.addItem(label, val)
        idx = self.comboTheme.findData(self._config.get("theme", "auto"))
        self.comboTheme.setCurrentIndex(idx if idx >= 0 else 0)
        h3.addWidget(QLabel("主题:"), 0)
        h3.addWidget(self.comboTheme, 1)
        layout.addWidget(g3)

        # 语音词组查漏：SayIt 语音导出 JSON
        g4 = QGroupBox("语音词组文件（SayIt 语音导出 JSON）")
        h4 = QHBoxLayout(g4)
        self.edit_voice = QLineEdit(self._config.get("voice_file", ""))
        btn_voice = QPushButton("浏览...")
        btn_voice.clicked.connect(self._pick_voice)
        h4.addWidget(QLabel("文件:"), 0)
        h4.addWidget(self.edit_voice, 1)
        h4.addWidget(btn_voice, 0)
        layout.addWidget(g4)

        # 默认输出文件夹：新增功能模块产物落点
        g5 = QGroupBox("默认输出文件夹（新增功能模块产物）")
        h5 = QHBoxLayout(g5)
        self.edit_out = QLineEdit(self._config.get("output_dir", ""))
        btn_out = QPushButton("浏览...")
        btn_out.clicked.connect(self._pick_out)
        h5.addWidget(QLabel("文件夹:"), 0)
        h5.addWidget(self.edit_out, 1)
        h5.addWidget(btn_out, 0)
        layout.addWidget(g5)

        # 单字编码文件（五笔编码生成读取的单字表；默认 resources/word.txt）
        g7 = QGroupBox("单字编码文件（五笔编码生成读取）")
        h7 = QHBoxLayout(g7)
        self.edit_single = QLineEdit(self._config.get("single_char_file", ""))
        btn_single = QPushButton("浏览...")
        btn_single.clicked.connect(self._pick_single)
        h7.addWidget(QLabel("文件:"), 0)
        h7.addWidget(self.edit_single, 1)
        h7.addWidget(btn_single, 0)
        layout.addWidget(g7)

        # 备份：从基线回退（退回备份时的状态）
        g6 = QGroupBox("备份")
        h6 = QHBoxLayout(g6)
        self.btn_restore = QPushButton("从备份恢复…")
        self.btn_restore.clicked.connect(self._on_restore_backup)
        h6.addWidget(QLabel("误改后可退回自动备份时的状态："), 0)
        h6.addWidget(self.btn_restore, 0)
        h6.addStretch(1)
        layout.addWidget(g6)

        layout.addStretch(1)

        # 按钮（主操作 accent 突出，次要描边，避免全灰）
        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        _set_btn_class(box.button(QDialogButtonBox.Ok), "btn-blue")
        _set_btn_class(box.button(QDialogButtonBox.Cancel), "btn-ghost")
        box.button(QDialogButtonBox.Ok).setToolTip("保存配置并关闭对话框")
        box.button(QDialogButtonBox.Cancel).setToolTip("放弃本次修改，关闭对话框")
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        layout.addWidget(box)

    def _pick_tsv(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 TSV 文件", self.edit_tsv.text() or "",
            "TSV 文件 (*.tsv);;所有文件 (*.*)"
        )
        if path:
            self.edit_tsv.setText(path)

    def _pick_dir(self):
        d = QFileDialog.getExistingDirectory(
            self, "选择 Rime 配置文件夹", self.edit_dir.text() or ""
        )
        if d:
            self.edit_dir.setText(d)

    def _pick_voice(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 SayIt 语音导出 JSON", self.edit_voice.text() or "",
            "JSON 文件 (*.json);;所有文件 (*.*)"
        )
        if path:
            self.edit_voice.setText(path)

    def _pick_out(self):
        d = QFileDialog.getExistingDirectory(
            self, "选择默认输出文件夹", self.edit_out.text() or ""
        )
        if d:
            self.edit_out.setText(d)

    def _pick_single(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择单字编码文件", self.edit_single.text() or "",
            "文本文件 (*.txt);;所有文件 (*.*)"
        )
        if path:
            self.edit_single.setText(path)

    def _on_restore_backup(self):
        """列出 Logs 中可用备份，选择后解压写回目标文件（退回备份时的状态）。"""
        items = backup_mod.list_backups()
        if not items:
            info(self, "从备份恢复", "当前没有可用的备份。")
            return
        dlg = QDialog(self)
        apply_dark_title(dlg, self._config.get("theme", "auto"))
        dlg.setWindowTitle("从备份恢复")
        dlg.resize(580, 380)
        vlay = QVBoxLayout(dlg)
        vlay.addWidget(QLabel("选择要回退的备份（写回其目标文件）："))
        lw = QListWidget(dlg)
        for it in items:
            lw.addItem("%s\n    -> %s" % (it["name"], it["target"]))
        vlay.addWidget(lw)
        hlay = QHBoxLayout()
        btn_cancel = QPushButton("取消")
        btn_ok = QPushButton("恢复")
        hlay.addStretch(1)
        hlay.addWidget(btn_cancel)
        hlay.addWidget(btn_ok)
        vlay.addLayout(hlay)

        def _do():
            row = lw.currentRow()
            if row < 0:
                return
            it = items[row]
            # ConfirmBox 支持 Y（确认）/ N（取消）快捷键；返回判定保持原逻辑
            if ConfirmBox.ask(
                self, "确认恢复",
                "将把备份\n  %s\n写回到\n  %s\n当前内容会被覆盖（回退前会自动留一份安全快照）。"
                % (it["name"], it["target"]),
                QMessageBox.Ok | QMessageBox.Cancel,
            ) != QMessageBox.Ok:
                return
            ok = backup_mod.restore_snapshot(it["backup"], it["target"], safe=True)
            if ok:
                info(self, "从备份恢复", "已恢复到备份时的状态。")
                dlg.accept()
            else:
                critical(self, "从备份恢复", "恢复失败：无法写入目标文件。")

        btn_ok.clicked.connect(_do)
        btn_cancel.clicked.connect(dlg.reject)
        lw.itemDoubleClicked.connect(lambda _=None: _do())
        dlg.exec_()

    def _restore_geometry(self):
        """恢复上次弹窗大小/位置（dialog/config/geometry）；无记忆则用 resize 默认。"""
        try:
            geo = QSettings().value("dialog/config/geometry")
            if geo:
                self.restoreGeometry(geo)
        except Exception:  # noqa: BLE001 - 几何恢复失败不影响使用，仅记录
            _log.debug("恢复配置对话框几何失败", exc_info=True)

    def done(self, r):
        """弹窗关闭（确定/取消/系统关闭）时保存几何，覆盖 QDialog.accept/reject。"""
        try:
            QSettings().setValue("dialog/config/geometry", self.saveGeometry())
        except Exception:  # noqa: BLE001 - 几何保存失败不影响关闭
            _log.debug("保存配置对话框几何失败", exc_info=True)
        super().done(r)

    def get_config(self):
        return {
            "tsv_path": self.edit_tsv.text().strip(),
            "rime_config_dir": self.edit_dir.text().strip(),
            "theme": self.comboTheme.currentData(),
            "voice_file": self.edit_voice.text().strip(),
            "output_dir": self.edit_out.text().strip(),
            "single_char_file": self.edit_single.text().strip(),
        }
