import asyncio

from trading.config import AppConfig
from trading.engine import AsyncTradingEngine
from trading.strategy import TrendFollowingStrategy
from trading.utils import setup_logging
from trading.broker import PaperBrokerClient
from trading.risk import RiskManager
from trading.execution import OrderHandler
from trading.state import StateManager


async def main() -> None:
    config = AppConfig.from_env()
    setup_logging(config.log_level, config.log_dir)

    state_manager = StateManager(config.state_file, initial_balance=config.initial_balance)
    broker = PaperBrokerClient(config)
    risk_manager = RiskManager(config)
    order_handler = OrderHandler(broker=broker, risk_manager=risk_manager, config=config)
    strategy = TrendFollowingStrategy()

    engine = AsyncTradingEngine(
        broker=broker,
        strategy=strategy,
        state_manager=state_manager,
        order_handler=order_handler,
        risk_manager=risk_manager,
        config=config,
    )

    # Demonstration runtime is bounded to avoid runaway processes in this example.
    await engine.run(runtime_seconds=30)


if __name__ == "__main__":
    asyncio.run(main())
