# -*- coding: utf-8 -*-
"""P1 其余项修复回归测试（2026-08-23）。

锁定审查报告 P1-②/P1-③/P1-④ 三处修复：
- P1-② write_tsv 原子写：先写同目录临时文件 + os.replace 原子替换；中途（os.replace）失败
  时原文件不被半截覆盖，且临时文件被清理不残留。
- P1-③ RimeDictModel.save 写回前经 is_safe_target 校验，拒绝危险目录、且正常安全路径仍落盘。
- P1-④ BOM 一致性：weight_replacer 的 chaos / TSV 两条写回路径不再写 utf-8-sig(BOM)，
  与 write_tsv / rime_export / voice_gap / rime_dict_model.save 一致（均纯 utf-8，无 BOM）。
"""
import os
import sys
import pathlib

RIMETOOL = str(pathlib.Path(__file__).resolve().parents[1])
if RIMETOOL not in sys.path:
    sys.path.insert(0, RIMETOOL)

import core.config as cfg
import core.io_tsv as io_tsv
import core.rime_export as rime_export
import core.weight_replacer as weight_replacer
from core.rime_dict_model import RimeDictModel


# ---------------- P1-② write_tsv 原子写 ----------------
def test_write_tsv_atomic_preserves_original_on_replace_failure(tmp_path, monkeypatch):
    p = tmp_path / "a.tsv"
    p.write_text("orig\t1\t1\tA 词库\tA\n", encoding="utf-8")
    calls = []
    real_replace = io_tsv.os.replace

    def failing_replace(src, dst):
        calls.append((src, dst))
        raise OSError("simulated atomic failure")

    monkeypatch.setattr(io_tsv.os, "replace", failing_replace)
    try:
        ok = io_tsv.write_tsv(str(p), [["词", "c", "1", "A 词库", "A"]])
    finally:
        monkeypatch.setattr(io_tsv.os, "replace", real_replace)
    assert ok is False
    # 原子替换这步失败：原文件内容保持不变（未被半截覆盖）
    assert p.read_text(encoding="utf-8") == "orig\t1\t1\tA 词库\tA\n"
    # 临时文件已清理，不残留半截文件
    assert list(tmp_path.glob(".rimetool_*")) == []
    assert calls  # 确实走到了 os.replace


def test_write_tsv_happy(tmp_path):
    p = tmp_path / "b.tsv"
    rows = [["词一", "a", "1", "A 词库", "A"], ["词二", "b", "2", "B 人名", "A"]]
    assert io_tsv.write_tsv(str(p), rows) is True
    got = p.read_text(encoding="utf-8").splitlines()
    assert got == ["词一\ta\t1\tA 词库\tA", "词二\tb\t2\tB 人名\tA"]


def test_write_tsv_rejects_unsafe(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "is_safe_target", lambda p: False)
    p = tmp_path / "x.tsv"
    assert io_tsv.write_tsv(str(p), [["a", "b", "1", "A 词库", "A"]]) is False
    assert not p.exists()


# ---------------- P1-③ RimeDictModel.save 安全校验 ----------------
def test_rime_save_rejects_unsafe(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "is_safe_target", lambda p: False)
    m = RimeDictModel()
    m._header_lines = ["---", "name: wubi", "..."]
    m._all_data = [("词", "code", "1"), ("词2", "code2", "")]
    m._path = str(tmp_path / "src.yaml")
    out = tmp_path / "out.yaml"
    assert m.save(str(out)) is False
    assert not out.exists()


def test_rime_save_writes_file_when_safe(tmp_path):
    m = RimeDictModel()
    m._header_lines = ["---", "name: wubi", "..."]
    m._all_data = [("词", "code", "1"), ("词2", "code2", "")]
    m._path = str(tmp_path / "src.yaml")
    out = tmp_path / "out.yaml"
    assert m.save(str(out)) is True
    content = out.read_text(encoding="utf-8")
    assert "..." in content
    assert "词\tcode\t1" in content


# ---------------- P1-④ BOM 一致性 ----------------
def test_weight_replacer_chaos_no_bom(tmp_path):
    chaos = tmp_path / "wubi.chaos.dict.yaml"
    chaos.write_text("---\nname: wubi\n...\n词\tcode\n词2\tcode2\n", encoding="utf-8")
    removed = weight_replacer._rewrite_chaos_drop(str(chaos), {("词", "code")})
    assert removed == 1
    raw = chaos.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf"), "chaos 写回应无 BOM"


def test_weight_replacer_tsv_no_bom(tmp_path, monkeypatch):
    # 把依赖的 A-F 映射 / 参考词典缩减为最小临时文件，聚焦 TSV 写回路径
    monkeypatch.setattr(rime_export, "GROUP_TARGETS", {"A": ("af.txt", "af")})
    monkeypatch.setattr(rime_export, "REFERENCE_DICTS", ["chaos.txt"])
    monkeypatch.setattr(weight_replacer, "GROUP_TARGETS", {"A": ("af.txt", "af")})
    monkeypatch.setattr(weight_replacer, "REFERENCE_DICTS", ["chaos.txt"])
    # 屏蔽真实快照，避免污染项目 Logs/
    monkeypatch.setattr("core.backup.open_snapshot", lambda *a, **k: "")

    cfg = tmp_path / "cfg"
    cfg.mkdir()
    (cfg / "af.txt").write_text("---\nname: af\n...\n词一\ta\t5\n", encoding="utf-8")
    (cfg / "chaos.txt").write_text("---\nname: chaos\n...\n词二\tb\t9\n", encoding="utf-8")
    tsv = tmp_path / "Alamo.tsv"
    tsv.write_text("词一\ta\t1\tA 词库\tA\n词二\tb\t2\tB 人名\tA\n", encoding="utf-8")

    res = weight_replacer.replace_weights(str(tsv), rime_config_dir=str(cfg))
    assert res["ok"] is True
    raw = tsv.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf"), "批量权重写回 TSV 不应带 BOM"


# ---------------- P1-⑤ 分组切换异步化（RimeDictModel 后台筛选） ----------------
def _rime_model_with_groups():
    """构造一个带 A/B 两分组的 RimeDictModel（绕过文件加载，直接填数据）。"""
    m = RimeDictModel()
    m._header_lines = ["---", "name: wubi", "..."]
    m._all_data = [
        ("苹果", "pg", "1"),
        ("香蕉", "xj", "2"),
        ("苹果汁", "pgz", "3"),
        ("猫", "m", "4"),
    ]
    m._groups = ["A 词库", "B 词库"]
    m._row_group = ["A 词库", "B 词库", "A 词库", "B 词库"]
    m._order = list(range(len(m._all_data)))
    return m


def test_rime_set_filter_state_and_compute_order(app):
    m = _rime_model_with_groups()
    # 仅分组筛选
    m.set_filter_state(group="A 词库", field={})
    assert m.snapshot_filters()["group"] == "A 词库"
    assert m.compute_order(m.snapshot_filters()) == [0, 2]   # A 组两行
    # 分组 + 字段叠加：A 组且词组含「苹果」
    m.set_filter_state(group="A 词库", field={"词组": "苹果"})
    assert m.compute_order(m.snapshot_filters()) == [0, 2]
    # 切到 B 组 + 词组含「猫」
    m.set_filter_state(group="B 词库", field={"词组": "猫"})
    assert m.compute_order(m.snapshot_filters()) == [3]


def test_rime_group_thread_emits_filtered_order(app):
    from PyQt5.QtCore import QEventLoop

    m = _rime_model_with_groups()
    m.set_filter_state(group="A 词库", field={})
    # P1-⑤ 修复后 RimeGroupThread 接收「启动前拷贝的快照」，不再持有 model 引用
    th = io_tsv.RimeGroupThread(list(m._all_data), list(m._row_group), m.snapshot_filters())
    received = []
    th.finished_order.connect(lambda o: received.append(o))
    loop = QEventLoop()
    th.finished.connect(loop.quit)
    th.start()
    loop.exec_()
    assert received and received[0] == [0, 2]   # 后台线程预算出正确顺序
    th.deleteLater()


def test_rime_commit_order_refreshes(app):
    m = _rime_model_with_groups()
    m.commit_order([0, 2])
    assert m._order == [0, 2]


def test_rime_apply_field_filter_refactor_consistent(app):
    """P1-⑤ 重构 apply_field_filter 后，旧同步入口行为不变，且与 compute_order 结果一致。"""
    m = _rime_model_with_groups()
    m.set_group_filter("A 词库")
    assert m._order == [0, 2]                      # 旧同步入口仍正确
    m.set_group_filter("")                          # 全部
    assert m._order == [0, 1, 2, 3]
    # 与异步 compute_order 同源逻辑，结果一致
    m.set_filter_state(group="B 词库", field={})
    assert m.compute_order(m.snapshot_filters()) == [1, 3]
