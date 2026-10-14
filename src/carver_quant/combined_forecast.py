from dataclasses import dataclass
from datetime import date

from carver_quant.forecast import (
    calculate_ewmac_forecast,
    make_afts_ewmac_config,
)
from carver_quant.futures_data import (
    BackAdjustedPrice,
)
from carver_quant.volatility import (
    VolatilityPoint,
)


AFTS_TREND_RULE_SETS = {
    (2, 4, 8, 16, 32, 64): 1.26,
    (4, 8, 16, 32, 64): 1.19,
    (8, 16, 32, 64): 1.13,
    (16, 32, 64): 1.08,
    (32, 64): 1.03,
    (64,): 1.00,
}


@dataclass(frozen=True)
class CombinedTrendForecastPoint:
    date: date

    component_forecasts: dict[
        int,
        float | None,
    ]

    weighted_forecast: float | None

    fdm: float

    combined_forecast: float | None


def get_afts_trend_fdm(
    fast_spans: tuple[int, ...],
) -> float:
    if fast_spans not in AFTS_TREND_RULE_SETS:
        raise ValueError(
            "Unsupported AFTS trend rule set."
        )

    return AFTS_TREND_RULE_SETS[
        fast_spans
    ]


def combine_forecast_values(
    forecasts: list[float],
    fdm: float,
    cap: float = 20.0,
) -> tuple[float, float]:
    if not forecasts:
        raise ValueError(
            "forecasts must not be empty."
        )

    weighted = (
        sum(forecasts)
        / len(forecasts)
    )

    diversified = (
        weighted
        * fdm
    )

    capped = max(
        -cap,
        min(
            cap,
            diversified,
        ),
    )

    return (
        weighted,
        capped,
    )


def calculate_combined_ewmac_forecast(
    adjusted_prices: list[BackAdjustedPrice],
    volatility: list[VolatilityPoint],
    fast_spans: tuple[int, ...] = (
        2,
        4,
        8,
        16,
        32,
        64,
    ),
) -> list[CombinedTrendForecastPoint]:
    fdm = get_afts_trend_fdm(
        fast_spans
    )

    component_series = {
        fast_span: calculate_ewmac_forecast(
            adjusted_prices=adjusted_prices,
            volatility=volatility,
            config=make_afts_ewmac_config(
                fast_span
            ),
        )
        for fast_span in fast_spans
    }

    results: list[
        CombinedTrendForecastPoint
    ] = []

    for index, price in enumerate(
        adjusted_prices
    ):
        components = {
            fast_span: (
                component_series[
                    fast_span
                ][index]
                .capped_forecast
            )
            for fast_span in fast_spans
        }

        if any(
            value is None
            for value in components.values()
        ):
            weighted = None
            combined = None

        else:
            values = [
                value
                for value
                in components.values()
                if value is not None
            ]

            weighted, combined = (
                combine_forecast_values(
                    forecasts=values,
                    fdm=fdm,
                )
            )

        results.append(
            CombinedTrendForecastPoint(
                date=price.date,
                component_forecasts=components,
                weighted_forecast=weighted,
                fdm=fdm,
                combined_forecast=combined,
            )
        )

    return results