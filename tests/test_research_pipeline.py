from datetime import date, timedelta

import pytest

from carver_quant.forecast import (
    make_afts_ewmac_config,
)
from carver_quant.futures_data import (
    ContractPrice,
    RollEvent,
)
from carver_quant.research_pipeline import (
    build_combined_ewmac_research_signals,
    build_ewmac_research_signals,
    build_point_in_time_combined_ewmac_signals,
)

def make_contract_prices(
    values,
    contract="TEST",
):
    start = date(2026, 1, 1)

    return [
        ContractPrice(
            date=start + timedelta(days=index),
            contract=contract,
            close=value,
        )
        for index, value in enumerate(values)
    ]


def test_research_pipeline_generates_positive_forecast_for_uptrend():
    prices = make_contract_prices([
        100.0,
        101.0,
        103.0,
        106.0,
        110.0,
        115.0,
    ])

    result = build_ewmac_research_signals(
        prices=prices,
        initial_contract="TEST",
        roll_events=[],
        ewmac_config=make_afts_ewmac_config(
            16
        ),
    )

    assert len(result) == 6

    assert result[-1].price_volatility is not None
    assert result[-1].raw_crossover > 0.0
    assert result[-1].forecast > 0.0


def test_research_pipeline_has_warmup_period():
    prices = make_contract_prices([
        100.0,
        101.0,
        103.0,
        106.0,
    ])

    result = build_ewmac_research_signals(
        prices=prices,
        initial_contract="TEST",
        roll_events=[],
        ewmac_config=make_afts_ewmac_config(
            16
        ),
    )

    assert result[0].price_volatility is None
    assert result[0].forecast is None

    assert result[1].price_volatility is None
    assert result[1].forecast is None

    assert result[2].price_volatility is not None
    assert result[2].forecast is not None

def test_research_pipeline_removes_artificial_roll_jump():
    prices = [
        ContractPrice(
            date=date(2026, 1, 1),
            contract="A",
            close=100.0,
        ),
        ContractPrice(
            date=date(2026, 1, 2),
            contract="A",
            close=101.0,
        ),
        ContractPrice(
            date=date(2026, 1, 2),
            contract="B",
            close=111.0,
        ),
        ContractPrice(
            date=date(2026, 1, 3),
            contract="B",
            close=111.0,
        ),
    ]

    result = build_ewmac_research_signals(
        prices=prices,
        initial_contract="A",
        roll_events=[
            RollEvent(
                date=date(2026, 1, 2),
                old_contract="A",
                new_contract="B",
            ),
        ],
        ewmac_config=make_afts_ewmac_config(
            16
        ),
    )

    assert result[1].adjusted_price == pytest.approx(
        111.0
    )

    assert result[2].adjusted_price == pytest.approx(
        111.0
    )

    assert (
        result[2].adjusted_price
        - result[1].adjusted_price
    ) == pytest.approx(
        0.0
    )

def test_research_pipeline_supports_negative_prices():
    prices = make_contract_prices([
        -10.0,
        -8.0,
        -11.0,
        -7.0,
    ])

    result = build_ewmac_research_signals(
        prices=prices,
        initial_contract="TEST",
        roll_events=[],
        ewmac_config=make_afts_ewmac_config(
            16
        ),
    )

    assert result[0].adjusted_price == pytest.approx(
        -10.0
    )

    assert result[-1].price_volatility is not None

def test_future_raw_price_does_not_change_past_signals():
    short_prices = make_contract_prices([
        100.0,
        102.0,
        101.0,
        104.0,
        103.0,
    ])

    long_prices = make_contract_prices([
        100.0,
        102.0,
        101.0,
        104.0,
        103.0,
        500.0,
    ])

    short_result = build_ewmac_research_signals(
        prices=short_prices,
        initial_contract="TEST",
        roll_events=[],
        ewmac_config=make_afts_ewmac_config(
            16
        ),
    )

    long_result = build_ewmac_research_signals(
        prices=long_prices,
        initial_contract="TEST",
        roll_events=[],
        ewmac_config=make_afts_ewmac_config(
            16
        ),
    )

    for short, long in zip(
        short_result,
        long_result[:5],
    ):
        assert long.adjusted_price == pytest.approx(
            short.adjusted_price
        )

        if short.price_volatility is None:
            assert long.price_volatility is None
        else:
            assert long.price_volatility == pytest.approx(
                short.price_volatility
            )

        if short.forecast is None:
            assert long.forecast is None
        else:
            assert long.forecast == pytest.approx(
                short.forecast
            )

def test_combined_research_pipeline_uses_blended_volatility():
    prices = make_contract_prices([
        100.0,
        110.0,
        100.0,
        101.0,
        102.0,
        103.0,
        104.0,
        105.0,
    ])

    result = (
        build_combined_ewmac_research_signals(
            prices=prices,
            initial_contract="TEST",
            roll_events=[],

            # 테스트에서 차이를 빨리 보기 위해
            # 짧은 long-run window 사용
            long_run_window=3,
        )
    )

    assert (
        result[-1].price_volatility
        is not None
    )

    assert (
        result[-1].forecast
        is not None
    )

def test_future_price_does_not_change_past_combined_blended_signals():
    short_prices = make_contract_prices([
        100.0,
        110.0,
        100.0,
        101.0,
        102.0,
        103.0,
    ])

    extended_prices = make_contract_prices([
        100.0,
        110.0,
        100.0,
        101.0,
        102.0,
        103.0,

        # 미래의 극단적인 가격
        500.0,
    ])

    short_result = (
        build_combined_ewmac_research_signals(
            prices=short_prices,
            initial_contract="TEST",
            roll_events=[],
            long_run_window=3,
        )
    )

    extended_result = (
        build_combined_ewmac_research_signals(
            prices=extended_prices,
            initial_contract="TEST",
            roll_events=[],
            long_run_window=3,
        )
    )

    for expected, actual in zip(
        short_result,
        extended_result[:6],
    ):
        if expected.price_volatility is None:
            assert (
                actual.price_volatility
                is None
            )
        else:
            assert (
                actual.price_volatility
                == pytest.approx(
                    expected.price_volatility
                )
            )

        if expected.forecast is None:
            assert actual.forecast is None

        else:
            assert (
                actual.forecast
                == pytest.approx(
                    expected.forecast
                )
            )

def test_future_roll_does_not_change_past_point_in_time_signals():
    prices = [
        ContractPrice(
            date=date(2026, 1, 1),
            contract="A",
            close=100.0,
        ),
        ContractPrice(
            date=date(2026, 1, 2),
            contract="A",
            close=101.0,
        ),
        ContractPrice(
            date=date(2026, 1, 3),
            contract="A",
            close=102.0,
        ),
        ContractPrice(
            date=date(2026, 1, 4),
            contract="A",
            close=103.0,
        ),
        ContractPrice(
            date=date(2026, 1, 5),
            contract="A",
            close=104.0,
        ),

        # 미래 roll date
        ContractPrice(
            date=date(2026, 1, 6),
            contract="A",
            close=105.0,
        ),
        ContractPrice(
            date=date(2026, 1, 6),
            contract="B",
            close=114.0,
        ),
        ContractPrice(
            date=date(2026, 1, 7),
            contract="B",
            close=115.0,
        ),
    ]

    roll_events = [
        RollEvent(
            date=date(2026, 1, 6),
            old_contract="A",
            new_contract="B",
        )
    ]

    prefix_prices = [
        price
        for price in prices
        if price.date <= date(
            2026,
            1,
            5,
        )
    ]

    prefix = (
        build_point_in_time_combined_ewmac_signals(
            prices=prefix_prices,
            initial_contract="A",

            # 미래 roll을 넘겨도
            # as-of 처리 때문에 사용되면 안 된다.
            roll_events=roll_events,

            long_run_window=3,
        )
    )

    full = (
        build_point_in_time_combined_ewmac_signals(
            prices=prices,
            initial_contract="A",
            roll_events=roll_events,
            long_run_window=3,
        )
    )

    assert len(prefix) == 5

    for expected, actual in zip(
        prefix,
        full[:5],
    ):
        assert (
            actual.as_of_date
            == expected.as_of_date
        )

        assert (
            actual.snapshot_adjusted_price
            == pytest.approx(
                expected
                .snapshot_adjusted_price
            )
        )

        if expected.price_volatility is None:
            assert (
                actual.price_volatility
                is None
            )
        else:
            assert (
                actual.price_volatility
                == pytest.approx(
                    expected.price_volatility
                )
            )

        if expected.forecast is None:
            assert actual.forecast is None

        else:
            assert (
                actual.forecast
                == pytest.approx(
                    expected.forecast
                )
            )

def test_point_in_time_adjusted_level_rebases_when_roll_becomes_known():
    prices = [
        ContractPrice(
            date=date(2026, 1, 1),
            contract="A",
            close=100.0,
        ),
        ContractPrice(
            date=date(2026, 1, 2),
            contract="A",
            close=101.0,
        ),
        ContractPrice(
            date=date(2026, 1, 3),
            contract="A",
            close=102.0,
        ),
        ContractPrice(
            date=date(2026, 1, 4),
            contract="A",
            close=103.0,
        ),
        ContractPrice(
            date=date(2026, 1, 5),
            contract="A",
            close=104.0,
        ),
        ContractPrice(
            date=date(2026, 1, 6),
            contract="A",
            close=105.0,
        ),
        ContractPrice(
            date=date(2026, 1, 6),
            contract="B",
            close=114.0,
        ),
        ContractPrice(
            date=date(2026, 1, 7),
            contract="B",
            close=115.0,
        ),
    ]

    result = (
        build_point_in_time_combined_ewmac_signals(
            prices=prices,
            initial_contract="A",
            roll_events=[
                RollEvent(
                    date=date(2026, 1, 6),
                    old_contract="A",
                    new_contract="B",
                )
            ],
            long_run_window=3,
        )
    )

    jan5 = next(
        point
        for point in result
        if point.as_of_date
        == date(2026, 1, 5)
    )

    jan6 = next(
        point
        for point in result
        if point.as_of_date
        == date(2026, 1, 6)
    )

    assert (
        jan5.snapshot_adjusted_price
        == pytest.approx(104.0)
    )

    # Jan 6:
    # A = 105
    # B = 114
    # roll gap = +9
    #
    # snapshot 전체가 +9로 재기준화된다.
    assert (
        jan6.snapshot_adjusted_price
        == pytest.approx(114.0)
    )

def test_point_in_time_active_contract_switches_after_roll_date():
    prices = [
        ContractPrice(
            date=date(2026, 1, 1),
            contract="A",
            close=100.0,
        ),
        ContractPrice(
            date=date(2026, 1, 2),
            contract="A",
            close=101.0,
        ),
        ContractPrice(
            date=date(2026, 1, 2),
            contract="B",
            close=110.0,
        ),
        ContractPrice(
            date=date(2026, 1, 3),
            contract="B",
            close=111.0,
        ),
    ]

    result = (
        build_point_in_time_combined_ewmac_signals(
            prices=prices,
            initial_contract="A",
            roll_events=[
                RollEvent(
                    date=date(2026, 1, 2),
                    old_contract="A",
                    new_contract="B",
                )
            ],
            long_run_window=3,
        )
    )

    jan2 = next(
        point
        for point in result
        if point.as_of_date
        == date(2026, 1, 2)
    )

    jan3 = next(
        point
        for point in result
        if point.as_of_date
        == date(2026, 1, 3)
    )

    assert jan2.active_contract == "A"
    assert jan3.active_contract == "B"