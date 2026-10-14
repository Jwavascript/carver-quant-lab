import pytest

from carver_quant.fx import convert_to_base_currency


def test_convert_usd_profit_to_krw_base_currency():
    amount_base = convert_to_base_currency(
        amount_instrument_currency=225.0,
        fx_to_base=1350.0,
    )

    assert amount_base == pytest.approx(303750.0)

def test_convert_usd_loss_to_krw_base_currency():
    amount_base = convert_to_base_currency(
        amount_instrument_currency=-225.0,
        fx_to_base=1350.0,
    )

    assert amount_base == pytest.approx(-303750.0)

def test_convert_to_base_currency_rejects_non_positive_fx_rate():
    with pytest.raises(
        ValueError,
        match="fx_to_base must be positive.",
    ):
        convert_to_base_currency(
            amount_instrument_currency=225.0,
            fx_to_base=0.0,
        )

def test_convert_to_base_currency_rejects_nan_fx_rate():
    with pytest.raises(
        ValueError,
        match="fx_to_base must be finite and positive.",
    ):
        convert_to_base_currency(
            amount_instrument_currency=225.0,
            fx_to_base=float("nan"),
        )

def test_convert_to_base_currency_rejects_nan_amount():
    with pytest.raises(
        ValueError,
        match="amount_instrument_currency must be finite.",
    ):
        convert_to_base_currency(
            amount_instrument_currency=float("nan"),
            fx_to_base=1350.0,
        )

def test_convert_same_currency_with_fx_rate_one():
    amount_base = convert_to_base_currency(
        amount_instrument_currency=303750.0,
        fx_to_base=1.0,
    )

    assert amount_base == pytest.approx(303750.0)