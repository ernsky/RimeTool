"""深色/浅色主题应用（PySide6 / Qt）。

提供 apply_theme(app, name) 一键应用 Fusion 主题 + 全局 QSS，
以及 style_toolbar(toolbar) 统一工具栏外观。
"""

from __future__ import annotations

from PySide6.QtWidgets import QApplication, QToolBar
from PySide6.QtGui import QPalette, QColor

from .tokens import (
    BG_WINDOW, BG_APP, BG_CARD, TEXT_PRIMARY, TEXT_SECONDARY, TEXT_VALUE,
    ACCENT, ACCENT_BTN, ACCENT_BTN_HOVER,
    BG_WINDOW_LIGHT, BG_APP_LIGHT, BG_CARD_LIGHT,
    TEXT_PRIMARY_LIGHT, TEXT_SECONDARY_LIGHT, TEXT_VALUE_LIGHT,
    ACCENT_LIGHT, ACCENT_BTN_LIGHT, ACCENT_BTN_HOVER_LIGHT,
    BG_PANEL, BG_PANEL_LIGHT,
    BG_ELEVATED, BG_ELEVATED_LIGHT,
    BG_ACCENT, BG_ACCENT_LIGHT,
    BORDER, BORDER_LIGHT,
    BORDER_CARD, BORDER_CARD_LIGHT,
    BORDER_INPUT, BORDER_INPUT_LIGHT,
    BORDER_HOVER, BORDER_HOVER_LIGHT,
    BORDER_BTN_HOVER, BORDER_BTN_HOVER_LIGHT,
    TEXT_MUTED, TEXT_MUTED_LIGHT,
    TEXT_MUTED2, TEXT_MUTED2_LIGHT,
    TEXT_BRIGHT, TEXT_BRIGHT_LIGHT,
    RADIUS_CARD, RADIUS_BAR, RADIUS_BAR_CHUNK, RADIUS_TAB, RADIUS_INPUT, RADIUS_BTN,
    CARD_PADDING, SPACING_TOOLBAR, TOOLBAR_PADDING, TAB_PADDING, CHART_MARGIN, CHART_MARGIN_MINI,
    PROGRESS_BAR_HEIGHT,
)


def style_toolbar(toolbar: QToolBar) -> None:
    """统一工具栏外观：不可移动、不可浮动。"""
    toolbar.setMovable(False)
    toolbar.setFloatable(False)


def apply_theme(app: QApplication, theme_name: str = "dark") -> None:
    """应用主题（dark 或 light）。"""
    app.setStyle("Fusion")
    if theme_name == "light":
        _apply_light_theme(app)
    else:
        _apply_dark_theme(app)


def apply_dark_theme(app: QApplication) -> None:
    """应用深色主题（兼容旧接口）。"""
    apply_theme(app, "dark")


def _apply_dark_theme(app: QApplication) -> None:
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(BG_WINDOW))
    palette.setColor(QPalette.WindowText, QColor(TEXT_PRIMARY))
    palette.setColor(QPalette.Base, QColor(BG_APP))
    palette.setColor(QPalette.AlternateBase, QColor(BG_CARD))
    palette.setColor(QPalette.ToolTipBase, QColor("#ffffff"))
    palette.setColor(QPalette.ToolTipText, QColor("#000000"))
    palette.setColor(QPalette.Text, QColor(TEXT_PRIMARY))
    palette.setColor(QPalette.Button, QColor("#2a2a2a"))
    palette.setColor(QPalette.ButtonText, QColor(TEXT_PRIMARY))
    palette.setColor(QPalette.BrightText, QColor("#ff0000"))
    palette.setColor(QPalette.Highlight, QColor(ACCENT))
    palette.setColor(QPalette.HighlightedText, QColor("#000000"))
    app.setPalette(palette)
    app.setStyleSheet(THEME_QSS)


def _apply_light_theme(app: QApplication) -> None:
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(BG_WINDOW_LIGHT))
    palette.setColor(QPalette.WindowText, QColor(TEXT_PRIMARY_LIGHT))
    palette.setColor(QPalette.Base, QColor(BG_APP_LIGHT))
    palette.setColor(QPalette.AlternateBase, QColor(BG_CARD_LIGHT))
    palette.setColor(QPalette.ToolTipBase, QColor("#ffffff"))
    palette.setColor(QPalette.ToolTipText, QColor("#000000"))
    palette.setColor(QPalette.Text, QColor(TEXT_PRIMARY_LIGHT))
    palette.setColor(QPalette.Button, QColor(BG_ACCENT_LIGHT))
    palette.setColor(QPalette.ButtonText, QColor(TEXT_PRIMARY_LIGHT))
    palette.setColor(QPalette.BrightText, QColor("#ff0000"))
    palette.setColor(QPalette.Highlight, QColor(ACCENT_LIGHT))
    palette.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    app.setPalette(palette)
    app.setStyleSheet(THEME_QSS_LIGHT)


# 全局样式表（深色）
THEME_QSS = """
QWidget { background-color: #121212; color: #e0e0e0; }
QMainWindow { background-color: #0d0d0d; }
QDialog { background-color: #0d0d0d; }
QWidget#Central { background-color: #0d0d0d; }

/* 指标卡片：带深度感的圆角面板 */
QFrame#Card {
    background-color: #1e1e1e;
    border: 1px solid #333333;
    border-radius: 12px;
    padding: 4px;
}
QFrame#Card:hover {
    border: 1px solid #404040;
    background-color: #232323;
}

/* 卡片排版 */
QLabel#Title {
    font-weight: 600;
    font-size: 12pt;
    color: #b0b0b0;
    letter-spacing: 0.5px;
}
QLabel#Value {
    font-weight: 700;
    font-size: 22pt;
    color: #ffffff;
    letter-spacing: 0.3px;
}

/* 进度条 */
QProgressBar {
    background-color: #1a1a1a;
    border: 1px solid #2a2a2a;
    border-radius: 7px;
    height: 16px;
    text-align: center;
}
QProgressBar::chunk {
    background-color: #00c853;
    border-radius: 6px;
}

/* 顶栏（#TopBar 容器） */
#TopBar {
    background-color: #1a1a1a;
    spacing: 8px;
}
/* 圆角标签（配置对话框） */
QLabel#RoundedLabel {
    background-color: #252525;
    border: 1px solid #3a3a3a;
    border-radius: 4px;
    padding: 2px 8px;
    color: #e0e0e0;
}

#TopBar QLabel {
    color: #b0b0b0;
    font-size: 10pt;
    padding: 0 4px;
}
#TopBar QSpinBox {
    background-color: #252525;
    border: 1px solid #3a3a3a;
    border-radius: 4px;
    padding: 0 8px;
    color: #e0e0e0;
    min-width: 80px;
    height: 28px;
}
#TopBar QComboBox {
    background-color: #252525;
    border: 1px solid #3a3a3a;
    border-radius: 4px;
    padding: 0 8px;
    color: #e0e0e0;
    height: 28px;
}
#TopBar QCheckBox {
    background-color: #252525;
    border: 1px solid #3a3a3a;
    border-radius: 4px;
    padding: 0 8px;
    spacing: 4px;
    color: #e0e0e0;
    height: 28px;
}
#TopBar QCheckBox::indicator {
    width: 14px;
    height: 14px;
}
#TopBar QLineEdit {
    background-color: #252525;
    border: 1px solid #3a3a3a;
    border-radius: 4px;
    padding: 0 8px;
    color: #e0e0e0;
    height: 28px;
}
#TopBar QPushButton {
    background-color: #2a2a2a;
    border: 1px solid #3a3a3a;
    border-radius: 4px;
    padding: 0 12px;
    color: #e0e0e0;
    font-weight: 500;
    height: 28px;
}
#TopBar QPushButton:hover {
    background-color: #333333;
    border: 1px solid #4a4a4a;
}
QToolBar QPushButton:pressed {
    background-color: #202020;
}
QToolBar QPushButton#PauseButton {
    background-color: #1976d2;
    border: 1px solid #2196f3;
}
QToolBar QPushButton#PauseButton:hover {
    background-color: #2196f3;
}

/* 危险操作按钮：强烈警示色（删除/批量删除/合并重复等） */
QPushButton#DangerButton {
    background-color: #c62828;
    border: 1px solid #e53935;
    color: #ffffff;
    font-weight: 600;
    border-radius: 4px;
    height: 28px;
}
QPushButton#DangerButton:hover {
    background-color: #e53935;
}
QPushButton#DangerButton:pressed {
    background-color: #b71c1c;
}
/* 右栏按钮基础态：统一高度与圆角（避免 checked 态高度/圆角变化） */
#RightPanel QPushButton {
    background-color: #2a2a2a;
    border: 1px solid #3a3a3a;
    border-radius: 4px;
    color: #e0e0e0;
    height: 28px;
    padding: 0 8px;
}
#RightPanel QPushButton:hover {
    background-color: #333333;
    border: 1px solid #4a4a4a;
}
/* 右栏筛选按钮激活（checked）态：仅换强调色，高度/圆角保持不变 */
#RightPanel QPushButton:checked {
    background-color: #3584e4;
    border: 1px solid #5aa0ff;
    color: #ffffff;
    font-weight: 600;
    border-radius: 4px;
    height: 28px;
}
/* 全局输入控件圆角（高度由 #TopBar 精确锁定） */
QLineEdit, QComboBox, QSpinBox, QTextEdit {
    border-radius: 4px;
}
QTextEdit {
    background-color: #252525;
    border: 1px solid #3a3a3a;
    color: #e0e0e0;
    padding: 6px;
}
/* 复选框（启用）：给一个与输入框一致的深色背景块，保持视觉统一 */
QCheckBox {
    background-color: #252525;
    border: 1px solid #3a3a3a;
    border-radius: 4px;
    padding: 0 8px;
    height: 28px;
    spacing: 4px;
    color: #e0e0e0;
}
QCheckBox:hover {
    border: 1px solid #4a4a4a;
}
QCheckBox::indicator {
    width: 14px;
    height: 14px;
}

/* 标签页 */
QTabWidget::pane {
    border: 1px solid #2a2a2a;
    background-color: #141414;
    top: -1px;
}
QTabBar::tab {
    background: #1a1a1a;
    padding: 8px 16px;
    border: 1px solid #2a2a2a;
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    margin-right: 2px;
}
QTabBar::tab:selected {
    background: #2a2a2a;
    border-bottom: 2px solid #3584e4;
}
QTabBar::tab:hover:!selected {
    background: #222222;
}

/* 表格 */
QTableView {
    background-color: #1a1a1a;
    alternate-background-color: #1e1e1e;
    gridline-color: #2a2a2a;
    selection-background-color: #3584e4;
}
QTableWidget {
    background-color: #1a1a1a;
    alternate-background-color: #1e1e1e;
    gridline-color: #2a2a2a;
    selection-background-color: #3584e4;
}
QHeaderView::section {
    background-color: #252525;
    color: #b0b0b0;
    padding: 4px 6px;
    border: 1px solid #2a2a2a;
    font-weight: 600;
    height: 28px;
}
QTreeWidget { padding-left: 8px; }
QTreeWidget::item { height: 28px; border-radius: 4px; display: inline-block; min-width: 100%; }
QTreeWidget::item:selected { background-color: #3584e4; color: #ffffff; border-radius: 4px; }
QTreeWidget::item:selected:!active { background-color: #3584e4; color: #ffffff; border-radius: 4px; }
QTableView::item { padding-left: 10px; }
#TopBarSeparator { background-color: #2a2a2a; }
/* 左分组树：隐藏展开/折叠三角（层级靠缩进表达） */
QTreeView::branch,
QTreeWidget::branch {
    border-image: none;
    image: none;
}
QTreeView::branch:has-children:!has-siblings:closed,
QTreeView::branch:has-children:has-siblings:closed,
QTreeView::branch:open:has-children:!has-siblings,
QTreeView::branch:open:has-children:has-siblings,
QTreeWidget::branch:has-children:!has-siblings:closed,
QTreeWidget::branch:has-children:has-siblings:closed,
QTreeWidget::branch:open:has-children:!has-siblings,
QTreeWidget::branch:open:has-children:has-siblings {
    border-image: none;
    image: none;
}
/* 下拉框：圆角 + 取消下拉三角图标（功能保留，仅去视觉三角） */
QComboBox {
    border: 1px solid #3a3a3a;
}
QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 0px;
    border: none;
}
QComboBox::down-arrow {
    image: none;
    width: 0px;
    height: 0px;
}
QToolBar QComboBox::drop-down {
    width: 0px;
    border: none;
}
QToolBar QComboBox::down-arrow {
    image: none;
}
"""


# 全局样式表（浅色）
THEME_QSS_LIGHT = """
QWidget { background-color: #ffffff; color: #212121; }
QMainWindow { background-color: #f5f5f5; }
QDialog { background-color: #ffffff; }
QWidget#Central { background-color: #ffffff; }

/* 指标卡片：带深度感的圆角面板 */
QFrame#Card {
    background-color: #f0f0f0;
    border: 1px solid #e0e0e0;
    border-radius: 12px;
    padding: 4px;
}
QFrame#Card:hover {
    border: 1px solid #a0a0a0;
    background-color: #e8e8e8;
}

/* 卡片排版 */
QLabel#Title {
    font-weight: 600;
    font-size: 12pt;
    color: #616161;
    letter-spacing: 0.5px;
}
QLabel#Value {
    font-weight: 700;
    font-size: 22pt;
    color: #000000;
    letter-spacing: 0.3px;
}

/* 进度条 */
QProgressBar {
    background-color: #e0e0e0;
    border: 1px solid #d0d0d0;
    border-radius: 7px;
    height: 16px;
    text-align: center;
    color: #212121;
}
QProgressBar::chunk {
    background-color: #00c853;
    border-radius: 6px;
}

/* 顶栏（#TopBar 容器） */
#TopBar {
    background-color: #ffffff;
    spacing: 8px;
}
/* 圆角标签（配置对话框） */
QLabel#RoundedLabel {
    background-color: #e0e0e0;
    border: 1px solid #c0c0c0;
    border-radius: 4px;
    padding: 2px 8px;
    color: #212121;
}

#TopBar QLabel {
    color: #616161;
    font-size: 10pt;
    padding: 0 4px;
}
#TopBar QSpinBox {
    background-color: #ffffff;
    border: 1px solid #c0c0c0;
    border-radius: 4px;
    padding: 0 8px;
    color: #212121;
    min-width: 80px;
    height: 28px;
}
#TopBar QComboBox {
    background-color: #ffffff;
    border: 1px solid #c0c0c0;
    border-radius: 4px;
    padding: 0 8px;
    color: #212121;
    height: 28px;
}
#TopBar QCheckBox {
    background-color: #ffffff;
    border: 1px solid #c0c0c0;
    border-radius: 4px;
    padding: 0 8px;
    spacing: 4px;
    color: #212121;
    height: 28px;
}
#TopBar QCheckBox::indicator {
    width: 14px;
    height: 14px;
}
#TopBar QLineEdit {
    background-color: #ffffff;
    border: 1px solid #c0c0c0;
    border-radius: 4px;
    padding: 0 8px;
    color: #212121;
    height: 28px;
}
#TopBar QPushButton {
    background-color: #e0e0e0;
    border: 1px solid #c0c0c0;
    border-radius: 4px;
    padding: 0 12px;
    color: #212121;
    font-weight: 500;
    height: 28px;
}
#TopBar QPushButton:hover {
    background-color: #d0d0d0;
    border: 1px solid #b0b0b0;
}
QToolBar QPushButton:pressed {
    background-color: #c0c0c0;
}
QToolBar QPushButton#PauseButton {
    background-color: #1565c0;
    border: 1px solid #1e88e5;
}
QToolBar QPushButton#PauseButton:hover {
    background-color: #1e88e5;
}

/* 危险操作按钮：强烈警示色（删除/批量删除/合并重复等） */
QPushButton#DangerButton {
    background-color: #c62828;
    border: 1px solid #e53935;
    color: #ffffff;
    font-weight: 600;
    border-radius: 4px;
    height: 28px;
}
QPushButton#DangerButton:hover {
    background-color: #e53935;
}
QPushButton#DangerButton:pressed {
    background-color: #b71c1c;
}
/* 右栏按钮基础态：统一高度与圆角（避免 checked 态高度/圆角变化） */
#RightPanel QPushButton {
    background-color: #e0e0e0;
    border: 1px solid #c0c0c0;
    border-radius: 4px;
    color: #212121;
    height: 28px;
    padding: 0 8px;
}
#RightPanel QPushButton:hover {
    background-color: #d0d0d0;
    border: 1px solid #b0b0b0;
}
/* 右栏筛选按钮激活（checked）态：仅换强调色，高度/圆角保持不变 */
#RightPanel QPushButton:checked {
    background-color: #1976d2;
    border: 1px solid #1e88e5;
    color: #ffffff;
    font-weight: 600;
    border-radius: 4px;
    height: 28px;
}
/* 全局输入控件圆角（高度由 #TopBar 精确锁定） */
QLineEdit, QComboBox, QSpinBox, QTextEdit {
    border-radius: 4px;
}
QTextEdit {
    background-color: #ffffff;
    border: 1px solid #c0c0c0;
    color: #212121;
    padding: 6px;
}
/* 复选框（启用）：给一个与输入框一致的浅色背景块，保持视觉统一 */
QCheckBox {
    background-color: #ffffff;
    border: 1px solid #c0c0c0;
    border-radius: 4px;
    padding: 0 8px;
    height: 28px;
    spacing: 4px;
    color: #212121;
}
QCheckBox:hover {
    border: 1px solid #a0a0a0;
}
QCheckBox::indicator {
    width: 14px;
    height: 14px;
}

/* 标签页 */
QTabWidget::pane {
    border: 1px solid #d0d0d0;
    background-color: #ffffff;
    top: -1px;
}
QTabBar::tab {
    background: #f0f0f0;
    padding: 8px 16px;
    border: 1px solid #d0d0d0;
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    margin-right: 2px;
    color: #616161;
}
QTabBar::tab:selected {
    background: #ffffff;
    border-bottom: 2px solid #1976d2;
    color: #212121;
}
QTabBar::tab:hover:!selected {
    background: #e0e0e0;
}

/* 表格 */
QTableView {
    background-color: #ffffff;
    alternate-background-color: #f5f5f5;
    gridline-color: #e0e0e0;
    selection-background-color: #1976d2;
    color: #212121;
}
QTableWidget {
    background-color: #ffffff;
    alternate-background-color: #f5f5f5;
    gridline-color: #e0e0e0;
    selection-background-color: #1976d2;
    color: #212121;
}
QHeaderView::section {
    background-color: #e0e0e0;
    color: #616161;
    padding: 4px 6px;
    border: 1px solid #d0d0d0;
    font-weight: 600;
    height: 28px;
}
QTreeWidget { padding-left: 8px; }
QTreeWidget::item { height: 28px; border-radius: 4px; display: inline-block; min-width: 100%; }
QTreeWidget::item:selected { background-color: #1976d2; color: #ffffff; border-radius: 4px; }
QTreeWidget::item:selected:!active { background-color: #1976d2; color: #ffffff; border-radius: 4px; }
QTableView::item { padding-left: 10px; }
#TopBarSeparator { background-color: #d0d0d0; }
/* 左分组树：隐藏展开/折叠三角（层级靠缩进表达） */
QTreeView::branch,
QTreeWidget::branch {
    border-image: none;
    image: none;
}
QTreeView::branch:has-children:!has-siblings:closed,
QTreeView::branch:has-children:has-siblings:closed,
QTreeView::branch:open:has-children:!has-siblings,
QTreeView::branch:open:has-children:has-siblings,
QTreeWidget::branch:has-children:!has-siblings:closed,
QTreeWidget::branch:has-children:has-siblings:closed,
QTreeWidget::branch:open:has-children:!has-siblings,
QTreeWidget::branch:open:has-children:has-siblings {
    border-image: none;
    image: none;
}
/* 下拉框：圆角 + 取消下拉三角图标（功能保留，仅去视觉三角） */
QComboBox {
    border: 1px solid #c0c0c0;
}
QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 0px;
    border: none;
}
QComboBox::down-arrow {
    image: none;
    width: 0px;
    height: 0px;
}
QToolBar QComboBox::drop-down {
    width: 0px;
    border: none;
}
QToolBar QComboBox::down-arrow {
    image: none;
}
"""
