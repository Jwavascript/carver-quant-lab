import math
from carver_quant.fx import convert_to_base_currency

def calculate_commission(
    filled_quantity: int,
    commission_per_contract: float,
) -> float:
    if filled_quantity == 0:
        raise ValueError("filled_quantity must not be zero.")

    if not math.isfinite(commission_per_contract):
        raise ValueError(
            "commission_per_contract must be a finite number."
        )

    if commission_per_contract < 0:
        raise ValueError(
            "commission_per_contract must be greater than or equal to 0."
        )

    return abs(filled_quantity) * commission_per_contract

def calculate_execution_price_cost(
    filled_quantity: int,
    fill_price: float,
    mid_price: float,
    multiplier: float,
) -> float:
    if filled_quantity == 0:
        raise ValueError(
            "filled_quantity must be non-zero."
        )

    values = [
        fill_price,
        mid_price,
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

    if filled_quantity > 0:
        execution_price_points = fill_price - mid_price

        if execution_price_points < 0:
            raise ValueError(
                "BUY fill price must not be below mid price."
            )

    else:
        execution_price_points = mid_price - fill_price

        if execution_price_points < 0:
            raise ValueError(
                "SELL fill price must not be above mid price."
            )

    return (
        execution_price_points
        * multiplier
        * abs(filled_quantity)
    )

def calculate_spread_cost(
    filled_quantity: int,
    fill_price: float,
    mid_price: float,
    multiplier: float,
) -> float:
    return calculate_execution_price_cost(
        filled_quantity=filled_quantity,
        fill_price=fill_price,
        mid_price=mid_price,
        multiplier=multiplier,
    )

def calculate_total_trading_cost(
    filled_quantity: int,
    fill_price: float,
    mid_price: float,
    multiplier: float,
    commission_per_contract: float,
    fx_to_base: float = 1.0,
) -> float:
    commission = calculate_commission(
        filled_quantity=filled_quantity,
        commission_per_contract=commission_per_contract,
    )

    execution_price_cost = calculate_execution_price_cost(
        filled_quantity=filled_quantity,
        fill_price=fill_price,
        mid_price=mid_price,
        multiplier=multiplier,
    )

    total_cost_instrument_currency = (
        commission
        + execution_price_cost
    )

    return convert_to_base_currency(
        amount_instrument_currency=total_cost_instrument_currency,
        fx_to_base=fx_to_base,
    )