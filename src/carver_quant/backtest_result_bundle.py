from dataclasses import dataclass
import hashlib
import math
from typing import Protocol


from carver_quant.backtest_manifest import (
    BacktestManifest,
    to_canonical_json,
)

from carver_quant.performance import (
    PerformanceSummary,
    summarise_portfolio_performance,
)


BACKTEST_RESULT_SCHEMA_VERSION = 1


class PortfolioBacktestResultLike(
    Protocol
):
    days: list


@dataclass(frozen=True)
class BacktestResultBundle:
    result_schema_version: int

    code_version: str

    manifest: BacktestManifest

    performance: PerformanceSummary

    final_account_value: float

    result_fingerprint_sha256: str

def _validate_code_version(
    code_version: str,
) -> str:
    if (
        not isinstance(
            code_version,
            str,
        )
        or not code_version.strip()
    ):
        raise ValueError(
            "code_version must not be empty."
        )

    return code_version.strip()

def build_backtest_result_payload(
    result: PortfolioBacktestResultLike,
) -> dict[str, object]:
    if not result.days:
        raise ValueError(
            "Backtest result must contain "
            "at least one day."
        )

    daily_results = []

    for day in result.days:
        if (
            not math.isfinite(
                day.opening_account_value
            )
            or not math.isfinite(
                day.closing_account_value
            )
            or not math.isfinite(
                day.gross_pnl
            )
            or not math.isfinite(
                day.net_pnl
            )
        ):
            raise ValueError(
                "Backtest result contains "
                "non-finite values."
            )

        instrument_results = {}

        for symbol in sorted(
            day.instrument_results
        ):
            instrument = (
                day.instrument_results[
                    symbol
                ]
            )

            instrument_results[
                symbol
            ] = {
                "gross_pnl": (
                    instrument.gross_pnl
                ),

                "trading_cost": (
                    instrument
                    .total_trading_cost
                ),

                "net_pnl": (
                    instrument.net_pnl
                ),

                "target_position": (
                    instrument
                    .target_position
                ),

                "directional_trade": (
                    instrument
                    .directional_trade
                ),

                "contract_positions": dict(
                    sorted(
                        instrument
                        .new_contract_positions
                        .items()
                    )
                ),
            }

        daily_results.append(
            {
                "opening_account_value": (
                    day
                    .opening_account_value
                ),

                "closing_account_value": (
                    day
                    .closing_account_value
                ),

                "gross_pnl": (
                    day.gross_pnl
                ),

                "trading_cost": (
                    day.trading_cost
                ),

                "net_pnl": (
                    day.net_pnl
                ),

                "instrument_results": (
                    instrument_results
                ),
            }
        )

    return {
        "result_schema_version": (
            BACKTEST_RESULT_SCHEMA_VERSION
        ),

        "days": daily_results,
    }

def calculate_backtest_result_fingerprint(
    result: PortfolioBacktestResultLike,
) -> str:
    payload = (
        build_backtest_result_payload(
            result
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
def build_backtest_result_bundle(
    result: PortfolioBacktestResultLike,
    manifest: BacktestManifest,
    code_version: str,
) -> BacktestResultBundle:
    resolved_code_version = (
        _validate_code_version(
            code_version
        )
    )

    if not result.days:
        raise ValueError(
            "Backtest result must contain "
            "at least one day."
        )

    performance = (
        summarise_portfolio_performance(
            result.days
        )
    )

    final_account_value = (
        result.days[-1]
        .closing_account_value
    )

    fingerprint = (
        calculate_backtest_result_fingerprint(
            result
        )
    )

    return BacktestResultBundle(
        result_schema_version=(
            BACKTEST_RESULT_SCHEMA_VERSION
        ),

        code_version=(
            resolved_code_version
        ),

        manifest=manifest,

        performance=performance,

        final_account_value=(
            final_account_value
        ),

        result_fingerprint_sha256=(
            fingerprint
        ),
    )

def serialize_backtest_result_bundle(
    bundle: BacktestResultBundle,
) -> str:
    return to_canonical_json(
        bundle
    )

