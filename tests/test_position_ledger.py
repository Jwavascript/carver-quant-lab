from carver_quant.position_ledger import apply_fill


def test_apply_buy_fill():
    result = apply_fill(
        current_position=2,
        filled_quantity=3,
    )

    assert result == 5


def test_apply_sell_fill():
    result = apply_fill(
        current_position=5,
        filled_quantity=-3,
    )

    assert result == 2


def test_apply_partial_fill():
    result = apply_fill(
        current_position=2,
        filled_quantity=2,
    )

    assert result == 4


def test_apply_reversal_fill():
    result = apply_fill(
        current_position=-4,
        filled_quantity=5,
    )

    assert result == 1