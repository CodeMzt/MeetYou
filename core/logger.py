"""
统一日志配置。

默认仅输出到日志文件，避免污染 CLI 交互界面。
格式: [2026-03-29 20:00:00] [meetyou.module] [LEVEL] message
"""

import logging
import os
from datetime import datetime


def setup_logger(
    log_dir: str = "logs",
    level: int = logging.INFO,
    enable_console: bool = False,
) -> logging.Logger:
    """
    配置并返回 meetyou 命名空间的 Logger。

    Args:
        log_dir: 日志文件输出目录
        level: 最低日志级别

    Returns:
        配置好的 Logger 实例
    """
    log = logging.getLogger("meetyou")

    # 防止重复配置
    if log.handlers:
        return log

    log.setLevel(level)

    formatter = logging.Formatter(
        "[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if enable_console:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.WARNING)
        console_handler.setFormatter(formatter)
        log.addHandler(console_handler)

    # 文件 handler — INFO 及以上
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(
        log_dir, f"meetyou_{datetime.now().strftime('%Y%m%d')}.log"
    )
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    log.addHandler(file_handler)

    third_party_loggers = [
        logging.getLogger("Lark"),
    ]
    for third_party_logger in third_party_loggers:
        third_party_logger.handlers.clear()
        third_party_logger.setLevel(level)
        third_party_logger.propagate = False
        third_party_logger.addHandler(file_handler)

    return log
