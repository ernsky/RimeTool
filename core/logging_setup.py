# -*- coding: utf-8 -*-
"""统一的日志初始化（替代散落的 print 报错）。

设计要点：
  - 在 main 启动早期调用 setup_logging()，之后各模块用
    `import logging; _log = logging.getLogger(__name__)` 输出。
  - 日志同时落两个去处：
      1) RimeTool/Logs/rime_tool.log（INFO 及以上）—— 可持久排障；
      2) 控制台 stderr —— pythonw 下已被 main.py 重定向到 devnull，此处无副作用。
  - 之所以必须落文件：pythonw 运行时 sys.stdout/stderr 为 None，main.py 已将其重定向到
    devnull，任何 print 都会"看似正常、实则永久丢失"。错误要可观测，只能走文件日志。

只暴露 setup_logging() 一个入口；重复调用安全（force=True 覆盖旧配置）。
"""
import logging
import os


def setup_logging(level: int = logging.INFO) -> None:
    """初始化根日志：文件 + 控制台双 handler，格式含时间/级别/模块名。"""
    # 日志目录：core/logging_setup.py -> RimeTool/Logs
    log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Logs")
    try:
        os.makedirs(log_dir, exist_ok=True)
    except OSError:
        log_dir = None

    handlers: list = []
    if log_dir:
        try:
            handlers.append(
                logging.FileHandler(
                    os.path.join(log_dir, "rime_tool.log"), encoding="utf-8"
                )
            )
        except OSError:
            pass
    # 控制台（pythonw 下为 devnull，无害；普通终端可见）
    handlers.append(logging.StreamHandler())

    if not handlers:
        # 极端情况（连 StreamHandler 都建不出）：退化为纯内存，不报错
        handlers.append(logging.NullHandler())

    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
        force=True,  # 允许重复调用覆盖旧配置
    )
