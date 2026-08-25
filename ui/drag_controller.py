# 文件：ui/drag_controller.py
"""拖拽控制器：接管表格拖拽过程，提供 Excel 式交互反馈。

替换原有的 Qt 内置拖拽实现，解决：
1. 深浅主题无区别（拖拽指示线使用主题色）
2. 非连续选区视觉反馈错误
3. 自动滚动时指示器错位
4. 焦点丢失误取消
5. 分组头拖拽语义不一致
"""

from PyQt5.QtCore import (
    QObject, QEvent, QTimer, Qt, QPoint, QRect, pyqtSignal
)
from PyQt5.QtWidgets import (
    QFrame, QLabel, QTableView, QApplication, QStyledItemDelegate
)
from PyQt5.QtGui import QPainter, QColor

from core.config import theme_dict, get_active_theme_name

import logging
_log = logging.getLogger(__name__)

# 分组项「拖入目标」标记角色：经自定义 delegate 绘制高亮，
# 因为 style.qss 的 ::item 规则会覆盖 QListWidgetItem.setBackground()
# （BackgroundRole 在套用样式表后不再被绘制），故高亮必须走 delegate 而非 setBackground。
DRAG_TARGET_ROLE = Qt.UserRole + 137

# 拖拽反馈统一使用「当前激活主题」的主色（core.config.theme_dict 的 primary），
# 跟随浅/深主题切换自动变化，避免写死浅色主色。旧实现在模块导入时固定取
# THEME["primary"]，导致深色主题下拖拽线仍是蓝色。颜色在 __init__ 与每次拖拽开始时
# 按当前主题重算（详见 _refresh_drag_color / _compute_drag_colors）。


class _GroupListDragDelegate(QStyledItemDelegate):
    """分组面板专属 delegate：仅当某项被标记为拖入目标时，绘制主色实心高亮 + 白字。

    其余项完全委托默认绘制（保留 style.qss 的 hover/selected 样式），因此零副作用。
    主色跟随当前激活主题（self._drag_hex / self._drag_rgb 由 DragController 写入）。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        # 默认紫，实际由 DragController._refresh_drag_color 按当前主题覆盖
        self._drag_hex = "#7f6df2"
        self._drag_rgb = (127, 109, 242)

    def paint(self, painter, option, index):
        is_target = bool(index.data(DRAG_TARGET_ROLE))
        if not is_target:
            super().paint(painter, option, index)
            return
        painter.save()
        rect = option.rect
        painter.fillRect(rect, QColor(*self._drag_rgb))
        painter.setPen(Qt.white)
        painter.setFont(option.font)
        text = index.data(Qt.DisplayRole) or ""
        painter.drawText(
            rect.adjusted(8, 0, 0, 0),
            Qt.AlignLeft | Qt.AlignVCenter,
            str(text),
        )
        painter.restore()


class DragStateMachine:
    """拖拽状态机：管理从按下到释放的完整生命周期，避免状态泄漏"""
    
    IDLE = 0           # 空闲
    PRESSED = 1        # 鼠标按下，等待拖动阈值
    DRAGGING = 2       # 拖动中
    DROPPED = 3        # 已释放（等待落点处理完成）
    
    def __init__(self):
        self.state = self.IDLE
        self.src_rows = []
        self.start_pos = None
        self.target_row = -1
        self.insert_before = True
    
    def transition(self, new_state):
        """状态转换：带合法性检查，禁止非法跳转"""
        valid = {
            self.IDLE:     [self.PRESSED],
            self.PRESSED:  [self.IDLE, self.DRAGGING],
            self.DRAGGING: [self.DROPPED, self.IDLE],
            self.DROPPED:  [self.IDLE],
        }
        if new_state not in valid.get(self.state, []):
            _log.warning(f"非法拖拽状态转换: {self.state} -> {new_state}")
            return False
        self.state = new_state
        return True


class DragController(QObject):
    """拖拽控制器：完全接管表格拖拽，提供 Excel 式交互反馈"""
    
    # 信号
    drag_started = pyqtSignal(list)
    drag_moved = pyqtSignal(int)
    drag_dropped = pyqtSignal(int, bool, list)
    drag_cancelled = pyqtSignal()
    group_drop_requested = pyqtSignal(str)   # 拖到左侧分组面板某分组项：参数为分组名
    
    def __init__(self, table_view: QTableView, group_list_widget=None):
        super().__init__(table_view)
        self._view = table_view
        self._group_list_widget = group_list_widget  # 左侧分组面板：拖到某分组项 = 移动分组
        self._connected_model = None   # 仅用于跟踪信号连接；模型一律走 self._view.model()，不缓存（避免被替换后变陈旧/None）

        # 缓存 viewport 指针（关键：viewport() 每次返回新的 Python wrapper，必须缓存才能 is 比较）
        self._viewport = table_view.viewport()

        # 拖拽主色：按当前激活主题计算（不再写死浅色），供下方 frame / 影子 / delegate 使用
        self._drag_hex, self._drag_rgb = self._compute_drag_colors()

        # 分组面板高亮走自定义 delegate（绕过 style.qss 对 setBackground 的覆盖）
        if group_list_widget is not None:
            self._group_delegate = _GroupListDragDelegate(group_list_widget)
            group_list_widget.setItemDelegate(self._group_delegate)
        else:
            self._group_delegate = None

        # 把当前主题主色同步给 delegate（其高亮颜色跟随主题）
        self._refresh_drag_color()

        # 拖到分组面板的落点状态（拖拽期间实时维护）
        self._drop_target_group = None   # 当前悬停命中的分组名，None=无
        self._highlighted_item = None    # 当前被高亮的分组项（用于还原）
        
        # 状态机
        self._sm = DragStateMachine()
        
        # 视觉反馈组件（全部 parent 到 viewport，随滚动自动移动）
        self._insert_line = QFrame(self._viewport)
        self._insert_line.setFixedHeight(3)
        self._insert_line.setStyleSheet(f"background-color: {self._drag_hex};")
        self._insert_line.setVisible(False)
        self._insert_line.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        
        # 拖拽影子：为每行单独一个 Frame（解决非连续选区问题）
        self._drag_shadows = []  # list[QFrame]
        
        # 拖拽手柄（显示行数，跟随鼠标）
        self._drag_handle = QLabel(self._viewport)
        self._drag_handle.setFixedSize(24, 24)
        self._drag_handle.setStyleSheet(f"""
            QLabel {{
                background-color: {self._drag_hex};
                border-radius: 12px;
                color: white;
                font-weight: bold;
                font-size: 11px;
            }}
        """)
        self._drag_handle.setAlignment(Qt.AlignCenter)
        self._drag_handle.setVisible(False)
        self._drag_handle.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        
        # 分组头高亮
        self._group_header_highlight = QFrame(self._viewport)
        self._group_header_highlight.setStyleSheet(f"""
            QFrame {{
                background-color: rgba({self._drag_rgb[0]}, {self._drag_rgb[1]}, {self._drag_rgb[2]}, 0.3);
                border: 2px solid {self._drag_hex};
            }}
        """)
        self._group_header_highlight.setVisible(False)
        self._group_header_highlight.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        
        # 自动滚动定时器（替代 MouseMove 中直接滚动）
        self._auto_scroll_timer = QTimer(self)
        self._auto_scroll_timer.setInterval(30)
        self._auto_scroll_timer.timeout.connect(self._on_auto_scroll_tick)
        self._auto_scroll_direction = 0  # -1=上, 0=停, +1=下
        
        # 模型重置保护
        self._model_reset_pending = False

    def _compute_drag_colors(self):
        """按当前激活主题返回 (hex, rgb) 主色，供拖拽视觉使用。"""
        th = theme_dict(get_active_theme_name())
        hex_ = th["primary"]
        return hex_, QColor(hex_).getRgb()[:3]

    def _refresh_drag_color(self):
        """重算当前主题主色，并同步给分组面板 delegate。

        在 __init__ 与每次拖拽开始时调用，确保运行时切换主题后拖拽线立即跟随。
        """
        self._drag_hex, self._drag_rgb = self._compute_drag_colors()
        if self._group_delegate is not None:
            self._group_delegate._drag_hex = self._drag_hex
            self._group_delegate._drag_rgb = self._drag_rgb

    def install(self):
        """安装拖拽控制器：完全替换现有拖拽"""
        # 禁用 Qt 内置拖拽
        self._view.setDragEnabled(False)
        self._view.setAcceptDrops(False)
        self._view.setDragDropMode(QTableView.NoDragDrop)
        
        # 移除现有事件过滤器（如果存在）
        parent = self._view.parent()
        if parent and hasattr(parent, 'eventFilter'):
            self._view.removeEventFilter(parent)
        
        # 安装本控制器
        self._view.installEventFilter(self)
        self._viewport.installEventFilter(self)
        
        # 监听模型重置（模型可能被后续 _set_model/_load_tsv 替换，统一由 bind_model 维护连接）
        self.bind_model(self._view.model())

    def bind_model(self, model):
        """（重新）绑定模型信号。

        DragController 不再缓存模型对象（缓存会在模型被替换后变陈旧，
        导致拖拽时访问陈旧/None 的 _order 而崩溃）。模型访问一律走
        self._view.model()（实时）。本方法仅负责 modelAboutToBeReset /
        modelReset 信号的连接维护，并在模型替换时先断开旧连接，避免重复连接。
        """
        old = self._connected_model
        if old is not None:
            try:
                old.modelAboutToBeReset.disconnect(self._on_model_about_to_reset)
                old.modelReset.disconnect(self._on_model_reset_complete)
            except Exception:
                pass
        self._connected_model = model
        if model is not None:
            model.modelAboutToBeReset.connect(self._on_model_about_to_reset)
            model.modelReset.connect(self._on_model_reset_complete)

    def uninstall(self):
        """卸载拖拽控制器"""
        self._view.removeEventFilter(self)
        self._viewport.removeEventFilter(self)
        self._view.setDragEnabled(True)  # 恢复 Qt 内置拖拽
    
    def eventFilter(self, obj, event):
        """事件过滤：处理鼠标和拖拽事件（表格本身 / 视口）。

        拖拽中鼠标移到左侧分组面板时，仍由视口事件分支处理：Windows 下左键按住会
        捕获鼠标到按下时的 viewport，MouseMove 持续发给 viewport，故用事件的全局坐标
        （event.globalPos，鼠标捕获下仍准确）判断光标是否悬停在分组项上，不依赖全局
        事件过滤器（那一路在鼠标捕获下不会触发）。
        """
        if obj is self._view:
            return self._filter_table_event(event)
        elif obj is self._viewport:
            return self._filter_viewport_event(event)
        return False
    
    def _filter_table_event(self, event):
        """处理表格事件（键盘、焦点等）"""
        et = event.type()
        
        if et == QEvent.KeyPress:
            if event.key() == Qt.Key_Escape and self._sm.state == DragStateMachine.DRAGGING:
                self._cancel_drag()
                return True
        elif et == QEvent.FocusOut:
            # Bug #5 修复：FocusOut 只停止自动滚动，不取消拖拽
            if self._sm.state == DragStateMachine.DRAGGING:
                self._stop_auto_scroll()
        
        return False
    
    def _filter_viewport_event(self, event):
        """处理视口事件：鼠标事件实际发送给 viewport"""
        et = event.type()
        
        if et == QEvent.MouseButtonPress:
            return self._on_mouse_press(event)
        elif et == QEvent.MouseMove:
            return self._on_mouse_move(event)
        elif et == QEvent.MouseButtonRelease:
            return self._on_mouse_release(event)
        
        return False
    
    def _on_mouse_press(self, event):
        """鼠标按下（修复 Bug #10：不修改选择状态，完全交给 QTableView）"""
        if event.button() != Qt.LeftButton:
            return False
        
        row = self._view.rowAt(event.pos().y())
        if row < 0:
            return False
        
        # 仅记录起始位置，不修改选择状态
        # 选择由 QTableView 原生处理（支持 Ctrl/Shift 多选、范围选中）
        self._sm.start_pos = event.pos()
        self._sm.transition(DragStateMachine.PRESSED)
        
        # src_rows 在进入 DRAGGING 时实时获取（_start_drag 中）
        return False  # 完全交给 QTableView 处理选中
    
    def _on_mouse_move(self, event):
        """鼠标移动（修复 Bug #1, #2, #7）"""
        if self._sm.state != DragStateMachine.PRESSED and self._sm.state != DragStateMachine.DRAGGING:
            return False
        
        # Bug #7 修复：检测左键是否仍按下
        if not (event.buttons() & Qt.LeftButton):
            # 鼠标移出窗口后释放，此处检测到松开
            if self._sm.state == DragStateMachine.DRAGGING:
                self._cancel_drag()
            else:
                self._sm.transition(DragStateMachine.IDLE)
            return False
        
        # 拖动阈值判断
        if self._sm.state == DragStateMachine.PRESSED:
            if (event.pos() - self._sm.start_pos).manhattanLength() < QApplication.startDragDistance():
                return True  # 阈值内也吞掉：避免 Qt 开始橡皮筋圈选
            # 进入拖拽状态
            if not self._sm.transition(DragStateMachine.DRAGGING):
                return True
            self._start_drag()

        # 拖拽中（PRESSED 待拖 / DRAGGING 拖动中）一律吞掉 MouseMove：
        # 阻止 QTableView 的橡皮筋圈选把"鼠标经过的非拖拽行"也高亮（用户反馈的"被圈选"根因）。
        # 仅保留我们自己的玫瑰影子（拖拽源高亮）+ 插入线（落点提示），非拖拽行无任何颜色。
        if self._sm.state == DragStateMachine.DRAGGING:
            self._update_drag_feedback(event.pos())
            return True  # 拦截！

        return False
    
    def _on_mouse_release(self, event):
        """鼠标释放（修复 Bug #7）"""
        if self._sm.state not in (DragStateMachine.PRESSED, DragStateMachine.DRAGGING):
            return False
        
        if self._sm.state == DragStateMachine.PRESSED:
            # 未达到拖动阈值，当作普通点击
            self._sm.transition(DragStateMachine.IDLE)
            return False
        
        # 拖动中释放
        if not self._sm.transition(DragStateMachine.DROPPED):
            return False
        
        self._stop_auto_scroll()
        
        # 执行落点操作
        self._handle_drop(event.pos())
        
        # 清理并回到空闲
        self._clear_drag_feedback()
        self._sm.transition(DragStateMachine.IDLE)
        return False  # 不吞掉事件
    
    def _start_drag(self):
            """开始拖拽（修复 Bug #3：非连续选区）"""
            # 拖拽开始：按当前主题重算主色（运行时切换主题后跟随）
            self._refresh_drag_color()
            # 实时获取当前选中行（支持 Ctrl/Shift 多选）
            self._sm.src_rows = self._get_selected_rows()
            if not self._sm.src_rows:
                self._sm.transition(DragStateMachine.IDLE)
                return
        
            # 清除旧影子
            for shadow in self._drag_shadows:
                shadow.deleteLater()
            self._drag_shadows.clear()
        
            # Bug #3 修复：为每行单独创建影子
            viewport = self._viewport
            for row in self._sm.src_rows:
                shadow = QFrame(viewport)
                shadow.setStyleSheet(f"""QFrame {{
                    background-color: rgba({self._drag_rgb[0]}, {self._drag_rgb[1]}, {self._drag_rgb[2]}, 0.5);
                    border: 2px solid {self._drag_hex};
                }}""")
                shadow.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            
                # 计算影子的几何位置（跟随滚动）
                rect = self._view.visualRect(self._view.model().index(row, 0))
                shadow.setGeometry(0, rect.top(), viewport.width(), rect.height())
                shadow.setVisible(True)
            
                self._drag_shadows.append(shadow)
        
            # 拖拽手柄显示行数
            self._drag_handle.setText(str(len(self._sm.src_rows)))
            self._drag_handle.setVisible(True)
        
            # 设置拖拽态样式类（仅置动态属性；不再对整表 unpolish/polish——
            # 坑1：拖拽中/拖拽起止对整张视图 unpolish/polish 会打断正在进行的拖放并致行隐身）。
            # 拖拽视觉反馈由拖拽阴影 / 插入线 / 手柄叠加层承载，无需整表重排样式。
            if self._view.property("class") != "dragging":
                self._view.setProperty("class", "dragging")
        
            # 重置分组面板落点状态（拖拽开始）
            self._drop_target_group = None
            # 清掉上一次拖拽可能因"拖入成功确认"延迟定时器残留的玫瑰高亮
            self._clear_group_highlight()
        
            self.drag_started.emit(self._sm.src_rows)
    
    def _update_drag_feedback(self, pos):
        """更新拖拽反馈（修复 Bug #4, #6, #8）。

        同时用全局坐标检测光标是否悬停在左侧分组面板的某个分组项上：Windows 下左键
        按住会捕获鼠标到 viewport，MouseMove 持续发给 viewport，但 event.globalPos()
        仍反映真实光标位置，故分组面板命中检测在此统一处理（不依赖全局事件过滤器，
        那一路在鼠标捕获下不会触发）。
        """
        viewport = self._viewport
        global_pos = viewport.mapToGlobal(pos)
        in_viewport = self._cursor_in_viewport(global_pos)

        if not in_viewport:
            # 光标已离开列表区：重排模式关闭（移动功能失效），不显示插入线/不计算 target_row
            self._insert_line.setVisible(False)
            self._hide_group_header_highlight()
            self._sm.target_row = -1
            # 直接高亮「被拖入的目标分组」：仅当压在某一具体分组条目上才高亮该条目
            # （移动分组生效）；面板空白 / 「（全部）」/ 间隙 / 两区域外 → 无高亮（无目标）。
            name = self._group_panel_hit(global_pos)
            if name is not None:
                self._drop_target_group = name
                self._update_group_highlight(name)
                self.drag_moved.emit(-1)
            else:
                if self._drop_target_group is not None:
                    self._drop_target_group = None
                    self._clear_group_highlight()
            # 分组移动模式下隐藏行数手柄：它会被 clamp 到 viewport 左缘，
            # 看起来像一个「阻挡拖拽」的圆点（实际 WA_TransparentForMouseEvents 不拦截事件）。
            self._drag_handle.setVisible(False)
            return

        # 光标在列表区内：列表重排模式（移动功能生效）
        # 清除分组命中记忆
        if self._drop_target_group is not None:
            self._drop_target_group = None
            self._clear_group_highlight()

        # Bug #6 修复：滚动时更新所有影子位置
        for i, row in enumerate(self._sm.src_rows):
            if i < len(self._drag_shadows):
                rect = self._view.visualRect(self._view.model().index(row, 0))
                self._drag_shadows[i].setGeometry(
                    0, rect.top(), viewport.width(), rect.height()
                )
        
        # 更新手柄位置（跟随鼠标，但限制在 viewport 内）
        handle_pos = pos + QPoint(12, -12)
        handle_pos.setX(max(0, min(handle_pos.x(), viewport.width() - 24)))
        handle_pos.setY(max(0, min(handle_pos.y(), viewport.height() - 24)))
        self._drag_handle.move(handle_pos)
        self._drag_handle.setVisible(True)  # 回到列表区内：恢复行数手柄
        
        # 计算目标行
        target_row = self._view.rowAt(pos.y())
        
        # Bug #8 修复：分组头拖拽的视觉语义
        if self._is_group_header(target_row):
            # 拖到分组头：显示分组头高亮，隐藏插入线
            self._show_group_header_highlight(target_row)
            self._insert_line.setVisible(False)
            self._sm.target_row = target_row
            self._sm.insert_before = True  # 分组头特殊标记
        else:
            self._hide_group_header_highlight()
            
            if target_row < 0:
                # 拖到表格末尾
                # B4 修复：用真实全表行数（_order 长度）而非懒加载的 rowCount()，
                # 否则大表下「拖到底部」只落到已加载末尾（~200 行）而非文件真实末尾。
                m = self._view.model()
                order_len = len(getattr(m, "_order", ())) if m is not None else 0
                last_order = max(order_len - 1, 0)
                # 指示线用已加载范围内最末可见行（超出范围 visualRect 无意义）
                vis_last = min(last_order, self._view.model().rowCount() - 1)
                rect = self._view.visualRect(self._view.model().index(vis_last, 0))
                y = rect.bottom()
                self._sm.target_row = last_order
                self._sm.insert_before = False
            else:
                rect = self._view.visualRect(self._view.model().index(target_row, 0))
                mid_y = rect.center().y()
                
                if pos.y() < mid_y:
                    y = rect.top()
                    self._sm.insert_before = True
                    self._sm.target_row = target_row
                else:
                    y = rect.bottom()
                    self._sm.insert_before = False
                    self._sm.target_row = target_row + 1
            
            # 更新指示线位置
            self._insert_line.setGeometry(0, y - 1, viewport.width(), 3)
            self._insert_line.setVisible(True)
        
        # Bug #4 修复：检查是否需要自动滚动
        self._check_auto_scroll(pos)
        
        self.drag_moved.emit(self._sm.target_row)
    
    def _check_auto_scroll(self, pos):
        """检查是否需要启动/停止自动滚动"""
        viewport = self._viewport
        margin = 30
        
        if pos.y() < margin:
            self._auto_scroll_direction = -1
            if not self._auto_scroll_timer.isActive():
                self._auto_scroll_timer.start()
        elif pos.y() > viewport.height() - margin:
            self._auto_scroll_direction = 1
            if not self._auto_scroll_timer.isActive():
                self._auto_scroll_timer.start()
        else:
            self._auto_scroll_direction = 0
            self._auto_scroll_timer.stop()
    
    def _on_auto_scroll_tick(self):
        """自动滚动 tick：滚动后重新计算反馈"""
        scrollbar = self._view.verticalScrollBar()
        speed = 15
        
        if self._auto_scroll_direction == -1:
            new_val = max(scrollbar.minimum(), scrollbar.value() - speed)
        elif self._auto_scroll_direction == 1:
            new_val = min(scrollbar.maximum(), scrollbar.value() + speed)
        else:
            return
        
        scrollbar.setValue(new_val)
        
        # Bug #4 修复：滚动后，用 viewport 中心坐标重新计算反馈
        viewport = self._viewport
        if self._auto_scroll_direction == -1:
            fake_pos = QPoint(self._sm.start_pos.x(), 5)
        else:
            fake_pos = QPoint(self._sm.start_pos.x(), viewport.height() - 5)
        
        self._update_drag_feedback(fake_pos)
    
    def _stop_auto_scroll(self):
        """停止自动滚动"""
        self._auto_scroll_timer.stop()
        self._auto_scroll_direction = 0
    
    def _handle_drop(self, pos):
        """处理落点操作（修复 Bug #8）。

        按松手时光标的全局位置判定动作，两种动作互斥：
        - 光标在列表 viewport 内 → 列表重排（含分组头改分组值）；
        - 光标在 viewport 外、且压在具体分组条目上 → 移动分组；
        - 其余（面板空白 / 「（全部）」/ 间隙 / 两区域外）→ 无操作，绝不落到
          奇怪的重排结果。分组面板命中用全局坐标，即使鼠标被捕获到 viewport
          也能正确识别（见 _update_drag_feedback）。
        """
        # B1 修复：dict 模式（RimeDictModel.kind == 'dict'）模型无 reorder_view_rows /
        # move_selected_to_group，列表内拖拽会崩溃。非 tsv 模型直接忽略本次拖放，不崩溃、无副作用。
        if getattr(self._view.model(), "kind", "") != "tsv":
            self._clear_drag_feedback()
            return
        viewport = self._viewport
        global_pos = viewport.mapToGlobal(pos)
        in_viewport = self._cursor_in_viewport(global_pos)
        # 仅在离开列表区时才去判定分组面板命中（列表区内不可能压在分组条目上）
        on_group_item = self._group_panel_hit(global_pos) if not in_viewport else None

        # 1) 拖到具体分组条目：整组移动（优先，不依赖表格内 target_row）
        if not in_viewport and on_group_item:
            name = on_group_item
            self._drop_target_group = None
            # 拖入成功：保留玫瑰高亮约 0.7 秒作为"拖入成功"视觉确认，
            # 而非立即清除（否则用户看不到任何反馈）。延迟定时器负责还原；
            # 立即清除由 _clear_drag_feedback 中剥离，避免松手瞬间抹掉确认高亮。
            if self._highlighted_item is not None:
                # Bug D 修复：捕获 item 快照，700ms 后只清该特定项，
                # 避免期间再拖拽/取消导致清错或提前清掉新的确认高亮
                item = self._highlighted_item
                QTimer.singleShot(700, lambda it=item: self._clear_group_highlight_item(it))
            # 仅发信号，由 _on_group_drop_requested 统一处理（含 MRU/下拉刷新）。
            # 注意：此处**不要**再直接调 move_selected_to_group——信号已连接，重复调用会让
            # 一次拖放被执行两次（第二次用拖拽开始时的旧 src_rows，可能误改其它行分组）。
            self.group_drop_requested.emit(name)
            return

        # 2) 在列表内：普通重排（含分组头改分组值）
        if in_viewport:
            if self._sm.target_row < 0:
                return

            # 检查是否拖到原位置
            if self._sm.src_rows[0] == self._sm.target_row and self._sm.insert_before:
                return

            m = self._view.model()
            if m is None:
                return

            # Bug #8 修复：分组头拖拽 → 改分组值（并默认把「启用」置 A，与拖到面板一致）
            if self._is_group_header(self._sm.target_row):
                group_name = self._get_group_header_name(self._sm.target_row)
                if group_name:
                    changed, first = m.move_selected_to_group(
                        self._sm.src_rows, group_name, enable_value="A"
                    )
                    # 防御修复①：拖拽落入分组头后，把选区迁到移动后的新位置，
                    # 避免「行号漂移 → 后续把 A 内容误写到 B 行」制造重复。
                    self.drag_dropped.emit(
                        self._sm.target_row, True, [first] if first >= 0 else []
                    )
                    return

            # 普通行重排
            moved, new_view_rows = m.reorder_view_rows(
                self._sm.src_rows,
                self._sm.target_row,
                self._sm.insert_before
            )
            # 防御修复①：把选区迁到重排后的新位置，保证五框回填的是用户刚拖动的行。
            self.drag_dropped.emit(self._sm.target_row, self._sm.insert_before, new_view_rows)
            return

        # 3) 其余（面板空白 / 「（全部）」/ 间隙 / 两区域外）：无操作，
        #    绝不落到奇怪的重排结果
        self._drop_target_group = None
        return
    
    def _cancel_drag(self):
        """取消拖拽"""
        self._stop_auto_scroll()
        # 取消时立即还原分组面板高亮（拖入成功确认的延迟定时器不在此路径）
        self._clear_group_highlight()
        # 清空悬停落点状态，避免残留影响下次拖拽
        self._drop_target_group = None
        self._clear_drag_feedback()
        self._sm.transition(DragStateMachine.IDLE)
        self.drag_cancelled.emit()
    
    def _clear_drag_feedback(self):
        """清除拖拽视觉反馈。

        注：分组面板高亮（_highlighted_item）不在此清除——成功拖入分组后由
        700ms 延迟定时器还原作为"拖入成功"视觉确认；取消拖拽由 _cancel_drag
        显式还原。若此处也清，会抹掉刚松手时的确认高亮。
        """
        # 清除影子
        for shadow in self._drag_shadows:
            shadow.deleteLater()
        self._drag_shadows.clear()
        
        # 隐藏其他组件
        self._insert_line.setVisible(False)
        self._drag_handle.setVisible(False)
        self._group_header_highlight.setVisible(False)

        # 清除拖拽态样式类（同上：不调整表 unpolish/polish，避免破坏拖放/视图）
        if self._view.property("class") != "":
            self._view.setProperty("class", "")
    
    def _on_model_about_to_reset(self):
        """模型即将重置：取消当前拖拽，避免行号失效"""
        if self._sm.state == DragStateMachine.DRAGGING:
            self._cancel_drag()
        self._model_reset_pending = True
    
    def _on_model_reset_complete(self):
        """模型重置完成"""
        self._model_reset_pending = False
    
    def _is_group_header(self, row):
        """检查行是否为分组头"""
        m = self._view.model()
        if m is None:
            return False
        order = getattr(m, "_order", None)
        if order is None or row < 0 or row >= len(order):
            return False
        # 分组头是 ("H", 组名) 元组，而非整数
        return isinstance(order[row], tuple)
    
    def _get_group_header_name(self, row):
        """获取分组头的组名"""
        m = self._view.model()
        if m is None:
            return None
        order = getattr(m, "_order", None)
        if order is None or not (0 <= row < len(order)):
            return None
        item = order[row]
        if isinstance(item, tuple) and item[0] == "H":
            return item[1]
        return None
    
    def _show_group_header_highlight(self, row):
        """显示分组头高亮"""
        rect = self._view.visualRect(self._view.model().index(row, 0))
        self._group_header_highlight.setGeometry(rect)
        self._group_header_highlight.setVisible(True)
    
    def _hide_group_header_highlight(self):
        """隐藏分组头高亮"""
        self._group_header_highlight.setVisible(False)
    
    def _get_selected_rows(self):
        """获取当前选中的行列表"""
        return sorted({idx.row() for idx in self._view.selectedIndexes()})

    # ---------- 拖到左侧分组面板（不依赖原生 QDrag，自己做命中检测） ----------

    # 分组面板命中检测已并入 _update_drag_feedback（全局事件过滤器方案已移除：
    # Windows 左键按下会捕获鼠标到按下时的 viewport，全局过滤器在捕获期间收不到事件，
    # 故统一在视口拖拽反馈里用 event.globalPos 做命中检测）。

    def _cursor_in_viewport(self, global_pos):
        """判定光标全局坐标是否落在表格 viewport 矩形内。

        用于把『列表重排』与『移动分组』两种动作按光标位置互斥：在 viewport 内才
        激活重排，否则一律视为离开列表区（重排失效）。
        """
        rect = QRect(self._viewport.mapToGlobal(QPoint(0, 0)), self._viewport.size())
        return rect.contains(global_pos)

    def _group_panel_hit(self, global_pos):
        """返回鼠标全局坐标命中的左侧分组项名称（排除「全部」），无则 None。"""
        glw = self._group_list_widget
        if glw is None:
            return None
        local = glw.mapFromGlobal(global_pos)
        if not glw.rect().contains(local):
            return None
        item = glw.itemAt(local)
        if item is None:
            return None
        name = item.text()
        if not name or name == "（全部）":
            return None
        return name

    def _update_group_highlight(self, name):
        """高亮命中的分组项（纯玫瑰色），并清除先前的命中项。

        通过自定义 delegate 的 DRAG_TARGET_ROLE 实现，绕过 style.qss 对 setBackground 的覆盖。
        """
        glw = self._group_list_widget
        if glw is None:
            return
        self._clear_group_highlight()
        if not name:
            return
        for i in range(glw.count()):
            item = glw.item(i)
            if item is not None and item.text() == name:
                item.setData(DRAG_TARGET_ROLE, True)
                self._highlighted_item = item
                break

    def _clear_group_highlight(self):
        """清除被高亮的分组项标记（delegate 自动还原为默认绘制）。"""
        if self._highlighted_item is not None:
            try:
                self._highlighted_item.setData(DRAG_TARGET_ROLE, False)
            except Exception:  # noqa: BLE001 - 样式还原失败不阻断拖拽
                _log.debug("还原分组项高亮失败", exc_info=True)
            self._highlighted_item = None

    def _clear_group_highlight_item(self, item):
        """清除指定分组项的高亮（Bug D 修复：用于 700ms 延迟确认的快照回调）。

        只清传入的特定项；仅当该项仍是当前高亮项时才把 _highlighted_item 置空，
        以免清掉之后新拖拽产生的高亮。"""
        if item is None:
            return
        try:
            item.setData(DRAG_TARGET_ROLE, False)
        except Exception:  # noqa: BLE001 - 样式还原失败不阻断拖拽
            _log.debug("还原分组项高亮失败", exc_info=True)
        if self._highlighted_item is item:
            self._highlighted_item = None


