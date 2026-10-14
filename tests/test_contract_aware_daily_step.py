import pytest

from carver_quant.roll_execution import ContractQuote
from carver_quant.contract_aware_daily_step import (
    run_contract_aware_daily_step,
)


def test_day_7_contract_aware_daily_step_without_roll():
    result = run_contract_aware_daily_step(
        previous_account_value=50040.0,
        current_position=60,
        current_contract_positions={
            "SEP": 60,
        },
        active_contract="SEP",
        roll_to_contract=None,
        previous_adjusted_price=104.0,
        current_adjusted_price=106.0,
        daily_cash_vol_target=600.0,
        price_volatility=3.0,
        multiplier=10.0,
        forecast=10.0,
        quotes={
            "SEP": ContractQuote(
                bid=105.9,
                ask=106.1,
            ),
        },
        tick_size=0.1,
        commission_per_contract=1.0,
    )

    assert result.gross_pnl == pytest.approx(1200.0)

    assert result.target_position == 20
    assert result.directional_trade == -40

    assert result.new_instrument_position == 20
    assert result.new_contract_positions == {
        "SEP": 20,
    }
    assert result.active_contract == "SEP"

    assert result.total_trading_cost == pytest.approx(80.0)
    assert result.net_pnl == pytest.approx(1120.0)
    assert result.closing_account_value == pytest.approx(51160.0)

def test_day_8_contract_aware_daily_step_with_roll():
    result = run_contract_aware_daily_step(
        previous_account_value=51160.0,
        current_position=20,
        current_contract_positions={
            "SEP": 20,
        },
        active_contract="SEP",
        roll_to_contract="DEC",
        previous_adjusted_price=106.0,
        current_adjusted_price=105.0,
        daily_cash_vol_target=600.0,
        price_volatility=3.0,
        multiplier=10.0,
        forecast=10.0,
        quotes={
            "SEP": ContractQuote(
                bid=104.9,
                ask=105.1,
            ),
            "DEC": ContractQuote(
                bid=106.9,
                ask=107.1,
            ),
        },
        tick_size=0.1,
        commission_per_contract=1.0,
    )

    assert result.gross_pnl == pytest.approx(-200.0)

    assert result.target_position == 20
    assert result.directional_trade == 0

    assert len(result.executions) == 2

    assert result.executions[0].contract == "SEP"
    assert result.executions[0].quantity == -20

    assert result.executions[1].contract == "DEC"
    assert result.executions[1].quantity == 20

    assert result.total_trading_cost == pytest.approx(80.0)

    assert result.new_instrument_position == 20
    assert result.new_contract_positions == {
        "DEC": 20,
    }
    assert result.active_contract == "DEC"

    assert result.net_pnl == pytest.approx(-280.0)
    assert result.closing_account_value == pytest.approx(50880.0)

def test_day_9_contract_aware_daily_step_reverses_position():
    result = run_contract_aware_daily_step(
        previous_account_value=50880.0,
        current_position=20,
        current_contract_positions={
            "DEC": 20,
        },
        active_contract="DEC",
        roll_to_contract=None,
        previous_adjusted_price=105.0,
        current_adjusted_price=101.0,
        daily_cash_vol_target=600.0,
        price_volatility=4.0,
        multiplier=10.0,
        forecast=-20.0,
        quotes={
            "DEC": ContractQuote(
                bid=100.9,
                ask=101.1,
            ),
        },
        tick_size=0.1,
        commission_per_contract=1.0,
    )

    assert result.gross_pnl == pytest.approx(-800.0)

    assert result.target_position == -30
    assert result.directional_trade == -50

    assert len(result.executions) == 1
    assert result.executions[0].contract == "DEC"
    assert result.executions[0].quantity == -50
    assert result.executions[0].fill_price == pytest.approx(100.9)

    assert result.total_trading_cost == pytest.approx(100.0)

    assert result.new_instrument_position == -30
    assert result.new_contract_positions == {
        "DEC": -30,
    }
    assert result.active_contract == "DEC"

    assert result.net_pnl == pytest.approx(-900.0)
    assert result.closing_account_value == pytest.approx(49980.0)

def test_day_10_contract_aware_daily_step_reduces_short_position():
    result = run_contract_aware_daily_step(
        previous_account_value=49980.0,
        current_position=-30,
        current_contract_positions={
            "DEC": -30,
        },
        active_contract="DEC",
        roll_to_contract=None,
        previous_adjusted_price=101.0,
        current_adjusted_price=103.0,
        daily_cash_vol_target=600.0,
        price_volatility=5.0,
        multiplier=10.0,
        forecast=-10.0,
        quotes={
            "DEC": ContractQuote(
                bid=102.9,
                ask=103.1,
            ),
        },
        tick_size=0.1,
        commission_per_contract=1.0,
    )

    assert result.gross_pnl == pytest.approx(-600.0)

    assert result.target_position == -12
    assert result.directional_trade == 18

    assert len(result.executions) == 1
    assert result.executions[0].contract == "DEC"
    assert result.executions[0].quantity == 18
    assert result.executions[0].fill_price == pytest.approx(103.1)

    assert result.total_trading_cost == pytest.approx(36.0)

    assert result.new_instrument_position == -12
    assert result.new_contract_positions == {
        "DEC": -12,
    }
    assert result.active_contract == "DEC"

    assert result.net_pnl == pytest.approx(-636.0)
    assert result.closing_account_value == pytest.approx(49344.0)

def test_day_6_to_day_10_state_chaining():
    # -------------------------
    # Day 6
    # -------------------------
    day_6 = run_contract_aware_daily_step(
        previous_account_value=50160.0,
        current_position=0,
        current_contract_positions={},
        active_contract="JUN",
        roll_to_contract="SEP",
        previous_adjusted_price=100.0,
        current_adjusted_price=104.0,
        daily_cash_vol_target=600.0,
        price_volatility=1.0,
        multiplier=10.0,
        forecast=10.0,
        quotes={
            "SEP": ContractQuote(
                bid=103.9,
                ask=104.1,
            ),
        },
        tick_size=0.1,
        commission_per_contract=1.0,
    )

    # -------------------------
    # Day 7
    # -------------------------
    day_7 = run_contract_aware_daily_step(
        previous_account_value=day_6.closing_account_value,
        current_position=day_6.new_instrument_position,
        current_contract_positions=day_6.new_contract_positions,
        active_contract=day_6.active_contract,
        roll_to_contract=None,
        previous_adjusted_price=104.0,
        current_adjusted_price=106.0,
        daily_cash_vol_target=600.0,
        price_volatility=3.0,
        multiplier=10.0,
        forecast=10.0,
        quotes={
            "SEP": ContractQuote(
                bid=105.9,
                ask=106.1,
            ),
        },
        tick_size=0.1,
        commission_per_contract=1.0,
    )

    # -------------------------
    # Day 8
    # -------------------------
    day_8 = run_contract_aware_daily_step(
        previous_account_value=day_7.closing_account_value,
        current_position=day_7.new_instrument_position,
        current_contract_positions=day_7.new_contract_positions,
        active_contract=day_7.active_contract,
        roll_to_contract="DEC",
        previous_adjusted_price=106.0,
        current_adjusted_price=105.0,
        daily_cash_vol_target=600.0,
        price_volatility=3.0,
        multiplier=10.0,
        forecast=10.0,
        quotes={
            "SEP": ContractQuote(
                bid=104.9,
                ask=105.1,
            ),
            "DEC": ContractQuote(
                bid=106.9,
                ask=107.1,
            ),
        },
        tick_size=0.1,
        commission_per_contract=1.0,
    )

    # -------------------------
    # Day 9
    # -------------------------
    day_9 = run_contract_aware_daily_step(
        previous_account_value=day_8.closing_account_value,
        current_position=day_8.new_instrument_position,
        current_contract_positions=day_8.new_contract_positions,
        active_contract=day_8.active_contract,
        roll_to_contract=None,
        previous_adjusted_price=105.0,
        current_adjusted_price=101.0,
        daily_cash_vol_target=600.0,
        price_volatility=4.0,
        multiplier=10.0,
        forecast=-20.0,
        quotes={
            "DEC": ContractQuote(
                bid=100.9,
                ask=101.1,
            ),
        },
        tick_size=0.1,
        commission_per_contract=1.0,
    )

    # -------------------------
    # Day 10
    # -------------------------
    day_10 = run_contract_aware_daily_step(
        previous_account_value=day_9.closing_account_value,
        current_position=day_9.new_instrument_position,
        current_contract_positions=day_9.new_contract_positions,
        active_contract=day_9.active_contract,
        roll_to_contract=None,
        previous_adjusted_price=101.0,
        current_adjusted_price=103.0,
        daily_cash_vol_target=600.0,
        price_volatility=5.0,
        multiplier=10.0,
        forecast=-10.0,
        quotes={
            "DEC": ContractQuote(
                bid=102.9,
                ask=103.1,
            ),
        },
        tick_size=0.1,
        commission_per_contract=1.0,
    )

    assert [
        day_6.closing_account_value,
        day_7.closing_account_value,
        day_8.closing_account_value,
        day_9.closing_account_value,
        day_10.closing_account_value,
    ] == pytest.approx([
        50040.0,
        51160.0,
        50880.0,
        49980.0,
        49344.0,
    ])

    assert [
        day_6.new_instrument_position,
        day_7.new_instrument_position,
        day_8.new_instrument_position,
        day_9.new_instrument_position,
        day_10.new_instrument_position,
    ] == [
        60,
        20,
        20,
        -30,
        -12,
    ]

    assert day_6.new_contract_positions == {
        "SEP": 60,
    }

    assert day_7.new_contract_positions == {
        "SEP": 20,
    }

    assert day_8.new_contract_positions == {
        "DEC": 20,
    }

    assert day_9.new_contract_positions == {
        "DEC": -30,
    }

    assert day_10.new_contract_positions == {
        "DEC": -12,
    }

    assert [
        day_6.active_contract,
        day_7.active_contract,
        day_8.active_contract,
        day_9.active_contract,
        day_10.active_contract,
    ] == [
        "SEP",
        "SEP",
        "DEC",
        "DEC",
        "DEC",
    ]

def test_contract_aware_daily_step_rejects_roll_to_same_contract():
    with pytest.raises(
        ValueError,
        match="roll_to_contract must differ from active_contract.",
    ):
        run_contract_aware_daily_step(
            previous_account_value=50000.0,
            current_position=20,
            current_contract_positions={
                "SEP": 20,
            },
            active_contract="SEP",
            roll_to_contract="SEP",
            previous_adjusted_price=100.0,
            current_adjusted_price=100.0,
            daily_cash_vol_target=600.0,
            price_volatility=3.0,
            multiplier=10.0,
            forecast=10.0,
            quotes={
                "SEP": ContractQuote(
                    bid=99.9,
                    ask=100.1,
                ),
            },
            tick_size=0.1,
            commission_per_contract=1.0,
        )

def test_contract_aware_daily_step_rejects_split_positions_on_roll_day():
    with pytest.raises(
        ValueError,
        match="All current position must be held in active_contract before roll.",
    ):
        run_contract_aware_daily_step(
            previous_account_value=50000.0,
            current_position=20,
            current_contract_positions={
                "SEP": 10,
                "JUN": 10,
            },
            active_contract="SEP",
            roll_to_contract="DEC",
            previous_adjusted_price=100.0,
            current_adjusted_price=100.0,
            daily_cash_vol_target=600.0,
            price_volatility=3.0,
            multiplier=10.0,
            forecast=10.0,
            quotes={
                "SEP": ContractQuote(
                    bid=99.9,
                    ask=100.1,
                ),
                "DEC": ContractQuote(
                    bid=102.9,
                    ask=103.1,
                ),
            },
            tick_size=0.1,
            commission_per_contract=1.0,
        )

def test_contract_aware_daily_step_rejects_split_positions_on_non_roll_day():
    with pytest.raises(
        ValueError,
        match="All current position must be held in active_contract.",
    ):
        run_contract_aware_daily_step(
            previous_account_value=50000.0,
            current_position=20,
            current_contract_positions={
                "SEP": 10,
                "JUN": 10,
            },
            active_contract="SEP",
            roll_to_contract=None,
            previous_adjusted_price=100.0,
            current_adjusted_price=100.0,
            daily_cash_vol_target=600.0,
            price_volatility=3.0,
            multiplier=10.0,
            forecast=10.0,
            quotes={},
            tick_size=0.1,
            commission_per_contract=1.0,
        )

def test_contract_aware_daily_step_rejects_rebalance_when_position_not_in_active_contract():
    with pytest.raises(
        ValueError,
        match="Cannot rebalance unless current position is held in active_contract.",
    ):
        run_contract_aware_daily_step(
            previous_account_value=50000.0,
            current_position=20,
            current_contract_positions={
                "JUN": 20,
            },
            active_contract="SEP",
            roll_to_contract=None,
            previous_adjusted_price=100.0,
            current_adjusted_price=100.0,
            daily_cash_vol_target=600.0,
            price_volatility=6.0,
            multiplier=10.0,
            forecast=10.0,
            quotes={
                "SEP": ContractQuote(
                    bid=99.9,
                    ask=100.1,
                ),
            },
            tick_size=0.1,
            commission_per_contract=1.0,
        )

def test_contract_aware_daily_step_rejects_offsetting_contract_positions():
    with pytest.raises(
        ValueError,
        match="Offsetting contract positions are not supported.",
    ):
        run_contract_aware_daily_step(
            previous_account_value=50000.0,
            current_position=0,
            current_contract_positions={
                "SEP": 10,
                "DEC": -10,
            },
            active_contract="SEP",
            roll_to_contract=None,
            previous_adjusted_price=100.0,
            current_adjusted_price=101.0,
            daily_cash_vol_target=600.0,
            price_volatility=3.0,
            multiplier=10.0,
            forecast=0.0,
            quotes={},
            tick_size=0.1,
            commission_per_contract=1.0,
        )

def test_contract_aware_daily_step_rejects_opposing_contract_positions():
    with pytest.raises(
        ValueError,
        match="Opposing contract positions are not supported.",
    ):
        run_contract_aware_daily_step(
            previous_account_value=50000.0,
            current_position=10,
            current_contract_positions={
                "SEP": 20,
                "DEC": -10,
            },
            active_contract="SEP",
            roll_to_contract=None,
            previous_adjusted_price=100.0,
            current_adjusted_price=101.0,
            daily_cash_vol_target=600.0,
            price_volatility=6.0,
            multiplier=10.0,
            forecast=10.0,
            quotes={},
            tick_size=0.1,
            commission_per_contract=1.0,
        )

def test_contract_aware_daily_step_applies_slippage():
    result = run_contract_aware_daily_step(
        previous_account_value=50000.0,
        current_position=0,
        current_contract_positions={},
        active_contract="SEP",
        roll_to_contract=None,
        previous_adjusted_price=100.0,
        current_adjusted_price=100.0,
        daily_cash_vol_target=600.0,
        price_volatility=6.0,
        multiplier=10.0,
        forecast=10.0,
        quotes={
            "SEP": ContractQuote(
                bid=99.9,
                ask=100.1,
            ),
        },
        tick_size=0.1,
        commission_per_contract=1.0,
        slippage_ticks=1,
    )

    assert result.target_position == 10
    assert result.directional_trade == 10

    assert len(result.executions) == 1
    assert result.executions[0].quantity == 10
    assert result.executions[0].fill_price == pytest.approx(100.2)

    assert result.total_trading_cost == pytest.approx(30.0)

    assert result.new_instrument_position == 10
    assert result.new_contract_positions == {
        "SEP": 10,
    }

    assert result.gross_pnl == pytest.approx(0.0)
    assert result.net_pnl == pytest.approx(-30.0)
    assert result.closing_account_value == pytest.approx(49970.0)

def test_day_8_roll_applies_slippage_to_both_contract_legs():
    result = run_contract_aware_daily_step(
        previous_account_value=51160.0,
        current_position=20,
        current_contract_positions={
            "SEP": 20,
        },
        active_contract="SEP",
        roll_to_contract="DEC",
        previous_adjusted_price=106.0,
        current_adjusted_price=105.0,
        daily_cash_vol_target=600.0,
        price_volatility=3.0,
        multiplier=10.0,
        forecast=10.0,
        quotes={
            "SEP": ContractQuote(
                bid=104.9,
                ask=105.1,
            ),
            "DEC": ContractQuote(
                bid=106.9,
                ask=107.1,
            ),
        },
        tick_size=0.1,
        commission_per_contract=1.0,
        slippage_ticks=1,
    )

    assert result.directional_trade == 0
    assert len(result.executions) == 2

    assert result.executions[0].contract == "SEP"
    assert result.executions[0].quantity == -20
    assert result.executions[0].fill_price == pytest.approx(104.8)
    assert result.executions[0].trading_cost == pytest.approx(60.0)

    assert result.executions[1].contract == "DEC"
    assert result.executions[1].quantity == 20
    assert result.executions[1].fill_price == pytest.approx(107.2)
    assert result.executions[1].trading_cost == pytest.approx(60.0)

    assert result.total_trading_cost == pytest.approx(120.0)

    assert result.new_contract_positions == {
        "DEC": 20,
    }

    assert result.gross_pnl == pytest.approx(-200.0)
    assert result.net_pnl == pytest.approx(-320.0)
    assert result.closing_account_value == pytest.approx(50840.0)

def test_contract_aware_daily_step_uses_krw_base_currency():
    result = run_contract_aware_daily_step(
        previous_account_value=10_000_000.0,
        current_position=1,
        current_contract_positions={
            "SEP": 1,
        },
        active_contract="SEP",
        roll_to_contract=None,
        previous_adjusted_price=100.0,
        current_adjusted_price=101.0,
        daily_cash_vol_target=27_000.0,
        price_volatility=1.0,
        multiplier=10.0,
        forecast=10.0,
        quotes={
            "SEP": ContractQuote(
                bid=100.9,
                ask=101.1,
            ),
        },
        tick_size=0.1,
        commission_per_contract=1.0,
        slippage_ticks=0,
        fx_to_base=1350.0,
    )

    assert result.gross_pnl == pytest.approx(13_500.0)

    assert result.target_position == 2
    assert result.directional_trade == 1

    assert len(result.executions) == 1
    assert result.executions[0].quantity == 1
    assert result.executions[0].fill_price == pytest.approx(101.1)

    assert result.total_trading_cost == pytest.approx(2_700.0)

    assert result.new_instrument_position == 2
    assert result.new_contract_positions == {
        "SEP": 2,
    }

    assert result.net_pnl == pytest.approx(10_800.0)
    assert result.closing_account_value == pytest.approx(
        10_010_800.0
    )