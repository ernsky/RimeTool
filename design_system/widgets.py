"""通用深色 UI 组件（PySide6 / Qt）。

提炼自 system_monitor 项目，参数化后可在任意 Qt 项目复用：
- MetricCard：指标卡片（标题 + 大数值 + 频率/型号副标 + 进度条 + 迷你曲线）
- TimeSeriesChart：实时时间序列曲线（深色主题、可滑动窗口、固定/自动 y 轴）
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from PySide6.QtCore import Qt, QPointF, QMargins
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QProgressBar, QSizePolicy, QFrame,
)
from PySide6.QtCharts import QChart, QChartView, QLineSeries, QValueAxis

from .tokens import METRIC_CPU, TEXT_MUTED, TEXT_MUTED2


class MetricCard(QWidget):
    """指标卡片：把一项指标以「标题 + 大数值 + 进度条 + 迷你曲线」呈现。

    参数：
        title: 卡片标题（如 "CPU"）
        unit: 数值单位（如 "%"、"MiB/s"）
        is_percent: True 表示百分比指标，进度条与 y 轴固定 0–100
        color: 进度条 / 曲线主色（默认绿色 #00c853）
        sparkline: 是否显示底部迷你曲线
        max_points: 迷你曲线滑动窗口保留的最大采样点数
    """

    def __init__(
        self,
        title: str,
        unit: str = "",
        is_percent: bool = False,
        color: str = METRIC_CPU,
        sparkline: bool = True,
        max_points: int = 60,
    ) -> None:
        super().__init__()
        self.is_percent = is_percent
        self.unit = unit
        self.color = color
        self._dyn_max: float = 10.0 if not is_percent else 100.0

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.frame = QFrame()
        self.frame.setObjectName("Card")
        outer.addWidget(self.frame)

        v = QVBoxLayout(self.frame)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(8)

        self.lbl_title = QLabel(title)
        self.lbl_title.setObjectName("Title")
        self.lbl_value = QLabel(("-- " + unit).strip())
        self.lbl_value.setObjectName("Value")
        v.addWidget(self.lbl_title)
        v.addWidget(self.lbl_value)

        self.lbl_frequency = QLabel("")
        self.lbl_frequency.setStyleSheet("QLabel { color: #909090; font-size: 9pt; }")
        self.lbl_frequency.setVisible(False)
        v.addWidget(self.lbl_frequency)

        self.lbl_model = QLabel("")
        self.lbl_model.setStyleSheet(
            "QLabel { color: #808080; font-size: 8pt; font-style: italic; }"
        )
        self.lbl_model.setWordWrap(True)
        self.lbl_model.setVisible(False)
        v.addWidget(self.lbl_model)

        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setStyleSheet(
            f"QProgressBar::chunk{{background-color:{color}; border-radius:6px;}}"
        )
        v.addWidget(self.bar)

        self.sparkline: Optional[TimeSeriesChart] = None
        if sparkline:
            self.sparkline = TimeSeriesChart(
                "",
                [title],
                max_points=max_points,
                y_range=(0, 100 if is_percent else 1),
                auto_scale=(not is_percent),
            )
            self.sparkline.chart.legend().setVisible(False)
            self.sparkline.chart.setTitle("")
            self.sparkline.axis_x.setVisible(False)
            self.sparkline.axis_y.setVisible(False)
            self.sparkline.chart.setMargins(QMargins(0, 0, 0, 0))
            v.addWidget(self.sparkline)

        sp = QSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self.setSizePolicy(sp)

    def set_tooltip(self, text: str) -> None:
        """为卡片整体及关键子控件设置 tooltip。"""
        self.setToolTip(text)
        self.frame.setToolTip(text)
        self.lbl_value.setToolTip(text)
        self.lbl_title.setToolTip(text)

    def set_unavailable(self, message: str = "N/A") -> None:
        """标记指标不可用（如未检测到 GPU）。"""
        self.lbl_value.setText(message)
        self.bar.setValue(0)

    def set_frequency(self, freq_mhz: float) -> None:
        """设置频率显示（MHz），>0 时显示 ⚡ 前缀。"""
        if freq_mhz > 0:
            self.lbl_frequency.setText(f"\u26a1 {freq_mhz:.0f} MHz")
            self.lbl_frequency.setVisible(True)
        else:
            self.lbl_frequency.setVisible(False)

    def set_model(self, model_name: str) -> None:
        """设置型号/品牌名称显示（如 "RTX 3090"）。"""
        if model_name and model_name.strip():
            self.lbl_model.setText(f"\U0001f539 {model_name.strip()}")
            self.lbl_model.setVisible(True)
        else:
            self.lbl_model.setVisible(False)

    def update_percent(self, pct: float) -> None:
        """更新百分比指标，并按阈值切换进度条颜色（≥80 橙 / ≥90 红）。"""
        try:
            pct_f = max(0.0, min(100.0, float(pct)))
        except Exception:
            pct_f = 0.0
        self.lbl_value.setText(f"{pct_f:.1f} %")
        self.bar.setValue(int(round(pct_f)))

        if pct_f >= 90.0:
            self.bar.setStyleSheet(
                "QProgressBar::chunk{background-color:#f44336; border-radius:6px;}"
            )
        elif pct_f >= 80.0:
            self.bar.setStyleSheet(
                "QProgressBar::chunk{background-color:#ff9800; border-radius:6px;}"
            )
        else:
            self.bar.setStyleSheet(
                f"QProgressBar::chunk{{background-color:{self.color}; border-radius:6px;}}"
            )

        if self.sparkline is not None:
            self.sparkline.append([pct_f])

    def update_value(self, value: float, ref_max: Optional[float] = None) -> None:
        """更新非百分比指标（如吞吐），进度条按 ref_max 或动态上限归一化。"""
        try:
            v = float(value)
        except Exception:
            v = 0.0
        self.lbl_value.setText(f"{v:.2f} {self.unit}".strip())
        if self.is_percent:
            m = 100.0
        else:
            if ref_max is None:
                self._dyn_max = max(v, self._dyn_max * 0.98)
                m = max(self._dyn_max, 1e-6)
            else:
                m = max(ref_max, 1e-6)
        pct = (
            int(round(max(0.0, min(100.0, (v / m) * 100.0)))) if m > 0 else 0
        )
        self.bar.setValue(pct)
        if self.sparkline is not None:
            self.sparkline.append([v])


class TimeSeriesChart(QWidget):
    """实时时间序列曲线组件。

    基于 QtCharts，深色主题、关闭动画、透明背景、底部图例、抗锯齿、框选缩放。
    支持固定 y 轴范围或随数据自动放大（auto_scale），适合吞吐类无上限指标。

    参数：
        title: 图表标题
        series_names: 系列名列表（每条线对应一项）
        max_points: 滑动窗口保留的最大采样点数
        y_range: y 轴固定范围；传 None 则回退到 (0, 100)
        auto_scale: True 时 y 轴上限随当前数据最大值 ×1.2 放大
    """

    def __init__(
        self,
        title: str,
        series_names: List[str],
        max_points: int = 400,
        y_range: Optional[Tuple[float, float]] = (0.0, 100.0),
        auto_scale: bool = False,
    ) -> None:
        super().__init__()
        self.max_points = max_points
        self.auto_scale = auto_scale
        self._x: int = 0

        layout = QVBoxLayout(self)
        self.chart = QChart()
        self.chart.setTheme(QChart.ChartThemeDark)
        self.chart.setTitle(title)
        self.chart.legend().setVisible(True)
        self.chart.legend().setAlignment(Qt.AlignBottom)
        self.chart.setAnimationOptions(QChart.NoAnimation)
        self.chart.setBackgroundVisible(False)
        self.chart.setMargins(QMargins(8, 8, 8, 8))

        self.series: List[QLineSeries] = []
        for name in series_names:
            s = QLineSeries()
            s.setName(name)
            self.chart.addSeries(s)
            self.series.append(s)

        self.axis_x = QValueAxis()
        self.axis_x.setTitleText("Samples")
        self.axis_x.setRange(0, max_points)
        self.axis_x.setTickCount(6)
        self.chart.addAxis(self.axis_x, Qt.AlignBottom)
        for s in self.series:
            s.attachAxis(self.axis_x)

        self.axis_y = QValueAxis()
        self.axis_y.setTitleText("Value")
        if y_range is not None:
            self.axis_y.setRange(y_range[0], y_range[1])
        else:
            self.axis_y.setRange(0, 100)
        self.axis_y.setTickCount(6)
        self.chart.addAxis(self.axis_y, Qt.AlignLeft)
        for s in self.series:
            s.attachAxis(self.axis_y)

        self.view = QChartView(self.chart)
        self.view.setRenderHint(QPainter.Antialiasing, True)
        self.view.setRubberBand(QChartView.RectangleRubberBand)
        self.view.setStyleSheet("background-color: transparent;")
        layout.addWidget(self.view)

        self._buffers: List[List[QPointF]] = [[] for _ in self.series]

        sp = QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setSizePolicy(sp)

    def append(self, values: List[float]) -> None:
        """追加一帧采样值（每条线一个），并刷新滑动窗口与 x 轴范围。"""
        n = min(len(values), len(self.series))
        self._x += 1
        x0 = max(0, self._x - self.max_points)
        for i in range(n):
            buf = self._buffers[i]
            buf.append(QPointF(float(self._x), float(values[i])))
            if len(buf) > self.max_points:
                del buf[: len(buf) - self.max_points]
            self.series[i].replace(buf)

        self.axis_x.setRange(x0, x0 + self.max_points)

        if self.auto_scale:
            current_max = 1.0
            for buf in self._buffers:
                if buf:
                    m = max(p.y() for p in buf)
                    if m > current_max:
                        current_max = m
            self.axis_y.setRange(0, current_max * 1.2)
