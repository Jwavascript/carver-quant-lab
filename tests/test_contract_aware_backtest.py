import pytest

from carver_quant.roll_execution import ContractQuote
from carver_quant.instrument import InstrumentSpec
from carver_quant.contract_aware_backtest import (
    ContractAwareBacktestDayInput,
    run_contract_aware_backtest,
)

instrument_spec = InstrumentSpec(
    symbol="TEST",
    currency="USD",
    multiplier=10.0,
    tick_size=0.1,
    
)


def test_contract_aware_backtest_chains_day_6_to_day_7():
    days = [
        ContractAwareBacktestDayInput(
            previous_adjusted_price=100.0,
            current_adjusted_price=104.0,
            daily_cash_vol_target=600.0,
            price_volatility=1.0,
            forecast=10.0,
            quotes={
                "SEP": ContractQuote(
                    bid=103.9,
                    ask=104.1,
                ),
            },
            commission_per_contract=1.0,
            roll_to_contract="SEP",
        ),
        ContractAwareBacktestDayInput(
            previous_adjusted_price=104.0,
            current_adjusted_price=106.0,
            daily_cash_vol_target=600.0,
            price_volatility=3.0,
            forecast=10.0,
            quotes={
                "SEP": ContractQuote(
                    bid=105.9,
                    ask=106.1,
                ),
            },
            commission_per_contract=1.0,
            roll_to_contract=None,
        ),
    ]

    results = run_contract_aware_backtest(
        initial_account_value=50160.0,
        initial_position=0,
        initial_contract_positions={},
        initial_active_contract="JUN",
        days=days,
        instrument_spec=instrument_spec,
    )

    assert len(results) == 2

    day_6 = results[0]
    day_7 = results[1]

    assert day_6.closing_account_value == pytest.approx(50040.0)
    assert day_6.new_instrument_position == 60
    assert day_6.new_contract_positions == {
        "SEP": 60,
    }
    assert day_6.active_contract == "SEP"

    assert day_7.gross_pnl == pytest.approx(1200.0)
    assert day_7.closing_account_value == pytest.approx(51160.0)
    assert day_7.new_instrument_position == 20
    assert day_7.new_contract_positions == {
        "SEP": 20,
    }
    assert day_7.active_contract == "SEP"

def test_contract_aware_backtest_rejects_disconnected_price_intervals():
    days = [
        ContractAwareBacktestDayInput(
            previous_adjusted_price=100.0,
            current_adjusted_price=101.0,
            daily_cash_vol_target=600.0,
            price_volatility=1.0,
            forecast=0.0,
            quotes={},
            commission_per_contract=1.0,
            roll_to_contract=None,
        ),
        ContractAwareBacktestDayInput(
            previous_adjusted_price=999.0,
            current_adjusted_price=102.0,
            daily_cash_vol_target=600.0,
            price_volatility=1.0,
            forecast=0.0,
            quotes={},
            commission_per_contract=1.0,
            roll_to_contract=None,
        ),
    ]

    with pytest.raises(
        ValueError,
        match="Adjusted price interval is not continuous.",
    ):
        run_contract_aware_backtest(
            initial_account_value=50000.0,
            initial_position=0,
            initial_contract_positions={},
            initial_active_contract="SEP",
            days=days,
            instrument_spec=instrument_spec,
        )

def test_contract_aware_backtest_runs_day_6_to_day_10():
    days = [
        # Day 6
        ContractAwareBacktestDayInput(
            previous_adjusted_price=100.0,
            current_adjusted_price=104.0,
            daily_cash_vol_target=600.0,
            price_volatility=1.0,
            forecast=10.0,
            quotes={
                "SEP": ContractQuote(
                    bid=103.9,
                    ask=104.1,
                ),
            },
            commission_per_contract=1.0,
            roll_to_contract="SEP",
        ),

        # Day 7
        ContractAwareBacktestDayInput(
            previous_adjusted_price=104.0,
            current_adjusted_price=106.0,
            daily_cash_vol_target=600.0,
            price_volatility=3.0,
            forecast=10.0,
            quotes={
                "SEP": ContractQuote(
                    bid=105.9,
                    ask=106.1,
                ),
            },
            commission_per_contract=1.0,
            roll_to_contract=None,
        ),

        # Day 8
        ContractAwareBacktestDayInput(
            previous_adjusted_price=106.0,
            current_adjusted_price=105.0,
            daily_cash_vol_target=600.0,
            price_volatility=3.0,
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
            commission_per_contract=1.0,
            roll_to_contract="DEC",
        ),

        # Day 9
        ContractAwareBacktestDayInput(
            previous_adjusted_price=105.0,
            current_adjusted_price=101.0,
            daily_cash_vol_target=600.0,
            price_volatility=4.0,
            forecast=-20.0,
            quotes={
                "DEC": ContractQuote(
                    bid=100.9,
                    ask=101.1,
                ),
            },
            commission_per_contract=1.0,
            roll_to_contract=None,
        ),

        # Day 10
        ContractAwareBacktestDayInput(
            previous_adjusted_price=101.0,
            current_adjusted_price=103.0,
            daily_cash_vol_target=600.0,
            price_volatility=5.0,
            forecast=-10.0,
            quotes={
                "DEC": ContractQuote(
                    bid=102.9,
                    ask=103.1,
                ),
            },
            commission_per_contract=1.0,
            roll_to_contract=None,
        ),
    ]

    results = run_contract_aware_backtest(
        initial_account_value=50160.0,
        initial_position=0,
        initial_contract_positions={},
        initial_active_contract="JUN",
        days=days,
        instrument_spec=instrument_spec,
    )

    assert len(results) == 5

    assert [
        result.closing_account_value
        for result in results
    ] == pytest.approx([
        50040.0,
        51160.0,
        50880.0,
        49980.0,
        49344.0,
    ])

    assert [
        result.new_instrument_position
        for result in results
    ] == [
        60,
        20,
        20,
        -30,
        -12,
    ]

    assert [
        result.total_trading_cost
        for result in results
    ] == pytest.approx([
        120.0,
        80.0,
        80.0,
        100.0,
        36.0,
    ])

    assert results[0].new_contract_positions == {
        "SEP": 60,
    }
    assert results[1].new_contract_positions == {
        "SEP": 20,
    }
    assert results[2].new_contract_positions == {
        "DEC": 20,
    }
    assert results[3].new_contract_positions == {
        "DEC": -30,
    }
    assert results[4].new_contract_positions == {
        "DEC": -12,
    }

    assert [
        result.active_contract
        for result in results
    ] == [
        "SEP",
        "SEP",
        "DEC",
        "DEC",
        "DEC",
    ]

def test_contract_aware_backtest_runs_day_1_to_day_5():
    days = [
        # Day 1
        ContractAwareBacktestDayInput(
            previous_adjusted_price=100.0,
            current_adjusted_price=100.0,
            daily_cash_vol_target=600.0,
            price_volatility=3.0,
            forecast=10.0,
            quotes={
                "JUN": ContractQuote(
                    bid=99.9,
                    ask=100.1,
                ),
            },
            commission_per_contract=1.0,
            roll_to_contract=None,
        ),

        # Day 2
        ContractAwareBacktestDayInput(
            previous_adjusted_price=100.0,
            current_adjusted_price=102.0,
            daily_cash_vol_target=600.0,
            price_volatility=2.0,
            forecast=10.0,
            quotes={
                "JUN": ContractQuote(
                    bid=101.9,
                    ask=102.1,
                ),
            },
            commission_per_contract=1.0,
            roll_to_contract=None,
        ),

        # Day 3
        ContractAwareBacktestDayInput(
            previous_adjusted_price=102.0,
            current_adjusted_price=101.0,
            daily_cash_vol_target=600.0,
            price_volatility=2.0,
            forecast=-10.0,
            quotes={
                "JUN": ContractQuote(
                    bid=100.9,
                    ask=101.1,
                ),
            },
            commission_per_contract=1.0,
            roll_to_contract=None,
        ),

        # Day 4
        ContractAwareBacktestDayInput(
            previous_adjusted_price=101.0,
            current_adjusted_price=99.0,
            daily_cash_vol_target=600.0,
            price_volatility=3.0,
            forecast=-15.0,
            quotes={},
            commission_per_contract=1.0,
            roll_to_contract=None,
        ),

        # Day 5
        ContractAwareBacktestDayInput(
            previous_adjusted_price=99.0,
            current_adjusted_price=100.0,
            daily_cash_vol_target=600.0,
            price_volatility=3.0,
            forecast=0.0,
            quotes={
                "JUN": ContractQuote(
                    bid=99.9,
                    ask=100.1,
                ),
            },
            commission_per_contract=1.0,
            roll_to_contract=None,
        ),
    ]

    results = run_contract_aware_backtest(
        initial_account_value=50000.0,
        initial_position=0,
        initial_contract_positions={},
        initial_active_contract="JUN",
        days=days,
        instrument_spec=instrument_spec,
    )

    assert len(results) == 5

    assert [
        result.closing_account_value
        for result in results
    ] == pytest.approx([
        49960.0,
        50340.0,
        49920.0,
        50520.0,
        50160.0,
    ])

    assert [
        result.new_instrument_position
        for result in results
    ] == [
        20,
        30,
        -30,
        -30,
        0,
    ]

    assert [
        result.directional_trade
        for result in results
    ] == [
        20,
        10,
        -60,
        0,
        30,
    ]

    assert [
        result.gross_pnl
        for result in results
    ] == pytest.approx([
        0.0,
        400.0,
        -300.0,
        600.0,
        -300.0,
    ])

    assert [
        result.total_trading_cost
        for result in results
    ] == pytest.approx([
        40.0,
        20.0,
        120.0,
        0.0,
        60.0,
    ])

    assert [
        result.net_pnl
        for result in results
    ] == pytest.approx([
        -40.0,
        380.0,
        -420.0,
        600.0,
        -360.0,
    ])

    assert results[0].new_contract_positions == {
        "JUN": 20,
    }

    assert results[1].new_contract_positions == {
        "JUN": 30,
    }

    assert results[2].new_contract_positions == {
        "JUN": -30,
    }

    assert results[3].new_contract_positions == {
        "JUN": -30,
    }

    assert results[4].new_contract_positions == {}

    assert all(
        result.active_contract == "JUN"
        for result in results
    )

def test_contract_aware_backtest_runs_full_10_day_acceptance():
    days = [
        # Day 1
        ContractAwareBacktestDayInput(
            previous_adjusted_price=100.0,
            current_adjusted_price=100.0,
            daily_cash_vol_target=600.0,
            price_volatility=3.0,
            forecast=10.0,
            quotes={
                "JUN": ContractQuote(
                    bid=99.9,
                    ask=100.1,
                ),
            },
            commission_per_contract=1.0,
            roll_to_contract=None,
        ),

        # Day 2
        ContractAwareBacktestDayInput(
            previous_adjusted_price=100.0,
            current_adjusted_price=102.0,
            daily_cash_vol_target=600.0,
            price_volatility=2.0,
            forecast=10.0,
            quotes={
                "JUN": ContractQuote(
                    bid=101.9,
                    ask=102.1,
                ),
            },
            commission_per_contract=1.0,
            roll_to_contract=None,
        ),

        # Day 3
        ContractAwareBacktestDayInput(
            previous_adjusted_price=102.0,
            current_adjusted_price=101.0,
            daily_cash_vol_target=600.0,
            price_volatility=2.0,
            forecast=-10.0,
            quotes={
                "JUN": ContractQuote(
                    bid=100.9,
                    ask=101.1,
                ),
            },
            commission_per_contract=1.0,
            roll_to_contract=None,
        ),

        # Day 4
        ContractAwareBacktestDayInput(
            previous_adjusted_price=101.0,
            current_adjusted_price=99.0,
            daily_cash_vol_target=600.0,
            price_volatility=3.0,
            forecast=-15.0,
            quotes={},
            commission_per_contract=1.0,
            roll_to_contract=None,
        ),

        # Day 5
        ContractAwareBacktestDayInput(
            previous_adjusted_price=99.0,
            current_adjusted_price=100.0,
            daily_cash_vol_target=600.0,
            price_volatility=3.0,
            forecast=0.0,
            quotes={
                "JUN": ContractQuote(
                    bid=99.9,
                    ask=100.1,
                ),
            },
            commission_per_contract=1.0,
            roll_to_contract=None,
        ),

        # Day 6
        ContractAwareBacktestDayInput(
            previous_adjusted_price=100.0,
            current_adjusted_price=104.0,
            daily_cash_vol_target=600.0,
            price_volatility=1.0,
            forecast=10.0,
            quotes={
                "SEP": ContractQuote(
                    bid=103.9,
                    ask=104.1,
                ),
            },
            commission_per_contract=1.0,
            roll_to_contract="SEP",
        ),

        # Day 7
        ContractAwareBacktestDayInput(
            previous_adjusted_price=104.0,
            current_adjusted_price=106.0,
            daily_cash_vol_target=600.0,
            price_volatility=3.0,
            forecast=10.0,
            quotes={
                "SEP": ContractQuote(
                    bid=105.9,
                    ask=106.1,
                ),
            },
            commission_per_contract=1.0,
            roll_to_contract=None,
        ),

        # Day 8
        ContractAwareBacktestDayInput(
            previous_adjusted_price=106.0,
            current_adjusted_price=105.0,
            daily_cash_vol_target=600.0,
            price_volatility=3.0,
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
            commission_per_contract=1.0,
            roll_to_contract="DEC",
        ),

        # Day 9
        ContractAwareBacktestDayInput(
            previous_adjusted_price=105.0,
            current_adjusted_price=101.0,
            daily_cash_vol_target=600.0,
            price_volatility=4.0,
            forecast=-20.0,
            quotes={
                "DEC": ContractQuote(
                    bid=100.9,
                    ask=101.1,
                ),
            },
            commission_per_contract=1.0,
            roll_to_contract=None,
        ),

        # Day 10
        ContractAwareBacktestDayInput(
            previous_adjusted_price=101.0,
            current_adjusted_price=103.0,
            daily_cash_vol_target=600.0,
            price_volatility=5.0,
            forecast=-10.0,
            quotes={
                "DEC": ContractQuote(
                    bid=102.9,
                    ask=103.1,
                ),
            },
            commission_per_contract=1.0,
            roll_to_contract=None,
        ),
    ]

    results = run_contract_aware_backtest(
        initial_account_value=50000.0,
        initial_position=0,
        initial_contract_positions={},
        initial_active_contract="JUN",
        days=days,
        instrument_spec=instrument_spec,
    )

    assert len(results) == 10

    assert [
        result.closing_account_value
        for result in results
    ] == pytest.approx([
        49960.0,
        50340.0,
        49920.0,
        50520.0,
        50160.0,
        50040.0,
        51160.0,
        50880.0,
        49980.0,
        49344.0,
    ])

    assert [
        result.new_instrument_position
        for result in results
    ] == [
        20,
        30,
        -30,
        -30,
        0,
        60,
        20,
        20,
        -30,
        -12,
    ]

    assert [
        result.directional_trade
        for result in results
    ] == [
        20,
        10,
        -60,
        0,
        30,
        60,
        -40,
        0,
        -50,
        18,
    ]

    assert [
        result.gross_pnl
        for result in results
    ] == pytest.approx([
        0.0,
        400.0,
        -300.0,
        600.0,
        -300.0,
        0.0,
        1200.0,
        -200.0,
        -800.0,
        -600.0,
    ])

    assert [
        result.total_trading_cost
        for result in results
    ] == pytest.approx([
        40.0,
        20.0,
        120.0,
        0.0,
        60.0,
        120.0,
        80.0,
        80.0,
        100.0,
        36.0,
    ])

    assert [
        result.net_pnl
        for result in results
    ] == pytest.approx([
        -40.0,
        380.0,
        -420.0,
        600.0,
        -360.0,
        -120.0,
        1120.0,
        -280.0,
        -900.0,
        -636.0,
    ])

    assert results[0].new_contract_positions == {"JUN": 20}
    assert results[1].new_contract_positions == {"JUN": 30}
    assert results[2].new_contract_positions == {"JUN": -30}
    assert results[3].new_contract_positions == {"JUN": -30}
    assert results[4].new_contract_positions == {}

    assert results[5].new_contract_positions == {"SEP": 60}
    assert results[6].new_contract_positions == {"SEP": 20}
    assert results[7].new_contract_positions == {"DEC": 20}
    assert results[8].new_contract_positions == {"DEC": -30}
    assert results[9].new_contract_positions == {"DEC": -12}

    assert [
        result.active_contract
        for result in results
    ] == [
        "JUN",
        "JUN",
        "JUN",
        "JUN",
        "JUN",
        "SEP",
        "SEP",
        "DEC",
        "DEC",
        "DEC",
    ]

    assert results[-1].closing_account_value == pytest.approx(49344.0)
    assert results[-1].new_instrument_position == -12
    assert results[-1].new_contract_positions == {
        "DEC": -12,
    }

def test_contract_aware_backtest_applies_slippage():
    days = [
        ContractAwareBacktestDayInput(
            previous_adjusted_price=100.0,
            current_adjusted_price=100.0,
            daily_cash_vol_target=600.0,
            price_volatility=6.0,
            forecast=10.0,
            quotes={
                "SEP": ContractQuote(
                    bid=99.9,
                    ask=100.1,
                ),
            },
            commission_per_contract=1.0,
            roll_to_contract=None,
            slippage_ticks=1,
        ),
    ]

    results = run_contract_aware_backtest(
        initial_account_value=50000.0,
        initial_position=0,
        initial_contract_positions={},
        initial_active_contract="SEP",
        days=days,
        instrument_spec=instrument_spec,
    )

    assert len(results) == 1

    result = results[0]

    print(
        "costs:",
        [result.total_trading_cost for result in results],
    )

    print(
        "gross:",
        [result.gross_pnl for result in results],
    )

    print(
        "net:",
        [result.net_pnl for result in results],
    )

    print(
        "accounts:",
        [result.closing_account_value for result in results],
    )

    print(
        "positions:",
        [result.new_instrument_position for result in results],
    )



    assert result.target_position == 10
    assert result.directional_trade == 10

    assert result.executions[0].fill_price == pytest.approx(100.2)

    assert result.total_trading_cost == pytest.approx(30.0)
    assert result.net_pnl == pytest.approx(-30.0)
    assert result.closing_account_value == pytest.approx(49970.0)

def test_full_10_day_acceptance_with_one_tick_slippage():
    days = [
        # Day 1
        ContractAwareBacktestDayInput(
            previous_adjusted_price=100.0,
            current_adjusted_price=100.0,
            daily_cash_vol_target=600.0,
            price_volatility=3.0,
            forecast=10.0,
            quotes={
                "JUN": ContractQuote(
                    bid=99.9,
                    ask=100.1,
                ),
            },
            
            commission_per_contract=1.0,
            roll_to_contract=None,
            slippage_ticks=1,
        ),

        # Day 2
        ContractAwareBacktestDayInput(
            previous_adjusted_price=100.0,
            current_adjusted_price=102.0,
            daily_cash_vol_target=600.0,
            price_volatility=2.0,
            forecast=10.0,
            quotes={
                "JUN": ContractQuote(
                    bid=101.9,
                    ask=102.1,
                ),
            },
            
            commission_per_contract=1.0,
            roll_to_contract=None,
            slippage_ticks=1,
        ),

        # Day 3
        ContractAwareBacktestDayInput(
            previous_adjusted_price=102.0,
            current_adjusted_price=101.0,
            daily_cash_vol_target=600.0,
            price_volatility=2.0,
            forecast=-10.0,
            quotes={
                "JUN": ContractQuote(
                    bid=100.9,
                    ask=101.1,
                ),
            },
            
            commission_per_contract=1.0,
            roll_to_contract=None,
            slippage_ticks=1,
        ),

        # Day 4
        ContractAwareBacktestDayInput(
            previous_adjusted_price=101.0,
            current_adjusted_price=99.0,
            daily_cash_vol_target=600.0,
            price_volatility=3.0,
            forecast=-15.0,
            quotes={},
            
            commission_per_contract=1.0,
            roll_to_contract=None,
            slippage_ticks=1,
        ),

        # Day 5
        ContractAwareBacktestDayInput(
            previous_adjusted_price=99.0,
            current_adjusted_price=100.0,
            daily_cash_vol_target=600.0,
            price_volatility=3.0,
            forecast=0.0,
            quotes={
                "JUN": ContractQuote(
                    bid=99.9,
                    ask=100.1,
                ),
            },
            
            commission_per_contract=1.0,
            roll_to_contract=None,
            slippage_ticks=1,
        ),

        # Day 6
        ContractAwareBacktestDayInput(
            previous_adjusted_price=100.0,
            current_adjusted_price=104.0,
            daily_cash_vol_target=600.0,
            price_volatility=1.0,
            forecast=10.0,
            quotes={
                "SEP": ContractQuote(
                    bid=103.9,
                    ask=104.1,
                ),
            },
            
            commission_per_contract=1.0,
            roll_to_contract="SEP",
            slippage_ticks=1,
        ),

        # Day 7
        ContractAwareBacktestDayInput(
            previous_adjusted_price=104.0,
            current_adjusted_price=106.0,
            daily_cash_vol_target=600.0,
            price_volatility=3.0,
            forecast=10.0,
            quotes={
                "SEP": ContractQuote(
                    bid=105.9,
                    ask=106.1,
                ),
            },
            
            commission_per_contract=1.0,
            roll_to_contract=None,
            slippage_ticks=1,
        ),

        # Day 8
        ContractAwareBacktestDayInput(
            previous_adjusted_price=106.0,
            current_adjusted_price=105.0,
            daily_cash_vol_target=600.0,
            price_volatility=3.0,
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
            
            commission_per_contract=1.0,
            roll_to_contract="DEC",
            slippage_ticks=1,
        ),

        # Day 9
        ContractAwareBacktestDayInput(
            previous_adjusted_price=105.0,
            current_adjusted_price=101.0,
            daily_cash_vol_target=600.0,
            price_volatility=4.0,
            forecast=-20.0,
            quotes={
                "DEC": ContractQuote(
                    bid=100.9,
                    ask=101.1,
                ),
            },
            
            commission_per_contract=1.0,
            roll_to_contract=None,
            slippage_ticks=1,
        ),

        # Day 10
        ContractAwareBacktestDayInput(
            previous_adjusted_price=101.0,
            current_adjusted_price=103.0,
            daily_cash_vol_target=600.0,
            price_volatility=5.0,
            forecast=-10.0,
            quotes={
                "DEC": ContractQuote(
                    bid=102.9,
                    ask=103.1,
                ),
            },
            
            commission_per_contract=1.0,
            roll_to_contract=None,
            slippage_ticks=1,
        ),
    ]

    results = run_contract_aware_backtest(
        initial_account_value=50000.0,
        initial_position=0,
        initial_contract_positions={},
        initial_active_contract="JUN",
        days=days,
        instrument_spec=instrument_spec,
    )

    assert len(results) == 10

    # -------------------------
    # Position sizing / trades
    # slippage는 position sizing에는 영향을 주지 않는다.
    # -------------------------
    assert [
        result.new_instrument_position
        for result in results
    ] == [
        20,
        30,
        -30,
        -30,
        0,
        60,
        20,
        20,
        -30,
        -12,
    ]

    assert [
        result.directional_trade
        for result in results
    ] == [
        20,
        10,
        -60,
        0,
        30,
        60,
        -40,
        0,
        -50,
        18,
    ]

    # -------------------------
    # Gross P&L
    # slippage와 무관하며 기존 actual position으로 계산한다.
    # -------------------------
    assert [
        result.gross_pnl
        for result in results
    ] == pytest.approx([
        0.0,
        400.0,
        -300.0,
        600.0,
        -300.0,
        0.0,
        1200.0,
        -200.0,
        -800.0,
        -600.0,
    ])

    # -------------------------
    # Trading cost
    #
    # 0.2 bid-ask spread:
    # half-spread = 0.1 point
    #
    # 1 tick slippage:
    # 0.1 point
    #
    # multiplier = $10 / point
    #
    # contract당:
    # spread effect $1
    # + slippage $1
    # + commission $1
    # = $3 / contract-side
    # -------------------------
    assert [
        result.total_trading_cost
        for result in results
    ] == pytest.approx([
        60.0,   # 20 × $3
        30.0,   # 10 × $3
        180.0,  # 60 × $3
        0.0,    # no trade
        90.0,   # 30 × $3
        180.0,  # 60 × $3
        120.0,  # 40 × $3
        120.0,  # roll: (20 + 20) × $3
        150.0,  # 50 × $3
        54.0,   # 18 × $3
    ])

    # -------------------------
    # Net P&L
    # gross - trading cost
    # -------------------------
    assert [
        result.net_pnl
        for result in results
    ] == pytest.approx([
        -60.0,
        370.0,
        -480.0,
        600.0,
        -390.0,
        -180.0,
        1080.0,
        -320.0,
        -950.0,
        -654.0,
    ])

    # -------------------------
    # Account value
    # -------------------------
    assert [
        result.closing_account_value
        for result in results
    ] == pytest.approx([
        49940.0,
        50310.0,
        49830.0,
        50430.0,
        50040.0,
        49860.0,
        50940.0,
        50620.0,
        49670.0,
        49016.0,
    ])

    # -------------------------
    # Contract positions
    # -------------------------
    assert results[0].new_contract_positions == {
        "JUN": 20,
    }
    assert results[1].new_contract_positions == {
        "JUN": 30,
    }
    assert results[2].new_contract_positions == {
        "JUN": -30,
    }
    assert results[3].new_contract_positions == {
        "JUN": -30,
    }
    assert results[4].new_contract_positions == {}

    assert results[5].new_contract_positions == {
        "SEP": 60,
    }
    assert results[6].new_contract_positions == {
        "SEP": 20,
    }
    assert results[7].new_contract_positions == {
        "DEC": 20,
    }
    assert results[8].new_contract_positions == {
        "DEC": -30,
    }
    assert results[9].new_contract_positions == {
        "DEC": -12,
    }

    # -------------------------
    # Active contract
    # -------------------------
    assert [
        result.active_contract
        for result in results
    ] == [
        "JUN",
        "JUN",
        "JUN",
        "JUN",
        "JUN",
        "SEP",
        "SEP",
        "DEC",
        "DEC",
        "DEC",
    ]

    # -------------------------
    # Final state
    # -------------------------
    assert results[-1].closing_account_value == pytest.approx(
        49016.0
    )

    assert results[-1].new_instrument_position == -12

    assert results[-1].new_contract_positions == {
        "DEC": -12,
    }


def test_contract_aware_backtest_uses_krw_base_currency():
    days = [
        ContractAwareBacktestDayInput(
            previous_adjusted_price=100.0,
            current_adjusted_price=101.0,
            daily_cash_vol_target=27_000.0,
            price_volatility=1.0,
            forecast=10.0,
            quotes={
                "SEP": ContractQuote(
                    bid=100.9,
                    ask=101.1,
                ),
            },
            
            commission_per_contract=1.0,
            roll_to_contract=None,
            slippage_ticks=0,
            fx_to_base=1350.0,
        ),
    ]

    results = run_contract_aware_backtest(
        initial_account_value=10_000_000.0,
        initial_position=1,
        initial_contract_positions={
            "SEP": 1,
        },
        initial_active_contract="SEP",
        days=days,
        instrument_spec=instrument_spec,
    )

    assert len(results) == 1

    result = results[0]

    assert result.gross_pnl == pytest.approx(
        13_500.0
    )

    assert result.target_position == 2
    assert result.directional_trade == 1

    assert result.total_trading_cost == pytest.approx(
        2_700.0
    )

    assert result.net_pnl == pytest.approx(
        10_800.0
    )

    assert result.closing_account_value == pytest.approx(
        10_010_800.0
    )

    assert result.new_contract_positions == {
        "SEP": 2,
    }

def test_full_10_day_acceptance_in_krw_base_currency():
    days = [
        # Day 1
        ContractAwareBacktestDayInput(
            previous_adjusted_price=100.0,
            current_adjusted_price=100.0,
            daily_cash_vol_target=810_000.0,
            price_volatility=3.0,
            forecast=10.0,
            quotes={
                "JUN": ContractQuote(
                    bid=99.9,
                    ask=100.1,
                ),
            },
            
            commission_per_contract=1.0,
            roll_to_contract=None,
            slippage_ticks=0,
            fx_to_base=1350.0,
        ),

        # Day 2
        ContractAwareBacktestDayInput(
            previous_adjusted_price=100.0,
            current_adjusted_price=102.0,
            daily_cash_vol_target=810_000.0,
            price_volatility=2.0,
            forecast=10.0,
            quotes={
                "JUN": ContractQuote(
                    bid=101.9,
                    ask=102.1,
                ),
            },
            
            commission_per_contract=1.0,
            roll_to_contract=None,
            slippage_ticks=0,
            fx_to_base=1350.0,
        ),

        # Day 3
        ContractAwareBacktestDayInput(
            previous_adjusted_price=102.0,
            current_adjusted_price=101.0,
            daily_cash_vol_target=810_000.0,
            price_volatility=2.0,
            forecast=-10.0,
            quotes={
                "JUN": ContractQuote(
                    bid=100.9,
                    ask=101.1,
                ),
            },
            
            commission_per_contract=1.0,
            roll_to_contract=None,
            slippage_ticks=0,
            fx_to_base=1350.0,
        ),

        # Day 4
        ContractAwareBacktestDayInput(
            previous_adjusted_price=101.0,
            current_adjusted_price=99.0,
            daily_cash_vol_target=810_000.0,
            price_volatility=3.0,
            forecast=-15.0,
            quotes={},
            
            commission_per_contract=1.0,
            roll_to_contract=None,
            slippage_ticks=0,
            fx_to_base=1350.0,
        ),

        # Day 5
        ContractAwareBacktestDayInput(
            previous_adjusted_price=99.0,
            current_adjusted_price=100.0,
            daily_cash_vol_target=810_000.0,
            price_volatility=3.0,
            forecast=0.0,
            quotes={
                "JUN": ContractQuote(
                    bid=99.9,
                    ask=100.1,
                ),
            },
            
            commission_per_contract=1.0,
            roll_to_contract=None,
            slippage_ticks=0,
            fx_to_base=1350.0,
        ),

        # Day 6
        ContractAwareBacktestDayInput(
            previous_adjusted_price=100.0,
            current_adjusted_price=104.0,
            daily_cash_vol_target=810_000.0,
            price_volatility=1.0,
            forecast=10.0,
            quotes={
                "SEP": ContractQuote(
                    bid=103.9,
                    ask=104.1,
                ),
            },
            
            commission_per_contract=1.0,
            roll_to_contract="SEP",
            slippage_ticks=0,
            fx_to_base=1350.0,
        ),

        # Day 7
        ContractAwareBacktestDayInput(
            previous_adjusted_price=104.0,
            current_adjusted_price=106.0,
            daily_cash_vol_target=810_000.0,
            price_volatility=3.0,
            forecast=10.0,
            quotes={
                "SEP": ContractQuote(
                    bid=105.9,
                    ask=106.1,
                ),
            },
            
            commission_per_contract=1.0,
            roll_to_contract=None,
            slippage_ticks=0,
            fx_to_base=1350.0,
        ),

        # Day 8
        ContractAwareBacktestDayInput(
            previous_adjusted_price=106.0,
            current_adjusted_price=105.0,
            daily_cash_vol_target=810_000.0,
            price_volatility=3.0,
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
            
            commission_per_contract=1.0,
            roll_to_contract="DEC",
            slippage_ticks=0,
            fx_to_base=1350.0,
        ),

        # Day 9
        ContractAwareBacktestDayInput(
            previous_adjusted_price=105.0,
            current_adjusted_price=101.0,
            daily_cash_vol_target=810_000.0,
            price_volatility=4.0,
            forecast=-20.0,
            quotes={
                "DEC": ContractQuote(
                    bid=100.9,
                    ask=101.1,
                ),
            },
            
            commission_per_contract=1.0,
            roll_to_contract=None,
            slippage_ticks=0,
            fx_to_base=1350.0,
        ),

        # Day 10
        ContractAwareBacktestDayInput(
            previous_adjusted_price=101.0,
            current_adjusted_price=103.0,
            daily_cash_vol_target=810_000.0,
            price_volatility=5.0,
            forecast=-10.0,
            quotes={
                "DEC": ContractQuote(
                    bid=102.9,
                    ask=103.1,
                ),
            },
            
            commission_per_contract=1.0,
            roll_to_contract=None,
            slippage_ticks=0,
            fx_to_base=1350.0,
        ),
    ]

    results = run_contract_aware_backtest(
        initial_account_value=67_500_000.0,
        initial_position=0,
        initial_contract_positions={},
        initial_active_contract="JUN",
        days=days,
        instrument_spec=instrument_spec,
    )

    assert len(results) == 10

    assert [
        result.new_instrument_position
        for result in results
    ] == [
        20,
        30,
        -30,
        -30,
        0,
        60,
        20,
        20,
        -30,
        -12,
    ]

    assert [
        result.directional_trade
        for result in results
    ] == [
        20,
        10,
        -60,
        0,
        30,
        60,
        -40,
        0,
        -50,
        18,
    ]

    assert [
        result.gross_pnl
        for result in results
    ] == pytest.approx([
        0.0,
        540_000.0,
        -405_000.0,
        810_000.0,
        -405_000.0,
        0.0,
        1_620_000.0,
        -270_000.0,
        -1_080_000.0,
        -810_000.0,
    ])

    assert [
        result.total_trading_cost
        for result in results
    ] == pytest.approx([
        54_000.0,
        27_000.0,
        162_000.0,
        0.0,
        81_000.0,
        162_000.0,
        108_000.0,
        108_000.0,
        135_000.0,
        48_600.0,
    ])

    assert [
        result.net_pnl
        for result in results
    ] == pytest.approx([
        -54_000.0,
        513_000.0,
        -567_000.0,
        810_000.0,
        -486_000.0,
        -162_000.0,
        1_512_000.0,
        -378_000.0,
        -1_215_000.0,
        -858_600.0,
    ])

    assert [
        result.closing_account_value
        for result in results
    ] == pytest.approx([
        67_446_000.0,
        67_959_000.0,
        67_392_000.0,
        68_202_000.0,
        67_716_000.0,
        67_554_000.0,
        69_066_000.0,
        68_688_000.0,
        67_473_000.0,
        66_614_400.0,
    ])

    assert results[-1].closing_account_value == pytest.approx(
        66_614_400.0
    )

    assert results[-1].new_contract_positions == {
        "DEC": -12,
    }

def test_contract_aware_backtest_uses_daily_fx_rate():
    days = [
        # Day 1: 1 USD = 1,350 KRW
        ContractAwareBacktestDayInput(
            previous_adjusted_price=100.0,
            current_adjusted_price=101.0,
            daily_cash_vol_target=21_000.0,
            price_volatility=1.0,
            forecast=10.0,
            quotes={
                "SEP": ContractQuote(
                    bid=100.9,
                    ask=101.1,
                ),
            },
            
            commission_per_contract=1.0,
            roll_to_contract=None,
            slippage_ticks=0,
            fx_to_base=1350.0,
        ),

        # Day 2: 1 USD = 1,500 KRW
        ContractAwareBacktestDayInput(
            previous_adjusted_price=101.0,
            current_adjusted_price=102.0,
            daily_cash_vol_target=21_000.0,
            price_volatility=1.0,
            forecast=10.0,
            quotes={
                "SEP": ContractQuote(
                    bid=101.9,
                    ask=102.1,
                ),
            },
            
            commission_per_contract=1.0,
            roll_to_contract=None,
            slippage_ticks=0,
            fx_to_base=1500.0,
        ),
    ]

    results = run_contract_aware_backtest(
        initial_account_value=10_000_000.0,
        initial_position=1,
        initial_contract_positions={
            "SEP": 1,
        },
        initial_active_contract="SEP",
        days=days,
        instrument_spec=instrument_spec,
    )

    assert len(results) == 2

    day_1 = results[0]
    day_2 = results[1]

    # Day 1
    assert day_1.gross_pnl == pytest.approx(
        13_500.0
    )

    assert day_1.target_position == 2
    assert day_1.directional_trade == 1

    assert day_1.total_trading_cost == pytest.approx(
        2_700.0
    )

    assert day_1.net_pnl == pytest.approx(
        10_800.0
    )

    assert day_1.closing_account_value == pytest.approx(
        10_010_800.0
    )

    assert day_1.new_contract_positions == {
        "SEP": 2,
    }

    # Day 2
    assert day_2.gross_pnl == pytest.approx(
        30_000.0
    )

    assert day_2.target_position == 1
    assert day_2.directional_trade == -1

    assert day_2.total_trading_cost == pytest.approx(
        3_000.0
    )

    assert day_2.net_pnl == pytest.approx(
        27_000.0
    )

    assert day_2.closing_account_value == pytest.approx(
        10_037_800.0
    )

    assert day_2.new_contract_positions == {
        "SEP": 1,
    }

def test_backtest_uses_multiplier_from_instrument_spec():
    instrument_spec = InstrumentSpec(
        symbol="TEST",
        currency="USD",
        multiplier=20.0,
        tick_size=0.1,
    )

    days = [
        ContractAwareBacktestDayInput(
            previous_adjusted_price=100.0,
            current_adjusted_price=100.0,
            daily_cash_vol_target=600.0,
            price_volatility=3.0,
            forecast=10.0,
            quotes={
                "JUN": ContractQuote(
                    bid=99.9,
                    ask=100.1,
                ),
            },
            commission_per_contract=1.0,
            roll_to_contract=None,
        ),
    ]

    results = run_contract_aware_backtest(
        initial_account_value=50_000.0,
        initial_position=0,
        initial_contract_positions={},
        initial_active_contract="JUN",
        days=days,
        instrument_spec=instrument_spec,
    )

    assert results[0].target_position == 10

def test_backtest_uses_tick_size_from_instrument_spec():
    instrument_spec = InstrumentSpec(
        symbol="TEST",
        currency="USD",
        multiplier=10.0,
        tick_size=0.25,
    )

    days = [
        ContractAwareBacktestDayInput(
            previous_adjusted_price=100.0,
            current_adjusted_price=100.0,
            daily_cash_vol_target=100.0,
            price_volatility=1.0,
            forecast=10.0,
            quotes={
                "JUN": ContractQuote(
                    bid=99.75,
                    ask=100.25,
                ),
            },
            commission_per_contract=0.0,
            roll_to_contract=None,
            slippage_ticks=1,
        ),
    ]

    results = run_contract_aware_backtest(
        initial_account_value=50_000.0,
        initial_position=0,
        initial_contract_positions={},
        initial_active_contract="JUN",
        days=days,
        instrument_spec=instrument_spec,
    )

    assert results[0].executions[0].fill_price == pytest.approx(
        100.50
    )