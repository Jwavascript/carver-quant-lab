from carver_quant.trade import calculate_trade_quantity


def test_increase_long_position():
    result = calculate_trade_quantity(
        target_position=5,
        current_position=2,
    )

    assert result == 3

def test_reduce_long_position():
    result = calculate_trade_quantity(
        target_position=2,
        current_position=5,
    )

    assert result == -3


def test_increase_short_position():
    result = calculate_trade_quantity(
        target_position=-5,
        current_position=-2,
    )

    assert result == -3


def test_reduce_short_position():
    result = calculate_trade_quantity(
        target_position=-2,
        current_position=-5,
    )

    assert result == 3


def test_reverse_long_to_short():
    result = calculate_trade_quantity(
        target_position=-3,
        current_position=4,
    )

    assert result == -7


def test_no_trade_when_target_equals_current():
    result = calculate_trade_quantity(
        target_position=6,
        current_position=6,
    )

    assert result == 0