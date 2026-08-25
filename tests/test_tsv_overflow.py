# -*- coding: utf-8 -*-
"""M3 回归：加载含超过 5 列的行时，统计超列行数并经 extras 透出，而非静默丢列。

依赖 PyQt5（offscreen），由 conftest.py 提供 QApplication 实例（app fixture）。
"""
import sys
import pathlib

RIMETOOL = str(pathlib.Path(__file__).resolve().parents[1])
if RIMETOOL not in sys.path:
    sys.path.insert(0, RIMETOOL)

from PyQt5.QtCore import QEventLoop  # noqa: E402

from core.io_tsv import LoadThread  # noqa: E402


def _run_loader(path, app):
    th = LoadThread(path)
    captured = {}

    def on_loaded(data, total, extras):
        captured["data"] = data
        captured["total"] = total
        captured["extras"] = extras

    th.loaded.connect(on_loaded)
    th.error.connect(lambda msg: captured.update(error=msg))
    th.finished.connect(th.deleteLater)
    th.start()
    loop = QEventLoop()
    th.finished.connect(loop.quit)
    loop.exec_()
    return captured


def test_overflow_columns_counted(app, tmp_path):
    p = tmp_path / "over.tsv"
    # 2 行 5 列（正常）+ 1 行 7 列（超列）
    lines = [
        "词一\ta\t1\tA 词库\tA",
        "词二\tb\t2\tB 词库\tB",
        "词三\tc\t3\tC 词库\tC\textra1\textra2",   # 7 列
    ]
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    cap = _run_loader(str(p), app)
    assert cap.get("error") is None, cap
    data = cap["data"]
    assert len(data) == 3
    # 每行仍被截断为 5 列（schema 容差外列已忽略，但不应崩/丢行）
    assert all(len(r) == 5 for r in data)
    assert data[2][0] == "词三" and data[2][4] == "C"
    # 超列行数经 extras 透出，供 UI 持久告警
    assert (cap["extras"] or {}).get("overflow_lines", 0) == 1


def test_no_overflow_when_exactly_five(app, tmp_path):
    p = tmp_path / "ok.tsv"
    p.write_text("词一\ta\t1\tA 词库\tA\n", encoding="utf-8")
    cap = _run_loader(str(p), app)
    assert cap.get("error") is None, cap
    assert len(cap["data"]) == 1
    assert (cap["extras"] or {}).get("overflow_lines", 0) == 0
