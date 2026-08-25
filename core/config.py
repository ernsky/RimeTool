# -*- coding: utf-8 -*-
"""全局可配置项与主题变量。

所有配色 / 尺寸集中在 THEME 字典，供 resources/style.qss 通过 string.Template
渲染；所有业务常量集中在模块顶层，供 core / ui 各层共享。
"""

import os
import sys
import logging
from typing import Any, Dict, List

_log = logging.getLogger(__name__)

# 默认词库路径（入口 main.py 在未传命令行参数时使用）
# 按安装根目录推导，随程序位置移动自适应（不再写死绝对路径）
_RIME_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TSV_PATH = os.path.join(_RIME_ROOT, "Python", "Alamo.tsv")

# 默认单字编码表（五笔编码生成读取；可在「配置选项 → 单字编码文件」覆盖）
SINGLE_CHAR_FILE = os.path.join(_RIME_ROOT, "RimeTool", "resources", "word.txt")

# 部署前是否自动保存当前 TSV 源文件（让 Alamo.tsv 与导出到 Rime 的内容保持一致）。
# 设为 False 可关闭：此时 deploy 只导出内存数据到 Rime，不回写 Alamo.tsv。
DEPLOY_AUTO_SAVE_TSV = True

# 懒加载批次
BATCH_INITIAL = 200   # 启动后首批加载行数
BATCH_LATER = 500     # 之后每滚动到底部加载的行数

# 列定义（全部 5 列）
HEADERS = ("词组", "五笔编码", "词频", "分组", "启用")
# 需要按数值排序/校验的列（仅词频）
NUMERIC_COLS = (2,)
# 筛选框搜索范围：词条 / 编码 / 词频（子串匹配，编码不区分大小写）
FILTER_COLS = (0, 1, 2)

# 主题变量（供 resources/style.qss 以 $name 引用）。
# resources/style.qss 中以 $name 引用，由 main.py 用 string.Template 渲染注入。
THEME = {
    # 主色调（深蓝 / 深灰）
    "primary": "#1e3a8a",
    "primary_light": "#3b82f6",
    "primary_dark": "#374151",
    "primary_hover": "#3b82f6",
    # 背景色（浅灰）
    "panel": "#f3f4f6",
    "surface": "#ffffff",
    "background": "#f3f4f6",
    # 文字色（深灰 / 中灰）
    "text_primary": "#111827",
    "text_secondary": "#6b7280",
    "text_tertiary": "#9ca3af",
    "text_disabled": "#cbd5e1",
    # 边框色
    "border_light": "#e5e7eb",
    "border_medium": "#d1d5db",
    "border_dark": "#9ca3af",
    # 交互色（浅蓝 / 青）
    "accent": "#3b82f6",
    "accent_hover": "#06b6d4",
    "success": "#10b981",
    "warning": "#f59e0b",
    "error": "#ef4444",
    # 表格
    "row_even": "#ffffff",
    "row_odd": "#f9fafb",
    "row_hover": "rgba(59, 130, 246, 0.08)",
    "selected": "rgba(59, 130, 246, 0.18)",
    "selected_text": "#111827",
    # 圆角
    "radius": "3px",
    # ---- 与原 deep 主题同键的扩展键（供 style.qss 暗色专属覆盖，浅色给合理默认）----
    "title_text": "#111827",        # 弹窗/配置模块标题文字（深：白色）
    "side_active": "#3b82f6",       # 左侧当前文件/分组背景（深：青 #06b6d4）
    "search_btn": "#3b82f6",        # 搜索/交换权重按钮背景（深：#3b3b3b）
    "search_btn_hover": "#60a5fa",  # 搜索/交换权重按钮 hover（深：#4a4a4a）
    "search_btn_press": "#2563eb",  # 搜索/交换权重按钮 pressed（深：#2e2e2e）
    "status_text": "#6b7280",       # 状态栏文字（深：白色）
    "input_bg": "#ffffff",          # 输入框背景（浅色=白）
    "raised": "#ffffff",            # 浮层（弹窗/菜单/下拉/提示）背景（浅色=白）
}

# 暗色主题：与 THEME 同键，灰蓝低饱和配色（Linear/Arc 风，2026-08-23）：
#   - 背景为带蓝调的冷灰（层级：底 < 内容 < 浮层 < 输入框）
#   - 强调色低饱和灰蓝 #5c7fb8，克制使用（focus/选中/主按钮/分组标题）
#   - 文字非纯白 #dcddde，降低眩光
DARK_THEME = {
    # 主色调（低饱和灰蓝）
    "primary": "#5c7fb8",
    "primary_light": "#6f92cc",
    "primary_dark": "#4a6899",
    "primary_hover": "#6f92cc",
    # 背景色：层级 底#191b1e < 内容#1f2226 < 浮层#25282d（明度差表达层次）
    "panel": "#191b1e",
    "surface": "#1f2226",
    "background": "#1f2226",
    # 文字色：非纯白，降低眩光
    "text_primary": "#dcddde",
    "text_secondary": "#999999",
    "text_tertiary": "#666666",
    "text_disabled": "#5a5a5a",
    # 边框色（存在但不抢戏）
    "border_light": "#353a42",
    "border_medium": "#353a42",
    "border_dark": "#454b55",
    "border_group": "#353a42",
    # 交互色
    "accent": "#5c7fb8",
    "accent_hover": "#6f92cc",
    "success": "#44cf6e",
    "warning": "#e9973f",
    "error": "#fb464c",
    # 表格
    "row_even": "#1f2226",
    "row_odd": "#23262b",
    "row_hover": "#343943",
    "selected": "rgba(92, 127, 184, 0.22)",
    "selected_text": "#dcddde",
    # 圆角
    "radius": "3px",
    # ---- 暗色专属扩展键（与 THEME 同键，供 style.qss 引用；灰蓝主题下统一蓝）----
    "title_text": "#ffffff",        # 弹窗/配置模块标题文字：白色
    "side_active": "#5c7fb8",       # 左侧当前文件/分组竖线与强调：灰蓝主色
    "search_btn": "#5c7fb8",        # 搜索/交换权重按钮背景：灰蓝主色
    "search_btn_hover": "#6f92cc",  # 搜索/交换权重按钮 hover：亮一档
    "search_btn_press": "#4a6899",  # 搜索/交换权重按钮 pressed：深一档
    "status_text": "#dcddde",       # 状态栏文字：柔白
    # 输入框背景（比内容区亮一档，冷灰分层）
    "input_bg": "#2d3138",
    # 浮层（弹窗/菜单/下拉/提示）背景，比内容区抬升一档
    "raised": "#25282d",
}

# 主题三态选择（值, 显示名）
THEME_CHOICES = [("auto", "自动"), ("light", "浅色"), ("dark", "深色")]


def detect_system_dark() -> bool:
    """探测系统是否处于暗色模式（Windows 读注册表 AppsUseLightTheme，0=暗）。
    非 Windows 或任何异常均回退 False（浅色）。"""
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        )
        val, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        return val == 0
    except Exception:  # noqa: BLE001 - 探测失败回退浅色
        _log.debug("探测系统暗色模式失败，回退浅色", exc_info=True)
        return False


def resolve_theme(name: str) -> str:
    """把三态名解析为 concrete 'light'/'dark'。auto 跟随系统探测。"""
    if name == "auto":
        return "dark" if detect_system_dark() else "light"
    return name if name in ("light", "dark") else "light"


def theme_dict(name: str) -> Dict[str, Any]:
    """返回对应主题变量字典（THEME 或 DARK_THEME）。"""
    return DARK_THEME if resolve_theme(name) == "dark" else THEME


# 当前激活主题名：由 main.apply_theme 在每次应用/切换主题时写入，
# 供拖拽控制器等「运行时组件」读取当前主色，避免模块导入时把主题写死
# （旧实现在导入时固定取浅色 THEME["primary"]，导致深色下拖拽线仍是蓝色）。
_ACTIVE_THEME_NAME = "auto"


def get_active_theme_name() -> str:
    """返回当前激活的主题名（auto / light / dark）。"""
    return _ACTIVE_THEME_NAME


def set_active_theme_name(name: str) -> None:
    """由 main.apply_theme 调用，记录当前激活主题名。"""
    global _ACTIVE_THEME_NAME
    _ACTIVE_THEME_NAME = name


# 危险系统目录黑名单：写回目标不得落入其中，防止误配 / 恶意路径越权写（规范 2.5 🟡）。
# 合法的用户路径（安装根、OneDrive、桌面、文档等）均放行；仅拦截真正的系统关键目录。
_DANGEROUS_ROOTS: List[str] = []
if sys.platform.startswith("win"):
    _sr = os.environ.get("SystemRoot", r"C:\Windows").rstrip("/\\")
    _DANGEROUS_ROOTS = [
        _sr,
        os.path.join(_sr, "System32"),
        os.path.join(_sr, "SysWOW64"),
        r"C:\$Recycle.Bin",
        r"C:\System Volume Information",
        r"C:\ProgramData\Microsoft",
    ]
else:
    _DANGEROUS_ROOTS = ["/proc", "/sys", "/boot", "/dev", "/root"]


def is_safe_target(path: str) -> bool:
    """写回目标安全校验（deny-list / 黑名单语义）：拒绝落到危险系统目录（如 C:\\Windows\\System32）下的写入。

    返回 True 表示允许写入。合法的用户路径（安装根、OneDrive、桌面、文档、外部盘、网络盘等）均放行；
    仅拦截 _DANGEROUS_ROOTS 列出的少数系统关键目录。注意：这是黑名单而非白名单——
    不在此名单中的路径一律放行，调用方不应据此认为"只放行了极少数受控路径"（安全审查 F4）。
    """
    if not path:
        return False
    try:
        # 用 realpath 解析符号链接/连接点（纵深防御）：拒绝「经符号链接逃逸到系统目录」的写入
        # （如指向 C:\Windows\System32 的 junction/symlink）。abspath 只做词法规范化、不解析链接，故已弃用。
        p = os.path.realpath(os.path.normpath(path))
    except (OSError, ValueError):
        return False
    pl = p.lower()
    for d in _DANGEROUS_ROOTS:
        dl = d.rstrip("/\\").lower()
        if pl == dl or pl.startswith(dl + os.sep):
            _log.warning("拒绝写回危险系统目录：%s", p)
            return False
    return True
