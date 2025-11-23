from __future__ import annotations

import collections
from dataclasses import dataclass

from .broker import PriceTick


class Signal:
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass
class StrategyDecision:
    signal: str
    stop_loss: float | None
    take_profit: float | None


class BaseStrategy:
    def get_signal(self, tick: PriceTick) -> StrategyDecision:
        raise NotImplementedError


class TrendFollowingStrategy(BaseStrategy):
    """EMA crossover + RSI filter + ATR-based stop for XAUUSD paper trading."""

    def __init__(
        self,
        fast_period: int = 9,
        slow_period: int = 21,
        rsi_period: int = 14,
        atr_period: int = 14,
        atr_multiplier: float = 2.0,
    ) -> None:
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.rsi_period = rsi_period
        self.atr_period = atr_period
        self.atr_multiplier = atr_multiplier

        self.fast_ema: dict[str, float | None] = {}
        self.slow_ema: dict[str, float | None] = {}
        self.atr: dict[str, float | None] = {}
        self.prev_close: dict[str, float | None] = {}
        self.avg_gain: dict[str, float | None] = {}
        self.avg_loss: dict[str, float | None] = {}
        self.rsi_seed: dict[str, collections.deque[float]] = {}

    def _ema(self, price: float, prev: float | None, period: int) -> float:
        if prev is None:
            return price
        k = 2 / (period + 1)
        return price * k + prev * (1 - k)

    def _update_rsi(self, symbol: str, close: float) -> float | None:
        prev = self.prev_close.get(symbol)
        if prev is None:
            self.prev_close[symbol] = close
            return None

        delta = close - prev
        gain = max(delta, 0.0)
        loss = max(-delta, 0.0)

        if symbol not in self.avg_gain or self.avg_gain[symbol] is None:
            seed = self.rsi_seed.setdefault(symbol, collections.deque(maxlen=self.rsi_period))
            seed.append(delta)
            if len(seed) < self.rsi_period:
                self.prev_close[symbol] = close
                return None
            gains = [max(x, 0.0) for x in seed]
            losses = [max(-x, 0.0) for x in seed]
            self.avg_gain[symbol] = sum(gains) / self.rsi_period
            self.avg_loss[symbol] = sum(losses) / self.rsi_period
        else:
            self.avg_gain[symbol] = (self.avg_gain[symbol] * (self.rsi_period - 1) + gain) / self.rsi_period
            self.avg_loss[symbol] = (self.avg_loss[symbol] * (self.rsi_period - 1) + loss) / self.rsi_period

        self.prev_close[symbol] = close
        avg_gain = self.avg_gain[symbol] or 0.0
        avg_loss = self.avg_loss[symbol] or 0.0
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def _update_atr(self, symbol: str, high: float, low: float, close: float) -> float | None:
        prev_close = self.prev_close.get(symbol)
        tr = (
            max(
                high - low,
                abs(high - prev_close) if prev_close is not None else 0.0,
                abs(low - prev_close) if prev_close is not None else 0.0,
            )
            if prev_close is not None
            else high - low
        )
        prev_atr = self.atr.get(symbol)
        if prev_atr is None:
            self.atr[symbol] = tr
        else:
            self.atr[symbol] = (prev_atr * (self.atr_period - 1) + tr) / self.atr_period
        return self.atr[symbol]

    def get_signal(self, tick: PriceTick) -> StrategyDecision:
        close = tick.close if tick.close is not None else (tick.bid + tick.ask) / 2
        high = tick.high if tick.high is not None else close
        low = tick.low if tick.low is not None else close

        prev_fast = self.fast_ema.get(tick.symbol)
        prev_slow = self.slow_ema.get(tick.symbol)

        fast = self._ema(close, prev_fast, self.fast_period)
        slow = self._ema(close, prev_slow, self.slow_period)
        self.fast_ema[tick.symbol] = fast
        self.slow_ema[tick.symbol] = slow

        atr = self._update_atr(tick.symbol, high, low, close)
        rsi = self._update_rsi(tick.symbol, close)

        if prev_fast is None or prev_slow is None or atr is None or rsi is None:
            return StrategyDecision(Signal.HOLD, None, None)

        bullish_cross = prev_fast <= prev_slow and fast > slow and rsi < 70
        bearish_cross = prev_fast >= prev_slow and fast < slow and rsi > 30

        stop_distance = self.atr_multiplier * atr
        if bullish_cross:
            stop = close - stop_distance
            return StrategyDecision(Signal.BUY, stop_loss=stop, take_profit=None)
        if bearish_cross:
            stop = close + stop_distance
            return StrategyDecision(Signal.SELL, stop_loss=stop, take_profit=None)

        return StrategyDecision(Signal.HOLD, None, None)
