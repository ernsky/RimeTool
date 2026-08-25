# -*- coding: utf-8 -*-
"""回归：分组首字母 -> Rime 词典 路由映射（含 A 改指 wubi.word）。

锁住两点：
  - A 组写回到 dicts/wubi.word.dict.yaml（name=wubi.word），不再写回顶层 wubi.dict.yaml；
  - 权重回灌(weight_replacer) 复用同一张 GROUP_TARGETS，故 A 组权重也从该路径读取。
"""
import os

from core.rime_export import GROUP_TARGETS, build_single_tables
import core.weight_replacer as wr


def test_group_a_target_is_wubi_word():
    assert GROUP_TARGETS["A"] == ("dicts/wubi.word.dict.yaml", "wubi.word")


def test_group_a_no_longer_points_to_top_level_wubi_dict():
    for path, _ in GROUP_TARGETS.values():
        assert path != "wubi.dict.yaml", "A 已改指 wubi.word，顶层 wubi.dict.yaml 不应再被路由"


def test_b_through_f_unchanged():
    assert GROUP_TARGETS["B"] == ("dicts/wubi.phrase.dict.yaml", "wubi.phrase")
    assert GROUP_TARGETS["C"] == ("dicts/wubi.user.dict.yaml", "wubi.user")
    assert GROUP_TARGETS["D"] == ("dicts/wubi.long.dict.yaml", "wubi.long")
    assert GROUP_TARGETS["E"] == ("English.dict.yaml", "English")
    assert GROUP_TARGETS["F"] == ("dicts/wubi.low.dict.yaml", "wubi.low")


def test_build_single_tables():
    """功能3 保存为单一码表：启用=A 按分组首字母拆分 E→English，其它→wubi。"""
    rows = [
        ("apple", "pg", "1", "E Google一万", "A"),
        ("banana", "xj", "1", "E 水果", "A"),
        ("樱桃", "yz", "1", "A 词库", "A"),
        ("禁用词", "xx", "1", "B 词库", "B"),   # 启用非 A → 跳过
        ("", "yy", "1", "E 空词组", "A"),        # 词组空 → 跳过
    ]
    tables = build_single_tables(rows)
    assert set(tables.keys()) == {"English.dict.yaml", "wubi.dict.yaml"}
    eng = tables["English.dict.yaml"]
    wubi = tables["wubi.dict.yaml"]
    assert "apple" in eng and "banana" in eng
    assert "## Google一万" in eng and "## 水果" in eng
    assert "樱桃" in wubi
    assert "禁用词" not in wubi and "yy" not in wubi


def test_weight_replacer_reads_from_same_mapping():
    # weight_replacer.af_files 由 GROUP_TARGETS.values() 推导（见 weight_replacer.py），
    # 故新 A 路径必须出现在它要读取的相对路径集合里，保证写回/回灌对称。
    rel_paths = {p for p, _ in GROUP_TARGETS.values()}
    assert "dicts/wubi.word.dict.yaml" in rel_paths
    # 模拟 weight_replacer 拼接（d 为任意 rime_config_dir）
    d = "X"
    af_files = [os.path.join(d, p) for p, _ in GROUP_TARGETS.values()]
    assert os.path.join(d, "dicts/wubi.word.dict.yaml") in af_files


def test_weight_replacer_default_group_is_single_letter_a():
    # 兜底桶「A 备用」须为单字母前缀（不再用 AZ 两字母），符合分组列 X 描述 约定。
    assert wr.DEFAULT_GROUP == "A 备用"
    assert wr.DEFAULT_ENABLE == "A"
