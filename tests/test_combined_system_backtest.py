from datetime import date, timedelta

import pytest

from carver_quant.futures_data import (
    ContractPrice,
)
from carver_quant.roll_execution import (
    ContractQuote,
)
from carver_quant.system_backtest import (
    ExecutionMarketDay,
    prepare_combined_ewmac_backtest,
)


def test_combined_system_uses_previous_days_combined_forecast():
    start = date(2026, 1, 1)

    values = [
        100.0,
        101.0,
        103.0,
        106.0,
        110.0,
        115.0,
    ]

    prices = [
        ContractPrice(
            date=start + timedelta(days=index),
            contract="TEST",
            close=value,
        )
        for index, value in enumerate(values)
    ]

    execution_days = [
        ExecutionMarketDay(
            date=start + timedelta(days=index),
            daily_cash_vol_target=100.0,
            quotes={
                "TEST": ContractQuote(
                    bid=value - 0.1,
                    ask=value + 0.1,
                )
            },
            commission_per_contract=1.0,
        )
        for index, value in enumerate(values)
        if index >= 3
    ]

    prepared = prepare_combined_ewmac_backtest(
        prices=prices,
        initial_contract="TEST",
        roll_events=[],
        execution_days=execution_days,
    )

    first_day = prepared.days[0]

    # 첫 거래 가능한 날은 이전 signal을 사용한다.
    previous_signal = next(
        signal
        for signal in prepared.signals
        if (
            signal.adjusted_price
            == first_day.previous_adjusted_price
        )
    )

    assert previous_signal.forecast is not None

    assert first_day.forecast == pytest.approx(
        previous_signal.forecast
    )