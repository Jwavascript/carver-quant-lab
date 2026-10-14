from datetime import date

import pytest

from carver_quant.forecast import (
    calculate_ewmac_forecast,
    make_afts_ewmac_config,
    scale_and_cap_forecast,
)
from carver_quant.futures_data import (
    BackAdjustedPrice,
)
from carver_quant.volatility import (
    calculate_ewma_price_volatility,
)


def make_prices(values):
    return [
        BackAdjustedPrice(
            date=date(
                2026,
                1,
                index + 1,
            ),
            active_contract="TEST",
            raw_price=value,
            adjusted_price=value,
        )
        for index, value in enumerate(values)
    ]


def test_afts_ewmac16_config():
    config = make_afts_ewmac_config(
        16
    )

    assert config.fast_span == 16
    assert config.slow_span == 64

    assert config.forecast_scalar == pytest.approx(
        4.10
    )

    assert config.cap == pytest.approx(
        20.0
    )


def test_unsupported_afts_ewmac_speed_is_rejected():
    with pytest.raises(
        ValueError,
        match="Unsupported",
    ):
        make_afts_ewmac_config(
            10
        )


def test_scale_forecast_before_cap():
    result = scale_and_cap_forecast(
        raw_crossover=0.5,
        price_volatility=1.0,
        forecast_scalar=4.10,
    )

    risk_normalized, scaled, capped = result

    assert risk_normalized == pytest.approx(
        0.5
    )

    assert scaled == pytest.approx(
        2.05
    )

    assert capped == pytest.approx(
        2.05
    )


def test_positive_forecast_is_capped_at_20():
    result = scale_and_cap_forecast(
        raw_crossover=10.0,
        price_volatility=1.0,
        forecast_scalar=4.10,
    )

    _, scaled, capped = result

    assert scaled == pytest.approx(
        41.0
    )

    assert capped == pytest.approx(
        20.0
    )


def test_negative_forecast_is_capped_at_minus_20():
    result = scale_and_cap_forecast(
        raw_crossover=-10.0,
        price_volatility=1.0,
        forecast_scalar=4.10,
    )

    _, scaled, capped = result

    assert scaled == pytest.approx(
        -41.0
    )

    assert capped == pytest.approx(
        -20.0
    )


def test_zero_volatility_produces_no_forecast():
    result = scale_and_cap_forecast(
        raw_crossover=1.0,
        price_volatility=0.0,
        forecast_scalar=4.10,
    )

    assert result is None


def test_uptrend_produces_positive_ewmac_forecast():
    prices = make_prices([
        100.0,
        101.0,
        103.0,
        106.0,
        110.0,
        115.0,
    ])

    volatility = calculate_ewma_price_volatility(
        prices,
        span=32,
    )

    forecast = calculate_ewmac_forecast(
        adjusted_prices=prices,
        volatility=volatility,
        config=make_afts_ewmac_config(
            16
        ),
    )

    assert (
        forecast[-1].raw_crossover
        > 0.0
    )

    assert (
        forecast[-1].capped_forecast
        > 0.0
    )


def test_downtrend_produces_negative_ewmac_forecast():
    prices = make_prices([
        115.0,
        110.0,
        106.0,
        103.0,
        101.0,
        100.0,
    ])

    volatility = calculate_ewma_price_volatility(
        prices,
        span=32,
    )

    forecast = calculate_ewmac_forecast(
        adjusted_prices=prices,
        volatility=volatility,
        config=make_afts_ewmac_config(
            16
        ),
    )

    assert (
        forecast[-1].raw_crossover
        < 0.0
    )

    assert (
        forecast[-1].capped_forecast
        < 0.0
    )


def test_price_and_volatility_dates_must_match():
    prices = make_prices([
        100.0,
        101.0,
        102.0,
    ])

    volatility = calculate_ewma_price_volatility(
        prices,
        span=32,
    )

    wrong_volatility = [
        volatility[0],
        volatility[2],
        volatility[1],
    ]

    with pytest.raises(
        ValueError,
        match="dates must match",
    ):
        calculate_ewmac_forecast(
            adjusted_prices=prices,
            volatility=wrong_volatility,
            config=make_afts_ewmac_config(
                16
            ),
        )