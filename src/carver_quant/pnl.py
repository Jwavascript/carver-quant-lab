import math
from carver_quant.fx import convert_to_base_currency

def calculate_gross_pnl(
    position_held: int,
    previous_price: float,
    current_price: float,
    multiplier: float,
    fx_to_base: float = 1.0,
) -> float:
    values = [
        previous_price,
        current_price,
        multiplier,
    ]

    if not all(math.isfinite(value) for value in values):
        raise ValueError(
            "Prices and multiplier must be finite."
        )

    if multiplier <= 0:
        raise ValueError(
            "multiplier must be positive."
        )

    gross_pnl_instrument_currency = (
        position_held
        * (current_price - previous_price)
        * multiplier
    )

    return convert_to_base_currency(
        amount_instrument_currency=gross_pnl_instrument_currency,
        fx_to_base=fx_to_base,
    )

def calculate_net_pnl(
    gross_pnl: float,
    total_trading_cost: float,
) -> float:
    if not math.isfinite(gross_pnl):
        raise ValueError("gross_pnl must be a finite number.")

    if not math.isfinite(total_trading_cost):
        raise ValueError(
            "total_trading_cost must be a finite number."
        )

    if total_trading_cost < 0:
        raise ValueError(
            "total_trading_cost must be greater than or equal to 0."
        )

    return gross_pnl - total_trading_cost