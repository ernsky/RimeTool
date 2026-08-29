"""右栏功能模块 builder：新建编码 / 字数筛选 / 分类导出 / 启用筛选 / 各种动作。

按钮带相关 emoji；严重操作（删除类）用危险警示色（#DangerButton）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QButtonGroup,
)

if TYPE_CHECKING:
    from ...app import RimeDictApp


class ModuleBuilder:
    """构建右栏功能模块，所有按钮接到 monitor 的对应方法。"""

    @staticmethod
    def build(monitor: "RimeDictApp") -> QWidget:
        panel = QWidget()
        panel.setObjectName("RightPanel")
        panel.setMaximumWidth(230)
        root = QVBoxLayout(panel)
        root.setSpacing(6)
        root.setContentsMargins(8, 8, 8, 8)

        # ① 新建编码
        monitor.btn_new = QPushButton("➕ 新建编码")
        monitor.btn_new.setToolTip("按编码规则批量或单条生成编码并入库（可手填自由编码）")
        root.addWidget(monitor.btn_new)

        # ② 批量修改权重（危险）
        monitor.btn_batch_weight = QPushButton("⚖ 批量修改权重")
        monitor.btn_batch_weight.setObjectName("DangerButton")
        monitor.btn_batch_weight.setToolTip("读取 Rime 用户词典权重，按 词组+编码 匹配回写数据库")
        root.addWidget(monitor.btn_batch_weight)

        # ③ 批量删除（危险）
        monitor.btn_batch_del = QPushButton("🗑 批量删除")
        monitor.btn_batch_del.setObjectName("DangerButton")
        monitor.btn_batch_del.setToolTip("从 .txt/.yaml/.md 清单批量删除（一列匹配词组/两列匹配词组+编码），危险")
        root.addWidget(monitor.btn_batch_del)

        # ④ 替换分组（危险）
        monitor.btn_replace_group = QPushButton("🔄 替换分组")
        monitor.btn_replace_group.setObjectName("DangerButton")
        monitor.btn_replace_group.setToolTip("将指定词库与数据库匹配，更新分类/分组/权重")
        root.addWidget(monitor.btn_replace_group)

        # ⑤ 字数筛选（6 并排）
        root.addWidget(QLabel("字数"))
        h_len = QHBoxLayout()
        monitor.len_btns = {}
        for tag in ["无", "一", "二", "三", "四", "多"]:
            b = QPushButton(tag)
            b.setCheckable(True)
            b.setToolTip("按词组字数筛选：无/一/二/三/四/多(≥5)，可与其它筛选叠加")
            monitor.len_btns[tag] = b
            h_len.addWidget(b)
        root.addLayout(h_len)

        # ⑥ 语音词组查漏
        monitor.btn_voice = QPushButton("🎙 语音词组查漏（占位）")
        monitor.btn_voice.setToolTip("占位功能：列出缺失拼音/音频参照的词组（逻辑待补）")
        root.addWidget(monitor.btn_voice)

        # ⑦ 启用筛选（3 并排）
        root.addWidget(QLabel("启用"))
        h_en = QHBoxLayout()
        monitor.en_btns = {}
        for tag in ["全部", "启用", "未启用"]:
            b = QPushButton(tag)
            b.setCheckable(True)
            b.setChecked(tag == "全部")
            b.setToolTip("按启用状态筛选（可与其它筛选叠加）")
            monitor.en_btns[tag] = b
            h_en.addWidget(b)
        root.addLayout(h_en)

        # ⑧~⑪ 动作
        monitor.btn_multi_code = QPushButton("🔁 一词多码")
        monitor.btn_multi_code.setToolTip("筛选：同一词组存在多个不同编码的记录")
        monitor.btn_multi_code.setCheckable(True)
        monitor.btn_dup = QPushButton("👥 重复项筛选")
        monitor.btn_dup.setToolTip("筛选：词组+编码完全相同的冗余记录")
        monitor.btn_dup.setCheckable(True)
        monitor.btn_next_dup = QPushButton("⏭ 下一自重复")
        monitor.btn_next_dup.setToolTip("跳到下一个重复组的第一条")
        monitor.btn_merge = QPushButton("🔀 合并重复")
        monitor.btn_merge.setToolTip("每组(词组+编码相同)保留权重最大一条，删其余（危险）")
        for b in (monitor.btn_multi_code, monitor.btn_dup, monitor.btn_next_dup, monitor.btn_merge):
            root.addWidget(b)

        # ⑫ 保存为单一码表
        monitor.btn_save_single = QPushButton("📤 保存为单一码表")
        monitor.btn_save_single.setToolTip("将中栏当前显示记录导出为单个 .dict.yaml（前三列）")
        root.addWidget(monitor.btn_save_single)

        # ⑬ 分类导出（6 并排，互斥）
        root.addWidget(QLabel("分类导出"))
        h_cat = QHBoxLayout()
        monitor.cat_export_btns = {}
        cat_tip = {"单字": "导出单字类全部到 wubi.word.dict.yaml",
                   "常用": "导出常用类全部到 wubi.phrase.dict.yaml",
                   "用户": "导出用户类全部到 wubi.user.dict.yaml",
                   "多码": "导出多码类全部到 wubi.long.dict.yaml",
                   "英语": "导出英语类全部到 English.dict.yaml",
                   "符号": "导出符号类全部到 wubi.low.dict.yaml"}
        for cat in monitor.CATEGORY_CHOICES:
            label = monitor.CATEGORY_TO_BUTTON[cat]
            b = QPushButton(label)
            b.setCheckable(True)
            b.setToolTip(cat_tip[cat])
            monitor.cat_export_btns[cat] = b
            h_cat.addWidget(b)
        root.addLayout(h_cat)

        # ⑭ 导入数据库
        monitor.btn_import_db = QPushButton("📥 导入数据库")
        monitor.btn_import_db.setToolTip("从 .db 文件导入数据到当前数据库")
        root.addWidget(monitor.btn_import_db)

        root.addStretch(1)

        ModuleBuilder._wire(monitor)
        return panel

    @staticmethod
    def _wire(monitor: "RimeDictApp") -> None:
        monitor.btn_new.clicked.connect(monitor.on_new_code)
        monitor.btn_batch_weight.clicked.connect(monitor.on_batch_weight)
        monitor.btn_batch_del.clicked.connect(monitor.on_batch_delete)
        monitor.btn_replace_group.clicked.connect(monitor.on_replace_group)
        for tag, b in monitor.len_btns.items():
            b.clicked.connect(lambda _=False, t=tag: monitor.on_len_filter(t))
        monitor.btn_voice.clicked.connect(monitor.on_voice_placeholder)
        for tag, b in monitor.en_btns.items():
            b.clicked.connect(lambda _=False, t=tag: monitor.on_enabled_filter(t))
        monitor.btn_multi_code.clicked.connect(monitor.on_filter_multi_code)
        monitor.btn_dup.clicked.connect(monitor.on_filter_duplicate)
        monitor.btn_next_dup.clicked.connect(monitor.on_next_duplicate)
        monitor.btn_merge.clicked.connect(monitor.on_merge_duplicates)
        monitor.btn_save_single.clicked.connect(monitor.on_save_single_table)
        for cat, b in monitor.cat_export_btns.items():
            b.clicked.connect(lambda _=False, c=cat: monitor.on_export_category(c))
        monitor.btn_import_db.clicked.connect(monitor.on_import_database)
