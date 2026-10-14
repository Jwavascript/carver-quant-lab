import math


def calculate_annual_cash_vol_target(
    capital: float,
    annual_volatility_target: float,
) -> float:
    if not math.isfinite(capital):
        raise ValueError(
            "capital must be finite."
        )

    if capital <= 0:
        raise ValueError(
            "capital must be positive."
        )

    if not math.isfinite(
        annual_volatility_target
    ):
        raise ValueError(
            "annual_volatility_target "
            "must be finite."
        )

    if annual_volatility_target <= 0:
        raise ValueError(
            "annual_volatility_target "
            "must be positive."
        )

    return (
        capital
        * annual_volatility_target
    )


def calculate_daily_cash_vol_target(
    capital: float,
    annual_volatility_target: float,
    trading_days_per_year: int = 256,
) -> float:
    if (
        not isinstance(
            trading_days_per_year,
            int,
        )
        or isinstance(
            trading_days_per_year,
            bool,
        )
        or trading_days_per_year <= 0
    ):
        raise ValueError(
            "trading_days_per_year "
            "must be a positive integer."
        )

    annual_cash_target = (
        calculate_annual_cash_vol_target(
            capital=capital,
            annual_volatility_target=(
                annual_volatility_target
            ),
        )
    )

    return (
        annual_cash_target
        / math.sqrt(
            trading_days_per_year
        )
    )