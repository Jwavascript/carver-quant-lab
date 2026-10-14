from datetime import date

import pytest

from carver_quant.futures_data import (
    BackAdjustedPrice,
)
from carver_quant.volatility import (
    VolatilityPoint,
    blend_price_volatility,
    calculate_carver_blended_price_volatility,
    calculate_ewma_price_volatility,
    calculate_long_run_average_volatility,
    calculate_price_changes,
)


def make_prices(values):
    return [
        BackAdjustedPrice(
            date=date(2026, 1, index + 1),
            active_contract="TEST",
            raw_price=value,
            adjusted_price=value,
        )
        for index, value in enumerate(values)
    ]


def test_calculate_price_changes():
    prices = make_prices([
        100.0,
        102.0,
        101.0,
        104.0,
    ])

    changes = calculate_price_changes(
        prices
    )

    assert changes == [
        None,
        2.0,
        -1.0,
        3.0,
    ]


def test_price_changes_are_not_percentage_returns():
    prices = make_prices([
        100.0,
        110.0,
    ])

    changes = calculate_price_changes(
        prices
    )

    assert changes == [
        None,
        10.0,
    ]


def test_negative_adjusted_prices_are_supported():
    prices = make_prices([
        -10.0,
        -8.0,
        -11.0,
    ])

    changes = calculate_price_changes(
        prices
    )

    assert changes == [
        None,
        2.0,
        -3.0,
    ]


def test_ewma_volatility_returns_same_number_of_dates():
    prices = make_prices([
        100.0,
        101.0,
        103.0,
        102.0,
    ])

    volatility = calculate_ewma_price_volatility(
        prices,
        span=32,
    )

    assert len(volatility) == 4

    assert volatility[0].price_volatility is None
    assert volatility[1].price_volatility is None

    assert (
        volatility[2].price_volatility
        is not None
    )


def test_constant_price_changes_converge_to_zero_volatility():
    prices = make_prices([
        100.0,
        100.0,
        100.0,
        100.0,
        100.0,
    ])

    volatility = calculate_ewma_price_volatility(
        prices,
        span=32,
    )

    assert volatility[-1].price_volatility == pytest.approx(
        0.0
    )


def test_variable_price_changes_have_positive_volatility():
    prices = make_prices([
        100.0,
        102.0,
        101.0,
        104.0,
        100.0,
    ])

    volatility = calculate_ewma_price_volatility(
        prices,
        span=32,
    )

    assert (
        volatility[-1].price_volatility
        > 0.0
    )


def test_invalid_span_is_rejected():
    prices = make_prices([
        100.0,
        101.0,
        102.0,
    ])

    with pytest.raises(
        ValueError,
        match="span must be at least 2",
    ):
        calculate_ewma_price_volatility(
            prices,
            span=1,
        )

def test_future_prices_do_not_change_past_volatility():
    short_prices = make_prices([
        100.0,
        102.0,
        101.0,
        103.0,
    ])

    long_prices = make_prices([
        100.0,
        102.0,
        101.0,
        103.0,
        500.0,
    ])

    short_result = calculate_ewma_price_volatility(
        short_prices,
        span=32,
    )

    long_result = calculate_ewma_price_volatility(
        long_prices,
        span=32,
    )

    for short, long in zip(
        short_result,
        long_result[:4],
    ):
        if short.price_volatility is None:
            assert long.price_volatility is None
        else:
            assert (
                long.price_volatility
                == pytest.approx(
                    short.price_volatility
                )
            )

def test_blend_price_volatility_uses_70_30_weights():
    short_run = [
        VolatilityPoint(
            date=date(2026, 1, 1),
            price_volatility=2.0,
        )
    ]

    long_run = [
        VolatilityPoint(
            date=date(2026, 1, 1),
            price_volatility=1.0,
        )
    ]

    result = blend_price_volatility(
        short_run=short_run,
        long_run=long_run,
    )

    assert result[0].price_volatility == pytest.approx(
        1.7
    )

def test_long_run_average_uses_only_available_history():
    points = [
        VolatilityPoint(
            date=date(2026, 1, 1),
            price_volatility=1.0,
        ),
        VolatilityPoint(
            date=date(2026, 1, 2),
            price_volatility=2.0,
        ),
        VolatilityPoint(
            date=date(2026, 1, 3),
            price_volatility=3.0,
        ),
    ]

    result = (
        calculate_long_run_average_volatility(
            volatility=points,
            window=2560,
        )
    )

    assert result[0].price_volatility == pytest.approx(
        1.0
    )

    assert result[1].price_volatility == pytest.approx(
        1.5
    )

    assert result[2].price_volatility == pytest.approx(
        2.0
    )

def test_carver_blend_uses_70_percent_current_and_30_percent_long_run():
    short_run = [
        VolatilityPoint(
            date=date(2026, 1, 1),
            price_volatility=4.0,
        )
    ]

    long_run = [
        VolatilityPoint(
            date=date(2026, 1, 1),
            price_volatility=2.0,
        )
    ]

    result = blend_price_volatility(
        short_run=short_run,
        long_run=long_run,
        short_weight=0.7,
    )

    # 0.7 × 4 + 0.3 × 2
    # = 3.4
    assert result[0].price_volatility == pytest.approx(
        3.4
    )

def test_future_volatility_does_not_change_past_long_run_average():
    short = [
        VolatilityPoint(
            date=date(2026, 1, 1),
            price_volatility=1.0,
        ),
        VolatilityPoint(
            date=date(2026, 1, 2),
            price_volatility=2.0,
        ),
        VolatilityPoint(
            date=date(2026, 1, 3),
            price_volatility=3.0,
        ),
    ]

    extended = short + [
        VolatilityPoint(
            date=date(2026, 1, 4),
            price_volatility=100.0,
        )
    ]

    short_result = (
        calculate_long_run_average_volatility(
            volatility=short,
            window=2560,
        )
    )

    extended_result = (
        calculate_long_run_average_volatility(
            volatility=extended,
            window=2560,
        )
    )

    for expected, actual in zip(
        short_result,
        extended_result[:3],
    ):
        assert (
            actual.price_volatility
            == pytest.approx(
                expected.price_volatility
            )
        )