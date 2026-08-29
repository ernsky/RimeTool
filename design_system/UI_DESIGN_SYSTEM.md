# System Monitor 深色 UI 设计系统（供 AI 设计参考）

> 本文档由 `system_monitor`（PySide6 + psutil 实时系统监视器）的 UI 反向提炼而来，
> 目标：让 AI（或开发者）在新建 / 改造任意桌面 UI 时，直接按本文参数产出**视觉一致**的深色界面。
> 配色、字体、间距、圆角均为显式定值；组件模式给出结构规范与可直接复用的代码。

---

## 0. 设计原则（先读这条）

1. **单色深色基底 + 单一强调蓝 + 每指标一色**。背景只用 4–5 档灰黑，靠边框分层；交互/选中用 `#3584e4`；每个监控项用自己的指标色（见 §2）。
2. **卡片化信息**。每项指标都是「标题 + 大数值 + 进度条 + 迷你曲线」的结构，格栅排布。
3. **克制的层级**。不用阴影、不用渐变；层次只靠 `背景明度差 + 1px 边框 + 选中态下划线`。
4. **实时优先**。曲线关动画（`NoAnimation`）、透明背景融入面板、滑动窗口固定点数（默认 60 卡 / 400 图）、百分比固定 y 轴、吞吐 auto_scale。
5. **阈值即颜色**。进度条 ≥80% 转橙、≥90% 转红，无需额外文字告警。

---

## 1. 颜色令牌（Color Tokens）

```
背景（由深到浅）
  BG_WINDOW       #0d0d0d   主窗口背景 (QMainWindow)
  BG_APP          #121212   通用控件背景 (QWidget)
  BG_PANEL        #1a1a1a   工具栏、表格背景
  BG_CARD         #1e1e1e   指标卡片面、表格交替行
  BG_CARD_HOVER   #232323   卡片 hover 背景
  BG_ELEVATED     #252525   表头、输入框背景
  BG_ACCENT       #2a2a2a   按钮、选中标签背景

边框
  BORDER          #2a2a2a   通用边框 / 表格网格线 / 标签栏分隔
  BORDER_CARD     #333333   卡片边框
  BORDER_INPUT    #3a3a3a   输入框 / SpinBox 边框
  BORDER_HOVER    #404040   卡片 hover 边框
  BORDER_BTN_HOVER#4a4a4a   按钮 hover 边框

文字
  TEXT_PRIMARY    #e0e0e0   正文 / 数值
  TEXT_SECONDARY  #b0b0b0   标签 / 标题 / 工具栏文字
  TEXT_MUTED      #909090   频率副标
  TEXT_MUTED2     #808080   型号副标（斜体）
  TEXT_VALUE      #ffffff   卡片大数值
  TEXT_BRIGHT     #ff0000   告警亮色 (BrightText)

强调
  ACCENT          #3584e4   高亮 / 表格选区 / 标签选中下划线
  ACCENT_BTN      #1976d2   主操作钮底色（如 暂停）
  ACCENT_BTN_HOVER #2196f3  主操作钮 hover

指标色（每个监控项固定一色，全局统一）
  METRIC_CPU         #00c853  绿
  METRIC_MEM         #ffd54f  黄
  METRIC_NET_UP      #2962ff  蓝
  METRIC_NET_DOWN    #ff5252  红
  METRIC_DISK_READ   #00bcd4  青
  METRIC_DISK_WRITE  #ab47bc  紫
  METRIC_GPU         #7c4dff  深紫

阈值告警色
  THRESHOLD_WARN = 80   → COLOR_WARN  #ff9800  橙
  THRESHOLD_CRIT = 90   → COLOR_CRIT  #f44336  红

每核色板（循环取用，最多 12 色；第 13 核回到第 1 色）
  #e53935 #8e24aa #3949ab #1e88e5 #00897b #43a047
  #fdd835 #fb8c00 #6d4c41 #546e7a #d81b60 #00acc1
```

---

## 2. 字体令牌（Typography）

系统默认无衬线字体，**不自定义 font-family**，只设字号 / 字重 / 字色 / 字距。

```
卡片标题   Title   12pt / 600 / #b0b0b0 / letter-spacing 0.5px
卡片数值   Value   22pt / 700 / #ffffff / letter-spacing 0.3px
次级标签          9pt  / #b0b0b0   （工具栏、副信息）
弱标签            8pt  / #909090（频率）/ #808080 斜体（型号）
工具栏标签       10pt / #b0b0b0
```

---

## 3. 间距与圆角（Spacing & Radius）

```
间距（px）
  SPACING_CARD     12    卡片内边距 (padding: 12 12 12 12)
  SPACING_INNER    8     卡片内部控件间距
  SPACING_GRID     12    仪表盘网格间距
  SPACING_TOOLBAR  8     工具栏控件间距
  TOOLBAR_PADDING  8     工具栏内边距 (8px)
  CARD_PADDING     4     QSS 中 QFrame#Card padding
  TAB_PADDING      8px 16px  标签内边距
  CHART_MARGIN     8     主图边距
  CHART_MARGIN_MINI 4    迷你图边距

圆角（px）
  RADIUS_CARD      12    卡片
  RADIUS_BAR       7     进度条外框
  RADIUS_BAR_CHUNK 6     进度条填充
  RADIUS_TAB       6     标签顶部
  RADIUS_INPUT     4     输入框 / SpinBox
  RADIUS_BTN       4     按钮

尺寸
  PROGRESS_BAR_HEIGHT 16  进度条高
```

---

## 4. 全局样式（Global QSS）

应用 `Fusion` 风格 + 上述调色板；以下 QSS 直接可用（颜色已对齐 §1）：

```css
QWidget { background-color: #121212; color: #e0e0e0; }
QMainWindow { background-color: #0d0d0d; }

/* 卡片：圆角面板 + hover 微亮 */
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
QLabel#Title { font-weight: 600; font-size: 12pt; color: #b0b0b0; letter-spacing: 0.5px; }
QLabel#Value { font-weight: 700; font-size: 22pt; color: #ffffff; letter-spacing: 0.3px; }

/* 进度条 */
QProgressBar {
  background-color: #1a1a1a; border: 1px solid #2a2a2a;
  border-radius: 7px; height: 16px; text-align: center;
}
QProgressBar::chunk { background-color: #00c853; border-radius: 6px; }

/* 工具栏 */
QToolBar { background-color: #1a1a1a; border-bottom: 2px solid #2a2a2a; spacing: 8px; padding: 8px; }
QToolBar QLabel { color: #b0b0b0; font-size: 10pt; padding: 0 4px; }
QToolBar QSpinBox { background-color: #252525; border: 1px solid #3a3a3a; border-radius: 4px; padding: 4px 8px; color: #e0e0e0; min-width: 80px; }
QToolBar QPushButton { background-color: #2a2a2a; border: 1px solid #3a3a3a; border-radius: 4px; padding: 6px 12px; color: #e0e0e0; font-weight: 500; }
QToolBar QPushButton:hover { background-color: #333333; border: 1px solid #4a4a4a; }
QToolBar QPushButton:pressed { background-color: #202020; }
QToolBar QPushButton#PauseButton { background-color: #1976d2; border: 1px solid #2196f3; }
QToolBar QPushButton#PauseButton:hover { background-color: #2196f3; }

/* 标签栏 */
QTabWidget::pane { border: 1px solid #2a2a2a; background-color: #141414; top: -1px; }
QTabBar::tab { background: #1a1a1a; padding: 8px 16px; border: 1px solid #2a2a2a; border-bottom: none; border-top-left-radius: 6px; border-top-right-radius: 6px; margin-right: 2px; }
QTabBar::tab:selected { background: #2a2a2a; border-bottom: 2px solid #3584e4; }
QTabBar::tab:hover:!selected { background: #222222; }

/* 表格 */
QTableWidget { background-color: #1a1a1a; alternate-background-color: #1e1e1e; gridline-color: #2a2a2a; selection-background-color: #3584e4; }
QHeaderView::section { background-color: #252525; color: #b0b0b0; padding: 6px; border: 1px solid #2a2a2a; font-weight: 600; }
```

---

## 5. 组件模式（Component Patterns）

### 5.1 MetricCard（指标卡片）
**结构（自上而下）**：`Title` → `Value(大字)` → （可选）`频率 ⚡ MHz` → （可选）`型号 🔹 斜体` → `进度条` → `迷你曲线(sparkline)`。
**参数化**：`title / unit / is_percent / color / sparkline / max_points`。
**规则**：
- 百分比指标：进度条 0–100、sparkline 关 auto_scale、阈值色随 `update_percent` 切换（≥80 橙、≥90 红）。
- 非百分比（吞吐）：进度条按 `ref_max` 或动态上限归一化、sparkline 开 auto_scale。
- 卡片对象名 `objectName("Card")` 才能命中 §4 的 QSS；标题 `Title`、数值 `Value` 同理。

### 5.2 TimeSeriesChart（实时曲线）
**结构**：`QChart(ChartThemeDark)` + `QChartView`；底部图例、关动画、透明背景、抗锯齿、矩形框选缩放。
**参数化**：`title / series_names / max_points(默认400) / y_range / auto_scale`。
**规则**：
- 百分比类：`y_range=(0,100)`、`auto_scale=False`。
- 吞吐类：`y_range=(0,10)`、`auto_scale=True`（上限随数据 ×1.2 放大）。
- 滑动窗口：`append(values)` 每帧_push 并截到 `max_points`；x 轴窗口跟随 `_x` 平移。

### 5.3 图表工厂（通用）
`create_time_series_chart(title, series_names, y_range, auto_scale, max_points)` —— 禁止把 CPU/内存等专属配置写死进工厂，调用方传参。

### 5.4 工具栏
不可移动、不可浮动；左到右：间隔 SpinBox（全局）→ 分隔符 → GPU 刷新 SpinBox → 进程刷新 SpinBox → 分隔符 → 主操作钮（暂停，蓝色 `#1976d2`）。
控件间距 8、内边距 8（由 §4 QSS 控制）。

### 5.5 仪表盘布局
`QGridLayout` 2 列，`spacing=12`；GPU 卡 `addWidget(card, row, col, 1, 2)` 跨整行。

### 5.6 每核迷你图网格
列数 `min(4, max(1, ⌊√n⌋+1))`；外层套 `QScrollArea(setWidgetResizable=True)`；每核一条 `TimeSeriesChart`（关坐标轴、margin 4、隐藏图例）；下方居中频率标签 `QLabel("NNN MHz")`、`8pt #b0b0b0`。

### 5.7 表格 / 树
`alternatingRowColors=True`；表头 `Interactive` 可调宽、`setSectionsClickable(True)`；选区色 `#3584e4`。

---

## 6. 可复用代码（PySide6）

> 已提炼为独立包 `design_system/`，位于原项目 `design_system/` 目录。
> 任意 Qt 项目：`pip install PySide6` 后把该目录作为包引入即可。

```python
from PySide6.QtWidgets import QApplication, QMainWindow
from design_system import apply_dark_theme, MetricCard, create_time_series_chart, style_toolbar

app = QApplication(sys.argv)
apply_dark_theme(app)                 # 套全局深色主题 + QSS

# 指标卡
cpu = MetricCard("CPU", unit="%", is_percent=True, color="#00c853")
cpu.update_percent(42.5)              # 自动按阈值变色

# 曲线
chart = create_time_series_chart("CPU Utilization", ["CPU %"], y_range=(0, 100))
chart.append([42.5])
```

`design_system/` 包结构：
```
design_system/
├── __init__.py        # 统一导出令牌 + 组件 + apply_dark_theme / style_toolbar
├── tokens.py          # §1–§3 全部常量
├── theme.py           # apply_dark_theme() + THEME_QSS + style_toolbar()
├── widgets.py         # MetricCard / TimeSeriesChart
├── charts.py          # create_time_series_chart()
└── example.py         # 最小可运行演示
```

---

## 7. AI 设计检查清单（交付前自检）

- [ ] 背景只用 §1 的灰黑档，未引入新背景色（除指标色）
- [ ] 所有边框为 §1 的 BORDER_*，圆角取自 §3 RADIUS_*
- [ ] 大数值用 `Value` 样式（22pt/700/白），标题用 `Title` 样式
- [ ] 进度条 0–100、≥80 橙 / ≥90 红
- [ ] 指标色全局统一，未为同一指标用两种色
- [ ] 曲线关闭动画、透明背景、百分比固定 y、吞吐 auto_scale
- [ ] 卡片对象名为 `Card`、标题 `Title`、数值 `Value`（命中 QSS）
- [ ] 未使用阴影 / 渐变（设计原则 #3）
- [ ] 主操作钮为蓝色 `#1976d2`（若有的话）
```
