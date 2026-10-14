from datetime import date, timedelta

import pytest

from carver_quant.forecast import (
    make_afts_ewmac_config,
)
from carver_quant.futures_data import (
    ContractPrice,
)
from carver_quant.instrument import (
    InstrumentSpec,
)
from carver_quant.roll_execution import (
    ContractQuote,
)
from carver_quant.system_backtest import (
    ExecutionMarketDay,
    _prepare_backtest_from_point_in_time_signals,
    prepare_ewmac_backtest,
    run_ewmac_system_backtest,
)

from carver_quant.research_pipeline import (
    PointInTimeResearchSignalPoint,
    ResearchSignalPoint,
)



def make_prices(values):
    start = date(2026, 1, 1)

    return [
        ContractPrice(
            date=start + timedelta(
                days=index
            ),
            contract="TEST",
            close=value,
        )
        for index, value
        in enumerate(values)
    ]

def test_backtest_uses_previous_days_signal():
    prices = make_prices([
        100.0,
        101.0,
        103.0,
        106.0,
    ])

    prepared = prepare_ewmac_backtest(
        prices=prices,
        initial_contract="TEST",
        roll_events=[],
        execution_days=[
            ExecutionMarketDay(
                date=date(2026, 1, 4),
                daily_cash_vol_target=100.0,
                quotes={
                    "TEST": ContractQuote(
                        bid=105.9,
                        ask=106.1,
                    )
                },
                commission_per_contract=1.0,
            )
        ],
        ewmac_config=(
            make_afts_ewmac_config(2)
        ),
    )

    assert len(prepared.days) == 1

    day = prepared.days[0]

    # Jan 4에 거래하지만
    # signal은 Jan 3 데이터를 사용한다.
    previous_signal = prepared.signals[2]

    assert day.previous_adjusted_price == pytest.approx(
        103.0
    )

    assert day.current_adjusted_price == pytest.approx(
        106.0
    )

    assert day.price_volatility == pytest.approx(
        previous_signal.price_volatility
    )

    assert day.forecast == pytest.approx(
        previous_signal.forecast
    )

def test_current_close_does_not_change_same_day_trade_signal():
    normal_prices = make_prices([
        100.0,
        101.0,
        103.0,
        106.0,
    ])

    shock_prices = make_prices([
        100.0,
        101.0,
        103.0,
        500.0,
    ])

    execution_days = [
        ExecutionMarketDay(
            date=date(2026, 1, 4),
            daily_cash_vol_target=100.0,
            quotes={
                "TEST": ContractQuote(
                    bid=499.9,
                    ask=500.1,
                )
            },
            commission_per_contract=1.0,
        )
    ]

    normal = prepare_ewmac_backtest(
        prices=normal_prices,
        initial_contract="TEST",
        roll_events=[],
        execution_days=execution_days,
        ewmac_config=(
            make_afts_ewmac_config(2)
        ),
    )

    shock = prepare_ewmac_backtest(
        prices=shock_prices,
        initial_contract="TEST",
        roll_events=[],
        execution_days=execution_days,
        ewmac_config=(
            make_afts_ewmac_config(2)
        ),
    )

    assert (
        shock.days[0].forecast
        == pytest.approx(
            normal.days[0].forecast
        )
    )

    assert (
        shock.days[0].price_volatility
        == pytest.approx(
            normal.days[0]
            .price_volatility
        )
    )

def test_price_to_account_end_to_end():
    prices = make_prices([
        100.0,
        101.0,
        103.0,
        106.0,
        110.0,
        115.0,
    ])

    execution_days = [
        ExecutionMarketDay(
            date=date(2026, 1, 4),
            daily_cash_vol_target=100.0,
            quotes={
                "TEST": ContractQuote(
                    bid=105.9,
                    ask=106.1,
                )
            },
            commission_per_contract=1.0,
        ),
        ExecutionMarketDay(
            date=date(2026, 1, 5),
            daily_cash_vol_target=100.0,
            quotes={
                "TEST": ContractQuote(
                    bid=109.9,
                    ask=110.1,
                )
            },
            commission_per_contract=1.0,
        ),
        ExecutionMarketDay(
            date=date(2026, 1, 6),
            daily_cash_vol_target=100.0,
            quotes={
                "TEST": ContractQuote(
                    bid=114.9,
                    ask=115.1,
                )
            },
            commission_per_contract=1.0,
        ),
    ]

    instrument_spec = InstrumentSpec(
        symbol="TEST",
        currency="USD",
        multiplier=10.0,
        tick_size=0.1,
    )

    results = run_ewmac_system_backtest(
        initial_account_value=50_000.0,
        prices=prices,
        initial_contract="TEST",
        roll_events=[],
        execution_days=execution_days,
        ewmac_config=(
            make_afts_ewmac_config(2)
        ),
        instrument_spec=instrument_spec,
    )

    assert len(results) == 3

    assert [
        result.target_position
        for result in results
    ] == [
        28,
        18,
        13,
    ]

    assert [
        result.directional_trade
        for result in results
    ] == [
        28,
        -10,
        -5,
    ]

    assert [
        result.total_trading_cost
        for result in results
    ] == pytest.approx([
        56.0,
        20.0,
        10.0,
    ])

    assert [
        result.gross_pnl
        for result in results
    ] == pytest.approx([
        0.0,
        1120.0,
        900.0,
    ])

    assert results[-1].closing_account_value == pytest.approx(
        51_934.0
    )

    assert results[-1].new_contract_positions == {
        "TEST": 13,
    }

def test_pit_replay_uses_pit_signal_but_continuous_price_for_pnl():
    d1 = date(2026, 1, 1)
    d2 = date(2026, 1, 2)
    d3 = date(2026, 1, 3)

    pit_signals = [
        PointInTimeResearchSignalPoint(
            as_of_date=d1,
            active_contract="TEST",
            raw_price=100.0,
            snapshot_adjusted_price=100.0,
            price_volatility=2.0,
            forecast=5.0,
        ),

        PointInTimeResearchSignalPoint(
            as_of_date=d2,
            active_contract="TEST",
            raw_price=101.0,
            snapshot_adjusted_price=101.0,
            price_volatility=3.0,
            forecast=7.0,
        ),

        # 새로운 roll adjustment가 알려졌다고
        # 가정해서 snapshot level이 크게 rebase.
        PointInTimeResearchSignalPoint(
            as_of_date=d3,
            active_contract="TEST",
            raw_price=102.0,
            snapshot_adjusted_price=111.0,
            price_volatility=4.0,
            forecast=9.0,
        ),
    ]

    # P&L용 continuous series.
    #
    # 전체 level은 snapshot과 달라도
    # d2 -> d3 실제 변화는 +1.
    continuous_signals = [
        ResearchSignalPoint(
            date=d1,
            active_contract="TEST",
            raw_price=100.0,
            adjusted_price=109.0,
            price_volatility=None,
            raw_crossover=0.0,
            forecast=None,
        ),

        ResearchSignalPoint(
            date=d2,
            active_contract="TEST",
            raw_price=101.0,
            adjusted_price=110.0,
            price_volatility=None,
            raw_crossover=0.0,
            forecast=None,
        ),

        ResearchSignalPoint(
            date=d3,
            active_contract="TEST",
            raw_price=102.0,
            adjusted_price=111.0,
            price_volatility=None,
            raw_crossover=0.0,
            forecast=None,
        ),
    ]

    execution_days = [
        ExecutionMarketDay(
            date=d2,
            daily_cash_vol_target=1000.0,
            quotes={
                "TEST": ContractQuote(
                    bid=101.0,
                    ask=101.0,
                ),
            },
            commission_per_contract=0.0,
        ),

        ExecutionMarketDay(
            date=d3,
            daily_cash_vol_target=1000.0,
            quotes={
                "TEST": ContractQuote(
                    bid=102.0,
                    ask=102.0,
                ),
            },
            commission_per_contract=0.0,
        ),
    ]

    prepared = (
        _prepare_backtest_from_point_in_time_signals(
            pit_signals=pit_signals,
            continuous_signals=(
                continuous_signals
            ),
            roll_events=[],
            execution_days=(
                execution_days
            ),
        )
    )

    assert len(prepared.days) == 2

    second_day = prepared.days[1]

    # ---------------------------------
    # Signal은 t-1 PIT
    # ---------------------------------

    assert (
        second_day.price_volatility
        == pytest.approx(3.0)
    )

    assert (
        second_day.forecast
        == pytest.approx(7.0)
    )

    # ---------------------------------
    # P&L price는 continuous path
    # ---------------------------------

    assert (
        second_day.previous_adjusted_price
        == pytest.approx(110.0)
    )

    assert (
        second_day.current_adjusted_price
        == pytest.approx(111.0)
    )

    assert (
        second_day.current_adjusted_price
        - second_day.previous_adjusted_price
        == pytest.approx(1.0)
    )

    # PIT snapshot끼리 빼면 +10이지만
    # 그 값은 P&L에 사용하면 안 된다.
    assert (
        pit_signals[2]
        .snapshot_adjusted_price
        - pit_signals[1]
        .snapshot_adjusted_price
        == pytest.approx(10.0)
    )