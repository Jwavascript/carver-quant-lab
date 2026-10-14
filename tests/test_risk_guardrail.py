import pytest

from carver_quant.risk_guardrail import (
    PortfolioRiskPolicy,
    calculate_contract_notional_base,
    calculate_margin_required,
    calculate_portfolio_risk_snapshot,
    calculate_position_notional_base,
    validate_risk_snapshot,
)

def test_contract_notional_in_base_currency():
    result = (
        calculate_contract_notional_base(
            price=5000.0,
            multiplier=5.0,
            fx_to_base=1.0,
        )
    )

    assert result == pytest.approx(
        25_000.0
    )


def test_position_notional_uses_absolute_position():
    long_result = (
        calculate_position_notional_base(
            position=4,
            price=5000.0,
            multiplier=5.0,
            fx_to_base=1.0,
        )
    )

    short_result = (
        calculate_position_notional_base(
            position=-4,
            price=5000.0,
            multiplier=5.0,
            fx_to_base=1.0,
        )
    )

    assert long_result == pytest.approx(
        100_000.0
    )

    assert short_result == pytest.approx(
        100_000.0
    )


def test_negative_futures_price_can_produce_notional():
    result = (
        calculate_contract_notional_base(
            price=-20.0,
            multiplier=1000.0,
            fx_to_base=1.0,
        )
    )

    assert result == pytest.approx(
        20_000.0
    )


def test_margin_required_uses_absolute_position():
    result = calculate_margin_required(
        position=-4,
        margin_per_contract_base=3000.0,
    )

    assert result == pytest.approx(
        12_000.0
    )


def test_portfolio_risk_snapshot():
    snapshot = (
        calculate_portfolio_risk_snapshot(
            account_value=100_000.0,
            notionals=[
                80_000.0,
                40_000.0,
            ],
            margins=[
                10_000.0,
                5_000.0,
            ],
        )
    )

    assert (
        snapshot.gross_notional_exposure
        == pytest.approx(120_000.0)
    )

    assert (
        snapshot.gross_leverage
        == pytest.approx(1.2)
    )

    assert (
        snapshot.margin_required
        == pytest.approx(15_000.0)
    )

    assert (
        snapshot.margin_usage
        == pytest.approx(0.15)
    )


def test_risk_policy_rejects_excess_margin():
    snapshot = (
        calculate_portfolio_risk_snapshot(
            account_value=100_000.0,
            notionals=[
                100_000.0,
            ],
            margins=[
                65_000.0,
            ],
        )
    )

    policy = PortfolioRiskPolicy(
        max_gross_leverage=3.0,
        max_margin_usage=0.60,
    )

    with pytest.raises(
        ValueError,
        match="Margin usage",
    ):
        validate_risk_snapshot(
            snapshot=snapshot,
            policy=policy,
        )