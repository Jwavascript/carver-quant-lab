import pytest

from carver_quant.daily_step import run_daily_step


def test_day_2_vertical_slice():
    result = run_daily_step(
        previous_account_value=49960.0,
        current_position=20,
        previous_adjusted_price=100.0,
        current_adjusted_price=102.0,
        daily_cash_vol_target=600.0,
        price_volatility=2.0,
        multiplier=10.0,
        forecast=10.0,
        execution_bid=101.9,
        execution_ask=102.1,
        tick_size=0.1,
        commission_per_contract=1.0,
    )

    assert result.gross_pnl == pytest.approx(400.0)
    assert result.target_position == 30
    assert result.requested_trade == 10

    assert result.filled_quantity == 10
    assert result.fill_price == pytest.approx(102.1)
    assert result.new_position == 30

    assert result.trading_cost == pytest.approx(20.0)
    assert result.net_pnl == pytest.approx(380.0)
    assert result.closing_account_value == pytest.approx(50340.0)


def test_no_trade_day_skips_execution_and_has_zero_cost():
    result = run_daily_step(
        previous_account_value=49960.0,
        current_position=20,
        previous_adjusted_price=100.0,
        current_adjusted_price=102.0,
        daily_cash_vol_target=600.0,
        price_volatility=3.0,
        multiplier=10.0,
        forecast=10.0,
        execution_bid=101.9,
        execution_ask=102.1,
        tick_size=0.1,
        commission_per_contract=1.0,
    )

    assert result.gross_pnl == pytest.approx(400.0)

    assert result.target_position == 20
    assert result.requested_trade == 0

    assert result.filled_quantity == 0
    assert result.fill_price is None
    assert result.new_position == 20

    assert result.trading_cost == pytest.approx(0.0)
    assert result.net_pnl == pytest.approx(400.0)
    assert result.closing_account_value == pytest.approx(50360.0)

def test_day_3_position_reversal():
    result = run_daily_step(
        previous_account_value=50340.0,
        current_position=30,
        previous_adjusted_price=102.0,
        current_adjusted_price=101.0,
        daily_cash_vol_target=600.0,
        price_volatility=2.0,
        multiplier=10.0,
        forecast=-10.0,
        execution_bid=100.9,
        execution_ask=101.1,
        tick_size=0.1,
        commission_per_contract=1.0,
    )

    assert result.gross_pnl == pytest.approx(-300.0)

    assert result.target_position == -30
    assert result.requested_trade == -60

    assert result.filled_quantity == -60
    assert result.fill_price == pytest.approx(100.9)
    assert result.new_position == -30

    assert result.trading_cost == pytest.approx(120.0)
    assert result.net_pnl == pytest.approx(-420.0)
    assert result.closing_account_value == pytest.approx(49920.0)

def test_day_2_and_day_3_are_chained_by_state():
    day_2 = run_daily_step(
        previous_account_value=49960.0,
        current_position=20,
        previous_adjusted_price=100.0,
        current_adjusted_price=102.0,
        daily_cash_vol_target=600.0,
        price_volatility=2.0,
        multiplier=10.0,
        forecast=10.0,
        execution_bid=101.9,
        execution_ask=102.1,
        tick_size=0.1,
        commission_per_contract=1.0,
    )

    day_3 = run_daily_step(
        previous_account_value=day_2.closing_account_value,
        current_position=day_2.new_position,
        previous_adjusted_price=102.0,
        current_adjusted_price=101.0,
        daily_cash_vol_target=600.0,
        price_volatility=2.0,
        multiplier=10.0,
        forecast=-10.0,
        execution_bid=100.9,
        execution_ask=101.1,
        tick_size=0.1,
        commission_per_contract=1.0,
    )

    assert day_2.new_position == 30
    assert day_2.closing_account_value == pytest.approx(50340.0)

    assert day_3.gross_pnl == pytest.approx(-300.0)
    assert day_3.target_position == -30
    assert day_3.requested_trade == -60
    assert day_3.new_position == -30
    assert day_3.net_pnl == pytest.approx(-420.0)
    assert day_3.closing_account_value == pytest.approx(49920.0)