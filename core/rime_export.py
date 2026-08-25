# -*- coding: utf-8 -*-
"""把当前词库（5 列 TSV 内存数据）导出 / 分发到真实 Rime 词典（deploy 实现）。

复刻 Rime 工具箱 `features/feature_export_to_rime.py` 的语义，
（RimeTool）自包含的纯逻辑模块，不依赖隔壁 Python 工具的 core 包：

  1. 仅保留第 5 列（启用码）= 'A' 的行；B/C/其它不参与。
  2. 用第 3 列作权重，与 词组/编码 组成新码表。
  3. 按第 4 列分组（去 'XX ' 前缀）输出 ## 组名 分段。
  4. 按第 4 列首位字母 A–F 分发写回对应 Rime 词典文件。
  5. 写回前自动备份目标文件；不存在则按标准头创建。

路径约定（与原有 feature 一致）：
  - 默认基准目录 RIME_DIR = 环境变量 RIME_CONFIG_DIR，否则
    dirname(dirname(TSV_PATH)) / "RimeConfig"（运行时按用户实际路径推导，不写死盘符）。
  - Rime 重新编译（重新部署）默认尽力而为：有 RIME_DEPLOYER 或常见部署器则调用，
    否则返回手动重新部署提示，绝不猜测危险命令。
"""
import os
import re
import shutil
import subprocess
from datetime import datetime
from typing import Any, Dict, List, Tuple
import logging

_log = logging.getLogger(__name__)

from core.config import TSV_PATH, is_safe_target
from core import backup as backup_mod

# 默认基准目录 RIME_DIR
RIME_DIR = os.environ.get("RIME_CONFIG_DIR") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(TSV_PATH))), "RimeConfig"
)

# ── 单一数据源：分组首字母 -> (相对 rime_config_dir 的路径, name) ──
# 导出(rime_export) 按此写回；批量权重(weight_replacer) 按此集合（含 chaos 纯引用）读取，
# 保证读写词典集合对称（修复：E/English 之前只写不读，数据无法回灌）。
# 与 Python/features/feature_export_to_rime.DEFAULT_TARGETS 保持一致。
GROUP_TARGETS = {
    "A": ("dicts/wubi.word.dict.yaml", "wubi.word"),
    "B": ("dicts/wubi.phrase.dict.yaml", "wubi.phrase"),
    "C": ("dicts/wubi.user.dict.yaml", "wubi.user"),
    "D": ("dicts/wubi.long.dict.yaml", "wubi.long"),
    "E": ("English.dict.yaml", "English"),
    "F": ("dicts/wubi.low.dict.yaml", "wubi.low"),
}
# 无对应分组字母、仅作权重参考、不导出的词典（保持历史行为：chaos 词也参与权重匹配）
REFERENCE_DICTS = ["dicts/wubi.chaos.dict.yaml"]


def _targets_for(rime_dir: str) -> Dict[str, Tuple[str, str]]:
    """首位字母 -> (目标词典路径, name)；路径随传入的 rime_dir 走，不从模块常量硬算。"""
    return {k: (os.path.join(rime_dir, p), n) for k, (p, n) in GROUP_TARGETS.items()}


# 默认基准（模块级，仅当调用方未传入 rime_dir 时回退）
DEFAULT_TARGETS = _targets_for(RIME_DIR)

WEIGHT_IDX = 2   # 第 3 列：唯一保留的权重
GROUP_IDX = 3    # 第 4 列：分组
ENABLE_IDX = 4   # 第 5 列：启用码

GROUP_PREFIX_RE = re.compile(r"^[A-Z]{1,2}\s+(.*)$")


def _norm_weight(w: str) -> str:
    """权重规范化：正整数，缺失或非数字默认 1。"""
    w = (w or "").strip()
    try:
        return str(int(float(w)))
    except ValueError:
        return "1"


def extract_group_name(col5: str) -> str:
    """第 5 列去 'XX ' 前缀得组名；非标准值整列当组名。"""
    m = GROUP_PREFIX_RE.match(col5 or "")
    if m:
        return m.group(1).strip()
    return (col5 or "").strip()


def read_tsv_rows(filepath: str) -> List[List[str]]:
    """读取 5 列 TSV（兼容 Rime 词典头）：忽略 ... 之前内容与 #/空行，返回分列后的行。

    与 features/feature_export_to_rime.py 的 read_tsv_rows 保持一致。
    """
    with open(filepath, "r", encoding="utf-8-sig") as f:
        lines = f.readlines()
    has_marker = any(line.strip() == "..." for line in lines)
    rows = []
    started = (not has_marker)
    for line in lines:
        s = line.rstrip("\n")
        if not started:
            if s.strip() == "...":
                started = True
            continue
        if not s.strip() or s.strip().startswith("#"):
            continue
        parts = s.split("\t")
        if len(parts) < 2:
            continue
        rows.append([p.strip() for p in parts])
    return rows


def build_export_structure(rows: List[List[str]]) -> Dict[str, Dict[str, List[Tuple[str, str, str]]]]:
    """返回 首位字母 -> {组名 -> [(词组, 编码, 权重), ...]}。

    仅保留 启用码='A' 且 第 5 列首位字母属于 A-F 的行；按 (词组, 编码) 去重。
    rows: 可迭代的 5 字段序列（list/tuple）。
    """
    structure: Dict[str, Dict[str, List[Tuple[str, str, str]]]] = {}
    seen: set = set()
    for parts in rows:
        if len(parts) < 5:
            continue
        if (parts[ENABLE_IDX] or "").strip() != "A":
            continue
        word = (parts[0] or "").strip()
        code = (parts[1] or "").strip()
        if not word:
            continue
        weight = _norm_weight(parts[WEIGHT_IDX] if WEIGHT_IDX < len(parts) else "")
        col5 = (parts[GROUP_IDX] or "").strip() if len(parts) > GROUP_IDX else ""
        letter = col5[:1].upper()
        if letter not in DEFAULT_TARGETS:
            continue
        gname = extract_group_name(col5) or "未命名分组"
        dedup_key = (word, code)
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        structure.setdefault(letter, {}).setdefault(gname, []).append((word, code, weight))
    return structure


def render_groups(groups: Dict[str, List[Tuple[str, str, str]]]) -> str:
    """渲染：## 组名 分段 + 组内 词组\\t编码\\t权重，段间空行。"""
    blocks = []
    for gname in sorted(groups.keys()):
        lines = ["## " + gname, ""]
        for (word, code, weight) in groups[gname]:
            lines.append(word + "\t" + code + "\t" + weight)
        lines.append("")
        blocks.append("\n".join(lines))
    return "\n".join(blocks)


def _head_before_marker(orig: str) -> str:
    """返回 ... 行及其之前的内容（含 ... 行）。"""
    out = []
    for line in orig.split("\n"):
        out.append(line)
        if line.strip() == "...":
            break
    return "\n".join(out)


def build_header(name: str) -> str:
    """生成标准 Rime 词典头（name 由调用方传入，version 取最新日期）。"""
    today = datetime.now().strftime("%Y-%m-%d")
    return (
        "# Rime dictionary: " + name + "\n"
        "# encoding: utf-8\n"
        "---\n"
        "name: " + name + "          # 最常用的、固定词库\n"
        'version: "' + today + '"\n'
        "sort: by_weight\n"
        "dict_grouped: true\n"
        "columns:\n"
        "  - text\n"
        "  - code\n"
        "  - weight\n"
        "...\n"
    )


def write_rime_file(target_path: str, content: str, name: str) -> str:
    """写回 Rime 词典：存在则保留 ... 前内容重写 ... 后；不存在按标准头创建。
    备份（带 Rime- 前缀）由调用方 export_model_to_rime 统一走 core.backup.open_snapshot。
    写回目标先做路径安全校验（防止越权写系统目录，规范 2.5 🟡）。
    返回空串（备份路径由调用方记录）。"""
    target = os.path.abspath(target_path)
    if not is_safe_target(target):
        _log.error("拒绝写回危险系统目录：%s", target)
        return ""
    if os.path.exists(target):
        with open(target, "r", encoding="utf-8-sig") as f:
            orig = f.read()
        head = _head_before_marker(orig)
        new_text = head.rstrip("\n") + "\n" + content.rstrip("\n") + "\n"
        with open(target, "w", encoding="utf-8") as f:
            f.write(new_text)
    else:
        parent = os.path.dirname(target)
        if parent:
            os.makedirs(parent, exist_ok=True)
        header = build_header(name)
        new_text = header.rstrip("\n") + "\n" + content.rstrip("\n") + "\n"
        with open(target, "w", encoding="utf-8") as f:
            f.write(new_text)
    return ""


def export_model_to_rime(rows, rime_dir: str = None) -> Dict[str, Any]:
    """把内存行导出到 Rime 词典。

    返回 dict：{
      "total": int, "written": {letter: {"path":..., "count":...}},
      "backups": [str...], "message": str
    }
    """
    rime_dir = rime_dir or RIME_DIR
    structure = build_export_structure(rows)
    if not structure:
        return {
            "total": 0, "written": {}, "backups": [],
            "message": "没有符合 A-F 分组且启用码为 A 的数据，未写出。",
        }
    written: Dict[str, dict] = {}
    backups: List[str] = []
    for letter in sorted(structure.keys()):
        tp, nm = _targets_for(rime_dir)[letter]
        # 写回前快照（带 Rime- 前缀，整会话仅一次）；不存在则跳过备份直接创建
        bp = backup_mod.open_snapshot(tp, "Rime-")
        if bp:
            backups.append(bp)
        content = render_groups(structure[letter])
        write_rime_file(tp, content, nm)
        cnt = sum(len(v) for v in structure[letter].values())
        written[letter] = {"path": tp, "count": cnt}
    total = sum(w["count"] for w in written.values())
    return {"total": total, "written": written, "backups": backups, "message": ""}


def _find_deployer() -> str:
    """返回 Rime 部署器可执行路径（环境变量优先，否则按系统环境探测，绝不写死盘符）。找不到返回空串。"""
    env = os.environ.get("RIME_DEPLOYER")
    if env and os.path.exists(env):
        return env
    # 从 Windows 标准环境变量推导 Program Files 目录，跨机器/跨盘符可用
    pf = os.environ.get("ProgramFiles")
    pf_x86 = os.environ.get("ProgramFiles(x86)")
    candidates = []
    for base in (pf, pf_x86):
        if base:
            candidates.append(os.path.join(base, "Rime", "weasel", "WeaselDeployer.exe"))
    # 兜底：RIME_DIR 通常在 .../Rime/RimeConfig，部署器在其兄弟目录 weasel 下
    candidates.append(os.path.join(RIME_DIR, "..", "weasel", "WeaselDeployer.exe"))
    for c in candidates:
        if c and os.path.exists(c):
            return c
    return ""


def trigger_rime_deploy(rime_dir: str = None) -> str:
    """尽力触发 Rime 重新部署。有部署器则调用；否则返回手动提示。"""
    deployer = _find_deployer()
    if not deployer:
        return "词典已写出；请到 Rime 输入法状态栏右键 → 『重新部署』使改动生效。"
    try:
        proc = subprocess.run([deployer], timeout=60, capture_output=True)
        if proc.returncode == 0:
            return "已触发 Rime 重新部署。"
        return "已尝试触发重新部署（退出码 %d），如未生效请手动重新部署。" % proc.returncode
    except Exception as exc:  # noqa: BLE001 - 部署器不可用不应阻断主流程
        _log.debug("自动部署失败", exc_info=True)
        return "已写出词典，但自动部署失败（%s）；请手动在 Rime 中重新部署。" % exc


def export_tsv_to_rime(tsv_path: str, rime_dir: str = None) -> Dict[str, Any]:
    """从指定 TSV 文件读出 5 列数据并分发到 Rime 词典。

    参数：
      tsv_path —— 5 列 TSV 文件路径（来自用户文件夹配置，不硬编码）；
      rime_dir —— Rime 配置文件夹（词典写出基准目录）；None 时回退模块级 RIME_DIR。
    返回：与 export_model_to_rime 相同的 dict。
    """
    rows = read_tsv_rows(tsv_path)
    if not rows:
        return {
            "total": 0, "written": {}, "backups": [],
            "message": "未读取到有效数据行（文件不存在或为空）。",
        }
    return export_model_to_rime(rows, rime_dir)


def build_single_tables(rows) -> Dict[str, str]:
    """把内存行按 启用=='A' 拆分为两个码表内容（不含 ... 前头，头由 write_rime_file 补）：

    - 分组列首字母 == 'E' → English.dict.yaml 的内容；
    - 其它首字母（A/B/C/D/F 等）→ wubi.dict.yaml 的内容。
    均按 组名（extract_group_name）做 ## 组名 分段（复用 render_groups）。
    返回 {文件名: 文件体内容(str)}。两个文件都没有启用=A 的数据时返回空串内容。
    """
    eng_groups: Dict[str, List[Tuple[str, str, str]]] = {}
    wubi_groups: Dict[str, List[Tuple[str, str, str]]] = {}
    for parts in rows:
        if len(parts) < 5:
            continue
        if (parts[ENABLE_IDX] or "").strip() != "A":
            continue
        word = (parts[0] or "").strip()
        code = (parts[1] or "").strip()
        if not word:
            continue
        weight = _norm_weight(parts[WEIGHT_IDX] if WEIGHT_IDX < len(parts) else "")
        col5 = (parts[GROUP_IDX] or "").strip()
        letter = col5[:1].upper()
        gname = extract_group_name(col5) or "未命名分组"
        entry = (word, code, weight)
        bucket = eng_groups if letter == "E" else wubi_groups
        bucket.setdefault(gname, []).append(entry)
    return {
        "English.dict.yaml": render_groups(eng_groups),
        "wubi.dict.yaml": render_groups(wubi_groups),
    }
