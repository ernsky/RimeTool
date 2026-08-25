# -*- coding: utf-8 -*-
"""工作区主窗口（三栏 + 顶部三模块）：

顶部：
  第一部分 录入：词组/编码/权重/分组/启用 五框（分组、启用为下拉）。
  第二部分 操作（顺序）：搜索 / 添加 / 删除 / 保存 / 移动到... / 部署 / 配置。
    其中 移动到 / 删除 仅 tsv 且选中行≥1 时启用；删除需确认。
三栏：
  左：文件树（TSV 文件组 + Dict 文件组）。
  中：表格（tsv 可多选[ExtendedSelection]；选中行→顶部五框；编辑经五框→保存写回）。
  右：功能按钮区（本期挂起，仅占位）。
状态栏：总 / 显 / 选 ｜ 文件名。

中栏对 tsv 复用 DictModel（可读写、ExtendedSelection），对 dict.yaml 用 RimeDictModel（只读）。
所有增改都经顶部五框 → 模型字段接口 → 保存写回，符合「中栏仅预览只读」（dict）或
「编辑经五框→写回」（tsv）。
"""
import os
import logging

_log = logging.getLogger(__name__)

from ui.ui_workspace_window import Ui_WorkspaceWindow
from ui.drag_controller import DragController
from ui.confirm import ConfirmBox
from ui.msgbox import apply_box_style
from PyQt5.QtCore import QModelIndex, Qt, QTimer, QSettings, QItemSelectionModel, QItemSelection, QRect
from PyQt5.QtGui import QFont, QPalette, QColor, QPen, QFontMetrics
from PyQt5.QtWidgets import (
    QMainWindow, QMessageBox, QTreeWidgetItem, QHeaderView, QLineEdit, QApplication,
    QLabel, QWidget, QHBoxLayout, QSizePolicy, QShortcut, QComboBox, QPushButton,
    QFileDialog, QDialog, QButtonGroup, QRadioButton, QVBoxLayout, QGroupBox,
    QAbstractItemView, QStyledItemDelegate, QStyle,
)
from ui.msgbox import info, warning, critical

from core.dict_model import DictModel
from core.rime_dict_model import RimeDictModel
from core.io_tsv import LoadThread, write_tsv
from core import backup as backup_mod
from ui.config_dialog import ConfigDialog, load_config, save_config
from core.config import theme_dict, get_active_theme_name

# 左栏树节点类型（存于 Qt.UserRole+1）
ROLE_TYPE = Qt.UserRole + 1
ROLE_PATH = Qt.UserRole


def _apply_btn_class(btn, cls):
    """设置按钮的动态 class 属性并刷新样式（让 style.qss 的 [class=...] 选择器生效）。"""
    btn.setProperty("class", cls)
    btn.style().unpolish(btn)
    btn.style().polish(btn)


class ComboDelegate(QStyledItemDelegate):
    """分组列/启用列单元格下拉编辑器（tsv 专属）。

    双击这两列的单元格即弹出下拉：选项为该列去重值（来自 DictModel.distinct_values），
    且可手填新值（沿用顶栏「完全自由手填」语义：NoInsert，手填不污染候选列表）。
    写回走模型 setData（标脏 + 刷新单元格），与顶栏编辑路径一致。
    其余列不可编辑（DictModel.flags 仅 分组/启用 返回 ItemIsEditable），不会触发本编辑器。
    """

    def createEditor(self, parent, option, index):
        combo = QComboBox(parent)
        combo.setEditable(True)
        combo.setInsertPolicy(QComboBox.NoInsert)
        combo.setMinimumWidth(max(option.rect.width(), 140))  # 分组名较长时弹层可读性
        model = index.model()
        cur = index.data(Qt.EditRole) or ""
        vals = []
        if isinstance(model, DictModel):
            vals = list(model.distinct_values(index.column()))
        if cur and cur not in vals:
            vals = [cur] + vals   # 当前值（可能不在去重列表，如空变体/新值）置顶
        combo.addItems(vals)
        if cur:
            combo.setCurrentText(cur)
        else:
            combo.setCurrentIndex(-1)
        return combo

    def setModelData(self, editor, model, index):
        text = (editor.currentText() or "").strip()
        model.setData(index, text, Qt.EditRole)

    def setEditorData(self, editor, index):
        # createEditor 已按当前值预选；保持默认即可
        pass

    def _grid_color(self):
        """读取当前主题的内部网格色（与 style.qss 的 $border_light 同源）。"""
        try:
            return QColor(theme_dict(get_active_theme_name())["border_light"])
        except Exception:
            return QColor("#e5e7eb")

    def paint(self, painter, option, index):
        # 去掉焦点框(PE_FrameFocusRect)：默认样式会在聚焦/选中/悬停单元格内预留约 2px
        # 左边距给焦点框，导致文字相对单元格背景"向右缩进"。我们用 delegate 自己重画文字，
        # 以固定内边距绘制，从根本上消除位移；hover/选中 只换背景色，文字位置恒定。
        option.state &= ~QStyle.State_HasFocus
        # 先让基类画一次（背景、交替行、选中/hover 底色、编辑器预览等）
        super().paint(painter, option, index)

        model = index.model()
        if model is None or model.columnCount() == 0 or model.rowCount() == 0:
            return

        theme = theme_dict(get_active_theme_name())
        view = option.widget
        alt = view.alternatingRowColors() if view is not None else False
        if option.state & QStyle.State_Selected:
            bg, fg = QColor(theme["selected"]), QColor(theme["selected_text"])
        elif option.state & QStyle.State_MouseOver:
            bg, fg = QColor(theme["row_hover"]), QColor(theme["text_primary"])
        elif alt and (index.row() % 2 == 1):
            bg, fg = QColor(theme["row_odd"]), QColor(theme["text_primary"])
        else:
            bg, fg = QColor(theme["panel"]), QColor(theme["text_primary"])

        r = option.rect
        # 用背景色回填整格，盖掉基类在"焦点框留白"处画的旧(右移)文字，消除位移残影
        painter.save()
        painter.fillRect(r, bg)
        # 以固定内边距(左右 8px、上下 3px，与 QTableView::item padding 一致)重画文字，
        # 不再受样式焦点框留白影响 -> hover/选中 时文字位置恒定，只换背景色
        text = index.data(Qt.DisplayRole)
        text = "" if text is None else str(text)
        painter.setFont(option.font)
        painter.setPen(fg)
        fm = QFontMetrics(painter.font())
        elided = fm.elidedText(text, Qt.ElideRight, max(1, r.width() - 16))
        painter.drawText(r.adjusted(8, 3, -8, -3),
                         Qt.AlignLeft | Qt.AlignVCenter, elided)
        painter.restore()

        # 内部网格（列间竖线 + 行间横线，跳过最外边框），与列头竖线对齐
        last_col = model.columnCount() - 1
        last_row = model.rowCount() - 1
        # 最右下角单元格：整格跳过，避免误画出最右/最下外边框
        if index.column() >= last_col and index.row() >= last_row:
            return
        pen = QPen(self._grid_color())
        pen.setWidth(1)
        painter.save()
        painter.setPen(pen)
        # 非最后一列：画右侧内部竖线（列间分隔）
        if index.column() < last_col:
            # 列头竖线由 QHeaderView::section 的 border-right 绘制，位置在该列分节的"右边界"
            # (=左边界+列宽，即下一列起始位置)。delegate 若画在 r.right()(单元格最后一像素)会偏左 1px，
            # 导致"列头竖线"与"表格竖线"不在同一 x。故 +1 画到分节右边界，与列头对齐。
            x = r.right() + 1
            painter.drawLine(x, r.top(), x, r.bottom())
        # 非最后一行：画底部内部横线（行间分隔）
        if index.row() < last_row:
            y = r.bottom()
            painter.drawLine(r.left(), y, r.right(), y)
        painter.restore()


class WorkspaceWindow(QMainWindow, Ui_WorkspaceWindow):
    def __init__(self):
        super().__init__()
        # 注意：UI 已从 Qt Designer 的 workspace_window.ui 用 pyuic5 预编译为
        # ui/ui_workspace_window.py（Ui_WorkspaceWindow）。这里通过「多重继承」
        # 直接 self.setupUi(self)，控件作为 self（QMainWindow）的属性挂载，
        # 完全等价于原 uic.loadUi(ui_path, self)；且运行时不再读取 .ui 文件，
        # 打包成 exe 后无需随附 .ui。
        self.setupUi(self)

        self._config = load_config()
        self._model = None
        self._current_path = ""
        self._current_kind = ""      # 'tsv' | 'dict'
        self._thread = None
        self._filter_thread = None   # 后台筛选线程（P0-1 生命周期管理）

        # 五框联动状态
        self._updating = False       # 程序性填值期间抑制信号回环
        self._filter_timer = QTimer(self)
        self._filter_timer.setSingleShot(True)
        self._filter_timer.timeout.connect(self._apply_filter_now)
        self._field_widgets = {
            "词组": self.editWord, "编码": self.editCode, "权重": self.editWeight,
            "分组": self.comboGroup, "启用": self.comboEnable,
        }
        # 筛选快照：记录「筛选态」时五框的值（含完整筛选条件）。编辑态（选中行）改框不更新它；
        # 保存后把五框复位成它，使中间栏回到「最初筛选结果」。
        self._filter_state = {}
        # 后台筛选线程（大词库把 _rebuild_order 的全表扫描下沉后台，主线程不再冻结）。
        # _filter_token 为「代号」：每次发起新筛选自增，过期结果（token 不匹配）直接丢弃，
        # 避免与增删/移动/合并/排序等同步重建竞争写 _order。
        self._filter_token = 0
        self._filter_thread = None
        self._splitter_restored = False   # 是否已从 QSettings 恢复分隔条状态（恢复后跳过固定宽覆盖）

        self._build_footer()         # 状态栏 widgets：总 / 显 / 选 ｜ 文件名
        self._bind_ui()
        self._apply_placeholder_style()  # 五框占位提示（词组/编码/…）全空时灰色，避免黑字看不清
        self._restore_geometry()     # 有记忆则覆盖 _bind_ui 的默认尺寸（须在 _apply_side_widths 之前）
        self._apply_side_widths()    # 用「最终」窗口宽重算左右栏固定宽
        self._build_tree()
        self._build_feature_buttons()  # 右侧新增 4 个功能模块按钮（须在 _connect_signals 之前创建，供信号绑定引用）
        self._connect_signals()
        self._apply_btn_classes()    # 给按钮套 [class=...] 属性，触发 QSS 渲染
        self._apply_right_panel_style()  # 右侧功能栏 UI（缩短20%/居中/字体放大）
        self._build_sort_controls()   # 顶部「组内排序」控件（↑/↓ + 批量重排 + 归一化）
        self._reorder_top_prefix()    # 把 配置/部署/保存 移到五框之前（用户要求）
        self._set_tooltips()          # 给所有按钮加操作提示（参照顶部「应用」按钮风格）
        self._install_drag_drop()     # 拖拽选中行到左侧分组树 = 移动（增强）
        self._refresh_action_buttons()   # 初始禁用，等模型/选中行就绪
        self._auto_load_first()
        self._apply_fixed_fonts()         # 锁定状态栏 + 五框为 12pt（构造期；main.apply_theme 后会再调一次确保最终生效）

    # ---------- 绑定 / 信号 ----------
    def _bind_ui(self):
        # 三栏分隔竖线「到顶」：去掉主布局顶部留白与控件间距，使分隔条紧贴顶部工具条下边线
        self.mainLayout.setContentsMargins(8, 0, 8, 8)
        self.mainLayout.setSpacing(0)
        # ① 窗口默认宽 +20%（基准 .ui 设计宽 1200 → 显式 1440）。
        #    注意：这只是「首次/无记忆」时的默认值；若 QSettings 里存过上次几何，
        #    会在 __init__ 末尾的 _restore_geometry() 覆盖此默认（见下方调用）。
        BASE_W = 1200
        self.resize(int(BASE_W * 1.2), self.height())

        self.tableView.verticalHeader().setDefaultSectionSize(22)
        hdr = self.tableView.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.Interactive)
        hdr.setStretchLastSection(False)   # 列宽由 _fit_columns_to_view 按比例铺满，避免横向滚动条
        # req：列宽锁定为比例默认宽，超长词组等内容一律截断显示（…），绝不被内容撑大；仅手动拖拽可改宽
        self.tableView.setTextElideMode(Qt.ElideRight)
        hdr.sortIndicatorChanged.connect(self._on_sort_changed)   # 表头排序持久化（#90）
        # 列宽按视口等比铺满（见 _fit_columns_to_view，表格尺寸变化时实时重算）；
        # 横向滚动条设为「按需」作为兜底：正常情况下列宽恰好铺满不出现，
        # 若极端窄窗（列最小宽之和 > 视口）也允许横向滚动而非直接裁掉末列（避免末列永久不可见）。
        self.tableView.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.tableView.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # 分组列/启用列：双击单元格弹下拉编辑器（仅这两列可编辑，见 DictModel.flags）；
        # 单击仍选中并回填顶栏五框，不触发编辑，避免与「顶栏录入」冲突。
        self.tableView.setEditTriggers(
            QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed)
        self._combo_delegate = ComboDelegate(self.tableView)
        # 全表统一使用本 delegate：既提供分组/启用列的下拉编辑，
        # 又在所有单元格绘制「仅内部」网格（跳过最左/最右/最上/最下外边框）。
        self.tableView.setItemDelegate(self._combo_delegate)

        # 顶部固定高度、三栏占满剩余空间
        self.mainLayout.setStretch(0, 0)
        self.mainLayout.setStretch(1, 1)

        # 三栏：左/右按默认宽度固定，仅中栏随窗口加宽而拉伸（具体像素宽见 _apply_side_widths）
        self.splitter.setStretchFactor(0, 0)   # 左固定
        self.splitter.setStretchFactor(1, 1)   # 中拉伸
        self.splitter.setStretchFactor(2, 0)   # 右固定

        # 中栏内部：分组列表（左）固定宽、表格（右）拉伸；tsv 模式隐藏分组面板
        self.midSplitter.setStretchFactor(0, 0)   # 分组列表固定
        self.midSplitter.setStretchFactor(1, 1)   # 表格拉伸
        # 分隔条强制 1px：CSS 的 handle-width 会被 Windows 样式忽略，必须用 setHandleWidth 才生效
        self.splitter.setHandleWidth(1)
        self.midSplitter.setHandleWidth(1)
        self.groupPanel.setFixedWidth(200)
        # 分组列表（QListWidget）同样去掉横/竖滚动条：滚轮仍可用、列表内容可卷动
        self.groupListWidget.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.groupListWidget.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.groupPanel.hide()   # 初始隐藏，加载 dict 时再显示

        # 顶部：五框按 8:5:4:7:2 瓜分「按钮之外」的剩余宽度（req5：分组 10→7，腾出 3 份按 2:1 给编码/权重）；输入布局整体随窗口扩展
        self.inputLayout.setStretch(0, 8)   # 词组（8 字）
        self.inputLayout.setStretch(1, 5)   # 编码（5 字）：分组缩出的 2 份
        self.inputLayout.setStretch(2, 4)   # 权重（4 字）：分组缩出的 1 份
        self.inputLayout.setStretch(3, 7)   # 分组（7 字）：10→7
        self.inputLayout.setStretch(4, 2)   # 启用（2 字）
        self.topLayout.setStretch(0, 1)   # 输入布局扩展
        self.topLayout.setStretch(1, 0)   # 分隔线
        self.topLayout.setStretch(2, 0)   # 操作按钮段（固定）
        self.topLayout.setStretch(3, 0)   # 分隔线
        self.topLayout.setStretch(4, 0)   # 配置按钮段（固定）

        # 五框最小宽度下限（防过窄），比例仍由上方 stretch 主导
        self.editWord.setMinimumWidth(60)
        self.editCode.setMinimumWidth(40)
        self.editWeight.setMinimumWidth(40)
        self.comboGroup.setMinimumWidth(70)
        self.comboEnable.setMinimumWidth(30)
        # req5(a)：分组下拉列表的滚动条设为不显示（分组很多时仍可滚轮/方向键翻看）
        self.comboGroup.view().setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # req2：分组/启用两下拉改为「完全自由手填」——可编辑、可直接打字新增值，
        # 不再锁定为既有 distinct 值；下拉项仅作候选提示（由 _refresh_combos 填充）。
        for _cb, _ph in ((self.comboGroup, "分组"), (self.comboEnable, "启用")):
            _cb.setEditable(True)                        # 可直接手填新值
            _cb.setInsertPolicy(QComboBox.NoInsert)      # 手填的新值不污染下拉候选列表；下拉仍可正常选项
            _le = _cb.lineEdit()
            _le.setPlaceholderText(_ph)
            # 不硬编码占位符调色板：交由 style.qss 的 `QLineEdit::placeholder { color: $text_tertiary }`
            # 统一驱动（深=#57575a / 浅=#9ca3af），避免覆盖暗色主题下「五框提示文字 #57575a」的规范，
            # 且主题切换时随 setStyleSheet 自动刷新。

        # 按钮：不再固定宽度、不再 *0.7 缩窄；交由 QSS padding(2px 8px) + 文字自然决定宽度，
        # 剩余空间全部留给五框（actionLayout 固定 stretch，按钮不被挤压）。长文字按钮（移动到...）也按内容显示。

    def _apply_btn_classes(self):
        """给按钮套动态 class 属性，触发 QSS 的 [class=...] 选择器渲染。
        配色：搜索/添加=roseo 主操作(btn-main)，删除=红(btn-red)，
        移动到=蓝(btn-blue)，保存/部署=中性灰(btn-primary #555)，配置=透明(btn-ghost)。"""
        _apply_btn_class(self.btnSearch, "btn-search")
        _apply_btn_class(self.btnAdd, "btn-main")
        # 与「保存」合一：隐藏独立添加按钮，「保存录入」承担录入提交（齐全→存 tsv / 缺要素→弹编码窗口）
        self.btnAdd.setVisible(False)
        _apply_btn_class(self.btnDelete, "btn-red")
        _apply_btn_class(self.btnSave, "btn-primary")
        _apply_btn_class(self.btnDeploy, "btn-primary")
        _apply_btn_class(self.btnConfig, "btn-ghost")
        # 右侧功能按钮统一 btn-ghost（与下方重复词条按钮一致），不再用玫红主操作色
        _apply_btn_class(self.btnExportRime, "btn-ghost")
        _apply_btn_class(self.btnBatchWeight, "btn-ghost")
        _apply_btn_class(self.btnVoiceGap, "btn-ghost")
        _apply_btn_class(self.btnMultiCode, "btn-ghost")
        _apply_btn_class(self.btnSaveSingle, "btn-ghost")

    def _apply_right_panel_style(self):
        """右侧功能栏 UI（按用户最新要求）：
        - 6 个按钮顶部居中排列（水平居中、垂直顶对齐，AlignTop | AlignHCenter）；
        - 全部统一宽度，锁定为「最宽按钮内容宽 + 两边各 10px 留白」（=237px，覆盖「批量修改TSV权重」217px
          再加 20px 呼吸空间，保证所有标题完整不裁切）；setFixedWidth 同时锁 min/max，整列严格等宽；
        - 按钮标题左对齐（text-align:left），保留 btn-ghost 配色，仅改对齐；标题文字与现状一致不动；
        - 字号沿用全局应用字体（main.py 已设为 base+2=14pt），此处不单独 setFont，避免叠加放大。
          覆盖「导出到Rime/批量修改TSV权重/语音词组查漏」与「高亮/下一处/合并重复」两组。"""
        self.rightLayout.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        all_btns = list(getattr(self, "_feature_buttons", [])) + list(getattr(self, "_dup_buttons", []))
        if all_btns:
            # 锁定宽度 = 最宽按钮的自然内容宽 + 两边各 10px 留白（具体像素写死，不写公式）
            max_w = max(b.minimumSizeHint().width() for b in all_btns)
            w0 = max_w + 20
            for b in all_btns:
                b.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
                b.setFixedWidth(w0)            # 同时锁 min/max，整列严格等宽
                b.setStyleSheet("text-align: left;")   # 标题左对齐（不动 btn-ghost 配色，仅改对齐）
        # 字数筛选 6 钮：宽度按功能按钮宽 w0 反推，使「6 钮 + 间隔」恰好铺满 w0（无溢出），
        # 容器同宽 → 「无」贴左、「多」贴右，与功能按钮左右边精确对齐
        if hasattr(self, "_char_buttons") and self._char_buttons:
            _n = len(self._char_buttons)
            _gap = 2
            _char_w = max(34, (w0 - _gap * (_n - 1)) // _n)
            for _, b in self._char_buttons:
                b.setFixedWidth(_char_w)
        if hasattr(self, "_char_filter_widget"):
            self._char_filter_widget.setFixedWidth(w0)   # 字数筛选行与功能按钮同宽 → 无贴左、多贴右对齐

    def _reorder_top_prefix(self):
        """把 配置/部署/保存 三个按钮移到五框（inputLayout）之前（用户要求）。

        这三个按钮当前都在 .ui 的 actionLayout 中；从中抽出，组成一个固定宽前缀段，
        插入到 topLayout 最前（index 0），使顶部顺序变为：
        [配置][部署][保存] [五框] | [搜索][清除][添加][删除][移动到...][↑][↓][组内重排▾][应用]…"""
        prefix = QHBoxLayout()
        prefix.setSpacing(6)
        prefix.setContentsMargins(0, 0, 0, 0)
        for b in (self.btnConfig, self.btnDeploy, self.btnSave):
            self.actionLayout.removeWidget(b)
            prefix.addWidget(b)
        self.topLayout.insertLayout(0, prefix)
        # 前缀段固定宽、五框段(index 1)仍随窗口扩展（沿用 _bind_ui 的 stretch 语义）
        self.topLayout.setStretch(0, 0)
        self.topLayout.setStretch(1, 1)

    def _set_tooltips(self):
        """给所有按钮加操作提示（参照顶部「应用」按钮风格：一句话说明作用）。

        顶部操作按钮、右侧功能按钮、组内排序控件统一补 tooltip；排序控件里已有 tooltip
        的（↑/↓/应用/交换权重/阶梯重排）保持原样，这里只补缺失项。"""
        # 顶部操作按钮（.ui 中定义）
        self.btnSearch.setToolTip("按顶部五框条件筛选中间列表（词组/编码/词频子串匹配，编码不区分大小写）")
        self.btnAdd.setToolTip("新增词条：五框齐全时弹五笔编码对话框（编码预填为自由编码），否则空对话框手动输入；新增后需保存才落盘")
        self.btnDelete.setToolTip("删除选中行（tsv 可多选，删除前确认；确认后直接写入文件）")
        self.btnSave.setToolTip("录入提交（保存与添加合一）：五框齐全→写 tsv（选中行则更新该行、未选中则追加新行、多选批量改分组/启用）；缺任一要素→弹编码窗口补全并落盘；全程仅写 tsv")
        self.btnDeploy.setToolTip("保存并请求 Rime 部署（部署钩子预留，等价于先点保存）")
        self.btnConfig.setToolTip("打开配置对话框：指定 tsv 文件、Rime 配置文件夹、外观、语音文件、输出文件夹、单字编码文件、备份恢复")
        # 右侧功能按钮（代码创建）
        self.btnExportRime.setToolTip("按分组把当前 TSV 导出分发到 Rime 词典并触发重新部署（写前自动备份 .bak.gz）")
        self.btnBatchWeight.setToolTip("按码表匹配替换第 3 列权重、自动新增缺失词条，写回主 TSV（不触发部署；写前自动备份）")
        self.btnNewEncode.setToolTip("新建编码：弹出五笔编码对话框新增词条（原顶部「添加」逻辑迁至此处）；新增后需点保存才落盘")
        self.btnVoiceGap.setToolTip("语音词组查漏：对比 SayIt 语音 JSON 与基准 TSV，找出语音有但词库缺的词组，结果写入输出文件夹")
        self.btnDupHighlight.setToolTip("筛选重复项（词组+编码 完全相同）：仅保留重复行，并把相同的聚拢在一起")
        self.btnDupNext.setToolTip("从选中行之后定位下一个重复词条并滚动到它，到底循环回顶部")
        self.btnDupMerge.setToolTip("合并重复词条（key=词组+编码）：保留每组首行、词频取最大、删除冗余行")
        # 第 7 个按钮：五要素不全筛选（tsv 专属）
        self.btnIncomplete.setToolTip("开/关『五要素不全』筛选：词组/编码/权重/分组/启用 任一为空即筛出（仅 tsv 5 列模式）")
        # 功能1：字数筛选（无/一/二/三/四/多）
        if hasattr(self, "_char_buttons"):
            for val, b in self._char_buttons:
                desc = "全部（清除本筛选）" if val == -1 else ("≥5 字" if val == 5 else "%d 字" % val)
                b.setToolTip("字数筛选：仅显示词组列 %s 的行" % desc)
        # 功能2：一词多码
        self.btnMultiCode.setToolTip("开/关『一词多码』筛选：仅显示同一词组存在多个不同编码的行")
        # 功能3：保存为单一码表
        self.btnSaveSingle.setToolTip("把启用=A 的行按分组首字母拆分导出：E 开头→English.dict.yaml，其它→wubi.dict.yaml（弹框选保存位置）")

    def _build_feature_buttons(self):
        """右侧功能栏：程序化新增功能模块按钮。

        布局顺序（自上而下，每项为右侧栏一行；字数筛选为横向单字按钮组，占一行）：
          1 导出到Rime（.ui）
          2 批量修改TSV权重（.ui）
          3 🎙️ 语音词组查漏
          4 字数筛选（无/一/二/三/四/多 横排 6 钮）
          5 一词多码（可勾选）
          6 保存为单一码表
          7 ⚠ 要素不全（可勾选，原第4行顺延）
          8-10 重复词条（高亮/下一处/合并）
        """
        # 已有按钮（.ui）：导出到Rime、批量修改TSV权重
        # 新建编码：原顶部「添加」合一后迁至右侧栏；复用原添加逻辑（弹五笔编码对话框新增词条）
        self.btnNewEncode = QPushButton("➕ 新建编码")
        self.btnNewEncode.clicked.connect(self.on_add)
        self.btnVoiceGap = QPushButton("🎙️ 语音词组查漏")

        # 功能1：字数筛选（第4行）—— 横向单字按钮组（无/一/二/三/四/多）
        # 映射：无→-1(关/显示全部)；一~四→1~4 精确；多→5(≥5 字)
        # 对齐：按钮间插入可伸缩间隔，使「无」贴左、「多」贴右，与下方功能按钮左右边对齐
        self._char_buttons = []
        hbox = QHBoxLayout()
        hbox.setSpacing(2)
        hbox.setContentsMargins(0, 0, 0, 0)
        for idx, (label, val) in enumerate((("无", -1), ("一", 1), ("二", 2), ("三", 3), ("四", 4), ("多", 5))):
            b = QPushButton(label)
            # 宽度在 _apply_right_panel_style 中按功能按钮宽 w0 反推，保证 6 钮+间隔恰好铺满、无溢出且字全显
            _apply_btn_class(b, "btn-ghost")
            b.clicked.connect(lambda _=None, v=val: self.on_char_count_clicked(v))
            self._char_buttons.append((val, b))
            hbox.addWidget(b)
            if idx != 5:                # 末钮「多」后不再加间隔 → 多贴右、无贴左
                hbox.addStretch(1)
        self._char_filter_widget = QWidget()
        self._char_filter_widget.setLayout(hbox)
        self._char_active = -1          # 当前激活的字数筛选值（-1=无）

        # 功能2：一词多码（第5行，可勾选）
        self.btnMultiCode = QPushButton("🔢 一词多码")
        self.btnMultiCode.setCheckable(True)
        # 功能3：保存为单一码表（第6行）
        self.btnSaveSingle = QPushButton("💾 保存为单一码表")

        # 五要素不全（第7行，可勾选，原第4行顺延）
        self.btnIncomplete = QPushButton("⚠ 要素不全")
        self.btnIncomplete.setCheckable(True)

        # 全量功能按钮列表（供 _apply_btn_classes / _apply_right_panel_style 统一处理等宽样式）。
        # 注：字数筛选的 6 个单字按钮走独立布局，不加入此列表（避免被强制拉宽）。
        self._feature_buttons = [
            self.btnNewEncode,
            self.btnExportRime, self.btnBatchWeight, self.btnVoiceGap,
            self.btnMultiCode, self.btnSaveSingle, self.btnIncomplete,
        ]
        # 按目标垂直顺序加入右侧栏（每项占一行）
        self.rightLayout.addWidget(self.btnNewEncode)
        self.rightLayout.addWidget(self.btnExportRime)
        self.rightLayout.addWidget(self.btnBatchWeight)
        self.rightLayout.addWidget(self.btnVoiceGap)
        self.rightLayout.addWidget(self._char_filter_widget)
        self.rightLayout.addWidget(self.btnMultiCode)
        self.rightLayout.addWidget(self.btnSaveSingle)
        self.rightLayout.addWidget(self.btnIncomplete)

        # 重复词条处理（P0-2：重复定义=词组+编码 完全相同）：高亮开关 + 跳转下一处 + 合并
        self.btnDupHighlight = QPushButton("🔍 重复项筛选")
        self.btnDupHighlight.setCheckable(True)
        self.btnDupNext = QPushButton("⏭ 下一处重复")
        self.btnDupMerge = QPushButton("🔀 合并重复")
        self._dup_buttons = [self.btnDupHighlight, self.btnDupNext, self.btnDupMerge]
        for b in self._dup_buttons:
            self.rightLayout.addWidget(b)

        _apply_btn_class(self.btnIncomplete, "btn-ghost")
        _apply_btn_class(self.btnMultiCode, "btn-ghost")
        _apply_btn_class(self.btnSaveSingle, "btn-ghost")
        _apply_btn_class(self.btnDupHighlight, "btn-ghost")
        _apply_btn_class(self.btnDupNext, "btn-ghost")
        _apply_btn_class(self.btnDupMerge, "btn-ghost")
        self._dup_on = False
        self._incomplete_on = False
        self._multi_code_on = False

    def _flash_save_success(self):
        """保存成功后短暂把保存按钮切到绿色背景状态样式（不改文字，保持「保存」），1.5s 后恢复。"""
        _apply_btn_class(self.btnSave, "btn-green")
        QTimer.singleShot(1500, self._reset_save_btn)

    def _reset_save_btn(self):
        _apply_btn_class(self.btnSave, "btn-primary")

    def _build_footer(self):
        """构造状态栏：左侧放当前文件路径（超长中间省略，绝不挤占右侧数字）；
        右侧放 总/显/选 数字（永久 widget，不被路径覆盖）。两者分离、不重叠。"""
        sb = self.statusBar()
        sb.setSizeGripEnabled(False)
        # 文件名：左侧普通 widget（只读 QLineEdit，原生裁剪超长文本，绝不挤占/覆盖右侧数字）
        self._lblFile = QLineEdit("")
        self._lblFile.setReadOnly(True)
        self._lblFile.setFrame(False)
        self._lblFile.setProperty("class", "footer-name")
        self._lblFile.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        sb.addWidget(self._lblFile)
        # 数字：右侧永久 widget（不被路径挤占）
        self._footerWidget = QWidget()
        self._footerLayout = QHBoxLayout(self._footerWidget)
        self._footerLayout.setContentsMargins(8, 0, 8, 0)
        self._footerLayout.setSpacing(0)
        self._lblTotal = QLabel("总")
        self._lblTotalNum = QLabel("0")
        self._lblTotalNum.setProperty("class", "footer-num")
        self._lblShown = QLabel("· 显")
        self._lblShownNum = QLabel("0")
        self._lblShownNum.setProperty("class", "footer-num")
        self._lblSel = QLabel("· 选")
        self._lblSelNum = QLabel("0")
        self._lblSelNum.setProperty("class", "footer-num")
        for w in (self._lblTotal, self._lblTotalNum,
                  self._lblShown, self._lblShownNum,
                  self._lblSel, self._lblSelNum):
            self._footerLayout.addWidget(w)
        sb.addPermanentWidget(self._footerWidget)

    def _apply_fixed_fonts(self):
        """把状态栏与顶部五框的字号分别锁定（控件级 stylesheet，优先级最高）。

        - 状态栏整条（文件名框 + 总/显/选 数字）= 8pt（用户要求状态栏更小、与五框区分）。
        - 顶部五框（词组/编码/权重/分组/启用）= 10pt（保持原定）。
        用「setFont + widget 级 setStyleSheet」双保险：仅 setFont 在真实屏幕
        会被 apply_theme 二次 setStyleSheet 的 repolish 覆盖回全局 14pt（离屏 fontMetrics
        测量还会假报已生效），故必须给每个控件设自身 stylesheet 以压住一切继承。
        时序：main.py 在 apply_theme(二次 setStyleSheet) 之后再调一次本方法。"""
        _FONT_FAMILY = "Microsoft YaHei"   # 明确指定微软雅黑，避免继承系统默认宋体
        _fixed_sb = QFont(_FONT_FAMILY, 7)    # 状态栏 7pt（2026-08-23 整体小一号：原 8 → 7）
        _locked_sb = "font-size: 7pt; font-family: 'Microsoft YaHei';"
        _fixed_box = QFont(_FONT_FAMILY, 9)  # 五框 9pt（整体小一号：原 10 → 9）
        _locked_box = "font-size: 9pt; font-family: 'Microsoft YaHei';"
        # 状态栏：文件名框 + 总/显/选 数字
        if hasattr(self, "_lblFile"):
            self._lblFile.setFont(_fixed_sb)
            self._lblFile.setStyleSheet(_locked_sb)
        for w in (getattr(self, "_lblTotal", None), getattr(self, "_lblTotalNum", None),
                  getattr(self, "_lblShown", None), getattr(self, "_lblShownNum", None),
                  getattr(self, "_lblSel", None), getattr(self, "_lblSelNum", None)):
            if w is not None:
                w.setFont(_fixed_sb)
                w.setStyleSheet(_locked_sb)
        # 顶部五框：词组/编码/权重/分组/启用（保持 10pt，与状态栏区分）
        for w in (self.editWord, self.editCode, self.editWeight,
                  self.comboGroup, self.comboEnable):
            w.setFont(_fixed_box)
            w.setStyleSheet(_locked_box)

    def _apply_placeholder_style(self):
        """五框占位提示（词组/编码/权重/分组/启用）在全空时用灰色，避免黑字与白底对比过弱看不清。"""
        pal = self.editWord.palette()
        pal.setColor(QPalette.PlaceholderText, QColor(150, 150, 150))
        for w in (self.editWord, self.editCode, self.editWeight,
                  self.comboGroup, self.comboEnable):
            w.setPalette(pal)

    def _refresh_action_buttons(self):
        """删除 / 交换权重 按钮使能条件。"""
        kind_ok = self._current_kind == "tsv"
        sel = self._selected_view_rows()
        enabled = kind_ok and len(sel) >= 1
        self.btnDelete.setEnabled(enabled)
        # 重复词条按钮：tsv 且有模型时可用（合并/跳转依赖 tsv 的重复集合）
        dup_enabled = kind_ok and self._model is not None
        for w in ("btnDupHighlight", "btnDupNext", "btnDupMerge"):
            if hasattr(self, w):
                getattr(self, w).setEnabled(dup_enabled)
        # 五要素不全筛选按钮：仅 tsv 且有模型时可用（dict 无分组/启用列，无意义）
        if hasattr(self, "btnIncomplete"):
            self.btnIncomplete.setEnabled(dup_enabled)
            if not dup_enabled:
                self._incomplete_on = False
                self.btnIncomplete.setChecked(False)
                _apply_btn_class(self.btnIncomplete, "btn-ghost")
                self.btnIncomplete.setText("⚠ 要素不全")
        # 字数筛选 / 一词多码：词组、编码两列在 tsv 与 dict 模式均存在，只要有模型即可用
        filter_enabled = self._model is not None
        if hasattr(self, "_char_buttons"):
            for _, b in self._char_buttons:
                b.setEnabled(filter_enabled)
        if hasattr(self, "btnMultiCode"):
            self.btnMultiCode.setEnabled(filter_enabled)
            if not filter_enabled:
                self._multi_code_on = False
                self.btnMultiCode.setChecked(False)
                _apply_btn_class(self.btnMultiCode, "btn-ghost")
                self.btnMultiCode.setText("🔢 一词多码")
        if hasattr(self, "btnSaveSingle"):
            self.btnSaveSingle.setEnabled(filter_enabled)
        # 交换权重：恰好选中 2 行
        if hasattr(self, "btnSwapWeight"):
            self.btnSwapWeight.setEnabled(kind_ok and len(sel) == 2)

    # ---------- 重复词条（P0-2：重复定义=词组+编码 完全相同） ----------
    def on_dup_filter_toggled(self, checked):
        """重复项筛选开关：仅保留 (词组,编码) 完全相同的重复行，并按 (词组,编码) 聚拢相邻；
        走后台线程预算新顺序（与一词多码筛选同路径），避免百万行主线程卡顿。"""
        self._dup_on = bool(checked)
        if self._model is not None and self._current_kind == "tsv":
            self._model.set_filter_state(dup_only=self._dup_on)
            self._run_background_filter()
        _apply_btn_class(self.btnDupHighlight, "btn-main" if self._dup_on else "btn-ghost")
        self.btnDupHighlight.setText("🔍 已筛重复项" if self._dup_on else "🔍 重复项筛选")
        self._flash_status("已开启重复项筛选" if self._dup_on else "已关闭重复项筛选", "ok")

    def on_incomplete_toggled(self, checked):
        """五要素不全筛选开关（tsv 5 列专属）：开启时仅保留 词组/编码/权重/分组/启用 任一缺失的行。
        与文本/五框/分组筛选 AND 叠加；dict 模式无分组/启用列，调用前已在 _refresh_action_buttons 禁用。"""
        self._incomplete_on = bool(checked)
        if self._model is not None and self._current_kind == "tsv":
            self._model.set_filter_state(incomplete=self._incomplete_on)
            self._run_background_filter()
        else:
            # 非 tsv（理论上按钮已禁用）：强制复位状态，避免悬挂
            self._incomplete_on = False
            self.btnIncomplete.setChecked(False)
        self._flash_status("已开启『要素不全』筛选" if self._incomplete_on else "已关闭『要素不全』筛选", "ok")
        _apply_btn_class(self.btnIncomplete, "btn-main" if self._incomplete_on else "btn-ghost")
        self.btnIncomplete.setText("⚠ 已筛要素不全" if self._incomplete_on else "⚠ 要素不全")

    def _reset_incomplete_button(self):
        """复位『五要素不全』按钮到关闭态（clear_filter / 添加行后调用，避免状态与模型脱节）。"""
        if not hasattr(self, "btnIncomplete"):
            return
        self._incomplete_on = False
        self.btnIncomplete.setChecked(False)
        _apply_btn_class(self.btnIncomplete, "btn-ghost")
        self.btnIncomplete.setText("⚠ 要素不全")

    def _reset_char_filter(self):
        """复位字数筛选按钮组到全关态（与模型 clear_filter 对齐）。"""
        if not hasattr(self, "_char_buttons"):
            return
        self._char_active = -1
        for _, b in self._char_buttons:
            _apply_btn_class(b, "btn-ghost")

    def _reset_multi_code_button(self):
        """复位「一词多码」按钮到关闭态。"""
        if not hasattr(self, "btnMultiCode"):
            return
        self._multi_code_on = False
        self.btnMultiCode.setChecked(False)
        _apply_btn_class(self.btnMultiCode, "btn-ghost")
        self.btnMultiCode.setText("🔢 一词多码")

    def _reset_filter_buttons(self):
        """复位全部筛选型按钮（五要素不全 / 字数 / 一词多码）到关闭态。"""
        self._reset_incomplete_button()
        self._reset_char_filter()
        self._reset_multi_code_button()

    def on_char_count_clicked(self, n):
        """字数筛选（功能1）：点单字按钮 → 仅显示词组列字符数匹配的行；再点同一钮取消。
        n: -1=无(清除本筛选/显示全部)；1~4=精确；5=≥5(多)。"""
        if self._model is None:
            return
        new = -1 if self._char_active == n else n
        self._char_active = new
        if new == -1:
            self._flash_status("已清除字数筛选", "ok")
        else:
            self._flash_status("正在按字数筛选：%d 字%s…" % (
                new, "及以上" if new == 5 else ""), "ok")
        if self._current_kind == "tsv":
            self._model.set_filter_state(char_count=new)
            self._run_background_filter()   # tsv 走后台，完成提示在 _on_filter_computed
        else:
            self._model.set_char_count_filter(new)
            self._flash_status("字数筛选完成：仅显示 %d 字%s的词组" % (
                new, "及以上" if new == 5 else ""), "ok")
        for val, b in self._char_buttons:
            _apply_btn_class(b, "btn-main" if val == self._char_active else "btn-ghost")
        self._update_status()

    def on_multi_code_toggled(self, checked):
        """一词多码筛选开关（功能2）：开启时仅显示『同一词组存在 ≥2 个互异编码』的行。"""
        self._multi_code_on = bool(checked)
        if self._model is not None:
            if self._current_kind == "tsv":
                self._model.set_filter_state(multi_code=self._multi_code_on)
                self._run_background_filter()
            else:
                self._model.set_multi_code_filter(self._multi_code_on)
        else:
            self._multi_code_on = False
            self.btnMultiCode.setChecked(False)
        _apply_btn_class(self.btnMultiCode, "btn-main" if self._multi_code_on else "btn-ghost")
        self.btnMultiCode.setText("🔢 已筛一词多码" if self._multi_code_on else "🔢 一词多码")
        self._flash_status("已开启一词多码筛选" if self._multi_code_on else "已关闭一词多码筛选", "ok")

    def on_save_single_code_table(self):
        """保存为单一码表（功能3）：取内存全部行 → 启用=='A' → 按分组首字母拆分
        E→English.dict.yaml，其它→wubi.dict.yaml；弹文件夹选择框写两文件（写前同目录留快照）。"""
        if self._model is None or self._current_kind != "tsv":
            info(self, "保存为单一码表", "请先加载 TSV 词库。")
            return
        self.statusBar().showMessage("正在生成单一码表…")   # 过程提示：导出前准备
        self._model._sync_order_to_data()   # 方案①：导出单一码表前固化拖拽产生的 _order 改动到物理顺序
        rows = self._model.rows()
        dir_path = QFileDialog.getExistingDirectory(
            self, "选择保存位置（将写入 English.dict.yaml 与 wubi.dict.yaml）")
        if not dir_path:
            self.statusBar().showMessage("已取消保存为单一码表", 2000)
            return
        try:
            from core.rime_export import build_single_tables, write_rime_file
            tables = build_single_tables(rows)
        except Exception as exc:  # noqa: BLE001
            critical(self, "保存为单一码表", "生成码表失败：%s" % exc)
            return
        for fname, content in tables.items():
            target = os.path.join(dir_path, fname)
            try:
                backup_mod.open_snapshot(target, "RimeTool-")   # 写前快照
                write_rime_file(target, content, os.path.splitext(fname)[0])
            except Exception as exc:  # noqa: BLE001
                critical(self, "保存为单一码表", "写出 %s 失败：%s" % (fname, exc))
                return
        lines_e = sum(1 for r in rows
                      if (r[4] or "").strip() == "A" and (r[3] or "")[:1].upper() == "E")
        lines_w = sum(1 for r in rows
                      if (r[4] or "").strip() == "A" and (r[3] or "")[:1].upper() != "E")
        info(
            self, "保存为单一码表",
            "已保存到：%s\n\nEnglish.dict.yaml（E 开头且启用=A）：%d 行\n"
            "wubi.dict.yaml（其它开头且启用=A）：%d 行" % (dir_path, lines_e, lines_w))
        self._flash_status("已保存单一码表到 %s（English %d 行 / wubi %d 行）"
                          % (dir_path, lines_e, lines_w), "ok", 5000)

    def on_dup_next(self):
        """从当前选中行之后查找下一个重复数据行，选中并滚动定位；到底循环回顶部。"""
        if self._model is None or self._current_kind != "tsv":
            return
        self.statusBar().showMessage("正在定位下一个重复词条…")
        if not self._model._dup_computed:
            self._model.recompute_duplicates()   # 重复集合懒算：未算过时先算，确保「下一处」可定位
        order = self._model._order
        dup = self._model._dup_srcs
        sel = self._selected_view_rows()
        start = (sel[-1] + 1) if sel else 0
        n = len(order)
        for vr in range(start, n):
            el = order[vr]
            if isinstance(el, int) and el in dup:
                self.tableView.selectRow(vr)
                self.tableView.scrollTo(self._model.index(vr, 0))
                self.statusBar().showMessage("已定位下一个重复词条（显示第 %d 行）" % (vr + 1), 3000)
                return
        for vr in range(0, max(0, start)):
            el = order[vr]
            if isinstance(el, int) and el in dup:
                self.tableView.selectRow(vr)
                self.tableView.scrollTo(self._model.index(vr, 0))
                self.statusBar().showMessage("已定位下一个重复词条（显示第 %d 行）" % (vr + 1), 3000)
                return
        info(self, "重复词条", "已无更多重复词条（key=词组+编码）。")
        self.statusBar().showMessage("已无更多重复词条", 3000)

    def on_dup_merge(self):
        """合并重复（key=词组+编码）：保留每组首行，词频取最大，删除冗余行。"""
        if self._model is None or self._current_kind != "tsv":
            return
        self.statusBar().showMessage("正在查找并合并重复词条…")
        groups = self._model.find_duplicate_groups((0, 1))
        if not groups:
            info(self, "合并重复", "没有发现重复词条（key=词组+编码）。")
            self.statusBar().showMessage("未找到重复词条", 3000)
            return
        removed = self._model.merge_duplicates(groups, strategy="max_freq")
        self._invalidate_filter()   # 合并同步重建 _order，失效在途后台筛选结果
        if removed:
            info(
                self, "合并重复",
                f"已合并 {removed} 条冗余重复词条（保留每组首行，词频取最大）。",
            )
            self._flash_status(f"已合并 {removed} 条冗余重复词条", "ok", 4000)
            self._update_status()          # 总/显/选 计数随之刷新
            self._refresh_action_buttons()

    # ---------- 五笔编码生成（P0-1：6 种编码方式，已并入顶部「添加」） ----------
    def _open_wubi_dialog(self, prefill=None):
        """打开五笔编码生成对话框（tsv 专用）：输入词组→按 6 种规则生成编码→追加到 TSV / dict。

        prefill 为顶部五框齐全时抄送来的 {词组,编码,权重,分组,启用}；
        为空则进入「原右边栏模式」（手动多行输入）。仅对已加载的 tsv 词库生效。
        「追加到TSV」写入当前 tsv；「追加到dict词典」按分组首字母路由到 rime_config_dir 下对应 .dict.yaml。
        """
        if self._model is None or self._current_kind != "tsv":
            warning(self, "提示", "五笔编码生成仅适用于已加载的 tsv 词库。")
            return
        from ui.wubi_encode_dialog import WubiEncodeDialog
        dlg = WubiEncodeDialog(self, self._model, prefill=prefill, tsv_path=self._current_path)
        dlg.exec_()
        # 对话框内已刷新状态/按钮；这里补：筛选复位 + 下拉刷新 + 计数
        # tsv 大词库走后台算新顺序（clear_filter 同步版会主线程全表扫描），dict 仍同步
        if self._current_kind == "tsv":
            self._model.set_filter_state(text="", field={}, group="", incomplete=False, char_count=-1, multi_code=False)
            self._run_background_filter()
        else:
            self._model.clear_filter()
        self._filter_state = {}
        self._refresh_combos()
        self._update_status()
        self.statusBar().showMessage("已通过五笔编码对话框追加（未保存）")

    # ---------- 组内排序控件（仅保留交换权重） ----------
    def _build_sort_controls(self):
        """顶部操作区：仅保留交换权重按钮。"""
        self.btnSwapWeight = QPushButton("⇄交换权重")
        self.btnSwapWeight.setToolTip("选中恰好 2 行 → 互换这两行的权重（col2）")
        self.actionLayout.addWidget(self.btnSwapWeight)
        self.btnSwapWeight.clicked.connect(self.on_swap_weight)
        _apply_btn_class(self.btnSwapWeight, "btn-search")

    def on_swap_weight(self):
        """交换权重：必须选中恰好 2 行（tsv），互换二者 col2 权重。"""
        if self._model is None or self._current_kind != "tsv":
            return
        rows = self._selected_view_rows()
        if len(rows) != 2:
            info(self, "提示", "请选中恰好 2 行来交换权重。")
            return
        ok = self._model.swap_weights(rows)
        if not ok:
            self.statusBar().showMessage("两行权重相同，无需交换", 3000)
            return
        self._refresh_combos()
        self._update_status()
        self.statusBar().showMessage("已交换选中两行的权重", 3000)

    # ---------- 拖拽到左侧分组树（增强） ----------
    def _install_drag_drop(self):
        """拖拽两种用途共存：
        - 在表格内拖动选中行（单行/多行，左键按住拖到任意位置）= 改变显示顺序（拖拽重排）；
        - 把选中行拖到左侧分组列表项 = 移动到该分组（同时启用A）。"""
        # 使用新的 DragController 完全接管表格拖拽（并感知左侧分组面板）
        self._drag_controller = DragController(self.tableView, self.groupListWidget)
        self._drag_controller.install()

        # 连接信号
        self._drag_controller.drag_started.connect(self._on_drag_started)
        self._drag_controller.drag_dropped.connect(self._on_drag_dropped)
        self._drag_controller.drag_cancelled.connect(self._on_drag_cancelled)
        self._drag_controller.group_drop_requested.connect(self._on_group_drop_requested)

        # 左侧分组面板拖拽保持不变
        self.groupListWidget.setAcceptDrops(True)
        self.groupListWidget.installEventFilter(self)

    def _set_drag_class(self, widget, name):
        """设置/清除拖拽态 class（dragging / drag-target），触发样式重算以显示虚线高亮。

        重要：unpolish/polish 会重建控件样式，必须在拖放「高频阶段之外」调用
        （仅 DragEnter / DragLeave / Drop 各一次，见 eventFilter）。一旦在 DragMove
        （拖拽过程中高频触发）里调用，会打断正在进行的拖放操作，导致 Drop 事件
        永不触发，排序与分组改写全部失效（Task #63 回归根因）。
        增加「值未变则跳过」保护，进一步避免任何重复刷新。
        """
        target = name if name else ""
        if widget.property("class") == target:
            return
        widget.setProperty("class", target)
        try:
            widget.style().unpolish(widget)
            widget.style().polish(widget)
        except Exception:  # noqa: BLE001 - 样式刷新失败不阻断拖拽
            _log.debug("拖拽态样式刷新失败", exc_info=True)

    # ---------- 拖拽信号处理（DragController） ----------

    def _on_drag_started(self, rows):
        """拖拽开始：状态栏提示"""
        self.statusBar().showMessage(f"正在拖拽 {len(rows)} 行...")

    def _on_drag_dropped(self, target, before, new_rows):
        """拖拽完成：状态栏反馈，并把选区迁到拖拽后的新位置（防御修复①）。"""
        pos = "之前" if before else "之后"
        self.statusBar().showMessage(f"已插入到第 {target} 行{pos}（未保存）", 3000)
        # 把选区迁到拖动后的新行号，确保五框回填的是用户刚拖动的行，
        # 而非行号漂移后错位的其他行（这是旧代码制造重复词条的根因之一）。
        if new_rows:
            self._select_and_reveal(new_rows)

    def _on_drag_cancelled(self):
        """拖拽取消"""
        self.statusBar().showMessage("已取消拖拽", 2000)

    def _on_group_drop_requested(self, name):
        """拖到左侧分组面板某分组项：把选中行移动到该分组（改分组列，并按设计把「启用」置 A；点保存才写文件）。

        由 DragController.group_drop_requested 信号触发，复用 _move_to_group_by_name 的
        完整 UI 刷新（MRU / 下拉 / 选中定位 / 状态栏反馈）。
        """
        if name:
            self._move_to_group_by_name(name, enable_value="A")

    def eventFilter(self, obj, event):
        """事件过滤：表格拖拽由 DragController 接管；分组面板拖拽同样由 DragController
        的全局事件过滤器（拖拽中鼠标移到 viewport 外时）接管——原生 QDrag 已被
        DragController.install() 的 setDragEnabled(False) 禁用，故本分支的 DragEnter/Drop
        正常情况下不会触发，仅作结构性保留。
        """
        # 表格尺寸变化（分组面板显隐、分隔条/窗口缩放导致中栏重布局）→ 此时视口宽已落定，
        # 用正确视口宽重铺列宽，避免「读到旧视口宽 → 列算宽溢出 → 末列被裁（横向滚动条已禁用）」。
        # 仅改列宽不会回触发表格 Resize（横向滚动条关闭，视口宽由布局决定），无递归风险。
        if obj is self.tableView and event.type() == QEvent.Resize:
            if getattr(self, "_model", None) is not None:
                self._fit_columns_to_view()
            return super().eventFilter(obj, event)
        if obj is self.groupListWidget:
            et = event.type()
            if et == event.DragEnter:
                # 进入时设置一次高亮（unpolish/polish 仅此处一次，安全）
                if self._selected_view_rows():
                    self._set_drag_class(self.groupListWidget, "drag-target")
                    event.acceptProposedAction()
                    return True
                self._set_drag_class(self.groupListWidget, None)
                return False
            if et == event.DragMove:
                # 高频阶段：保持与原 DragEnter 同款 accept 判定，但绝不触碰样式重建，
                # 否则会打断拖放导致 Drop 不触发（Task #63）
                if self._selected_view_rows():
                    event.acceptProposedAction()
                    return True
                return False
            if et == event.DragLeave:
                self._set_drag_class(self.groupListWidget, None)
                return False
            if et == event.Drop:
                self._set_drag_class(self.groupListWidget, None)
                item = self.groupListWidget.itemAt(event.pos())
                if item is not None:
                    name = item.text()
                    if name and name != "（全部）":
                        # 拖入分组：改写这些行的「分组」列，并按设计把「启用」置 A（点保存才写文件）
                        self._move_to_group_by_name(name, enable_value="A")
                        event.acceptProposedAction()
                        return True
                return False
        # 表格拖拽已由 DragController 接管，不再处理
        return super().eventFilter(obj, event)

    def _move_to_group_by_name(self, group=None, enable_value=None):
        """批量改选中行的分组和/或启用（对话框/拖拽共用）。

        group: None=不改分组；其它=目标分组名（拖拽场景固定传具体分组）。
        enable_value: None=不改启用；""=清空；"A"/自定义=置该值（拖拽场景固定传 "A"）。
        """
        if self._model is None or self._current_kind != "tsv":
            return
        rows = self._selected_view_rows()
        if not rows:
            return
        changed, first = self._model.move_selected_to_group(
            rows, group_name=group, enable_value=enable_value)
        if changed == 0:
            self.statusBar().showMessage("无变化（分组/启用已一致）", 3000)
            return
        if group:   # 仅当真正改了分组才更新 MRU
            self._update_mru(group)
        self._refresh_combos()
        if first >= 0:
            self.tableView.selectRow(first)
        self._update_status()
        self._refresh_action_buttons()
        parts = []
        if group:
            parts.append(f"分组→「{group}」")
        if enable_value is not None:
            parts.append(f"启用→{'空' if enable_value == '' else enable_value}")
        self.statusBar().showMessage(f"已改 {changed} 条：" + "，".join(parts), 3000)

    def _flash_status(self, msg, kind="ok", msec=3000):
        """状态栏提示 + 短暂颜色反馈：让用户明确知道发生了什么，不会以为程序卡死。
        kind: ok=绿 / warn=橙。颜色约 900ms 后复位，文字提示保留 msec 毫秒。"""
        sb = self.statusBar()
        sb.showMessage(msg, msec)
        color = "#1f7a3d" if kind == "ok" else "#8a5a00"
        sb.setStyleSheet("QStatusBar{background:%s;color:#ffffff;}" % color)
        QTimer.singleShot(900, lambda: sb.setStyleSheet(""))

    def _select_and_reveal(self, view_rows):
        """拖拽/移动后选中这些行并滚动到可见（模拟 Excel 拖完定位到那行）。

        view_rows: 移动后这些行在显示顺序中的新行号列表（可能为空）。"""
        if not view_rows:
            return
        sel = self.tableView.selectionModel()
        if sel is None:
            return
        rc = self._model.rowCount()
        cc = self._model.columnCount()
        selection = QItemSelection()
        for vr in view_rows:
            if 0 <= vr < rc:
                tl = self._model.index(vr, 0)
                br = self._model.index(vr, cc - 1)
                selection.select(tl, br)
        if selection.isEmpty():
            return
        sel.select(selection, QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows)
        first = view_rows[0]
        if 0 <= first < rc:
            self.tableView.scrollTo(self._model.index(first, 0))

    def _update_mru(self, group):
        """把最近移动到的分组写入 QSettings movegroup/mru（去重、截断、置顶）。"""
        try:
            cur = []
            val = QSettings().value("movegroup/mru")
            if val:
                cur = [str(v) for v in val] if isinstance(val, list) else [str(val)]
            cur = [g for g in cur if g and g != group][: (8 - 1)]
            QSettings().setValue("movegroup/mru", [group] + cur)
        except Exception:  # noqa: BLE001 - 保存 MRU 失败不阻断
            _log.debug("保存最近使用分组失败", exc_info=True)

    def _selected_view_rows(self):
        """读取 QTableView 当前选中行（view 行号列表）。"""
        sel = self.tableView.selectionModel()
        if sel is None:
            return []
        return sorted({idx.row() for idx in sel.selectedRows()})

    def _connect_signals(self):
        self.btnSearch.clicked.connect(self.on_search)
        self.btnAdd.clicked.connect(self.on_add)
        self.btnDelete.clicked.connect(self.on_delete)
        self.btnSave.clicked.connect(self.on_save)
        self.btnDeploy.clicked.connect(self.on_deploy)
        self.btnConfig.clicked.connect(self.on_config)
        self.btnExportRime.clicked.connect(self.on_export_rime)
        self.btnBatchWeight.clicked.connect(self.on_batch_weight)
        self.btnVoiceGap.clicked.connect(self.on_voice_gap)
        # 重复词条（P0-2）
        self.btnDupHighlight.toggled.connect(self.on_dup_filter_toggled)
        self.btnDupNext.clicked.connect(self.on_dup_next)
        self.btnDupMerge.clicked.connect(self.on_dup_merge)
        # 第 7 个按钮：五要素不全筛选（tsv 专属）
        self.btnIncomplete.toggled.connect(self.on_incomplete_toggled)
        # 功能2：一词多码
        self.btnMultiCode.toggled.connect(self.on_multi_code_toggled)
        # 功能3：保存为单一码表
        self.btnSaveSingle.clicked.connect(self.on_save_single_code_table)
        self.fileTree.itemClicked.connect(self._on_tree_clicked)
        # Bug B 修复：分组列表点击加 150ms 去抖，避免疯狂连点产生大量后台筛选线程
        self._group_click_timer = QTimer(self)
        self._group_click_timer.setSingleShot(True)
        self._group_click_timer.timeout.connect(self._on_group_clicked_deferred)
        self.groupListWidget.itemClicked.connect(self._on_group_clicked_request)
        # 五框联动：五框为「组合(AND)」筛选条件；输入/下拉变化都防抖重筛，互不清除；
        # 两个下拉间互级联限制选项；提供「清除」按钮复位全部条件。
        self.editWord.textEdited.connect(self._on_text_edited)
        self.editCode.textEdited.connect(self._on_text_edited)
        self.editWeight.textEdited.connect(self._on_text_edited)
        self.comboGroup.currentTextChanged.connect(self._on_combo_changed)
        self.comboEnable.currentTextChanged.connect(self._on_combo_changed)
        # 窗口 / 左右分隔条缩放时，重新按比例铺满列宽（保持无横向滚动条）
        self.splitter.splitterMoved.connect(self._fit_columns_to_view)
        self.midSplitter.splitterMoved.connect(self._fit_columns_to_view)

    def _connect_model_signals(self):
        sel = self.tableView.selectionModel()
        if sel is not None:
            sel.selectionChanged.connect(self._on_selection_changed)
        if self._model is not None:
            self._model.dirtyChanged.connect(self._refresh_title)

    def resizeEvent(self, event):
        """窗口尺寸变化 → 重新按比例铺满列宽，避免底部横向滚动条；并重算左右栏固定宽。"""
        super().resizeEvent(event)
        if getattr(self, "_model", None) is not None:
            self._fit_columns_to_view()
        self._apply_side_widths()

    # ---------- 窗口几何记忆（退出时记住大小/位置，下次启动恢复） ----------
    def _apply_side_widths(self):
        """按当前窗口宽重算左/右栏固定像素宽（仅中栏拉伸）；用最终宽度避免恢复后偏差。
        若已从 QSettings 恢复分隔条状态，则跳过——沿用用户记忆的左右栏宽度，中栏随窗口拉伸。"""
        if self._splitter_restored:
            return
        base = self.width()
        if base <= 0:
            return
        # 中间栏左侧（文件树）固定宽（按窗口 20% 比例，下限 160；用户要求不再叠加字符偏移）
        self.leftWidget.setFixedWidth(max(160, int(base * 0.2)))
        # 右侧功能栏缩短 20%（用户 UI 设计）：宽度 = 原 0.3 基宽 * 0.8；
        # 下限 240，确保右侧按钮（各自内容宽+100）在全局字号 14pt 下仍不溢出。
        self.rightWidget.setFixedWidth(max(240, int(base * 0.3 * 0.8)))

    def showEvent(self, event):
        """首次显示且布局稳定后，按正确视口宽重铺列，规避窗口记忆后『列向左集中/词组看不见』。
        （窗口几何/分隔条在 __init__ 恢复，但此时尚未布局，视口宽可能失真；show 之后再铺一次即准。）"""
        super().showEvent(event)
        if getattr(self, "_model", None) is not None:
            QTimer.singleShot(0, self._fit_columns_to_view)
        # 列头行高对齐顶部工具条（部署等按钮所在行）：布局稳定后取工具条控件高设为固定高度
        QTimer.singleShot(0, self._sync_header_height_to_topbar)

    def _sync_header_height_to_topbar(self):
        """把词库表格列头（词组/五笔编码/权重…那一行）的高度，设为与顶部工具条按钮所在行一致。

        仅改列头这一行，表格正文行高不受影响；顶部工具条单行（部署等按钮所在行）的高度即参照基准。
        同时把状态栏高度锁定为「工具条高度 - 2px」：与顶栏视觉呼应但略小一号（用户要求）。"""
        try:
            ref = getattr(self, "btnDeploy", None)
            if ref is not None:
                h = ref.height()
                if h > 0:
                    self.tableView.horizontalHeader().setFixedHeight(h)
                    # 状态栏 = 工具条高 - 2px（稍小一号；下限 22px 防过扁裁字）
                    self.statusBar().setFixedHeight(max(22, h - 2))
        except Exception:  # noqa: BLE001 - 高度同步失败不影响其它功能
            _log.debug("同步列头高度到顶部工具条失败", exc_info=True)

    def _restore_geometry(self):
        """启动时恢复上次退出的窗口几何（大小+位置+最大化态）与分隔条状态；无记忆则用默认。

        增加屏外/非法几何保护：若恢复后的窗口完全落在本机任何可见屏幕之外（如曾外接显示器后被
        拔掉、或分辨率变更导致坐标为负/越界），则重置为居中可见的默认窗口，避免「双击启动却看不到
        窗口」的假死现象（用户以为程序打不开，其实窗口开在了屏外）。"""
        try:
            geo = QSettings().value("window/geometry")
            if geo:
                self.restoreGeometry(geo)
                if not self._geometry_on_screen():
                    _log.warning("恢复到的窗口几何在可见屏幕之外，已重置为默认可见位置")
                    self._reset_geometry_to_default()
            st = QSettings().value("window/splitter")
            if st:
                self.splitter.restoreState(st)
                self._splitter_restored = True
            mst = QSettings().value("window/midSplitter")
            if mst:
                self.midSplitter.restoreState(mst)
                self._splitter_restored = True
        except Exception:  # noqa: BLE001 - 恢复失败不阻断
            _log.debug("恢复窗口几何/分隔条失败", exc_info=True)

    def _geometry_on_screen(self):
        """当前窗口 frameGeometry 是否与本机任一可见屏幕的可用区域有交集（非完全屏外/非法）。"""
        try:
            fg = self.frameGeometry()
            if fg.isEmpty() or fg.width() <= 0 or fg.height() <= 0:
                return False
            for scr in QApplication.screens():
                if fg.intersects(scr.availableGeometry()):
                    return True
            return False
        except Exception:  # noqa: BLE001 - 探测失败保守认为可见，不误重置
            return True

    def _reset_geometry_to_default(self):
        """把窗口重置为居中、可见的默认尺寸（基于主屏可用区域）。"""
        try:
            screen = QApplication.primaryScreen()
            if screen is not None:
                avail = screen.availableGeometry()
            else:
                avail = QRect(0, 0, 1280, 800)
            w = min(int(avail.width() * 0.9), 1600)
            h = min(int(avail.height() * 0.9), 1000)
            x = avail.x() + (avail.width() - w) // 2
            y = avail.y() + (avail.height() - h) // 2
            self.setGeometry(x, y, w, h)
        except Exception:  # noqa: BLE001
            _log.debug("重置默认几何失败", exc_info=True)

    def _save_geometry(self):
        r"""退出前保存窗口几何与分隔条状态到 QSettings（HKCU\Software\Rime\RimeTool）。"""
        try:
            QSettings().setValue("window/geometry", self.saveGeometry())
            QSettings().setValue("window/splitter", self.splitter.saveState())
            QSettings().setValue("window/midSplitter", self.midSplitter.saveState())
        except Exception:  # noqa: BLE001 - 保存分隔条失败不阻断
            _log.debug("保存分隔条状态失败", exc_info=True)

    # ---------- 左栏文件树 ----------
    def _build_tree(self):
        """文件树完全拍平：tsv 与 dict.yaml 文件直接作为顶层项，不做类型分组。

        每个文件项携带 ROLE_TYPE（tsv/dict）与 ROLE_PATH，点击行为与旧两级结构一致；
        分组壳节点已删除，_on_tree_clicked 对非文件项的过滤天然兼容。"""
        self.fileTree.clear()
        entries = []   # (name, full_path, type)

        tsv_path = self._config.get("tsv_path", "")
        if tsv_path and os.path.isfile(tsv_path):
            entries.append((os.path.basename(tsv_path), tsv_path, "tsv"))

        dir_path = self._config.get("rime_config_dir", "")
        if dir_path and os.path.isdir(dir_path):
            # 收集子目录下全部 .dict.yaml（不保留目录层级）
            for root, _dirs, files in os.walk(dir_path):
                for name in files:
                    if name.endswith(".dict.yaml"):
                        full = os.path.join(root, name)
                        entries.append((name, full, "dict"))

        # 按完整路径稳定排序，两类文件混排为一个平铺列表
        entries.sort(key=lambda x: x[1])
        for name, full, typ in entries:
            node = QTreeWidgetItem(self.fileTree, [name])
            node.setData(0, ROLE_TYPE, typ)
            node.setData(0, ROLE_PATH, full)

        self.fileTree.expandAll()

    def _auto_load_first(self):
        """启动后自动加载第一个可用文件（优先 tsv；拍平后遍历顶层项）。"""
        first_any = None
        for i in range(self.fileTree.topLevelItemCount()):
            item = self.fileTree.topLevelItem(i)
            typ = item.data(0, ROLE_TYPE)
            if typ not in ("tsv", "dict"):
                continue
            if typ == "tsv":
                self.fileTree.setCurrentItem(item)
                self._on_tree_clicked(item, 0)
                return
            if first_any is None:
                first_any = item
        if first_any is not None:
            self.fileTree.setCurrentItem(first_any)
            self._on_tree_clicked(first_any, 0)

    def _on_tree_clicked(self, item, _col):
        typ = item.data(0, ROLE_TYPE)
        if typ not in ("tsv", "dict"):
            return
        path = item.data(0, ROLE_PATH)
        if not path or not os.path.isfile(path):
            warning(self, "提示", f"文件不存在：\n{path}")
            return
        if typ == "tsv":
            self._load_tsv(path)
        else:
            self._load_dict(path)

    # ---------- 加载文件 ----------
    def _set_model(self, model, kind, path):
        self._model = model
        self._invalidate_filter()   # 切换文件：作废在途后台筛选结果，避免回写到新模型
        self._current_kind = kind
        self._current_path = path
        self._filter_timer.stop()       # 取消上一份文件遗留的防抖筛选
        self.tableView.setModel(model)
        # 拖拽控制器绑定新模型（维护 modelAboutToBeReset/modelReset 信号，避免模型被替换后连接失效/陈旧）
        dc = getattr(self, "_drag_controller", None)
        if dc is not None:
            dc.bind_model(model)
        # 列宽重算推迟到分组面板 show/hide 之后、布局稳定再做（见方法末尾 QTimer）
        self._connect_model_signals()
        self._clear_fields()            # 清空五框残留值
        self._filter_state = {}         # 新文件：筛选条件清空
        if kind == "dict":
            self._populate_groups(model)   # dict：填充并显式分组面板
        else:
            self.groupPanel.hide()         # tsv：隐藏分组面板
        self._refresh_combos()
        self._refresh_title()
        self._update_status()
        self._refresh_action_buttons()      # 新文件/类型切换 → 重算「移动到」按钮
        # 方案A：分组面板显隐会改变表格视口宽，必须等布局落定后再按比例铺列宽，
        # 否则按"宽视口"算出的列宽在面板出现后溢出、最右「启用」列被裁掉（横向滚动条已禁用）。
        QTimer.singleShot(0, self._fit_columns_to_view)

    def _populate_groups(self, model):
        """dict / tsv 模式：填充左侧分组列表（含「全部」）并显示面板。
        tsv 模式下列表来自分组列去重值，同时作为拖拽移动的目标与分组筛选。"""
        self.groupListWidget.clear()
        self.groupPanel.show()
        self.groupLabel.hide()          # 不显示「分组」标题（按需求）
        self.groupListWidget.addItem("（全部）")
        if self._current_kind == "dict":
            for g in model.groups():
                self.groupListWidget.addItem(g)
        else:   # tsv：分组列去重
            grp_col = model.FIELD_COLS.get("分组", 3)   # 分组列 index（5 列布局=3），勿硬编码启用列
            # 加载优化：优先取加载时预算好的分组去重缓存，免主线程再扫全表；
            # RimeDictModel 等无该接口的模型回退 distinct_values。
            if hasattr(model, "get_distinct_groups"):
                groups = model.get_distinct_groups()
            else:
                groups = model.distinct_values(grp_col)
            for g in groups:
                self.groupListWidget.addItem(g)
        self.groupListWidget.setCurrentRow(0)   # 默认「全部」

    def _on_group_clicked_request(self, item):
        """分组列表点击的防抖入口（Bug B）：150ms 内仅最后一次点击生效。"""
        self._pending_group_item = item
        self._group_click_timer.start(150)

    def _on_group_clicked_deferred(self):
        """去抖到期后真正执行分组筛选（取最后一次点击的分组项）。"""
        if getattr(self, "_pending_group_item", None) is not None:
            self._on_group_clicked(self._pending_group_item)

    def _on_group_clicked(self, item):
        """点击左侧分组名 → 对右侧表格按该组筛选（与顶部五框字段筛选叠加）。
        选分组列 → 自动清空五框（需求3：只要不是选中列表内容，五框不显示内容）。"""
        if self._model is None or self._current_kind not in ("dict", "tsv"):
            return
        name = "" if item.text() == "（全部）" else item.text()
        self._clear_fields()   # 选分组列 → 清空五框
        if self._current_kind == "tsv":
            # Bug A 修复：点分组同时清空字段筛选（field={}），避免旧列筛选残留叠加
            self._model.set_filter_state(group=name, field={})
            self._run_background_filter(autofill=False)   # 选分组 → 不自动填五框（规则：选分组清空五框）
        else:
            # P1-⑤：dict 模式点分组同样下沉后台线程，避免中大型 Rime 词典点分组时主线程全表扫描卡顿。
            # 经 set_filter_state（清空字段筛选、设分组）后走与 tsv 相同的 _run_background_filter 异步路径。
            self._model.set_filter_state(group=name, field={})
            self._run_background_filter(autofill=False)   # 选分组 → 不自动填五框
        self._update_status()

    def _apply_col_widths(self, kind):
        """列宽：按预设比例把各列铺满表格可视宽度（见 _fit_columns_to_view），
        任何窗口尺寸都不溢出 → 不再出现底部横向滚动条。"""
        self._fit_columns_to_view()

    def _fit_columns_to_view(self):
        """把各列按预设比例缩放到表格可视宽度，消除底部横向滚动条（窗口/分隔条缩放时重算）。"""
        if self._model is None:
            return
        hdr = self.tableView.horizontalHeader()
        avail = self.tableView.viewport().width()
        if avail <= 0:
            # 视口尚未就绪（布局未落定）：延后一帧再试，避免用 0 宽算出错误列宽后永久错列
            QTimer.singleShot(30, self._fit_columns_to_view)
            return
        if self._current_kind == "dict":
            desired = [300, 130, 90]
        else:
            # 列序（同 core.config.HEADERS）：词组/编码/词频/分组/启用码
            # req3：固定基线 250/100/100/150/100（合计 700），仍按窗口可视宽等比放大铺满中栏
            desired = [250, 100, 100, 150, 100]
        total = sum(desired)
        if not total:
            return
        scale = avail / total
        # 落地列宽：先按等比取整，再给每个列 40px 下限（太窄不可读）。
        COL_MIN = 40
        widths = [max(COL_MIN, int(w * scale)) for w in desired]
        # 收敛：下限会导致「取整后之和」略超视口 → 把超出部分从仍有余量（>下限）的列
        # 按比例扣回，保证 sum(widths) <= avail（除非视口窄到连 COL_MIN*列数 都放不下，
        # 那种极端情形由 ScrollBarAsNeeded 兜底，不会裁掉末列使其永久不可见）。
        excess = sum(widths) - avail
        if excess > 0:
            slack_total = sum(w - COL_MIN for w in widths)
            if slack_total >= excess:
                slack_idx = [i for i, w in enumerate(widths) if w > COL_MIN]
                # 先按比例扣（四舍五入），再精确收敛到 <= avail
                for i in slack_idx:
                    cut = int(round((widths[i] - COL_MIN) * excess / slack_total))
                    widths[i] = max(COL_MIN, widths[i] - cut)
                while sum(widths) > avail and any(w > COL_MIN for w in widths):
                    i = max((j for j, w in enumerate(widths) if w > COL_MIN),
                            key=lambda j: widths[j])
                    widths[i] -= 1
        for c, w in enumerate(widths):
            hdr.setSectionResizeMode(c, QHeaderView.Interactive)
            self.tableView.setColumnWidth(c, w)

    def _stop_background_threads(self, wait_ms=0):
        """P0-1 修复：停止并释放后台线程（LoadThread/FilterThread + 模型后台排序线程）。

        退出/重载时若线程仍在运行即随应用销毁 → "QThread: Destroyed while thread is still
        running" 崩溃/告警。wait_ms>0 阻塞等待（用于 closeEvent，给线程跑完当前任务）；
        =0 仅发 quit 并交由 finished→deleteLater 自愈（用于重载/重筛，不阻塞 UI）。
        注：LoadThread/FilterThread/SortThread.run 是普通 CPU 任务，quit() 对其无中断效果，
        故停止主要依赖「跑完后 finished→deleteLater 自愈」+ 调用方用 sender/token 守卫丢弃迟到结果。

        防御：线程在 finished→deleteLater 后其 C++ 对象已被删除，但 Python 包装仍可能残留在
        self._thread/self._filter_thread 上（如切换文件时旧 LoadThread 已删）；此时访问 isRunning()
        会抛 RuntimeError。用 try/except 吞掉，避免因删除对象导致后续 _load_tsv 整体中断、卡死"加载中"。"""
        threads = [self._thread, self._filter_thread]
        # 模型持有的后台排序线程（DictModel.SortThread）；RimeDictModel 等无此属性则跳过
        m = getattr(self, "_model", None)
        if m is not None:
            st = getattr(m, "_sort_thread", None)
            if st is not None:
                threads.append(st)
        for th in threads:
            if th is None:
                continue
            try:
                if th.isRunning():
                    th.quit()
                    if wait_ms:
                        th.wait(wait_ms)
            except RuntimeError:
                # C++ 对象已被 deleteLater 删除：无需也不能再停止，跳过即可
                continue

    def _load_tsv(self, path):
        self._invalidate_filter()   # 切换文件：作废在途后台筛选结果，避免回写到新模型
        self._current_path = path
        self._current_kind = "tsv"
        self._filter_state = {}         # 重新加载：筛选条件清空
        model = DictModel()
        self._model = model  # 必须在此持有引用，线程回调 _on_tsv_loaded 依赖 self._model
        self.tableView.setModel(model)
        # 拖拽控制器绑定新模型（维护 modelAboutToBeReset/modelReset 信号）
        dc = getattr(self, "_drag_controller", None)
        if dc is not None:
            dc.bind_model(model)
        self._apply_col_widths("tsv")
        self.groupPanel.hide()   # tsv 无 `##` 分组，隐藏左分组面板
        self._connect_model_signals()
        self.statusBar().showMessage(f"加载中: {path}")
        # P0-1 修复：重载前先停掉仍在跑的旧加载/筛选线程，否则旧线程随窗口销毁会触发
        # "QThread: Destroyed while thread is still running"。旧线程已是 finished→deleteLater
        # 自愈路径，这里仅确保不会与新线程并存导致回调竞态/重复写入。
        self._stop_background_threads()
        self._thread = LoadThread(path)
        self._thread.loaded.connect(self._on_tsv_loaded)
        self._thread.error.connect(self._on_load_error)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()

    def _on_tsv_loaded(self, data, total, extras=None):
        # 竞态防护：若加载期间用户切换了文件，self._thread / self._model 已指向新对象，
        # 此回调来自旧线程 → 丢弃，避免把数据写入错误模型。
        sender = self.sender()
        if sender is not self._thread:
            return
        # 双保险：dict 模式下不应再收到 tsv 加载回调（旧 LoadThread 迟到），直接丢弃，
        # 避免对 RimeDictModel 调用 DictModel 专属的 set_all_data 抛 AttributeError。
        if self._current_kind != "tsv":
            return
        self._model.set_all_data(data, total, extras)
        # #90 重开文件时恢复上次表头排序：须放在「重复项筛选」发起之前。否则下方 _run_background_filter
        # 用旧 token 发起 dup 筛选，随后 restore 触发的 sortIndicatorChanged→_on_sort_changed→
        # _invalidate_filter 把 token 自增，导致 dup 线程结果因 token 过期被丢弃——表格显示全部行、
        # 但按钮仍显示"已筛重复项"（状态不一致）。先 restore 再发起 dup 筛选即可用最新 token。
        self._restore_sort_state()
        # 若此前已开启重复项筛选，新文件加载后保持筛选（重复集合已在 set_all_data 内重算）
        if self._dup_on:
            self._model.set_filter_state(dup_only=True)
            self._run_background_filter()
        # 备份：tsv 在加载时（即软件打开后该文件被改动前的底）快照一次（整会话去重）
        backup_mod.open_snapshot(self._current_path)
        self._populate_groups(self._model)   # tsv 模式也填充左侧分组面板（拖拽目标+筛选）
        self._refresh_combos()
        self._refresh_title()
        self._update_status()
        self._refresh_action_buttons()
        # 数据落定后按默认比例重铺列宽：防止长词组等内容把列撑大（内容截断显示）；仅手动拖拽可改宽。
        # 延迟到布局稳定后再执行，规避分组面板 show 后视口变窄、按旧宽算的列宽溢出裁掉「启用」列。
        QTimer.singleShot(0, self._fit_columns_to_view)
        # ① 修复：加载完成时覆盖「加载中…」状态栏消息，否则它会永久残留
        # （_update_status 只改右侧标签、不碰 statusBar）。
        # M3：若加载时发现超 5 列的行，状态栏持久提示（而非仅加载时的瞬时闪现）。
        overflow = (extras or {}).get("overflow_lines", 0)
        if overflow:
            self.statusBar().showMessage(
                f"已加载 {total:,} 行；注意 {overflow:,} 行字段超过 5 列，多余字段已忽略", 8000)
        else:
            self.statusBar().showMessage(f"已加载 {total:,} 行", 5000)

    def _load_dict(self, path):
        # P0 修复（用户反馈：tsv→dict→转回 tsv 时 tsv 卡在"加载中"）：切换文件前先停掉并清空上一文件
        # 的后台线程（尤其是仍在跑的 tsv 加载线程）。否则：(1) 旧 LoadThread 的迟到 loaded 会落入 dict
        # 模型导致 _on_tsv_loaded 在 RimeDictModel 上调用 set_all_data 抛 AttributeError；(2) 旧线程
        # 经 finished→deleteLater 删除后 self._thread 仍指向已销毁的 C++ 对象，下次 _load_tsv 调
        # _stop_background_threads 时 isRunning() 抛 RuntimeError，使整次加载中断、永久卡"加载中"。
        # 清空 self._thread/self._filter_thread 后，旧线程迟到信号会被 _on_tsv_loaded 的 sender 守卫丢弃。
        self._stop_background_threads()
        self._thread = None
        self._filter_thread = None
        model = RimeDictModel()
        try:
            model.load(path)
        except OSError as exc:
            critical(self, "错误", f"无法读取词典：\n{exc}")
            return
        # 备份：6 个 Rime 词典打开时（被操作前的底）快照一次（整会话去重，前缀 Rime-）
        backup_mod.open_snapshot(path, "Rime-")
        self._set_model(model, "dict", path)

    def _on_load_error(self, msg):
        # 竞态防护：与 _on_tsv_loaded 同理
        sender = self.sender()
        if sender is not self._thread:
            return
        self.statusBar().showMessage(msg)
        critical(self, "错误", msg)

    # ---------- 表头排序持久化（#90） ----------
    def _on_sort_changed(self, column, order):
        """记录表头排序偏好到 QSettings，跨会话/重开文件保持。"""
        # 排序会同步改写 _order；失效在途的后台筛选结果，避免其回写覆盖排序结果
        self._invalidate_filter()
        QSettings().setValue("table/sortColumn", column)
        QSettings().setValue("table/sortOrder", int(order))

    def _restore_sort_state(self):
        """重开 TSV 时恢复上次表头排序；无记录则保持默认顺序。"""
        col = QSettings().value("table/sortColumn", -1, type=int)
        if col is None or col < 0:
            return
        order = QSettings().value("table/sortOrder", int(Qt.AscendingOrder), type=int)
        self.tableView.sortByColumn(col, Qt.SortOrder(order))

    # ---------- 顶部五框 ----------
    def _on_selection_changed(self, selected, _deselected):
        rows = self._selected_view_rows()
        self._refresh_action_buttons()     # 选中数变化即重算「移动到」按钮
        self._update_status()              # 状态栏「选 N」实时更新
        if not rows or self._model is None:
            return
        # 多选（≥2 行）→ 清空五框（不绑单行，避免误填）
        if len(rows) >= 2:
            self._clear_fields()
            return
        view_row = rows[0]
        self._updating = True
        try:
            self.editWord.setText(self._model.get_field(view_row, "词组"))
            self.editCode.setText(self._model.get_field(view_row, "编码"))
            self.editWeight.setText(self._model.get_field(view_row, "权重"))
            if self._current_kind == "tsv":
                g = self._model.get_field(view_row, "分组")
                e = self._model.get_field(view_row, "启用")
                if g:
                    self.comboGroup.setCurrentText(g)
                else:
                    self.comboGroup.setCurrentIndex(-1)   # 未填 → 显示「分组」占位
                if e:
                    self.comboEnable.setCurrentText(e)
                else:
                    self.comboEnable.setCurrentIndex(-1)  # 未填 → 显示「启用」占位
            else:
                self.comboGroup.setCurrentIndex(-1)
                self.comboEnable.setCurrentIndex(-1)
        finally:
            self._updating = False

    # ---------- 五框联动逻辑 ----------
    def _field_for_widget(self, widget):
        for f, w in self._field_widgets.items():
            if w is widget:
                return f
        return None

    def _on_text_edited(self):
        """输入框被编辑：
        - 筛选态（无选中行）：记录筛选条件并防抖重筛；
        - 编辑态（已选中行）：仅更新显示，不重筛、不实时写回（写回在保存时作用于选中行）。"""
        if self._updating:
            return
        if self._selected_view_rows():
            return  # 编辑态：改框只改显示，等保存时写回选中行
        self._record_filter_state()
        self._schedule_filter()

    def _on_combo_changed(self):
        """下拉选择：
        - 筛选态（无选中行）：级联限制选项 + 记录筛选条件 + 防抖重筛；
        - 编辑态（已选中行）：仅更新显示，不级联/不重筛（保存时写回选中行）。"""
        if self._updating:
            return
        if self._selected_view_rows():
            self._auto_group_on_enable_a()
            return  # 编辑态：改框只改显示，等保存时写回选中行
        field = self._field_for_widget(self.sender())
        self._refresh_cascading(field)
        self._record_filter_state()
        self._schedule_filter()

    def _auto_group_on_enable_a(self):
        """编辑态：当用户把「启用」改为 A 时，在五框内自动关联一个分组名，方便少选一次：
        - 当前分组以 E 开头 → 关联为 `E Google一万`
        - 其它            → 关联为 `B 青云`
        仅在选中单行时生效；仅此一个联动——只是填充「分组」框、不锁定（用户仍可改选其它分组），
        不触发任何自动保存（保存始终手动），也不反向联动其它框（词组/编码/权重/启用）。"""
        if self.sender() is not self.comboEnable:
            return                      # 仅响应「启用」框的改动（避免词组/编码/权重/分组改动误触发）
        if self._updating:
            return
        rows = self._selected_view_rows()
        if len(rows) != 1:
            return                      # 仅单选行编辑态生效（多选清空五框，无单行可写回）
        if self.comboEnable.currentText().strip() != "A":
            return                      # 仅当启用改为 A
        cur_group = self.comboGroup.currentText().strip()
        target = "E Google一万" if cur_group.upper().startswith("E") else "B 青云"
        # 仅填充「分组」框（不锁定：用户仍可改选其它分组）；不自动保存、不联动其它框
        self._updating = True
        try:
            self.comboGroup.setCurrentText(target)
        finally:
            self._updating = False

    def _record_filter_state(self):
        """把当前五框值记为「筛选态」快照（用于保存后复位五框、回到最初筛选结果）。"""
        self._filter_state = self._gather_fields()

    def _write_back_row(self, view_row):
        """把五框当前值写回指定可见行（tsv 可写；dict 只读不走此路）。
        写全部非空框值 → 启用+分组等多值一次写回（满足「写回所有修改过的值」）。"""
        if self._model is None or self._current_kind != "tsv":
            return
        fields = self._gather_fields()
        if not any(fields.values()):
            return
        if not (0 <= view_row < self._model.rowCount()):
            return
        # 防御修复②：写回前校验五框「词组」与选中行当前词组一致，不一致说明
        # 行号已漂移（如拖拽后未迁移选区、或用户已另选行），整行拒绝写回，避免把
        # A 词条的编辑内容误写到 B 行、制造重复词条。让用户重新点选后再编辑。
        word = fields.get("词组", "")
        cur = self._model.get_field(view_row, "词组") if word else ""
        if word and cur is not None and word != cur:
            self.statusBar().showMessage(
                "选中行已变化（五框词组与目标行不符），跳过该行写回，请重新点选后再编辑",
                4000,
            )
            return
        for f, col in self._model.FIELD_COLS.items():
            v = fields[f]
            if not v:
                continue
            if self._model.get_field(view_row, f) != v:
                self._model.set_field(view_row, f, v)

    def _write_back_rows_batch(self, view_rows):
        """多选批量写回：仅写回顶栏的「分组」「启用」两下拉字段（安全批改字段），
        不碰 词组/编码/权重（避免把同一值误写到所有选中行）。返回实际发生改动的行数。"""
        if self._model is None or self._current_kind != "tsv":
            return 0
        fields = self._gather_fields()
        group = fields.get("分组", "")
        enable = fields.get("启用", "")
        if not group and not enable:
            return 0
        changed = 0
        for vr in view_rows:
            if not (0 <= vr < self._model.rowCount()):
                continue
            row_changed = False
            if group and self._model.get_field(vr, "分组") != group:
                self._model.set_field(vr, "分组", group)
                row_changed = True
            if enable and self._model.get_field(vr, "启用") != enable:
                self._model.set_field(vr, "启用", enable)
                row_changed = True
            if row_changed:
                changed += 1
        return changed

    def _restore_filter_boxes(self):
        """把五框复位为「筛选态」快照（保留完整筛选条件，清空编辑时改的值）。"""
        self._updating = True
        try:
            st = self._filter_state or {}
            for f, w in self._field_widgets.items():
                v = st.get(f, "")
                if isinstance(w, QLineEdit):
                    w.setText(v)
                else:
                    if v:
                        w.setCurrentText(v)
                    else:
                        w.setCurrentIndex(-1)
        finally:
            self._updating = False

    def _clear_fields(self):
        """清空全部五框（加载新文件时调用）。"""
        self._updating = True
        try:
            for w in self._field_widgets.values():
                if isinstance(w, QLineEdit):
                    w.setText("")
                else:
                    w.setCurrentIndex(-1)   # 下拉回未选 → 显示占位标题
        finally:
            self._updating = False

    def _schedule_filter(self):
        """防抖：停止输入 300ms 后才真正筛选表格，避免逐字刷新卡顿（大词库尤甚）。"""
        if self._model is None:
            return
        self._filter_timer.start(300)

    def _apply_filter_now(self):
        if self._model is None:
            return
        fields = self._gather_fields()
        if self._current_kind == "tsv":
            # 大词库：仅设状态 + 后台线程算新顺序，主线程不再全表扫描（避免卡顿）。
            self._model.set_filter_state(field=fields)
            self._run_background_filter()
        else:
            # dict 模式：原先走同步 apply_field_filter，会与「点分组」的后台 RimeGroupThread 共享 token
            # 互相覆盖（分组线程用点击时刻快照 field={} 算完提交，把刚输入的字段筛选冲掉）。
            # 改为与 tsv 一致：set_filter_state 后统一走 _run_background_filter（重新快照+重新 token，
            # 同时停掉在途分组线程），既修复竞态、又避免中大型 Rime 词典同步全表扫描卡顿。
            self._model.set_filter_state(field=fields)
            self._run_background_filter()

    def _invalidate_filter(self):
        """使在途的后台筛选结果作废（代号自增），用于同步重建入口（增删/移动/合并/排序）。"""
        self._filter_token += 1

    def _run_background_filter(self, autofill=True):
        """发起一次后台筛选：快照当前筛选态，交给后台线程预算新顺序；
        仅当结果代号与最新一致、且模型未切换（未重载）才 commit（丢弃过期/迟到结果）。
        tsv(DictModel) 与 dict(RimeDictModel) 共用此路径，按模型类型选用对应计算线程（P1-⑤ 扩展）。
        autofill: 计算完成后是否对「唯一结果」自动回填五框。顶部五框筛选用 True（结果唯一即填好方便微调）；
        选分组（_on_group_clicked）传 False，遵循「选分组→清空五框」规则，避免唯一词条被误填。"""
        if self._model is None:
            return
        self._filter_token += 1
        token = self._filter_token
        filters = self._model.snapshot_filters()
        # H1 修复：仅当存在「拖拽重排」脏标记时才固化拖拽改动（_order → _all_data）。
        # 表头排序也会置 _order_dirty，但筛选基于值、与物理序无关，无需预同步；
        # 若不分流，百万行词库点击分组会触发 1.6M 全量 _sync_order_to_data 卡顿（P1-① 连带修复）。
        if getattr(self._model, "_drag_dirty", False):
            self._model._sync_order_to_data()
        expected = self._model
        from core.io_tsv import FilterThread, RimeGroupThread
        # P0-1 修复：再次发起筛选前，停掉上一个可能仍在跑的筛选线程（防连点/快速切换）。
        self._stop_background_threads()
        # 竞态修复（追加崩溃根因）：后台线程必须操作「启动前拷贝的不可变快照」，而非与主线程
        # 共享的 self._model._all_data 引用。否则追加新行（主线程 append/重排 _all_data）与子线程
        # 遍历同一 list 并发，会触发 C 层 list 迭代器失效段错误——表现即「追加一个词组到 tsv 后
        # 程序直接退出」。快照在 _run_background_filter 主线程内 list() 拷贝，与后续任何改写隔离。
        if isinstance(self._model, RimeDictModel):
            data = list(self._model._all_data)
            row_group = list(self._model._row_group)
            th = RimeGroupThread(data, row_group, filters)
        else:
            data = list(self._model._all_data)
            th = FilterThread(data, filters)
        th.finished_order.connect(
            lambda order, t=token, af=autofill, m=expected:
                self._on_filter_computed(order, t, af, m))
        # P0 修复：FilterThread / RimeGroupThread 的 error 信号此前无人接收 → compute_filtered_order /
        # compute_rime_order 抛错被静默吞掉，表格停留旧/错误顺序、状态栏无提示（pythonw 下完全不可见，
        # 用户误以为"筛选没反应"）。此处接上，把失败暴露到状态栏+日志，让"无反应"变成"可见错误"。
        th.error.connect(lambda m: self._on_filter_error(m))
        th.finished.connect(th.deleteLater)
        self._filter_thread = th
        th.start()

    def _on_filter_computed(self, order, token, autofill=True, expected_model=None):
        # 模型已切换（重载/切换文件）：丢弃迟到结果，避免把旧模型的顺序写回新模型造成数据错乱。
        if expected_model is not None and self._model is not expected_model:
            return
        if token != self._filter_token:
            return  # 过期结果，丢弃（已有更新的筛选或同步重建）
        if self._model is None:
            return
        self._model.commit_order(order)
        self._update_status()
        if autofill:
            self._autofill_unique()   # 仅顶部五框筛选（autofill=True）时回填唯一结果；选分组时跳过
        self.statusBar().showMessage("筛选计算完成", 2000)   # 后台筛选落定：状态栏给出完成提示

    def _on_filter_error(self, msg):
        """后台筛选线程异常兜底（见 _run_background_filter 的 error 连接）。

        io_tsv 的 error 信号消息已带语境前缀（"筛选失败：…" / "分组筛选失败：…"），此处不再重复加前缀。"""
        _log.warning("后台筛选失败：%s", msg)
        self.statusBar().showMessage(msg, 5000)

    def _autofill_unique(self):
        """筛选后：仅当结果集精确为 1 行（数据行，不含分组头）时，把其余空框填入该行对应值。
        多行结果不自动填充——否则清空某框后会被「唯一值」反复回填，导致组合筛选无法放松。"""
        if self._model is None:
            return
        # 仅统计数据行（分组头行 ("H",...) 不计入）；结果集唯一时取首个数据行回填
        data_rows = [e for e in self._model._order if isinstance(e, int)]
        if len(data_rows) != 1:
            return
        row = self._model._all_data[data_rows[0]]
        self._updating = True
        try:
            for f, col in self._model.FIELD_COLS.items():
                w = self._field_widgets[f]
                cur = w.text().strip() if isinstance(w, QLineEdit) else w.currentText().strip()
                if cur:
                    continue  # 用户已填，跳过
                v = row[col]
                if not v:
                    continue
                if isinstance(w, QLineEdit):
                    w.setText(v)
                else:
                    w.setCurrentText(v)
        finally:
            self._updating = False

    def _refresh_cascading(self, which):
        """级联：另一个下拉只列与当前下拉所选值共现的选项（保留其已选值）。"""
        if self._model is None or self._current_kind != "tsv":
            return
        other = "启用" if which == "分组" else "分组"
        which_widget = self._field_widgets[which]
        other_widget = self._field_widgets[other]
        which_val = which_widget.currentText().strip()
        cols = {"分组": self._model.FIELD_COLS["分组"], "启用": self._model.FIELD_COLS["启用"]}
        if not which_val:
            # 清空选择 → 恢复该下拉的完整选项
            self._updating = True
            other_widget.clear()
            other_widget.addItems([""] + self._model.distinct_values(cols[other]))
            self._updating = False
            return
        col_which = cols[which]
        col_other = cols[other]
        vals = sorted({
            row[col_other]
            for row in self._model._all_data
            if row[col_which] == which_val and row[col_other]
        })
        prev = other_widget.currentText()  # 保留链式选择
        self._updating = True
        other_widget.clear()
        other_widget.addItems([""] + vals)
        if prev in vals:
            other_widget.setCurrentText(prev)
        self._updating = False

    def _refresh_combos(self):
        if self._model is None:
            return
        # 用 _updating 抑制 clear()/addItems() 触发的 combo 信号副作用：
        # 否则每次 rebuild 下拉都会误触发 _on_combo_changed → 级联筛选/意外发起后台筛选
        # （尤其拖到分组等路径会反复调用本方法）。
        self._updating = True
        try:
            if self._current_kind == "tsv":
                self.comboGroup.setEnabled(True)
                self.comboEnable.setEnabled(True)
                # 分组下拉直接取加载时预算好的去重缓存（_distinct_groups_cache），
                # 免主线程再扫全表（1.6M 行 distinct_values 扫描耗时，是启动拖慢的元凶之一）
                groups = [""] + list(self._model.get_distinct_groups())
                enables = [""] + self._model.distinct_values(self._model.FIELD_COLS["启用"])
                self.comboGroup.clear()
                self.comboGroup.addItems(groups)
                self.comboGroup.setCurrentIndex(-1)   # 未选 → 显示「分组」占位
                self.comboEnable.clear()
                self.comboEnable.addItems(enables)
                self.comboEnable.setCurrentIndex(-1)  # 未选 → 显示「启用」占位
            else:
                self.comboGroup.setEnabled(False)
                self.comboEnable.setEnabled(False)
                self.comboGroup.clear()
                self.comboEnable.clear()
        finally:
            self._updating = False

    def _gather_fields(self):
        return {
            "词组": self.editWord.text().strip(),
            "编码": self.editCode.text().strip(),
            "权重": self.editWeight.text().strip(),
            "分组": self.comboGroup.currentText().strip() if self.comboGroup.isEnabled() else "",
            "启用": self.comboEnable.currentText().strip() if self.comboEnable.isEnabled() else "",
        }

    def _all_boxes_filled(self):
        """五框是否全部填写（词组/编码/权重/分组/启用 均非空）。用于判断用户是否在『新增词条』。"""
        f = self._gather_fields()
        return all(f[k] for k in ("词组", "编码", "权重", "分组", "启用"))

    def on_add(self):
        if self._model is None:
            return
        # 已加载 tsv 词库：合并「五笔编码」入口，弹对话框。
        # 五框齐全 → 抄送预填（编码预填为自由编码，确认即添加）；不全 → 空对话框手动输入。
        if self._current_kind == "tsv":
            fields = self._gather_fields()
            all_filled = all(fields[k] for k in ("词组", "编码", "权重", "分组", "启用"))
            self._open_wubi_dialog(prefill=fields if all_filled else None)
            return
        # 非 tsv（如 dict 只读）保持原直接添加逻辑
        fields = self._gather_fields()
        if not fields["词组"] or not fields["编码"]:
            info(self, "提示", "「词组」和「编码」不能为空")
            return
        new_row = self._model.add_row_fields(fields)
        self._model.clear_filter()
        self._reset_filter_buttons()   # dict 模式按钮本就禁用，此处复位保持状态一致
        self._filter_state = {}       # 添加后筛选清空
        self._refresh_combos()
        self.tableView.selectRow(new_row)
        self._update_status()
        self.statusBar().showMessage("已添加一行（未保存）")

    def on_search(self):
        if self._model is None:
            return
        self._record_filter_state()
        self._apply_filter_now()

    def on_clear_filter(self):
        """清空顶部五框全部筛选条件，表格恢复显示全部行（dict 同时复位左侧分组选择）。"""
        if self._model is None:
            return
        self._updating = True
        try:
            self._clear_fields()
            if self._current_kind == "tsv":
                # 大词库：仅设状态 + 后台算新顺序，主线程不再全表扫描
                self._model.set_filter_state(text="", field={}, group="", incomplete=False, char_count=-1, multi_code=False, dup_only=False)
                self._run_background_filter()
            else:
                self._model.clear_filter()
            self._reset_filter_buttons()   # 清除筛选时同步复位筛选型按钮（模型状态已由 clear_filter 重置）
            # 复位重复项筛选按钮（模型状态已随 dup_only=False / clear_filter 重置）
            self._dup_on = False
            self.btnDupHighlight.setText("🔍 重复项筛选")
            _apply_btn_class(self.btnDupHighlight, "btn-ghost")
            self._filter_state = {}    # 筛选已清，快照同步清空
            self._refresh_combos()     # 程序性复位：_updating 期间不触发联动/级联/筛选
        finally:
            self._updating = False
        # 复位左侧分组选择高亮（tsv 已通过 set_filter_state 清 group，dict 还需同步清模型分组筛选）
        self.groupListWidget.setCurrentRow(0)   # 高亮回「（全部）」
        if self._current_kind == "dict":
            self._model.set_group_filter("")
        self._update_status()
        self.statusBar().showMessage("已清除筛选条件", 3000)

    # ---------- 操作按钮 ----------
    def _persist_tsv(self, success_msg="保存成功"):
        """把内存数据写回 tsv 文件并刷新界面（统一落盘收口：写回/新增/编码窗口补全 都走这里）。

        仅写 tsv（不触发 Rime 部署）；保存后清选中、五框复位为筛选快照、重筛回到最初筛选结果。
        返回是否成功写回。
        """
        # 先提示「保存中…」并立即重绘状态栏，再同步写盘；
        # 写盘任务真正完成后（下方 try 成功分支末尾）才提示「保存成功」，避免「成功」先于写入完成。
        self.statusBar().showMessage("保存中…")
        QApplication.processEvents()   # 让「保存中…」先可见，再进入可能阻塞的写盘
        try:
            self._model._sync_order_to_data()   # 方案①：写盘前把拖拽改动的 _order 固化回 _all_data
            ok = write_tsv(self._current_path, self._model.rows())
        except OSError as exc:
            critical(self, "保存失败", str(exc))
            self.statusBar().showMessage("保存失败", 3000)
            return False
        if not ok:
            critical(self, "保存失败", "写入失败")
            self.statusBar().showMessage("保存失败", 3000)
            return False
        self._model.mark_clean()
        self.tableView.clearSelection()
        self._restore_filter_boxes()
        self._apply_filter_now()   # 刷新中间列表，回到最初筛选结果
        self._update_status()
        self._flash_status(f"{success_msg}：{self._current_path}", "ok")
        self._flash_save_success()      # 短暂切到绿色背景状态样式（不改按钮文字）
        return True

    def on_save(self, interactive=True):
        """「保存」= 保存当前状态（仅写 tsv；任何情况都不弹窗口）。

        - 若选中了行且五框有内容 → 先把五框编辑写回选中行（分组/启用等）；
        - 排序 / 拖入分组等内存改动已体现在 _all_data，统一在此落盘；
        - 新增词条改走右侧栏「新建编码」按钮，不在此处弹编码窗口。
        写回后由 _persist_tsv 统一（清选中、复位五框、重筛、状态栏提示 + 保存按钮绿色闪烁）。
        """
        if self._model is None or not self._current_path:
            return
        if self._current_kind != "tsv":
            # dict 只读预览：保持原 model.save 逻辑
            self.statusBar().showMessage("保存中…")
            QApplication.processEvents()
            try:
                ok = self._model.save(self._current_path)
            except OSError as exc:
                critical(self, "保存失败", str(exc))
                self.statusBar().showMessage("保存失败", 3000)
                return
            if ok:
                self._model.mark_clean()
                self._flash_status(f"保存成功：{self._current_path}", "ok")
                self._flash_save_success()
            else:
                critical(self, "保存失败", "写入失败")
                self.statusBar().showMessage("保存失败", 3000)
            return
        # tsv：写回选中行编辑（五框有内容时），随后统一落盘当前状态
        rows = self._selected_view_rows()
        if len(rows) >= 2:
            n = self._write_back_rows_batch(rows)
            if n:
                self.statusBar().showMessage(f"已批量改 {n} 行（分组/启用）", 2000)
        elif len(rows) == 1:
            self._write_back_row(rows[0])
        else:
            # 未选中任何行：若五框已填满，用户意图是「新增词条」，但「保存」按钮不负责新增
            # （新增走右侧栏「新建编码」按钮，且会预填当前五框）。弹提示引导，避免误以为已保存。
            if self._all_boxes_filled():
                info(
                    self, "新增词条请走「新建编码」",
                    "你已填好五个要素，但「保存」只保存当前词库的编辑（写回选中行 / 排序 / 移动分组等），"
                    "不会新增词条。\n\n要新增这条词，请点右侧栏的「➕ 新建编码」按钮——你刚填的五框内容会预填进去，"
                    "确认后即新增（新增后仍需点「保存」落盘）。")
                return
        self._persist_tsv("保存成功")

    def on_refresh(self):
        if not self._current_path:
            return
        if self._model is None:
            return
        if self._current_kind == "tsv":
            self._load_tsv(self._current_path)   # 重新走线程，丢弃未保存改动
        else:
            self._model.reload()
            self._refresh_combos()
            self._update_status()
            self.statusBar().showMessage("已刷新", 3000)

    def on_delete(self):
        """删除当前选中行（tsv 多选可批量）。按显示行号降序删除，避免索引漂移；删除前确认。
        确认后即**直接落盘**（等价于「删除后点保存」），无需再点「保存」。"""
        if self._model is None or self._current_kind != "tsv":
            return
        rows = self._selected_view_rows()
        if not rows:
            info(self, "提示", "请先选中要删除的行（Ctrl/Shift+点击多选）。")
            return
        n = len(rows)
        # ConfirmBox 支持 Y（确认）/ N（取消）快捷键；返回判定保持原逻辑
        reply = ConfirmBox.ask(
            self, "确认删除",
            f"确定删除选中的 {n} 行吗？\n（确认后将从文件移除并保存）",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        # 批量删除（单次重建 _all_data + _rebuild_order，避免 O(n²)）
        deleted = self._model.delete_rows_by_view(sorted(rows, reverse=True))
        if not deleted:
            return
        self._invalidate_filter()   # 删除同步重建 _order，失效在途后台筛选结果
        # 确认即写文件：统一走 _persist_tsv 落盘 + 刷新（固化排序→写回→清选中→重筛→状态提示），
        # 与「删除后点保存」行为一致，无需用户再点一次「保存」。
        self._persist_tsv(f"已删除 {n} 行并保存")
        # 落盘后补充刷新下拉候选与按钮使能态（_persist_tsv 已清选中并重筛）
        self._refresh_combos()
        self._refresh_action_buttons()

    def on_deploy(self):
        """保存并触发 Rime 部署。本期部署钩子默认等价于保存；外部部署命令可在此扩展。"""
        if self._model is None or not self._current_path:
            return
        self.on_save(interactive=False)
        self.statusBar().showMessage("已保存并请求 Rime 部署（部署钩子预留）")

    def _save_if_dirty(self):
        """导出/批量改权重前，先把内存里未保存的 TSV 编辑落盘，避免后续读取磁盘旧文件时把改动静默丢弃。"""
        if self._current_kind != "tsv" or self._model is None or not self._current_path:
            return
        if not self._model.is_dirty():
            return
        try:
            self._model._sync_order_to_data()   # 方案①：自动保存前固化拖拽改动
            write_tsv(self._current_path, self._model.rows())
            # H2 修复：_sync_order_to_data 已把 _all_data 按 _order 重排，但内存 _order 仍指向旧位置；
            # 不重建会导致显示错乱、且随后再保存会把陈旧 _order 烤回 _all_data 损坏顺序。
            # 与 _persist_tsv 一致，写盘后按当前筛选态重建 _order。
            self._model._rebuild_order()
        except OSError as exc:
            critical(self, "自动保存失败", "操作前自动保存失败：\n%s" % exc)
            return
        self._model.mark_clean()
        self.statusBar().showMessage("已自动保存未落盘的编辑", 3000)

    def on_export_rime(self):
        """按分组导出分发到 Rime 词典。优先使用当前已加载的 TSV（含未保存编辑），不读取旧文件。"""
        # 高危写操作：先二次确认，避免误点把整库导出分发到 Rime 并触发部署。
        if ConfirmBox.ask(
            self, "确认导出到 Rime",
            "将按分组把当前 TSV 导出分发到 Rime 词典并触发重新部署。\n"
            "此操作会写入 Rime 词典（写前自动备份），确定要继续吗？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        ) != QMessageBox.Yes:
            return
        try:
            tsv_path = (self._config or {}).get("tsv_path", "")
            rime_dir = (self._config or {}).get("rime_config_dir", "")
            # 当前内存中正在编辑的 TSV（若有）才是用户看到的真实数据来源；否则回退到配置项
            src_path = self._current_path if (self._current_kind == "tsv" and self._current_path) else tsv_path
            self._save_if_dirty()   # 先把未保存编辑落盘，否则导出会读到不含最新编辑的旧文件
            if not src_path or not os.path.exists(src_path):
                warning(
                    self, "导出到 Rime",
                    "未找到指定的 TSV 文件：\n%s\n请先在『配置』中指定 tsv 文件，或先在左侧打开一个 TSV。" % src_path,
                )
                return
            if not rime_dir:
                warning(
                    self, "导出到 Rime",
                    "未配置 Rime 配置文件夹（rime_config_dir）。\n请先在『配置』中指定。",
                )
                return
            from core.rime_export import export_tsv_to_rime, trigger_rime_deploy
            result = export_tsv_to_rime(src_path, rime_dir)
            lines = []
            if result.get("written"):
                for letter, ginfo in result["written"].items():
                    lines.append("[%s] %s —— %d 条" % (letter, ginfo["path"], ginfo["count"]))
            else:
                lines.append(result.get("message") or "无符合导出条件的数据。")
            if result.get("backups"):
                lines.append("")
                lines.append("已自动备份(.bak.gz)：")
                lines.append("\n".join(result["backups"]))
            # 用户确认：写完后自动触发 Rime 重新部署
            deploy_msg = trigger_rime_deploy(rime_dir)
            lines.append("")
            lines.append("部署：" + deploy_msg)
            info(self, "导出到 Rime", "\n".join(lines))
            self.statusBar().showMessage(
                "已导出到 Rime：%d 条；%s" % (result.get("total", 0), deploy_msg)
            )
        except Exception as exc:  # noqa: BLE001 - 任何意外都弹窗告知，绝不静默吞掉
            _log.exception("导出到 Rime 失败")
            critical(self, "导出到 Rime", "操作失败：\n%s" % exc)

    def on_batch_weight(self):
        """按码表匹配替换权重：读配置 tsv_path（写入文件）与 rime_config_dir（6 个映射文件），
        用 (词组,编码)->最大权重 覆盖第 3 列；自动新增缺失词条；覆盖写回原文件（写前自动备份）。
        不触发 Rime 部署（改的是主 TSV，需再点『导出到Rime』推送）。"""
        # 高危写操作：先二次确认，避免误点直接覆盖写回主 TSV。
        if ConfirmBox.ask(
            self, "确认批量修改 TSV 权重",
            "将按码表匹配替换主 TSV 第 3 列权重，并自动新增缺失词条，覆盖写回原文件（写前自动备份）。\n"
            "确定要继续吗？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        ) != QMessageBox.Yes:
            return
        try:
            tsv_path = (self._config or {}).get("tsv_path", "")
            rime_dir = (self._config or {}).get("rime_config_dir", "")
            # 当前内存中正在编辑的 TSV（若有）才是用户看到的真实数据来源；否则回退到配置项
            src_path = self._current_path if (self._current_kind == "tsv" and self._current_path) else tsv_path
            self._save_if_dirty()   # 先把未保存编辑落盘，否则批量权重会读到不含最新编辑的旧文件
            if not src_path or not os.path.exists(src_path):
                warning(
                    self, "批量修改TSV权重",
                    "未找到指定的 TSV 文件：\n%s\n请先在『配置』中指定 tsv 文件，或先在左侧打开一个 TSV。" % src_path,
                )
                return
            if not rime_dir:
                warning(
                    self, "批量修改TSV权重",
                    "未配置 Rime 配置文件夹（rime_config_dir）。\n请先在『配置』中指定。",
                )
                return
            from core.weight_replacer import replace_weights
            result = replace_weights(src_path, rime_dir)
            if not result.get("ok"):
                warning(
                    self, "批量修改TSV权重",
                    result.get("message") or "未执行（无可用映射文件或写入文件异常）。",
                )
                return

            # H3 修复：replace_weights 已直接改写磁盘 src_path，但内存模型仍是旧权重；
            # 若不重载，表格继续显示旧数据，用户再保存会把批量权重结果覆盖掉。
            # 上方 _save_if_dirty() 已先把内存编辑落盘，此处重载不会丢失未保存改动。
            self._load_tsv(src_path)
            lines = []
            lines.append("写入文件：%s" % result.get("output_path", tsv_path))
            lines.append("替换权重行数：%d" % result.get("replaced", 0))
            lines.append("新增词条行数：%d" % result.get("added", 0))
            cu = result.get("chaos_updated", 0)
            ca = result.get("chaos_added", 0)
            cr = result.get("chaos_removed", 0)
            if cu or ca or cr:
                lines.append("chaos 处理：更新 %d / 新增 %d / 已从 chaos 删除 %d"
                             % (cu, ca, cr))
            lines.append("最终总行数：%d" % result.get("total", 0))
            if result.get("backup"):
                lines.append("")
                lines.append("自动备份(.bak.gz)：%s" % result["backup"])
            if result.get("missing_files"):
                lines.append("")
                lines.append("以下映射文件不存在，已跳过：")
                lines.append("\n".join(result["missing_files"]))
            lines.append("")
            lines.append("提示：权重已写回主 TSV，请点『导出到Rime』推送到 Rime。")
            info(self, "批量修改TSV权重", "\n".join(lines))
            self.statusBar().showMessage(
                "批量修改TSV权重完成：替换 %d / 新增 %d"
                % (result.get("replaced", 0), result.get("added", 0))
            )
        except Exception as exc:  # noqa: BLE001 - 任何意外都弹窗告知，绝不静默吞掉
            _log.exception("批量修改TSV权重失败")
            critical(self, "批量修改TSV权重", "操作失败：\n%s" % exc)

    # ---------- 新增功能模块（需求 1-4） ----------
    def _output_dir(self):
        """返回配置中的默认输出文件夹，并确保其存在。"""
        out = (self._config or {}).get("output_dir", "") or os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "RimeTool", "Outputs",
        )
        try:
            os.makedirs(out, exist_ok=True)
        except OSError:
            _log.debug("创建输出目录失败", exc_info=True)
        return out

    def on_voice_gap(self):
        """🎙️ 语音词组查漏：读配置 voice_file（空则弹窗选 SayIt JSON）+ 基准 tsv_path，写结果到 output_dir。"""
        sayit = (self._config or {}).get("voice_file", "").strip()
        if not sayit:
            sayit, _ = QFileDialog.getOpenFileName(
                self, "选择 SayIt 语音导出 JSON", "",
                "JSON 文件 (*.json);;所有文件 (*.*)")
            if not sayit:
                return
        baseline = (self._config or {}).get("tsv_path", "").strip()
        out = self._output_dir()
        try:
            from core.voice_gap import find_gaps
            res = find_gaps(sayit, baseline, out)
        except Exception as exc:  # noqa: BLE001
            critical(self, "语音词组查漏", "执行失败：\n%s" % exc)
            return
        out_path, summary = res
        if out_path is None:
            warning(self, "语音词组查漏", summary or "未生成结果")
            return
        lines = ["语音词组查漏完成："]
        for k, v in summary.items():
            if k == "输出文件":
                continue
            lines.append("  %s：%s" % (k, v))
        lines.append("")
        lines.append("结果文件：%s" % out_path)
        info(self, "语音词组查漏", "\n".join(lines))
        self.statusBar().showMessage("语音词组查漏完成，结果：%s" % out_path)

    def on_config(self):
        dlg = ConfigDialog(self._config, self)
        # 弹窗显示后再把原生标题栏切暗（与 main.py 主窗口在 win.show() 后切暗同款时序）；
        # QSS 只管客户区背景，标题栏是原生装饰，须走 DWM。
        QTimer.singleShot(0, lambda: self._style_dialog_title(dlg))
        if dlg.exec_() == dlg.Accepted:
            self._config = dlg.get_config()
            save_config(self._config)
            # 主题即时切换（无需重启）：把当前主题应用到整个应用
            from main import apply_theme
            apply_theme(QApplication.instance(), self._config.get("theme", "auto"), self)
            self._apply_fixed_fonts()         # 二次 setStyleSheet 后需重新锁定状态栏/五框字体
            self._build_tree()
            self._auto_load_first()
            self._flash_status("配置已保存并应用", "ok")

    def _style_dialog_title(self, dlg):
        """让弹窗原生标题栏随主题配色（QSS 只管客户区，标题栏需 DWM；offscreen 下静默忽略）。"""
        try:
            from main import title_colors_for, _set_dark_title_bar
            dlg.winId()   # 强制创建原生窗口句柄，确保 DWM 属性可写入
            cap, txt, drk = title_colors_for(self._config.get("theme", "auto"))
            _set_dark_title_bar(dlg, drk, cap, txt)
        except Exception:  # noqa: BLE001 - 设置暗色标题栏失败静默忽略
            _log.debug("设置暗色标题栏失败", exc_info=True)

    # ---------- 状态 / 标题 ----------
    def _refresh_title(self):
        name = os.path.basename(self._current_path) if self._current_path else "未打开"
        title = f"词库工具箱 · 工作区 - {name}"
        if self._model is not None and self._model.is_dirty():
            title += "（已修改）"
        self.setWindowTitle(title)

    def _update_status(self):
        if not hasattr(self, "_lblTotalNum"):
            return
        if self._model is None:
            self._lblTotalNum.setText("0")
            self._lblShownNum.setText("0")
            self._lblSelNum.setText("0")
            self._lblFile.setText("")
            return
        total = self._model.total_count()
        shown = self._model.filtered_count()   # 仅数据行（不含分组头）
        sel = len(self._selected_view_rows())
        self._lblTotalNum.setText(f"{total:,}")
        # 「显」仅在显式总数≠显示数时才有意义
        self._lblShown.setText("· 显" if shown != total else "")
        self._lblShownNum.setText(f"{shown:,}" if shown != total else "")
        self._lblSelNum.setText(f"{sel:,}")
        # 仅有选中行时显式「· 选」
        self._lblSel.setText("· 选" if sel > 0 else "")
        # 文件名（右侧）
        name = os.path.basename(self._current_path) if self._current_path else ""
        suffix = ""
        if self._current_kind == "dict":
            suffix = "  (dict 只读)"
        self._lblFile.setText(f"{name}{suffix}")

    # ---------- 关闭提示 ----------
    def closeEvent(self, event):
        if self._model is not None and self._model.is_dirty():
            msg = ConfirmBox(self)
            msg.setIcon(QMessageBox.Question)
            msg.setWindowTitle("提示")
            msg.setText("数据已修改，是否保存？")
            btn_save = msg.addButton("保存并退出", QMessageBox.AcceptRole)
            btn_discard = msg.addButton("不保存退出", QMessageBox.DestructiveRole)
            msg.addButton("取消", QMessageBox.RejectRole)
            msg.setDefaultButton(btn_save)
            apply_box_style(msg)
            msg.exec_()
            # Y → 保存并退出(AcceptRole)；N → 取消(RejectRole)，绝不绑到「不保存退出」
            clicked = msg.clickedButton()
            if clicked == btn_save:
                self.on_save(interactive=False)
                self._save_geometry()
                self._stop_background_threads(wait_ms=3000)  # P0-1：退出前停线程，阻塞等其收尾
                event.accept()
            elif clicked == btn_discard:
                self._save_geometry()
                self._stop_background_threads(wait_ms=3000)
                event.accept()
            else:
                event.ignore()
        else:
            self._save_geometry()
            self._stop_background_threads(wait_ms=3000)
            event.accept()
