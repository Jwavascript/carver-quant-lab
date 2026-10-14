from datetime import date

import pytest

from carver_quant.data_quality import (
    validate_contract_prices,
    validate_execution_days,
    validate_roll_events,
)
from carver_quant.futures_data import (
    ContractPrice,
    RollEvent,
)
from carver_quant.roll_execution import (
    ContractQuote,
)
from carver_quant.system_backtest import (
    ExecutionMarketDay,
)

def test_duplicate_contract_price_is_rejected():
    prices = [
        ContractPrice(
            date=date(2026, 1, 1),
            contract="A",
            close=100.0,
        ),
        ContractPrice(
            date=date(2026, 1, 1),
            contract="A",
            close=101.0,
        ),
    ]

    with pytest.raises(
        ValueError,
        match="Duplicate",
    ):
        validate_contract_prices(
            prices
        )

def test_non_finite_contract_price_is_rejected():
    with pytest.raises(
        ValueError,
        match="close must be finite",
    ):
        ContractPrice(
            date=date(2026, 1, 1),
            contract="A",
            close=float("nan"),
        )

def test_negative_futures_price_is_allowed():
    prices = [
        ContractPrice(
            date=date(2026, 1, 1),
            contract="A",
            close=-37.63,
        )
    ]

    validate_contract_prices(
        prices
    )

def test_roll_events_must_be_chronological():
    roll_events = [
        RollEvent(
            date=date(2026, 3, 1),
            old_contract="B",
            new_contract="C",
        ),
        RollEvent(
            date=date(2026, 2, 1),
            old_contract="A",
            new_contract="B",
        ),
    ]

    with pytest.raises(
        ValueError,
        match="chronological",
    ):
        validate_roll_events(
            roll_events
        )

def test_crossed_quote_is_rejected():
    days = [
        ExecutionMarketDay(
            date=date(2026, 1, 1),
            daily_cash_vol_target=1000.0,
            quotes={
                "TEST": ContractQuote(
                    bid=101.0,
                    ask=100.0,
                )
            },
            commission_per_contract=1.0,
            fx_to_base=1.0,
            slippage_ticks=0,
        )
    ]

    with pytest.raises(
        ValueError,
        match="Bid",
    ):
        validate_execution_days(
            days
        )

def test_calendar_gaps_are_allowed():
    prices = [
        ContractPrice(
            date=date(2026, 1, 2),
            contract="A",
            close=100.0,
        ),

        # 주말이나 휴일일 수 있으므로
        # Jan 3, Jan 4가 없다는 이유만으로
        # 오류를 내면 안 된다.
        ContractPrice(
            date=date(2026, 1, 5),
            contract="A",
            close=101.0,
        ),
    ]

    validate_contract_prices(
        prices
    )