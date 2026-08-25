# -*- coding: utf-8 -*-
"""列宽铺满收敛回归（修复「打开 dict 文件末列被裁」）。

核心不变量：_fit_columns_to_view 在任何视口宽下都应保证
sum(列宽) <= 视口宽（除非视口窄到连 40px*列数 都放不下，那种极端情形由
ScrollBarAsNeeded 兜底）。本测试用受控视口宽直接验证收敛数学，不依赖 offscreen 布局。
"""
import os
import sys
import tempfile
import pathlib
from unittest import mock

RIMETOOL = str(pathlib.Path(__file__).resolve().parents[1])
if RIMETOOL not in sys.path:
    sys.path.insert(0, RIMETOOL)

from PyQt5.QtWidgets import QApplication  # noqa: E402
from ui.workspace_window import WorkspaceWindow  # noqa: E402


def _make_dict():
    content = (
        "---\nname: t\nversion: \"1.0\"\n...\n"
        "## g\n你\tni\t1\n好\thao\t2\n中\tzhong\t3\n"
    )
    f = tempfile.NamedTemporaryFile(suffix=".dict", delete=False, mode="w",
                                    encoding="utf-8")
    f.write(content)
    f.close()
    return f.name


def test_fit_no_overflow(app):
    path = _make_dict()
    try:
        win = WorkspaceWindow()
        win._load_dict(path)
        QApplication.processEvents()
        hdr = win.tableView.horizontalHeader()
        vp = win.tableView.viewport()
        n = hdr.count()
        # 各受控视口宽（均 >= 40*列数=120，故必须严格收敛到 <= 视口宽）
        for target in (150, 250, 400, 600, 900, 1400, 2000):
            with mock.patch.object(vp, "width", return_value=target):
                win._fit_columns_to_view()
                widths = [win.tableView.columnWidth(c) for c in range(n)]
                assert sum(widths) <= target, (target, widths)
                # 各列均 >= 下限 40，保证可读
                assert all(w >= 40 for w in widths), (target, widths)
    finally:
        os.unlink(path)
