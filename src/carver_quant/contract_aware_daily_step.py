from dataclasses import dataclass

from carver_quant.account_ledger import update_account_value
from carver_quant.pnl import (
    calculate_gross_pnl,
    calculate_net_pnl,
)
from carver_quant.buffering import (
    calculate_buffered_position,
)
from carver_quant.position import (
    calculate_average_position,
    calculate_unrounded_target_position,
    round_half_away_from_zero,
)
from carver_quant.roll import (
    generate_contract_rebalance_trades,
    generate_roll_and_rebalance_trades,
)
from carver_quant.roll_execution import (
    ContractQuote,
    RollExecution,
    execute_contract_trades,
)
from carver_quant.trade import calculate_trade_quantity


@dataclass(frozen=True)
class ContractAwareDailyStepResult:
    gross_pnl: float

    target_position: int
    directional_trade: int

    executions: list[RollExecution]
    total_trading_cost: float

    new_instrument_position: int
    new_contract_positions: dict[str, int]
    active_contract: str

    net_pnl: float
    closing_account_value: float


def run_contract_aware_daily_step(
    previous_account_value: float,
    current_position: int,
    current_contract_positions: dict[str, int],
    active_contract: str,
    roll_to_contract: str | None,
    previous_adjusted_price: float,
    current_adjusted_price: float,
    daily_cash_vol_target: float,
    price_volatility: float,
    multiplier: float,
    forecast: float,
    quotes: dict[str, ContractQuote],
    tick_size: float,
    commission_per_contract: float,
    slippage_ticks: int = 0,
    fx_to_base: float = 1.0,
    position_buffer_fraction: float | None = None,
) -> ContractAwareDailyStepResult:
    contract_position_total = sum(
        current_contract_positions.values()
    )

    if contract_position_total != current_position:
        raise ValueError(
            "Instrument position does not match contract positions."
        )

    if (
        current_position == 0
        and any(
            position != 0
            for position in current_contract_positions.values()
        )
    ):
        raise ValueError(
            "Offsetting contract positions are not supported."
        )
    
    has_long_position = any(
        position > 0
        for position in current_contract_positions.values()
    )

    has_short_position = any(
        position < 0
        for position in current_contract_positions.values()
    )


    if (
        current_position != 0
        and has_long_position
        and has_short_position
    ):
        raise ValueError(
            "Opposing contract positions are not supported."
        )

    if (
        roll_to_contract is not None
        and roll_to_contract == active_contract
    ):
        raise ValueError(
            "roll_to_contract must differ from active_contract."
        )

    if (
        roll_to_contract is not None
        and current_position != 0
        and current_contract_positions
        != {active_contract: current_position}
    ):
        raise ValueError(
            "All current position must be held in active_contract before roll."
        )
    



    gross_pnl = calculate_gross_pnl(
        position_held=current_position,
        previous_price=previous_adjusted_price,
        current_price=current_adjusted_price,
        multiplier=multiplier,
        fx_to_base=fx_to_base,
    )

    average_position = (
        calculate_average_position(
            daily_cash_vol_target=(
                daily_cash_vol_target
            ),
            price_volatility=(
                price_volatility
            ),
            multiplier=multiplier,
            fx_to_base=fx_to_base,
        )
    )

    unrounded_target_position = (
        calculate_unrounded_target_position(
            daily_cash_vol_target=(
                daily_cash_vol_target
            ),
            price_volatility=(
                price_volatility
            ),
            multiplier=multiplier,
            forecast=forecast,
            fx_to_base=fx_to_base,
        )
    )

    if position_buffer_fraction is None:
        # 기존 시스템과 완전히 동일한 동작
        target_position = (
            round_half_away_from_zero(
                unrounded_target_position
            )
        )

    else:
        buffer_decision = (
            calculate_buffered_position(
                current_position=(
                    current_position
                ),
                optimal_unrounded_position=(
                    unrounded_target_position
                ),
                average_position=(
                    average_position
                ),
                buffer_fraction=(
                    position_buffer_fraction
                ),
            )
        )

        target_position = (
            buffer_decision.target_position
        )

    directional_trade = calculate_trade_quantity(
        target_position=target_position,
        current_position=current_position,
    )
    
    if (
        roll_to_contract is None
        and directional_trade != 0
        and current_contract_positions
        and current_contract_positions
        != {active_contract: current_position}
    ):
        raise ValueError(
            "Cannot rebalance unless current position is held in active_contract."
        )

    if (
        current_position != 0
        and current_contract_positions
        != {active_contract: current_position}
    ):
        raise ValueError(
            "All current position must be held in active_contract."
        )
    
    if roll_to_contract is None:
        trades = generate_contract_rebalance_trades(
            contract=active_contract,
            current_position=current_position,
            target_position=target_position,
        )

        new_active_contract = active_contract

    else:
        trades = generate_roll_and_rebalance_trades(
            old_contract=active_contract,
            new_contract=roll_to_contract,
            current_position=current_position,
            target_position=target_position,
        )

        new_active_contract = roll_to_contract

    execution_result = execute_contract_trades(
        current_positions=current_contract_positions,
        trades=trades,
        quotes=quotes,
        tick_size=tick_size,
        multiplier=multiplier,
        commission_per_contract=commission_per_contract,
        slippage_ticks=slippage_ticks,
        fx_to_base=fx_to_base,
    )

    total_trading_cost = (
        execution_result.total_trading_cost
    )

    net_pnl = calculate_net_pnl(
        gross_pnl=gross_pnl,
        total_trading_cost=total_trading_cost,
    )

    closing_account_value = update_account_value(
        previous_account_value=previous_account_value,
        net_pnl=net_pnl,
    )

    return ContractAwareDailyStepResult(
        gross_pnl=gross_pnl,
        target_position=target_position,
        directional_trade=directional_trade,
        executions=execution_result.executions,
        total_trading_cost=total_trading_cost,
        new_instrument_position=target_position,
        new_contract_positions=execution_result.new_positions,
        active_contract=new_active_contract,
        net_pnl=net_pnl,
        closing_account_value=closing_account_value,
    )