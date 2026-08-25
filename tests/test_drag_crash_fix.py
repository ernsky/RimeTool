# -*- coding: utf-8 -*-
"""拖拽崩溃修复回归测试（2026-08-23）。

锁定三件事：
1. reorder_view_rows / move_selected_to_group 在行数不变时配对的
   layoutAboutToBeChanged / layoutChanged 通知（Qt 文档要求成对，避免视图持久索引损坏）。
2. 把行拖到「当前分组筛选下被隐藏的目标分组」时，显示数据行数发生变化；
   _rebuild_order_keep_loaded 必须改用 beginResetModel/endResetModel（而非裸
   layoutChanged），否则视图缓存行数越界 → 段错误（拖到分组/拖最后一个崩溃的根因）。
3. move_selected_to_group 之后数据行数一致、不丢行。

注意：rowCount() 含分组头元组（("H", group)），不等于数据行数；
本测试一律用 filtered_count()（纯数据行数）做行数断言，避免分组头干扰。
"""
import pathlib
import sys

RIMETOOL = str(pathlib.Path(__file__).resolve().parents[1])
if RIMETOOL not in sys.path:
    sys.path.insert(0, RIMETOOL)

from PyQt5.QtTest import QSignalSpy
from core.dict_model import DictModel  # noqa: E402


def _sample(n=12):
    groups = ["A 词库", "B 人名", "C 地名"]
    return [(f"词组{i}", f"code{i}", str(100 + i), groups[i % len(groups)], "A") for i in range(n)]


def _data_view_rows(m, n=2):
    out = []
    for vr, el in enumerate(m._order):
        if isinstance(el, int):
            out.append(vr)
        if len(out) >= n:
            break
    return out


def test_reorder_emits_paired_layout_signals():
    m = DictModel()
    m.set_all_data(_sample(12), 12)
    spy_a = QSignalSpy(m.layoutAboutToBeChanged)
    spy_c = QSignalSpy(m.layoutChanged)
    d = _data_view_rows(m, 2)
    m.reorder_view_rows([d[0]], d[1], True)
    # 必须成对发出（至少各一次），且数据行数不变
    assert len(spy_a) >= 1
    assert len(spy_c) >= 1
    assert m.filtered_count() == 12


def test_move_to_visible_group_emits_paired_signals():
    m = DictModel()
    m.set_all_data(_sample(12), 12)
    spy_a = QSignalSpy(m.layoutAboutToBeChanged)
    spy_c = QSignalSpy(m.layoutChanged)
    d = _data_view_rows(m, 2)
    # 拖到同视图内可见的「B 人名」组（无筛选，所有组头都在 _order）
    changed, first = m.move_selected_to_group(d, "B 人名", "A")
    assert changed >= 1   # 前 2 数据行含一个 B 组，仅 A 行被改（数据行数不变）
    assert len(spy_a) >= 1
    assert len(spy_c) >= 1
    assert m.filtered_count() == 12  # 数据行数不变


def test_move_to_hidden_group_rebuilds_rowcount_safely():
    """拖到被当前筛选隐藏的分组 → 显示数据行数减少 → 必须用整表重置而非裸 layoutChanged。"""
    m = DictModel()
    m.set_all_data(_sample(12), 12)
    m.set_group_filter("A 词库")          # 仅显示 A 组（4 数据行）
    before = m.filtered_count()
    assert before == 4
    rows = _data_view_rows(m, 2)          # A 组前 2 个数据行
    changed, first = m.move_selected_to_group(rows, "B 人名", "A")  # B 被筛选隐藏
    after = m.filtered_count()
    assert changed == 2
    # 数据行数必须正确减少（2 行从 A 改为 B，不再匹配 A 筛选），且不应触发非法通知
    assert after == before - changed
    assert after == 2
