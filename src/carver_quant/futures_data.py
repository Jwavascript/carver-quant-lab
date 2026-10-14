from dataclasses import dataclass
from datetime import date
import math


@dataclass(frozen=True)
class ContractPrice:
    date: date
    contract: str
    close: float

    def __post_init__(self) -> None:
        if not self.contract.strip():
            raise ValueError("contract must not be empty.")

        if not math.isfinite(self.close):
            raise ValueError("close must be finite.")


@dataclass(frozen=True)
class RollEvent:
    date: date
    old_contract: str
    new_contract: str

    def __post_init__(self) -> None:
        if not self.old_contract.strip():
            raise ValueError("old_contract must not be empty.")

        if not self.new_contract.strip():
            raise ValueError("new_contract must not be empty.")

        if self.old_contract == self.new_contract:
            raise ValueError(
                "old_contract and new_contract must be different."
            )


@dataclass(frozen=True)
class BackAdjustedPrice:
    date: date
    active_contract: str
    raw_price: float
    adjusted_price: float


def build_back_adjusted_prices(
    prices: list[ContractPrice],
    initial_contract: str,
    roll_events: list[RollEvent],
) -> list[BackAdjustedPrice]:
    if not initial_contract.strip():
        raise ValueError("initial_contract must not be empty.")

    price_index: dict[tuple[date, str], float] = {}

    for price in prices:
        key = (price.date, price.contract)

        if key in price_index:
            raise ValueError(
                f"Duplicate contract price: "
                f"{price.date} {price.contract}"
            )

        price_index[key] = price.close

    sorted_rolls = sorted(
        roll_events,
        key=lambda event: event.date,
    )

    # v1에서는 하루에 하나의 roll만 허용한다.
    roll_dates: set[date] = set()

    current_contract = initial_contract

    roll_gaps: list[tuple[RollEvent, float]] = []

    for event in sorted_rolls:
        if event.date in roll_dates:
            raise ValueError(
                "Multiple roll events on the same date "
                "are not supported."
            )

        roll_dates.add(event.date)

        if event.old_contract != current_contract:
            raise ValueError(
                "Roll event chain is inconsistent."
            )

        old_key = (
            event.date,
            event.old_contract,
        )
        new_key = (
            event.date,
            event.new_contract,
        )

        if old_key not in price_index:
            raise ValueError(
                "Old contract price is missing "
                "on roll date."
            )

        if new_key not in price_index:
            raise ValueError(
                "New contract price is missing "
                "on roll date."
            )

        old_price = price_index[old_key]
        new_price = price_index[new_key]

        gap = new_price - old_price

        roll_gaps.append(
            (event, gap)
        )

        current_contract = event.new_contract

    all_dates = sorted(
        {
            price.date
            for price in prices
        }
    )

    results: list[BackAdjustedPrice] = []

    for current_date in all_dates:
        active_contract = initial_contract

        for event in sorted_rolls:
            # Roll date 자체까지는 old contract를 사용한다.
            # 다음 날짜부터 new contract가 active가 된다.
            if current_date > event.date:
                active_contract = event.new_contract
            else:
                break

        raw_key = (
            current_date,
            active_contract,
        )

        if raw_key not in price_index:
            raise ValueError(
                f"Active contract price is missing: "
                f"{current_date} {active_contract}"
            )

        raw_price = price_index[raw_key]

        cumulative_adjustment = sum(
            gap
            for event, gap in roll_gaps
            if current_date <= event.date
        )

        adjusted_price = (
            raw_price
            + cumulative_adjustment
        )

        results.append(
            BackAdjustedPrice(
                date=current_date,
                active_contract=active_contract,
                raw_price=raw_price,
                adjusted_price=adjusted_price,
            )
        )

    return results

def build_back_adjusted_prices_as_of(
    prices: list[ContractPrice],
    initial_contract: str,
    roll_events: list[RollEvent],
    as_of_date: date,
) -> list[BackAdjustedPrice]:
    visible_prices = [
        price
        for price in prices
        if price.date <= as_of_date
    ]

    visible_roll_events = [
        roll
        for roll in roll_events
        if roll.date <= as_of_date
    ]

    if not visible_prices:
        return []

    return build_back_adjusted_prices(
        prices=visible_prices,
        initial_contract=initial_contract,
        roll_events=visible_roll_events,
    )