from __future__ import annotations

import logging
import sys
from contextlib import contextmanager
from time import perf_counter


def setup_logger(name="fetcher", log_file="fetcher.log", level=logging.INFO):
    """
    Thread-safe logger: clean messages to the console, detailed
    timestamped messages to a log file.
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)

    if logger.hasHandlers():
        logger.handlers.clear()

    file_formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(threadName)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler = logging.FileHandler(log_file)
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(logging.Formatter(fmt="%(message)s"))
    logger.addHandler(console_handler)

    return logger


@contextmanager
def timer(description, logger=None):
    """Context manager to measure and log execution time."""
    start = perf_counter()
    yield
    elapsed = perf_counter() - start
    msg = f"{description} took {elapsed:.2f}s"
    if logger:
        logger.info(msg)
    else:
        print(msg)
