import math
from dataclasses import dataclass


def validate_price_on_tick(
    price: float,
    tick_size: float,
) -> None:
    if not math.isfinite(tick_size):
        raise ValueError("tick_size must be a finite number.")

    if tick_size <= 0:
        raise ValueError("tick_size must be greater than 0.")

    tick_count = price / tick_size
    nearest_tick_count = round(tick_count)

    if not math.isclose(
        tick_count,
        nearest_tick_count,
        rel_tol=0.0,
        abs_tol=1e-9,
    ):
        raise ValueError(
            "price must be aligned with tick_size."
        )


@dataclass(frozen=True)
class Fill:
    quantity: int
    price: float

def validate_market_order(
    requested_trade: int,
    bid: float,
    ask: float,
    tick_size: float | None = None,
) -> None:
    if requested_trade == 0:
        raise ValueError("requested_trade must not be zero.")

    if not math.isfinite(bid):
        raise ValueError("bid must be a finite number.")

    if not math.isfinite(ask):
        raise ValueError("ask must be a finite number.")

    if bid > ask:
        raise ValueError("bid must be less than or equal to ask.")

    if tick_size is not None:
        validate_price_on_tick(
            price=bid,
            tick_size=tick_size,
        )
        validate_price_on_tick(
            price=ask,
            tick_size=tick_size,
        )

def execute_market_order(
    requested_trade: int,
    bid: float,
    ask: float,
    tick_size: float | None = None,
    slippage_ticks: int = 0,
) -> Fill:
    if not isinstance(slippage_ticks, int):
        raise ValueError(
            "slippage_ticks must be an integer."
        )

    if slippage_ticks < 0:
        raise ValueError(
            "slippage_ticks must be non-negative."
        )

    validate_market_order(
        requested_trade=requested_trade,
        bid=bid,
        ask=ask,
        tick_size=tick_size,
    )

    if requested_trade > 0:
        reference_fill_price = ask
    else:
        reference_fill_price = bid

    if slippage_ticks == 0:
        fill_price = reference_fill_price
    else:
        if tick_size is None:
            raise ValueError(
                "tick_size is required when slippage_ticks is non-zero."
            )

        fill_price = apply_slippage(
            reference_fill_price=reference_fill_price,
            quantity=requested_trade,
            slippage_ticks=slippage_ticks,
            tick_size=tick_size,
        )

    return Fill(
        quantity=requested_trade,
        price=fill_price,
    )

def apply_slippage(
    reference_fill_price: float,
    quantity: int,
    slippage_ticks: int,
    tick_size: float,
) -> float:
    if not math.isfinite(reference_fill_price):
        raise ValueError(
            "reference_fill_price must be finite."
        )

    if not isinstance(slippage_ticks, int):
        raise ValueError(
            "slippage_ticks must be an integer."
        )

    if slippage_ticks < 0:
        raise ValueError(
            "slippage_ticks must be non-negative."
        )

    if not math.isfinite(tick_size):
        raise ValueError(
            "tick_size must be finite and positive."
        )

    if tick_size <= 0:
        raise ValueError(
            "tick_size must be positive."
        )

    slippage_amount = slippage_ticks * tick_size

    if quantity > 0:
        return reference_fill_price + slippage_amount

    if quantity < 0:
        return reference_fill_price - slippage_amount

    raise ValueError(
        "quantity must be non-zero."
    )