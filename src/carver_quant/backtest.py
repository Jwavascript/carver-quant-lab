import math
from dataclasses import dataclass

from carver_quant.daily_step import (
    DailyStepResult,
    run_daily_step,
)


@dataclass(frozen=True)
class BacktestDayInput:
    previous_adjusted_price: float
    current_adjusted_price: float

    daily_cash_vol_target: float
    price_volatility: float
    multiplier: float
    forecast: float

    execution_bid: float
    execution_ask: float
    tick_size: float
    commission_per_contract: float


def run_backtest(
    initial_account_value: float,
    initial_position: int,
    days: list[BacktestDayInput],
) -> list[DailyStepResult]:
    account_value = initial_account_value
    position = initial_position

    results = []
    previous_day_current_price = None

    for day in days:
        if previous_day_current_price is not None:
            if not math.isclose(
                day.previous_adjusted_price,
                previous_day_current_price,
                rel_tol=0.0,
                abs_tol=1e-12,
            ):
                raise ValueError(
                    "Price intervals must be continuous between days."
                )

        result = run_daily_step(
            previous_account_value=account_value,
            current_position=position,
            previous_adjusted_price=day.previous_adjusted_price,
            current_adjusted_price=day.current_adjusted_price,
            daily_cash_vol_target=day.daily_cash_vol_target,
            price_volatility=day.price_volatility,
            multiplier=day.multiplier,
            forecast=day.forecast,
            execution_bid=day.execution_bid,
            execution_ask=day.execution_ask,
            tick_size=day.tick_size,
            commission_per_contract=day.commission_per_contract,
        )

        results.append(result)

        account_value = result.closing_account_value
        position = result.new_position
        previous_day_current_price = day.current_adjusted_price

    return results