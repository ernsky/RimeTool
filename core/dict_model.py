# -*- coding: utf-8 -*-
"""虚拟表数据模型（Model 层）：可编辑、懒加载、排序、筛选、增删行。

只负责数据逻辑，不碰任何 UI 构件——UI 在 ui/workspace_window.py。
"""
import re
import logging

_log = logging.getLogger(__name__)

from PyQt5.QtCore import QAbstractTableModel, QModelIndex, Qt, pyqtSignal, QMimeData, QByteArray
from PyQt5.QtGui import QColor, QFont
from typing import Dict, List, Optional, Set, Tuple

from core.config import (BATCH_INITIAL, BATCH_LATER, HEADERS, NUMERIC_COLS,
                         FILTER_COLS, THEME)

# 分组头行的标记元组：("H", 组名)
HEADER_MARK = "H"


class DictModel(QAbstractTableModel):
    """可编辑的虚拟表模型；排序/筛选作用在 _order 索引列表上。"""

    dirtyChanged = pyqtSignal(bool)   # 脏数据状态变化：True=已修改，False=已保存/刚加载

    def __init__(self, parent=None):
        super().__init__(parent)
        self._all_data = []   # 全部数据（原始顺序），元素为 5 字段元组
        self._order = []      # 当前显示顺序（指向 _all_data 的行索引）
        self._loaded = 0      # 已加载到视图的行数
        self._dirty = False   # 是否有未保存修改
        self._order_dirty = False   # 方案①：_order 是否被拖拽/移动改动（延迟归并回 _all_data 的标志）
        # _drag_dirty：与 _order_dirty 区分「拖拽重排」与「表头排序」造成的脏。
        # 后台筛选(_run_background_filter)的预同步只应在「拖拽重排」后固化物理顺序时执行；
        # 表头排序(_order_dirty=True 但 _drag_dirty=False)无需预同步——筛选基于值、与物理序无关，
        # 否则百万行词库点击分组会触发 1.6M 全量 _sync_order_to_data 卡顿（P1-① 连带修复）。
        self._drag_dirty = False
        # 组合筛选状态：文本 / 五框字段 / 分组（三者 AND 叠加）
        self._text_filter = ""
        self._field_filter = {}
        self._group_filter = ""
        # 五要素不全筛选（tsv 5 列专属）：开启时仅保留 词组/编码/权重/分组/启用 任一缺失的行
        self._incomplete_filter = False
        # 字数筛选（功能1）：-1=关；0~4=词组列精确字符数；5=字符数≥5（"多"）。
        # 注意：UI 的「无」按钮映射为 -1（清除本筛选、显示全部），不表示 0 字。
        self._char_count_filter = -1
        # 一词多码筛选（功能2）：开启时仅保留「同一词组存在 ≥2 个互异编码」的行
        self._multi_code_filter = False
        self._multi_code_srcs = set()
        # 重复项筛选：开启时仅保留 (词组,编码) 完全相同的重复行，并按 (词组,编码) 聚拢相邻
        self._dup_only_filter = False
        # 分组视图：在「全部」视图下于数据行前插入 ("H",组名) 分组头行（tsv 默认开启）
        self._grouped = True
        # 分组头行视觉样式（主题无关：玫红加粗文字，区别于数据行）
        self._header_font = QFont()
        self._header_font.setBold(True)
        self._header_fg = QColor(THEME["primary"])
        # 重复词条高亮（P0-2）：_dup_srcs = _all_data 下标集合（key=词组+编码 即列0+列1）；
        # _show_dup 控制是否着色（默认关，避免百万行无谓渲染）；_dup_bg 为琥珀色半透明底，浅/深主题均可见。
        self._show_dup = False
        self._dup_srcs = set()
        self._dup_bg = QColor(255, 193, 7, 55)
        # 加载时预算好的分组列去重列表（与 distinct_values(分组列) 结果一致）；
        # _populate_groups 直接取此缓存，免主线程再扫全表（加载优化）。
        self._distinct_groups_cache = []
        # 懒计算状态标志：dup_srcs / multi_srcs 是否在加载后已被实际算过。
        # 加载走轻量预计算（compute_load_minimal）时不算这俩，置 False；
        # 待用户首次启用「重复高亮」(set_show_duplicates) / 「一词多码筛选」
        # (set_multi_code_filter / set_filter_state) 时（或编辑触发重算时）置 True。
        self._dup_computed = False
        self._multi_computed = False
        # 后台排序线程（P1-① 修复：百万行点击表头/恢复排序时主线程全表排序会卡顿白屏，
        # 改为超阈值(见 SORT_THRESHOLD)走子线程，主线程仅做结果刷新 + token 丢弃过期结果）
        self._sort_thread = None
        self._sort_token = 0

    # ---- 数据就绪后由主线程调用 ----
    def set_all_data(self, data: List[List[str]], total: int, extras: Optional[dict] = None) -> None:
        """全量载入。extras 为后台线程预算的派生结果（见 compute_load_minimal /
        compute_load_extras）；缺省则主线程自算完整版（保持测试 (data, total) 两参调用的向后兼容）。

        懒计算：extras 来自 LoadThread 时只含 initial_order + distinct_groups（compute_load_minimal），
        不含 dup_srcs / multi_srcs——这俩默认关闭的功能推迟到用户首次启用「重复高亮」/
        「一词多码筛选」时才 O(n) 重算（见 set_show_duplicates / set_multi_code_filter /
        set_filter_state）。故 160 万行加载只付一次轻量扫描，界面不冻结、也不白算未启用功能。
        """
        self._all_data = data
        self._loaded = 0
        self._set_dirty(False)
        if extras is None:
            extras = compute_load_extras(data)
        # dup_srcs / multi_srcs 懒计算：若 extras 已含（完整预计算，如测试/回退路径）则直接用并标记已算；
        # 否则（LoadThread 走 compute_load_minimal，省去这俩默认关闭功能）置空 + 标记未算，
        # 推迟到用户真正启用「重复高亮」(set_show_duplicates) / 「一词多码筛选」
        # (set_multi_code_filter / set_filter_state) 时再算，避免 160 万行加载白付 O(n) 扫描。
        if "dup_srcs" in extras:
            self._dup_srcs = extras["dup_srcs"]
            self._dup_computed = True
        else:
            self._dup_srcs = set()
            self._dup_computed = False
        if "multi_srcs" in extras:
            self._multi_code_srcs = extras["multi_srcs"]
            self._multi_computed = True
        else:
            self._multi_code_srcs = set()
            self._multi_computed = False
        self._distinct_groups_cache = extras.get("distinct_groups", [])
        self.beginResetModel()
        self._order = extras["initial_order"]
        self._loaded = 0
        self.endResetModel()
        if self.canFetchMore(QModelIndex()):
            self.fetchMore(QModelIndex())

    def rows(self) -> List[List[str]]:
        """返回原始顺序的全部数据（保存时用）。"""
        return self._all_data

    def is_dirty(self) -> bool:
        return self._dirty

    def _set_dirty(self, flag):
        if self._dirty != flag:
            self._dirty = flag
            self.dirtyChanged.emit(flag)

    def mark_clean(self) -> None:
        self._set_dirty(False)

    # ---- 模型基本接口 ----
    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return min(self._loaded, len(self._order))

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(HEADERS)

    def headerData(self, section: int, orientation, role: int = Qt.DisplayRole) -> Optional[str]:
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            if 0 <= section < len(HEADERS):
                return HEADERS[section]
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlags:
        if not index.isValid():
            return Qt.ItemIsDropEnabled   # 表尾/空白允许放下（InternalMove 需要 drop-enabled）
        el = self._order[index.row()]
        # 分组头行：仅可见，不可选/不可编辑/不可拖（避免被选中或误改）
        if isinstance(el, tuple) and el and el[0] == HEADER_MARK:
            return Qt.ItemIsEnabled
        # 基础标志：可选/可拖放；仅「分组列/启用列」可双击单元格内下拉编辑，
        # 其余列（词组/编码/权重）保持只读——编辑统一走顶栏五框（设计：表格只读 + 顶栏录入）。
        base = Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsDragEnabled | Qt.ItemIsDropEnabled
        if index.column() in (self.FIELD_COLS["分组"], self.FIELD_COLS["启用"]):
            base |= Qt.ItemIsEditable
        return base

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Optional[str]:
        # DisplayRole / EditRole 返回单元格文本；ForegroundRole / FontRole 用于分组头行样式；
        # BackgroundRole 用于重复词条高亮（P0-2）。
        if role not in (Qt.DisplayRole, Qt.EditRole, Qt.ForegroundRole, Qt.FontRole, Qt.BackgroundRole):
            return None
        if not index.isValid():
            return None
        row = index.row()
        col = index.column()
        if not (0 <= row < len(self._order)):
            return None
        el = self._order[row]
        # 分组头行：第 0 列显示组名，整行玫红加粗，其余列空白、不可编辑
        if isinstance(el, tuple) and el and el[0] == HEADER_MARK:
            if role == Qt.ForegroundRole:
                return self._header_fg
            if role == Qt.FontRole:
                return self._header_font
            if role == Qt.DisplayRole and col == 0:
                return el[1]
            return None
        if not isinstance(el, int):
            return None
        if row >= self._loaded:
            return None
        if not (0 <= col < len(HEADERS)):
            return None
        # 重复词条背景高亮：仅当开启高亮且该数据行属于重复组（key=词组+编码）
        if role == Qt.BackgroundRole:
            if self._show_dup and el in self._dup_srcs:
                return self._dup_bg
            return None
        return self._all_data[el][col]

    def setData(self, index: QModelIndex, value, role: int = Qt.EditRole) -> bool:
        if role not in (Qt.EditRole, Qt.DisplayRole):
            return False
        if not index.isValid():
            return False
        row = index.row()
        col = index.column()
        if not (0 <= row < len(self._order)) or row >= self._loaded:
            return False
        src = self._order[row]
        if not isinstance(src, int):
            return False
        text = "" if value is None else str(value).strip()
        # 数值列：尝试归一化为整数文本；失败（非数字/空）则保留原样，绝不抛异常
        if col in NUMERIC_COLS:
            if text != "":
                try:
                    text = str(int(text))
                except ValueError:
                    pass
        # 未真正修改（与原值相同）：保持原数据，不标脏、不发射，默认不保存
        if text == self._all_data[src][col]:
            return True
        row_list = list(self._all_data[src])
        row_list[col] = text
        self._all_data[src] = tuple(row_list)
        self._set_dirty(True)
        if col in (0, 1):
            # M4 修复：惰性重算。仅当对应功能真正启用（重复高亮 / 重复项筛选 / 一词多码筛选）
            # 时才立即付 2×O(n) 全表扫描；否则只置「未计算」标志，推迟到用户首次启用相关功能时
            # 再算，避免每次编辑词组/编码列都无谓扫整张百万行表（卡顿根源）。
            if self._show_dup or self._dup_only_filter:
                self.recompute_duplicates()
            else:
                self._dup_computed = False
            if self._multi_code_filter:
                self.recompute_multi_code()
            else:
                self._multi_computed = False
        elif col == self.FIELD_COLS["分组"]:
            # L2 修复：改了「分组」列 → 行归属变化，需重建显示顺序以把行重插到正确的分组头下
            # （否则行停留原地、显示在新旧分组头错位处）。物理重排延迟到保存时统一归并。
            self._rebuild_order_keep_loaded()
        self.dataChanged.emit(index, index, [role])
        return True

    # ---- 懒加载核心 ----
    def canFetchMore(self, parent: QModelIndex) -> bool:
        if parent.isValid():
            return False
        return self._loaded < len(self._order)

    def fetchMore(self, parent: QModelIndex) -> None:
        if parent.isValid() or self._loaded >= len(self._order):
            return
        batch = BATCH_INITIAL if self._loaded == 0 else BATCH_LATER
        n = min(batch, len(self._order) - self._loaded)
        first = self._loaded
        last = first + n - 1
        self.beginInsertRows(parent, first, last)
        self._loaded += n
        self.endInsertRows()

    # ---- 排序：点击表头触发 ----
    # 超过此行数走后台线程排序，避免主线程全表排序卡顿/白屏（大词库；小词库同步更快）
    SORT_THRESHOLD = 200_000

    def sort(self, column: int, order: Qt.SortOrder) -> None:
        if not (0 <= column < len(HEADERS)):
            return
        reverse = (order == Qt.DescendingOrder)
        # 仅对数据行排序；手动列排序 = 平铺视图（暂不插分组头，下次筛选/分组时再恢复）
        data_idx = [e for e in self._order if isinstance(e, int)]
        if len(data_idx) <= self.SORT_THRESHOLD:
            # 小词库：主线程同步排序，立即生效、响应更快
            self._commit_sort(data_idx, column, reverse)
        else:
            # 大词库：后台排序，主线程立即返回，杜绝启动白屏 / 点击分组卡顿
            token = self._sort_token + 1
            self._sort_token = token
            self._stop_sort_thread()
            from core.io_tsv import SortThread
            # 竞态修复（同 _run_background_filter/RimeGroupThread）：子线程操作启动前拷贝的快照，
            # 避免排序期间主线程追加/重排 _all_data 引发 C 层段错误。
            th = SortThread(list(self._all_data), data_idx, column, reverse)
            th.finished_order.connect(
                lambda idx, t=token: self._on_sorted(idx, t))
            th.error.connect(lambda m: _log.warning("后台排序失败：%s", m))
            th.finished.connect(th.deleteLater)
            self._sort_thread = th
            th.start()

    def _stop_sort_thread(self):
        """停止仍在跑的后台排序线程（closeEvent 等退出路径调用，避免线程随模型销毁悬空）。"""
        th = getattr(self, "_sort_thread", None)
        if th is not None and th.isRunning():
            th.quit()

    def _on_sorted(self, sorted_idx: list, token: int) -> None:
        if token != self._sort_token:
            return  # 过期结果（已有更新的排序请求），丢弃
        self._commit_sort(sorted_idx, None, False)

    def _commit_sort(self, data_idx: list, column, reverse) -> None:
        if column is not None:
            # 同步路径：就地按列排序（线程路径已在子线程排好，column=None 跳过）
            def key(i):
                v = self._all_data[i][column]
                if column in NUMERIC_COLS:
                    try:
                        return (0, int(v))
                    except ValueError:
                        return (1, v)
                return (0, v)
            data_idx.sort(key=key, reverse=reverse)
        self.layoutAboutToBeChanged.emit()
        self._order = data_idx
        # P1-① 修复：排序不再强制全量加载（原 self._loaded = len(self._order) 会令百万行
        # 词库在点击表头/恢复排序瞬间物化全部行 → 启动白屏 + 点击分组变慢 + 视图卡顿）。
        # 保留懒加载边界：已加载多少行就继续显示多少行，其余随滚动按需 fetchMore。
        self._loaded = min(self._loaded, len(self._order))
        # L1 修复：表头排序改动了显示顺序，必须标记延迟归并；否则保存时 _sync_order_to_data
        # 因为 _order_dirty 未置位而直接返回，排序结果被静默丢弃、落盘仍是旧序。
        self._order_dirty = True
        self.layoutChanged.emit()

    # ---- 拖拽重排（组内重排的前置：拖动行改变显示顺序，按「组内重排」才固化进文件） ----
    _MIME = "application/x-rime-roworder"

    def supportedDropActions(self) -> Qt.DropActions:
        return Qt.MoveAction

    def mimeData(self, indexes) -> QMimeData:
        rows = sorted({ix.row() for ix in indexes if ix.isValid()})
        m = QMimeData()
        m.setData(self._MIME, QByteArray(",".join(str(r) for r in rows).encode("utf-8")))
        return m

    def dropMimeData(self, data: QMimeData, action: Qt.DropAction, row: int, column: int, parent: QModelIndex) -> bool:
        if action != Qt.MoveAction or not data.hasFormat(self._MIME):
            return False
        try:
            src_rows = [int(x) for x in bytes(data.data(self._MIME)).decode("utf-8").split(",") if x != ""]
        except Exception:  # noqa: BLE001 - 拖拽数据解析失败
            _log.debug("拖拽数据解析失败", exc_info=True)
            return False
        moving = [r for r in src_rows if 0 <= r < len(self._order) and isinstance(self._order[r], int)]
        if not moving:
            return False
        moving_set = set(moving)
        src_data = [self._order[r] for r in moving]   # 按当前显示顺序保存源数据下标
        # 从 _order 剔除被移动项，并去掉分组头（头在重排后按归属重新插入），得到纯数据序列
        rest = [e for i, e in enumerate(self._order) if i not in moving_set and isinstance(e, int)]
        # dropMimeData 的 row 为显示行号；这里以剔除头/被移动项后的纯数据序列为基准定位
        insert_at = row if (0 <= row <= len(rest)) else len(rest)
        rest[insert_at:insert_at] = src_data
        # 分组视图下依据新的数据顺序重新插入分组头（按实际分组归属，避免行落到错误分组头下）
        new_order = self._reinsert_group_headers(rest) if self._grouped else rest
        self.layoutAboutToBeChanged.emit()
        self._order = new_order
        self._loaded = sum(1 for e in self._order if isinstance(e, int))
        self.layoutChanged.emit()
        self._set_dirty(True)
        self._order_dirty = True
        self._drag_dirty = True
        return True

    def _reinsert_group_headers(self, data_order):
        """依据数据行的实际分组归属，在 data_order 序列上重新插入分组头（HEADER_MARK）。
        用于拖拽/手动重排后保持分组头与数据行一致。"""
        if not self._grouped:
            return data_order
        grp_col = self.FIELD_COLS["分组"]
        new_order = []
        last_g = None
        for i in data_order:
            g = self._all_data[i][grp_col] or "（无分组）"
            if g != last_g:
                new_order.append((HEADER_MARK, g))
                last_g = g
            new_order.append(i)
        return new_order

    # ---- 筛选（文本 / 五框字段 / 分组 / 五要素不全 四者 AND 叠加） ----
    def _is_row_incomplete(self, row_list) -> bool:
        """五要素（词组/编码/权重/分组/启用，即列 0~4）任一为空或纯空白即视为不全。"""
        return _row_incomplete(row_list)

    def _rebuild_order(self):
        """按当前筛选状态重建显示顺序（含分组头）。

        纯扫描部分抽为模块级 compute_filtered_order，供后台筛选线程复用同一逻辑；
        本方法保留主线程上的模型通知（beginResetModel/endResetModel/fetchMore），
        并被程序内同步调用（增删/合并/移动等需立即看到结果处）使用。"""
        self._sync_order_to_data()   # 方案①：全扫前先固化拖拽产生的 _order 改动，避免丢失
        filters = self.snapshot_filters()
        new_order = compute_filtered_order(self._all_data, filters)
        self.beginResetModel()
        self._order = new_order
        self._loaded = 0
        self.endResetModel()
        if self.canFetchMore(QModelIndex()):
            self.fetchMore(QModelIndex())

    def apply_filter(self, text: str) -> None:
        self._text_filter = text or ""
        self._rebuild_order()

    # ---- 行操作：添加 / 删除 ----
    def add_row(self) -> int:
        """在末尾追加一个 5 空字段的行，并重建显示顺序（含分组头），使新行可见。
        返回新行的 _all_data 真实下标。"""
        src = len(self._all_data)
        self._all_data.append(tuple("" for _ in range(5)))
        self._set_dirty(True)
        self._rebuild_order()
        self.recompute_duplicates()       # 空行(key=空+空)可能并入重复组，重算
        self.recompute_multi_code()       # 新增行可能影响「一词多码」集合
        # 仅把新行纳入「已加载边界」，不强制全表加载（保留虚拟表懒加载）：
        # _rebuild_order 已把 _loaded 重置为首批批量（见其实现），此处只把 _loaded 上推到足以
        # 覆盖新行显示位置的最小边界；若新行不在当前筛选结果中（new_view_row==-1），则保持懒加载。
        # 注：未筛选的大表把新行追加在末尾，上推到末尾等价于全表加载——这是「末尾追加」语义下的固有代价，
        # 但已消除「无条件 _loaded = len(_order)」对筛选视图/中小表的过度加载。
        new_view_row = self._view_row_of_data(src)
        if new_view_row >= 0:
            self._loaded = max(self._loaded, new_view_row + 1)
        return src

    def delete_rows_by_view(self, view_rows: List[int]) -> int:
        """按显示行号批量删除（自动跳过分组头行）；删除后一次性重建顺序。返回删除行数。"""
        srcs = []
        for vr in view_rows:
            if not (0 <= vr < len(self._order)):
                continue
            e = self._order[vr]
            if isinstance(e, int):
                srcs.append(e)
        srcs = sorted(set(srcs), reverse=True)
        if not srcs:
            return 0
        drop = set(srcs)
        new = [r for i, r in enumerate(self._all_data) if i not in drop]
        self._all_data = new
        self._set_dirty(True)
        self._rebuild_order()
        self.recompute_duplicates()       # 删除后重复集合变化，重算
        self.recompute_multi_code()       # 删除后「一词多码」集合变化，重算
        return len(srcs)

    def delete_row(self, view_row: int) -> bool:
        """删除单个显示行（封装到 delete_rows_by_view）。"""
        return self.delete_rows_by_view([view_row]) > 0

    def _view_row_of_data(self, src):
        """返回 _all_data 真实下标 src 在显示顺序中的行号（找不到返回 -1）。"""
        for vr, e in enumerate(self._order):
            if isinstance(e, int) and e == src:
                return vr
        return -1

    # ---- 顶部五框字段接口（供 workspace 顶部录入/搜索区使用） ----
    # 顶部五框（词组/编码/权重/分组/启用）→ 5 列 tsv 的对应列索引。
    FIELD_COLS = {"词组": 0, "编码": 1, "权重": 2, "分组": 3, "启用": 4}

    def get_field(self, view_row: int, field: str) -> str:
        col = self.FIELD_COLS.get(field)
        if col is None:
            return ""
        el = self._order[view_row] if 0 <= view_row < len(self._order) else None
        if not isinstance(el, int):
            return ""
        return self.data(self.index(view_row, col), Qt.DisplayRole) or ""

    def set_field(self, view_row: int, field: str, value: str) -> bool:
        col = self.FIELD_COLS.get(field)
        if col is None:
            return False
        return self.setData(self.index(view_row, col), value, Qt.EditRole)

    def add_row_fields(self, fields: Dict[str, str]) -> int:
        """按五框值追加一行；返回新行在显示顺序中的行号。

        M1 修复：直接在物理行 _all_data[src] 上写各字段，绕开「先重建显示顺序→再按显示行号回填」
        的链路——当存在筛选（如字数筛选只显示 2 字词组）时新行可能不匹配筛选，
        _view_row_of_data(src) 返回 -1，原写法 set_field(-1, ...) 静默失败、把用户输入丢掉。
        直接写物理行保证输入不丢；随后 _rebuild_order（_all_data 已含新值）才决定其是否可见。
        """
        src = self.add_row()
        row_list = list(self._all_data[src])
        changed = False
        for f in ("词组", "编码", "权重", "分组", "启用"):
            v = fields.get(f)
            if v:
                col = self.FIELD_COLS[f]
                row_list[col] = v
                changed = True
        if changed:
            self._all_data[src] = tuple(row_list)
            self._set_dirty(True)
            # 词组/编码变更影响重复 / 一词多码集合，与 setData 一致重算
            self.recompute_duplicates()
            self.recompute_multi_code()
        new_view_row = self._view_row_of_data(src)
        if new_view_row >= 0:
            self._loaded = max(self._loaded, new_view_row + 1)
        return new_view_row

    def add_rows_fields(self, fields_list: List[Dict[str, str]]) -> int:
        """批量按五框值追加多行；返回新增条数。

        关键性能修复：逐行 add_row_fields 会触发「全表 compute_filtered_order 扫描 +
        两次全表重算」每行一次；在百万行词库上粘贴多行词组时退化为 O(行数×总行数)，
        表现为点击「追加」后长时间无响应（死机）。本方法把多行一次性写入 _all_data，
        末尾只做一次 _rebuild_order + 一次重算集合，复杂度降为 O(总行数 + 新增行数)。
        """
        if not fields_list:
            return 0
        new_srcs = []
        for fields in fields_list:
            src = len(self._all_data)
            self._all_data.append(tuple("" for _ in range(5)))
            self._set_dirty(True)
            for f in ("词组", "编码", "权重", "分组", "启用"):
                v = fields.get(f)
                if v:
                    col = self.FIELD_COLS[f]
                    row_list = list(self._all_data[src])
                    row_list[col] = v
                    self._all_data[src] = tuple(row_list)
            new_srcs.append(src)
        # 仅在此处做一次显示顺序重建 + 派生集合重算（而非每行一次）
        self._rebuild_order()
        self.recompute_duplicates()
        self.recompute_multi_code()
        # 上推懒加载边界覆盖新增行（与 add_row 末尾逻辑一致）
        for s in new_srcs:
            vr = self._view_row_of_data(s)
            if vr >= 0:
                self._loaded = max(self._loaded, vr + 1)
        return len(new_srcs)

    def apply_field_filter(self, fields: Dict[str, str]) -> None:
        """fields: {五框名: 值}；空值忽略；多框 AND；子串包含（不区分大小写）。"""
        active = {}
        for f, v in (fields or {}).items():
            col = self.FIELD_COLS.get(f)
            if col is not None and v:
                active[col] = v.lower()
        self._field_filter = active
        self._rebuild_order()

    def set_group_filter(self, name: str) -> None:
        """按分组名筛选（与文本/字段筛选 AND 叠加）；同 RimeDictModel.set_group_filter。"""
        self._group_filter = name or ""
        self._rebuild_order()

    def set_incomplete_filter(self, on: bool) -> None:
        """开关『五要素不全』筛选（tsv 5 列专属）：开启时仅保留 词组/编码/权重/分组/启用 任一缺失的行。"""
        self._incomplete_filter = bool(on)
        self._rebuild_order()

    def clear_filter(self) -> None:
        """清除全部筛选（文本 / 五框字段 / 分组 / 五要素不全 / 重复项），恢复显示全部行。"""
        self._text_filter = ""
        self._field_filter = {}
        self._group_filter = ""
        self._incomplete_filter = False
        self._char_count_filter = -1
        self._multi_code_filter = False
        self._dup_only_filter = False
        self._rebuild_order()

    def snapshot_filters(self) -> dict:
        """导出当前全部筛选状态快照，供后台线程 compute_filtered_order 预算新顺序。"""
        return {
            "text": self._text_filter,
            "field": self._field_filter,
            "group": self._group_filter,
            "incomplete": self._incomplete_filter,
            "char_count": self._char_count_filter,
            "multi_code": self._multi_code_filter,
            "multi_code_srcs": self._multi_code_srcs,
            "dup_only": self._dup_only_filter,
            "grouped": self._grouped,
        }

    def set_filter_state(self, *, text=None, field=None, group=None, incomplete=None,
                         char_count=None, multi_code=None, dup_only=None) -> None:
        """仅设置筛选状态，不触发重建（重建由调用方显式走后台线程 commit_order）。

        用于大词库把筛选计算下沉后台，避免主线程全表扫描卡顿；dict 模式与单测仍走
        各 set_*_filter 公共方法的同步 _rebuild_order 路径，不受影响。"""
        if text is not None:
            self._text_filter = text or ""
        if field is not None:
            active = {}
            for f, v in (field or {}).items():
                col = self.FIELD_COLS.get(f)
                if col is not None and v:
                    active[col] = v.lower()
            self._field_filter = active
        if group is not None:
            self._group_filter = group or ""
        if incomplete is not None:
            self._incomplete_filter = bool(incomplete)
        if char_count is not None:
            try:
                self._char_count_filter = int(char_count)
            except (TypeError, ValueError):
                self._char_count_filter = -1
        if multi_code is not None:
            if multi_code and not self._multi_computed:
                self.recompute_multi_code()   # 懒计算：tsv 后台筛选首次启用一词多码时才算
            self._multi_code_filter = bool(multi_code)
        if dup_only is not None:
            if dup_only and not self._dup_computed:
                self.recompute_duplicates()   # 懒计算：首次启用重复项筛选时才算重复集合
            self._dup_only_filter = bool(dup_only)

    def commit_order(self, new_order: list, restore_loaded: bool = True) -> None:
        """后台线程预算出新顺序后，由主线程调用以原子刷新显示（含懒加载到切换前的规模）。

        restore_loaded=True 时，先把已加载规模还原到切换前（_loaded），避免 160 万行大表切分组后
        只显示前 BATCH_INITIAL(200) 行，造成「白屏」感知（Bug #7）。"""
        prev_loaded = self._loaded if restore_loaded else 0
        self.beginResetModel()
        self._order = new_order
        # L3 修复：后台筛选算出的新顺序是「已与 _all_data 同步后」的权威显示序，不应再带脏标志；
        # 否则后续 _sync_order_to_data 会据此把显示序反写回 _all_data，破坏数据。
        self._order_dirty = False
        self._loaded = 0
        self.endResetModel()
        if self.canFetchMore(QModelIndex()):
            self.fetchMore(QModelIndex())
        # 还原到切换前的已加载规模（最多到新顺序长度），消除「切分组只显示前 200 行」
        target = min(prev_loaded, len(self._order))
        while self._loaded < target and self.canFetchMore(QModelIndex()):
            self.fetchMore(QModelIndex())

    def distinct_values(self, col: int) -> List[str]:
        """返回第 col 列去重后的排序列表（空值忽略），供下拉框填充。"""
        if not (0 <= col < len(HEADERS)):
            return []
        seen = set()
        for row in self._all_data:
            v = row[col]
            if v:
                seen.add(v)
        return sorted(seen)

    def get_distinct_groups(self) -> List[str]:
        """返回加载时预算好的分组列去重列表（与 distinct_values(分组列) 结果一致）。

        供左侧分组面板填充使用，避免加载完成后再扫全表（加载优化）；
        若尚未加载则回退空列表（调用方应已先 set_all_data）。
        """
        return self._distinct_groups_cache

    # ---- 批量移动到指定分组 ----
    def move_selected_to_group(self, view_rows: List[int], group_name: Optional[str] = None,
                               also_enable: Optional[bool] = None,
                               enable_value: Optional[str] = None) -> Tuple[int, int]:
        """批量改选中行的「分组」和/或「启用」。

        - group_name: 非 None/非空 → 把这些行的分组列(3)写成 group_name（并物理重排到目标组
          槽位末尾）；None/空 → 不改分组。
        - 启用列(4)的新值按以下优先级决定：
            * enable_value is not None → 直接采用（"" 表示清空、其它为自定义值）；
            * also_enable is not None（旧接口兼容）→ True 置 'A'、False 不改；
            * 两者都未给 → 不改启用。
        保留其它字段；5 列 schema 下不再维护顺序码列。改写后这些行会被物理重排到目标组
        现有成员之后（组内追加到尾），使 _rebuild_order 在目标组头下把移动行显示在该组末尾。
        仅改启用（不改分组）时只刷新受影响单元格，不重排分组。
        返回 (changed_count, first_changed_view_row)。无变更返回 (0, -1)。
        """
        change_group = bool(group_name)
        # 解析启用改动意图（优先级：enable_value > also_enable > 不改）
        if enable_value is not None:
            change_enable = True
            enable_val = enable_value
        elif also_enable is not None:
            change_enable = also_enable
            enable_val = "A" if also_enable else None
        else:
            change_enable = False
            enable_val = None
        if not change_group and not change_enable:
            return (0, -1)

        group_col = self.FIELD_COLS["分组"]
        enable_col = self.FIELD_COLS["启用"]
        changed = 0
        changed_srcs = []   # 实际被改写的源行（物理下标），用于物理重排
        new_all = [list(r) for r in self._all_data]
        for vr in view_rows:
            if not (0 <= vr < len(self._order)):
                continue
            src = self._order[vr]
            if not isinstance(src, int):
                continue
            row = new_all[src]
            modified = False
            if change_group and row[group_col] != group_name:
                row[group_col] = group_name
                modified = True
            if change_enable and row[enable_col] != enable_val:
                row[enable_col] = enable_val
                modified = True
            if modified:
                new_all[src] = row
                changed_srcs.append(src)
                changed += 1
        if changed == 0:
            return (0, -1)
        self._all_data = [tuple(r) for r in new_all]
        self._set_dirty(True)
        if change_group:
            # 方案①：拖到分组面板卡顿根因 = 物理重排整张 1.63M 行列表 + compute_filtered_order 全扫。
            # 改为只 splice 显示序列 _order（O(块)），物理顺序延迟到保存时由 _sync_order_to_data() 归并。
            # 先定位目标组头；若当前 _order 不含（筛选态隐藏该组），退回原全量重建保证正确。
            hg = None
            for i, el in enumerate(self._order):
                if isinstance(el, tuple) and el and el[0] == HEADER_MARK and el[1] == group_name:
                    hg = i
                    break
            if hg is None:
                moved_set = set(changed_srcs)
                moved_rows = [self._all_data[si] for si in changed_srcs]
                rest = [r for i, r in enumerate(self._all_data) if i not in moved_set]
                last_pos = -1
                for idx, r in enumerate(rest):
                    if r[group_col] == group_name:
                        last_pos = idx
                if last_pos == -1:
                    # 目标组为空组（数据集中无任何该组成员，含被本操作移动的）：
                    # 原 last_pos 保持 -1 会把行甩到文件最顶端，改为追加到文件末尾（物理位置不影响 Rime 分组）。
                    self._all_data = rest + moved_rows
                    first_data_idx = len(rest)
                else:
                    self._all_data = rest[:last_pos + 1] + moved_rows + rest[last_pos + 1:]
                    first_data_idx = last_pos + 1
                self._rebuild_order_keep_loaded()
                # 必须在重建 _order 之后再算 first_view：此前 _order 仍是旧序列，
                # 直接按物理下标取会错落到分组头行（防御修复①依赖此值迁移选区）。
                first_view = self._view_row_of_data(first_data_idx)
                return (changed, first_view)
            # 移除被移动数据行 → 在新序列中定位目标组块尾 → 插回（保留选中相对次序）
            changed_set = set(changed_srcs)
            block = list(changed_srcs)
            # 行数不变（仅从原位置取出块再插回目标组块尾）：配对的
            # layoutAboutToBeChanged/layoutChanged 通知视图重排持久索引，安全。
            self.layoutAboutToBeChanged.emit()
            new_order = [el for el in self._order
                         if not (isinstance(el, int) and el in changed_set)]
            hg2 = None
            for i, el in enumerate(new_order):
                if isinstance(el, tuple) and el and el[0] == HEADER_MARK and el[1] == group_name:
                    hg2 = i
                    break
            j2 = hg2 + 1
            while j2 < len(new_order) and not (
                    isinstance(new_order[j2], tuple) and new_order[j2]
                    and new_order[j2][0] == HEADER_MARK):
                j2 += 1
            for el in reversed(block):
                new_order.insert(j2, el)
            self._order = new_order
            self._order_dirty = True
            self._drag_dirty = True
            self.layoutChanged.emit()
            return (changed, j2)
        else:
            # 仅改启用：不影响分组归属，刷新单元格即可（统一重建以保持显示一致）
            self._rebuild_order_keep_loaded()
            return (changed, -1)

    # ---- 组内排序顺序调整（按 _all_data 物理顺序，无顺序码列） ----
    # 注：move_rows_in_group / sort_group_by_key / _group_members / _renumber_group /
    # reladder_weights / bake_display_order 等「组内 ↑/↓、组内重排、阶梯重排」方法，
    # 其对应 UI 按钮已删除（见审核再评估），且全工程无调用方，已于 2026-08-22 清理为死代码。

    def _rebuild_order_keep_loaded(self):
        """重建显示顺序（含分组头）但**保留懒加载边界 _loaded**，用于仅顺序重排、
        数据总量与筛选均未变化的场景。避免 _rebuild_order 把 _loaded 砍回 BATCH_INITIAL
        造成已显示/移动的行被卸载成空白「隐身」（Task #64）。

        ⚠️ 关键修复：当新顺序的**数据行数**与原视图行数不同（例如把行拖到一个被当前
        分组筛选隐藏的目标分组，这些行不再匹配筛选而消失；或改分组列后该行被筛掉）时，
        必须改用 beginResetModel/endResetModel 通知视图——裸 layoutChanged.emit() 在行数
        变化时属 Qt 未定义行为，视图缓存的行数/索引与实际不符，后续绘制或访问越界会
        段错误（程序直接退出）。行数不变时仍用配对的 layoutAboutToBeChanged/layoutChanged
        以保留滚动与选区。
        """
        # B2 修复：先归并可能尚未保存的手工排序（_order 延迟归并标志 _order_dirty）。
        # 否则后续操作（改筛选 / 批量改启用 / 拖入隐藏分组）重建 _order 时会静默清掉待保存排序。
        self._sync_order_to_data()
        filters = self.snapshot_filters()
        new_order = compute_filtered_order(self._all_data, filters)
        old_count = self.rowCount()
        new_count = sum(1 for e in new_order if isinstance(e, int))
        prev_loaded = self._loaded
        if new_count != old_count:
            # 行数变化 → 必须整表重置（beginResetModel/endResetModel），恢复懒加载边界避免「隐身」。
            self.beginResetModel()
            self._order = new_order
            self._loaded = 0
            self.endResetModel()
            if self.canFetchMore(QModelIndex()):
                self.fetchMore(QModelIndex())
            target = min(prev_loaded, len(self._order))
            while self._loaded < target and self.canFetchMore(QModelIndex()):
                self.fetchMore(QModelIndex())
        else:
            self.layoutAboutToBeChanged.emit()
            self._order = new_order
            self.layoutChanged.emit()

    def _sync_order_to_data(self):
        """方案①：把显示序列 _order 固化回 _all_data 物理顺序（拖拽只改 _order，物理顺序延迟归并）。

        无筛选时：_order 覆盖全部数据行，直接整体重排 _all_data。
        有筛选时：_order 为可见子集（含分组头元组，已忽略），按拖拽后的相对顺序对可见行重排，
        被筛掉的行保持原绝对位置不变（不会丢失），因此拖拽重排在任何筛选态下都能持久化。
        幂等：_order_dirty 为 False 时直接返回。
        """
        if not getattr(self, "_order_dirty", False):
            return
        # 收集当前可见数据行在 _all_data 中的下标（已按拖拽后的显示顺序排列）
        visible = [i for i in self._order if isinstance(i, int)]
        if not visible:
            # 无可见数据行：无可归并内容，直接清除脏标志（仍记录日志便于排查）
            _log.debug("reorder: 无可归并的可见数据行，跳过 _sync_order_to_data")
            self._order_dirty = False
            self._drag_dirty = False
            return
        visible_set = set(visible)
        # 异常态（越界 / 重复）直接放弃归并，避免破坏文件
        # B5 修复：异常分支原先静默清 _order_dirty 返回且无日志，问题被吞掉。
        # 现补 warning，便于定位「拖拽排序改动莫名丢失」类问题。
        if (len(visible) != len(visible_set)
                or any(i < 0 or i >= len(self._all_data) for i in visible_set)):
            _log.warning(
                "reorder: _order 含越界或重复下标（len=%d, distinct=%d, 越界=%s），"
                "放弃本次归并以保护文件",
                len(visible), len(visible_set),
                any(i < 0 or i >= len(self._all_data) for i in visible_set),
            )
            self._order_dirty = False
            self._drag_dirty = False
            return
        # 构造新 _all_data：原可见位置依次填入「拖拽后顺序」的可见行；其余位置填原行
        new_data = list(self._all_data)
        vi = 0
        for pos in range(len(self._all_data)):
            if pos in visible_set:
                new_data[pos] = self._all_data[visible[vi]]
                vi += 1
        self._all_data = new_data
        self._order_dirty = False
        self._drag_dirty = False

    def reorder_view_rows(self, src_view_rows: List[int], target_view_row: int, before: bool = True) -> Tuple[int, List[int]]:
        """把选中的显示行拖到 target_view_row 之前(before=True)/之后，直接重排显示序列 _order。

        方案①（Task #68 后续优化）：拖拽**只 splice 显示序列 _order**，不再物理重排 _all_data
        （原地 splice 整行）、也不再调 compute_filtered_order 全扫（0.239s）。_all_data 物理顺序
        延迟到保存时由 _sync_order_to_data() 按 _order 归并（见 _persist_tsv / _rebuild_order 入口）。
        跨组拖拽时同步把源行的「分组」列改成目标组（O(1) 改字段，不重排物理行）。
        仅改内存顺序（标脏），落盘由调用方在保存时统一写回。
        返回 (实际移动的数据行数, 移动后这些行在显示顺序中的新行号列表)；0 行移动时返回 (0, [])。
        """
        # 1. 收集源显示行（仅数据行 int，跳过分组头）；srcs 即 _order 中的索引
        srcs = []
        for vr in src_view_rows:
            if not (0 <= vr < len(self._order)):
                continue
            if isinstance(self._order[vr], int):
                srcs.append(vr)
        if not srcs:
            return 0, []
        srcs.sort()

        # B3 修复：拖回原位时顺序与分组均无变化，不应标脏。先快照 _order，
        # 拖拽完成后若与快照一致且无分组字段改动，则跳过标脏与布局刷新。
        snapshot = list(self._order)

        # 2. target 信息（删除源块前取；目标为分组头则取其组名，否则取目标行归属组）
        if not (0 <= target_view_row < len(self._order)):
            return 0, []
        tgt_el = self._order[target_view_row]
        tgt_is_header = isinstance(tgt_el, tuple) and tgt_el and tgt_el[0] == HEADER_MARK
        if tgt_is_header:
            target_group = tgt_el[1]
        else:
            di = tgt_el
            if not isinstance(di, int):
                return 0, []
            target_group = self._all_data[di][self.FIELD_COLS["分组"]]

        # 3. 提取源块并从 _order 删除（从大到小删，保持剩余下标稳定）
        # 行数不变：用配对的 layoutAboutToBeChanged/layoutChanged 通知视图重排持久索引，
        # 避免裸 layoutChanged 在行数不变场景下仍可能损坏视图内部状态（Qt 要求配对）。
        block = [self._order[s] for s in srcs]
        self.layoutAboutToBeChanged.emit()
        for s in reversed(srcs):
            del self._order[s]

        # 4. 计算删除后插入点（经典 list 搬移偏移）
        n_removed_before = sum(1 for s in srcs if s < target_view_row)
        tgt_after_del = target_view_row - n_removed_before
        if tgt_is_header:
            if before:
                insert_at = tgt_after_del + 1          # 分组头之后 = 组块首
            else:
                j = tgt_after_del + 1                  # 组块尾：下一个分组头之前
                while j < len(self._order) and not (
                        isinstance(self._order[j], tuple) and self._order[j]
                        and self._order[j][0] == HEADER_MARK):
                    j += 1
                insert_at = j
        else:
            insert_at = tgt_after_del if before else tgt_after_del + 1

        # 5. 跨组：把源行「分组」列改成目标组（O(1) 改字段，不重排物理行）
        group_changed = False
        if target_group:
            group_col = self.FIELD_COLS["分组"]
            for di in block:
                if isinstance(di, int):
                    row = list(self._all_data[di])
                    if row[group_col] != target_group:
                        row[group_col] = target_group
                        self._all_data[di] = tuple(row)
                        group_changed = True

        # 6. 插入块
        for el in reversed(block):
            self._order.insert(insert_at, el)

        # B3 修复：仅当顺序或分组字段真的变化时才标脏（通知已通过上文
        # layoutAboutToBeChanged/layoutChanged 配对发出，始终成对、避免视图状态损坏）。
        if group_changed or (self._order != snapshot):
            self._set_dirty(True)
            self._order_dirty = True
            self._drag_dirty = True
        self.layoutChanged.emit()

        new_view_rows = list(range(insert_at, insert_at + len(block)))
        return len(block), new_view_rows

    # ---- 便于状态栏显示 ----
    @property
    def kind(self) -> str:
        """模型类型标识：tsv 侧固定为 'tsv'（与 RimeDictModel.kind 统一接口）。"""
        return "tsv"

    def loaded_count(self) -> int:
        return self._loaded

    def total_count(self) -> int:
        return len(self._all_data)

    def filtered_count(self) -> int:
        """当前显示的数据行数（不含分组头行）。"""
        return sum(1 for e in self._order if isinstance(e, int))

    def first_data_view_row(self) -> int:
        """返回第一个数据行（非头行）的显示行号；无则 -1。"""
        for vr, e in enumerate(self._order):
            if isinstance(e, int):
                return vr
        return -1

    # ---- 词频交换 / 阶梯重排（Request 1） ----
    def swap_weights(self, view_rows: List[int]) -> None:
        """交换两个选中行的权重（col2）。恰好 2 个数据行时生效；返回是否成功（权重不同才换）。"""
        if not view_rows or len(view_rows) != 2:
            return False
        srcs = []
        for vr in view_rows:
            if not (0 <= vr < len(self._order)):
                return False
            e = self._order[vr]
            if not isinstance(e, int):
                return False
            srcs.append(e)
        a, b = srcs
        wa = self._all_data[a][2]
        wb = self._all_data[b][2]
        if wa == wb:
            return False
        row_a = list(self._all_data[a]); row_a[2] = wb
        row_b = list(self._all_data[b]); row_b[2] = wa
        self._all_data[a] = tuple(row_a)
        self._all_data[b] = tuple(row_b)
        self._set_dirty(True)
        self.dataChanged.emit(self.index(view_rows[0], 2), self.index(view_rows[0], 2),
                               [Qt.DisplayRole, Qt.EditRole])
        self.dataChanged.emit(self.index(view_rows[1], 2), self.index(view_rows[1], 2),
                               [Qt.DisplayRole, Qt.EditRole])
        return True

    def sort_display_by_weight(self, desc: bool = True) -> None:
        """把当前筛选结果显示顺序按权重降序（或升序）排列（仅显示顺序，不重排 _all_data）。
        手动按词频排序后转为平铺视图（无分组头），下次筛选/分组时恢复分组。返回行数。"""
        data_idx = [e for e in self._order if isinstance(e, int)]
        if len(data_idx) < 2:
            return 0

        def keyf(i):
            v = self._all_data[i][2]
            try:
                return int(v)
            except ValueError:
                return 0
        data_idx.sort(key=keyf, reverse=desc)
        self.beginResetModel()
        self._order = data_idx
        self._loaded = len(self._order)
        self.endResetModel()
        if self.canFetchMore(QModelIndex()):
            self.fetchMore(QModelIndex())
        return len(data_idx)

    # ---- 懒加载跳转：供查找定位使用 ----
    def ensure_row_loaded(self, view_row: int) -> None:
        """确保显示顺序中的第 view_row 行已加载到视图（懒加载前提供定位跳转）。

        若 view_row 已在已加载范围内则直接返回；否则循环 fetchMore 直到该行可见或到底。
        """
        if view_row < self._loaded:
            return
        parent = QModelIndex()
        while self._loaded <= view_row and self.canFetchMore(parent):
            self.fetchMore(parent)

    # ---- 查找 / 替换 ----
    def _cell_match(self, needle, cell, regex):
        """单元格是否命中：正则走 re.search(IGNORECASE)，否则子串包含（不区分大小写）。"""
        if regex:
            try:
                return re.search(needle, cell, re.IGNORECASE) is not None
            except re.error:
                return False
        return needle.lower() in cell.lower()

    @staticmethod
    def _replace_in_text(needle, repl, cell):
        """非正则：不区分大小写地替换 cell 中所有 needle 出现（保留原大小写位置）。"""
        if not needle:
            return cell
        lower_cell = cell.lower()
        lower_needle = needle.lower()
        parts = []
        i = 0
        while True:
            idx = lower_cell.find(lower_needle, i)
            if idx == -1:
                break
            parts.append(cell[i:idx])
            parts.append(repl)
            i = idx + len(needle)
        parts.append(cell[i:])
        return "".join(parts)

    def find_next(self, start_view_row: int, needle: str, col: int, regex: bool) -> int:
        """从 start_view_row 向下查找（到底循环回顶部）。

        needle: 查找内容；col: 列索引或 None(全部列)；regex: 是否按正则。
        返回 (view_row, col) 或 None（未找到）。
        """
        n = len(self._order)
        if n == 0:
            return None
        cols = range(len(HEADERS)) if col is None else (col,)
        seq = list(range(start_view_row, n)) + list(range(0, start_view_row))
        for view_row in seq:
            el = self._order[view_row]
            if not isinstance(el, int):
                continue   # 跳过分组头行
            row = self._all_data[el]
            for c in cols:
                if self._cell_match(needle, row[c], regex):
                    return (view_row, c)
        return None

    def replace_cell(self, view_row: int, col: int, needle: str, replacement: str, regex: bool) -> bool:
        """替换 view_row 行 col 列单元格中匹配 needle 的部分；返回是否真改了。"""
        if not (0 <= view_row < len(self._order)):
            return False
        if not (0 <= col < len(HEADERS)):
            return False
        el = self._order[view_row]
        if not isinstance(el, int):
            return False   # 分组头行不可编辑
        src = el
        old = self._all_data[src][col]
        if regex:
            try:
                new = re.sub(needle, replacement, old, flags=re.IGNORECASE)
            except re.error:
                return False
        else:
            new = self._replace_in_text(needle, replacement, old)
        if new == old:
            return False
        row_list = list(self._all_data[src])
        row_list[col] = new
        self._all_data[src] = tuple(row_list)
        self._set_dirty(True)
        idx = self.index(view_row, col)
        self.dataChanged.emit(idx, idx, [Qt.EditRole, Qt.DisplayRole])
        return True

    def replace_all(self, needle: str, replacement: str, col: int, regex: bool) -> int:
        """遍历整张 _all_data（含隐藏/未加载行），对匹配单元格做替换。

        返回发生替换的单元格数量；无任何命中返回 0。
        """
        if not needle:
            return 0
        cols = range(len(HEADERS)) if col is None else (col,)
        count = 0
        new_all = list(self._all_data)
        for si, row in enumerate(self._all_data):
            row_list = list(row)
            changed = False
            for c in cols:
                old = row_list[c]
                if regex:
                    try:
                        new = re.sub(needle, replacement, old, flags=re.IGNORECASE)
                    except re.error:
                        new = old
                else:
                    new = self._replace_in_text(needle, replacement, old)
                if new != old:
                    row_list[c] = new
                    changed = True
                    count += 1
            if changed:
                new_all[si] = tuple(row_list)
        if count == 0:
            return 0
        self._all_data = new_all
        self._set_dirty(True)
        self.beginResetModel()
        self.endResetModel()
        return count

    # ---- 重复词条（P0-2：key=词组+编码） ----
    def recompute_duplicates(self) -> None:
        """重算重复集合（key=词组+编码，即列0+列1），结果存 _dup_srcs（_all_data 下标集合）。

        单次 O(n) 全表扫描；仅在加载完成、或词组/编码列被提交修改、或增删/合并后调用，
        不在单元格渲染路径上（data() 仅做 O(1) 集合成员判断），故 163 万行也不拖慢滚动/筛选。
        """
        groups = self.find_duplicate_groups((0, 1))
        s = set()
        for srcs in groups.values():
            s.update(srcs)
        self._dup_srcs = s
        self._dup_computed = True

    def recompute_multi_code(self) -> None:
        """重算「一词多码」集合：按 词组 分组收集互异编码，distinct>1 的组所有行下标入 _multi_code_srcs。
        单次 O(n) 扫描；加载完成、或 词组/编码 列被提交修改、或增删/合并后调用（镜像 recompute_duplicates）。"""
        code_by_word: Dict[str, set] = {}
        for si, row in enumerate(self._all_data):
            w = (row[0] or "").strip()
            if not w:
                continue
            code_by_word.setdefault(w, set()).add((row[1] or "").strip())
        multi = {w for w, cs in code_by_word.items() if len(cs) > 1}
        self._multi_code_srcs = {si for si, row in enumerate(self._all_data)
                                 if (row[0] or "").strip() in multi}
        self._multi_computed = True

    def set_char_count_filter(self, n: int) -> None:
        """功能1 字数筛选：-1=关；0~4=词组列精确字符数；5=字符数≥5（"多"）。"""
        try:
            self._char_count_filter = int(n)
        except (TypeError, ValueError):
            self._char_count_filter = -1
        self._rebuild_order()

    def set_multi_code_filter(self, on: bool) -> None:
        """功能2 一词多码筛选开关。"""
        if on and not self._multi_computed:
            self.recompute_multi_code()   # 懒计算：首次启用才付 O(n) 扫描
        self._multi_code_filter = bool(on)
        self._rebuild_order()

    def set_show_duplicates(self, on: bool) -> None:
        """开关重复高亮。仅刷新已加载行的背景角色（未加载行在 fetch 时自动按 _dup_srcs 着色），
        不触发整表重建，故不丢失滚动位置、不影响百万行性能。"""
        if on and not self._dup_computed:
            self.recompute_duplicates()   # 懒计算：首次启用才付 O(n) 扫描
        self._show_dup = bool(on)
        last = self.rowCount() - 1
        if last >= 0:
            self.dataChanged.emit(
                self.index(0, 0),
                self.index(last, self.columnCount() - 1),
                [Qt.BackgroundRole],
            )

    def find_duplicate_groups(self, key_cols: Tuple[int, int] = (0, 1)) -> Dict[Tuple[str, str], List[int]]:
        """按 key_cols 分组（默认 key = 词组 + 编码），返回 {key: [src, ...]}。

        仅包含 len > 1 的重复组；src 为 _all_data 原始下标，按出现顺序。
        """
        groups = {}
        for si, row in enumerate(self._all_data):
            key = tuple(row[c] for c in key_cols)
            groups.setdefault(key, []).append(si)
        return {k: v for k, v in groups.items() if len(v) > 1}

    def merge_duplicates(self, groups: Dict[Tuple[str, str], List[int]], strategy: str = "max_freq") -> int:
        """合并重复组：保留每组首次出现行，其余行的词频并入（max/sum）后删除冗余行。

        groups: find_duplicate_groups 的返回值；strategy: "max_freq" | "sum"。
        直接重建 _all_data/_order，返回删除的冗余行数（0 表示无可合并）。
        """
        redundant = set()
        merge_map = {}   # primary_src -> [redundant_src, ...]
        for _key, srcs in groups.items():
            primary = srcs[0]
            for s in srcs[1:]:
                redundant.add(s)
                merge_map.setdefault(primary, []).append(s)
        if not redundant:
            return 0

        # 计算合并后的词频（空值当 0；非数字当 0）
        new_freq = {}
        for primary, others in merge_map.items():
            vals = []
            for s in (primary, *others):
                v = self._all_data[s][2]
                try:
                    vals.append(int(v) if v != "" else 0)
                except ValueError:
                    vals.append(0)
            new_freq[primary] = sum(vals) if strategy == "sum" else max(vals)

        # 重建 _all_data：保留非冗余行，更新 primary 词频
        kept = []
        for si, row in enumerate(self._all_data):
            if si in redundant:
                continue
            row_list = list(row)
            if si in new_freq:
                row_list[2] = str(new_freq[si])
            kept.append(tuple(row_list))

        removed = len(self._all_data) - len(kept)
        self._all_data = kept
        self._set_dirty(True)
        self._rebuild_order()   # 合并后重建顺序（含分组头）
        self.recompute_duplicates()   # 合并后重复集合变化，重算
        self.recompute_multi_code()   # 合并后「一词多码」集合变化，重算
        return removed


def _row_incomplete(row_list) -> bool:
    """五要素（词组/编码/权重/分组/启用，即列 0~4）任一为空或纯空白即视为不全。"""
    for c in range(5):
        if not (row_list[c] or "").strip():
            return True
    return False


def compute_filtered_order(data: List[Tuple], filters: dict) -> list:
    """纯函数：按 filters 预算新显示顺序（含 ("H",组名) 分组头）。

    与 DictModel._rebuild_order 原扫描逻辑逐字等价，抽为独立函数以便：
    - 主线程程序内同步重建（增删/合并/移动等）直接复用；
    - 大词库筛选时由后台 FilterThread 调用，主线程仅做 commit_order 刷新，避免全表扫描卡顿。
    filters 来自 DictModel.snapshot_filters()，字段：text/field/group/incomplete/
    char_count/multi_code/multi_code_srcs/dup_only/grouped。
    """
    text = (filters.get("text") or "").strip().lower()
    field = filters.get("field") or {}
    group = (filters.get("group") or "").strip()
    n = len(data)
    if not text and not field and not group:
        data_order = list(range(n))
    else:
        data_order = []
        for i in range(n):
            r = data[i]
            if text and not any(text in r[c].lower() for c in FILTER_COLS):
                continue
            ok = True
            for col, val in field.items():
                if val and val.lower() not in r[col].lower():
                    ok = False
                    break
            if not ok:
                continue
            if group:
                rg = r[DictModel.FIELD_COLS["分组"]]
                if group == "（无分组）":
                    if rg:  # 非空分组 → 不匹配「无分组」
                        continue
                elif rg != group:
                    continue
            data_order.append(i)
    # 五要素不全筛选（tsv 专属）
    if filters.get("incomplete"):
        data_order = [i for i in data_order if _row_incomplete(data[i])]
    # 字数筛选（功能1）：-1=关；5="多"（≥5）
    char_count = filters.get("char_count", -1)
    if char_count >= 0:
        if char_count == 5:
            data_order = [i for i in data_order
                          if len((data[i][0] or "").strip()) >= 5]
        else:
            data_order = [i for i in data_order
                          if len((data[i][0] or "").strip()) == char_count]
    # 一词多码筛选（功能2）：在当前作用域（已含文本/字数/分组筛选）内，
    # 按 词组 聚编码，找出「≥2 个互异编码」的词组，仅保留这些词组的全部行；
    # 再按 (词组, 编码) 升序聚拢——同词组相邻、内部按编码对比（不区分分组）。
    # 判定跟随当前选区：选某分组时 data_order 已被该组收窄，故只在该组内判定多码。
    if filters.get("multi_code"):
        codes_by_word = {}
        for i in data_order:
            w = (data[i][0] or "").strip()
            if not w:
                continue
            codes_by_word.setdefault(w, set()).add((data[i][1] or "").strip())
        multi_words = {w for w, cs in codes_by_word.items() if len(cs) > 1}
        data_order = [i for i in data_order
                      if (data[i][0] or "").strip() in multi_words]
        data_order.sort(key=lambda i: ((data[i][0] or "").strip(),
                                       (data[i][1] or "").strip()))
    # 重复项筛选：在当前作用域（已含文本/字数/分组筛选）内，
    # 按 (词组, 编码) 完全相同统计出现次数，仅保留出现 ≥2 次的重复行；
    # 再按 (词组, 编码) 升序聚拢——完全相同的条目相邻排列（不区分分组）。
    if filters.get("dup_only"):
        key_count = {}
        for i in data_order:
            k = ((data[i][0] or "").strip(), (data[i][1] or "").strip())
            key_count[k] = key_count.get(k, 0) + 1
        data_order = [i for i in data_order
                      if key_count[((data[i][0] or "").strip(), (data[i][1] or "").strip())] > 1]
        data_order.sort(key=lambda i: ((data[i][0] or "").strip(),
                                       (data[i][1] or "").strip()))
    # 分组头：仅「全部」视图（未选特定分组）且启用分组视图、且非一词多码/重复项筛选模式时插入
    # （一词多码/重复项筛选模式强制不插分组头，实现「不区分分组、相同条目跨组相邻」）
    if filters.get("grouped") and not group and not filters.get("multi_code") and not filters.get("dup_only"):
        grp_col = DictModel.FIELD_COLS["分组"]
        new_order = []
        last_g = None
        for i in data_order:
            g = data[i][grp_col] or "（无分组）"
            if g != last_g:
                new_order.append((HEADER_MARK, g))
                last_g = g
            new_order.append(i)
    else:
        new_order = data_order
    return new_order


def compute_load_extras(data: List[Tuple]) -> dict:
    """加载完成、交付主线程前，在后台线程用单次扫描预算后续不变派生结果。

    合并原来主线程上的 4 次全表扫描：_rebuild_order 插分组头 / recompute_duplicates /
    recompute_multi_code / _populate_groups 的 distinct_values，统一为一次 O(n) 扫描，
    使 160 万行词库加载时主线程不再冻结。返回 dict，供 DictModel.set_all_data 直接取用。

    extras 内容：
      - dup_srcs: 重复词条下标集合（key=词组+编码，与 find_duplicate_groups((0,1)) 一致）
      - multi_srcs: 一词多码下标集合（词组→互异编码数≥2 的组所有行）
      - distinct_groups: 分组列去重后的排序列表（与 distinct_values(分组列) 一致）
      - initial_order: 无筛选、分组视图下的初始显示顺序（含 ("H",组名) 分组头行）
    """
    grp_col = DictModel.FIELD_COLS["分组"]
    dup_groups = {}
    code_by_word = {}
    distinct_groups = set()
    initial_order = []
    last_g = None
    for i, row in enumerate(data):
        # 分组列去重 + 初始分组头插入（与 _rebuild_order 无筛选分支一致）
        g = row[grp_col] or ""
        disp_g = g or "（无分组）"
        distinct_groups.add(disp_g)
        if disp_g != last_g:
            initial_order.append((HEADER_MARK, disp_g))
            last_g = disp_g
        initial_order.append(i)
        # 重复词条（key = 词组 + 编码，与 find_duplicate_groups((0,1)) 一致）
        dkey = (row[0], row[1])
        dup_groups.setdefault(dkey, []).append(i)
        # 一词多码（词组 → 互异编码集合，与 recompute_multi_code 一致）
        w = (row[0] or "").strip()
        if w:
            code_by_word.setdefault(w, set()).add((row[1] or "").strip())
    dup_srcs = set()
    for srcs in dup_groups.values():
        if len(srcs) > 1:
            dup_srcs.update(srcs)
    multi = {w for w, cs in code_by_word.items() if len(cs) > 1}
    multi_srcs = {i for i, row in enumerate(data) if (row[0] or "").strip() in multi}
    return {
        "dup_srcs": dup_srcs,
        "multi_srcs": multi_srcs,
        "distinct_groups": sorted(distinct_groups),
        "initial_order": initial_order,
    }


def compute_load_minimal(data: List[Tuple]) -> dict:
    """加载预计算（轻量版，仅含加载必需项）：初始显示顺序 initial_order + 分组去重列表 distinct_groups。

    刻意不包含 dup_srcs / multi_srcs——这俩是默认关闭的功能（重复高亮 / 一词多码筛选），
    推迟到用户真正启用时再算（见 DictModel.set_show_duplicates / set_multi_code_filter /
    set_filter_state 的懒触发），避免 160 万行词库加载时白白付 O(n) 扫描代价
    （实测 compute_load_extras 的 dup/multi 部分占加载耗时约 84%）。

    与 compute_load_extras 的区别仅在于跳过「重复组 / 一词多码」两张字典的构建与二次全表扫描；
    initial_order / distinct_groups 的生成逻辑（分组头插入、分组列去重）与之一致。
    """
    grp_col = DictModel.FIELD_COLS["分组"]
    distinct_groups = set()
    initial_order = []
    last_g = None
    for i, row in enumerate(data):
        g = row[grp_col] or ""
        disp_g = g or "（无分组）"
        distinct_groups.add(disp_g)
        if disp_g != last_g:
            initial_order.append((HEADER_MARK, disp_g))
            last_g = disp_g
        initial_order.append(i)
    return {
        "distinct_groups": sorted(distinct_groups),
        "initial_order": initial_order,
    }
