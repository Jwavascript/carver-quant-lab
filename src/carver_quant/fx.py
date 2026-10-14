import math


def convert_to_base_currency(
    amount_instrument_currency: float,
    fx_to_base: float,
) -> float:
    if not math.isfinite(amount_instrument_currency):
        raise ValueError(
            "amount_instrument_currency must be finite."
        )

    if not math.isfinite(fx_to_base):
        raise ValueError(
            "fx_to_base must be finite and positive."
        )

    if fx_to_base <= 0:
        raise ValueError(
            "fx_to_base must be positive."
        )

    return amount_instrument_currency * fx_to_base