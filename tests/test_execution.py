import math
import pytest

from carver_quant.execution import (
    Fill,
    execute_market_order,
    validate_market_order,
    validate_price_on_tick,
    apply_slippage,
)


def test_market_buy_fills_at_ask():
    fill = execute_market_order(
        requested_trade=3,
        bid=99.5,
        ask=100.5,
    )

    assert fill.quantity == 3
    assert fill.price == 100.5

def test_market_sell_fills_at_bid():
    fill = execute_market_order(
        requested_trade=-4,
        bid=99.5,
        ask=100.5,
    )

    assert fill.quantity == -4
    assert fill.price == 99.5

def test_zero_trade_raises_value_error():
    with pytest.raises(ValueError):
        execute_market_order(
            requested_trade=0,
            bid=99.5,
            ask=100.5,
        )

def test_bid_greater_than_ask_raises_value_error():
    with pytest.raises(ValueError):
        execute_market_order(
            requested_trade=1,
            bid=101.0,
            ask=100.0,
        )


def test_nan_bid_raises_value_error():
    with pytest.raises(ValueError):
        execute_market_order(
            requested_trade=-1,
            bid=math.nan,
            ask=100.0,
        )


def test_infinite_ask_raises_value_error():
    with pytest.raises(ValueError):
        execute_market_order(
            requested_trade=1,
            bid=99.0,
            ask=math.inf,
        )

def test_price_on_tick_is_valid():
    validate_price_on_tick(
        price=100.50,
        tick_size=0.25,
    )


def test_price_off_tick_raises_value_error():
    with pytest.raises(ValueError):
        validate_price_on_tick(
            price=100.10,
            tick_size=0.25,
        )

def test_market_order_rejects_off_tick_quote():
    with pytest.raises(ValueError):
        execute_market_order(
            requested_trade=1,
            bid=100.00,
            ask=100.10,
            tick_size=0.25,
        )

def test_zero_tick_size_raises_value_error():
    with pytest.raises(ValueError):
        validate_price_on_tick(
            price=100.0,
            tick_size=0.0,
        )


def test_negative_tick_size_raises_value_error():
    with pytest.raises(ValueError):
        validate_price_on_tick(
            price=100.0,
            tick_size=-0.25,
        )


def test_infinite_tick_size_raises_value_error():
    with pytest.raises(ValueError):
        validate_price_on_tick(
            price=100.0,
            tick_size=math.inf,
        )

def test_validate_market_order_rejects_invalid_bid_ask():
    with pytest.raises(ValueError):
        validate_market_order(
            requested_trade=10,
            bid=101.1,
            ask=100.9,
            tick_size=0.1,
        )

def test_apply_slippage_to_buy_fill():
    actual_fill_price = apply_slippage(
        reference_fill_price=100.1,
        quantity=10,
        slippage_ticks=1,
        tick_size=0.1,
    )

    assert actual_fill_price == pytest.approx(100.2)

def test_apply_slippage_to_sell_fill():
    actual_fill_price = apply_slippage(
        reference_fill_price=99.9,
        quantity=-10,
        slippage_ticks=1,
        tick_size=0.1,
    )

    assert actual_fill_price == pytest.approx(99.8)

def test_apply_zero_slippage_keeps_buy_fill_unchanged():
    actual_fill_price = apply_slippage(
        reference_fill_price=100.1,
        quantity=10,
        slippage_ticks=0,
        tick_size=0.1,
    )

    assert actual_fill_price == pytest.approx(100.1)

def test_apply_zero_slippage_keeps_sell_fill_unchanged():
    actual_fill_price = apply_slippage(
        reference_fill_price=99.9,
        quantity=-10,
        slippage_ticks=0,
        tick_size=0.1,
    )

    assert actual_fill_price == pytest.approx(99.9)

def test_apply_slippage_rejects_negative_slippage_ticks():
    with pytest.raises(
        ValueError,
        match="slippage_ticks must be non-negative.",
    ):
        apply_slippage(
            reference_fill_price=100.1,
            quantity=10,
            slippage_ticks=-1,
            tick_size=0.1,
        )

def test_apply_slippage_rejects_non_positive_tick_size():
    with pytest.raises(
        ValueError,
        match="tick_size must be positive.",
    ):
        apply_slippage(
            reference_fill_price=100.1,
            quantity=10,
            slippage_ticks=1,
            tick_size=0.0,
        )

def test_apply_slippage_rejects_zero_quantity():
    with pytest.raises(
        ValueError,
        match="quantity must be non-zero.",
    ):
        apply_slippage(
            reference_fill_price=100.1,
            quantity=0,
            slippage_ticks=1,
            tick_size=0.1,
        )

def test_apply_slippage_rejects_nan_reference_fill_price():
    with pytest.raises(
        ValueError,
        match="reference_fill_price must be finite.",
    ):
        apply_slippage(
            reference_fill_price=float("nan"),
            quantity=10,
            slippage_ticks=1,
            tick_size=0.1,
        )

def test_apply_slippage_rejects_nan_tick_size():
    with pytest.raises(
        ValueError,
        match="tick_size must be finite and positive.",
    ):
        apply_slippage(
            reference_fill_price=100.1,
            quantity=10,
            slippage_ticks=1,
            tick_size=float("nan"),
        )

def test_apply_slippage_rejects_fractional_slippage_ticks():
    with pytest.raises(
        ValueError,
        match="slippage_ticks must be an integer.",
    ):
        apply_slippage(
            reference_fill_price=100.1,
            quantity=10,
            slippage_ticks=0.5,
            tick_size=0.1,
        )

def test_execute_market_order_applies_buy_slippage():
    fill = execute_market_order(
        requested_trade=10,
        bid=99.9,
        ask=100.1,
        tick_size=0.1,
        slippage_ticks=1,
    )

    assert fill.quantity == 10
    assert fill.price == pytest.approx(100.2)

def test_execute_market_order_applies_sell_slippage():
    fill = execute_market_order(
        requested_trade=-10,
        bid=99.9,
        ask=100.1,
        tick_size=0.1,
        slippage_ticks=1,
    )

    assert fill.quantity == -10
    assert fill.price == pytest.approx(99.8)

def test_execute_market_order_rejects_negative_slippage_before_missing_tick_size():
    with pytest.raises(
        ValueError,
        match="slippage_ticks must be non-negative.",
    ):
        execute_market_order(
            requested_trade=10,
            bid=99.9,
            ask=100.1,
            tick_size=None,
            slippage_ticks=-1,
        )

def test_execute_market_order_rejects_fractional_slippage_before_missing_tick_size():
    with pytest.raises(
        ValueError,
        match="slippage_ticks must be an integer.",
    ):
        execute_market_order(
            requested_trade=10,
            bid=99.9,
            ask=100.1,
            tick_size=None,
            slippage_ticks=0.5,
        )