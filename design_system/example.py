"""最小演示：证明 design_system 可直接套用，无需拷贝原项目代码。

运行（需图形环境）：
    cd system_monitor-master
    python -m design_system.example

在无显示的服务器上只做语法校验，不实际启动 GUI。
"""

from __future__ import annotations

import sys

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QGridLayout,
)

from design_system import (
    apply_dark_theme,
    MetricCard,
    create_time_series_chart,
    style_toolbar,
    METRIC_CPU,
    METRIC_MEM,
    METRIC_NET_UP,
)


class DemoWindow(QMainWindow):
    """演示窗口：一张仪表盘网格（3 张卡）+ 一张实时曲线。"""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("design_system 演示")
        self.resize(900, 600)

        toolbar = self.addToolBar("Controls")
        style_toolbar(toolbar)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        grid = QGridLayout()
        grid.setSpacing(12)
        card_cpu = MetricCard("CPU", unit="%", is_percent=True, color=METRIC_CPU)
        card_mem = MetricCard("Memory", unit="%", is_percent=True, color=METRIC_MEM)
        card_net = MetricCard("Net Up", unit="MiB/s", is_percent=False, color=METRIC_NET_UP)
        grid.addWidget(card_cpu, 0, 0)
        grid.addWidget(card_mem, 0, 1)
        grid.addWidget(card_net, 1, 0)
        root.addLayout(grid)

        chart = create_time_series_chart("CPU Utilization", ["CPU %"], y_range=(0, 100))
        root.addWidget(chart)

        # 保存引用，便于外部用 update_percent / append 推数据
        self.card_cpu = card_cpu
        self.chart = chart


def main() -> None:
    app = QApplication(sys.argv)
    apply_dark_theme(app)
    win = DemoWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
