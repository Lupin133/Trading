from __future__ import annotations

import asyncio
import logging
from pathlib import Path
import sys
import time


def setup_logging(level: str = "INFO", log_dir: Path | None = None) -> None:
    """Configure console and rotating file logging with timestamps."""
    resolved_dir = log_dir or Path("logs")
    resolved_dir.mkdir(parents=True, exist_ok=True)
    log_path = resolved_dir / "trader.log"

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)

    logging.basicConfig(level=level, handlers=[console_handler, file_handler], force=True)
    logging.getLogger("asyncio").setLevel(logging.WARNING)


def compute_backoff(attempt: int, base: float, max_delay: float) -> float:
    return min(max_delay, base * (2**attempt))


async def resilient_sleep(delay: float, cancel_event: asyncio.Event) -> None:
    """Sleep while allowing cooperative cancellation."""
    end_time = time.monotonic() + delay
    while time.monotonic() < end_time and not cancel_event.is_set():
        await asyncio.sleep(min(0.5, end_time - time.monotonic()))
