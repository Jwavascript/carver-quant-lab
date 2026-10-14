import math
import pytest

from carver_quant.pnl import (
    calculate_gross_pnl,
    calculate_net_pnl,
)


def test_gross_pnl_for_long_position():
    result = calculate_gross_pnl(
        position_held=3,
        previous_price=100.0,
        current_price=102.0,
        multiplier=10.0,
    )

    assert result == 60.0

def test_gross_pnl_for_short_position():
    result = calculate_gross_pnl(
        position_held=-3,
        previous_price=100.0,
        current_price=102.0,
        multiplier=10.0,
    )

    assert result == -60.0

def test_gross_pnl_for_flat_position_is_zero():
    result = calculate_gross_pnl(
        position_held=0,
        previous_price=100.0,
        current_price=105.0,
        multiplier=10.0,
    )

    assert result == 0.0


def test_gross_pnl_for_long_position_when_price_falls():
    result = calculate_gross_pnl(
        position_held=3,
        previous_price=100.0,
        current_price=98.0,
        multiplier=10.0,
    )

    assert result == -60.0


def test_gross_pnl_for_short_position_when_price_falls():
    result = calculate_gross_pnl(
        position_held=-3,
        previous_price=100.0,
        current_price=98.0,
        multiplier=10.0,
    )

    assert result == 60.0

def test_nan_previous_price_raises_value_error():
    with pytest.raises(ValueError):
        calculate_gross_pnl(
            position_held=3,
            previous_price=math.nan,
            current_price=102.0,
            multiplier=10.0,
        )


def test_infinite_current_price_raises_value_error():
    with pytest.raises(ValueError):
        calculate_gross_pnl(
            position_held=3,
            previous_price=100.0,
            current_price=math.inf,
            multiplier=10.0,
        )


def test_zero_multiplier_raises_value_error():
    with pytest.raises(ValueError):
        calculate_gross_pnl(
            position_held=3,
            previous_price=100.0,
            current_price=102.0,
            multiplier=0.0,
        )


def test_negative_multiplier_raises_value_error():
    with pytest.raises(ValueError):
        calculate_gross_pnl(
            position_held=3,
            previous_price=100.0,
            current_price=102.0,
            multiplier=-10.0,
        )

def test_net_pnl_after_trading_cost():
    result = calculate_net_pnl(
        gross_pnl=400.0,
        total_trading_cost=20.0,
    )

    assert result == 380.0

def test_net_pnl_when_gross_pnl_is_negative():
    result = calculate_net_pnl(
        gross_pnl=-300.0,
        total_trading_cost=120.0,
    )

    assert result == -420.0

def test_net_pnl_when_trading_cost_is_zero():
    result = calculate_net_pnl(
        gross_pnl=250.0,
        total_trading_cost=0.0,
    )

    assert result == 250.0

def test_negative_trading_cost_raises_value_error():
    with pytest.raises(ValueError):
        calculate_net_pnl(
            gross_pnl=100.0,
            total_trading_cost=-10.0,
        )

def test_day_8_net_pnl_includes_directional_and_roll_cost():
    gross_pnl = -200.0

    directional_trading_cost = 0.0
    roll_trading_cost = 80.0

    total_trading_cost = (
        directional_trading_cost
        + roll_trading_cost
    )

    result = calculate_net_pnl(
        gross_pnl=gross_pnl,
        total_trading_cost=total_trading_cost,
    )

    assert result == pytest.approx(-280.0)

def test_calculate_gross_pnl_converts_usd_pnl_to_krw():
    gross_pnl = calculate_gross_pnl(
        position_held=1,
        previous_price=4500.0,
        current_price=4545.0,
        multiplier=5.0,
        fx_to_base=1350.0,
    )

    assert gross_pnl == pytest.approx(303750.0)

def test_calculate_gross_pnl_converts_usd_loss_to_krw():
    gross_pnl = calculate_gross_pnl(
        position_held=1,
        previous_price=4545.0,
        current_price=4500.0,
        multiplier=5.0,
        fx_to_base=1350.0,
    )

    assert gross_pnl == pytest.approx(-303750.0)