from dataclasses import dataclass
from datetime import date
import math

import pandas as pd

from carver_quant.futures_data import (
    BackAdjustedPrice,
)

@dataclass(frozen=True)
class VolatilityPoint:
    date: date
    price_volatility: float | None


def calculate_price_changes(
    adjusted_prices: list[BackAdjustedPrice],
) -> list[float | None]:
    if not adjusted_prices:
        return []

    changes: list[float | None] = [None]

    for previous, current in zip(
        adjusted_prices,
        adjusted_prices[1:],
    ):
        change = (
            current.adjusted_price
            - previous.adjusted_price
        )

        if not math.isfinite(change):
            raise ValueError(
                "price change must be finite."
            )

        changes.append(change)

    return changes


def calculate_ewma_price_volatility(
    adjusted_prices: list[BackAdjustedPrice],
    span: int = 32,
) -> list[VolatilityPoint]:
    if span < 2:
        raise ValueError(
            "span must be at least 2."
        )

    if not adjusted_prices:
        return []

    changes = calculate_price_changes(
        adjusted_prices
    )

    change_series = pd.Series(
        changes,
        dtype="float64",
    )

    volatility_series = (
        change_series
        .ewm(
            span=span,
            adjust=False,
            min_periods=2,
        )
        .std(
            bias=False
        )
    )

    results: list[VolatilityPoint] = []

    for price, volatility in zip(
        adjusted_prices,
        volatility_series,
    ):
        if pd.isna(volatility):
            value = None
        else:
            value = float(volatility)

        results.append(
            VolatilityPoint(
                date=price.date,
                price_volatility=value,
            )
        )

    return results

def blend_price_volatility(
    short_run: list[VolatilityPoint],
    long_run: list[VolatilityPoint],
    short_weight: float = 0.7,
) -> list[VolatilityPoint]:
    if len(short_run) != len(long_run):
        raise ValueError(
            "short_run and long_run lengths must match."
        )

    if not 0.0 <= short_weight <= 1.0:
        raise ValueError(
            "short_weight must be between 0 and 1."
        )

    long_weight = 1.0 - short_weight

    results: list[VolatilityPoint] = []

    for short, long in zip(
        short_run,
        long_run,
    ):
        if short.date != long.date:
            raise ValueError(
                "short_run and long_run dates must match."
            )

        if (
            short.price_volatility is None
            or long.price_volatility is None
        ):
            value = None
        else:
            value = (
                short_weight
                * short.price_volatility
                + long_weight
                * long.price_volatility
            )

        results.append(
            VolatilityPoint(
                date=short.date,
                price_volatility=value,
            )
        )

    return results

def calculate_long_run_average_volatility(
    volatility: list[VolatilityPoint],
    window: int = 2560,
) -> list[VolatilityPoint]:
    if (
        not isinstance(window, int)
        or isinstance(window, bool)
        or window <= 0
    ):
        raise ValueError(
            "window must be a positive integer."
        )

    if not volatility:
        return []

    values = [
        point.price_volatility
        for point in volatility
    ]

    series = pd.Series(
        values,
        dtype=float,
    )

    long_run = series.rolling(
        window=window,
        min_periods=1,
    ).mean()

    results: list[
        VolatilityPoint
    ] = []

    for point, value in zip(
        volatility,
        long_run,
    ):
        if pd.isna(value):
            long_run_value = None
        else:
            long_run_value = float(value)

        results.append(
            VolatilityPoint(
                date=point.date,
                price_volatility=(
                    long_run_value
                ),
            )
        )

    return results

def calculate_carver_blended_price_volatility(
    adjusted_prices: list[BackAdjustedPrice],
    short_span: int = 32,
    long_run_window: int = 2560,
    short_weight: float = 0.7,
) -> list[VolatilityPoint]:
    short_run = (
        calculate_ewma_price_volatility(
            adjusted_prices=adjusted_prices,
            span=short_span,
        )
    )

    long_run = (
        calculate_long_run_average_volatility(
            volatility=short_run,
            window=long_run_window,
        )
    )

    return blend_price_volatility(
        short_run=short_run,
        long_run=long_run,
        short_weight=short_weight,
    )