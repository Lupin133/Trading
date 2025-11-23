from dataclasses import dataclass, field
from pathlib import Path
import os


@dataclass
class AppConfig:
    symbols: list[str] = field(default_factory=lambda: ["XAUUSD"])
    data_symbol: str = "GC=F"  # Yahoo Finance ticker for Gold futures fallback.
    risk_per_trade: float = 0.005  # 0.5% of equity per trade.
    max_global_exposure: float = 2.0  # As a multiple of equity.
    max_symbol_exposure: float = 1.0  # As a multiple of equity per symbol.
    max_daily_loss: float = 0.02  # 2% loss triggers trading halt.
    max_drawdown: float = 0.1  # 10% drawdown triggers halt.
    leverage_limit: float = 20.0
    spread_limit: float = 0.5
    volatility_limit: float = 0.02
    data_poll_interval: float = 5.0  # seconds
    simulated_spread: float = 0.2  # USD spread simulated on top of market mid.
    simulated_slippage: float = 0.05  # USD per fill added in trade direction.
    price_stream_interval: float = 0.5
    reconnect_base: float = 1.0
    reconnect_max: float = 30.0
    magic_number: str = "ALGOBOT-001"
    state_file: Path = Path("state.json")
    log_level: str = os.environ.get("LOG_LEVEL", "INFO")
    log_dir: Path = Path("logs")
    data_dir: Path = Path("data")
    initial_balance: float = 30_000.0

    @staticmethod
    def from_env() -> "AppConfig":
        def get_float(name: str, default: float) -> float:
            try:
                return float(os.environ.get(name, default))
            except ValueError:
                return default

        def get_list(name: str, default: list[str]) -> list[str]:
            raw = os.environ.get(name)
            if not raw:
                return default
            return [item.strip() for item in raw.split(",") if item.strip()]

        cfg = AppConfig(
            symbols=get_list("SYMBOLS", ["XAUUSD"]),
            data_symbol=os.environ.get("DATA_SYMBOL", "GC=F"),
            risk_per_trade=get_float("RISK_PER_TRADE", 0.005),
            max_global_exposure=get_float("MAX_GLOBAL_EXPOSURE", 2.0),
            max_symbol_exposure=get_float("MAX_SYMBOL_EXPOSURE", 1.0),
            max_daily_loss=get_float("MAX_DAILY_LOSS", 0.02),
            max_drawdown=get_float("MAX_DRAWDOWN", 0.1),
            leverage_limit=get_float("LEVERAGE_LIMIT", 20.0),
            spread_limit=get_float("SPREAD_LIMIT", 0.5),
            volatility_limit=get_float("VOLATILITY_LIMIT", 0.02),
            data_poll_interval=get_float("DATA_POLL_INTERVAL", 5.0),
            simulated_spread=get_float("SIMULATED_SPREAD", 0.2),
            simulated_slippage=get_float("SIMULATED_SLIPPAGE", 0.05),
            price_stream_interval=get_float("PRICE_STREAM_INTERVAL", 0.5),
            reconnect_base=get_float("RECONNECT_BASE", 1.0),
            reconnect_max=get_float("RECONNECT_MAX", 30.0),
            magic_number=os.environ.get("MAGIC_NUMBER", "ALGOBOT-001"),
            state_file=Path(os.environ.get("STATE_FILE", "state.json")),
            log_level=os.environ.get("LOG_LEVEL", "INFO"),
            log_dir=Path(os.environ.get("LOG_DIR", "logs")),
            data_dir=Path(os.environ.get("DATA_DIR", "data")),
            initial_balance=get_float("INITIAL_BALANCE", 30_000.0),
        )
        return cfg
