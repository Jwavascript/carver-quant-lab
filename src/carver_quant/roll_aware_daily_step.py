from dataclasses import dataclass

from carver_quant.account_ledger import update_account_value
from carver_quant.pnl import (
    calculate_gross_pnl,
    calculate_net_pnl,
)
from carver_quant.position import calculate_target_position
from carver_quant.roll import (
    generate_roll_and_rebalance_trades,
)
from carver_quant.roll_execution import (
    ContractQuote,
    RollExecution,
    execute_contract_trades,
)
from carver_quant.trade import calculate_trade_quantity


@dataclass(frozen=True)
class RollAwareDailyStepResult:
    gross_pnl: float

    target_position: int
    directional_trade: int
    directional_trading_cost: float

    roll_executions: list[RollExecution]
    roll_trading_cost: float

    total_trading_cost: float

    new_instrument_position: int
    new_contract_positions: dict[str, int]

    net_pnl: float
    closing_account_value: float


def run_roll_aware_daily_step(
    previous_account_value: float,
    current_position: int,
    current_contract_positions: dict[str, int],
    previous_adjusted_price: float,
    current_adjusted_price: float,
    daily_cash_vol_target: float,
    price_volatility: float,
    multiplier: float,
    forecast: float,
    roll_from_contract: str,
    roll_to_contract: str,
    roll_quotes: dict[str, ContractQuote],
    tick_size: float,
    commission_per_contract: float,
) -> RollAwareDailyStepResult:
    contract_position_total = sum(
        current_contract_positions.values()
    )

    if contract_position_total != current_position:
        raise ValueError(
            "Instrument position does not match contract positions."
        )

    if (
        current_position != 0
        and roll_from_contract not in current_contract_positions
    ):
        raise ValueError(
            f"No open position in roll_from_contract: {roll_from_contract}"
        )

    gross_pnl = calculate_gross_pnl(
        position_held=current_position,
        previous_price=previous_adjusted_price,
        current_price=current_adjusted_price,
        multiplier=multiplier,
    )


    target_position = calculate_target_position(
        daily_cash_vol_target=daily_cash_vol_target,
        price_volatility=price_volatility,
        multiplier=multiplier,
        forecast=forecast,
    )

    directional_trade = calculate_trade_quantity(
        target_position=target_position,
        current_position=current_position,
    )


    directional_trading_cost = 0.0

    roll_trades = generate_roll_and_rebalance_trades(
        old_contract=roll_from_contract,
        new_contract=roll_to_contract,
        current_position=current_position,
        target_position=target_position,
    )

    roll_result = execute_contract_trades(
        current_positions=current_contract_positions,
        trades=roll_trades,
        quotes=roll_quotes,
        tick_size=tick_size,
        multiplier=multiplier,
        commission_per_contract=commission_per_contract,
    )

    roll_trading_cost = roll_result.total_trading_cost

    total_trading_cost = (
        directional_trading_cost
        + roll_trading_cost
    )

    net_pnl = calculate_net_pnl(
        gross_pnl=gross_pnl,
        total_trading_cost=total_trading_cost,
    )

    closing_account_value = update_account_value(
        previous_account_value=previous_account_value,
        net_pnl=net_pnl,
    )

    return RollAwareDailyStepResult(
        gross_pnl=gross_pnl,
        target_position=target_position,
        directional_trade=directional_trade,
        directional_trading_cost=directional_trading_cost,
        roll_executions=roll_result.executions,
        roll_trading_cost=roll_trading_cost,
        total_trading_cost=total_trading_cost,
        new_instrument_position=target_position,
        new_contract_positions=roll_result.new_positions,
        net_pnl=net_pnl,
        closing_account_value=closing_account_value,
    )