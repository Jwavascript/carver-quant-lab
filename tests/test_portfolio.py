import pytest

from carver_quant.portfolio import (
    PortfolioSpec,
    calculate_instrument_cash_vol_target,
)
from carver_quant.position import (
    calculate_target_position,
)


def test_two_instrument_portfolio_spec():
    spec = PortfolioSpec(
        instrument_weights={
            "ES": 0.5,
            "ZN": 0.5,
        },
        instrument_diversification_multiplier=1.2,
    )

    assert sum(
        spec.instrument_weights.values()
    ) == pytest.approx(1.0)


def test_instrument_cash_vol_target_includes_weight_and_idm():
    result = (
        calculate_instrument_cash_vol_target(
            account_daily_cash_vol_target=1000.0,
            instrument_weight=0.5,
            instrument_diversification_multiplier=1.2,
        )
    )

    assert result == pytest.approx(
        600.0
    )


def test_portfolio_sizing_is_equivalent_to_carver_formula():
    instrument_target = (
        calculate_instrument_cash_vol_target(
            account_daily_cash_vol_target=1000.0,
            instrument_weight=0.5,
            instrument_diversification_multiplier=1.2,
        )
    )

    position = calculate_target_position(
        daily_cash_vol_target=instrument_target,
        price_volatility=2.0,
        multiplier=10.0,
        forecast=10.0,
    )

    # subsystem:
    # 1000 / (2 × 10) = 50 contracts
    #
    # portfolio:
    # 50 × 0.5 × 1.2 = 30
    assert position == 30


def test_portfolio_weights_must_sum_to_one():
    with pytest.raises(
        ValueError,
        match="sum to 1",
    ):
        PortfolioSpec(
            instrument_weights={
                "ES": 0.5,
                "ZN": 0.4,
            },
            instrument_diversification_multiplier=1.2,
        )