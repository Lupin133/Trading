from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any
import datetime

logger = logging.getLogger("state")


class StateManager:
    """Durable state for restart continuity."""

    def __init__(self, path: Path, initial_balance: float) -> None:
        self.path = path
        self.initial_balance = initial_balance
        self._lock = asyncio.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    async def load(self) -> dict[str, Any]:
        async with self._lock:
            if not self.path.exists():
                return self._default_state()
            try:
                content = self.path.read_text(encoding="utf-8")
                return json.loads(content)
            except json.JSONDecodeError:
                logger.error("State file corrupted; falling back to defaults")
                return self._default_state()

    async def persist(self, state: dict[str, Any]) -> None:
        async with self._lock:
            temp_path = self.path.with_suffix(".tmp")
            temp_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
            temp_path.replace(self.path)

    def _default_state(self) -> dict[str, Any]:
        return {
            "positions": {},
            "equity": self.initial_balance,
            "balance": self.initial_balance,
            "unrealized": 0.0,
            "margin_used": 0.0,
            "daily_start_equity": self.initial_balance,
            "equity_peak": self.initial_balance,
            "trading_day": datetime.date.today().isoformat(),
        }
