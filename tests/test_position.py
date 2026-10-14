from carver_quant.position import calculate_target_position
import math
import pytest

def test_target_position_long():
    result = calculate_target_position(
        daily_cash_vol_target=600.0,
        price_volatility=3.0,
        multiplier=10.0,
        forecast=10.0,
    )

    assert result == 20


def test_target_position_short():
    result = calculate_target_position(
        daily_cash_vol_target=600.0,
        price_volatility=2.0,
        multiplier=10.0,
        forecast=-10.0,
    )

    assert result == -30

def test_round_half_away_from_zero_positive():
    result = calculate_target_position(
        daily_cash_vol_target=25.0,
        price_volatility=1.0,
        multiplier=10.0,
        forecast=10.0,
    )

    assert result == 3

def test_round_half_away_from_zero_negative():
    result = calculate_target_position(
        daily_cash_vol_target=25.0,
        price_volatility=1.0,
        multiplier=10.0,
        forecast=-10.0,
    )

    assert result == -3

def test_zero_price_volatility_raises_value_error():
    with pytest.raises(ValueError):
        calculate_target_position(
            daily_cash_vol_target=600.0,
            price_volatility=0.0,
            multiplier=10.0,
            forecast=10.0,
        )


def test_negative_price_volatility_raises_value_error():
    with pytest.raises(ValueError):
        calculate_target_position(
            daily_cash_vol_target=600.0,
            price_volatility=-2.0,
            multiplier=10.0,
            forecast=10.0,
        )


def test_zero_multiplier_raises_value_error():
    with pytest.raises(ValueError):
        calculate_target_position(
            daily_cash_vol_target=600.0,
            price_volatility=2.0,
            multiplier=0.0,
            forecast=10.0,
        )


def test_nan_forecast_raises_value_error():
    with pytest.raises(ValueError):
        calculate_target_position(
            daily_cash_vol_target=600.0,
            price_volatility=2.0,
            multiplier=10.0,
            forecast=math.nan,
        )

def test_zero_forecast_returns_zero():
    result = calculate_target_position(
        daily_cash_vol_target=600.0,
        price_volatility=2.0,
        multiplier=10.0,
        forecast=0.0,
    )

    assert result == 0


def test_zero_daily_cash_vol_target_raises_value_error():
    with pytest.raises(ValueError):
        calculate_target_position(
            daily_cash_vol_target=0.0,
            price_volatility=2.0,
            multiplier=10.0,
            forecast=10.0,
        )


def test_negative_multiplier_raises_value_error():
    with pytest.raises(ValueError):
        calculate_target_position(
            daily_cash_vol_target=600.0,
            price_volatility=2.0,
            multiplier=-10.0,
            forecast=10.0,
        )


def test_nan_price_volatility_raises_value_error():
    with pytest.raises(ValueError):
        calculate_target_position(
            daily_cash_vol_target=600.0,
            price_volatility=math.nan,
            multiplier=10.0,
            forecast=10.0,
        )


def test_infinite_forecast_raises_value_error():
    with pytest.raises(ValueError):
        calculate_target_position(
            daily_cash_vol_target=600.0,
            price_volatility=2.0,
            multiplier=10.0,
            forecast=math.inf,
        )

def test_calculate_target_position_converts_usd_risk_to_krw():
    target_position = calculate_target_position(
        daily_cash_vol_target=810000.0,
        price_volatility=3.0,
        multiplier=10.0,
        forecast=10.0,
        fx_to_base=1350.0,
    )

    assert target_position == 20