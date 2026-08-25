# -*- coding: utf-8 -*-
"""DictModel 关键纯逻辑单测：懒加载、增/删、去重、合并、移动到分组。

依赖 PyQt5（offscreen），由 conftest.py 提供 QApplication。
"""
import os
import sys
import pathlib

RIMETOOL = str(pathlib.Path(__file__).resolve().parents[1])
if RIMETOOL not in sys.path:
    sys.path.insert(0, RIMETOOL)

from PyQt5.QtCore import Qt  # noqa: E402

from core.config import BATCH_INITIAL  # noqa: E402
from core.dict_model import DictModel  # noqa: E402


def _sample(n=10):
    return [("词组%d" % i, "code%d" % i, str(100 + i), "A 词库", "A") for i in range(n)]


def test_set_all_data_lazy(app):
    m = DictModel()
    m.set_all_data(_sample(5000), 5000)
    # 懒加载：仅加载首批，而非全表；rowCount 受 _loaded 限制
    assert m._loaded == BATCH_INITIAL
    assert m._loaded < len(m._order)
    assert m.rowCount() == BATCH_INITIAL


def test_add_and_delete(app):
    m = DictModel()
    m.set_all_data(_sample(5), 5)
    before = len(m._all_data)
    src = m.add_row()
    assert len(m._all_data) == before + 1
    vr = m._view_row_of_data(src)
    assert vr >= 0
    # 新行可经字段接口写入
    assert m.set_field(vr, "词组", "新词") is True
    assert m.get_field(vr, "词组") == "新词"
    # 删除该行
    assert m.delete_rows_by_view([vr]) == 1
    assert len(m._all_data) == before


def test_recompute_duplicates(app):
    rows = [
        ("重复词", "aa", "1", "A 词库", "A"),
        ("重复词", "aa", "2", "A 词库", "A"),
        ("唯一", "bb", "3", "A 词库", "A"),
    ]
    m = DictModel()
    m.set_all_data(rows, len(rows))
    groups = m.find_duplicate_groups((0, 1))
    assert ("重复词", "aa") in groups
    assert len(groups[("重复词", "aa")]) == 2
    m.recompute_duplicates()
    assert set(m._dup_srcs) == {0, 1}


def test_char_count_filter(app):
    """功能1 字数筛选：词组列字符数匹配；-1=关；5=≥5。"""
    rows = [
        ("一", "a", "1", "A 词库", "A"),          # 1 字
        ("二字", "b", "1", "A 词库", "A"),        # 2 字
        ("三四五", "c", "1", "A 词库", "A"),       # 3 字
        ("六七八九", "d", "1", "A 词库", "A"),     # 4 字
        ("十十一十二", "e", "1", "A 词库", "A"),    # 5 字
        ("一二三四五六", "f", "1", "A 词库", "A"),  # 6 字（≥5）
    ]
    m = DictModel()
    m.set_all_data(rows, len(rows))
    assert m.filtered_count() == 6
    m.set_char_count_filter(1)
    assert m.filtered_count() == 1
    m.set_char_count_filter(5)
    assert m.filtered_count() == 2    # 5 字 + 6 字
    m.set_char_count_filter(-1)
    assert m.filtered_count() == 6    # 关 → 全部


def _order_phrases(m):
    """多码模式下 _order 仅含 int 行（不插分组头），返回其词组序列用于断言聚拢顺序。"""
    return [m._all_data[i][0] for i in m._order]


def test_multi_code_filter(app):
    """功能2 一词多码：同词组异编码行被筛出，并按 (词组, 编码) 聚拢相邻。"""
    rows = [
        ("苹果", "pg", "1", "A 词库", "A"),
        ("苹果", "apple", "1", "A 词库", "A"),   # 苹果 有 2 编码 → 一词多码
        ("香蕉", "xj", "1", "A 词库", "A"),       # 唯一编码
        ("梨", "li", "1", "A 词库", "A"),
    ]
    m = DictModel()
    m.set_all_data(rows, len(rows))
    assert m._multi_code_srcs == {0, 1}
    m.set_multi_code_filter(True)
    assert m.filtered_count() == 2
    # 同词组聚拢相邻；多码模式不插分组头
    assert all(isinstance(i, int) for i in m._order)
    assert _order_phrases(m) == ["苹果", "苹果"]
    m.set_multi_code_filter(False)
    assert m.filtered_count() == 4


def test_multi_code_cluster_cross_group(app):
    """全部视图下，跨分组的同词组多码行应聚拢相邻，且不被分组头隔断。"""
    rows = [
        ("猫", "mao", "1", "A 词库", "A"),
        ("猫", "cat", "1", "B 词库", "A"),     # 猫 在 A、B 两组各一码 → 跨组多码
        ("狗", "gou", "1", "A 词库", "A"),
    ]
    m = DictModel()
    m.set_all_data(rows, len(rows))
    m.set_multi_code_filter(True)
    assert m.filtered_count() == 2
    # 跨组同词组相邻、无分组头穿插
    assert all(isinstance(i, int) for i in m._order)
    assert _order_phrases(m) == ["猫", "猫"]
    m.set_multi_code_filter(False)
    assert m.filtered_count() == 3


def test_multi_code_scoped_to_group(app):
    """选某分组时多码判定只在该分组内：仅在别组才有另一码的词不出现。"""
    rows = [
        ("猫", "mao", "1", "A 词库", "A"),     # 仅在 A 组、单码 → A 组内不算多码
        ("猫", "cat", "1", "B 词库", "A"),     # 仅在 B 组、单码
        ("鱼", "yu1", "1", "A 词库", "A"),
        ("鱼", "yu2", "1", "A 词库", "A"),     # 鱼 在 A 组内两码 → A 组内多码
    ]
    m = DictModel()
    m.set_all_data(rows, len(rows))
    # 选 A 组：跨组的猫(cat)不在 A 组不出现；A 组内猫单码不算；鱼双码算
    m.set_filter_state(group="A 词库")
    m.set_multi_code_filter(True)
    assert _order_phrases(m) == ["鱼", "鱼"], _order_phrases(m)
    # 选 B 组：猫单码不算 → 无多码行
    m.set_filter_state(group="B 词库")
    m.set_multi_code_filter(True)
    assert m.filtered_count() == 0
    # 复位
    m.set_filter_state(group="")
    m.set_multi_code_filter(False)
    assert m.filtered_count() == 4


def test_merge_duplicates_max_freq(app):
    rows = [
        ("重复词", "aa", "5", "A 词库", "A"),
        ("重复词", "aa", "3", "A 词库", "A"),
        ("重复词", "aa", "2", "A 词库", "A"),
    ]
    m = DictModel()
    m.set_all_data(rows, len(rows))
    groups = m.find_duplicate_groups((0, 1))
    removed = m.merge_duplicates(groups, strategy="max_freq")
    assert removed == 2
    assert len(m._all_data) == 1
    # 主行词频应取最大值 5
    assert m._all_data[0][2] == "5"


def test_move_to_group(app):
    rows = [
        ("甲", "a", "1", "A 词库", "A"),
        ("乙", "b", "2", "A 词库", "A"),
        ("丙", "c", "3", "B 青云", "B"),
    ]
    m = DictModel()
    m.set_all_data(rows, len(rows))
    vr = m._view_row_of_data(0)  # '甲' 的显示行（Plan ① 延迟重排：物理 _all_data 槽位不变，甲恒在 _all_data[0]）
    changed, first = m.move_selected_to_group([vr], "B 青云", also_enable=True)
    assert changed == 1
    assert first >= 0
    assert m.get_field(first, "分组") == "B 青云"
    assert m.get_field(first, "启用") == "A"
    # 物理数据量不变（仅改分组字段，不重排物理行）
    assert len(m._all_data) == 3
    # 幂等：已位于目标组的行再次移动到同组应无变更。
    # Plan ① 下甲移动后仍留 _all_data[0]，故仍用 _view_row_of_data(0) 取「甲」；
    # 其当前分组已是 B 青云，再移到 B 青云应为 0 变更。
    vr_jia = m._view_row_of_data(0)
    changed2, _ = m.move_selected_to_group([vr_jia], "B 青云", also_enable=True)
    assert changed2 == 0


def test_rebuild_keep_loaded_preserves_manual_reorder(app):
    """B2 修复：先手工拖拽排序（仅改 _order、置 _order_dirty），再调 _rebuild_order_keep_loaded，
    待保存的排序不应被静默清掉——_rebuild_order_keep_loaded 现在会先 _sync_order_to_data 归并。"""
    rows = [("词%d" % i, "c%d" % i, str(i), "A 词库", "A") for i in range(6)]
    m = DictModel()
    m.set_all_data(rows, len(rows))

    def phrases():
        return [m._all_data[i][0] for i in m._order if isinstance(i, int)]

    assert phrases() == ["词0", "词1", "词2", "词3", "词4", "词5"]
    # 把 view row 3（data idx 2，「词2」）拖到真实末尾
    src_vr = 3
    m.reorder_view_rows([src_vr], len(m._order) - 1, before=False)
    expected_phrases = phrases()  # 应为 [词0, 词1, 词3, 词4, 词5, 词2]
    assert expected_phrases[-1] == "词2"
    assert m._order_dirty is True
    # B2 场景：触发「重建显示顺序但保留懒加载边界」——修复前会静默丢弃待保存排序
    m._rebuild_order_keep_loaded()
    # 重建后显示序应与拖拽后一致（手工排序已归并进 _all_data）
    assert phrases() == expected_phrases, (phrases(), expected_phrases)
    # 且物理末尾确为被移动词（证明排序真正归并，未被清掉）
    assert m._all_data[-1][0] == "词2"


def test_drag_back_to_origin_not_dirty(app):
    """B3 修复：把行拖回原位（顺序与分组均无变化）不应标脏。"""
    rows = [("词%d" % i, "c%d" % i, str(i), "A 词库", "A") for i in range(4)]
    m = DictModel()
    m.set_all_data(rows, len(rows))
    dirty_before = m.is_dirty()
    odirty_before = getattr(m, "_order_dirty", False)
    # 取一个数据行（view row 2 -> data idx 1），拖到它自己的位置（target=同位置, before=True）
    src_vr = 2
    before = list(m._order)
    m.reorder_view_rows([src_vr], src_vr, before=True)
    # 拖回原位：顺序未变、分组未变 → 不标脏
    assert m._order == before, (m._order, before)
    assert m.is_dirty() == dirty_before, "拖回原位不应标脏 (B3)"
    assert getattr(m, "_order_dirty", False) == odirty_before, "拖回原位不应置 _order_dirty (B3)"


def test_reorder_to_bottom_reaches_true_end(app):
    """B4 修复的模型层契约：在大表懒加载下，拖到「真实末尾」（target=len(_order)-1, before=False）
    应把行放到 _order 最后一个数据位，而非已加载末尾（rowCount()-1）。

    控制器层（drag_controller._update_drag_feedback）现已把「拖到底部」的 target_row
    由 rowCount() 改为 len(_order)-1，本测试锁定模型侧契约：传入该参数时落点=真实文件末尾。
    """
    rows = [("词%d" % i, "c%d" % i, str(i), "A 词库", "A") for i in range(5000)]
    m = DictModel()
    m.set_all_data(rows, len(rows))
    # 懒加载：rowCount 远小于 _order 长度
    assert m.rowCount() < len(m._order)
    # 把第一个数据行（view row 1 -> data idx 0，「词0」）拖到真实末尾
    src_vr = 1
    # 这正是控制器在「拖到底部」时现在会传入的参数：
    target = len(m._order) - 1
    m.reorder_view_rows([src_vr], target, before=False)
    data_seq = [i for i in m._order if isinstance(i, int)]
    # 末尾数据行应为被移动的词（真实文件末尾，而非 ~200 行处）
    assert m._all_data[data_seq[-1]][0] == "词0"
    # 且它确在 _order 最后一个数据位（落点 = 真实末尾）
    assert data_seq[-1] == [i for i in m._order if isinstance(i, int)][-1]


def test_add_row_fields_preserves_input_under_filter(app):
    """M1 修复：存在筛选（字数=1）时，新追加的 2 字词组不匹配筛选、_view_row_of_data 返回 -1，
    原写法 set_field(-1, ...) 会静默丢输入；修复后直接写物理行，输入应保留。"""
    m = DictModel()
    m.set_all_data([("一", "a", "1", "A 词库", "A")], 1)
    m.set_char_count_filter(1)   # 仅显示 1 字词组
    vr = m.add_row_fields({"词组": "二字词", "编码": "ezc", "分组": "A 词库"})
    # 即使新行被筛掉（vr == -1），物理行必须已写入
    assert len(m._all_data) == 2
    assert m._all_data[1][0] == "二字词"
    assert m._all_data[1][1] == "ezc"
    assert m._all_data[1][3] == "A 词库"


def test_setdata_word_edit_lazy_recompute(app):
    """M4 修复：未启用重复高亮/一词多码时，编辑词组/编码列不应立即付 2×O(n) 全表重算，
    而是置 _dup_computed/_multi_computed=False（延迟到功能启用时再算）。"""
    rows = [("词%d" % i, "c%d" % i, str(i), "A 词库", "A") for i in range(20)]
    m = DictModel()
    m.set_all_data(rows, 20)   # 测试路径走 compute_load_extras，_dup_computed=True
    assert m._dup_computed is True
    assert m._multi_computed is True
    # 编辑首个数据行的词组列（col 0）——注意视图首行是分组头，须取数据行
    first_vr = m.first_data_view_row()
    assert m.setData(m.index(first_vr, 0), "改过的词", Qt.EditRole) is True
    # 不应立即重算 → 标志应被置回未计算（而非保留 True）
    assert m._dup_computed is False
    assert m._multi_computed is False
    # 启用重复高亮后，再编辑词组列应立刻重算并恢复已算状态（惰性重算生效）
    m.set_show_duplicates(True)
    assert m._dup_computed is True
    assert m.setData(m.index(first_vr, 0), "再改", Qt.EditRole) is True
    assert m._dup_computed is True


def test_sort_sets_order_dirty(app):
    """L1 修复：表头排序改动显示顺序后必须置 _order_dirty，否则保存时排序被静默丢弃。"""
    m = DictModel()
    m.set_all_data([("b", "x", "1", "A 词库", "A"), ("a", "y", "2", "A 词库", "A")], 2)
    assert m._order_dirty is False
    m.sort(0, Qt.AscendingOrder)
    assert m._order_dirty is True
    # 物理归并后排序应落盘：_all_data 按词组升序
    m._sync_order_to_data()
    assert [r[0] for r in m._all_data] == ["a", "b"]


def test_edit_group_reinserts_header(app):
    """L2 修复：在表格里把某行『分组』列从 A 改到 B，应重建顺序使该行落到 B 组头下。"""
    rows = [("甲", "a", "1", "A 词库", "A"), ("乙", "b", "2", "A 词库", "A")]
    m = DictModel()
    m.set_all_data(rows, 2)
    jia_vr = m._view_row_of_data(0)   # 甲
    assert m.set_field(jia_vr, "分组", "B 青云") is True
    order = m._order
    # 应存在 B 青云 分组头，且甲（data idx 0）紧跟其后
    assert ("H", "B 青云") in order
    b_hdr = order.index(("H", "B 青云"))
    assert order[b_hdr + 1] == 0
    assert m._all_data[0][3] == "B 青云"


def test_commit_order_clears_dirty(app):
    """L3 修复：后台筛选 commit 的新顺序是已同步的权威显示序，须清 _order_dirty，
    否则后续 _sync_order_to_data 会反写破坏数据。"""
    m = DictModel()
    m.set_all_data([("a", "x", "1", "A 词库", "A"), ("b", "y", "2", "A 词库", "A")], 2)
    m._order_dirty = True
    m.commit_order([1, 0])
    assert m._order_dirty is False
    assert m._order == [1, 0]
