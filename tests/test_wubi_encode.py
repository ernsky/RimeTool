# -*- coding: utf-8 -*-
"""wubi_encode 纯逻辑单测：6 规则 + 关键 helper。

使用受控单字编码表（unicode 无关，仅验证规则拼接逻辑），不依赖真实 word.txt。
"""
import os
import sys
import pathlib

RIMETOOL = str(pathlib.Path(__file__).resolve().parents[1])
if RIMETOOL not in sys.path:
    sys.path.insert(0, RIMETOOL)

from core.wubi_encode import (  # noqa: E402
    extract_chinese_chars,
    filter_encoded_chars,
    generate_for_phrase,
    generate_wubi_code_enhanced,
    get_first_code,
    get_first_two_codes,
    get_pinyin_initials,
    rule_standard_wubi_enhanced,
    validate_wubi_code,
)

# 受控编码表：一字多码/单码/无码混合，便于断言规则行为
CHAR_CODES = {
    "我": "abc",     # 3 码
    "们": "de",      # 2 码
    "中": "f",       # 1 码
    "国": "ghij",    # 4 码
    "好": "x",       # 1 码
}


def test_get_first_code():
    assert get_first_code("中", CHAR_CODES) == "f"
    assert get_first_code("我", CHAR_CODES) == "a"
    assert get_first_code("无", CHAR_CODES) == ""   # 不在表


def test_get_first_two_codes():
    assert get_first_two_codes("我", CHAR_CODES) == "ab"   # >=2 取前 2
    assert get_first_two_codes("中", CHAR_CODES) == "fx"   # 仅 1 码补 x
    assert get_first_two_codes("好", CHAR_CODES) == "xx"
    assert get_first_two_codes("无", CHAR_CODES) == ""     # 无码返回空


def test_filter_encoded_chars():
    assert filter_encoded_chars("我中好z", CHAR_CODES) == ["我", "中", "好"]


def test_validate_wubi_code():
    assert validate_wubi_code("abcf")
    assert not validate_wubi_code("")          # 空
    assert not validate_wubi_code("ab\tc")     # 含制表符
    assert not validate_wubi_code("AB1")       # 大写/数字


def test_extract_chinese_chars():
    assert extract_chinese_chars("abc中国123") == "中国"


def test_rule_standard_max4():
    # n==1
    assert generate_wubi_code_enhanced("中", CHAR_CODES, 1) == "f"
    # n==2：各自前 2 码
    assert generate_wubi_code_enhanced("我们", CHAR_CODES, 1) == "abde"
    # n==3：首1 首1 末2
    assert generate_wubi_code_enhanced("我中们", CHAR_CODES, 1) == "afde"
    # n==4：各首 1，截断 4
    assert generate_wubi_code_enhanced("我中们国", CHAR_CODES, 1) == "afdg"
    # n==5：前 3 首码 + 末首码，截断 4
    assert generate_wubi_code_enhanced("我中们国好", CHAR_CODES, 1) == "afdx"
    # 无编码字符 -> xxxx
    assert generate_wubi_code_enhanced("zzz", {}, 1) == "xxxx"


def test_rule_one_per_char_no_truncate():
    # n==2 与规则1一致
    assert generate_wubi_code_enhanced("我们", CHAR_CODES, 2) == "abde"
    # n==5：一字一码、不截断 -> 5 码（与规则1 的 4 码截断不同）
    assert generate_wubi_code_enhanced("我中们国好", CHAR_CODES, 2) == "afdgx"


def test_rule_first_two_rest_one():
    # 前两字各 2 码、其余 1 码
    assert generate_wubi_code_enhanced("我中们国好", CHAR_CODES, 3) == "abfxdgx"


def test_rule_all_two():
    # 每字都取前 2 码（1 码补 x），拼接不截断
    assert generate_wubi_code_enhanced("我中们国好", CHAR_CODES, 4) == "abfxdeghxx"


def test_rule_free():
    assert generate_wubi_code_enhanced("中国", CHAR_CODES, 5) == ""
    # 对外入口：自由编码用 free_code
    assert generate_for_phrase("中国", 5, CHAR_CODES, free_code="zz") == "zz"


def test_rule_wubi_pinyin():
    # 规则6 = 规则1 五笔码 + 拼音首字母（pypinyin 可用时）
    expected = rule_standard_wubi_enhanced("中国", CHAR_CODES) + get_pinyin_initials("中国")
    assert generate_wubi_code_enhanced("中国", CHAR_CODES, 6) == expected
    assert get_pinyin_initials("中国") == "zg"
