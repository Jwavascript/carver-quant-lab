import math
from dataclasses import (
    dataclass,
    field,
)
from carver_quant.instrument import InstrumentSpec
from carver_quant.contract_aware_daily_step import (
    ContractAwareDailyStepResult,
    run_contract_aware_daily_step,
)
from carver_quant.roll_execution import ContractQuote


@dataclass(frozen=True)
class ContractAwareBacktestDayInput:
    previous_adjusted_price: float
    current_adjusted_price: float

    daily_cash_vol_target: float
    price_volatility: float
    forecast: float

    quotes: dict[str, ContractQuote]

    commission_per_contract: float

    roll_to_contract: str | None
    slippage_ticks: int = 0
    fx_to_base: float = 1.0

    margin_per_contract_base: dict[
        str,
        float,
    ] = field(
        default_factory=dict
    )

def run_contract_aware_backtest(
    initial_account_value: float,
    initial_position: int,
    initial_contract_positions: dict[str, int],
    initial_active_contract: str,
    days: list[ContractAwareBacktestDayInput],
    instrument_spec: InstrumentSpec,
) -> list[ContractAwareDailyStepResult]:

    account_value = initial_account_value
    position = initial_position
    contract_positions = initial_contract_positions.copy()
    active_contract = initial_active_contract

    results = []

    previous_day_current_price: float | None = None
    for day in days:
        if (
            previous_day_current_price is not None
            and not math.isclose(
                day.previous_adjusted_price,
                previous_day_current_price,
                rel_tol=0.0,
                abs_tol=1e-12,
            )
        ):
            raise ValueError(
                "Adjusted price interval is not continuous."
            )

        result = run_contract_aware_daily_step(
            previous_account_value=account_value,
            current_position=position,
            current_contract_positions=contract_positions,
            active_contract=active_contract,
            roll_to_contract=day.roll_to_contract,
            previous_adjusted_price=day.previous_adjusted_price,
            current_adjusted_price=day.current_adjusted_price,
            daily_cash_vol_target=day.daily_cash_vol_target,
            price_volatility=day.price_volatility,
            multiplier=instrument_spec.multiplier,
            forecast=day.forecast,
            quotes=day.quotes,
            tick_size=instrument_spec.tick_size,
            commission_per_contract=day.commission_per_contract,
            slippage_ticks=day.slippage_ticks,
            fx_to_base=day.fx_to_base,
        )

        results.append(result)

        account_value = result.closing_account_value
        position = result.new_instrument_position
        contract_positions = result.new_contract_positions
        active_contract = result.active_contract

        previous_day_current_price = day.current_adjusted_price

    return results