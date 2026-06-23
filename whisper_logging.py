import logging
import sys
import os
from logging.handlers import RotatingFileHandler
from typing import Optional

_LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")

class TkinterHandler(logging.Handler):
    def __init__(self, widget_getter) -> None:
        super().__init__()
        self._get_widget = widget_getter

    def emit(self, record: logging.LogRecord) -> None:
        widget = self._get_widget()
        if widget is None:
            return
        msg = self.format(record)
        try:
            widget.configure(state="normal")
            widget.insert("end", msg + "\n")
            widget.see("end")
            widget.configure(state="disabled")
        except Exception:
            pass


def setup_logger(name: str = "whisper", log_file: Optional[str] = None, level: int = logging.DEBUG) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.handlers.clear()

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    log_path = log_file or os.path.join(_LOG_DIR, f"{name}.log")
    try:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        fh = RotatingFileHandler(
            log_path,
            maxBytes=5 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(formatter)
        logger.addHandler(fh)
    except OSError:
        pass

    sh = logging.StreamHandler(sys.stderr)
    sh.setLevel(logging.INFO)
    sh.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    logger.addHandler(sh)

    return logger


log = setup_logger()


def get_logger() -> logging.Logger:
    return log
