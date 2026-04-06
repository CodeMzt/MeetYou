"""
统一日志配置。
"""

import json
import logging
import os
from datetime import datetime

from core.runtime_context import get_correlation_context


class StructuredFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": self.formatTime(record, self.datefmt),
            "logger": record.name,
            "level": record.levelname,
            "message": record.getMessage(),
            "context": get_correlation_context(),
        }
        structured_data = getattr(record, "structured_data", None)
        if isinstance(structured_data, dict) and structured_data:
            payload["data"] = structured_data
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def _build_formatter() -> logging.Formatter:
    return StructuredFormatter(datefmt="%Y-%m-%d %H:%M:%S")


def _reset_logger(logger: logging.Logger, level: int):
    logger.handlers.clear()
    logger.setLevel(level)


def setup_logger(
    log_dir: str = "logs",
    level: int = logging.INFO,
    enable_console: bool = False,
    console_level: int | None = None,
    component: str = "app",
) -> logging.Logger:
    """
    配置并返回 meetyou 命名空间的 Logger。

    Args:
        log_dir: 日志文件输出目录
        level: 最低日志级别
        enable_console: 是否输出到控制台
        console_level: 控制台最低日志级别
        component: 当前进程/组件名称，用于拆分日志文件
    """
    os.makedirs(log_dir, exist_ok=True)

    formatter = _build_formatter()
    file_name = f"meetyou_{component}_{datetime.now().strftime('%Y%m%d')}.log"
    file_path = os.path.join(log_dir, file_name)
    file_handler = logging.FileHandler(file_path, encoding="utf-8")
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)

    handlers: list[logging.Handler] = [file_handler]
    if enable_console:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(console_level or level)
        console_handler.setFormatter(formatter)
        handlers.append(console_handler)

    for logger_name in (
        "meetyou",
        "uvicorn",
        "uvicorn.error",
        "uvicorn.access",
        "Lark",
    ):
        logger = logging.getLogger(logger_name)
        _reset_logger(logger, level)
        logger.propagate = False
        for handler in handlers:
            logger.addHandler(handler)

    return logging.getLogger("meetyou")
