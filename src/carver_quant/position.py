import math

from carver_quant.fx import (
    convert_to_base_currency,
)


def round_half_away_from_zero(
    value: float,
) -> int:
    if value >= 0:
        return math.floor(
            value + 0.5
        )

    return math.ceil(
        value - 0.5
    )


def _validate_position_risk_inputs(
    daily_cash_vol_target: float,
    price_volatility: float,
    multiplier: float,
) -> None:
    values = [
        daily_cash_vol_target,
        price_volatility,
        multiplier,
    ]

    if not all(
        math.isfinite(value)
        for value in values
    ):
        raise ValueError(
            "Inputs must be finite."
        )

    if daily_cash_vol_target <= 0:
        raise ValueError(
            "daily_cash_vol_target "
            "must be positive."
        )

    if price_volatility <= 0:
        raise ValueError(
            "price_volatility "
            "must be positive."
        )

    if multiplier <= 0:
        raise ValueError(
            "multiplier must be positive."
        )


def calculate_average_position(
    daily_cash_vol_target: float,
    price_volatility: float,
    multiplier: float,
    fx_to_base: float = 1.0,
) -> float:
    _validate_position_risk_inputs(
        daily_cash_vol_target=(
            daily_cash_vol_target
        ),
        price_volatility=(
            price_volatility
        ),
        multiplier=multiplier,
    )

    instrument_value_volatility_instrument_currency = (
        price_volatility
        * multiplier
    )

    instrument_value_volatility_base_currency = (
        convert_to_base_currency(
            amount_instrument_currency=(
                instrument_value_volatility_instrument_currency
            ),
            fx_to_base=fx_to_base,
        )
    )

    average_position = (
        daily_cash_vol_target
        / instrument_value_volatility_base_currency
    )

    return average_position


def calculate_unrounded_target_position(
    daily_cash_vol_target: float,
    price_volatility: float,
    multiplier: float,
    forecast: float,
    fx_to_base: float = 1.0,
) -> float:
    if not math.isfinite(
        forecast
    ):
        raise ValueError(
            "Inputs must be finite."
        )

    average_position = (
        calculate_average_position(
            daily_cash_vol_target=(
                daily_cash_vol_target
            ),
            price_volatility=(
                price_volatility
            ),
            multiplier=multiplier,
            fx_to_base=fx_to_base,
        )
    )

    unrounded_target = (
        average_position
        * forecast
        / 10.0
    )

    return unrounded_target


def calculate_target_position(
    daily_cash_vol_target: float,
    price_volatility: float,
    multiplier: float,
    forecast: float,
    fx_to_base: float = 1.0,
) -> int:
    unrounded_target = (
        calculate_unrounded_target_position(
            daily_cash_vol_target=(
                daily_cash_vol_target
            ),
            price_volatility=(
                price_volatility
            ),
            multiplier=multiplier,
            forecast=forecast,
            fx_to_base=fx_to_base,
        )
    )

    return round_half_away_from_zero(
        unrounded_target
    )