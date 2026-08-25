# -*- coding: utf-8 -*-
"""Rime 词典（dict.yaml）模型：只读预览 + 顶部五框编辑/写回。

dict.yaml 结构：
    ---
    name: wubi
    ...
    词条\t编码\t权重
    词条\t编码

- 头（--- 到 ... 含）原样保留，写回时不丢失；
- 体（... 之后每行）解析为 3 元组（词条, 编码, 权重），权重可空；
- 中栏表格只读（不直接编辑单元格），所有增改经顶部五框 → set_field/add_row_fields → 保存写回。
- 统一接口（与 tsv 侧 DictModel 对齐）：kind / field_cols / get_field / set_field /
  add_row_fields / apply_field_filter / clear_filter / is_dirty / mark_clean / save / reload。
"""
import logging

from PyQt5.QtCore import QAbstractTableModel, QModelIndex, Qt, pyqtSignal
from typing import Dict, List, Optional

_log = logging.getLogger(__name__)


# 顶部五框 → 模型列索引映射（dict.yaml 仅前三列有值）
FIELD_COLS = {"词组": 0, "编码": 1, "权重": 2}
HEADERS = ("词组", "编码", "权重")


class RimeDictModel(QAbstractTableModel):
    dirtyChanged = pyqtSignal(bool)
    FIELD_COLS = FIELD_COLS  # 与模块级常量对齐，供五框联动统一通过 self.FIELD_COLS 访问

    def __init__(self, parent=None):
        super().__init__(parent)
        self._path = ""
        self._header_lines = []      # 头（含 --- 与 ...）按行保存
        self._all_data = []          # 全部数据（3 元组），保存以此为准
        self._order = []             # 显示顺序（指向 _all_data）
        self._groups = []            # 分组名列表（body `## 分组名` 出现顺序，去重）
        self._row_group = []         # 每行词条所属分组名（与 _all_data 同序）
        self._group_filter = ""      # 当前选中的分组筛选（""=全部）
        self._last_fields = {}       # 最近一次 apply_field_filter 的字段条件（叠加分组用）
        self._dirty = False

    # ---- 加载 ----
    def load(self, path: str) -> None:
        self._path = path
        self._header_lines, self._all_data, self._groups, self._row_group = self._parse(path)
        self._order = list(range(len(self._all_data)))
        self._group_filter = ""
        self._last_fields = {}
        self._set_dirty(False)
        self.beginResetModel()
        self.endResetModel()

    @staticmethod
    def _parse(path):
        """返回 (header_lines, rows, groups, row_group)。

        - body 中 `## 分组名` 行标记分组（Rime dict.yaml 约定），其后词条归属该组，
          直到下一个 `##`；row_group[i] 为第 i 行词条所属分组名（无分组则为 ""）。
        - groups 为出现顺序的分组名列表（首次出现去重，保留顺序）。
        """
        header_lines = []
        rows = []
        groups = []
        row_group = []
        sep_found = False
        cur_group = ""
        try:
            with open(path, "r", encoding="utf-8") as f:
                lines = f.read().split("\n")
        except UnicodeDecodeError:
            with open(path, "r", encoding="utf-8-sig") as f:
                lines = f.read().split("\n")
        for line in lines:
            # 去掉行尾 \r（文件可能 CRLF）
            s = line.rstrip("\r")
            if not sep_found:
                header_lines.append(s)
                if s.strip() == "...":
                    sep_found = True
                continue
            s2 = s.strip()
            if not s2:
                continue
            # 分组标记：`## 分组名`（去掉前导 # 后的文本为分组名）
            if s2.startswith("##"):
                cur_group = s2.lstrip("#").strip()
                if cur_group and cur_group not in groups:
                    groups.append(cur_group)
                continue
            parts = s2.split("\t")
            word = parts[0]
            code = parts[1] if len(parts) > 1 else ""
            weight = parts[2] if len(parts) > 2 else ""
            rows.append((word, code, weight))
            row_group.append(cur_group)
        return header_lines, rows, groups, row_group

    def reload(self) -> None:
        if self._path:
            self.load(self._path)

    # ---- 基本接口 ----
    @property
    def kind(self) -> str:
        return "dict"

    @property
    def field_cols(self) -> Dict[str, int]:
        return FIELD_COLS

    def path(self) -> str:
        return self._path

    def name(self) -> str:
        import os
        return os.path.basename(self._path) if self._path else ""

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._order)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(HEADERS)

    def headerData(self, section: int, orientation, role: int = Qt.DisplayRole) -> Optional[str]:
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            if 0 <= section < len(HEADERS):
                return HEADERS[section]
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlags:
        if not index.isValid():
            return Qt.NoItemFlags
        # 只读：不可双击编辑
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Optional[str]:
        if role not in (Qt.DisplayRole, Qt.EditRole):
            return None
        if not index.isValid():
            return None
        row, col = index.row(), index.column()
        if not (0 <= row < len(self._order)):
            return None
        if not (0 <= col < len(HEADERS)):
            return None
        return self._all_data[self._order[row]][col]

    # ---- 脏标记 ----
    def is_dirty(self) -> bool:
        return self._dirty

    def _set_dirty(self, flag):
        if self._dirty != flag:
            self._dirty = flag
            self.dirtyChanged.emit(flag)

    def mark_clean(self) -> None:
        self._set_dirty(False)

    def total_count(self) -> int:
        return len(self._all_data)

    def filtered_count(self) -> int:
        """当前显示的数据行数（筛选后 _order 长度）。与 DictModel 接口对齐。"""
        return len(self._order)

    # ---- 字段接口（供顶部五框） ----
    def get_field(self, view_row: int, field: str) -> str:
        col = FIELD_COLS.get(field)
        if col is None:
            return ""
        return self.data(self.index(view_row, col), Qt.DisplayRole) or ""

    def set_field(self, view_row: int, field: str, value: str) -> bool:
        col = FIELD_COLS.get(field)
        if col is None:
            return False
        idx = self.index(view_row, col)
        old = self.data(idx, Qt.EditRole) or ""
        text = "" if value is None else str(value).strip()
        if text == old:
            return False
        row_list = list(self._all_data[self._order[view_row]])
        row_list[col] = text
        self._all_data[self._order[view_row]] = tuple(row_list)
        self._set_dirty(True)
        self.dataChanged.emit(idx, idx, [Qt.EditRole, Qt.DisplayRole])
        return True

    def add_row_fields(self, fields: Dict[str, str]) -> None:
        word = (fields.get("词组") or "").strip()
        code = (fields.get("编码") or "").strip()
        weight = (fields.get("权重") or "").strip()
        src = len(self._all_data)
        self._all_data.append((word, code, weight))
        self._order.append(src)
        self._set_dirty(True)
        self.beginResetModel()
        self.endResetModel()

    def apply_field_filter(self, fields: Dict[str, str]) -> None:
        """fields: {词组/编码/权重: 值}；空值忽略；多框 AND；子串包含（不区分大小写）。
        同时叠加 _group_filter（分组名筛选）：若已选分组，则只保留该组词条。"""
        self._last_fields = dict(fields)
        gf, active = self._compile_filters(fields, self._group_filter)
        new_order = self._compute_order_list(gf, active)
        self.beginResetModel()
        self._order = new_order
        self.endResetModel()

    def _compile_filters(self, fields, group):
        """把字段条件 + 分组条件编译为 (group_name, {col: 小写值})，供 keep 判定复用。"""
        active = {}
        for f, v in (fields or {}).items():
            col = FIELD_COLS.get(f)
            if col is not None and v:
                active[col] = v.lower()
        return (group or ""), active

    def _compute_order_list(self, gf, active):
        """按 (分组, 字段) 条件预算数据行下标列表（RimeDictModel 无分组头）。"""
        result = []
        for i in range(len(self._all_data)):
            if gf and self._row_group[i] != gf:
                continue
            if all(active[c] in self._all_data[i][c].lower() for c in active):
                result.append(i)
        return result

    # ---- 异步分组/字段筛选支持（P1-⑤：把点分组的全量重建下沉后台线程） ----
    def set_filter_state(self, *, group=None, field=None):
        """仅设置筛选状态、不触发重建（重建由调用方走后台线程 commit_order）。

        与 DictModel.set_filter_state 接口对齐，供 workspace 统一经 _run_background_filter
        把分组/字段筛选异步化，避免中大型 Rime 词典点分组时主线程全表扫描卡顿。"""
        if group is not None:
            self._group_filter = group or ""
        if field is not None:
            self._last_fields = dict(field)

    def snapshot_filters(self):
        """导出当前筛选状态快照，供后台线程 compute_order 预算新顺序。"""
        return {"group": self._group_filter, "field": dict(self._last_fields)}

    def compute_order(self, filters):
        """纯计算：按筛选状态预算新显示顺序（仅数据行下标，无分组头）。

        在后台线程调用，只读取 _all_data/_row_group（RimeDictModel 只读不写）不触碰 GUI，
        与 DictModel.compute_filtered_order 同源思路；过期结果由调用方用代号丢弃。"""
        return compute_rime_order(self._all_data, self._row_group, filters)

    def commit_order(self, new_order):
        """后台线程预算出新顺序后，由主线程调用以原子刷新显示。

        RimeDictModel 无懒加载（全量显示），直接 reset 即可；与 DictModel.commit_order 接口对齐。"""
        self.beginResetModel()
        self._order = new_order
        self.endResetModel()

    def groups(self) -> List[str]:
        """返回该词典解析出的分组名列表（出现顺序）。"""
        return list(self._groups)

    def set_group_filter(self, name: str) -> None:
        """设置/清除分组筛选：name 为空串表示「全部」。

        点分组即视为「清空五框」（需求3），故同时清空字段筛选（_last_fields），
        避免旧列筛选残留叠加（Bug A）。"""
        self._group_filter = name or ""
        self._last_fields = {}
        self.apply_field_filter({})

    def clear_filter(self) -> None:
        self._group_filter = ""
        self._last_fields = {}
        self.apply_field_filter({})

    # ---- 写回 ----
    def save(self, path: Optional[str] = None) -> bool:
        target = path or self._path
        if not target:
            return False
        # P1-③ 修复：写回前经 is_safe_target 校验，拒绝落到危险系统目录（与 write_tsv /
        # weight_replacer 等写回点统一安全护栏），避免越权写坏系统文件。
        from core.config import is_safe_target
        if not is_safe_target(target):
            _log.error("拒绝写回不安全路径：%s", target)
            return False
        lines = list(self._header_lines)
        # 确保头以 ... 结束
        if not lines or lines[-1].strip() != "...":
            lines.append("...")
        body = ["\t".join(r) for r in self._all_data]
        with open(target, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(lines) + "\n")
            if body:
                f.write("\n".join(body) + "\n")
        self._set_dirty(False)
        return True


def compute_rime_order(data, row_group, filters):
    """模块级纯函数：按筛选状态预算 RimeDictModel 的显示顺序（数据行下标）。

    与 RimeDictModel.compute_order 同源，抽为模块级以便后台线程在 _all_data/_row_group 的
    **快照副本**上计算，避免与主线程的追加/重排并发访问同一 list 对象导致 C 层迭代器失效
    段错误（即「追加一个词组到 tsv 后程序直接退出」的根因：FilterThread/RimeGroupThread 跨线程
    遍历与主线程 append 同一个 list）。调用方务必传入启动前拷贝的 list 快照，而非共享引用。"""
    gf = (filters.get("group") or "")
    fields = filters.get("field") or {}
    active = {}
    for f, v in (fields or {}).items():
        col = FIELD_COLS.get(f)
        if col is not None and v:
            active[col] = v.lower()
    result = []
    for i in range(len(data)):
        if gf and row_group[i] != gf:
            continue
        if all(active[c] in data[i][c].lower() for c in active):
            result.append(i)
    return result
