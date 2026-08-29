"""数据模型：词组记录 WordRecord。

对应数据库表 words，字段：
  词组(text, 主键) / 编码(text, 纯英文小写) / 权重(int, 默认1) /
  分类(text, 枚举) / 分组(text, path串如 数码/手机/旗舰) / 启用(bool, 默认是)
"""

from __future__ import annotations

from typing import Optional

# 分类枚举（与右栏 字/常/用/多/En/符 一一对应）
CATEGORY_CHOICES = ["单字", "常用", "用户", "多码", "英语", "符号"]

# 分类 -> 右栏导出按钮标签
CATEGORY_TO_BUTTON = {
    "单字": "字",
    "常用": "常",
    "用户": "用",
    "多码": "多",
    "英语": "En",
    "符号": "符",
}

# 分组 path 分隔符
GROUP_SEP = "/"


def char_count(text: str) -> int:
    """返回词组的"字数"（按字符计，非字节）。空串返回 0。"""
    return len(text) if text else 0


def word_length_bucket(text: str) -> str:
    """字数分桶：无(空)/一/二/三/四/多(>=5)。供右栏字数筛选用。"""
    n = char_count(text)
    if n == 0:
        return "无"
    if n <= 4:
        return ["一", "二", "三", "四"][n - 1]
    return "多"


class WordRecord:
    """词组记录实体（纯数据，不依赖 Qt）。"""

    __slots__ = ("词组", "编码", "权重", "分类", "分组", "启用")

    def __init__(
        self,
        key: str,
        code: str = "",
        weight: int = 1,
        category: str = "",
        group: str = "",
        enabled: bool = True,
    ) -> None:
        self.词组 = key
        self.编码 = code
        self.权重 = int(weight) if weight else 1
        self.分类 = category
        self.分组 = group
        self.启用 = bool(enabled)

    def as_tuple(self):
        return (self.词组, self.编码, self.权重, self.分类, self.分组, 1 if self.启用 else 0)

    @classmethod
    def from_row(cls, row) -> "WordRecord":
        """从数据库行 (词组,编码,权重,分类,分组,启用) 构造。"""
        return cls(
            key=row[0],
            code=row[1] or "",
            weight=row[2] if row[2] is not None else 1,
            category=row[3] or "",
            group=row[4] or "",
            enabled=bool(row[5]),
        )

    def group_last_level(self) -> str:
        """分组 path 的最后一级名称（数码/手机/旗舰 -> 旗舰）。无分组返回空串。"""
        if not self.分组:
            return ""
        return self.分组.split(GROUP_SEP)[-1]
