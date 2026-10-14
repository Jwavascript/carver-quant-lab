from datetime import date


import pytest
import json

from dataclasses import replace

from carver_quant.backtest_config import (
    BacktestConfig,
)

from carver_quant.backtest_manifest import (
    build_backtest_manifest,
    calculate_backtest_input_fingerprint,
    serialize_backtest_manifest,
    to_canonical_json,
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
)

from carver_quant.roll_execution import (
    ContractQuote,
)

from carver_quant.system_backtest import (
    ExecutionMarketDay,
)

def make_manifest_input(
    symbol: str,
    contract: str,
) -> CombinedEWMACInstrumentInput:
    prices = [
        ContractPrice(
            date=date(2026, 1, 1),
            contract=contract,
            close=100.0,
        ),
        ContractPrice(
            date=date(2026, 1, 2),
            contract=contract,
            close=101.0,
        ),
        ContractPrice(
            date=date(2026, 1, 3),
            contract=contract,
            close=102.0,
        ),
    ]

    execution_days = [
        ExecutionMarketDay(
            date=date(2026, 1, 2),
            daily_cash_vol_target=1000.0,
            quotes={
                contract: ContractQuote(
                    bid=101.0,
                    ask=101.0,
                ),
            },
            commission_per_contract=0.0,
        ),
        ExecutionMarketDay(
            date=date(2026, 1, 3),
            daily_cash_vol_target=1000.0,
            quotes={
                contract: ContractQuote(
                    bid=102.0,
                    ask=102.0,
                ),
            },
            commission_per_contract=0.0,
        ),
    ]

    return CombinedEWMACInstrumentInput(
        instrument_spec=InstrumentSpec(
            symbol=symbol,
            currency="USD",
            multiplier=10.0,
            tick_size=0.25,
        ),
        prices=prices,
        initial_contract=contract,
        roll_events=[],
        execution_days=execution_days,
    )

def test_manifest_captures_account_portfolio_and_config():
    es = make_manifest_input(
        symbol="ES",
        contract="ESM6",
    )

    config = BacktestConfig(
        annual_volatility_target=0.20,
        position_buffer_fraction=0.10,
    )

    portfolio = PortfolioSpec(
        instrument_weights={
            "ES": 1.0,
        },
        instrument_diversification_multiplier=1.0,
    )

    manifest = build_backtest_manifest(
        initial_account_value=100_000.0,
        account_base_currency="krw",
        portfolio_spec=portfolio,
        instruments={
            "ES": es,
        },
        config=config,
    )

    assert (
        manifest.initial_account_value
        == pytest.approx(100_000.0)
    )

    assert (
        manifest.account_base_currency
        == "KRW"
    )

    assert manifest.config == config

    assert (
        manifest.instrument_weights
        == (
            ("ES", 1.0),
        )
    )

def test_manifest_captures_instrument_data_range():
    es = make_manifest_input(
        symbol="ES",
        contract="ESM6",
    )

    manifest = build_backtest_manifest(
        initial_account_value=100_000.0,
        account_base_currency="KRW",
        portfolio_spec=PortfolioSpec(
            instrument_weights={
                "ES": 1.0,
            },
            instrument_diversification_multiplier=1.0,
        ),
        instruments={
            "ES": es,
        },
        config=BacktestConfig(),
    )

    instrument = manifest.instruments[0]

    assert instrument.symbol == "ES"
    assert instrument.currency == "USD"

    assert (
        instrument.contracts
        == ("ESM6",)
    )

    assert (
        instrument.price_start_date
        == date(2026, 1, 1)
    )

    assert (
        instrument.price_end_date
        == date(2026, 1, 3)
    )

    assert instrument.price_count == 3

    assert (
        instrument.execution_start_date
        == date(2026, 1, 2)
    )

    assert (
        instrument.execution_end_date
        == date(2026, 1, 3)
    )

    assert (
        instrument.execution_day_count
        == 2
    )

    assert instrument.roll_event_count == 0

def test_manifest_is_independent_of_instrument_dictionary_order():
    es = make_manifest_input(
        symbol="ES",
        contract="ESM6",
    )

    zn = make_manifest_input(
        symbol="ZN",
        contract="ZNM6",
    )

    portfolio = PortfolioSpec(
        instrument_weights={
            "ZN": 0.5,
            "ES": 0.5,
        },
        instrument_diversification_multiplier=1.2,
    )

    config = BacktestConfig()

    forward = build_backtest_manifest(
        initial_account_value=100_000.0,
        account_base_currency="KRW",
        portfolio_spec=portfolio,
        instruments={
            "ES": es,
            "ZN": zn,
        },
        config=config,
    )

    reverse = build_backtest_manifest(
        initial_account_value=100_000.0,
        account_base_currency="KRW",
        portfolio_spec=portfolio,
        instruments={
            "ZN": zn,
            "ES": es,
        },
        config=config,
    )

    assert forward == reverse

    assert tuple(
        instrument.symbol
        for instrument in forward.instruments
    ) == (
        "ES",
        "ZN",
    )

def test_manifest_rejects_dictionary_symbol_mismatch():
    es = make_manifest_input(
        symbol="ES",
        contract="ESM6",
    )

    portfolio = PortfolioSpec(
        instrument_weights={
            "WRONG": 1.0,
        },
        instrument_diversification_multiplier=1.0,
    )

    with pytest.raises(
        ValueError,
        match="match InstrumentSpec.symbol",
    ):
        build_backtest_manifest(
            initial_account_value=100_000.0,
            account_base_currency="KRW",
            portfolio_spec=portfolio,
            instruments={
                "WRONG": es,
            },
            config=BacktestConfig(),
        )

def test_manifest_rejects_invalid_account_metadata():
    es = make_manifest_input(
        symbol="ES",
        contract="ESM6",
    )

    portfolio = PortfolioSpec(
        instrument_weights={
            "ES": 1.0,
        },
        instrument_diversification_multiplier=1.0,
    )

    with pytest.raises(
        ValueError,
        match="initial_account_value",
    ):
        build_backtest_manifest(
            initial_account_value=0.0,
            account_base_currency="KRW",
            portfolio_spec=portfolio,
            instruments={
                "ES": es,
            },
            config=BacktestConfig(),
        )

    with pytest.raises(
        ValueError,
        match="account_base_currency",
    ):
        build_backtest_manifest(
            initial_account_value=100_000.0,
            account_base_currency="",
            portfolio_spec=portfolio,
            instruments={
                "ES": es,
            },
            config=BacktestConfig(),
        )


def test_canonical_json_is_independent_of_dictionary_order():
    left = {
        "b": 2,
        "a": 1,
    }

    right = {
        "a": 1,
        "b": 2,
    }

    assert (
        to_canonical_json(left)
        == to_canonical_json(right)
    )

    assert (
        to_canonical_json(left)
        == '{"a":1,"b":2}'
    )

def test_input_fingerprint_is_independent_of_instrument_order():
    es = make_manifest_input(
        symbol="ES",
        contract="ESM6",
    )

    zn = make_manifest_input(
        symbol="ZN",
        contract="ZNM6",
    )

    portfolio = PortfolioSpec(
        instrument_weights={
            "ES": 0.5,
            "ZN": 0.5,
        },
        instrument_diversification_multiplier=1.2,
    )

    config = BacktestConfig()

    forward = (
        calculate_backtest_input_fingerprint(
            initial_account_value=100_000.0,
            account_base_currency="KRW",
            portfolio_spec=portfolio,
            instruments={
                "ES": es,
                "ZN": zn,
            },
            config=config,
        )
    )

    reverse = (
        calculate_backtest_input_fingerprint(
            initial_account_value=100_000.0,
            account_base_currency="KRW",
            portfolio_spec=portfolio,
            instruments={
                "ZN": zn,
                "ES": es,
            },
            config=config,
        )
    )

    assert forward == reverse

def test_input_fingerprint_changes_when_price_data_changes():
    es = make_manifest_input(
        symbol="ES",
        contract="ESM6",
    )

    changed_prices = list(
        es.prices
    )

    changed_prices[-1] = (
        ContractPrice(
            date=date(2026, 1, 3),
            contract="ESM6",
            close=102.25,
        )
    )

    changed_es = replace(
        es,
        prices=changed_prices,
    )

    portfolio = PortfolioSpec(
        instrument_weights={
            "ES": 1.0,
        },
        instrument_diversification_multiplier=1.0,
    )

    config = BacktestConfig()

    original = (
        calculate_backtest_input_fingerprint(
            initial_account_value=100_000.0,
            account_base_currency="KRW",
            portfolio_spec=portfolio,
            instruments={
                "ES": es,
            },
            config=config,
        )
    )

    changed = (
        calculate_backtest_input_fingerprint(
            initial_account_value=100_000.0,
            account_base_currency="KRW",
            portfolio_spec=portfolio,
            instruments={
                "ES": changed_es,
            },
            config=config,
        )
    )

    assert original != changed

def test_input_fingerprint_changes_when_config_changes():
    es = make_manifest_input(
        symbol="ES",
        contract="ESM6",
    )

    portfolio = PortfolioSpec(
        instrument_weights={
            "ES": 1.0,
        },
        instrument_diversification_multiplier=1.0,
    )

    first = (
        calculate_backtest_input_fingerprint(
            initial_account_value=100_000.0,
            account_base_currency="KRW",
            portfolio_spec=portfolio,
            instruments={
                "ES": es,
            },
            config=BacktestConfig(
                annual_volatility_target=0.20,
            ),
        )
    )

    second = (
        calculate_backtest_input_fingerprint(
            initial_account_value=100_000.0,
            account_base_currency="KRW",
            portfolio_spec=portfolio,
            instruments={
                "ES": es,
            },
            config=BacktestConfig(
                annual_volatility_target=0.15,
            ),
        )
    )

    assert first != second

def test_manifest_contains_sha256_and_serializes_canonically():
    es = make_manifest_input(
        symbol="ES",
        contract="ESM6",
    )

    manifest = build_backtest_manifest(
        initial_account_value=100_000.0,
        account_base_currency="krw",
        portfolio_spec=PortfolioSpec(
            instrument_weights={
                "ES": 1.0,
            },
            instrument_diversification_multiplier=1.0,
        ),
        instruments={
            "ES": es,
        },
        config=BacktestConfig(
            annual_volatility_target=0.20,
        ),
    )

    fingerprint = (
        manifest
        .input_fingerprint_sha256
    )

    assert len(fingerprint) == 64

    # 16진수 문자열인지 검증
    int(
        fingerprint,
        16,
    )

    serialized = (
        serialize_backtest_manifest(
            manifest
        )
    )

    parsed = json.loads(
        serialized
    )

    assert (
        parsed[
            "manifest_schema_version"
        ]
        == 1
    )

    assert (
        parsed[
            "input_fingerprint_sha256"
        ]
        == fingerprint
    )

    assert (
        parsed[
            "account_base_currency"
        ]
        == "KRW"
    )

    # 같은 객체는 언제나
    # byte-for-byte 동일한 JSON
    assert (
        serialize_backtest_manifest(
            manifest
        )
        == serialized
    )