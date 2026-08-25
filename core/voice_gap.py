# -*- coding: utf-8 -*-
"""语音词组查漏（纯 Python 移植自 Python/features/feature_asr_extract.py，去交互式 input）。

目的：从 SayIt 语音识别导出 JSON 的 asrText 用 jieba 中文分词提取词组，与基准词库（配置的
tsv_path）比对，找出「常说但词库没覆盖/没启用」的词，便于补词或启用。

判定：
  - 启用列(第5列, index 4) == 'A' → 已在用（命中，无需处理）
  - 基准有 但 启用 != 'A'      → 已存在未启用（建议【启用】）
  - 基准完全没有               → 缺失（建议【加入词库】）

三重降噪（与 feature_asr_extract 一致）：jieba 自定义词典降噪、频次阈值、合格词组门槛。
输入/输出均由调用方（UI）传入：find_gaps(sayit_path, baseline_tsv, output_dir) -> out_path。
依赖 jieba（懒加载，缺失时返回错误字符串供 UI 提示）。
"""
import os
import re
import json
import tempfile
import logging
from typing import Any, Dict, List, Optional, Set, Tuple

_log = logging.getLogger(__name__)

ENABLE_IDX = 4          # 第5列（0-based=4）为启用列
MIN_FREQ = 2            # 候选至少出现次数
# 合格词组白名单（优先级最高）；按安装根目录推导，随程序位置移动自适应
_RIME_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WHITELIST_PATH = os.path.join(_RIME_ROOT, "wubi_whitelist.txt")

_CN_RE = re.compile(r"[\u3400-\u9fff]")
_GRAMMAR_SUFFIX = ["的", "了", "吗", "呢", "吧", "啊", "呀", "的话", "的时候", "的情况下",
                   "之后", "之前", "之中", "之上", "之下", "以来", "以后", "以前",
                   "出来", "进去", "起来", "上去", "下来", "过来", "过去", "出去", "一下", "着"]
_GRAMMAR_PREFIX = ["这", "那", "哪", "怎", "为", "是", "不", "没", "有", "我", "你", "他", "它", "她", "们"]
_GRAMMAR_PREFIX_SUF = ["的", "了", "吗", "呢", "个", "样", "种", "些", "里", "边", "儿", "们"]


def is_candidate(tok: str) -> bool:
    t = tok.strip()
    if len(t) < 2:
        return False
    if not _CN_RE.search(t):
        return False
    return True


def f_suf(w: str) -> bool:
    return any(w.endswith(x) for x in _GRAMMAR_SUFFIX)


def f_demo(w: str) -> bool:
    for p in _GRAMMAR_PREFIX:
        if w.startswith(p):
            tail = w[len(p):]
            if any(tail.startswith(s) for s in _GRAMMAR_PREFIX_SUF):
                return True
    return False


def load_baseline(path: str) -> Tuple[Dict[str, str], List[str]]:
    """读取基准 tsv。返回 (enable_map, dict_words)。"""
    enable_map = {}
    dict_words = []
    with open(path, "r", encoding="utf-8-sig") as f:
        for line in f:
            cols = line.rstrip("\n").split("\t")
            if not cols or not cols[0].strip():
                continue
            w = cols[0].strip()
            enable_val = cols[ENABLE_IDX].strip() if len(cols) > ENABLE_IDX else ""
            enable_map[w] = enable_val
            if _CN_RE.search(w) and len(w) >= 2:
                dict_words.append(w)
    return enable_map, dict_words


def load_whitelist(path: str) -> Set[str]:
    wl = set()
    if not os.path.exists(path):
        return wl
    with open(path, "r", encoding="utf-8-sig") as f:
        for line in f:
            w = line.strip()
            if not w or w.startswith("#"):
                continue
            wl.add(w)
    return wl


def collect_candidates(text: str, jieba_mod: Any) -> Dict[str, int]:
    freq = {}
    if not text or not str(text).strip():
        return freq
    for tok in jieba_mod.cut(str(text)):
        if is_candidate(tok):
            tok = tok.strip()
            freq[tok] = freq.get(tok, 0) + 1
    return freq


def is_good_wubi_word(w: str, whitelist: Set[str], base_words: Set[str]) -> bool:
    if w in whitelist:
        return True
    if not _CN_RE.search(w):
        return False
    if not (2 <= len(w) <= 4):
        return False
    if f_suf(w):
        return False
    if f_demo(w):
        return False
    return w in base_words


def _load_jieba() -> Optional[Any]:
    """懒加载 jieba；失败返回 None。"""
    try:
        import jieba
        return jieba
    except ImportError:
        return None


def find_gaps(sayit_path: str, baseline_tsv: str, output_dir: str) -> Tuple[Optional[str], str]:
    """主入口。返回 (out_path, summary_dict) 或 (None, error_message)。"""
    if not sayit_path or not os.path.exists(sayit_path):
        return None, "未提供或找不到 SayIt 语音 JSON 文件"
    if not baseline_tsv or not os.path.exists(baseline_tsv):
        return None, "未提供或找不到基准词库 tsv（请在配置中设置 tsv 文件）"

    jieba = _load_jieba()
    if jieba is None:
        return None, "本功能依赖 jieba 分词库，请先安装：pip install jieba"

    jieba.initialize()
    base_words = set(jieba.dt.FREQ)  # 原始词表快照（须在 load_userdict 前）

    enable_map, dict_words = load_baseline(baseline_tsv)

    # 自定义词典降噪
    tf = tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".txt", delete=False)
    try:
        for w in dict_words:
            tf.write(w + "\n")
        tf.close()
        jieba.load_userdict(tf.name)
    finally:
        try:
            os.remove(tf.name)
        except OSError:
            pass

    whitelist = load_whitelist(WHITELIST_PATH)

    # 解析 JSON
    try:
        with open(sayit_path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
    except Exception as e:
        _log.debug("读取/解析 JSON 失败", exc_info=True)
        return None, "读取/解析 JSON 失败: %s" % e

    if isinstance(data, list):
        records = data
    elif isinstance(data, dict):
        records = data.get("records", [])
    else:
        return None, "JSON 结构无法识别（既非数组也非含 records 的对象）"
    if not records:
        return None, "records 为空，没有可处理的数据"

    all_cands = {}
    for rec in records:
        asr = rec.get("asrText", "") if isinstance(rec, dict) else str(rec)
        for w, c in collect_candidates(asr, jieba).items():
            all_cands[w] = all_cands.get(w, 0) + c

    matched, present_disabled, missing = {}, {}, {}
    for w, c in all_cands.items():
        code = enable_map.get(w)
        if code == "A":
            matched[w] = c
        elif code is not None:
            present_disabled[w] = c
        else:
            missing[w] = c

    present_disabled_freq = {w: c for w, c in present_disabled.items() if c >= MIN_FREQ}
    missing_freq = {w: c for w, c in missing.items() if c >= MIN_FREQ}
    present_disabled_good = {w: c for w, c in present_disabled_freq.items()
                              if is_good_wubi_word(w, whitelist, base_words)}
    missing_good = {w: c for w, c in missing_freq.items()
                    if is_good_wubi_word(w, whitelist, base_words)}

    os.makedirs(output_dir, exist_ok=True)
    base = os.path.splitext(os.path.basename(sayit_path))[0]
    out_path = os.path.join(output_dir, "%s_语音词组查漏.txt" % base)
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        f.write("# 语音词组查漏结果\n")
        f.write("# 基准：%s（5列；第5列启用码=='A' 视为已在用；有但启用≠'A' 视为已存在未启用）\n"
                % os.path.basename(baseline_tsv))
        f.write("# 语音记录数：%d  候选词组去重：%d  频次阈值：>=%d  合格词组门槛：成词/规则/白名单\n"
                % (len(records), len(all_cands), MIN_FREQ))
        f.write("# " + "=" * 60 + "\n")
        f.write("## 一、建议加入词库（语音有、基准完全无、且为合格词组）共 %d 条\n" % len(missing_good))
        f.write("词组\t频次\n")
        for w, c in sorted(missing_good.items(), key=lambda x: (-x[1], x[0])):
            f.write("%s\t%d\n" % (w, c))
        f.write("# " + "=" * 60 + "\n")
        f.write("## 二、建议启用（语音有、基准有但启用≠'A'、且为合格词组）共 %d 条\n" % len(present_disabled_good))
        f.write("词组\t频次\n")
        for w, c in sorted(present_disabled_good.items(), key=lambda x: (-x[1], x[0])):
            f.write("%s\t%d\n" % (w, c))

    summary = {
        "语音记录数": len(records),
        "候选词组(去重)": len(all_cands),
        "已在用(启用==A)": len(matched),
        "已存在未启用(频次>=%d)" % MIN_FREQ: len(present_disabled_freq),
        "建议启用": len(present_disabled_good),
        "完全缺失(频次>=%d)" % MIN_FREQ: len(missing_freq),
        "建议加入": len(missing_good),
        "输出文件": out_path,
    }
    return out_path, summary
