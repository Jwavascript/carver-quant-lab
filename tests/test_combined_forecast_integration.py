from datetime import date, timedelta

from carver_quant.combined_forecast import (
    calculate_combined_ewmac_forecast,
)
from carver_quant.futures_data import (
    BackAdjustedPrice,
)
from carver_quant.volatility import (
    calculate_ewma_price_volatility,
)


def test_combined_ewmac_forecast_from_real_price_series():
    values = [
        100.0,
        101.0,
        103.0,
        106.0,
        110.0,
        115.0,
        121.0,
        128.0,
    ]

    start = date(2026, 1, 1)

    prices = [
        BackAdjustedPrice(
            date=start + timedelta(
                days=index
            ),
            active_contract="TEST",
            raw_price=value,
            adjusted_price=value,
        )
        for index, value
        in enumerate(values)
    ]

    volatility = calculate_ewma_price_volatility(
        prices,
        span=32,
    )

    result = calculate_combined_ewmac_forecast(
        adjusted_prices=prices,
        volatility=volatility,
    )

    assert result[-1].combined_forecast is not None

    assert (
        result[-1].combined_forecast
        > 0.0
    )

    assert (
        result[-1].combined_forecast
        <= 20.0
    )

    assert len(
        result[-1].component_forecasts
    ) == 6