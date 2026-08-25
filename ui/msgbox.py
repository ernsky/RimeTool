# -*- coding: utf-8 -*-
"""统一弹窗样式：加宽 + 中文化按钮 + Y/N 快捷键。

本模块取代项目里散落的 ``QMessageBox.information/warning/critical/question``
静态方法调用，统一应用：
  - 最小宽度 1000px（原默认过窄；640/800 仍会让长备份路径折行）；
  - 标准按钮文字中文化（"确认（Y）"/"取消（N）"/"保存（S）" 等）；
  - 绑定 Y/N/S/D/A 快捷键，与 ``ui.confirm.ConfirmBox`` 风格一致。

调用方改造：
  - ``from ui.msgbox import info, warning, critical, confirm``
  - ``QMessageBox.information(self, "标题", "正文")`` → ``info(self, "标题", "正文")``
  - ``QMessageBox.warning(self, "标题", "正文")``   → ``warning(self, "标题", "正文")``
  - ``QMessageBox.critical(self, "标题", "正文")``  → ``critical(self, "标题", "正文")``
  - ``QMessageBox.question(self, "标题", "正文", Yes|No, default)``
        → ``confirm(self, "标题", "正文", default_yes=True)``（返回 bool）

复杂自定义（三按钮、自定义 ButtonRole）仍走 ``ui.confirm.ConfirmBox``，
该类的 ``ask`` 已统一应用本模块样式。
"""
from PyQt5.QtWidgets import QMessageBox, QLabel
from PyQt5.QtGui import QKeySequence


# 弹窗最小宽度（像素）。14pt 字号下可一行容纳约 80 字符英文路径+少量 CJK，
# 覆盖现有"导出到 Rime"/"批量修改TSV权重"/"语音词组查漏"等长路径+备份列表场景。
# 历史：640 太窄、800 仍让 "dicts/" 处折行；1000 经 verify_msgbox_strategies 实测
# 可让所有导出行/备份路径一行内放完（用户 8/24 9:49 明确要求）。
MIN_WIDTH = 1000


# 标准按钮 → 中文文本 + 快捷键映射
_BTN_TEXT = {
    QMessageBox.Ok:      "确认（Y）",
    QMessageBox.Yes:     "确认（Y）",
    QMessageBox.No:      "取消（N）",
    QMessageBox.Cancel:  "取消（N）",
    QMessageBox.Save:    "保存（S）",
    QMessageBox.Discard: "不保存（D）",
    QMessageBox.Apply:   "应用（A）",
}

_BTN_SHORTCUT = {
    QMessageBox.Ok:      QKeySequence("Y"),
    QMessageBox.Yes:     QKeySequence("Y"),
    QMessageBox.No:      QKeySequence("N"),
    QMessageBox.Cancel:  QKeySequence("N"),
    QMessageBox.Save:    QKeySequence("S"),
    QMessageBox.Discard: QKeySequence("D"),
    QMessageBox.Apply:   QKeySequence("A"),
}

# 按 StandardButton 枚举遍历，统一处理
_ALL_STD = (
    QMessageBox.Ok, QMessageBox.Yes, QMessageBox.No, QMessageBox.Cancel,
    QMessageBox.Save, QMessageBox.Discard, QMessageBox.Apply,
)


def apply_box_style(box: QMessageBox) -> None:
    """对已构造的 QMessageBox 应用统一样式：最小宽度 + 中文化按钮 + 快捷键。
    也供 ``ui.confirm.ConfirmBox.ask`` 复用，保证所有弹窗一致。

    宽度策略：① 整框 ``setMinimumWidth(MIN_WIDTH)``；② 主文本标签
    ``setMinimumWidth(MIN_WIDTH-80)``。两个一起设，保证主内容（标签）足够宽，
    布局就会把整框撑到至少 MIN_WIDTH。

    **绝不使用** ``QLayout.setSizeConstraint(SetMinimumSize)``：该约束的语义是
    "把 widget 尺寸**强制设为** minimumSizeHint()"，会**反向覆盖**我们的
    setMinimumWidth(800)——实测 800 会被压回 633（label min 决定）。所以这里
    只用 setMinimumWidth，干净可控。

    **本函数绝不抛异常**：样式只是锦上添花，任何一步失败都跳过，
    绝不允许因为样式代码出错而让弹窗弹不出来。
    """
    try:
        box.setMinimumWidth(MIN_WIDTH)
    except Exception:
        pass
    try:
        # 文本标签对象名为 qt_msgbox_label；兜底取首个 QLabel，避免个别 Qt 版本差异
        lbl = box.findChild(QLabel, "qt_msgbox_label")
        if lbl is None:
            labels = box.findChildren(QLabel)
            lbl = labels[0] if labels else None
        if lbl is not None:
            lbl.setMinimumWidth(MIN_WIDTH - 80)
            # 给 label 加 60px 右边距：≈ 3 个中文字符（19×3=57，留余量）。
            # QMessageBox 默认布局让标签贴到右边缘，文本最后一行 wrap 后会紧挨
            # 关闭按钮/边框；20px 仍偏挤，用户要求"至少 3 个中文字符边距"才美观。
            # 用 QSS 而非 setContentsMargins 是为不影响 layout 的尺寸计算。
            lbl.setStyleSheet("padding-right: 60px;")
    except Exception:
        pass
    for std in _ALL_STD:
        try:
            btn = box.button(std)
            if btn is None:
                continue
            btn.setText(_BTN_TEXT.get(std, btn.text()))
            sc = _BTN_SHORTCUT.get(std)
            if sc is not None:
                btn.setShortcut(sc)
        except Exception:
            continue


def info(parent, title, text):
    """等价于 ``QMessageBox.information(...)``，但应用统一样式。"""
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Information)
    box.setWindowTitle(title)
    box.setText(text)
    box.setStandardButtons(QMessageBox.Ok)
    apply_box_style(box)
    return box.exec_()


def warning(parent, title, text):
    """等价于 ``QMessageBox.warning(...)``，但应用统一样式。"""
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Warning)
    box.setWindowTitle(title)
    box.setText(text)
    box.setStandardButtons(QMessageBox.Ok)
    apply_box_style(box)
    return box.exec_()


def critical(parent, title, text):
    """等价于 ``QMessageBox.critical(...)``，但应用统一样式。"""
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Critical)
    box.setWindowTitle(title)
    box.setText(text)
    box.setStandardButtons(QMessageBox.Ok)
    apply_box_style(box)
    return box.exec_()


def confirm(parent, title, text, default_yes=True):
    """等价于 ``QMessageBox.question(..., Yes|No, default)``。

    返回 bool：True 表示用户按了"确认（Y）"，False 表示"取消（N）"。
    若调用方需区分 StandardButton（Yes vs No），仍应走 ``ui.confirm.ConfirmBox``。
    """
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Question)
    box.setWindowTitle(title)
    box.setText(text)
    box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
    box.setDefaultButton(QMessageBox.Yes if default_yes else QMessageBox.No)
    apply_box_style(box)
    return box.exec_() == QMessageBox.Yes