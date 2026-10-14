import math


def update_account_value(
    previous_account_value: float,
    net_pnl: float,
) -> float:
    if not math.isfinite(previous_account_value):
        raise ValueError(
            "previous_account_value must be a finite number."
        )

    if not math.isfinite(net_pnl):
        raise ValueError(
            "net_pnl must be a finite number."
        )

    return previous_account_value + net_pnl