"""通用图表工厂（PySide6 / Qt）。

提供 create_time_series_chart 统一构造 TimeSeriesChart，避免在每个项目里
重复写死 CPU / 内存等专属配置。
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from .widgets import TimeSeriesChart


def create_time_series_chart(
    title: str,
    series_names: List[str],
    y_range: Optional[Tuple[float, float]] = (0.0, 100.0),
    auto_scale: bool = False,
    max_points: int = 400,
) -> TimeSeriesChart:
    """构造一个时间序列曲线组件。

    参数：
        title: 图表标题（显示在图例上方）
        series_names: 数据系列名列表（每条线对应一项）
        y_range: y 轴固定范围；传 None 则回退到 (0, 100)。
                 百分比类用 (0, 100)，吞吐类用较小固定值并配合 auto_scale=True
        auto_scale: True 时 y 轴上限随数据自动放大（适合无上限的吞吐指标）
        max_points: 滑动窗口保留的最大采样点数

    示例：
        chart = create_time_series_chart("CPU Utilization", ["CPU %"], y_range=(0, 100))
        net = create_time_series_chart("Net (MiB/s)", ["Up", "Down"],
                                       y_range=(0, 10), auto_scale=True)
    """
    return TimeSeriesChart(
        title, series_names, max_points=max_points, y_range=y_range, auto_scale=auto_scale
    )
