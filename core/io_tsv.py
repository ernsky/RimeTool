# -*- coding: utf-8 -*-
"""TSV 读写与后台加载线程（IO 层）。

把文件读取放到 QThread 子线程，解析完成后通过信号把全量数据交给主线程，
避免 160 万行文件阻塞 UI。
"""
import logging
import os
import tempfile
from typing import List

from PyQt5.QtCore import QThread, pyqtSignal

from core.dict_model import compute_load_minimal, compute_filtered_order

_log = logging.getLogger(__name__)


def write_tsv(path: str, rows: List[List[str]]) -> bool:
    """把行列表（每个元素为 5 字段的元组）按 TSV / UTF-8 写入文件。返回是否成功。

    写回前先经 is_safe_target 校验，拒绝写入危险系统目录（如 C:\\Windows\\System32），
    与 write_rime_file / weight_replacer 等写回点统一安全护栏（安全审查 F1）。
    采用「先写同目录临时文件 + os.replace 原子替换」：160 万行写回中途若崩溃，原文件
    不受影响，避免就地覆盖写导致文件半截损坏（P1-② 修复）。
    """
    from core.config import is_safe_target
    if not is_safe_target(path):
        _log.error("拒绝写回不安全路径：%s", path)
        return False
    dir_name = os.path.dirname(os.path.abspath(path)) or "."
    tmpf = tempfile.NamedTemporaryFile(
        dir=dir_name, prefix=".rimetool_", suffix=".tsv.tmp",
        mode="w", encoding="utf-8", newline="", delete=False)
    tmp_path = tmpf.name
    try:
        with tmpf:
            for row in rows:
                tmpf.write("\t".join(row))
                tmpf.write("\n")
        os.replace(tmp_path, path)  # 原子替换：同卷内要么全写、要么不动原文件
        return True
    except OSError as exc:
        _log.error("保存失败：%s", exc)
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass
        return False


class LoadThread(QThread):
    """在子线程中读取并解析 TSV，解析完成后通过信号把「全部数据」交给主线程。"""

    loaded = pyqtSignal(list, int, dict)    # (全部数据列表, 总行数, 预计算结果 extras)
    progress = pyqtSignal(str)        # 状态栏文本
    error = pyqtSignal(str)           # 错误信息

    def __init__(self, path: str) -> None:
        super().__init__()
        self._path = path

    @staticmethod
    def _read_lines(path: str) -> List[str]:
        """逐行读取并按 utf-8 解码，单行失败时回退 gbk，返回去掉换行符的字符串生成器。"""
        with open(path, "rb") as fb:
            for raw in fb:
                try:
                    line = raw.decode("utf-8-sig")
                except UnicodeDecodeError:
                    line = raw.decode("gbk", errors="replace")
                yield line

    def run(self) -> None:
        try:
            self.progress.emit("正在加载词库...")
            data = []
            count = 0
            overflow = 0   # M3：超过 5 列（schema 容差外）的行数，用于告警而非静默丢列
            for line in self._read_lines(self._path):
                line = line.rstrip("\n").rstrip("\r")
                if not line:
                    continue
                parts = line.split("\t")
                if len(parts) > 5:
                    overflow += 1
                row = tuple(parts[i] if i < len(parts) else "" for i in range(5))
                data.append(row)
                count += 1
                if count % 200000 == 0:
                    self.progress.emit(f"正在加载... 已读取 {count:,} 行")
            if overflow:
                # M3：超列系数据丢失风险点——5 列 schema 下第 6+ 列会被写回时丢弃；
                # 加载即告警，避免用户「莫名其妙丢了列」而无从排查。
                self.progress.emit(
                    f"注意：{overflow:,} 行含有超过 5 个字段，多余字段已忽略（仅保留前 5 列）")
            # 加载优化（懒计算）：只做加载必需的轻量预计算（初始顺序 + 分组去重），
            # 跳过默认关闭的「重复高亮 / 一词多码」全表扫描；那俩推迟到用户首次启用时再算
            # （见 core.dict_model 的 set_show_duplicates / set_multi_code_filter / set_filter_state）。
            # 失败则回退 None，由主线程 set_all_data 走完整重算（含 dup/multi），不丢数据。
            try:
                extras = compute_load_minimal(data)
            except Exception:  # noqa: BLE001 - 预计算失败可安全回退
                _log.warning("加载轻量预计算失败，回退主线程重算", exc_info=True)
                extras = None
            if extras is not None:
                extras["overflow_lines"] = overflow   # M3：把超列行数带给主线程，供状态栏持久提示
            self.loaded.emit(data, len(data), extras)
        except Exception as exc:  # noqa: BLE001 - 统一上报给主线程
            _log.error("读取词库失败：%s", exc, exc_info=True)
            self.error.emit(f"读取失败：{exc}")


class FilterThread(QThread):
    """在子线程按筛选条件预算新显示顺序，避免大词库筛选时主线程全表扫描卡顿。

    纯扫描逻辑复用 core.dict_model.compute_filtered_order（与 DictModel._rebuild_order
    同源），主线程拿到新顺序后仅做 commit_order 刷新。latest 结果由调用方用代号(token)丢弃过期值。
    """

    finished_order = pyqtSignal(list)    # 新显示顺序（含分组头）
    error = pyqtSignal(str)              # 错误信息

    def __init__(self, data: List[tuple], filters: dict) -> None:
        super().__init__()
        self._data = data
        self._filters = filters

    def run(self) -> None:
        try:
            order = compute_filtered_order(self._data, self._filters)
            self.finished_order.emit(order)
        except Exception as exc:  # noqa: BLE001 - 统一上报给主线程
            _log.error("筛选后台计算失败：%s", exc, exc_info=True)
            self.error.emit(f"筛选失败：{exc}")


class RimeGroupThread(QThread):
    """在子线程按筛选条件预算 RimeDictModel 的新显示顺序，避免中大型 Rime 词典点分组时主线程
    全表扫描卡顿（P1-⑤）。

    与 FilterThread 思路一致，但计算逻辑走模块级 compute_rime_order（3 列 dict.yaml 的
    _row_group 分组 + 字段子串判定），主线程拿到新顺序后仅做 commit_order 刷新。
    latest 结果由调用方用代号(token)丢弃过期值。Thread 一次性 CPU 任务，finished→deleteLater 自愈。

    接收 _all_data/_row_group 的**快照副本**（由调用方在启动线程前 list() 拷贝），不再持有 model
    引用——杜绝子线程遍历与主线程 append/重排同一 list 对象引发 C 层迭代器失效段错误（见 P1-⑤
    追加崩溃修复）。
    """

    finished_order = pyqtSignal(list)    # 新显示顺序（数据行下标）
    error = pyqtSignal(str)              # 错误信息

    def __init__(self, data, row_group, filters: dict) -> None:
        super().__init__()
        self._data = data
        self._row_group = row_group
        self._filters = filters

    def run(self) -> None:
        try:
            from core.rime_dict_model import compute_rime_order
            order = compute_rime_order(self._data, self._row_group, self._filters)
            self.finished_order.emit(order)
        except Exception as exc:  # noqa: BLE001 - 统一上报给主线程
            _log.error("Rime 分组后台计算失败：%s", exc, exc_info=True)
            self.error.emit(f"分组筛选失败：{exc}")


class SortThread(QThread):
    """在子线程对显示数据行按指定列排序，避免大词库点击表头/恢复排序时主线程全表排序卡顿（白屏）。

    纯排序逻辑复用 DictModel.sort 的 key 规则（数值列按 int 优先）；主线程拿到排序后的
    数据行下标列表后仅做模型通知刷新。过期结果由调用方用代号(token)丢弃（连续点击表头时
    只采用最后一次）。Thread 自身为一次性 CPU 任务（排序完即 emit 并退出），finished→deleteLater 自愈。
    """

    finished_order = pyqtSignal(list)    # 排序后的数据行下标列表（不含分组头）
    error = pyqtSignal(str)              # 错误信息

    def __init__(self, data: List[tuple], data_idx: List[int], column: int, reverse: bool) -> None:
        super().__init__()
        self._data = data
        self._data_idx = data_idx
        self._column = column
        self._reverse = reverse

    def run(self) -> None:
        try:
            from core.config import NUMERIC_COLS
            col = self._column

            def key(i):
                v = self._data[i][col]
                if col in NUMERIC_COLS:
                    try:
                        return (0, int(v))
                    except ValueError:
                        return (1, v)
                return (0, v)
            idx = list(self._data_idx)
            idx.sort(key=key, reverse=self._reverse)
            self.finished_order.emit(idx)
        except Exception as exc:  # noqa: BLE001 - 统一上报给主线程
            _log.error("排序后台计算失败：%s", exc, exc_info=True)
            self.error.emit(f"排序失败：{exc}")
