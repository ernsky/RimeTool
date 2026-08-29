"""日志系统：统一写入 data/logs/ 目录。"""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler

_INITIALIZED_LOGGERS: set = set()


def _get_log_dir() -> str:
    """日志目录：data/logs/（相对项目根）。"""
    project_root = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
    log_dir = os.path.join(project_root, "data", "logs")
    os.makedirs(log_dir, exist_ok=True)
    return log_dir


def get_logger(name: str = "RimeTool") -> logging.Logger:
    """获取统一配置的日志器。日志写入 data/logs/RimeTool.log。"""
    logger = logging.getLogger(name)
    # 每个 logger 独立初始化，避免全局标志导致后续 logger 无 handler
    if name not in _INITIALIZED_LOGGERS:
        logger.setLevel(logging.DEBUG)
        log_dir = _get_log_dir()
        handler = RotatingFileHandler(
            os.path.join(log_dir, "RimeTool.log"),
            maxBytes=5 * 1024 * 1024,  # 5MB
            backupCount=3,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
        logger.addHandler(handler)
        logger.propagate = False  # 避免向上传播到根 logger 导致重复输出
        _INITIALIZED_LOGGERS.add(name)
    return logger
