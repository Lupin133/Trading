from __future__ import annotations

import asyncio
import datetime
import logging
import time
from typing import Optional

from .broker import PaperBrokerClient, PriceTick
from .config import AppConfig
from .execution import ExecutionDecision, OrderHandler
from .risk import RiskManager
from .state import StateManager
from .strategy import BaseStrategy, Signal
from .utils import compute_backoff, resilient_sleep

logger = logging.getLogger("engine")


class AsyncTradingEngine:
    """Coordinates data, risk checks, execution, and persistence."""

    def __init__(
        self,
        broker: PaperBrokerClient,
        strategy: BaseStrategy,
        state_manager: StateManager,
        order_handler: OrderHandler,
        risk_manager: RiskManager,
        config: AppConfig,
    ) -> None:
        self.broker = broker
        self.strategy = strategy
        self.state_manager = state_manager
        self.order_handler = order_handler
        self.risk_manager = risk_manager
        self.config = config

        self._price_queue: asyncio.Queue[PriceTick] = asyncio.Queue(maxsize=1000)
        self._cancel_event = asyncio.Event()
        self._tasks: list[asyncio.Task] = []
        self._state: dict = {}
        self._last_persist = time.time()

    async def run(self, runtime_seconds: Optional[float] = None) -> None:
        self._state = await self.state_manager.load()
        self.risk_manager.daily_start_equity = self._state.get("daily_start_equity")
        self.risk_manager.equity_peak = self._state.get("equity_peak")
        await self._connect_with_backoff()

        producer = asyncio.create_task(self._price_producer())
        consumer = asyncio.create_task(self._price_consumer())
        monitor = asyncio.create_task(self._health_monitor())
        self._tasks = [producer, consumer, monitor]

        if runtime_seconds:
            await resilient_sleep(runtime_seconds, self._cancel_event)
            await self.stop()
        else:
            await asyncio.gather(*self._tasks)

    async def stop(self) -> None:
        self._cancel_event.set()
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        await self.broker.close()
        await self.state_manager.persist(self._state)
        logger.info("Engine stopped gracefully")

    async def _connect_with_backoff(self) -> None:
        attempt = 0
        while not self.broker.connected and not self._cancel_event.is_set():
            try:
                await self.broker.connect()
                return
            except Exception as exc:
                delay = compute_backoff(attempt, self.config.reconnect_base, self.config.reconnect_max)
                logger.error("Broker connection failed (%s). Retrying in %.1fs", exc, delay)
                attempt += 1
                await resilient_sleep(delay, self._cancel_event)

    async def _price_producer(self) -> None:
        while not self._cancel_event.is_set():
            try:
                async for tick in self.broker.price_stream(self.config.symbols):
                    await self._price_queue.put(tick)
                    if self._cancel_event.is_set():
                        break
            except Exception as exc:
                logger.error("Price stream error: %s", exc)
                await self._connect_with_backoff()

    async def _price_consumer(self) -> None:
        while not self._cancel_event.is_set():
            tick = await self._price_queue.get()
            await self._handle_tick(tick)

    async def _handle_tick(self, tick: PriceTick) -> None:
        account = await self.broker.get_account_info()
        today = datetime.date.today().isoformat()
        if self._state.get("trading_day") != today:
            self._state["trading_day"] = today
            self.risk_manager.daily_start_equity = account["equity"]
            self.risk_manager.equity_peak = account["equity"]

        self._state.update(account)
        self._state["positions"] = self.broker.positions
        self._state["daily_start_equity"] = self.risk_manager.daily_start_equity
        self._state["equity_peak"] = self.risk_manager.equity_peak

        decision = self._map_strategy_decision(self.strategy.get_signal(tick))
        if decision.signal == "HOLD":
            return

        result = await self.order_handler.execute(
            tick=tick,
            decision=decision,
            account=account,
            positions=self.broker.positions,
        )
        if result.success:
            await self.state_manager.persist(self._state)

    def _map_strategy_decision(self, strategy_decision) -> ExecutionDecision:
        signal = strategy_decision.signal
        if signal not in (Signal.BUY, Signal.SELL, Signal.HOLD):
            signal = Signal.HOLD
        return ExecutionDecision(signal=signal, stop_loss=strategy_decision.stop_loss, take_profit=strategy_decision.take_profit)

    async def _health_monitor(self) -> None:
        """Continuously ensure connectivity and log latency/pressure."""
        while not self._cancel_event.is_set():
            if not self.broker.connected:
                logger.warning("Broker disconnected; attempting reconnection")
                await self._connect_with_backoff()
            queue_depth = self._price_queue.qsize()
            if queue_depth > 500:
                logger.warning("Price queue pressure detected depth=%s", queue_depth)
            if time.time() - self._last_persist > 5:
                await self.state_manager.persist(self._state)
                self._last_persist = time.time()
            await resilient_sleep(1.0, self._cancel_event)
