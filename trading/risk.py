from __future__ import annotations

import logging
from dataclasses import dataclass

from .config import AppConfig

logger = logging.getLogger("risk")


@dataclass
class OrderContext:
    symbol: str
    side: str
    price: float
    stop_loss: float
    take_profit: float | None
    spread: float
    volatility: float


class RiskViolation(Exception):
    pass


class RiskManager:
    """Gatekeeper that blocks orders violating hard limits."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.daily_start_equity: float | None = None
        self.equity_peak: float | None = None

    def compute_position_size(self, equity: float, stop_distance: float, price: float) -> float:
        if stop_distance <= 0:
            raise RiskViolation("Stop distance must be positive")

        risk_amount = equity * self.config.risk_per_trade
        size = risk_amount / stop_distance
        return max(size, 0.0)

    def _check_circuit_breakers(self, equity: float) -> None:
        if self.daily_start_equity is None:
            self.daily_start_equity = equity
            self.equity_peak = equity

        self.equity_peak = max(self.equity_peak or equity, equity)

        if equity <= (self.daily_start_equity * (1 - self.config.max_daily_loss)):
            raise RiskViolation("Daily loss limit reached; trading halted")

        if equity <= (self.equity_peak * (1 - self.config.max_drawdown)):
            raise RiskViolation("Max drawdown breached; trading halted")

    def _check_leverage_and_exposure(
        self, symbol: str, price: float, size: float, account: dict, positions: dict
    ) -> None:
        notional = price * size
        projected_margin = account["margin_used"] + notional / self.config.leverage_limit
        if projected_margin > account["equity"]:
            raise RiskViolation("Insufficient margin for order")

        current_symbol_notional = abs(positions.get(symbol, {}).get("size", 0.0) * price)
        if current_symbol_notional + notional > account["equity"] * self.config.max_symbol_exposure:
            raise RiskViolation("Per-symbol exposure limit exceeded")

        aggregate_notional = sum(abs(pos["size"] * price) for pos in positions.values())
        if aggregate_notional + notional > account["equity"] * self.config.max_global_exposure:
            raise RiskViolation("Global exposure limit exceeded")

    def validate_order(
        self,
        ctx: OrderContext,
        account: dict,
        positions: dict,
    ) -> float:
        """Return approved position size if risk rules pass."""
        self._check_circuit_breakers(account["equity"])

        stop_distance = abs(ctx.price - ctx.stop_loss)
        size = self.compute_position_size(account["equity"], stop_distance, ctx.price)
        if size <= 0:
            raise RiskViolation("Computed size is zero; reject order")

        self._check_leverage_and_exposure(ctx.symbol, ctx.price, size, account, positions)
        return size
