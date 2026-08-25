# -*- coding: utf-8 -*-
"""TSV 加载/写回 BOM 一致性回归（修复 M2：加载不再把 UTF-8 BOM 当首格内容）。

- 带 BOM 的 tsv 加载后，首格不应含 '\ufeff'；
- write_tsv 写回不应产生 BOM；
- 重新加载写回文件，首格仍干净（避免「批量权重写入 utf-8-sig 后，下次打开被污染」）。
"""
import pathlib
import sys

RIMETOOL = str(pathlib.Path(__file__).resolve().parents[1])
if RIMETOOL not in sys.path:
    sys.path.insert(0, RIMETOOL)

from core.io_tsv import LoadThread, write_tsv  # noqa: E402


def test_read_lines_strips_bom():
    import tempfile, os
    f = tempfile.NamedTemporaryFile(suffix=".tsv", delete=False)
    f.write(b"\xef\xbb\xbfA\tb\ta\nB\tc\td\n")
    f.close()
    try:
        lines = list(LoadThread._read_lines(f.name))
        assert not lines[0].startswith("\ufeff"), lines[0]
        # _read_lines 仅解码（不剥换行，换行在 run() 中处理）；关键是首格无 BOM
        assert lines[0].lstrip("\ufeff").rstrip("\n") == "A\tb\ta", lines[0]
    finally:
        os.unlink(f.name)


def test_tsv_bom_roundtrip(app, tmp_path):
    p = tmp_path / "bom.tsv"
    # 带 BOM 的 5 列 tsv
    p.write_bytes("A\tb\ta\tA 组\tA\nB\tc\td\tB 组\tA\n".encode("utf-8-sig"))

    captured = {}
    th = LoadThread(str(p))
    th.loaded.connect(
        lambda data, total, extras: captured.update(data=data, total=total))
    th.run()  # 测试直接在主线程跑 run()，emit 同步送达
    rows = captured["data"]
    assert rows[0][0] == "A", rows[0]          # 首格无 BOM
    assert len(rows) == 2

    # 写回 + 重新加载，确认不引入/残留 BOM
    out = tmp_path / "out.tsv"
    write_tsv(str(out), rows)
    with open(str(out), "rb") as fb:
        head = fb.read(4)
    assert head[:3] != b"\xef\xbb\xbf", "write_tsv 不应写 BOM"

    captured2 = {}
    th2 = LoadThread(str(out))
    th2.loaded.connect(
        lambda data, total, extras: captured2.update(data=data, total=total))
    th2.run()
    assert captured2["data"][0][0] == "A", captured2["data"][0]
