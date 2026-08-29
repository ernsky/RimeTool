"""五笔编码引擎：移植自 五笔词库编码生成工具.py 的增强版规则。

提供 6 条编码规则 + 单字编码表读取。新建编码功能调用本模块自动生成编码。
依赖：单字编码表文件（格式 汉字\\t编码，每行两条），由配置 wubi_char_table 指定。
"""

from __future__ import annotations

import os
import re
from typing import Dict, List, Optional


def read_single_char_codes(filename: str) -> Dict[str, str]:
    """读取单字编码表，返回 {汉字: 编码(小写)}。文件不存在返回空字典。"""
    char_codes: Dict[str, str] = {}
    if not filename or not os.path.exists(filename):
        return char_codes
    try:
        with open(filename, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                parts = line.split("\t")
                if len(parts) >= 2:
                    char_codes[parts[0]] = parts[1].lower()
    except Exception:
        pass
    return char_codes


def extract_chinese_chars(text: str) -> str:
    return "".join(re.findall(r"[\u4e00-\u9fff]", text))


def filter_encoded_chars(phrase: str, char_codes: Dict[str, str]) -> List[str]:
    return [c for c in phrase if c in char_codes]


def get_first_code(char: str, char_codes: Dict[str, str]) -> str:
    code = char_codes.get(char, "")
    return code[0:1] if code else ""


def get_first_two_codes(char: str, char_codes: Dict[str, str]) -> str:
    code = char_codes.get(char, "")
    if len(code) >= 2:
        return code[:2].lower()
    elif len(code) == 1:
        return code.lower() + "x"
    return ""


# ---------- 6 条规则 ----------
def rule_standard_wubi(phrase: str, char_codes: Dict[str, str]) -> str:
    enc = filter_encoded_chars(phrase, char_codes)
    if not enc:
        return "xxxx"
    n = len(enc)
    if n == 1:
        return char_codes.get(enc[0], "xxxx").lower()
    if n == 2:
        return (get_first_two_codes(enc[0], char_codes) + get_first_two_codes(enc[1], char_codes))[:4].lower()
    if n == 3:
        c = get_first_code(enc[0], char_codes) + get_first_code(enc[1], char_codes) + get_first_two_codes(enc[2], char_codes)
        return c[:4].lower() if c else "xxxx"
    if n == 4:
        c = "".join(get_first_code(c, char_codes) for c in enc)
        return c[:4].lower() if c else "xxxx"
    c = get_first_code(enc[0], char_codes) + get_first_code(enc[1], char_codes) + get_first_code(enc[2], char_codes) + get_first_code(enc[-1], char_codes)
    return c[:4].lower() if c else "xxxx"


def rule_one_code_per_char(phrase: str, char_codes: Dict[str, str]) -> str:
    enc = filter_encoded_chars(phrase, char_codes)
    if not enc:
        return "xxxx"
    n = len(enc)
    if n == 1:
        return char_codes.get(enc[0], "xxxx").lower()
    if n == 2:
        return (get_first_two_codes(enc[0], char_codes) + get_first_two_codes(enc[1], char_codes)).lower()
    if n == 3:
        c = get_first_code(enc[0], char_codes) + get_first_code(enc[1], char_codes) + get_first_two_codes(enc[2], char_codes)
        return c.lower() if c else "xxxx"
    return "".join(get_first_code(c, char_codes) for c in enc).lower() or "xxxx"


def rule_first_two_chars_two_codes_rest_one(phrase: str, char_codes: Dict[str, str]) -> str:
    enc = filter_encoded_chars(phrase, char_codes)
    if not enc:
        return "xxxx"
    n = len(enc)
    if n == 1:
        return char_codes.get(enc[0], "xxxx").lower()
    if n == 2:
        return (get_first_two_codes(enc[0], char_codes) + get_first_two_codes(enc[1], char_codes)).lower()
    parts = []
    parts.append(get_first_two_codes(enc[0], char_codes))
    parts.append(get_first_two_codes(enc[1], char_codes))
    for i in range(2, n):
        parts.append(get_first_code(enc[i], char_codes))
    full = "".join(parts)
    return full.lower() if full else "xxxx"


def rule_all_two_codes(phrase: str, char_codes: Dict[str, str]) -> str:
    enc = filter_encoded_chars(phrase, char_codes)
    if not enc:
        return "xxxx"
    codes = [get_first_two_codes(c, char_codes) for c in enc]
    res = "".join(codes)
    return res.lower() if res else "xxxx"


def rule_free_coding(phrase: str, char_codes: Dict[str, str]) -> str:
    return ""  # 自由编码：由调用方手填


def rule_wubi_pinyin_initials(phrase: str, char_codes: Dict[str, str]) -> str:
    wubi = rule_standard_wubi(phrase, char_codes)
    py = get_pinyin_initials(phrase)
    return (wubi + py).lower() if py else wubi.lower()


def get_pinyin_initials(text: str) -> str:
    """取汉字拼音首字母（需 pypinyin）。未安装时返回空串。"""
    try:
        from pypinyin import lazy_pinyin, Style
        chars = extract_chinese_chars(text)
        if not chars:
            return ""
        return "".join(lazy_pinyin(chars, style=Style.FIRST_LETTER)).lower()
    except Exception:
        return ""


_RULES = {
    1: rule_standard_wubi,
    2: rule_one_code_per_char,
    3: rule_first_two_chars_two_codes_rest_one,
    4: rule_all_two_codes,
    5: rule_free_coding,
    6: rule_wubi_pinyin_initials,
}

RULE_NAMES = {
    1: "标准五笔(最多4码)",
    2: "一字一码",
    3: "前两字两码后字一码",
    4: "每字两码",
    5: "自由编码(手填)",
    6: "五笔+拼音首字母",
}


def generate(phrase: str, char_codes: Dict[str, str], rule: int = 1,
             free_code: str = "") -> str:
    """生成编码。rule=5 时返回 free_code（调用方已校验）。"""
    if rule == 5:
        return free_code
    fn = _RULES.get(rule, rule_standard_wubi)
    return fn(phrase, char_codes)


def validate_code(code: str) -> bool:
    """编码校验：只允许小写字母和空格，不含制表符。"""
    if not code:
        return False
    if "\t" in code:
        return False
    return bool(re.match(r"^[a-z ]+$", code))
