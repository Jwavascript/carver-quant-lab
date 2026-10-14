from dataclasses import dataclass
import math


@dataclass(frozen=True)
class InstrumentSpec:
    symbol: str
    currency: str
    multiplier: float
    tick_size: float

    def __post_init__(self) -> None:
        if not self.symbol.strip():
            raise ValueError("symbol must not be empty.")

        if not self.currency.strip():
            raise ValueError("currency must not be empty.")

        if not math.isfinite(self.multiplier):
            raise ValueError(
                "multiplier must be finite and positive."
            )

        if self.multiplier <= 0:
            raise ValueError(
                "multiplier must be positive."
            )

        if not math.isfinite(self.tick_size):
            raise ValueError(
                "tick_size must be finite and positive."
            )

        if self.tick_size <= 0:
            raise ValueError(
                "tick_size must be positive."
            )