# -*- coding: utf-8 -*-
"""五笔词库编辑器 - 入口。

职责：依赖检查（PyQt5 缺失兜底）、高 DPI 支持、加载 resources/style.qss 并渲染、
把主题变量注入样式表、创建并显示主窗口。UI 构建在 ui/workspace_window.py，数据逻辑在
core/，样式在 resources/style.qss —— 三者彻底分离，不再把 UI/样式混进业务逻辑代码。

运行：
    python main.py [可选 TSV 路径]
"""
import logging
import os
import sys
import string
import time
import traceback
import threading

_log = logging.getLogger(__name__)


def _install_crash_logger():
    """pythonw 下 stderr 被丢进 devnull，任何未捕获异常 / PyQt5 槽异常都会「静默退出」且无迹可查
    （典型表现：追加一个词组后程序直接退出）。装一个 sys.excepthook 把完整 traceback 落盘到
    Logs/rime_tool.log，便于事后排查；对 PyQt5 槽异常还能做到「记录后继续」而非直接崩。

    必须在创建 QApplication 之前、且 PROJECT_ROOT 可用时安装（此处用 __file__ 推算，不依赖下方常量）。
    """
    root = os.path.dirname(os.path.abspath(__file__))
    log_dir = os.path.join(root, "Logs")
    try:
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, "rime_tool.log")
    except Exception:  # noqa: BLE001 - 无法建日志目录则退化为仅调用原始 hook
        log_path = None
    original = sys.excepthook

    def _hook(et, ev, tb):
        try:
            msg = "".join(traceback.format_exception(et, ev, tb))
        except Exception:
            msg = repr(ev)
        try:
            if log_path:
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write("\n=== 未捕获异常 %s (thread=%s) ===\n" % (
                        time.strftime("%Y-%m-%d %H:%M:%S"),
                        threading.current_thread().name))
                    f.write(msg)
                    f.write("\n")
        except Exception:  # noqa: BLE001 - 写日志自身失败绝不应再抛异常
            pass
        try:
            original(et, ev, tb)
        except Exception:
            pass

    sys.excepthook = _hook

# 早期初始化日志（在任何可能报错的代码之前），替代散落的 print 报错。
# 即便 core 导入失败也静默跳过，不影响后续 PyQt5 缺失兜底逻辑。
try:
    from core.logging_setup import setup_logging
    setup_logging()
except Exception:  # noqa: BLE001 - 日志初始化失败绝不应阻断启动
    pass

# 崩溃落盘钩子：pythonw 运行（无控制台）时 sys.stdout/stderr 被重定向到 devnull，
# 任何未捕获异常 / PyQt5 槽异常都会「静默退出」且无迹可查（典型表现即「追加一个词组后程序直接退出」）。
# 这里装一个 sys.excepthook，把完整 traceback 落盘到 Logs/rime_tool.log，
# 既便于事后排查，也让 PyQt5 槽异常「记录后继续」而非直接崩。
_install_crash_logger()

# pythonw 运行（无控制台窗口）时 sys.stdout / sys.stderr 为 None，任何 print 都会
# 直接抛 AttributeError 导致静默退出（看似「闪退」）。这里重定向到 devnull，保证
# 「双击 .pyw 无黑窗」场景下，即便有 print / 兜底输出也不会崩。
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

# 路径引导：无论从哪个目录启动，都保证项目根目录（本文件所在目录）在 sys.path，
# 这样 `from core.xxx import ...`、`from ui.xxx import ...` 都能成功。
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def _show_missing_pyqt5():
    """PyQt5 未安装时的兜底提示：不依赖 PyQt5 本身，优先用 tkinter 弹窗。

    双击 .py 时若调用了「没装 PyQt5 的 Python」，import 会直接失败并闪退；
    这里把黑框闪退换成明确的安装指引，便于定位问题。
    """
    msg = (
        "无法启动词库编辑器：未能导入 PyQt5（依赖缺失）。\n\n"
        "最常见原因：双击 .py 文件时，Windows 用了一个没有 PyQt5 的 Python 去运行。\n\n"
        "解决办法（任选其一，最稳妥的是第 2 条）：\n"
        "  1) 在「装了 PyQt5 的 Python」里执行安装：\n"
        "       例如：python -m pip install PyQt5\n"
        "  2) 直接用该 Python 启动本程序（推荐，最不容易出错）：\n"
        "       例如：python main.py\n"
        "  3) 右键本文件 →「打开方式」→ 选择装了 PyQt5 的 python.exe；\n"
        "     或把文件名改为 .pyw 并关联到 pythonw.exe（无控制台窗口）。"
    )
    # 优先用 tkinter 弹窗（标准库自带，且不依赖 PyQt5）
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("缺少 PyQt5", msg)
        root.destroy()
        return
    except Exception:  # noqa: BLE001 - tkinter 不可用时静默降级到控制台兜底
        _log.debug("tkinter 不可用，降级到控制台提示", exc_info=True)
    # 兜底：打印到控制台并暂停，至少让用户看到原因（无 tkinter 时）；同时落日志便于排障
    _log.error("启动失败：缺少 PyQt5\n%s", msg)
    print(msg)
    try:
        input("按 Enter 退出...")
    except Exception:  # noqa: BLE001 - 无交互环境（如 pythonw）静默退出
        pass


try:
    from PyQt5.QtWidgets import QApplication, QMessageBox, QDialog
    from PyQt5.QtCore import Qt
    from PyQt5.QtGui import QIcon, QFont, QPalette, QColor
except ImportError:
    _show_missing_pyqt5()
    sys.exit(1)

from ui.msgbox import critical


def _load_style(theme_name="auto"):
    """读取 resources/style.qss，用对应主题变量渲染后返回样式表文本。"""
    from core.config import theme_dict, THEME, DARK_THEME
    import re
    from string import Template
    qss_path = os.path.join(PROJECT_ROOT, "resources", "style.qss")
    try:
        with open(qss_path, "r", encoding="utf-8") as f:
            content = f.read()
        # 检查QSS中引用的所有变量是否都在主题字典中
        used_vars = set(re.findall(r'\$(\w+)', content))
        theme = theme_dict(theme_name)
        missing = used_vars - set(theme.keys())
        if missing:
            raise RuntimeError(f"主题字典缺失QSS引用的变量: {missing}")
        return Template(content).substitute(theme)
    except OSError as exc:
        _log.warning("样式表加载失败，使用默认样式：%s", exc)
        return ""
    except RuntimeError as exc:
        _log.error("主题变量检查失败：%s", exc)
        return ""


# 运行时当前主题名（供弹窗标题栏过滤器读取，确保新弹出的对话框也按当前主题配色）
_current_theme = "auto"


def _is_dark(theme_name):
    """该主题名最终是否解析为深色（auto 跟随系统探测）。"""
    from core.config import theme_dict, DARK_THEME
    return theme_dict(theme_name) is DARK_THEME


def _hex_to_rgb(h):
    """#rrggbb / #rgb -> (r, g, b)。"""
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def title_colors_for(theme_name):
    """返回标题栏配色 (caption_rgb, text_rgb, is_dark)。

    - 浅色：主色深蓝 #1e3a8a 作标题栏底 + 白字；
    - 深色：#1f1f1f 作标题栏底 + 白字（略亮于主窗口背景 #141414，与内容区 #242629 形成层次）。

    这样原生标题栏真正「随主题配色」，而不只是系统亮/暗灰。"""
    from core.config import theme_dict, DARK_THEME, THEME
    d = theme_dict(theme_name)
    is_dark = d is DARK_THEME
    if is_dark:
        # 新暗色面板 #1a1a1a；标题栏文字用次级灰 #999999，与窗口融为一体（见 py配色.md）
        caption = _hex_to_rgb("#1a1a1a")
        text = (0x99, 0x99, 0x99)
    else:
        caption = _hex_to_rgb(THEME["primary"])   # #1e3a8a
        text = (0xFF, 0xFF, 0xFF)
    return caption, text, is_dark


def _set_dark_title_bar(win, is_dark, caption_color=None, text_color=None):
    """Windows 下把原生标题栏切为暗色（DWMWA_USE_IMMERSIVE_DARK_MODE=20），
    并可指定标题栏背景色(DWMWA_CAPTION_COLOR=35)与文字色(DWMWA_TEXT_COLOR=36)，
    使标题栏真正随主题配色。各 DWM 属性独立 try，单条失败不影响其余；
    最后强制非客户区重绘（SetWindowPos SWP_FRAMECHANGED）。
    非 Windows / 旧系统 / 任何异常静默忽略。"""
    try:
        import ctypes
        from ctypes import wintypes
        hwnd = int(win.winId())
        DWMWA_USE_IMMERSIVE_DARK_MODE = 20
        DWMWA_CAPTION_COLOR = 35   # Windows 11+
        DWMWA_TEXT_COLOR = 36      # Windows 11+

        def _attr(attr, value):
            try:
                v = ctypes.c_int(value)
                ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    wintypes.HWND(hwnd), ctypes.c_int(attr),
                    ctypes.byref(v), ctypes.sizeof(v))
            except Exception:  # noqa: BLE001 - 不支持的属性（如 Win10 无 CAPTION_COLOR）静默跳过
                _log.debug("DWM 属性 %s 设置失败，跳过", attr, exc_info=True)

        # 1) 沉浸式暗色（影响标题栏按钮字形明暗）
        _attr(DWMWA_USE_IMMERSIVE_DARK_MODE, 1 if is_dark else 0)
        # 2) 标题栏背景色（DWM 颜色格式 0x00RRGGBB，高字节必须为 0）
        if caption_color is not None:
            r, g, b = caption_color
            _attr(DWMWA_CAPTION_COLOR, (b << 16) | (g << 8) | r)
        # 3) 标题栏文字色
        if text_color is not None:
            r, g, b = text_color
            _attr(DWMWA_TEXT_COLOR, (b << 16) | (g << 8) | r)

        # 强制重绘非客户区（标题栏/边框），使 DWM 属性立即生效
        SWP_FRAMECHANGED = 0x0020
        SWP_NOSIZE = 0x0001
        SWP_NOMOVE = 0x0002
        SWP_NOZORDER = 0x0004
        ctypes.windll.user32.SetWindowPos(
            wintypes.HWND(hwnd), None, 0, 0, 0, 0,
            SWP_NOSIZE | SWP_NOMOVE | SWP_NOZORDER | SWP_FRAMECHANGED,
        )
    except Exception:  # noqa: BLE001 - 非 Windows 或任何异常静默忽略，不影响主流程
        _log.debug("设置原生标题栏配色失败（非 Windows 或调用异常），忽略", exc_info=True)


def _build_palette(theme_name):
    """按主题构造 QPalette：把未显式写死在 style.qss 的控件（中央部件、各类未命名容器、
    编辑框/视图底色、滚动条外框、失焦态文字等）统一到主题色，消除「标题栏以下/空白区仍是系统白」
    的问题。style.qss 已显式设色的控件（面板/按钮/输入框/表格…）优先级更高、不受此影响；本调色板
    只兜住所有漏网区域，做到「哪怕是空白也跟随主题色」。"""
    from core.config import theme_dict, DARK_THEME
    d = theme_dict(theme_name)
    try:
        pal = QPalette()
        # 基础背景 / 文字（中央部件、通用窗口底色 = background；文字 = text_primary）
        pal.setColor(QPalette.Window, QColor(d["background"]))
        pal.setColor(QPalette.WindowText, QColor(d["text_primary"]))
        # 编辑框 / 视图底色（QLineEdit/QTextEdit/QAbstractItemView 未显式设色时的 Base 角色）
        pal.setColor(QPalette.Base, QColor(d["surface"]))
        pal.setColor(QPalette.Text, QColor(d["text_primary"]))
        # 按钮底色 / 文字（QPushButton 未显式设色时）
        pal.setColor(QPalette.Button, QColor(d["surface"]))
        pal.setColor(QPalette.ButtonText, QColor(d["text_primary"]))
        # 交替行底色（表格 alternate row）
        pal.setColor(QPalette.AlternateBase, QColor(d["row_odd"]))
        # 选中 / 高亮
        pal.setColor(QPalette.Highlight, QColor(d["selected"]))
        pal.setColor(QPalette.HighlightedText, QColor(d["selected_text"]))
        # 浮层（tooltip）底/字
        pal.setColor(QPalette.ToolTipBase, QColor(d["raised"]))
        pal.setColor(QPalette.ToolTipText, QColor(d["text_primary"]))
        # 边框层次（Light/Midlight/Mid/Dark/Shadow 参与分隔线、3D 边框描边等）
        pal.setColor(QPalette.Light, QColor(d["border_light"]))
        pal.setColor(QPalette.Midlight, QColor(d["border_light"]))
        pal.setColor(QPalette.Mid, QColor(d["border_medium"]))
        pal.setColor(QPalette.Dark, QColor(d["border_medium"]))
        pal.setColor(QPalette.Shadow, QColor(d["border_dark"]))
        # 失焦 / 禁用态文字（避免禁用控件仍是浅色文字糊在浅底上）
        pal.setColor(QPalette.Disabled, QPalette.WindowText, QColor(d["text_disabled"]))
        pal.setColor(QPalette.Disabled, QPalette.Text, QColor(d["text_disabled"]))
        pal.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(d["text_disabled"]))
        return pal
    except Exception:  # noqa: BLE001 - 调色板构造失败绝不阻断启动/换肤
        _log.debug("构造主题调色板失败，使用默认调色板", exc_info=True)
        return QPalette()


def apply_theme(app, theme_name, win=None):
    """把指定主题应用到整个应用（启动与运行时切换均复用）。
    若传入主窗口 win，则同时把原生标题栏按当前主题配色刷新（仅 Windows 生效）。"""
    global _current_theme
    _current_theme = theme_name
    from core.config import set_active_theme_name
    set_active_theme_name(theme_name)   # 同步激活主题名，供拖拽控制器等运行时组件读取主色
    app.setStyleSheet(_load_style(theme_name))
    # 统一未显式设色的控件/空白区背景到主题色，消除「标题栏以下白块」
    try:
        app.setPalette(_build_palette(theme_name))
    except Exception:  # noqa: BLE001 - 调色板失败不影响样式表已生效的部分
        _log.debug("应用主题调色板失败，忽略", exc_info=True)
    if win is not None:
        cap, txt, drk = title_colors_for(theme_name)
        _set_dark_title_bar(win, drk, cap, txt)


def _dump_startup_error(exc):
    """双击启动失败时，把完整 traceback 落盘到 Logs/startup_error.log（pythonw 无控制台也能定位），
    并尽量弹出可见的错误框。即便弹窗本身也失败，日志仍会保留，避免「静默退出的打不开」。"""
    try:
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    except Exception:
        tb = repr(exc)
    try:
        log_dir = os.path.join(PROJECT_ROOT, "Logs")
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, "startup_error.log")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write("\n=== 启动失败 %s ===\n" % time.strftime("%Y-%m-%d %H:%M:%S"))
            f.write(tb)
            f.write("\n")
    except Exception:
        pass
    _log.error("启动失败:\n%s", tb)
    try:
        app = QApplication.instance() or QApplication(sys.argv)
        critical(None, "启动失败", "词库编辑器启动失败：\n\n" + tb[:3000])
    except Exception:
        try:
            _log.exception("启动失败（无法弹出错误框）")
        except Exception:
            pass


def _enable_high_dpi():
    """开启 Qt 高 DPI 缩放（适配高分屏）；PyQt5>=5.14 默认已开启，故仅旧版本显式设置。"""
    try:
        from PyQt5 import QtCore
        if QtCore.PYQT_VERSION < 0x050E00:
            QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
            QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    except Exception:  # noqa: BLE001 - 旧版 PyQt5 探测失败则保持默认高 DPI 设置，不影响启动
        _log.debug("高 DPI 设置探测失败（旧版 PyQt5 或非预期环境），保持默认", exc_info=True)


def _activate_existing_window():
    """把已运行实例的主窗口还原并置前（Windows；按标题前缀「词库工具箱」匹配）。

    用于单实例守卫：第二实例启动时若发现锁已被占，调用此函数把旧窗口弹到用户眼前，
    再自行退出——避免用户误以为「没打开」而反复双击。非 Windows 或任何异常均返回
    False 静默跳过，不影响退出主流程。"""
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        import ctypes.wintypes as wt

        user32 = ctypes.windll.user32
        found = []
        EnumProc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)

        def _cb(hwnd, lparam):
            n = user32.GetWindowTextLengthW(hwnd)
            if n > 0:
                buf = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(hwnd, buf, n + 1)
                if buf.value.startswith("词库工具箱") and user32.IsWindowVisible(hwnd):
                    found.append(hwnd)
                    return False          # 找到即停止枚举
            return True

        user32.EnumWindows(EnumProc(_cb), 0)
        if not found:
            return False
        hwnd = found[0]
        if user32.IsIconic(hwnd):         # 最小化中 → 先还原
            user32.ShowWindow(hwnd, 9)    # SW_RESTORE
        user32.SetForegroundWindow(hwnd)  # 置前（双击场景下通常有前台权限）
        return True
    except Exception:  # noqa: BLE001 - 激活失败不影响退出
        _log.debug("激活已存在实例的窗口失败", exc_info=True)
        return False


# 单实例锁的名字：带版本后缀避免与旧版残留冲突
_SINGLE_INSTANCE_KEY = "RimeTool_SingleInstance_v1"


def main():
    # 任务栏图标身份（AppUserModelID）：必须在创建 QApplication 之前设置，否则 Windows
    # 仍把任务栏按钮算在 pythonw.exe 头上，导致任务栏显示 Python 默认图标/空白。
    # 经 pythonw.exe 启动时尤其关键——显式给本进程一个独立任务栏身份后，任务栏才会采用下方图标。
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Rime.RimeTool.v1")
        except Exception:  # noqa: BLE001 - 失败不影响主窗口其余功能
            _log.debug("设置 AppUserModelID 失败", exc_info=True)
    # 高分屏（高 DPI）支持：必须在创建 QApplication 之前开启，
    # 让逻辑像素按系统缩放比映射，避免高分辨率屏上字体/控件被渲染得过小。
    _enable_high_dpi()
    # 先创建 QApplication，再导入重量级 UI 模块（PyQt5 官方推荐顺序：在 QApplication
    # 存在之前导入 widget 模块，部分 Qt 后端会触发 C++ 层崩溃；同时避免启动期静默退出）。
    app = QApplication(sys.argv)

    # 单实例守卫（方案B）：用命名共享内存当「锁」。第一个实例 create 成功并持有；
    # 之后任何实例 create 失败 = 已有人在跑 → 把旧窗口拉到前台，然后自己悄悄退出。
    # （Windows 下进程退出/崩溃时系统自动回收共享内存，无死锁残留问题。）
    # 必须放在导入 WorkspaceWindow 之前：让重复启动的第二实例尽早退出，不做无用加载。
    from PyQt5.QtCore import QSharedMemory
    _single_guard = QSharedMemory(_SINGLE_INSTANCE_KEY)
    if not _single_guard.create(1):
        _log.info("检测到已有实例在运行，激活其窗口后退出")
        _activate_existing_window()
        sys.exit(0)

    from ui.workspace_window import WorkspaceWindow
    from ui.config_dialog import load_config
    # 全局字号统一为「应用默认字号 +1 point」（2026-08-23 用户要求整体小一号：原 +2 → +1），
    # 满足「所有显示字体统一为该字号」的要求；各控件若未单独 setFont 均继承此值。
    # 表头「词组」等所有 QLabel/表格/对话框/按钮统一此字号。
    _base = app.font().pointSize()
    if _base <= 0:
        _base = 12
    # 字体带 CJK 回退栈：雅黑缺失/损坏时依次回退 PingFang SC / 雅黑 UI / 系统无衬线，
    # 避免「装了非雅黑系统却只指定单一字体 → 中文掉成方块/宋体」。逗号分隔家族名 Qt 会作为回退列表解析。
    app.setFont(QFont("Microsoft YaHei, PingFang SC, Microsoft YaHei UI, sans-serif", _base + 1))
    # 注册组织/应用名，让 QSettings 有稳定落点（Windows→注册表 HKCU\Software\Rime\RimeTool），
    # 用于记住窗口大小/位置。
    app.setOrganizationName("Rime")
    app.setApplicationName("RimeTool")
    # 窗口图标：优先用多分辨率 app_icon.ico（任务栏渲染最可靠），缺失则回退 PNG。
    # AppUserModelID 已在 main() 开头（创建 QApplication 之前）设置，确保任务栏采用本程序图标。
    icon_path = os.path.join(PROJECT_ROOT, "resources", "app_icon.ico")
    if not os.path.isfile(icon_path):
        icon_path = os.path.join(PROJECT_ROOT, "resources", "app_icon.png")
    if os.path.isfile(icon_path):
        app.setWindowIcon(QIcon(icon_path))
    theme = load_config().get("theme", "auto")
    app.setStyleSheet(_load_style(theme))   # 先上样式，避免创建窗口时的默认样式闪烁

    # 全局弹窗标题栏过滤器：任何 QDialog/QMessageBox 弹窗 show 时按当前主题刷新原生标题栏配色，
    # 统一兜底，确保配置/五笔/查找替换/合并/移动到分组/确认框/消息框等所有弹窗标题栏随主题。
    from PyQt5.QtCore import QObject, QEvent

    class _PopupTitleFilter(QObject):
        def eventFilter(self, obj, event):
            if event.type() == QEvent.Show and isinstance(obj, QDialog) and obj.isWindow():
                try:
                    cap, txt, drk = title_colors_for(_current_theme)
                    _set_dark_title_bar(obj, drk, cap, txt)
                except Exception:  # noqa: BLE001 - 失败静默忽略，不影响弹窗本身
                    pass
            return False

    app.installEventFilter(_PopupTitleFilter(app))

    win = WorkspaceWindow()
    win.setWindowIcon(QIcon(icon_path))   # 主窗口单独设图标，确保任务栏按钮采用本程序图标（标题栏沿用 app 级）
    win.show()
    apply_theme(app, theme, win)            # 重新应用（含原生标题栏暗色切换，需 HWND 已存在）
    win._apply_fixed_fonts()                # 二次 setStyleSheet 会把状态栏/五框字体重置回 14pt，此处再锁回（状态栏 8pt、五框 10pt）
    sys.exit(app.exec_())


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # 双击启动时若出错，落盘 + 弹窗提示而非静默退出
        _dump_startup_error(exc)
