# -*- coding: utf-8 -*-
"""带 Y/N 快捷键的确认对话框。

设计要点：
- 继承 QMessageBox，覆写 keyPressEvent：
    * 按 Y / y → 点击「肯定」按钮（Yes / Ok / AcceptRole）
    * 按 N / n → 点击「否定」按钮（No / Cancel / RejectRole）
    * Enter / Esc 由 Qt 默认行为处理（默认按钮 / 取消），无需接管。
- 焦点在文本输入框（QLineEdit / QTextEdit / QPlainTextEdit）时，Y/N 不接管，
  以免把字符误输入到框里——直接交给父类，由输入框消费按键。
- 刻意不把 N 绑定到 DestructiveRole（如「不保存退出」）这类破坏性按钮，
  避免误触导致数据丢失；N 只对应「取消 / 拒绝」语义。
- 注意：QMessageBox.question(...) 静态方法内部只会构造普通 QMessageBox，
  拿不到本类的 keyPressEvent 覆写，因此调用方必须用实例形式（见文件底部示例）。
"""


from PyQt5.QtWidgets import QMessageBox, QLineEdit, QTextEdit, QPlainTextEdit
from ui.msgbox import apply_box_style


# 焦点落在这些文本编辑控件时，Y/N 不接管（让输入框消费字符）
_TEXT_EDITS = (QLineEdit, QTextEdit, QPlainTextEdit)


def _buttons_by_role(box: QMessageBox, *roles):
    """按 ButtonRole 找按钮。注意：PyQt5 的 QMessageBox.button() 只接受
    StandardButton，不接受 ButtonRole，故用 buttonRole() 遍历。"""
    out = []
    for b in box.buttons():
        try:
            if box.buttonRole(b) in roles:
                out.append(b)
        except Exception:
            pass
    return out


def _affirmative_button(box: QMessageBox):
    """肯定按钮优先级：AcceptRole → YesRole → 标准 Yes/Ok/Save。"""
    for role in (QMessageBox.AcceptRole, QMessageBox.YesRole):
        bs = _buttons_by_role(box, role)
        if bs:
            return bs[0]
    for std in (QMessageBox.Ok, QMessageBox.Yes, QMessageBox.Save):
        b = box.button(std)
        if b is not None:
            return b
    return None


def _negative_button(box: QMessageBox):
    """否定按钮优先级：RejectRole → NoRole → 标准 No/Cancel。
    刻意绕开 DestructiveRole（破坏性操作）。"""
    for role in (QMessageBox.RejectRole, QMessageBox.NoRole):
        bs = _buttons_by_role(box, role)
        if bs:
            return bs[0]
    for std in (QMessageBox.Cancel, QMessageBox.No):
        b = box.button(std)
        if b is not None:
            return b
    return None


class ConfirmBox(QMessageBox):
    """支持 Y（确认）/ N（取消）快捷键的确认框。"""

    def keyPressEvent(self, event):
        key = event.text().lower()
        if key in ("y", "n"):
            # 焦点在文本输入框时，不拦截，交给输入框消费字符
            fw = self.focusWidget()
            if isinstance(fw, _TEXT_EDITS):
                super().keyPressEvent(event)
                return
            target = _affirmative_button(self) if key == "y" else _negative_button(self)
            if target is not None:
                target.click()
                event.accept()
                return
        super().keyPressEvent(event)

    @classmethod
    def ask(cls, parent, title, text, buttons, default=None,
            icon=QMessageBox.Question):
        """便捷封装：等价于 QMessageBox.question，但支持 Y/N 快捷键。
        返回被点击的标准按钮（QMessageBox.StandardButton）。"""
        box = cls(parent)
        box.setIcon(icon)
        box.setWindowTitle(title)
        box.setText(text)
        box.setStandardButtons(buttons)
        if default is not None:
            box.setDefaultButton(default)
        apply_box_style(box)
        return box.exec_()


# ----------------------------------------------------------------------------
# 调用方改造示例（保持不变的返回判定）：
#
#   from ui.confirm import ConfirmBox
#
#   # 原：reply = QMessageBox.question(self, "确认删除", txt, Yes | No, No)
#   # 改：
#   if ConfirmBox.ask(self, "确认删除", txt,
#                     QMessageBox.Yes | QMessageBox.No,
#                     QMessageBox.No) != QMessageBox.Yes:
#       return
#
#   # 三按钮（含自定义 Accept/Destructive/Reject 角色）需实例形式：
#   msg = ConfirmBox(self)
#   msg.setIcon(QMessageBox.Question)
#   msg.setText("数据已修改，是否保存？")
#   btn_save = msg.addButton("保存并退出", QMessageBox.AcceptRole)
#   msg.addButton("不保存退出", QMessageBox.DestructiveRole)
#   msg.addButton("取消", QMessageBox.RejectRole)
#   msg.setDefaultButton(btn_save)
#   msg.exec_()
#   # N 只会点「取消」(RejectRole)，不会点「不保存退出」(DestructiveRole)
#   if msg.clickedButton() == btn_save:
#       ...
# ----------------------------------------------------------------------------
