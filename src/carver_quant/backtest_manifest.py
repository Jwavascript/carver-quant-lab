from dataclasses import (
    dataclass,
    fields,
    is_dataclass,
)
from datetime import date
import hashlib
import json
import math

from typing import Mapping, Protocol

from collections.abc import (
    Mapping as ABCMapping,
)


from carver_quant.backtest_config import (
    BacktestConfig,
)

from carver_quant.instrument import (
    InstrumentSpec,
)

from carver_quant.portfolio import (
    PortfolioSpec,
)

BACKTEST_MANIFEST_SCHEMA_VERSION = 1
BACKTEST_INPUT_SCHEMA_VERSION = 1


class ManifestInstrumentInput(
    Protocol
):
    instrument_spec: InstrumentSpec

    prices: list

    initial_contract: str

    roll_events: list

    execution_days: list


@dataclass(frozen=True)
class InstrumentManifest:
    symbol: str

    currency: str

    multiplier: float

    tick_size: float

    initial_contract: str

    contracts: tuple[str, ...]

    price_start_date: date

    price_end_date: date

    price_count: int

    execution_start_date: date

    execution_end_date: date

    execution_day_count: int

    roll_event_count: int


@dataclass(frozen=True)
class BacktestManifest:
    manifest_schema_version: int

    input_fingerprint_sha256: str

    initial_account_value: float

    account_base_currency: str

    instrument_weights: tuple[
        tuple[str, float],
        ...
    ]

    instrument_diversification_multiplier: (
        float
    )

    config: BacktestConfig

    instruments: tuple[
        InstrumentManifest,
        ...
    ]


def _validate_account(
    initial_account_value: float,
    account_base_currency: str,
) -> None:
    if (
        not math.isfinite(
            initial_account_value
        )
        or initial_account_value <= 0
    ):
        raise ValueError(
            "initial_account_value must "
            "be finite and positive."
        )

    if (
        not isinstance(
            account_base_currency,
            str,
        )
        or not account_base_currency.strip()
    ):
        raise ValueError(
            "account_base_currency must "
            "not be empty."
        )


def _build_instrument_manifest(
    dictionary_symbol: str,
    instrument: ManifestInstrumentInput,
) -> InstrumentManifest:
    spec = instrument.instrument_spec

    if dictionary_symbol != spec.symbol:
        raise ValueError(
            "Instrument dictionary key must "
            "match InstrumentSpec.symbol."
        )

    if not instrument.prices:
        raise ValueError(
            f"{dictionary_symbol} has no "
            "price data."
        )

    if not instrument.execution_days:
        raise ValueError(
            f"{dictionary_symbol} has no "
            "execution market data."
        )

    price_dates = [
        point.date
        for point in instrument.prices
    ]

    execution_dates = [
        day.date
        for day in instrument.execution_days
    ]

    contracts = tuple(
        sorted(
            {
                point.contract
                for point in instrument.prices
            }
        )
    )

    return InstrumentManifest(
        symbol=spec.symbol,
        currency=spec.currency,
        multiplier=spec.multiplier,
        tick_size=spec.tick_size,

        initial_contract=(
            instrument.initial_contract
        ),

        contracts=contracts,

        price_start_date=min(
            price_dates
        ),

        price_end_date=max(
            price_dates
        ),

        price_count=len(
            instrument.prices
        ),

        execution_start_date=min(
            execution_dates
        ),

        execution_end_date=max(
            execution_dates
        ),

        execution_day_count=len(
            instrument.execution_days
        ),

        roll_event_count=len(
            instrument.roll_events
        ),
    )


def build_backtest_manifest(
    initial_account_value: float,
    account_base_currency: str,
    portfolio_spec: PortfolioSpec,
    instruments: Mapping[
        str,
        ManifestInstrumentInput,
    ],
    config: BacktestConfig,
) -> BacktestManifest:
    _validate_account(
        initial_account_value=(
            initial_account_value
        ),
        account_base_currency=(
            account_base_currency
        ),
    )

    if not instruments:
        raise ValueError(
            "instruments must not be empty."
        )

    manifests = tuple(
        _build_instrument_manifest(
            dictionary_symbol=symbol,
            instrument=instruments[symbol],
        )
        for symbol in sorted(
            instruments
        )
    )
    input_fingerprint = (
        calculate_backtest_input_fingerprint(
            initial_account_value=(
                initial_account_value
            ),
            account_base_currency=(
                account_base_currency
            ),
            portfolio_spec=(
                portfolio_spec
            ),
            instruments=instruments,
            config=config,
        )
    )

    return BacktestManifest(
        manifest_schema_version=(
            BACKTEST_MANIFEST_SCHEMA_VERSION
        ),

        input_fingerprint_sha256=(
            input_fingerprint
        ),

        initial_account_value=(
            initial_account_value
        ),

        account_base_currency=(
            account_base_currency
            .strip()
            .upper()
        ),

        instrument_weights=tuple(
            sorted(
                portfolio_spec
                .instrument_weights
                .items()
            )
        ),

        instrument_diversification_multiplier=(
            portfolio_spec
            .instrument_diversification_multiplier
        ),

        config=config,

        instruments=manifests,
    )

def _to_canonical_json_value(
    value: object,
) -> object:
    if value is None:
        return None

    # bool은 int의 subclass이므로
    # int보다 먼저 검사한다.
    if isinstance(value, bool):
        return value

    if isinstance(value, str):
        return value

    if isinstance(value, int):
        return value

    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(
                "Canonical JSON does not "
                "support non-finite floats."
            )

        return value

    if isinstance(value, date):
        return value.isoformat()

    if (
        is_dataclass(value)
        and not isinstance(value, type)
    ):
        return {
            field.name: (
                _to_canonical_json_value(
                    getattr(
                        value,
                        field.name,
                    )
                )
            )
            for field in fields(value)
        }

    if isinstance(
        value,
        ABCMapping,
    ):
        converted = {}

        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(
                    "Canonical JSON mapping "
                    "keys must be strings."
                )

            converted[key] = (
                _to_canonical_json_value(
                    item
                )
            )

        return converted

    if isinstance(
        value,
        (list, tuple),
    ):
        return [
            _to_canonical_json_value(
                item
            )
            for item in value
        ]

    raise TypeError(
        "Unsupported canonical JSON "
        f"type: {type(value).__name__}."
    )

def to_canonical_json(
    value: object,
) -> str:
    converted = (
        _to_canonical_json_value(
            value
        )
    )

    return json.dumps(
        converted,
        sort_keys=True,
        separators=(
            ",",
            ":",
        ),
        ensure_ascii=False,
        allow_nan=False,
    )

def build_backtest_input_payload(
    initial_account_value: float,
    account_base_currency: str,
    portfolio_spec: PortfolioSpec,
    instruments: Mapping[
        str,
        ManifestInstrumentInput,
    ],
    config: BacktestConfig,
) -> dict[str, object]:
    _validate_account(
        initial_account_value=(
            initial_account_value
        ),
        account_base_currency=(
            account_base_currency
        ),
    )

    if not instruments:
        raise ValueError(
            "instruments must not be empty."
        )

    # 기존 manifest validation도
    # fingerprint 생성 시 동일하게 적용한다.
    for symbol in sorted(
        instruments
    ):
        _build_instrument_manifest(
            dictionary_symbol=symbol,
            instrument=(
                instruments[symbol]
            ),
        )

    instrument_payload = {}

    for symbol in sorted(
        instruments
    ):
        instrument = (
            instruments[symbol]
        )

        # 주의:
        # CombinedEWMACInstrumentInput 전체를
        # 넣지 않는다.
        #
        # fast_spans 등의 legacy strategy
        # 설정은 BacktestConfig가 canonical
        # source이기 때문이다.
        instrument_payload[symbol] = {
            "instrument_spec": (
                instrument
                .instrument_spec
            ),

            "prices": (
                instrument.prices
            ),

            "initial_contract": (
                instrument
                .initial_contract
            ),

            "roll_events": (
                instrument.roll_events
            ),

            "execution_days": (
                instrument
                .execution_days
            ),
        }

    return {
        "input_schema_version": (
            BACKTEST_INPUT_SCHEMA_VERSION
        ),

        "initial_account_value": (
            initial_account_value
        ),

        "account_base_currency": (
            account_base_currency
            .strip()
            .upper()
        ),

        "portfolio": {
            "instrument_weights": dict(
                sorted(
                    portfolio_spec
                    .instrument_weights
                    .items()
                )
            ),

            "instrument_diversification_multiplier": (
                portfolio_spec
                .instrument_diversification_multiplier
            ),
        },

        "config": config,

        "instruments": (
            instrument_payload
        ),
    }

def build_backtest_input_payload(
    initial_account_value: float,
    account_base_currency: str,
    portfolio_spec: PortfolioSpec,
    instruments: Mapping[
        str,
        ManifestInstrumentInput,
    ],
    config: BacktestConfig,
) -> dict[str, object]:
    _validate_account(
        initial_account_value=(
            initial_account_value
        ),
        account_base_currency=(
            account_base_currency
        ),
    )

    if not instruments:
        raise ValueError(
            "instruments must not be empty."
        )

    # 기존 manifest validation도
    # fingerprint 생성 시 동일하게 적용한다.
    for symbol in sorted(
        instruments
    ):
        _build_instrument_manifest(
            dictionary_symbol=symbol,
            instrument=(
                instruments[symbol]
            ),
        )

    instrument_payload = {}

    for symbol in sorted(
        instruments
    ):
        instrument = (
            instruments[symbol]
        )

        # 주의:
        # CombinedEWMACInstrumentInput 전체를
        # 넣지 않는다.
        #
        # fast_spans 등의 legacy strategy
        # 설정은 BacktestConfig가 canonical
        # source이기 때문이다.
        instrument_payload[symbol] = {
            "instrument_spec": (
                instrument
                .instrument_spec
            ),

            "prices": (
                instrument.prices
            ),

            "initial_contract": (
                instrument
                .initial_contract
            ),

            "roll_events": (
                instrument.roll_events
            ),

            "execution_days": (
                instrument
                .execution_days
            ),
        }

    return {
        "input_schema_version": (
            BACKTEST_INPUT_SCHEMA_VERSION
        ),

        "initial_account_value": (
            initial_account_value
        ),

        "account_base_currency": (
            account_base_currency
            .strip()
            .upper()
        ),

        "portfolio": {
            "instrument_weights": dict(
                sorted(
                    portfolio_spec
                    .instrument_weights
                    .items()
                )
            ),

            "instrument_diversification_multiplier": (
                portfolio_spec
                .instrument_diversification_multiplier
            ),
        },

        "config": config,

        "instruments": (
            instrument_payload
        ),
    }

def calculate_backtest_input_fingerprint(
    initial_account_value: float,
    account_base_currency: str,
    portfolio_spec: PortfolioSpec,
    instruments: Mapping[
        str,
        ManifestInstrumentInput,
    ],
    config: BacktestConfig,
) -> str:
    payload = (
        build_backtest_input_payload(
            initial_account_value=(
                initial_account_value
            ),
            account_base_currency=(
                account_base_currency
            ),
            portfolio_spec=(
                portfolio_spec
            ),
            instruments=instruments,
            config=config,
        )
    )

    canonical_json = (
        to_canonical_json(
            payload
        )
    )

    return hashlib.sha256(
        canonical_json.encode(
            "utf-8"
        )
    ).hexdigest()

def serialize_backtest_manifest(
    manifest: BacktestManifest,
) -> str:
    return to_canonical_json(
        manifest
    )


