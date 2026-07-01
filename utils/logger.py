"""
Centralized logging setup for Dealyze.
Writes to both console and logs/dealyze.log (rotating).
The log file serves as proof of AI agent activity for the hackathon jury.
"""
import logging
import logging.handlers
import os
from pathlib import Path

LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging(level: int = logging.INFO) -> None:
    """Call once at app startup to configure all handlers."""
    root = logging.getLogger()
    if root.handlers:
        return  # already configured

    root.setLevel(level)
    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

    # Console
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)

    # Rotating file — 5 MB per file, keep 10 files
    file_handler = logging.handlers.RotatingFileHandler(
        LOG_DIR / "dealyze.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=10,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)
