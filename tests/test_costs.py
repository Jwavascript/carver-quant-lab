import math
import pytest

from carver_quant.costs import (
    calculate_commission,
    calculate_spread_cost,
    calculate_execution_price_cost,
    calculate_total_trading_cost,
)

def test_commission_for_buy_fill():
    result = calculate_commission(
        filled_quantity=3,
        commission_per_contract=1.5,
    )

    assert result == 4.5

def test_commission_for_sell_fill():
    result = calculate_commission(
        filled_quantity=-4,
        commission_per_contract=1.5,
    )

    assert result == 6.0

def test_zero_fill_quantity_raises_value_error():
    with pytest.raises(ValueError):
        calculate_commission(
            filled_quantity=0,
            commission_per_contract=1.5,
        )


def test_negative_commission_rate_raises_value_error():
    with pytest.raises(ValueError):
        calculate_commission(
            filled_quantity=3,
            commission_per_contract=-1.0,
        )


def test_nan_commission_rate_raises_value_error():
    with pytest.raises(ValueError):
        calculate_commission(
            filled_quantity=3,
            commission_per_contract=math.nan,
        )


def test_infinite_commission_rate_raises_value_error():
    with pytest.raises(ValueError):
        calculate_commission(
            filled_quantity=3,
            commission_per_contract=math.inf,
        )

def test_spread_cost_for_buy_fill():
    result = calculate_spread_cost(
        filled_quantity=3,
        fill_price=100.5,
        mid_price=100.0,
        multiplier=20.0,
    )

    assert result == 30.0

def test_spread_cost_for_sell_fill():
    result = calculate_spread_cost(
        filled_quantity=-4,
        fill_price=99.5,
        mid_price=100.0,
        multiplier=20.0,
    )

    assert result == 40.0

def test_zero_fill_quantity_for_spread_raises_value_error():
    with pytest.raises(ValueError):
        calculate_spread_cost(
            filled_quantity=0,
            fill_price=100.5,
            mid_price=100.0,
            multiplier=20.0,
        )


def test_zero_multiplier_for_spread_raises_value_error():
    with pytest.raises(ValueError):
        calculate_spread_cost(
            filled_quantity=3,
            fill_price=100.5,
            mid_price=100.0,
            multiplier=0.0,
        )


def test_negative_multiplier_for_spread_raises_value_error():
    with pytest.raises(ValueError):
        calculate_spread_cost(
            filled_quantity=3,
            fill_price=100.5,
            mid_price=100.0,
            multiplier=-20.0,
        )


def test_nan_fill_price_for_spread_raises_value_error():
    with pytest.raises(ValueError):
        calculate_spread_cost(
            filled_quantity=3,
            fill_price=math.nan,
            mid_price=100.0,
            multiplier=20.0,
        )


def test_infinite_mid_price_for_spread_raises_value_error():
    with pytest.raises(ValueError):
        calculate_spread_cost(
            filled_quantity=3,
            fill_price=100.5,
            mid_price=math.inf,
            multiplier=20.0,
        )


def test_buy_fill_better_than_mid_raises_value_error():
    with pytest.raises(ValueError):
        calculate_spread_cost(
            filled_quantity=3,
            fill_price=99.5,
            mid_price=100.0,
            multiplier=20.0,
        )


def test_sell_fill_better_than_mid_raises_value_error():
    with pytest.raises(ValueError):
        calculate_spread_cost(
            filled_quantity=-3,
            fill_price=100.5,
            mid_price=100.0,
            multiplier=20.0,
        )

def test_total_trading_cost_matches_carver_mes_example():
    result = calculate_total_trading_cost(
        filled_quantity=1,
        fill_price=4494.25,
        mid_price=4494.125,
        multiplier=5.0,
        commission_per_contract=0.25,
    )

    assert result == 0.875

def test_calculate_execution_price_cost_includes_slippage_from_mid():
    cost = calculate_execution_price_cost(
        filled_quantity=10,
        fill_price=100.2,
        mid_price=100.0,
        multiplier=10.0,
    )

    assert cost == pytest.approx(20.0)

def test_calculate_total_trading_cost_converts_usd_cost_to_krw():
    total_cost = calculate_total_trading_cost(
        filled_quantity=10,
        fill_price=100.2,
        mid_price=100.0,
        multiplier=10.0,
        commission_per_contract=1.0,
        fx_to_base=1350.0,
    )

    assert total_cost == pytest.approx(40500.0)