import pytest

from carver_quant.roll_execution import ContractQuote
from carver_quant.roll_aware_daily_step import (
    run_roll_aware_daily_step,
)


def test_day_8_roll_aware_daily_step():
    result = run_roll_aware_daily_step(
        previous_account_value=51160.0,
        current_position=20,
        current_contract_positions={
            "SEP": 20,
        },
        previous_adjusted_price=106.0,
        current_adjusted_price=105.0,
        daily_cash_vol_target=600.0,
        price_volatility=3.0,
        multiplier=10.0,
        forecast=10.0,
        roll_from_contract="SEP",
        roll_to_contract="DEC",
        roll_quotes={
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
    assert result.directional_trading_cost == pytest.approx(0.0)

    assert len(result.roll_executions) == 2
    assert result.roll_trading_cost == pytest.approx(80.0)
    assert result.total_trading_cost == pytest.approx(80.0)

    assert result.new_instrument_position == 20
    assert result.new_contract_positions == {
        "DEC": 20,
    }

    assert result.net_pnl == pytest.approx(-280.0)
    assert result.closing_account_value == pytest.approx(50880.0)

def test_roll_aware_daily_step_rejects_inconsistent_position_state():
    with pytest.raises(
        ValueError,
        match="Instrument position does not match contract positions.",
    ):
        run_roll_aware_daily_step(
            previous_account_value=51160.0,
            current_position=20,
            current_contract_positions={
                "SEP": 15,
            },
            previous_adjusted_price=106.0,
            current_adjusted_price=105.0,
            daily_cash_vol_target=600.0,
            price_volatility=3.0,
            multiplier=10.0,
            forecast=10.0,
            roll_from_contract="SEP",
            roll_to_contract="DEC",
            roll_quotes={
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

def test_roll_aware_daily_step_keeps_output_positions_consistent():
    result = run_roll_aware_daily_step(
        previous_account_value=51160.0,
        current_position=20,
        current_contract_positions={
            "SEP": 20,
        },
        previous_adjusted_price=106.0,
        current_adjusted_price=105.0,
        daily_cash_vol_target=600.0,
        price_volatility=3.0,
        multiplier=10.0,
        forecast=10.0,
        roll_from_contract="SEP",
        roll_to_contract="DEC",
        roll_quotes={
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

    contract_position_total = sum(
        result.new_contract_positions.values()
    )

    assert result.new_instrument_position == 20
    assert contract_position_total == 20

    assert (
        result.new_instrument_position
        == contract_position_total
    )

def test_roll_aware_daily_step_rejects_missing_roll_from_contract():
    with pytest.raises(
        ValueError,
        match="No open position in roll_from_contract: JUN",
    ):
        run_roll_aware_daily_step(
            previous_account_value=51160.0,
            current_position=20,
            current_contract_positions={
                "SEP": 20,
            },
            previous_adjusted_price=106.0,
            current_adjusted_price=105.0,
            daily_cash_vol_target=600.0,
            price_volatility=3.0,
            multiplier=10.0,
            forecast=10.0,
            roll_from_contract="JUN",
            roll_to_contract="DEC",
            roll_quotes={
                "JUN": ContractQuote(
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

def test_roll_aware_daily_step_is_no_op_when_flat():
    result = run_roll_aware_daily_step(
        previous_account_value=50000.0,
        current_position=0,
        current_contract_positions={},
        previous_adjusted_price=100.0,
        current_adjusted_price=102.0,
        daily_cash_vol_target=600.0,
        price_volatility=3.0,
        multiplier=10.0,
        forecast=0.0,
        roll_from_contract="SEP",
        roll_to_contract="DEC",
        roll_quotes={},
        tick_size=0.1,
        commission_per_contract=1.0,
    )

    assert result.gross_pnl == pytest.approx(0.0)

    assert result.target_position == 0
    assert result.directional_trade == 0
    assert result.directional_trading_cost == pytest.approx(0.0)

    assert result.roll_executions == []
    assert result.roll_trading_cost == pytest.approx(0.0)
    assert result.total_trading_cost == pytest.approx(0.0)

    assert result.new_instrument_position == 0
    assert result.new_contract_positions == {}

    assert result.net_pnl == pytest.approx(0.0)
    assert result.closing_account_value == pytest.approx(50000.0)

def test_roll_aware_daily_step_allows_directional_rebalance_on_roll_day():
    result = run_roll_aware_daily_step(
        previous_account_value=51160.0,
        current_position=20,
        current_contract_positions={
            "SEP": 20,
        },
        previous_adjusted_price=106.0,
        current_adjusted_price=105.0,
        daily_cash_vol_target=600.0,
        price_volatility=2.0,
        multiplier=10.0,
        forecast=10.0,
        roll_from_contract="SEP",
        roll_to_contract="DEC",
        roll_quotes={
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

    assert result.target_position == 30
    assert result.directional_trade == 10

    assert len(result.roll_executions) == 2

    assert result.roll_executions[0].contract == "SEP"
    assert result.roll_executions[0].quantity == -20

    assert result.roll_executions[1].contract == "DEC"
    assert result.roll_executions[1].quantity == 30

    assert result.total_trading_cost == pytest.approx(100.0)

    assert result.new_instrument_position == 30
    assert result.new_contract_positions == {
        "DEC": 30,
    }

    assert result.net_pnl == pytest.approx(-300.0)
    assert result.closing_account_value == pytest.approx(50860.0)
    
def test_day_6_roll_and_rebalance_from_flat():
    result = run_roll_aware_daily_step(
        previous_account_value=50160.0,
        current_position=0,
        current_contract_positions={},
        previous_adjusted_price=100.0,
        current_adjusted_price=104.0,
        daily_cash_vol_target=600.0,
        price_volatility=1.0,
        multiplier=10.0,
        forecast=10.0,
        roll_from_contract="JUN",
        roll_to_contract="SEP",
        roll_quotes={
            "SEP": ContractQuote(
                bid=103.9,
                ask=104.1,
            ),
        },
        tick_size=0.1,
        commission_per_contract=1.0,
    )

    assert result.gross_pnl == pytest.approx(0.0)

    assert result.target_position == 60
    assert result.directional_trade == 60

    assert len(result.roll_executions) == 1
    assert result.roll_executions[0].contract == "SEP"
    assert result.roll_executions[0].quantity == 60

    assert result.total_trading_cost == pytest.approx(120.0)

    assert result.new_instrument_position == 60
    assert result.new_contract_positions == {
        "SEP": 60,
    }

    assert result.net_pnl == pytest.approx(-120.0)
    assert result.closing_account_value == pytest.approx(50040.0)