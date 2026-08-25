# -*- coding: utf-8 -*-
r"""五笔编码生成（严格对齐真实源 五笔词库编码生成工具.py 的 6 规则语义）。

移植自 D:\OneDrive\Backup\Soft\Wubi\Base\五笔词库编码生成工具.py：
  规则 1 增强标准五笔（最多 4 码）
  规则 2 一字一码（不截断）
  规则 3 前两字各取前两码、其余字取第一码（不截断）
  规则 4 每个字都取前两码（不截断）
  规则 5 自由编码（手动输入，返回空串由调用方填 free_code）
  规则 6 五笔编码 + 拼音首字母（依赖 pypinyin，缺失时降级为规则 1）

关键 helper 与真实源逐字一致：
  filter_encoded_chars（只对编码表有码的字符取码）
  get_first_code（首 1 码）
  get_first_two_codes（前 2 码；仅 1 码补 x；无码返回空）
  get_pinyin_initials（lazy_pinyin 首字母，try/except 兜底）

单字编码表默认取 config.SINGLE_CHAR_FILE（即 resources/word.txt，已从权威 8105.txt 复制）；
可通过 read_single_char_codes(path) 覆盖，对应「配置选项 → 单字编码文件」。
GUI 对话框（ui/wubi_encode_dialog.py）按 6 规则生成编码并追加到词库。
"""
import logging
import os
import re

from core.config import SINGLE_CHAR_FILE
from typing import Dict, List, Optional

_log = logging.getLogger(__name__)

WORD_FILE = SINGLE_CHAR_FILE                          # 默认单字编码表路径（与配置默认一致）


def read_single_char_codes(path: Optional[str] = None) -> Dict[str, str]:
    """读取单字编码表（char\\tcode），返回 {char: code_lower}。

    path 为空时取默认 SINGLE_CHAR_FILE；若指定文件缺失，回退到 WORD_FILE。
    文件缺失或读空均返回空 dict（调用方据此走「无编码字符」逻辑）。
    """
    target = path or WORD_FILE
    if not os.path.exists(target):
        target = WORD_FILE
    codes = {}
    if not os.path.exists(target):
        return codes
    try:
        with open(target, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                parts = line.split("\t")
                if len(parts) >= 2:
                    codes[parts[0]] = parts[1].lower()
    except (OSError, UnicodeDecodeError) as exc:
        # 读取/解码失败：返回已解析的部分结果（或空 dict），但必须记录，避免静默丢失单字表
        _log.warning("读取单字编码表失败（%s）：%s", target, exc)
    return codes


# 6 种编码规则（整数编号，与真实源 generate_wubi_code_enhanced 的 rule 一一对应）
RULE_STANDARD = 1          # 增强标准五笔编码（最多 4 码）
RULE_ONE_PER_CHAR = 2      # 一字一码（不截断）
RULE_FIRST_TWO_REST_ONE = 3  # 前两字各 2 码、其余字 1 码（不截断）
RULE_ALL_TWO = 4           # 每字都取前两码（不截断）
RULE_FREE = 5              # 自由编码（手动输入）
RULE_WUBI_PINYIN = 6       # 五笔编码 + 拼音首字母

# 对话框下拉的 6 个选项（顺序即展示顺序）；值用整数规则号
COMBO_METHODS = [
    (RULE_STANDARD, "增强标准五笔编码（最多 4 码）"),
    (RULE_ONE_PER_CHAR, "一字一码（不截断）"),
    (RULE_FIRST_TWO_REST_ONE, "前两字各 2 码、其余字 1 码（不截断）"),
    (RULE_ALL_TWO, "每字都取前两码（不截断）"),
    (RULE_FREE, "自由编码（手动输入）"),
    (RULE_WUBI_PINYIN, "五笔编码 + 拼音首字母"),
]


def extract_chinese_chars(text: str) -> str:
    """提取文本中所有汉字（\\u4e00-\\u9fff），拼接返回。"""
    return "".join(re.findall(r"[\u4e00-\u9fff]", text))


def get_pinyin_initials(text: str) -> str:
    """返回文本中汉字的拼音首字母（小写拼接）；pypinyin 缺失时降级返回空串。"""
    try:
        from pypinyin import lazy_pinyin, Style
    except ImportError:
        return ""
    try:
        chinese_chars = extract_chinese_chars(text)
        if not chinese_chars:
            return ""
        initials = lazy_pinyin(chinese_chars, style=Style.FIRST_LETTER)
        return "".join(initials).lower()
    except Exception:  # noqa: BLE001 - pypinyin 异常：降级返回空串（规则 6 退化为规则 1）
        _log.debug("获取拼音首字母失败，降级为空串", exc_info=True)
        return ""


def validate_wubi_code(code: str) -> bool:
    """校验五笔编码：非空、不含制表符、仅小写字母与空格。"""
    if not code:
        return False
    if "\t" in code:
        return False
    return bool(re.match(r"^[a-z ]+$", code))


def get_first_code(char: str, char_codes: Dict[str, str]) -> str:
    """取单字首 1 码；无码返回空串。"""
    code = char_codes.get(char, "")
    return code[0:1] if code else ""


def get_first_two_codes(char: str, char_codes: Dict[str, str]) -> str:
    """取单字前 2 码：≥2 码取前 2；仅 1 码补 x；无码返回空串。"""
    code = char_codes.get(char, "")
    if len(code) >= 2:
        return code[:2].lower()
    elif len(code) == 1:
        return code.lower() + "x"
    return ""


def filter_encoded_chars(phrase: str, char_codes: Dict[str, str]) -> List[str]:
    """只保留 phrase 中在编码表里有码的字符。"""
    return [c for c in phrase if c in char_codes]


def has_encoded_chars(phrase: str, char_codes: Dict[str, str]) -> bool:
    """phrase 中是否至少含一个编码表有码的字符。"""
    return any(c in char_codes for c in phrase)


def rule_standard_wubi_enhanced(phrase: str, char_codes: Dict[str, str]) -> str:
    """规则 1：增强标准五笔，最多 4 码。"""
    encoded = filter_encoded_chars(phrase, char_codes)
    if not encoded:
        return "xxxx"
    n = len(encoded)
    if n == 1:
        return char_codes.get(encoded[0], "xxxx").lower()
    if n == 2:
        c1 = get_first_two_codes(encoded[0], char_codes)
        c2 = get_first_two_codes(encoded[1], char_codes)
        return (c1 + c2)[:4].lower()
    if n == 3:
        c1 = get_first_code(encoded[0], char_codes)
        c2 = get_first_code(encoded[1], char_codes)
        c3 = get_first_two_codes(encoded[2], char_codes)
        combined = c1 + c2 + c3
        return combined[:4].lower() if combined else "xxxx"
    if n == 4:
        codes = [get_first_code(c, char_codes) for c in encoded]
        combined = "".join(codes)
        return combined[:4].lower() if combined else "xxxx"
    # 5 字及以上：前 3 字首码 + 末字首码，截断 4 码
    c1 = get_first_code(encoded[0], char_codes)
    c2 = get_first_code(encoded[1], char_codes)
    c3 = get_first_code(encoded[2], char_codes)
    c_last = get_first_code(encoded[-1], char_codes)
    combined = c1 + c2 + c3 + c_last
    return combined[:4].lower() if combined else "xxxx"


def rule_one_code_per_char_enhanced(phrase: str, char_codes: Dict[str, str]) -> str:
    """规则 2：一字一码，不截断。"""
    encoded = filter_encoded_chars(phrase, char_codes)
    if not encoded:
        return "xxxx"
    n = len(encoded)
    if n == 1:
        return char_codes.get(encoded[0], "xxxx").lower()
    if n == 2:
        c1 = get_first_two_codes(encoded[0], char_codes)
        c2 = get_first_two_codes(encoded[1], char_codes)
        return (c1 + c2).lower()
    if n == 3:
        c1 = get_first_code(encoded[0], char_codes)
        c2 = get_first_code(encoded[1], char_codes)
        c3 = get_first_two_codes(encoded[2], char_codes)
        combined = c1 + c2 + c3
        return combined.lower() if combined else "xxxx"
    codes = [get_first_code(c, char_codes) for c in encoded]
    combined = "".join(codes).lower()
    return combined if combined else "xxxx"


def rule_first_two_chars_two_codes_rest_one_enhanced(phrase: str, char_codes: Dict[str, str]) -> str:
    """规则 3：前两字各取前两码，其余字取第一码（不截断）。"""
    encoded = filter_encoded_chars(phrase, char_codes)
    if not encoded:
        return "xxxx"
    n = len(encoded)
    if n == 1:
        return char_codes.get(encoded[0], "xxxx").lower()
    if n == 2:
        c1 = get_first_two_codes(encoded[0], char_codes)
        c2 = get_first_two_codes(encoded[1], char_codes)
        return (c1 + c2).lower()
    parts = [get_first_two_codes(encoded[0], char_codes)]
    parts.append(get_first_two_codes(encoded[1], char_codes))
    for c in encoded[2:]:
        parts.append(get_first_code(c, char_codes))
    full = "".join(parts)
    return full.lower() if full else "xxxx"


def rule_all_two_codes_enhanced(phrase: str, char_codes: Dict[str, str]) -> str:
    """规则 4：每个字都取前两码，拼接（不截断）。"""
    encoded = filter_encoded_chars(phrase, char_codes)
    if not encoded:
        return "xxxx"
    codes = [get_first_two_codes(c, char_codes) for c in encoded]
    result = "".join(codes)
    return result.lower() if result else "xxxx"


def rule_free_coding(phrase: str, char_codes: Dict[str, str]) -> str:
    """规则 5：自由编码，返回空串，由调用方填入 manual code。"""
    return ""


def rule_wubi_pinyin_initials_enhanced(phrase: str, char_codes: Dict[str, str]) -> str:
    """规则 6：规则 1 五笔编码 + 拼音首字母（pypinyin 缺失则退化为规则 1）。"""
    wubi_code = rule_standard_wubi_enhanced(phrase, char_codes)
    pinyin_initials = get_pinyin_initials(phrase)
    if pinyin_initials:
        return wubi_code + pinyin_initials
    return wubi_code


def generate_wubi_code_enhanced(phrase: str, char_codes: Dict[str, str], rule: int = 1) -> str:
    """按规则号分发到 6 个规则函数，返回小写编码。"""
    if rule == RULE_STANDARD:
        return rule_standard_wubi_enhanced(phrase, char_codes)
    if rule == RULE_ONE_PER_CHAR:
        return rule_one_code_per_char_enhanced(phrase, char_codes)
    if rule == RULE_FIRST_TWO_REST_ONE:
        return rule_first_two_chars_two_codes_rest_one_enhanced(phrase, char_codes)
    if rule == RULE_ALL_TWO:
        return rule_all_two_codes_enhanced(phrase, char_codes)
    if rule == RULE_FREE:
        return rule_free_coding(phrase, char_codes)
    if rule == RULE_WUBI_PINYIN:
        return rule_wubi_pinyin_initials_enhanced(phrase, char_codes)
    return rule_standard_wubi_enhanced(phrase, char_codes)


def generate_for_phrase(phrase: str, rule: int, char_codes: Dict[str, str], free_code: str = "") -> str:
    """对外入口：自由编码(规则 5)用 free_code；其余按规则生成。

    rule 为 1-6 整数；free_code 仅规则 5 生效。
    """
    if rule == RULE_FREE:
        return (free_code or "").lower()
    return generate_wubi_code_enhanced(phrase, char_codes, rule)
