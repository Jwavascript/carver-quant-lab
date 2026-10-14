import pytest

from carver_quant.contract_aware_daily_step import (
    run_contract_aware_daily_step,
)
from carver_quant.roll_execution import (
    ContractQuote,
)

def run_buffer_example(
    current_position: int,
    position_buffer_fraction,
):
    return run_contract_aware_daily_step(
        previous_account_value=100_000.0,

        current_position=current_position,

        current_contract_positions={
            "TEST": current_position,
        },

        active_contract="TEST",

        roll_to_contract=None,

        previous_adjusted_price=100.0,
        current_adjusted_price=100.0,

        # average position
        # = 88 / (1 × 10)
        # = 8.8
        daily_cash_vol_target=88.0,

        price_volatility=1.0,

        multiplier=10.0,

        # unrounded target
        # = 8.8 × 15 / 10
        # = 13.2
        forecast=15.0,

        quotes={
            "TEST": ContractQuote(
                bid=100.0,
                ask=100.0,
            )
        },

        tick_size=0.01,

        commission_per_contract=0.0,

        slippage_ticks=0,

        fx_to_base=1.0,

        position_buffer_fraction=(
            position_buffer_fraction
        ),
    )

def test_without_buffer_trades_to_rounded_optimal_position():
    result = run_buffer_example(
        current_position=12,
        position_buffer_fraction=None,
    )

    assert result.target_position == 13
    assert result.directional_trade == 1

    assert (
        result.new_instrument_position
        == 13
    )

def test_buffer_prevents_small_trade():
    result = run_buffer_example(
        current_position=12,
        position_buffer_fraction=0.10,
    )

    assert result.target_position == 12
    assert result.directional_trade == 0

    assert (
        result.new_instrument_position
        == 12
    )

    assert result.total_trading_cost == pytest.approx(
        0.0
    )

def test_buffer_trades_only_to_nearest_edge():
    result = run_buffer_example(
        current_position=10,
        position_buffer_fraction=0.10,
    )

    # optimal = 13.2
    # buffer = [12, 14]
    #
    # current = 10
    # 따라서 13까지 가지 않고 12까지만 거래.
    assert result.target_position == 12

    assert result.directional_trade == 2

    assert (
        result.new_instrument_position
        == 12
    )

