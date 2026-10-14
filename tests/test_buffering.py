import pytest

from carver_quant.buffering import (
    calculate_buffered_position,
)


def test_carver_buffer_example_no_trade():
    result = calculate_buffered_position(
        current_position=12,
        optimal_unrounded_position=13.2,
        average_position=8.8,
        buffer_fraction=0.10,
    )

    assert result.buffer_width == pytest.approx(
        0.88
    )

    assert result.lower_position == 12
    assert result.upper_position == 14

    assert result.target_position == 12
    assert result.trade == 0

def test_position_below_buffer_trades_to_lower_edge():
    result = calculate_buffered_position(
        current_position=10,
        optimal_unrounded_position=13.2,
        average_position=8.8,
    )

    assert result.lower_position == 12
    assert result.target_position == 12
    assert result.trade == 2

def test_position_above_buffer_trades_to_upper_edge():
    result = calculate_buffered_position(
        current_position=16,
        optimal_unrounded_position=13.2,
        average_position=8.8,
    )

    assert result.upper_position == 14
    assert result.target_position == 14
    assert result.trade == -2

def test_buffer_works_for_short_position():
    result = calculate_buffered_position(
        current_position=-16,
        optimal_unrounded_position=-13.2,
        average_position=8.8,
    )

    assert result.lower_position == -14
    assert result.upper_position == -12

    assert result.target_position == -14
    assert result.trade == 2