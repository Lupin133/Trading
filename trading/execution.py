from __future__ import annotations

import logging
from dataclasses import dataclass

from .broker import OrderRequest, OrderResult, PriceTick, PaperBrokerClient
from .config import AppConfig
from .risk import RiskManager, OrderContext, RiskViolation

logger = logging.getLogger("execution")


@dataclass
class ExecutionDecision:
    signal: str  # BUY, SELL, or HOLD
    stop_loss: float | None
    take_profit: float | None


class OrderHandler:
    """Executes broker-safe orders with mandatory stop-loss and filters."""

    def __init__(self, broker: PaperBrokerClient, risk_manager: RiskManager, config: AppConfig):
        self.broker = broker
        self.risk_manager = risk_manager
        self.config = config

    async def execute(self, tick: PriceTick, decision: ExecutionDecision, account: dict, positions: dict) -> OrderResult:
        if decision.signal == "HOLD":
            return OrderResult(True, 0, None, reason="No action")

        if decision.stop_loss is None:
            return OrderResult(False, 0, None, reason="Stop-loss required")

        if tick.spread > self.config.spread_limit:
            return OrderResult(False, 0, None, reason="Spread too wide")

        if tick.volatility > self.config.volatility_limit:
            return OrderResult(False, 0, None, reason="Volatility too high")

        side = "BUY" if decision.signal == "BUY" else "SELL"
        ctx = OrderContext(
            symbol=tick.symbol,
            side=side,
            price=tick.ask if side == "BUY" else tick.bid,
            stop_loss=decision.stop_loss,
            take_profit=decision.take_profit,
            spread=tick.spread,
            volatility=tick.volatility,
        )

        if side == "BUY" and ctx.stop_loss >= ctx.price:
            return OrderResult(False, 0, None, reason="Stop-loss must be below entry for BUY")
        if side == "SELL" and ctx.stop_loss <= ctx.price:
            return OrderResult(False, 0, None, reason="Stop-loss must be above entry for SELL")

        try:
            size = self.risk_manager.validate_order(ctx, account=account, positions=positions)
        except RiskViolation as exc:
            logger.warning("Order rejected by risk manager: %s", exc)
            return OrderResult(False, 0, None, reason=str(exc))

        order = OrderRequest(
            symbol=tick.symbol,
            side=side,
            size=size,
            price=ctx.price,
            stop_loss=decision.stop_loss,
            take_profit=decision.take_profit,
            order_type="MARKET",
            time_in_force="IOC",
            client_id=self.config.magic_number,
        )
        result = await self.broker.submit_order(order)
        if not result.success:
            logger.error("Order submission failed: %s", result.reason)
            return result

        logger.info(
            "Order executed side=%s size=%.4f price=%.5f sl=%.5f tp=%s",
            side,
            result.filled_size,
            result.avg_price,
            decision.stop_loss,
            decision.take_profit,
        )
        return result
