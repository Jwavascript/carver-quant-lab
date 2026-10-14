from dataclasses import (
    FrozenInstanceError,
)

import math

import pytest


from carver_quant.backtest_config import (
    BacktestConfig,
)

from carver_quant.risk_guardrail import (
    PortfolioRiskPolicy,
)

def test_backtest_config_defaults_match_v1():
    config = BacktestConfig()

    assert config.fast_spans == (
        2,
        4,
        8,
        16,
        32,
        64,
    )

    assert config.volatility_span == 32

    assert config.long_run_window == 2560

    assert (
        config.annual_volatility_target
        is None
    )

    assert (
        config.position_buffer_fraction
        is None
    )

    assert config.risk_policy is None

    assert (
        config.trading_days_per_year
        == 256
    )

def test_backtest_config_is_frozen():
    config = BacktestConfig()

    with pytest.raises(
        FrozenInstanceError
    ):
        config.volatility_span = 64

def test_backtest_config_rejects_invalid_fast_spans():
    with pytest.raises(
        ValueError,
        match="must not be empty",
    ):
        BacktestConfig(
            fast_spans=(),
        )

    with pytest.raises(
        ValueError,
        match="duplicates",
    ):
        BacktestConfig(
            fast_spans=(
                2,
                4,
                4,
            ),
        )

    with pytest.raises(
        ValueError,
        match="Unsupported",
    ):
        BacktestConfig(
            fast_spans=(
                2,
                3,
                4,
            ),
        )

    with pytest.raises(
        ValueError,
        match="ascending",
    ):
        BacktestConfig(
            fast_spans=(
                8,
                4,
                2,
            ),
        )

def test_backtest_config_rejects_invalid_windows():
    with pytest.raises(
        ValueError,
        match="volatility_span",
    ):
        BacktestConfig(
            volatility_span=0,
        )

    with pytest.raises(
        ValueError,
        match="long_run_window",
    ):
        BacktestConfig(
            long_run_window=0,
        )

def test_backtest_config_rejects_invalid_risk_settings():
    with pytest.raises(
        ValueError,
        match="annual_volatility_target",
    ):
        BacktestConfig(
            annual_volatility_target=0.0,
        )

    with pytest.raises(
        ValueError,
        match="annual_volatility_target",
    ):
        BacktestConfig(
            annual_volatility_target=(
                math.nan
            ),
        )

    with pytest.raises(
        ValueError,
        match="position_buffer_fraction",
    ):
        BacktestConfig(
            position_buffer_fraction=-0.1,
        )

    policy = PortfolioRiskPolicy(
        max_gross_leverage=3.0,
        max_margin_usage=0.60,
    )

    config = BacktestConfig(
        annual_volatility_target=0.20,
        position_buffer_fraction=0.10,
        risk_policy=policy,
    )

    assert (
        config.annual_volatility_target
        == pytest.approx(0.20)
    )

    assert (
        config.position_buffer_fraction
        == pytest.approx(0.10)
    )

    assert config.risk_policy == policy

def test_backtest_config_v1_rejects_non_256_calendar():
    with pytest.raises(
        ValueError,
        match="256 trading days",
    ):
        BacktestConfig(
            trading_days_per_year=252,
        )