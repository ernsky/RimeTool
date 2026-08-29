"""设计令牌（Design Tokens）。

把 system_monitor 的深色 UI 主题中所有硬编码的颜色、字体、间距、圆角、
指标色、阈值色提取为命名常量，供未来 PySide6 / Qt 项目直接复用。

所有值为纯字符串 / 数字，不依赖 PySide6，因此本模块可在任何 Python 环境 import。
"""

# ---------- 背景色 ----------
BG_WINDOW = "#0d0d0d"         # 主窗口背景（QMainWindow）
BG_APP = "#121212"            # 通用控件背景（全局 QWidget）
BG_PANEL = "#1a1a1a"          # 工具栏、表格背景
BG_CARD = "#1e1e1e"           # 指标卡片面、表格交替行
BG_CARD_HOVER = "#232323"     # 卡片 hover 背景
BG_ELEVATED = "#252525"       # 表头、输入框背景
BG_ACCENT = "#2a2a2a"         # 按钮、选中标签背景

# ---------- 边框色 ----------
BORDER = "#2a2a2a"            # 通用边框、表格网格线、标签栏分隔
BORDER_CARD = "#333333"       # 卡片边框
BORDER_INPUT = "#3a3a3a"      # 输入框 / SpinBox 边框
BORDER_HOVER = "#404040"      # 卡片 hover 边框
BORDER_BTN_HOVER = "#4a4a4a"  # 按钮 hover 边框

# ---------- 文字色 ----------
TEXT_PRIMARY = "#e0e0e0"      # 正文 / 数值
TEXT_SECONDARY = "#b0b0b0"    # 标签 / 标题 / 工具栏文字
TEXT_MUTED = "#909090"        # 频率副标
TEXT_MUTED2 = "#808080"       # 型号副标（斜体）
TEXT_VALUE = "#ffffff"        # 卡片大数值
TEXT_BRIGHT = "#ff0000"       # 告警亮色（BrightText）

# ---------- 强调色 ----------
ACCENT = "#3584e4"            # 高亮 / 表格选区 / 标签选中下划线
ACCENT_BTN = "#1976d2"        # 暂停钮底色
ACCENT_BTN_HOVER = "#2196f3"  # 暂停钮 hover

# ---------- 指标色（各监控项主色）----------
METRIC_CPU = "#00c853"
METRIC_MEM = "#ffd54f"
METRIC_NET_UP = "#2962ff"
METRIC_NET_DOWN = "#ff5252"
METRIC_DISK_READ = "#00bcd4"
METRIC_DISK_WRITE = "#ab47bc"
METRIC_GPU = "#7c4dff"

# ---------- 阈值告警色 ----------
THRESHOLD_WARN = 80           # 进度条 ≥ 80% 转橙
THRESHOLD_CRIT = 90           # 进度条 ≥ 90% 转红
COLOR_WARN = "#ff9800"
COLOR_CRIT = "#f44336"

# ---------- 每核色板（循环取用，最多 12 色）----------
CORE_PALETTE = [
    "#e53935", "#8e24aa", "#3949ab", "#1e88e5",
    "#00897b", "#43a047", "#fdd835", "#fb8c00",
    "#6d4c41", "#546e7a", "#d81b60", "#00acc1",
]

# ---------- 字体 ----------
FONT_TITLE_SIZE = "12pt"
FONT_TITLE_WEIGHT = 600
FONT_TITLE_COLOR = TEXT_SECONDARY
FONT_TITLE_SPACING = "0.5px"

FONT_VALUE_SIZE = "22pt"
FONT_VALUE_WEIGHT = 700
FONT_VALUE_COLOR = TEXT_VALUE
FONT_VALUE_SPACING = "0.3px"

FONT_SECONDARY_SIZE = "9pt"
FONT_MUTED_SIZE = "8pt"
FONT_SECONDARY_COLOR = TEXT_SECONDARY

# ---------- 间距（像素）----------
SPACING_CARD = 12             # 卡片内边距
SPACING_INNER = 8             # 卡片内部控件间距
SPACING_GRID = 12             # 仪表盘网格间距
SPACING_TOOLBAR = 8           # 工具栏控件间距
TOOLBAR_PADDING = 8           # 工具栏内边距
CARD_PADDING = 12             # 卡片 padding（QSS）
TAB_PADDING = "8px 16px"      # 标签内边距
CHART_MARGIN = 8              # 主图边距
CHART_MARGIN_MINI = 4         # 迷你图边距
CONTROL_HEIGHT = 28          # 统一控件高度（按钮/输入框/表头/分组标签）

# ---------- 圆角（像素）----------
RADIUS_CARD = 12
RADIUS_BAR = 7
RADIUS_BAR_CHUNK = 6
RADIUS_TAB = 6
RADIUS_INPUT = 4
RADIUS_BTN = 4

# ---------- 布局 ----------
DASHBOARD_COLS = 2            # 仪表盘列数
CORE_GRID_MAX_COLS = 4        # 每核图每行最多列数
UPDATE_INTERVAL_MS = 100      # 默认刷新间隔

# ---------- 进度条 ----------
PROGRESS_BAR_HEIGHT = 16

# ---------- 浅色主题令牌 ----------
BG_WINDOW_LIGHT = "#f5f5f5"
BG_APP_LIGHT = "#ffffff"
BG_PANEL_LIGHT = "#ffffff"
BG_CARD_LIGHT = "#f0f0f0"
BG_CARD_HOVER_LIGHT = "#e8e8e8"
BG_ELEVATED_LIGHT = "#ffffff"
BG_ACCENT_LIGHT = "#e0e0e0"

BORDER_LIGHT = "#d0d0d0"
BORDER_CARD_LIGHT = "#e0e0e0"
BORDER_INPUT_LIGHT = "#c0c0c0"
BORDER_HOVER_LIGHT = "#a0a0a0"
BORDER_BTN_HOVER_LIGHT = "#b0b0b0"

TEXT_PRIMARY_LIGHT = "#212121"
TEXT_SECONDARY_LIGHT = "#616161"
TEXT_MUTED_LIGHT = "#9e9e9e"
TEXT_MUTED2_LIGHT = "#bdbdbd"
TEXT_VALUE_LIGHT = "#000000"
TEXT_BRIGHT_LIGHT = "#ff0000"

ACCENT_LIGHT = "#1976d2"
ACCENT_BTN_LIGHT = "#1565c0"
ACCENT_BTN_HOVER_LIGHT = "#1e88e5"
