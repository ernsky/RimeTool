# -*- coding: utf-8 -*-
"""拖拽防御修复回归测试（防御修复①/②，2026-08-23）。

锁定两件事，避免后续误改回旧行为：
1. DictModel.reorder_view_rows / move_selected_to_group 的返回值是
   防御修复①（拖完迁移选区）依赖的契约：
   - reorder_view_rows 返回 (移动条数, 重排后的新连续可见行号列表)
   - move_selected_to_group 返回 (变更条数, 首个被改动的可见行号)
2. DragController.drag_dropped 信号签名为 3 参 (target, before, new_rows)，
   UI 的 _on_drag_dropped 据此把选区迁到拖拽后的新位置。
"""
import pathlib
import sys

RIMETOOL = str(pathlib.Path(__file__).resolve().parents[1])
if RIMETOOL not in sys.path:
    sys.path.insert(0, RIMETOOL)

from core.dict_model import DictModel  # noqa: E402
from ui.drag_controller import DragController  # noqa: E402
from PyQt5.QtWidgets import QTableView  # noqa: E402


def _sample(n=12):
    return [("词组%d" % i, "code%d" % i, str(100 + i), "A 词库", "A") for i in range(n)]


def _data_view_rows(m, n=2):
    """取前 n 个数据行（非分组头）的显示行号。"""
    out = []
    for vr, el in enumerate(m._order):
        if isinstance(el, int):
            out.append(vr)
        if len(out) >= n:
            break
    return out


def test_reorder_view_rows_returns_new_view_rows():
    m = DictModel()
    m.set_all_data(_sample(12), 12)
    # 取前两个数据行：把第一个拖到第二个数据行之前
    d = _data_view_rows(m, 2)
    src = [d[0]]
    moved, new_rows = m.reorder_view_rows(src, d[1], True)
    assert moved == 1
    assert len(new_rows) == 1
    # 新位置上的词应当是被移动的词组
    assert m.get_field(new_rows[0], "词组") == "词组0"


def test_move_selected_to_group_returns_first_row():
    m = DictModel()
    m.set_all_data(_sample(12), 12)
    # 取前两个数据行移动到新分组
    d = _data_view_rows(m, 2)
    changed, first = m.move_selected_to_group(d, "B 人名", enable_value="A")
    assert changed == 2
    assert first >= 0
    # 首个被改行的词组仍正确
    assert m.get_field(first, "词组") == "词组0"
    # 这些行的分组已被改写
    assert m.get_field(first, "分组") == "B 人名"


def test_drag_dropped_signal_carries_three_args(app):
    """信号必须是 3 参签名；3 参槽能正确收到 (target, before, new_rows)。"""
    tv = QTableView()
    dc = DragController(tv)
    captured = {}

    def _slot(target, before, new_rows):
        captured["target"] = target
        captured["before"] = before
        captured["new_rows"] = new_rows

    dc.drag_dropped.connect(_slot)
    dc.drag_dropped.emit(7, True, [3, 4, 5])
    assert captured == {"target": 7, "before": True, "new_rows": [3, 4, 5]}
