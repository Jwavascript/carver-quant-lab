from datetime import date, timedelta
import json


import pytest


from carver_quant.backtest_config import (
    BacktestConfig,
)

from carver_quant.backtest_manifest import (
    build_backtest_manifest,
)

from carver_quant.backtest_result_bundle import (
    build_backtest_result_bundle,
    calculate_backtest_result_fingerprint,
    serialize_backtest_result_bundle,
)

from carver_quant.futures_data import (
    ContractPrice,
)

from carver_quant.instrument import (
    InstrumentSpec,
)

from carver_quant.portfolio import (
    PortfolioSpec,
)

from carver_quant.portfolio_system_backtest import (
    CombinedEWMACInstrumentInput,
    run_combined_ewmac_portfolio_backtest,
)

from carver_quant.roll_execution import (
    ContractQuote,
)

from carver_quant.system_backtest import (
    ExecutionMarketDay,
)

def make_bundle_input():
    start = date(
        2026,
        1,
        1,
    )

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

    prices = [
        ContractPrice(
            date=(
                start
                + timedelta(
                    days=index
                )
            ),
            contract="ESM6",
            close=value,
        )
        for index, value
        in enumerate(values)
    ]

    execution_days = [
        ExecutionMarketDay(
            date=(
                start
                + timedelta(
                    days=index
                )
            ),

            daily_cash_vol_target=1000.0,

            quotes={
                "ESM6": ContractQuote(
                    bid=value,
                    ask=value,
                ),
            },

            commission_per_contract=0.0,
        )
        for index, value
        in enumerate(values)
        if index >= 3
    ]

    instrument = (
        CombinedEWMACInstrumentInput(
            instrument_spec=(
                InstrumentSpec(
                    symbol="ES",
                    currency="USD",
                    multiplier=10.0,
                    tick_size=0.01,
                )
            ),

            prices=prices,

            initial_contract="ESM6",

            roll_events=[],

            execution_days=(
                execution_days
            ),
        )
    )

    portfolio = PortfolioSpec(
        instrument_weights={
            "ES": 1.0,
        },

        instrument_diversification_multiplier=1.0,
    )

    config = BacktestConfig(
        annual_volatility_target=0.20,
        position_buffer_fraction=0.10,
    )

    return (
        instrument,
        portfolio,
        config,
    )

def test_result_bundle_contains_manifest_code_and_performance():
    (
        instrument,
        portfolio,
        config,
    ) = make_bundle_input()

    instruments = {
        "ES": instrument,
    }

    manifest = build_backtest_manifest(
        initial_account_value=100_000.0,
        account_base_currency="KRW",
        portfolio_spec=portfolio,
        instruments=instruments,
        config=config,
    )

    result = (
        run_combined_ewmac_portfolio_backtest(
            initial_account_value=100_000.0,
            portfolio_spec=portfolio,
            instruments=instruments,
            config=config,
        )
    )

    bundle = (
        build_backtest_result_bundle(
            result=result,
            manifest=manifest,
            code_version="test-commit-abc123",
        )
    )

    assert (
        bundle.code_version
        == "test-commit-abc123"
    )

    assert (
        bundle.manifest
        == manifest
    )

    assert (
        bundle.final_account_value
        == pytest.approx(
            result.days[-1]
            .closing_account_value
        )
    )

    assert (
        bundle.performance
        .total_net_pnl
        == pytest.approx(
            sum(
                day.net_pnl
                for day in result.days
            )
        )
    )

def test_same_backtest_produces_same_result_fingerprint():
    (
        instrument,
        portfolio,
        config,
    ) = make_bundle_input()

    kwargs = {
        "initial_account_value": (
            100_000.0
        ),
        "portfolio_spec": portfolio,
        "instruments": {
            "ES": instrument,
        },
        "config": config,
    }

    first = (
        run_combined_ewmac_portfolio_backtest(
            **kwargs
        )
    )

    second = (
        run_combined_ewmac_portfolio_backtest(
            **kwargs
        )
    )

    assert (
        calculate_backtest_result_fingerprint(
            first
        )
        == calculate_backtest_result_fingerprint(
            second
        )
    )

def test_result_bundle_rejects_empty_code_version():
    (
        instrument,
        portfolio,
        config,
    ) = make_bundle_input()

    instruments = {
        "ES": instrument,
    }

    manifest = build_backtest_manifest(
        initial_account_value=100_000.0,
        account_base_currency="KRW",
        portfolio_spec=portfolio,
        instruments=instruments,
        config=config,
    )

    result = (
        run_combined_ewmac_portfolio_backtest(
            initial_account_value=100_000.0,
            portfolio_spec=portfolio,
            instruments=instruments,
            config=config,
        )
    )

    with pytest.raises(
        ValueError,
        match="code_version",
    ):
        build_backtest_result_bundle(
            result=result,
            manifest=manifest,
            code_version="",
        )

def test_result_bundle_serializes_canonically():
    (
        instrument,
        portfolio,
        config,
    ) = make_bundle_input()

    instruments = {
        "ES": instrument,
    }

    manifest = build_backtest_manifest(
        initial_account_value=100_000.0,
        account_base_currency="KRW",
        portfolio_spec=portfolio,
        instruments=instruments,
        config=config,
    )

    result = (
        run_combined_ewmac_portfolio_backtest(
            initial_account_value=100_000.0,
            portfolio_spec=portfolio,
            instruments=instruments,
            config=config,
        )
    )

    bundle = (
        build_backtest_result_bundle(
            result=result,
            manifest=manifest,
            code_version="abc123",
        )
    )

    serialized = (
        serialize_backtest_result_bundle(
            bundle
        )
    )

    parsed = json.loads(
        serialized
    )

    assert (
        parsed[
            "result_schema_version"
        ]
        == 1
    )

    assert (
        parsed["code_version"]
        == "abc123"
    )

    assert (
        parsed[
            "manifest"
        ][
            "input_fingerprint_sha256"
        ]
        == (
            manifest
            .input_fingerprint_sha256
        )
    )

    assert len(
        parsed[
            "result_fingerprint_sha256"
        ]
    ) == 64

    assert (
        serialize_backtest_result_bundle(
            bundle
        )
        == serialized
    )