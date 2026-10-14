import pytest

from carver_quant.combined_forecast import (
    combine_forecast_values,
    get_afts_trend_fdm,
)


def test_full_six_rule_set_uses_afts_fdm():
    fdm = get_afts_trend_fdm(
        (
            2,
            4,
            8,
            16,
            32,
            64,
        )
    )

    assert fdm == pytest.approx(
        1.26
    )


def test_three_rule_set_uses_afts_fdm():
    fdm = get_afts_trend_fdm(
        (
            16,
            32,
            64,
        )
    )

    assert fdm == pytest.approx(
        1.08
    )


def test_invalid_rule_set_is_rejected():
    with pytest.raises(
        ValueError,
        match="Unsupported",
    ):
        get_afts_trend_fdm(
            (
                2,
                16,
                64,
            )
        )


def test_combined_forecast_is_equal_weighted_then_fdm():
    weighted, combined = (
        combine_forecast_values(
            forecasts=[
                10.0,
                20.0,
                0.0,
            ],
            fdm=1.08,
        )
    )

    # equal weight average
    # (10 + 20 + 0) / 3 = 10
    assert weighted == pytest.approx(
        10.0
    )

    # 10 × 1.08
    assert combined == pytest.approx(
        10.8
    )


def test_combined_forecast_is_capped_at_20():
    weighted, combined = (
        combine_forecast_values(
            forecasts=[
                20.0,
                20.0,
                20.0,
                20.0,
                20.0,
                20.0,
            ],
            fdm=1.26,
        )
    )

    assert weighted == pytest.approx(
        20.0
    )

    assert combined == pytest.approx(
        20.0
    )


def test_combined_forecast_is_capped_at_minus_20():
    _, combined = (
        combine_forecast_values(
            forecasts=[
                -20.0,
                -20.0,
            ],
            fdm=1.03,
        )
    )

    assert combined == pytest.approx(
        -20.0
    )