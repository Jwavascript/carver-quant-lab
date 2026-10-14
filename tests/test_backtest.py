import pytest

from carver_quant.backtest import (
    BacktestDayInput,
    run_backtest,
)


def test_run_backtest_chains_day_1_and_day_2():
    days = [
        BacktestDayInput(
            previous_adjusted_price=100.0,
            current_adjusted_price=100.0,
            daily_cash_vol_target=600.0,
            price_volatility=3.0,
            multiplier=10.0,
            forecast=10.0,
            execution_bid=99.9,
            execution_ask=100.1,
            tick_size=0.1,
            commission_per_contract=1.0,
        ),
        BacktestDayInput(
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
        ),
    ]

    results = run_backtest(
        initial_account_value=50000.0,
        initial_position=0,
        days=days,
    )

    assert len(results) == 2

    day_1 = results[0]
    day_2 = results[1]

    assert day_1.target_position == 20
    assert day_1.requested_trade == 20
    assert day_1.trading_cost == pytest.approx(40.0)
    assert day_1.closing_account_value == pytest.approx(49960.0)

    assert day_2.gross_pnl == pytest.approx(400.0)
    assert day_2.target_position == 30
    assert day_2.requested_trade == 10
    assert day_2.trading_cost == pytest.approx(20.0)
    assert day_2.closing_account_value == pytest.approx(50340.0)

def test_run_backtest_rejects_disconnected_price_intervals():
    days = [
        BacktestDayInput(
            previous_adjusted_price=98.0,
            current_adjusted_price=100.0,
            daily_cash_vol_target=600.0,
            price_volatility=3.0,
            multiplier=10.0,
            forecast=10.0,
            execution_bid=99.9,
            execution_ask=100.1,
            tick_size=0.1,
            commission_per_contract=1.0,
        ),
        BacktestDayInput(
            previous_adjusted_price=99.0,
            current_adjusted_price=102.0,
            daily_cash_vol_target=600.0,
            price_volatility=2.0,
            multiplier=10.0,
            forecast=10.0,
            execution_bid=101.9,
            execution_ask=102.1,
            tick_size=0.1,
            commission_per_contract=1.0,
        ),
    ]

    with pytest.raises(ValueError):
        run_backtest(
            initial_account_value=50000.0,
            initial_position=0,
            days=days,
        )

def test_run_backtest_reproduces_manual_day_1_to_day_5():
    days = [
        BacktestDayInput(
            previous_adjusted_price=100.0,
            current_adjusted_price=100.0,
            daily_cash_vol_target=600.0,
            price_volatility=3.0,
            multiplier=10.0,
            forecast=10.0,
            execution_bid=99.9,
            execution_ask=100.1,
            tick_size=0.1,
            commission_per_contract=1.0,
        ),
        BacktestDayInput(
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
        ),
        BacktestDayInput(
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
        ),
        BacktestDayInput(
            previous_adjusted_price=101.0,
            current_adjusted_price=99.0,
            daily_cash_vol_target=600.0,
            price_volatility=3.0,
            multiplier=10.0,
            forecast=-15.0,
            execution_bid=98.9,
            execution_ask=99.1,
            tick_size=0.1,
            commission_per_contract=1.0,
        ),
        BacktestDayInput(
            previous_adjusted_price=99.0,
            current_adjusted_price=100.0,
            daily_cash_vol_target=600.0,
            price_volatility=3.0,
            multiplier=10.0,
            forecast=0.0,
            execution_bid=99.9,
            execution_ask=100.1,
            tick_size=0.1,
            commission_per_contract=1.0,
        ),
    ]

    results = run_backtest(
        initial_account_value=50000.0,
        initial_position=0,
        days=days,
    )

    assert len(results) == 5

    assert [r.new_position for r in results] == [
        20,
        30,
        -30,
        -30,
        0,
    ]

    assert [r.requested_trade for r in results] == [
        20,
        10,
        -60,
        0,
        30,
    ]

    assert [r.gross_pnl for r in results] == pytest.approx([
        0.0,
        400.0,
        -300.0,
        600.0,
        -300.0,
    ])

    assert [r.trading_cost for r in results] == pytest.approx([
        40.0,
        20.0,
        120.0,
        0.0,
        60.0,
    ])

    assert [r.net_pnl for r in results] == pytest.approx([
        -40.0,
        380.0,
        -420.0,
        600.0,
        -360.0,
    ])

    assert [r.closing_account_value for r in results] == pytest.approx([
        49960.0,
        50340.0,
        49920.0,
        50520.0,
        50160.0,
    ])