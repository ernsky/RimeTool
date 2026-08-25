# -*- coding: utf-8 -*-
"""追加词组到 TSV 流程回归测试（覆盖「追加后程序直接退出」修复）。

重点验证：
- WubiEncodeDialog._on_append 在真实 DictModel + 真实落盘下不会抛异常、行数 +1、TSV 含新词条；
- 重复词条被跳过（行数不变）；
- 写回失败（write_tsv 返回 False）时走 critical 提示而非静默退出；
- 异常被捕获并落日志，绝不因未捕获异常导致进程退出。
"""
import os
import sys
import pathlib
import tempfile

RIMETOOL = str(pathlib.Path(__file__).resolve().parents[1])
if RIMETOOL not in sys.path:
    sys.path.insert(0, RIMETOOL)

import pytest
from PyQt5.QtWidgets import QMessageBox

from core.dict_model import DictModel
from ui.wubi_encode_dialog import WubiEncodeDialog
from core.wubi_encode import RULE_FREE


@pytest.fixture
def model_with_rows():
    m = DictModel()
    data = [
        ("苹果", "ap", "1", "A 词库", "A"),
        ("香蕉", "bj", "2", "A 词库", "A"),
        ("微信", "vl", "3", "B 词库", "A"),
    ]
    m.set_all_data(data, len(data), None)
    return m


def _make_dialog(m, tsv_path, phrase, free_code="zzzz"):
    """用自由编码规则构造对话框并填好词组/编码，保证 generate_for_phrase 稳定出码。"""
    dlg = WubiEncodeDialog(None, m, tsv_path=tsv_path)
    idx = dlg.comboMethod.findData(RULE_FREE)
    dlg.comboMethod.setCurrentIndex(idx if idx >= 0 else 0)
    dlg.editFree.setText(free_code)
    dlg.editPhrases.setPlainText(phrase)
    return dlg


def test_append_new_phrase_writes_tsv_and_increases_rows(app, model_with_rows, monkeypatch):
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: None)
    m = model_with_rows
    tmp = tempfile.NamedTemporaryFile(suffix=".tsv", delete=False)
    tmp.close()
    tsv_path = tmp.name
    try:
        dlg = _make_dialog(m, tsv_path, "测试追加词组xy")
        dlg._on_append()
        # 行数 +1
        assert len(m._all_data) == 4
        # 落盘文件包含新词组
        with open(tsv_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "测试追加词组xy" in content
        # mark_clean 已被调用
        assert m.is_dirty() is False
    finally:
        os.remove(tsv_path)


def test_append_duplicate_is_skipped(app, model_with_rows, monkeypatch):
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: None)
    m = model_with_rows
    tmp = tempfile.NamedTemporaryFile(suffix=".tsv", delete=False)
    tmp.close()
    tsv_path = tmp.name
    try:
        # 用自由编码并填与已存在行完全一致的 (词组, 编码) = (苹果, ap)，应被判重跳过
        dlg = _make_dialog(m, tsv_path, "苹果", free_code="ap")
        dlg._on_append()
        assert len(m._all_data) == 3  # 未新增
    finally:
        os.remove(tsv_path)


def test_append_write_failure_shows_critical_not_crash(app, model_with_rows, monkeypatch):
    """write_tsv 返回 False（如路径被占用）时，应弹 critical 并 return，而非抛未捕获异常退出。"""
    criticals = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "critical",
                        lambda *a, **k: criticals.append(a))
    m = model_with_rows
    # 指向一个不存在目录下的文件，使 os.replace 失败 → write_tsv 返回 False
    bad_path = os.path.join(tempfile.gettempdir(), "nonexistent_dir_xyz", "x.tsv")
    dlg = _make_dialog(m, bad_path, "测试追加词组xy")
    dlg._on_append()  # 不应抛出
    assert criticals, "写回失败应弹 critical 提示"
    assert len(m._all_data) == 4  # 内存已追加（写回失败不影响内存新增）


def test_append_exception_is_caught_and_logged(app, model_with_rows, monkeypatch):
    """_sync_order_to_data / write_tsv 抛非 OSError 时，必须被捕获并弹窗，绝不静默退出。"""
    criticals = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "critical",
                        lambda *a, **k: criticals.append(a))
    # 让 write_tsv 抛一个非 OSError（写回段意外异常），模拟 pythonw 下会「静默退出」的场景
    def boom_write(*a, **k):
        raise RuntimeError("模拟意外异常")
    monkeypatch.setattr("ui.wubi_encode_dialog.write_tsv", boom_write)
    m = model_with_rows
    tmp = tempfile.NamedTemporaryFile(suffix=".tsv", delete=False)
    tmp.close()
    tsv_path = tmp.name
    try:
        dlg = _make_dialog(m, tsv_path, "测试追加词组xy")
        dlg._on_append()  # 必须被捕获，绝不该逸出
        assert criticals, "意外异常应被捕获并弹 critical"
    finally:
        os.remove(tsv_path)
