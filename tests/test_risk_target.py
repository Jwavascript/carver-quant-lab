import pytest

from carver_quant.risk_target import (
    calculate_annual_cash_vol_target,
    calculate_daily_cash_vol_target,
)


def test_annual_cash_vol_target():
    result = (
        calculate_annual_cash_vol_target(
            capital=100_000.0,
            annual_volatility_target=0.20,
        )
    )

    assert result == pytest.approx(
        20_000.0
    )


def test_daily_cash_vol_target_uses_square_root_of_time():
    result = (
        calculate_daily_cash_vol_target(
            capital=100_000.0,
            annual_volatility_target=0.20,
            trading_days_per_year=256,
        )
    )

    assert result == pytest.approx(
        1_250.0
    )


def test_daily_cash_vol_target_changes_with_capital():
    before = (
        calculate_daily_cash_vol_target(
            capital=100_000.0,
            annual_volatility_target=0.20,
        )
    )

    after = (
        calculate_daily_cash_vol_target(
            capital=110_000.0,
            annual_volatility_target=0.20,
        )
    )

    assert before == pytest.approx(
        1_250.0
    )

    assert after == pytest.approx(
        1_375.0
    )


def test_invalid_volatility_target_is_rejected():
    with pytest.raises(
        ValueError,
        match="positive",
    ):
        calculate_daily_cash_vol_target(
            capital=100_000.0,
            annual_volatility_target=0.0,
        )