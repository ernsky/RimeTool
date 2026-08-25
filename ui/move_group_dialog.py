# -*- coding: utf-8 -*-
"""批量改分组 / 启用 对话框（单步可搜索面板）。

在「移动到分组」基础上增强：同时支持批量改「分组」与「启用」两列，且各自可任意指定：

- 分组：①（不改分组）② 选现有分组（一级前缀 / 二级描述树，搜索框实时过滤，MRU 置顶）③（新建分组…）手填新名。
- 启用：下拉四种 —— 不改启用 / 清空（空） / 设为 A / 自定义…（手填任意值）。

两列可单独改、也可同时改：只要「分组有选择」或「启用≠不改」即可确定。
启用列的自定义值支持任意字符串（含空以外的自由值），满足「分组和启用都要任意设」。

对外 API（兼容旧调用）：
  selected_group() -> 目标分组名；None 表示不改分组（含「不改分组」或「新建」未填）。
  enable_value()   -> 启用新值：None=不改 / ""=清空 / "A"=设为A / 其它=自定义。
  also_enable()    -> 兼容旧接口：仅当启用模式为「设为 A」时返回 True。

不依赖任何项目模块（仅 Qt），便于单测与复用。
"""
import logging
import re

from PyQt5.QtCore import Qt, QSettings
from PyQt5.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
)

_log = logging.getLogger(__name__)


_NOCHANGE = "__NOCHANGE__"   # 分组节点：不改分组
_NEW = "__NEW__"             # 分组节点：新建分组…

_ENABLE_MODES = ["不改启用", "清空（空）", "设为 A", "自定义…"]
_ENABLE_INDEX_NOCHANGE = 0
_ENABLE_INDEX_CLEAR = 1
_ENABLE_INDEX_A = 2
_ENABLE_INDEX_CUSTOM = 3


_LETTER_RE = re.compile(r"[A-Za-z]")
MRU_KEY = "movegroup/mru"
MRU_MAX = 8


def _tier_of(name):
    """返回 (一级前缀, 二级描述)。'C 成语' -> ('C', '成语')；'短语' -> ('(其他)', '短语')。"""
    s = (name or "").strip()
    if not s:
        return ("(其他)", s)
    if " " in s:
        pre, rest = s.split(" ", 1)
        return (pre, rest)
    if _LETTER_RE.match(s[0]):
        return (s[0], s)        # 单字母前缀，整体作描述
    return ("(其他)", s)


def _load_mru():
    try:
        val = QSettings().value(MRU_KEY)
    except Exception:  # noqa: BLE001 - MRU 读取失败则退化为空列表，仅记录
        _log.debug("读取最近使用分组失败", exc_info=True)
        return []
    if not val:
        return []
    if isinstance(val, str):
        return [val]
    return [str(v) for v in val]


class MoveToGroupDialog(QDialog):
    """单步可搜索的批量改分组 / 启用 对话框。"""

    def __init__(self, groups, count, parent=None):
        super().__init__(parent)
        self.setWindowTitle("批量改分组 / 启用")
        self.setMinimumWidth(360)
        self.setMinimumHeight(480)
        self._restore_geometry()

        self._groups = sorted(set(groups or []))
        self._selected_group = ""
        self._mru = _load_mru()

        # 分组选择状态：None / "nochange" / "real" / "new"
        self._group_mode = None
        self._group_value = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        title = QLabel(f"把选中的 {count} 条：")
        title.setObjectName("dlgTitle")   # 由 style.qss 的 QLabel#dlgTitle 统一控制（随主题）
        layout.addWidget(title)

        # 搜索框（仅过滤现有分组；特殊节点常驻）
        self.editSearch = QLineEdit()
        self.editSearch.setPlaceholderText("搜索分组名 / 拼音…")
        self.editSearch.textEdited.connect(self._apply_search)
        layout.addWidget(self.editSearch)

        # 最近使用
        self.recentList = QListWidget()
        self.recentList.itemClicked.connect(self._on_recent_clicked)
        self.recentList.itemDoubleClicked.connect(self._on_recent_double_clicked)
        if self._mru:
            layout.addWidget(QLabel("最近使用："))
            for g in self._mru:
                self.recentList.addItem(g)
            layout.addWidget(self.recentList, 1)
            layout.addWidget(QLabel("全部分组："))

        # 分组树（含特殊节点：不改分组 / 新建分组…）
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.itemClicked.connect(self._on_tree_clicked)
        self.tree.itemDoubleClicked.connect(self._on_tree_double_clicked)
        layout.addWidget(self.tree, 3)
        self._build_tree()

        # 新建分组名输入（仅当选「新建分组…」时出现）
        self.editGroupNew = QLineEdit()
        self.editGroupNew.setPlaceholderText("输入新分组名（如 B 青云）")
        self.editGroupNew.textEdited.connect(self._on_new_group_text)
        self.editGroupNew.setVisible(False)
        layout.addWidget(self.editGroupNew)

        # 启用值选择
        hb = QHBoxLayout()
        hb.addWidget(QLabel("启用："))
        self.cmbEnable = QComboBox()
        self.cmbEnable.addItems(_ENABLE_MODES)
        self.cmbEnable.setCurrentIndex(_ENABLE_INDEX_A)   # 默认「设为 A」，兼容旧默认行为
        self.cmbEnable.currentIndexChanged.connect(self._on_enable_mode)
        hb.addWidget(self.cmbEnable, 1)
        layout.addLayout(hb)
        self.editEnableCustom = QLineEdit()
        self.editEnableCustom.setPlaceholderText("自定义启用值")
        self.editEnableCustom.setVisible(False)
        layout.addWidget(self.editEnableCustom)

        # 底部按钮
        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_box.button(QDialogButtonBox.Ok).setText("确定")
        btn_box.button(QDialogButtonBox.Cancel).setText("取消")
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        self.btnOk = btn_box.button(QDialogButtonBox.Ok)
        self.btnOk.setEnabled(False)
        layout.addWidget(btn_box)

        self._apply_search("")

        # 原生标题栏随主题配色（浅=深蓝底白字 / 深=#1C1F24 底白字）
        try:
            from ui.config_dialog import apply_dark_title
            _cfg = getattr(parent, "_config", None) or {}
            apply_dark_title(self, _cfg.get("theme", "auto"))
        except Exception:  # noqa: BLE001 - 失败静默忽略
            pass

    # ---- 构建 / 过滤 ----
    def _build_tree(self):
        self.tree.clear()
        # 顶部特殊节点：不改分组
        nochange = QTreeWidgetItem(self.tree, ["（不改分组）"])
        nochange.setData(0, Qt.UserRole, _NOCHANGE)
        # 一级前缀 / 二级描述（现有分组）
        tiers = {}
        for g in self._groups:
            pre, rest = _tier_of(g)
            tiers.setdefault(pre, []).append(g)
        for pre in sorted(tiers.keys()):
            top = QTreeWidgetItem(self.tree, [pre])
            top.setData(0, Qt.UserRole, "")
            for g in sorted(tiers[pre]):
                child = QTreeWidgetItem(top, [g])
                child.setData(0, Qt.UserRole, g)
            top.setExpanded(True)
        # 底部特殊节点：新建分组
        newnode = QTreeWidgetItem(self.tree, ["（新建分组…）"])
        newnode.setData(0, Qt.UserRole, _NEW)

    def _apply_search(self, text):
        text = (text or "").strip().lower()
        # 最近使用列表过滤
        if hasattr(self, "recentList"):
            for i in range(self.recentList.count()):
                item = self.recentList.item(i)
                item.setHidden(bool(text) and text not in item.text().lower())
        # 分组树过滤：特殊节点常驻；现有分组按名称过滤
        for ti in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(ti)
            top_role = top.data(0, Qt.UserRole)
            if top_role in (_NOCHANGE, _NEW):
                top.setHidden(False)
                continue
            visible_children = 0
            for ci in range(top.childCount()):
                child = top.child(ci)
                g = child.data(0, Qt.UserRole) or ""
                match = (not text) or (text in g.lower())
                child.setHidden(not match)
                if match:
                    visible_children += 1
            top.setHidden(visible_children == 0)
            if visible_children == 0:
                top.setExpanded(False)
            else:
                top.setExpanded(True)

    # ---- 槽 ----
    def _on_tree_clicked(self, item):
        g = item.data(0, Qt.UserRole)
        if g == _NOCHANGE:
            self._group_mode = "nochange"
            self._group_value = None
            self.editGroupNew.setVisible(False)
        elif g == _NEW:
            self._group_mode = "new"
            self.editGroupNew.setVisible(True)
            self.editGroupNew.setFocus()
            self._group_value = self.editGroupNew.text().strip()
        elif g:
            self._group_mode = "real"
            self._group_value = g
            self.editGroupNew.setVisible(False)
        else:
            return   # 点了一级节点，不当作选择
        self._refresh_ok()

    def _on_tree_double_clicked(self, item):
        g = item.data(0, Qt.UserRole)
        if not g or g in (_NOCHANGE, _NEW):
            return
        self._group_mode = "real"
        self._group_value = g
        self.editGroupNew.setVisible(False)
        self.accept()

    def _on_recent_clicked(self, item):
        self._group_mode = "real"
        self._group_value = item.text()
        self.editGroupNew.setVisible(False)
        self._refresh_ok()

    def _on_recent_double_clicked(self, item):
        self._group_mode = "real"
        self._group_value = item.text()
        self.editGroupNew.setVisible(False)
        self.accept()

    def _on_new_group_text(self, text):
        self._group_value = text.strip()
        self._refresh_ok()

    def _on_enable_mode(self, idx):
        self.editEnableCustom.setVisible(idx == _ENABLE_INDEX_CUSTOM)
        self._refresh_ok()

    def _refresh_ok(self):
        # 「不改分组」本身不算有效改动；只有「选现有/新建」才算分组被改。
        group_ok = self._group_mode in ("real", "new") and not (
            self._group_mode == "new" and not (self._group_value or "").strip())
        enable_ok = self.cmbEnable.currentIndex() != _ENABLE_INDEX_NOCHANGE
        self.btnOk.setEnabled(bool(group_ok or enable_ok))

    # ---- 对外 API ----
    def selected_group(self):
        """返回目标分组名；None 表示不改分组。"""
        if self._group_mode in ("real", "new"):
            v = (self._group_value or "").strip()
            return v or None
        return None   # nochange 或 未选

    def enable_value(self):
        """返回启用新值：None=不改 / ""=清空 / "A"=设为A / 其它=自定义。"""
        idx = self.cmbEnable.currentIndex()
        if idx == _ENABLE_INDEX_NOCHANGE:
            return None
        if idx == _ENABLE_INDEX_CLEAR:
            return ""
        if idx == _ENABLE_INDEX_A:
            return "A"
        return (self.editEnableCustom.text() or "").strip()

    def also_enable(self):
        """兼容旧接口：仅当启用模式为「设为 A」时返回 True。"""
        return self.cmbEnable.currentIndex() == _ENABLE_INDEX_A

    def _restore_geometry(self):
        try:
            geo = QSettings().value("dialog/movegroup/geometry")
            if geo:
                self.restoreGeometry(geo)
        except Exception:  # noqa: BLE001 - 几何恢复失败不影响使用，仅记录
            _log.debug("恢复移动到分组对话框几何失败", exc_info=True)

    def done(self, r):
        try:
            QSettings().setValue("dialog/movegroup/geometry", self.saveGeometry())
        except Exception:  # noqa: BLE001 - 几何保存失败不影响关闭
            _log.debug("保存移动到分组对话框几何失败", exc_info=True)
        super().done(r)
