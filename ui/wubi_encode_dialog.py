# -*- coding: utf-8 -*-
"""五笔编码生成对话框（P0-1，6 规则对齐真实源）。

交互：输入词组（每行一个）→ 选 6 种编码规则之一（不按词长自动预选）→ 选目标分组/启用/词频
→「预览」看 词组 / 编码 / 权重 / 分组 / 启用 五要素 →「追加到TSV」写入 5 列 tsv；
另提供「追加到dict词典」：按分组首字母路由到 rime_config_dir 下对应 .dict.yaml（仅写 词组/编码/权重 三列）。自由编码仅支持单行。
追加前按 (词组,编码) 查重，避免重复词条（与全局重复定义一致）。

同时作为顶部栏「添加」的统一切口：当顶部五框齐全时，on_add 以 prefill 打开本对话框，
把五框内容抄送进来（编码预填为自由编码，保留用户手动编码），用户确认规则+添加即可；
五框不全时以空对话框进入「原右边栏模式」（手动多行输入）。
"""
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit,
                            QComboBox, QLineEdit, QPushButton, QMessageBox)
from ui.msgbox import info, warning, critical
from PyQt5.QtCore import Qt

from core.wubi_encode import (read_single_char_codes, generate_for_phrase,
                              COMBO_METHODS, RULE_FREE)
from ui.config_dialog import load_config
from core.config import SINGLE_CHAR_FILE
from core.io_tsv import write_tsv

import logging
_log = logging.getLogger(__name__)


def _green(btn):
    """给确认类按钮套绿色 class（需求 e-2：Y/确认语义=绿）；刷新样式使 style.qss 生效。"""
    btn.setProperty("class", "btn-green")
    btn.style().unpolish(btn)
    btn.style().polish(btn)


class WubiEncodeDialog(QDialog):
    def __init__(self, parent=None, model=None, prefill=None, tsv_path=None):
        super().__init__(parent)
        self.setObjectName("WubiEncodeDialog")
        self._model = model
        self._tsv_path = tsv_path
        cfg = load_config()
        single_path = cfg.get("single_char_file") or SINGLE_CHAR_FILE
        self._codes = read_single_char_codes(single_path)
        self.setWindowTitle("⌨️ 五笔编码生成")
        self.resize(460, 420)
        self._build_ui()
        self._populate_groups()
        from ui.config_dialog import apply_dark_title
        apply_dark_title(self, cfg.get("theme", "auto"))
        if prefill:
            self._apply_prefill(prefill)

    def _build_ui(self):
        root = QVBoxLayout(self)

        root.addWidget(QLabel("词组（每行一个；自由编码仅支持单行）："))
        self.editPhrases = QTextEdit()
        self.editPhrases.setPlaceholderText("例如：\n苹果\n香蕉\n微信")
        root.addWidget(self.editPhrases)

        h = QHBoxLayout()
        h.addWidget(QLabel("编码方式："))
        self.comboMethod = QComboBox()
        for key, label in COMBO_METHODS:
            self.comboMethod.addItem(label, key)
        self.comboMethod.currentIndexChanged.connect(self._on_method_changed)
        h.addWidget(self.comboMethod, 1)
        root.addLayout(h)

        self.editFree = QLineEdit()
        self.editFree.setPlaceholderText("自由编码：手动输入编码（小写字母/空格）")
        self.editFree.setEnabled(False)
        root.addWidget(self.editFree)

        hg = QHBoxLayout()
        hg.addWidget(QLabel("目标分组："))
        self.comboGroup = QComboBox()
        self.comboGroup.setEditable(True)
        hg.addWidget(self.comboGroup, 1)
        hg.addWidget(QLabel("启用："))
        self.comboEnable = QComboBox()
        self.comboEnable.addItems(["A", "Y", "D"])
        self.comboEnable.setCurrentText("A")
        hg.addWidget(self.comboEnable)
        hg.addWidget(QLabel("词频："))
        self.editWeight = QLineEdit("1")
        self.editWeight.setMinimumWidth(40)
        hg.addWidget(self.editWeight)
        root.addLayout(hg)

        root.addWidget(QLabel("预览（词组 / 编码 / 权重 / 分组 / 启用）："))
        self.editPreview = QTextEdit()
        self.editPreview.setReadOnly(True)
        root.addWidget(self.editPreview)

        hb = QHBoxLayout()
        self.btnPreview = QPushButton("预览")
        self.btnPreview.clicked.connect(self._on_preview)
        self.btnAppendTsv = QPushButton("追加到TSV")
        self.btnAppendTsv.setDefault(True)
        self.btnAppendTsv.clicked.connect(self._on_append)
        self.btnAppendDict = QPushButton("追加到dict词典")
        self.btnAppendDict.clicked.connect(self._on_append_dict)
        # 需求 e-2：确认类（Y 快捷键等价）按钮统一绿色；删除原「关闭」按钮（N 类），
        # 对话框改由标题栏 X / Esc 关闭，故无「放弃」红色按钮落点（见下方注释）。
        _green(self.btnAppendTsv)
        _green(self.btnAppendDict)
        hb.addWidget(self.btnPreview)
        hb.addWidget(self.btnAppendTsv)
        hb.addWidget(self.btnAppendDict)
        root.addLayout(hb)

    def _apply_prefill(self, prefill):
        """顶部五框齐全时抄送：词组/分组/启用/词频；编码预填为自由编码保留手动码。"""
        phrase = (prefill.get("词组") or "").strip()
        if phrase:
            self.editPhrases.setPlainText(phrase)
        group = (prefill.get("分组") or "").strip()
        if group:
            self.comboGroup.setCurrentText(group)
        enable = (prefill.get("启用") or "").strip()
        if enable:
            self.comboEnable.setCurrentText(enable)
        weight = (prefill.get("权重") or "").strip()
        if weight:
            self.editWeight.setText(weight)
        code = (prefill.get("编码") or "").strip()
        if code:
            # 用户已手填编码：转为自由编码规则，保留该编码，确认即可
            idx = self.comboMethod.findData(RULE_FREE)
            if idx >= 0:
                self.comboMethod.setCurrentIndex(idx)
            self.editFree.setText(code)
        self._on_method_changed(self.comboMethod.currentIndex())

    def _populate_groups(self):
        groups = []
        if self._model is not None:
            groups = self._model.distinct_values(self._model.FIELD_COLS["分组"])
        self.comboGroup.clear()
        self.comboGroup.addItems(groups)
        if "B 青云" in groups:
            self.comboGroup.setCurrentText("B 青云")
        elif groups:
            self.comboGroup.setCurrentText(groups[0])

    def _on_method_changed(self, _):
        self.editFree.setEnabled(self.comboMethod.currentData() == RULE_FREE)

    def _iter_phrases(self):
        for line in self.editPhrases.toPlainText().splitlines():
            p = line.strip()
            if p:
                yield p

    def _on_preview(self):
        rule = self.comboMethod.currentData()
        free = self.editFree.text().strip()
        lines = list(self._iter_phrases())
        if rule == RULE_FREE and len(lines) != 1:
            warning(self, "提示", "自由编码仅支持单行词组。")
            return
        group = self.comboGroup.currentText().strip() or "B 青云"
        enable = self.comboEnable.currentText().strip() or "A"
        weight = self.editWeight.text().strip() or "1"
        out = []
        for p in lines:
            code = generate_for_phrase(p, rule, self._codes,
                                       free if rule == RULE_FREE else "")
            # 预览按五要素完整展示，与实际追加内容一致
            out.append(f"{p}\t{code}\t{weight}\t{group}\t{enable}")
        self.editPreview.setPlainText("\n".join(out))

    def _on_append(self):
        if self._model is None:
            warning(self, "提示", "未加载词库，无法追加。")
            return
        rule = self.comboMethod.currentData()
        free = self.editFree.text().strip()
        lines = list(self._iter_phrases())
        if not lines:
            warning(self, "提示", "请先输入词组。")
            return
        if rule == RULE_FREE:
            if len(lines) != 1:
                warning(self, "提示", "自由编码仅支持单行词组。")
                return
            if not free:
                warning(self, "提示", "自由编码不能为空。")
                return
            if not all(c.isalpha() or c.isspace() for c in free) or "\t" in free:
                warning(self, "提示", "编码只能含小写字母和空格，且不含制表符。")
                return
        group = self.comboGroup.currentText().strip() or "B 青云"
        enable = self.comboEnable.currentText().strip() or "A"
        weight = self.editWeight.text().strip() or "1"
        # 一次性构建已有 (词组,编码) 集合，避免逐条扫全表
        existing = {(r[0], r[1]) for r in self._model.rows()}
        new_fields = []
        for p in lines:
            code = generate_for_phrase(p, rule, self._codes,
                                       free if rule == RULE_FREE else "")
            if not code:
                continue
            if (p, code) in existing:
                continue
            new_fields.append({"词组": p, "编码": code, "权重": weight,
                               "分组": group, "启用": enable})
            existing.add((p, code))
        # 批量追加：全程仅一次全表扫描 + 一次重算（避免逐行全扫导致百万行词库卡死）
        added = self._model.add_rows_fields(new_fields) if new_fields else 0
        if added:
            if self._tsv_path:
                try:
                    self._model._sync_order_to_data()  # 固化（如本会话曾有拖拽重排）
                    ok = write_tsv(self._tsv_path, self._model.rows())
                    if not ok:
                        # write_tsv 内部已重试/记录，这里仅向用户说明，绝不静默退出
                        critical(
                            self, "保存失败",
                            "写入 %s 失败（路径可能被占用、无写入权限或位于受限目录）。" % self._tsv_path)
                        return
                    self._model.mark_clean()
                except Exception as exc:  # noqa: BLE001
                    # 关键：pythonw 下 stderr 被丢弃，任何异常若在此逸出都会「程序直接退出」且无日志。
                    # 改为记录到文件并弹窗提示，保证用户能看到原因、程序不崩。
                    _log.error("追加后写回 TSV 失败：%s", exc, exc_info=True)
                    critical(self, "保存失败", "写入 %s 失败：%s" % (self._tsv_path, exc))
                    return
            try:
                info(self, "完成",
                    f"已追加 {added} 条词组到分组「{group}」并已保存到 TSV：\n{self._tsv_path}")
                if hasattr(self.parent(), "_update_status"):
                    self.parent()._update_status()
                if hasattr(self.parent(), "_refresh_action_buttons"):
                    self.parent()._refresh_action_buttons()
            except Exception as exc:  # noqa: BLE001 - 界面刷新异常也兜底，避免静默退出
                _log.error("追加完成后的界面刷新失败：%s", exc, exc_info=True)
        else:
            info(self, "完成", "没有新词条（均为重复或空编码，已跳过）。")

    def _append_to_dict(self, word, code, weight, group):
        """把一条 (词组, 编码, 权重) 追加到「按分组首字母路由」的 Rime .dict.yaml。

        返回 True=已追加 / None=重复跳过 / False=出错（已弹窗）。
        dict 仅有 词组/编码/权重 三列，无「分组」「启用」列：分组仅用于决定目标文件，启用列丢弃。
        """
        import os
        from core.rime_export import GROUP_TARGETS
        from core.rime_dict_model import RimeDictModel
        rime_dir = load_config().get("rime_config_dir", "")
        if not rime_dir:
            warning(self, "提示",
                               "未配置 Rime 配置文件夹（rime_config_dir）。\n请先在『配置』中指定。")
            return False
        # 取分组首字母路由到对应 dict 文件（与导出 GROUP_TARGETS 一致）
        letter = (group or "B 词库")[:1].upper()
        target = GROUP_TARGETS.get(letter) or GROUP_TARGETS["B"]
        rel_path, dict_name = target
        path = os.path.join(rime_dir, rel_path)
        model = RimeDictModel()
        if os.path.exists(path):
            try:
                model.load(path)
            except Exception as exc:  # noqa: BLE001
                critical(self, "错误", "读取 %s 失败：%s" % (path, exc))
                return False
        else:
            # 目标 dict 文件不存在：用最简 Rime 头新建（save 时写出）
            model._path = path
            model._header_lines = ["---", "name: %s" % dict_name,
                                   "version: \"1.0\"", "sort: by_weight", "..."]
            model._all_data = []
            model._order = []
            model._groups = []
            model._row_group = []
            model._group_filter = ""
            model._last_fields = {}
            model.mark_clean()
        # 查重：同 (词组,编码) 不重复追加
        existing = {(r[0], r[1]) for r in model._all_data}
        if (word, code) in existing:
            return None
        model.add_row_fields({"词组": word, "编码": code, "权重": weight})
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            model.save(path)
        except Exception as exc:  # noqa: BLE001
            critical(self, "错误", "写入 %s 失败：%s" % (path, exc))
            return False
        return True

    def _on_append_dict(self):
        """追加到 dict 词典：按分组首字母路由到对应 .dict.yaml，写入 词组/编码/权重 三列。"""
        rule = self.comboMethod.currentData()
        free = self.editFree.text().strip()
        lines = list(self._iter_phrases())
        if not lines:
            warning(self, "提示", "请先输入词组。")
            return
        if rule == RULE_FREE:
            if len(lines) != 1:
                warning(self, "提示", "自由编码仅支持单行词组。")
                return
            if not free:
                warning(self, "提示", "自由编码不能为空。")
                return
        group = self.comboGroup.currentText().strip() or "B 青云"
        weight = self.editWeight.text().strip() or "1"
        added = 0
        skipped = 0
        for p in lines:
            code = generate_for_phrase(p, rule, self._codes,
                                       free if rule == RULE_FREE else "")
            if not code:
                continue
            res = self._append_to_dict(p, code, weight, group)
            if res is True:
                added += 1
            elif res is None:
                skipped += 1
            else:  # False：已弹错误框
                return
        if added:
            msg = "已追加 %d 条到 dict 词典（分组『%s』→ 对应 .dict.yaml）。" % (added, group)
            if skipped:
                msg += "\n%d 条因重复跳过。" % skipped
            info(self, "完成", msg)
        elif skipped:
            info(self, "完成", "没有新词条（均为重复，已跳过）。")
