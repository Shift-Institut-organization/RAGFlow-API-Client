"""Structured logging configuration for Bruno Populator."""

import logging
import os
import sys
from enum import Enum
from pathlib import Path
from typing import Any

from paths import DEFAULT_LOG_FILE


class LogLevelMode(str, Enum):
    """Logging environment modes determining which env var controls log levels."""

    POPULATOR = "POPULATOR"  # Uses LOG_LEVEL env var (default: INFO)
    CONVERSE = "CONVERSE"  # Uses CONVERSE_LOG_LEVEL env var (default: WARNING)


_CURRENT_LOG_MODE: LogLevelMode = LogLevelMode.POPULATOR


def set_log_level_mode(mode: LogLevelMode) -> None:
    """
    Set the active global logging mode (LogLevelMode.POPULATOR or LogLevelMode.CONVERSE).

    Updates existing loggers and sets default level behavior for future get_logger calls.
    """
    global _CURRENT_LOG_MODE
    _CURRENT_LOG_MODE = mode

    target_level = get_current_mode_log_level()

    for logger_name, logger_obj in logging.Logger.manager.loggerDict.items():
        if isinstance(logger_obj, logging.Logger) and (
            logger_name.startswith("bruno_populator")
            or logger_name.startswith("bruno_converser")
            or logger_name in ["start_bruno", "start_converse"]
        ):
            logger_obj.setLevel(target_level)


def get_current_mode_log_level() -> int:
    """Read target log level integer based on the active LogLevelMode."""
    if _CURRENT_LOG_MODE == LogLevelMode.CONVERSE:
        env_level = os.environ.get("CONVERSE_LOG_LEVEL", "WARNING")
    else:
        env_level = os.environ.get("LOG_LEVEL", "INFO")
    return parse_log_level(env_level)


def parse_log_level(level_val: Any) -> int:
    """
    Parse log level input (string name or int) into standard logging level integer.

    Supports 'DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL' (case-insensitive) or int.
    Defaults to logging.INFO (20) if unrecognized.
    """
    if isinstance(level_val, int):
        return level_val
    if isinstance(level_val, str):
        val_upper = level_val.strip().upper()
        if hasattr(logging, val_upper):
            return getattr(logging, val_upper)
        if val_upper.isdigit():
            return int(val_upper)
    return logging.INFO


def get_logger(
    name: str = "bruno_populator",
    level: int | str | None = None,
    log_file: Path | str | None = DEFAULT_LOG_FILE,
) -> logging.Logger:
    """
    Retrieve or create a configured logger with standard formatting.

    If level is provided, it explicitly overrides. Otherwise, uses the active LogLevelMode environment setting.
    If log_file is provided (defaults to DEFAULT_LOG_FILE), logs will also be appended to that file.
    """
    logger = logging.getLogger(name)

    if level is not None:
        target_level = parse_log_level(level)
    else:
        target_level = get_current_mode_log_level()

    logger.setLevel(target_level)

    formatter = logging.Formatter(
        fmt="[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console stream handler
    has_stream_handler = any(
        isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler) for h in logger.handlers
    )
    if not has_stream_handler:
        if hasattr(sys.stdout, "reconfigure"):
            try:
                sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass

        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(formatter)
        logger.addHandler(stream_handler)

    # File handler
    if log_file:
        resolved_file = Path(log_file).resolve()
        has_file_handler = any(
            isinstance(h, logging.FileHandler) and Path(h.baseFilename) == resolved_file for h in logger.handlers
        )
        if not has_file_handler:
            resolved_file.parent.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(resolved_file, encoding="utf-8")
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)

    return logger
