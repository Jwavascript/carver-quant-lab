import math
import pytest

from carver_quant.performance import (
    calculate_afts_turnover,
    calculate_annualised_mean_return,
    calculate_annualised_volatility,
    calculate_drawdowns,
    calculate_instrument_attribution,
    calculate_sharpe_ratio,
    calculate_systematic_trading_turnover,
    summarise_portfolio_performance,
)
def test_annualised_mean_return():
    daily_returns = [
        0.01,
        0.02,
        0.03,
    ]

    result = (
        calculate_annualised_mean_return(
            daily_returns
        )
    )

    # daily mean = 0.02
    # annualised = 0.02 × 256
    assert result == pytest.approx(
        5.12
    )

def test_annualised_volatility():
    daily_returns = [
        0.01,
        0.02,
        0.03,
    ]

    result = (
        calculate_annualised_volatility(
            daily_returns
        )
    )

    # sample std = 0.01
    # annualised = 0.01 × 16
    assert result == pytest.approx(
        0.16
    )

def test_sharpe_ratio():
    daily_returns = [
        0.01,
        0.02,
        0.03,
    ]

    result = (
        calculate_sharpe_ratio(
            daily_returns
        )
    )

    # 5.12 / 0.16 = 32
    assert result == pytest.approx(
        32.0
    )

def test_drawdowns():
    result = calculate_drawdowns(
        [
            100.0,
            110.0,
            99.0,
            105.0,
        ]
    )

    assert result[0] == pytest.approx(
        0.0
    )

    assert result[1] == pytest.approx(
        0.0
    )

    assert result[2] == pytest.approx(
        -0.10
    )

    assert result[3] == pytest.approx(
        -5.0 / 110.0
    )

def test_sharpe_is_none_when_volatility_is_zero():
    result = calculate_sharpe_ratio(
        [
            0.01,
            0.01,
            0.01,
        ]
    )

    assert result is None

def test_annualised_volatility_requires_two_observations():
    result = (
        calculate_annualised_volatility(
            [0.01]
        )
    )

    assert result is None

def test_afts_turnover():
    directional_trades = (
        [1] * 60
        + [0] * 196
    )

    absolute_positions = (
        [10.0] * 256
    )

    result = calculate_afts_turnover(
        directional_trades=(
            directional_trades
        ),
        absolute_positions=(
            absolute_positions
        ),
    )

    # 60 contracts / average position 10
    assert result == pytest.approx(
        6.0
    )

def test_systematic_trading_turnover_is_round_trip_based():
    directional_trades = (
        [1] * 60
        + [0] * 196
    )

    absolute_positions = (
        [10.0] * 256
    )

    result = (
        calculate_systematic_trading_turnover(
            directional_trades=(
                directional_trades
            ),
            absolute_positions=(
                absolute_positions
            ),
        )
    )

    assert result == pytest.approx(
        3.0
    )

def test_turnover_is_none_when_average_position_is_zero():
    result = calculate_afts_turnover(
        directional_trades=[
            0,
            0,
            0,
        ],
        absolute_positions=[
            0.0,
            0.0,
            0.0,
        ],
    )

    assert result is None

