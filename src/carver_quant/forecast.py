from dataclasses import dataclass
from datetime import date
import math

import pandas as pd

from carver_quant.futures_data import BackAdjustedPrice
from carver_quant.volatility import VolatilityPoint


AFTS_EWMAC_SCALARS = {
    2: 12.1,
    4: 8.53,
    8: 5.95,
    16: 4.10,
    32: 2.79,
    64: 1.91,
}


@dataclass(frozen=True)
class EWMACConfig:
    fast_span: int
    slow_span: int
    forecast_scalar: float
    cap: float = 20.0

    def __post_init__(self) -> None:
        if self.fast_span < 2:
            raise ValueError(
                "fast_span must be at least 2."
            )

        if self.slow_span <= self.fast_span:
            raise ValueError(
                "slow_span must be greater than fast_span."
            )

        if not math.isfinite(self.forecast_scalar):
            raise ValueError(
                "forecast_scalar must be finite and positive."
            )

        if self.forecast_scalar <= 0:
            raise ValueError(
                "forecast_scalar must be positive."
            )

        if not math.isfinite(self.cap):
            raise ValueError(
                "cap must be finite and positive."
            )

        if self.cap <= 0:
            raise ValueError(
                "cap must be positive."
            )


@dataclass(frozen=True)
class EWMACForecastPoint:
    date: date

    fast_ewma: float
    slow_ewma: float

    raw_crossover: float

    price_volatility: float | None

    risk_normalized_forecast: float | None
    scaled_forecast: float | None
    capped_forecast: float | None


def make_afts_ewmac_config(
    fast_span: int,
) -> EWMACConfig:
    if fast_span not in AFTS_EWMAC_SCALARS:
        raise ValueError(
            "Unsupported AFTS EWMAC fast span."
        )

    return EWMACConfig(
        fast_span=fast_span,
        slow_span=fast_span * 4,
        forecast_scalar=(
            AFTS_EWMAC_SCALARS[fast_span]
        ),
        cap=20.0,
    )


def scale_and_cap_forecast(
    raw_crossover: float,
    price_volatility: float,
    forecast_scalar: float,
    cap: float = 20.0,
) -> tuple[float, float, float] | None:
    values = [
        raw_crossover,
        price_volatility,
        forecast_scalar,
        cap,
    ]

    if not all(
        math.isfinite(value)
        for value in values
    ):
        raise ValueError(
            "forecast inputs must be finite."
        )

    if price_volatility < 0:
        raise ValueError(
            "price_volatility must not be negative."
        )

    if forecast_scalar <= 0:
        raise ValueError(
            "forecast_scalar must be positive."
        )

    if cap <= 0:
        raise ValueError(
            "cap must be positive."
        )

    # 변동성이 0이면 risk normalization을
    # 계산할 수 없으므로 forecast를 만들지 않는다.
    if price_volatility == 0:
        return None

    risk_normalized = (
        raw_crossover
        / price_volatility
    )

    scaled = (
        risk_normalized
        * forecast_scalar
    )

    capped = max(
        -cap,
        min(
            cap,
            scaled,
        ),
    )

    return (
        risk_normalized,
        scaled,
        capped,
    )


def calculate_ewmac_forecast(
    adjusted_prices: list[BackAdjustedPrice],
    volatility: list[VolatilityPoint],
    config: EWMACConfig,
) -> list[EWMACForecastPoint]:
    if len(adjusted_prices) != len(volatility):
        raise ValueError(
            "price and volatility lengths must match."
        )

    if not adjusted_prices:
        return []

    for price, vol in zip(
        adjusted_prices,
        volatility,
    ):
        if price.date != vol.date:
            raise ValueError(
                "price and volatility dates must match."
            )

    prices = pd.Series(
        [
            price.adjusted_price
            for price in adjusted_prices
        ],
        dtype="float64",
    )

    fast = (
        prices
        .ewm(
            span=config.fast_span,
            adjust=False,
        )
        .mean()
    )

    slow = (
        prices
        .ewm(
            span=config.slow_span,
            adjust=False,
        )
        .mean()
    )

    results: list[EWMACForecastPoint] = []

    for index, price in enumerate(
        adjusted_prices
    ):
        fast_value = float(
            fast.iloc[index]
        )

        slow_value = float(
            slow.iloc[index]
        )

        raw_crossover = (
            fast_value
            - slow_value
        )

        price_volatility = (
            volatility[index]
            .price_volatility
        )

        if price_volatility is None:
            risk_normalized = None
            scaled = None
            capped = None
        else:
            forecast_result = (
                scale_and_cap_forecast(
                    raw_crossover=raw_crossover,
                    price_volatility=price_volatility,
                    forecast_scalar=(
                        config.forecast_scalar
                    ),
                    cap=config.cap,
                )
            )

            if forecast_result is None:
                risk_normalized = None
                scaled = None
                capped = None
            else:
                (
                    risk_normalized,
                    scaled,
                    capped,
                ) = forecast_result

        results.append(
            EWMACForecastPoint(
                date=price.date,
                fast_ewma=fast_value,
                slow_ewma=slow_value,
                raw_crossover=raw_crossover,
                price_volatility=(
                    price_volatility
                ),
                risk_normalized_forecast=(
                    risk_normalized
                ),
                scaled_forecast=scaled,
                capped_forecast=capped,
            )
        )

    return results