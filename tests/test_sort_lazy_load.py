# -*- coding: utf-8 -*-
"""表头排序懒加载回归测试（2026-08-23）。

锁定 P1-① 修复：点击表头 / 恢复排序不再强制全量物化（原 self._loaded = len(self._order)
会令百万行词库在排序瞬间加载全部行 → 启动白屏 + 点击分组变慢）。

- 小词库：sort() 同步完成，且 _loaded 不被强制设为 len(_order)（保留懒加载边界）。
- 大词库（>SORT_THRESHOLD）：sort() 必须走后台线程、同步立即返回、不阻塞、不物化全表；
  后台完成后 _order 平铺为按列排序、_loaded 仍保留懒加载边界。
"""
import pathlib
import sys

RIMETOOL = str(pathlib.Path(__file__).resolve().parents[1])
if RIMETOOL not in sys.path:
    sys.path.insert(0, RIMETOOL)

from PyQt5.QtCore import Qt

from core.dict_model import DictModel


def _sample(n=12):
    groups = ["A 词库", "B 人名", "C 地名"]
    return [(f"词组{i}", f"code{i}", str(100 + i), groups[i % len(groups)], "A") for i in range(n)]


def test_sort_small_preserves_lazy_loading():
    m = DictModel()
    m.set_all_data(_sample(12), 12)
    m._loaded = 5  # 仅懒加载前 5 行
    m.sort(2, Qt.AscendingOrder)  # 按权重（数值列）升序
    # 关键断言：_loaded 未被强制设为 len(_order)，保留懒加载边界
    assert m._loaded == min(5, len(m._order))
    # 顺序应为按权重升序（数值列 int 比较）
    data_rows = [e for e in m._order if isinstance(e, int)]
    weights = [int(m._all_data[i][2]) for i in data_rows]
    assert weights == sorted(weights)


def test_sort_large_defers_and_preserves_loaded():
    m = DictModel()
    n = DictModel.SORT_THRESHOLD + 1000  # 越过阈值 → 后台排序
    data = [(f"w{i}", f"c{i}", str(i), "A 词库", "A") for i in range(n)]
    m.set_all_data(data, n)
    m._loaded = 200  # 懒加载边界
    m.sort(2, Qt.DescendingOrder)  # 触发后台排序
    # 同步返回后：不应立即重排、_loaded 仍小、仍含分组头（未平铺）
    assert m._loaded == 200
    assert not all(isinstance(e, int) for e in m._order)  # 仍含 ("H",...) 分组头
    # 模拟后台线程完成（子线程会回传已按权重降序排好的下标列表）
    data_idx = [e for e in m._order if isinstance(e, int)]
    sorted_idx = sorted(data_idx, key=lambda i: int(m._all_data[i][2]), reverse=True)
    m._on_sorted(sorted_idx, m._sort_token)
    # 完成后：平铺（无分组头）、按权重降序、_loaded 仍保留懒加载边界
    assert all(isinstance(e, int) for e in m._order)
    assert m._loaded == 200
    weights = [int(m._all_data[i][2]) for i in m._order]
    assert weights == sorted(weights, reverse=True)


def test_sort_token_discards_stale_result():
    m = DictModel()
    n = DictModel.SORT_THRESHOLD + 500
    data = [(f"w{i}", f"c{i}", str(i), "A 词库", "A") for i in range(n)]
    m.set_all_data(data, n)
    m.sort(2, Qt.AscendingOrder)  # token 自增 → 1
    stale_token = m._sort_token
    m.sort(2, Qt.DescendingOrder)  # token → 2（最新）
    # 用过期 token 回调应被丢弃：_order 不被错误覆盖（仍含分组头、未平铺），_order_dirty 不变
    data_idx = [e for e in m._order if isinstance(e, int)]
    m._on_sorted(data_idx, stale_token)
    assert m._order_dirty is False
    assert not all(isinstance(e, int) for e in m._order)  # 仍含分组头 = 未被错误平铺
    # 用最新 token 回调才生效
    data_idx2 = [e for e in m._order if isinstance(e, int)]
    m._on_sorted(sorted(data_idx2, key=lambda i: int(m._all_data[i][2]), reverse=True),
                 m._sort_token)
    assert all(isinstance(e, int) for e in m._order)
