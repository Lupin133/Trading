from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import AsyncIterator

import yfinance as yf

from .config import AppConfig

logger = logging.getLogger("broker")


@dataclass
class PriceTick:
    symbol: str
    bid: float
    ask: float
    timestamp: float
    spread: float
    volatility: float
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None


@dataclass
class OrderRequest:
    symbol: str
    side: str  # BUY or SELL
    size: float
    price: float
    stop_loss: float
    take_profit: float | None
    order_type: str = "MARKET"
    time_in_force: str = "IOC"
    client_id: str = ""


@dataclass
class OrderResult:
    success: bool
    filled_size: float
    avg_price: float | None
    reason: str | None = None
    order_id: str | None = None


class PaperBrokerClient:
    """
    Paper-trading broker: pulls real prices via yfinance and simulates fills, margin, and PnL.
    """

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.connected = False
        self.balance = config.initial_balance
        self.equity = config.initial_balance
        self.margin_used = 0.0
        self.positions: dict[str, dict[str, float]] = {}
        self._last_prices: dict[str, float] = {}
        self._latency_ms = 25
        self._ticker = yf.Ticker(self.config.data_symbol)

    async def connect(self) -> None:
        # Validate data source availability with a quick fetch.
        await asyncio.to_thread(self._fetch_price_sync)
        self.connected = True
        logger.info("Connected to paper broker with data feed %s", self.config.data_symbol)

    async def close(self) -> None:
        self.connected = False
        logger.info("Paper broker connection closed")

    def _fetch_price_sync(self) -> tuple[float, float, float, float]:
        data = self._ticker.history(period="1d", interval="1m")
        if data.empty:
            raise RuntimeError("Empty price history from yfinance")
        last = data.tail(1)
        open_ = float(last["Open"].iloc[0])
        high = float(last["High"].iloc[0])
        low = float(last["Low"].iloc[0])
        close = float(last["Close"].iloc[0])
        return open_, high, low, close

    def _mark_positions(self, mid_price: float) -> None:
        unrealized = 0.0
        margin = 0.0
        for symbol, position in list(self.positions.items()):
            position["pnl"] = (mid_price - position["entry"]) * position["size"]
            unrealized += position["pnl"]
            margin += abs(position["size"] * mid_price) / self.config.leverage_limit
            self.positions[symbol] = position
        self.margin_used = margin
        self.equity = self.balance + unrealized

    async def price_stream(self, symbols: list[str]) -> AsyncIterator[PriceTick]:
        """Yield prices from yfinance at a fixed polling interval."""
        symbol = symbols[0] if symbols else self.config.data_symbol
        while self.connected:
            try:
                open_, high, low, close = await asyncio.to_thread(self._fetch_price_sync)
                mid = close
                last_mid = self._last_prices.get(symbol, mid)
                spread = self.config.simulated_spread
                bid = mid - spread / 2
                ask = mid + spread / 2
                volatility = abs(mid - last_mid) / last_mid if last_mid else 0.0
                self._last_prices[symbol] = mid
                self._mark_positions(mid)
                yield PriceTick(
                    symbol=symbol,
                    bid=bid,
                    ask=ask,
                    timestamp=time.time(),
                    spread=spread,
                    volatility=volatility,
                    open=open_,
                    high=high,
                    low=low,
                    close=close,
                )
            except Exception as exc:
                logger.error("Price fetch failed: %s", exc)
            await asyncio.sleep(self.config.data_poll_interval)

    async def get_account_info(self) -> dict[str, float]:
        """Return account metrics for risk checks."""
        # Ensure equity reflects latest marks.
        last_mid = next(iter(self._last_prices.values()), None)
        if last_mid is not None:
            self._mark_positions(last_mid)
        unrealized = sum(pos["pnl"] for pos in self.positions.values())
        self.equity = self.balance + unrealized
        return {
            "balance": self.balance,
            "equity": self.equity,
            "margin_used": self.margin_used,
            "unrealized": unrealized,
        }

    async def submit_order(self, order: OrderRequest) -> OrderResult:
        if not self.connected:
            return OrderResult(False, 0, None, reason="Disconnected")

        await asyncio.sleep(self._latency_ms / 1000.0)

        mid = self._last_prices.get(order.symbol)
        if mid is None:
            _, _, _, close = await asyncio.to_thread(self._fetch_price_sync)
            mid = close
            self._last_prices[order.symbol] = mid

        spread = self.config.simulated_spread
        bid = mid - spread / 2
        ask = mid + spread / 2
        fill_price = ask if order.side == "BUY" else bid
        slip = self.config.simulated_slippage
        fill_price += slip if order.side == "BUY" else -slip

        position = self.positions.get(order.symbol, {"size": 0.0, "entry": fill_price, "pnl": 0.0})
        signed_size = order.size if order.side == "BUY" else -order.size

        # Realize PnL when reducing/closing, otherwise adjust average price when adding.
        if position["size"] == 0 or (position["size"] > 0 and signed_size > 0) or (position["size"] < 0 and signed_size < 0):
            new_size = position["size"] + signed_size
            if position["size"] != 0:
                position["entry"] = (
                    position["entry"] * abs(position["size"]) + fill_price * abs(signed_size)
                ) / abs(new_size)
            position["size"] = new_size
        else:
            closing_size = min(abs(position["size"]), abs(signed_size))
            realized = (fill_price - position["entry"]) * closing_size * (1 if position["size"] > 0 else -1)
            self.balance += realized
            position["size"] = position["size"] + signed_size
            if position["size"] == 0:
                position["entry"] = 0.0
            else:
                position["entry"] = fill_price

        position["pnl"] = (mid - position["entry"]) * position["size"]
        if position["size"] == 0:
            self.positions.pop(order.symbol, None)
        else:
            self.positions[order.symbol] = position

        self._mark_positions(mid)

        order_id = f"{order.client_id}-{int(time.time() * 1000)}"
        logger.info(
            "Order filled id=%s side=%s size=%.4f price=%.2f sl=%.2f",
            order_id,
            order.side,
            order.size,
            fill_price,
            order.stop_loss,
        )
        return OrderResult(True, order.size, fill_price, order_id=order_id)


# Backward compatibility alias for existing imports.
SimulatedBrokerClient = PaperBrokerClient
