from dataclasses import dataclass
from datetime import date

from carver_quant.forecast import (
    EWMACConfig,
    calculate_ewmac_forecast,
)
from carver_quant.futures_data import (
    BackAdjustedPrice,
    ContractPrice,
    RollEvent,
    build_back_adjusted_prices,
    build_back_adjusted_prices_as_of,
)
from carver_quant.volatility import (
    calculate_carver_blended_price_volatility,
    calculate_ewma_price_volatility,
)

from carver_quant.combined_forecast import (
    calculate_combined_ewmac_forecast,
)


@dataclass(frozen=True)
class ResearchSignalPoint:
    date: date

    active_contract: str

    raw_price: float
    adjusted_price: float

    price_volatility: float | None

    raw_crossover: float

    forecast: float | None


def build_ewmac_research_signals(
    prices: list[ContractPrice],
    initial_contract: str,
    roll_events: list[RollEvent],
    ewmac_config: EWMACConfig,
    volatility_span: int = 32,
) -> list[ResearchSignalPoint]:
    adjusted_prices = build_back_adjusted_prices(
        prices=prices,
        initial_contract=initial_contract,
        roll_events=roll_events,
    )

    volatility = calculate_ewma_price_volatility(
        adjusted_prices=adjusted_prices,
        span=volatility_span,
    )

    forecasts = calculate_ewmac_forecast(
        adjusted_prices=adjusted_prices,
        volatility=volatility,
        config=ewmac_config,
    )

    if not (
        len(adjusted_prices)
        == len(volatility)
        == len(forecasts)
    ):
        raise RuntimeError(
            "Research pipeline lengths do not match."
        )

    return [
        ResearchSignalPoint(
            date=price.date,
            active_contract=price.active_contract,
            raw_price=price.raw_price,
            adjusted_price=price.adjusted_price,
            price_volatility=vol.price_volatility,
            raw_crossover=forecast.raw_crossover,
            forecast=forecast.capped_forecast,
        )
        for price, vol, forecast in zip(
            adjusted_prices,
            volatility,
            forecasts,
        )
    ]

def _build_combined_signals_from_adjusted_prices(
    adjusted_prices: list[BackAdjustedPrice],
    fast_spans: tuple[int, ...],
    volatility_span: int,
    long_run_window: int,
) -> list[ResearchSignalPoint]:
    volatility = (
        calculate_carver_blended_price_volatility(
            adjusted_prices=adjusted_prices,
            short_span=volatility_span,
            long_run_window=long_run_window,
            short_weight=0.7,
        )
    )

    combined = (
        calculate_combined_ewmac_forecast(
            adjusted_prices=adjusted_prices,
            volatility=volatility,
            fast_spans=fast_spans,
        )
    )

    if not (
        len(adjusted_prices)
        == len(volatility)
        == len(combined)
    ):
        raise RuntimeError(
            "Research pipeline lengths do not match."
        )

    return [
        ResearchSignalPoint(
            date=price.date,
            active_contract=price.active_contract,
            raw_price=price.raw_price,
            adjusted_price=price.adjusted_price,
            price_volatility=(
                vol.price_volatility
            ),
            raw_crossover=0.0,
            forecast=(
                combined_point
                .combined_forecast
            ),
        )
        for price, vol, combined_point in zip(
            adjusted_prices,
            volatility,
            combined,
        )
    ]

def build_combined_ewmac_research_signals(
    prices: list[ContractPrice],
    initial_contract: str,
    roll_events: list[RollEvent],
    fast_spans: tuple[int, ...] = (
        2,
        4,
        8,
        16,
        32,
        64,
    ),
    volatility_span: int = 32,
    long_run_window: int = 2560,
) -> list[ResearchSignalPoint]:
    adjusted_prices = build_back_adjusted_prices(
        prices=prices,
        initial_contract=initial_contract,
        roll_events=roll_events,
    )

    return _build_combined_signals_from_adjusted_prices(
        adjusted_prices=adjusted_prices,
        fast_spans=fast_spans,
        volatility_span=volatility_span,
        long_run_window=long_run_window,
    )

@dataclass(frozen=True)
class PointInTimeResearchSignalPoint:
    as_of_date: date

    active_contract: str

    raw_price: float

    # 주의:
    # 이 값은 해당 as-of snapshot 안에서만 의미가 있다.
    # 서로 다른 날짜의 snapshot_adjusted_price를
    # 빼서 P&L을 계산하면 안 된다.
    snapshot_adjusted_price: float

    price_volatility: float | None

    forecast: float | None

def build_point_in_time_combined_ewmac_signals(
    prices: list[ContractPrice],
    initial_contract: str,
    roll_events: list[RollEvent],
    fast_spans: tuple[int, ...] = (
        2,
        4,
        8,
        16,
        32,
        64,
    ),
    volatility_span: int = 32,
    long_run_window: int = 2560,
) -> list[PointInTimeResearchSignalPoint]:
    if not prices:
        return []

    as_of_dates = sorted(
        {
            price.date
            for price in prices
        }
    )

    results: list[
        PointInTimeResearchSignalPoint
    ] = []

    for as_of_date in as_of_dates:
        adjusted_prices = (
            build_back_adjusted_prices_as_of(
                prices=prices,
                initial_contract=initial_contract,
                roll_events=roll_events,
                as_of_date=as_of_date,
            )
        )

        if not adjusted_prices:
            continue

        # 해당 날짜에 active contract 가격이 없는 경우에는
        # 새로운 signal point를 만들지 않는다.
        if (
            adjusted_prices[-1].date
            != as_of_date
        ):
            continue

        snapshot_signals = (
            _build_combined_signals_from_adjusted_prices(
                adjusted_prices=adjusted_prices,
                fast_spans=fast_spans,
                volatility_span=volatility_span,
                long_run_window=long_run_window,
            )
        )

        latest = snapshot_signals[-1]

        results.append(
            PointInTimeResearchSignalPoint(
                as_of_date=as_of_date,
                active_contract=(
                    latest.active_contract
                ),
                raw_price=latest.raw_price,
                snapshot_adjusted_price=(
                    latest.adjusted_price
                ),
                price_volatility=(
                    latest.price_volatility
                ),
                forecast=latest.forecast,
            )
        )

    return results