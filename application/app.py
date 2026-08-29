"""Rime 码表管理工具 —— 主窗口与全部交互逻辑。

四区布局：
  顶 = 工具栏（配置/部署/保存 + 六输入框 + 搜索/删除/交换权重）
  左 = 分组树
  中 = 词组表（六列）
  右 = 功能模块栏
"""

from __future__ import annotations

import json
import os
from typing import List, Optional

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QFileDialog, QMessageBox, QInputDialog, QDialog, QFormLayout, QLineEdit,
    QComboBox,
)
from PySide6.QtCore import Qt

from design_system import apply_theme

from .core.models import WordRecord, CATEGORY_CHOICES, CATEGORY_TO_BUTTON, word_length_bucket
from .core.repository import Repository
from .core.logger import get_logger
from .providers.datasource import DataSource
from .ui.builders.toolbar_builder import ToolbarBuilder
from .ui.builders.group_builder import GroupBuilder
from .ui.builders.list_builder import ListBuilder
from .ui.builders.module_builder import ModuleBuilder
from .ui.builders.collapsible_splitter import CollapsibleSplitter
from .ui.config_dialog import ConfigDialog


class RimeDictApp(QMainWindow):
    CATEGORY_CHOICES = CATEGORY_CHOICES
    CATEGORY_TO_BUTTON = CATEGORY_TO_BUTTON

    def __init__(self, config_path: str = "config.json") -> None:
        super().__init__()
        self._logger = get_logger("RimeTool")
        self._logger.info("程序启动")
        self.setWindowTitle("Rime 码表管理工具")
        self.resize(1000, 600)
        # 窗口图标
        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 "ui", "resources", "app_icon.ico")
        if os.path.exists(icon_path):
            from PySide6.QtGui import QIcon
            self.setWindowIcon(QIcon(icon_path))

        self.config_path = config_path
        self.config = self._load_config()

        # 数据层
        db_path = self._resolve_path(self.config.get("db_path", "data.db"))
        self.repo = Repository(db_path)
        self.ds = DataSource(self.repo)

        # 当前筛选状态
        self._cur_filter_group = ""
        self._len_filter = ""
        self._enabled_filter = ""
        self._suppress_group_signal = False   # 回填行时抑制分组筛选信号

        self._build_ui()
        # 先显示窗口，再加载数据
        self.show()
        # 直接加载数据（带异常处理，避免静默失败）
        try:
            self.refresh_all()
        except Exception as e:
            self._logger.error("初始化加载失败: %s", e)
            self._set_status(f"数据加载失败: {e}")

    # ---------------- 配置 ----------------
    def _load_config(self) -> dict:
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {"db_path": "data/data.db", "rime_user_dir": "", "default_weight": 1,
                "theme": "dark", "backup_dir": "data/bak", "wubi_char_table": "",
                "wubi_weight_table": "", "word_list": "data/word.txt",
                "weight_table": "data/weight.txt",
                "voice_word_file": "", "export_dir": "", "newcode_ref_dir": "data/dict",
                "log_dir": "data/logs", "replace_group_file": "dict/wubi.chaos.dict.yaml",
                "rime_deployer_path": ""}

    def _resolve_path(self, p: str) -> str:
        if os.path.isabs(p):
            return p
        return os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", p))

    def _rime_user_dir(self) -> str:
        d = self.config.get("rime_user_dir", "")
        if not d:
            d = os.path.expanduser("~/AppData/Roaming/Rime")
        return d

    # ---------------- UI ----------------
    def _build_ui(self) -> None:
        top_bar = ToolbarBuilder.build(self)

        central = QWidget()
        central.setObjectName("Central")
        self.setCentralWidget(central)
        # 消除窗口首帧白色闪烁：让 widget 使用样式背景而非原生背景
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAutoFillBackground(True)
        central.setAttribute(Qt.WA_StyledBackground, True)
        central.setAutoFillBackground(True)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(top_bar)
        split = CollapsibleSplitter(Qt.Horizontal)
        self.group_tree = GroupBuilder.build(self)
        # 左分组树：关滚动条、隐藏展开箭头
        self.group_tree.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.group_tree.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.group_tree.setRootIsDecorated(False)
        self.word_table = ListBuilder.build(self)
        self.word_table.verticalHeader().setVisible(False)
        self.module_panel = ModuleBuilder.build(self)

        split.addWidget(self.group_tree)
        split.addWidget(self.word_table)
        split.addWidget(self.module_panel)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 3)
        split.setStretchFactor(2, 1)
        root.addWidget(split)

        # 状态栏
        from PySide6.QtWidgets import QStatusBar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("就绪")

        # 工具栏信号
        self.btn_config.clicked.connect(self.on_config)
        self.btn_deploy.clicked.connect(self.on_deploy)
        self.btn_save.clicked.connect(self.on_save)
        self.btn_search.clicked.connect(self.on_search)
        self.btn_delete.clicked.connect(self.on_delete_row)
        self.btn_swap.clicked.connect(self.on_swap_weight)
        # 输入框修改追踪
        self._modified_fields = set()
        self.in_key.textChanged.connect(lambda: self._modified_fields.add("key"))
        self.in_code.textChanged.connect(lambda: self._modified_fields.add("code"))
        self.in_weight.valueChanged.connect(lambda: self._modified_fields.add("weight"))
        self.in_category.currentTextChanged.connect(lambda: self._modified_fields.add("category"))
        self.in_group.currentTextChanged.connect(lambda: self._modified_fields.add("group"))
        self.in_enabled.stateChanged.connect(lambda: self._modified_fields.add("enabled"))
        # 分组单框：选择即触发筛选（选中行时不触发，避免干扰批量修改）
        self.in_group.activated.connect(self._on_group_changed)
        self.in_category.currentTextChanged.connect(self._on_category_or_enabled_changed)
        self.in_enabled.stateChanged.connect(self._on_category_or_enabled_changed)
        # Ctrl+A 全选
        from PySide6.QtGui import QShortcut, QKeySequence
        QShortcut(QKeySequence("Ctrl+A"), self, self.on_select_all)
    
    def _on_category_or_enabled_changed(self):
        """分类/启用框变化时，如果有选中行则不触发刷新（批量修改模式）。"""
        sel = self.word_table.selectionModel().selectedRows()
        if sel:
            # 有选中行时不刷新，等用户点击保存
            return
        # 无选中行时刷新（筛选）
        self.refresh_list()

    def _on_group_changed(self) -> None:
        if getattr(self, "_suppress_group_signal", False):
            return
        # 如果有选中的行，不触发筛选（批量修改模式）
        sel = self.word_table.selectionModel().selectedRows()
        if sel:
            return
        self._cur_filter_group = self.in_group.full_path()
        self.refresh_list()

    def _set_status(self, msg: str) -> None:
        self.status_bar.showMessage(msg)

    # ---------------- 刷新 ----------------
    def refresh_all(self) -> None:
        # 刷新过程中分组下拉会被重填，屏蔽其筛选信号，避免表格被意外过滤
        self._suppress_group_signal = True
        try:
            self.ds.invalidate_cache()  # 失效分组树缓存
            GroupBuilder.refresh(self)
            ToolbarBuilder.fill_group_combo(self)
            self.refresh_list()
        finally:
            self._suppress_group_signal = False

    def refresh_list(self, from_search: bool = False) -> None:
        # from_search=False 时（如保存/刷新），不把输入框文本当作筛选条件；
        # 仅 from_search=True（点搜索按钮）才按输入框 key/code/weight/category 过滤。
        # 大数据量时只加载前 1000 条，避免启动卡顿（搜索时不限）
        limit = 0 if from_search else 1000
        recs = self.ds.query(
            key=self.in_key.text().strip() if from_search else "",
            code=self.in_code.text().strip() if from_search else "",
            weight=str(self.in_weight.value()) if (from_search and self._weight_touched()) else "",
            category=self.in_category.currentText() if from_search else "",
            group=self._cur_filter_group,
            enabled=self._enabled_filter,
            length_bucket=self._len_filter,
            limit=limit,
        )
        # 已选中的额外筛选（字数/一词多码/重复）
        if getattr(self, "_only_multi_code", False):
            recs = self._filter_multi_code(recs)
        if getattr(self, "_only_duplicate", False):
            recs = self._filter_duplicate(recs)
        ListBuilder.refresh(self, recs)
        # 显示加载提示
        total = self.ds.count()
        loaded = len(recs)
        if loaded < total:
            self._set_status(f"已加载 {loaded} / {total} 条（点击搜索查看全部）")
        elif total > 0:
            self._set_status(f"共 {total} 条记录")

    def _weight_touched(self) -> bool:
        # 权重仅当非默认1且用户改过时参与搜索
        return self.in_weight.value() != 1

    # ---------------- 顶栏交互 ----------------
    def on_row_selected(self, index) -> None:
        rec = self.word_model.recs[index.row()]
        # 回填期间抑制分组级联的筛选信号，避免点击行后表格被过滤
        self._suppress_group_signal = True
        try:
            self.in_key.setText(rec.词组)
            self.in_code.setText(rec.编码)
            self.in_weight.setValue(rec.权重)
            self.in_category.setCurrentText(rec.分类)
            self._set_group_ui(rec.分组)
            self.in_enabled.setChecked(rec.启用)
        finally:
            self._suppress_group_signal = False
            # 清空修改记录（回填不算修改）
            self._modified_fields.clear()

    def _set_group_ui(self, group_path: str) -> None:
        """把 分组 path 回填到三级级联框（逐级依赖加载）。"""
        self.in_group.set_path(group_path)

    def on_save(self) -> None:
        """保存：如果有选中行则批量修改，否则单条新增/更新。"""
        # 检查是否有选中的行
        sel = self.word_table.selectionModel().selectedRows()
        
        if sel:
            # 批量修改选中的行
            self._batch_update_from_inputs(sel)
        elif self._cur_filter_group or self.in_category.currentText():
            # 无选中行但有分组/分类筛选，批量更新该分组/分类
            self.on_batch_update_by_filter()
        else:
            # 单条新增/更新
            self._single_save_from_inputs()

    def _single_save_from_inputs(self) -> None:
        """从输入框取值，单条新增或更新。"""
        key = self.in_key.text().strip()
        if not key:
            QMessageBox.warning(self, "提示", "词组不能为空。")
            return
        group_path = self.in_group.full_path()
        rec = WordRecord(
            key=key,
            code=self.in_code.text().strip().lower(),
            weight=self.in_weight.value(),
            category=self.in_category.currentText(),
            group=group_path.strip("/"),
            enabled=self.in_enabled.isChecked(),
        )
        self.ds.upsert(rec)
        self.refresh_all()
        self._set_status(f"已保存：{key}（分类={rec.分类 or '空'}，分组={group_path or '空'}）")

    def _batch_update_from_inputs(self, sel) -> None:
        """批量修改选中的行：只修改输入框中有值的字段，未修改的保持原值。"""
        # 获取输入框的值
        new_key = self.in_key.text().strip()
        new_code = self.in_code.text().strip().lower()
        new_weight = self.in_weight.value()
        new_category = self.in_category.currentText()
        new_group = self.in_group.full_path().strip("/")
        new_enabled = self.in_enabled.isChecked()

        # 判断哪些字段需要修改（输入框非空）
        change_key = "key" in self._modified_fields
        change_code = "code" in self._modified_fields
        change_weight = "weight" in self._modified_fields
        change_category = "category" in self._modified_fields
        change_group = "group" in self._modified_fields
        change_enabled = "enabled" in self._modified_fields

        updated = 0
        for idx in sel:
            row = idx.row()
            if row >= len(self.word_model.recs):
                continue
            rec = self.word_model.recs[row]
            # 只修改有变化的字段
            if change_key and rec.词组 != new_key:
                rec.词组 = new_key
            if change_code and rec.编码 != new_code:
                rec.编码 = new_code
            if change_weight and rec.权重 != new_weight:
                rec.权重 = new_weight
            if change_category and rec.分类 != new_category:
                rec.分类 = new_category
            if change_group and rec.分组 != new_group:
                rec.分组 = new_group
            if change_enabled and rec.启用 != new_enabled:
                rec.启用 = new_enabled
            self.ds.upsert(rec)
            updated += 1

        # 清空修改记录
        self._modified_fields.clear()

        self.refresh_all()
        self._set_status(f"已批量修改 {updated} 条记录")

    def on_search(self) -> None:
        self.refresh_list(from_search=True)

    def on_delete_row(self) -> None:
        """删除：优先删除选中行，无选中行但有分组/分类筛选时删除该分组/分类全部记录。"""
        sel = self.word_table.selectionModel().selectedRows()
        
        if sel:
            # 有选中行，删除选中的行
            rows_to_delete = [(self.word_model.recs[i.row()].词组, self.word_model.recs[i.row()].编码) for i in sel]
            for k, c in rows_to_delete:
                self.ds.delete_by_key_and_code(k, c)
            self.refresh_all()
            self._set_status(f"已删除 {len(rows_to_delete)} 条记录")
        elif self._cur_filter_group or self.in_category.currentText():
            # 无选中行但有分组/分类筛选，删除该分组/分类的全部记录
            group = self._cur_filter_group
            category = self.in_category.currentText()
            
            # 先获取要删除的记录数
            count = self.ds.count_by_filter(group=group, category=category)
            
            if count == 0:
                self._set_status("没有匹配的记录")
                return
            
            # 确认删除
            scope = []
            if group:
                scope.append(f"分组={group}")
            if category:
                scope.append(f"分类={category}")
            scope_str = "，".join(scope)
            
            reply = QMessageBox.question(
                self, "确认删除",
                f"将删除 {scope_str} 的全部 {count} 条记录。\n\n此操作不可恢复，是否继续？",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return
            
            # 执行批量删除
            deleted = self.ds.delete_by_filter(group=group, category=category)
            self.refresh_all()
            self._set_status(f"已删除 {scope_str} 的全部 {deleted} 条记录")
        else:
            QMessageBox.warning(self, "提示", "请先选中要删除的行，或点击分组/分类标签筛选后再删除。")

    def on_select_all(self) -> None:
        """全选：选中当前筛选条件下的所有记录（跨页全选）。"""
        # 使用搜索模式加载所有匹配的记录
        recs = self.ds.query(
            key=self.in_key.text().strip(),
            code=self.in_code.text().strip(),
            weight=str(self.in_weight.value()) if self._weight_touched() else "",
            category=self.in_category.currentText(),
            group=self._cur_filter_group,
            enabled=self._enabled_filter,
            length_bucket=self._len_filter,
            limit=0,  # 不限数量
        )
        if not recs:
            self._set_status("没有匹配的记录")
            return
        
        # 选中表格中显示的所有行
        self.word_table.selectAll()
        
        self._set_status(f"已选中当前筛选条件下的 {len(recs)} 条记录")

    def on_batch_update_by_filter(self) -> None:
        """按分组/分类批量更新：将当前筛选条件下的所有记录批量修改。"""
        # 获取输入框的值
        new_category = self.in_category.currentText()
        new_group = self.in_group.full_path().strip("/")
        new_enabled = self.in_enabled.isChecked()
        new_weight = self.in_weight.value()
        new_code = self.in_code.text().strip().lower()

        # 判断哪些字段需要修改
        change_category = "category" in self._modified_fields
        change_group = "group" in self._modified_fields
        change_enabled = "enabled" in self._modified_fields
        change_weight = "weight" in self._modified_fields
        change_code = "code" in self._modified_fields

        if not any([change_category, change_group, change_enabled, change_weight, change_code]):
            QMessageBox.warning(self, "提示", "请先在输入框中修改要更新的字段。")
            return

        # 构建查询条件
        kwargs = {}
        if self._cur_filter_group:
            kwargs["group"] = self._cur_filter_group
        if self.in_category.currentText():
            kwargs["category"] = self.in_category.currentText()
        if self._enabled_filter:
            kwargs["enabled"] = self._enabled_filter

        # 先获取要更新的记录数
        count = self.ds.count_by_filter(**kwargs)
        if count == 0:
            self._set_status("没有匹配的记录")
            return

        # 确认更新
        reply = QMessageBox.question(
            self, "确认批量修改",
            f"将更新当前筛选条件下的全部 {count} 条记录。\n\n是否继续？",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        # 执行批量更新
        updated = self.ds.batch_update(
            new_group=new_group if change_group else "",
            new_category=new_category if change_category else "",
            new_enabled=new_enabled if change_enabled else None,
            new_weight=new_weight if change_weight else None,
            new_code=new_code if change_code else "",
            **kwargs
        )

        # 清空修改记录
        self._modified_fields.clear()

        self.refresh_all()
        self._set_status(f"已批量更新 {updated} 条记录")

    def on_swap_weight(self) -> None:
        sel = self.word_table.selectionModel().selectedRows()
        if len(sel) < 2:
            QMessageBox.warning(self, "提示", "请选中两行以交换权重。")
            return
        r1 = self.word_model.recs[sel[0].row()]
        r2 = self.word_model.recs[sel[1].row()]
        r1.权重, r2.权重 = r2.权重, r1.权重
        self.ds.upsert(r1); self.ds.upsert(r2)
        self.refresh_list(from_search=False)
        self._set_status(f"已交换权重：{r1.词组} <-> {r2.词组}")

    def on_group_selected(self, item, col) -> None:
        path = item.data(0, Qt.UserRole)
        self._cur_filter_group = path or ""
        # 点左侧分组标签时，清空顶栏输入框
        self._clear_inputs()
        # 分组切换使用 limit 避免大数据量假死
        self.refresh_list(from_search=False)

    def _clear_inputs(self) -> None:
        """清空顶部六个输入框（词组/编码/权重/分类/分组/启用）。"""
        self.in_key.clear()
        self.in_code.clear()
        self.in_weight.setValue(1)
        self.in_category.setCurrentIndex(0)
        self.in_group.set_path("")
        self.in_enabled.setChecked(True)

    # ---------------- 右栏：筛选 ----------------
    def on_len_filter(self, tag: str) -> None:
        # 互斥：选中一个时，其它字数按钮自动取消
        for t, b in self.len_btns.items():
            if t != tag:
                b.setChecked(False)
        self._len_filter = tag if self.len_btns[tag].isChecked() else ""
        self.refresh_list()

    def on_enabled_filter(self, tag: str) -> None:
        for t, b in self.en_btns.items():
            if t != tag:
                b.setChecked(False)
        # 检查点击后当前按钮是否仍被选中（点击已选中的按钮会 toggle 为未选中）
        if self.en_btns[tag].isChecked():
            self._enabled_filter = {"全部": "", "启用": "1", "未启用": "0"}[tag]
        else:
            self._enabled_filter = ""
        self.refresh_list()

    def on_filter_multi_code(self) -> None:
        self._only_multi_code = not getattr(self, "_only_multi_code", False)
        self.btn_multi_code.setChecked(self._only_multi_code)
        self.refresh_list()

    def on_filter_duplicate(self) -> None:
        self._only_duplicate = not getattr(self, "_only_duplicate", False)
        self.btn_dup.setChecked(self._only_duplicate)
        self.refresh_list()

    def on_next_duplicate(self) -> None:
        groups = self.repo.duplicate_groups()
        if not groups:
            QMessageBox.information(self, "提示", "没有重复项。")
            self._set_status("没有重复项")
            return
        # 跳到第一个重复组的第一条
        first = groups[0][0]
        self.in_key.setText(first.词组)
        self.refresh_list(from_search=False)
        self._set_status(f"已定位重复组：{first.词组}")

    def on_merge_duplicates(self) -> None:
        n = self.repo.merge_duplicates()
        self.refresh_all()
        QMessageBox.information(self, "合并重复", f"已删除 {n} 条冗余记录。")
        self._set_status(f"合并重复完成，已删除 {n} 条冗余记录")

    def on_voice_placeholder(self) -> None:
        QMessageBox.information(self, "占位", "语音词组查漏：逻辑待补充。")
        self._set_status("语音词组查漏：功能待补充")

    # 字数/重复 的内存筛选（query 已支持 only_multi_code/only_duplicate，
    # 这里用 Python 侧处理以复用模型）
    def _filter_multi_code(self, recs: List[WordRecord]) -> List[WordRecord]:
        seen = {}
        for r in recs:
            seen.setdefault(r.词组, set()).add(r.编码)
        multi = {k for k, v in seen.items() if len(v) >= 2}
        return [r for r in recs if r.词组 in multi]

    def _filter_duplicate(self, recs: List[WordRecord]) -> List[WordRecord]:
        s = set()
        dups = set()
        for r in recs:
            sig = (r.词组, r.编码)
            if sig in s:
                dups.add(sig)
            s.add(sig)
        return [r for r in recs if (r.词组, r.编码) in dups]

    # ---------------- 右栏：导出/动作 ----------------
    def on_export_category(self, category: str) -> None:
        # 互斥：选中一个分类时，其它分类按钮自动取消
        for c, b in self.cat_export_btns.items():
            if c != category:
                b.setChecked(False)
        from .core import rime_io
        # 仅加载该分类的记录，避免全量加载 162 万条导致内存暴涨
        recs = self.ds.query(category=category, limit=0)
        # 导出到配置的默认输出文件夹
        export_dir = self.config.get("export_dir", "")
        if export_dir:
            target = rime_io.export_category(recs, category, export_dir)
        else:
            target = rime_io.export_category(recs, category, self._rime_user_dir())
        QMessageBox.information(self, "导出完成", f"已导出到：\n{target}")
        self._set_status(f"已导出分类[{category}]到：{target}")

    def on_save_single_table(self) -> None:
        from .core import rime_io
        # 默认导出目录：配置中的「默认输出文件夹」（未配置则用当前目录）
        initial = self._resolve_path(self.config.get("export_dir", "")) or ""
        path, _ = QFileDialog.getSaveFileName(
            self, "保存为单一码表", initial or "export.dict.yaml", "*.dict.yaml")
        if not path:
            return
        recs = self.word_model.recs
        rime_io.export_single_table(recs, path, "wubi.custom")
        QMessageBox.information(self, "完成", f"已保存 {len(recs)} 条到：\n{path}")
        self._set_status(f"已保存单一码表 {len(recs)} 条到：{path}")

    def on_replace_group(self) -> None:
        """替换分组：弹出对话面板，选择源文件并设置替换分组。"""
        from .ui.replace_group_dialog import ReplaceGroupDialog
        dlg = ReplaceGroupDialog(self, self, self.config)
        dlg.exec()

    def on_batch_weight(self) -> None:
        from .core import rime_io
        # 读六个词库的权重，按 词组+编码 匹配回写库
        updated = 0
        batch = []
        for cat in CATEGORY_CHOICES:
            rel = rime_io.CATEGORY_FILE_MAP[cat]
            target = rime_io._resolve(self._rime_user_dir(), rel)
            weights = rime_io.parse_dict_weights(target)
            for (key, code), w in weights.items():
                rec = self.ds.repo.get_by_key_and_code(key, code)
                if rec and rec.权重 != w:
                    rec.权重 = w
                    batch.append(rec)
                    updated += 1
        # 批量写入
        for rec in batch:
            self.ds.upsert(rec)
        self.refresh_all()
        QMessageBox.information(self, "批量修改权重", f"已回写 {updated} 条权重。")
        self._set_status(f"批量修改权重完成，已回写 {updated} 条")

    def on_batch_delete(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择删除清单", "", "文本/词典(*.txt *.yaml *.md)")
        if not path:
            return
        keys = set()
        pairs = set()
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                parts = line.split("\t")
                if len(parts) >= 2:
                    pairs.add((parts[0].strip(), parts[1].strip()))
                else:
                    keys.add(parts[0].strip())
        removed = 0
        if pairs:
            for k, c in pairs:
                rec = self.ds.repo.get_by_key_and_code(k, c)
                if rec:
                    self.ds.delete_by_key_and_code(k, c); removed += 1
        else:
            for k in keys:
                if self.ds.repo.get_by_key(k):
                    self.ds.delete(k); removed += 1
        self.refresh_all()
        QMessageBox.information(self, "批量删除", f"已删除 {removed} 条。")
        self._set_status(f"批量删除完成，已删除 {removed} 条")

    def on_import_database(self) -> None:
        """导入数据库：从 .db 或 .tsv 文件导入数据到当前数据库。"""
        path, _ = QFileDialog.getOpenFileName(self, "选择要导入的文件", "", "数据库/TSV (*.db *.tsv);;SQLite 数据库 (*.db);;TSV 文件 (*.tsv)")
        if not path:
            return

        # 确认导入
        reply = QMessageBox.question(
            self, "确认导入",
            f"将从以下文件导入数据到当前数据库：\n{path}\n\n导入操作会将源数据合并到当前数据库中（词组+编码相同的记录会被覆盖）。\n\n是否继续？",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        try:
            imported = 0
            if path.lower().endswith(".tsv"):
                # TSV 导入
                imported = self._import_from_tsv(path)
            else:
                # SQLite 数据库导入
                imported = self._import_from_db(path)

            self.refresh_all()
            QMessageBox.information(self, "导入完成", f"已从 {path} 导入 {imported} 条记录。")
            self._set_status(f"导入完成，共导入 {imported} 条记录")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"导入失败：{e}")

    def _import_from_tsv(self, path: str) -> int:
        """从 TSV 文件导入。格式: 词组\t编码\t权重\t分类\t分组\t启用"""
        batch = []
        imported = 0
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                parts = line.split("\t")
                if len(parts) >= 6:
                    batch.append((parts[0], parts[1], int(parts[2] or 1), parts[3], parts[4], 1 if parts[5] == "A" else 0))
                elif len(parts) >= 2:
                    batch.append((parts[0], parts[1], int(parts[2] or 1) if len(parts) > 2 else 1, parts[3] if len(parts) > 3 else "", parts[4] if len(parts) > 4 else "", 1 if len(parts) > 5 and parts[5] == "A" else 0))
                if len(batch) >= 10000:
                    self.ds.repo.conn.executemany(
                        "INSERT INTO words(key,code,weight,category,grp,enabled) VALUES(?,?,?,?,?,?) "
                        "ON CONFLICT(key,code) DO UPDATE SET weight=excluded.weight, category=excluded.category, grp=excluded.grp, enabled=excluded.enabled",
                        batch
                    )
                    imported += len(batch)
                    batch = []
        if batch:
            self.ds.repo.conn.executemany(
                "INSERT INTO words(key,code,weight,category,grp,enabled) VALUES(?,?,?,?,?,?) "
                "ON CONFLICT(key,code) DO UPDATE SET weight=excluded.weight, category=excluded.category, grp=excluded.grp, enabled=excluded.enabled",
                batch
            )
            imported += len(batch)
        self.ds.repo.conn.commit()
        return imported

    def _import_from_db(self, path: str) -> int:
        """从 SQLite 数据库导入。"""
        import sqlite3 as sqlite
        src_conn = sqlite.connect(path)
        src_count = src_conn.execute("SELECT COUNT(*) FROM words").fetchone()[0]
        batch = []
        imported = 0
        cur = src_conn.execute("SELECT key, code, weight, category, grp, enabled FROM words")
        for row in cur.fetchall():
            batch.append(row)
            if len(batch) >= 10000:
                self.ds.repo.conn.executemany(
                    "INSERT INTO words(key,code,weight,category,grp,enabled) VALUES(?,?,?,?,?,?) "
                    "ON CONFLICT(key,code) DO UPDATE SET weight=excluded.weight, category=excluded.category, grp=excluded.grp, enabled=excluded.enabled",
                    batch
                )
                imported += len(batch)
                batch = []
        if batch:
            self.ds.repo.conn.executemany(
                "INSERT INTO words(key,code,weight,category,grp,enabled) VALUES(?,?,?,?,?,?) "
                "ON CONFLICT(key,code) DO UPDATE SET weight=excluded.weight, category=excluded.category, grp=excluded.grp, enabled=excluded.enabled",
                batch
            )
            imported += len(batch)
        self.ds.repo.conn.commit()
        src_conn.close()
        return imported

    def on_new_code(self) -> None:
        from .ui.new_code_dialog import NewCodeDialog
        dlg = NewCodeDialog(self, self, self.config)
        dlg.exec()



    # ---------------- 配置 / 部署 ----------------
    def on_config(self) -> None:
        """点击顶栏「配置」按钮：弹出半屏配置窗体（样式与主窗体一致）。"""
        dlg = ConfigDialog(self, self.config, self.config_path,
                          on_theme_changed=self._apply_theme)
        dlg.exec()

    def _apply_theme(self, theme_name: str) -> None:
        """应用主题（供配置对话框回调）。"""
        from design_system import apply_theme
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app:
            apply_theme(app, theme_name)

    def on_deploy(self) -> None:
        from .core import rime_io
        # 先导出启用记录，再触发部署
        self.on_export_to_rime()
        ok = rime_io.deploy(self._rime_user_dir(), self.config)
        if ok:
            QMessageBox.information(self, "部署", "已触发 Rime 重新部署。")
            self._set_status("已导出启用记录并触发 Rime 重新部署")
        else:
            QMessageBox.information(self, "部署", "未找到 rime_deployer，请手动部署。")
            self._set_status("导出完成，但未找到 rime_deployer，请手动部署")

    def on_export_to_rime(self) -> None:
        from .core import rime_io
        recs = self.ds.all()
        targets = rime_io.export_enabled_to_rime(recs, self._rime_user_dir())
        QMessageBox.information(self, "导出到 Rime", f"已导出 {len(targets)} 个词库（仅启用=是）。")
        self._set_status(f"已导出到 Rime：{len(targets)} 个词库（仅启用=是）")

    def closeEvent(self, event) -> None:
        self.ds.close()
        super().closeEvent(event)


class QComboBox2(QComboBox):  # type: ignore
    """包装 QComboBox 让 currentData 返回规则编号。已废弃，保留兼容。"""
    def __init__(self, rule_names: dict):
        super().__init__()
        for k, v in rule_names.items():
            self.addItem(v, k)


def main() -> None:
    import sys
    app = QApplication(sys.argv)
    # 读取配置中的主题设置
    import os, json
    config_path = "config.json"
    theme_name = "dark"
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                theme_name = cfg.get("theme", "dark")
        except Exception:
            pass
    apply_theme(app, theme_name)
    win = RimeDictApp()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
