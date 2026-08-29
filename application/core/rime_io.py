"""Rime 词典读写与导出。

负责：
- 解析 Rime 用户词典里的权重（批量修改权重用：按 词组+编码 匹配回写库）
- 导出 .dict.yaml（保留表头、version 日期换当前、dict_grouped 分段）
- 导出到 Rime（六分类中启用=是的，分流写 6 词库）
- 部署（复制+触发 Rime 重部署，路径由配置决定）
- 数据库备份 / 恢复
"""

from __future__ import annotations

import os
import re
import shutil
import datetime
from typing import Dict, List, Optional

from .models import WordRecord, CATEGORY_CHOICES


# 分类 -> 相对 rime_user_dir 的词库路径
CATEGORY_FILE_MAP = {
    "单字": r".\dicts\wubi.word.dict.yaml",
    "常用": r".\dicts\wubi.phrase.dict.yaml",
    "用户": r".\dicts\wubi.user.dict.yaml",
    "多码": r".\dicts\wubi.long.dict.yaml",
    "英语": r".\English.dict.yaml",
    "符号": r".\dicts\wubi.low.dict.yaml",
}

# 标准表头模板（导出时 version 日期替换为当前）
HEADER_TEMPLATE = (
    "# Rime dictionary: {name}\n"
    "# encoding: utf-8\n"
    "---\n"
    "name: {name}\n"
    'version: "{date}"\n'
    "sort: by_weight\n"
    "dict_grouped: true\n"
    "columns:\n"
    "  - text\n"
    "  - code\n"
    "  - weight\n"
    "  - stem\n"
    "...\n"
)


def _resolve(rime_user_dir: str, rel: str) -> str:
    """把相对 rime_user_dir 的路径解析为绝对路径。"""
    if os.path.isabs(rel):
        return rel
    return os.path.normpath(os.path.join(rime_user_dir, rel.replace("/", os.sep)))


def _name_from_path(rel: str) -> str:
    base = os.path.basename(rel)
    return re.sub(r"\.dict\.yaml$", "", base)


def parse_dict_weights(path: str) -> Dict[tuple, int]:
    """解析 Rime .dict.yaml，返回 {(词组,编码): 权重}。用于批量修改权重回写。

    支持多段分隔（--- / ...），跳过表头、段头、空行。
    """
    result: Dict[tuple, int] = {}
    if not os.path.exists(path):
        return result
    try:
        with open(path, "r", encoding="utf-8") as f:
            in_data = False
            for line in f:
                line = line.rstrip("\n")
                if not line or line.startswith("#"):
                    continue
                # 多段分隔：--- 进入表头，... 进入数据区
                if line.strip() == "---":
                    in_data = False
                    continue
                if line.strip() == "...":
                    in_data = True
                    continue
                if not in_data:
                    continue
                if line.startswith("##"):
                    continue
                if line.startswith("name:") or line.startswith("version:") or line.startswith("sort:") \
                        or line.startswith("dict_grouped:") or line.startswith("columns:") \
                        or line.startswith("- "):
                    continue
                parts = line.split("\t")
                if len(parts) >= 3:
                    key = parts[0].strip()
                    code = parts[1].strip()
                    try:
                        w = int(float(parts[2].strip()))
                    except ValueError:
                        w = 0
                    result[(key, code)] = w
    except Exception as e:
        # 记录错误但不中断流程
        import logging
        logging.getLogger("rime_io").error("解析词库文件失败 %s: %s", path, e)
    return result


def build_yaml(recs: List[WordRecord], name: str) -> str:
    """把记录集渲染为 .dict.yaml 文本（按分类分流、按分组 ## 分段）。

    仅取各记录自身分类对应的词库；分组段头用分组 path 的最后一级。
    未分组记录放在段前，不写段头。
    """
    date = datetime.date.today().isoformat()
    header = HEADER_TEMPLATE.format(name=name, date=date)

    # 按 分组最后一级 分组（空分组不写段头，直接放段前）
    grouped: Dict[str, List[WordRecord]] = {}
    ungrouped: List[WordRecord] = []
    for r in recs:
        last = r.group_last_level()
        if last:
            grouped.setdefault(last, []).append(r)
        else:
            ungrouped.append(r)

    lines: List[str] = [header]
    if ungrouped:
        for r in ungrouped:
            lines.append(f"{r.词组}\t{r.编码}\t{r.权重}")
    for grp_name in sorted(grouped.keys()):
        lines.append(f"## {grp_name}")
        for r in grouped[grp_name]:
            lines.append(f"{r.词组}\t{r.编码}\t{r.权重}")
    return "\n".join(lines) + "\n"


def export_category(recs: List[WordRecord], category: str, rime_user_dir: str) -> str:
    """导出单个分类全部记录到对应词库，返回目标绝对路径。"""
    rel = CATEGORY_FILE_MAP[category]
    target = _resolve(rime_user_dir, rel)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    name = _name_from_path(rel)
    text = build_yaml([r for r in recs if r.分类 == category], name)
    with open(target, "w", encoding="utf-8") as f:
        f.write(text)
    return target


def export_enabled_to_rime(recs: List[WordRecord], rime_user_dir: str) -> List[str]:
    """导出到 Rime：六分类中 启用=是 的记录，依次分流写 6 个词库。返回导出路径列表。"""
    enabled = [r for r in recs if r.启用]
    targets: List[str] = []
    for cat in CATEGORY_CHOICES:
        cat_recs = [r for r in enabled if r.分类 == cat]
        if cat_recs:
            targets.append(export_category(cat_recs, cat, rime_user_dir))
    return targets


def export_single_table(recs: List[WordRecord], path: str, name: str = "wubi.custom") -> str:
    """保存为单一码表：中栏当前显示记录导出到指定 .dict.yaml（前三列）。"""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    text = build_yaml(recs, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def deploy(rime_user_dir: str, config: dict = None) -> bool:
    """触发 Rime 重新部署。返回是否成功。"""
    import subprocess
    # 优先使用配置中的部署器路径
    deployer = ""
    if config and config.get("rime_deployer_path"):
        deployer = config["rime_deployer_path"]
    if not deployer:
        # 尝试 Weasel 安装目录下的 WeaselDeployer.exe
        candidate = os.path.join(rime_user_dir, "..", "WeaselDeployer.exe")
        candidate = os.path.normpath(candidate)
        if os.path.exists(candidate):
            deployer = candidate
    if deployer and os.path.exists(deployer):
        try:
            # 传 /deploy 参数触发直接部署，工作目录设为 Weasel 安装目录
            deployer_dir = os.path.dirname(deployer)
            subprocess.run([deployer, "/deploy"], check=True, timeout=30, cwd=deployer_dir)
            return True
        except Exception:
            return False
    return False


def backup_database(db_path: str, backup_dir: str) -> str:
    """备份数据库到 backup_dir，返回备份文件路径。"""
    os.makedirs(backup_dir, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = os.path.join(backup_dir, f"data_{ts}.db")
    shutil.copy2(db_path, dst)
    return dst


def restore_database(backup_path: str, db_path: str) -> bool:
    """从备份文件恢复数据库（覆盖）。"""
    if not os.path.exists(backup_path):
        return False
    shutil.copy2(backup_path, db_path)
    return True
