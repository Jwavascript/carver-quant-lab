from dataclasses import dataclass
import math


@dataclass(frozen=True)
class PortfolioSpec:
    instrument_weights: dict[str, float]
    instrument_diversification_multiplier: float

    def __post_init__(self) -> None:
        if not self.instrument_weights:
            raise ValueError(
                "instrument_weights must not be empty."
            )

        for symbol, weight in (
            self.instrument_weights.items()
        ):
            if not symbol.strip():
                raise ValueError(
                    "instrument symbol must not be empty."
                )

            if not math.isfinite(weight):
                raise ValueError(
                    "instrument weight must be finite."
                )

            if weight <= 0:
                raise ValueError(
                    "instrument weight must be positive."
                )

        total_weight = sum(
            self.instrument_weights.values()
        )

        if not math.isclose(
            total_weight,
            1.0,
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            raise ValueError(
                "instrument weights must sum to 1."
            )

        idm = (
            self.instrument_diversification_multiplier
        )

        if not math.isfinite(idm):
            raise ValueError(
                "IDM must be finite and positive."
            )

        if idm <= 0:
            raise ValueError(
                "IDM must be positive."
            )


def calculate_instrument_cash_vol_target(
    account_daily_cash_vol_target: float,
    instrument_weight: float,
    instrument_diversification_multiplier: float,
) -> float:
    values = [
        account_daily_cash_vol_target,
        instrument_weight,
        instrument_diversification_multiplier,
    ]

    if not all(
        math.isfinite(value)
        for value in values
    ):
        raise ValueError(
            "portfolio sizing inputs must be finite."
        )

    if account_daily_cash_vol_target <= 0:
        raise ValueError(
            "account_daily_cash_vol_target "
            "must be positive."
        )

    if instrument_weight <= 0:
        raise ValueError(
            "instrument_weight must be positive."
        )

    if instrument_diversification_multiplier <= 0:
        raise ValueError(
            "IDM must be positive."
        )

    return (
        account_daily_cash_vol_target
        * instrument_weight
        * instrument_diversification_multiplier
    )