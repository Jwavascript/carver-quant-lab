import math

from carver_quant.futures_data import (
    ContractPrice,
    RollEvent,
)
from carver_quant.system_backtest import (
    ExecutionMarketDay,
)


def validate_contract_prices(
    prices: list[ContractPrice],
) -> None:
    if not prices:
        raise ValueError(
            "Contract prices must not be empty."
        )

    seen: set[tuple] = set()

    for price in prices:
        if not price.contract.strip():
            raise ValueError(
                "Contract name must not be empty."
            )

        if not math.isfinite(
            price.close
        ):
            raise ValueError(
                "Contract price must be finite."
            )

        key = (
            price.date,
            price.contract,
        )

        if key in seen:
            raise ValueError(
                "Duplicate contract price."
            )

        seen.add(key)


def validate_roll_events(
    roll_events: list[RollEvent],
) -> None:
    seen_dates = set()
    previous_date = None

    for roll in roll_events:
        if not roll.old_contract.strip():
            raise ValueError(
                "Old contract must not be empty."
            )

        if not roll.new_contract.strip():
            raise ValueError(
                "New contract must not be empty."
            )

        if (
            roll.old_contract
            == roll.new_contract
        ):
            raise ValueError(
                "Old and new contracts "
                "must be different."
            )

        if roll.date in seen_dates:
            raise ValueError(
                "Duplicate roll date."
            )

        if (
            previous_date is not None
            and roll.date < previous_date
        ):
            raise ValueError(
                "Roll events must be "
                "in chronological order."
            )

        seen_dates.add(
            roll.date
        )

        previous_date = (
            roll.date
        )


def validate_execution_days(
    execution_days: list[
        ExecutionMarketDay
    ],
) -> None:
    seen_dates = set()
    previous_date = None

    for day in execution_days:
        if day.date in seen_dates:
            raise ValueError(
                "Duplicate execution date."
            )

        if (
            previous_date is not None
            and day.date < previous_date
        ):
            raise ValueError(
                "Execution days must be "
                "in chronological order."
            )

        if (
            not math.isfinite(
                day.daily_cash_vol_target
            )
            or day.daily_cash_vol_target <= 0
        ):
            raise ValueError(
                "daily_cash_vol_target "
                "must be finite and positive."
            )

        if (
            not math.isfinite(
                day.commission_per_contract
            )
            or day.commission_per_contract < 0
        ):
            raise ValueError(
                "commission_per_contract "
                "must be finite and non-negative."
            )

        if (
            not math.isfinite(
                day.fx_to_base
            )
            or day.fx_to_base <= 0
        ):
            raise ValueError(
                "fx_to_base must be "
                "finite and positive."
            )

        if (
            not isinstance(
                day.slippage_ticks,
                int,
            )
            or isinstance(
                day.slippage_ticks,
                bool,
            )
            or day.slippage_ticks < 0
        ):
            raise ValueError(
                "slippage_ticks must be "
                "a non-negative integer."
            )

        for contract, quote in (
            day.quotes.items()
        ):
            if not contract.strip():
                raise ValueError(
                    "Quote contract name "
                    "must not be empty."
                )

            if not (
                math.isfinite(quote.bid)
                and math.isfinite(quote.ask)
            ):
                raise ValueError(
                    "Bid and ask must be finite."
                )

            if quote.bid > quote.ask:
                raise ValueError(
                    "Bid must not be "
                    "greater than ask."
                )

        seen_dates.add(
            day.date
        )

        previous_date = (
            day.date
        )