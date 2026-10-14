from dataclasses import dataclass, replace
from datetime import date
import math

from carver_quant.risk_target import (
    calculate_daily_cash_vol_target,
)

from carver_quant.contract_aware_daily_step import (
    run_contract_aware_daily_step,
)
from carver_quant.instrument import (
    InstrumentSpec,
)
from carver_quant.portfolio import (
    PortfolioSpec,
    calculate_instrument_cash_vol_target,
)
from carver_quant.system_backtest import (
    PreparedEWMACBacktest,
)

from carver_quant.risk_guardrail import (
    PortfolioRiskPolicy,
    PortfolioRiskSnapshot,
    calculate_margin_required,
    calculate_portfolio_risk_snapshot,
    calculate_position_notional_base,
    validate_risk_snapshot,
)


@dataclass(frozen=True)
class PreparedPortfolioInstrument:
    instrument_spec: InstrumentSpec
    prepared_backtest: PreparedEWMACBacktest


@dataclass(frozen=True)
class PortfolioBacktestDayResult:
    date: date

    opening_account_value: float

    account_daily_cash_vol_target: float

    instrument_cash_vol_targets: dict[
        str,
        float,
    ]

    instrument_results: dict[
        str,
        object,
    ]

    gross_pnl: float
    trading_cost: float
    net_pnl: float

    closing_account_value: float

    risk_snapshot: (
        PortfolioRiskSnapshot | None
    ) = None
def _calculate_portfolio_day_risk_snapshot(
    account_value: float,
    instruments: dict[
        str,
        PreparedPortfolioInstrument,
    ],
    day_index: int,
    candidate_contract_positions: dict[
        str,
        dict[str, int],
    ],
) -> PortfolioRiskSnapshot:
    notionals: list[float] = []
    margins: list[float] = []

    for symbol, positions_by_contract in (
        candidate_contract_positions.items()
    ):
        instrument = instruments[symbol]

        spec = instrument.instrument_spec

        day = (
            instrument
            .prepared_backtest
            .days[day_index]
        )

        for contract, position in (
            positions_by_contract.items()
        ):
            if position == 0:
                continue

            quote = day.quotes.get(
                contract
            )

            if quote is None:
                raise ValueError(
                    "Missing quote for "
                    f"non-zero position: "
                    f"{symbol}/{contract}."
                )

            margin_per_contract = (
                day
                .margin_per_contract_base
                .get(contract)
            )

            if margin_per_contract is None:
                raise ValueError(
                    "Missing margin for "
                    f"non-zero position: "
                    f"{symbol}/{contract}."
                )

            mid_price = (
                quote.bid
                + quote.ask
            ) / 2.0

            notional = (
                calculate_position_notional_base(
                    position=position,
                    price=mid_price,
                    multiplier=spec.multiplier,
                    fx_to_base=day.fx_to_base,
                )
            )

            margin_required = (
                calculate_margin_required(
                    position=position,
                    margin_per_contract_base=(
                        margin_per_contract
                    ),
                )
            )

            notionals.append(
                notional
            )

            margins.append(
                margin_required
            )

    return calculate_portfolio_risk_snapshot(
        account_value=account_value,
        notionals=notionals,
        margins=margins,
    )


def run_prepared_portfolio_backtest(
    initial_account_value: float,
    portfolio_spec: PortfolioSpec,
    instruments: dict[
        str,
        PreparedPortfolioInstrument,
    ],
    annual_volatility_target: (
        float | None
    ) = None,
    position_buffer_fraction: (
        float | None
    ) = None,
    risk_policy: (
        PortfolioRiskPolicy | None
    ) = None,
) -> list[PortfolioBacktestDayResult]:
    if not math.isfinite(
        initial_account_value
    ):
        raise ValueError(
            "initial_account_value must be finite."
        )

    if initial_account_value <= 0:
        raise ValueError(
            "initial_account_value must be positive."
        )

    if not instruments:
        raise ValueError(
            "instruments must not be empty."
        )

    expected_symbols = set(
        portfolio_spec
        .instrument_weights
        .keys()
    )

    actual_symbols = set(
        instruments.keys()
    )

    if expected_symbols != actual_symbols:
        raise ValueError(
            "Portfolio symbols and "
            "instrument symbols must match."
        )

    # ---------------------------------
    # Trading dates 동기화 확인
    # ---------------------------------

    reference_dates = None

    for instrument in instruments.values():
        prepared = (
            instrument.prepared_backtest
        )

        dates = prepared.day_dates

        if len(dates) != len(
            prepared.days
        ):
            raise ValueError(
                "day_dates and days lengths "
                "must match."
            )

        if reference_dates is None:
            reference_dates = dates

        elif dates != reference_dates:
            raise ValueError(
                "Instrument backtest dates "
                "must be synchronized."
            )

    assert reference_dates is not None

    # ---------------------------------
    # Instrument별 position state
    # ---------------------------------

    positions = {
        symbol: 0
        for symbol in instruments
    }

    contract_positions = {
        symbol: {}
        for symbol in instruments
    }

    active_contracts = {
        symbol: (
            instrument
            .prepared_backtest
            .initial_active_contract
        )
        for symbol, instrument
        in instruments.items()
    }

    # ---------------------------------
    # Portfolio account state
    # ---------------------------------

    account_value = (
        initial_account_value
    )

    results: list[
        PortfolioBacktestDayResult
    ] = []

    # =================================
    # DAY LOOP
    # =================================

    for day_index, current_date in enumerate(
        reference_dates
    ):
        opening_account_value = (
            account_value
        )

        candidate_positions = (
        positions.copy()
    )

        candidate_contract_positions = {
            symbol: dict(
                positions_by_contract
            )
            for (
                symbol,
                positions_by_contract
            ) in contract_positions.items()
        }

        candidate_active_contracts = (
            active_contracts.copy()
        )

        instrument_results = {}

        portfolio_gross_pnl = 0.0
        portfolio_cost = 0.0
        portfolio_net_pnl = 0.0

        instrument_cash_vol_targets = {}

        # ---------------------------------
        # Account-level daily risk target
        # ---------------------------------

        if annual_volatility_target is None:
            # Legacy mode:
            # ExecutionMarketDay에 들어 있던
            # daily_cash_vol_target을 사용.
            account_daily_cash_vol_target = None

        else:
            # Dynamic mode:
            # 오늘 opening account value로
            # 오늘 risk budget 계산.
            account_daily_cash_vol_target = (
                calculate_daily_cash_vol_target(
                    capital=(
                        opening_account_value
                    ),
                    annual_volatility_target=(
                        annual_volatility_target
                    ),
                )
            )

        # =============================
        # INSTRUMENT LOOP
        # =============================

        for symbol, instrument in (
            instruments.items()
        ):
            prepared = (
                instrument
                .prepared_backtest
            )

            original_day = (
                prepared.days[
                    day_index
                ]
            )

            # ---------------------------------
            # Legacy mode에서만
            # static daily target 검증
            # ---------------------------------

            if annual_volatility_target is None:
                if (
                    account_daily_cash_vol_target
                    is None
                ):
                    account_daily_cash_vol_target = (
                        original_day
                        .daily_cash_vol_target
                    )

                elif not math.isclose(
                    original_day
                    .daily_cash_vol_target,
                    account_daily_cash_vol_target,
                    rel_tol=0.0,
                    abs_tol=1e-12,
                ):
                    raise ValueError(
                        "Account daily cash volatility "
                        "target must match across "
                        "instruments."
                    )

            # 여기까지 오면
            # legacy / dynamic 모두 반드시
            # account target이 존재해야 함.
            assert (
                account_daily_cash_vol_target
                is not None
            )

            # ---------------------------------
            # Portfolio allocation
            # ---------------------------------

            weight = (
                portfolio_spec
                .instrument_weights[
                    symbol
                ]
            )

            instrument_cash_vol_target = (
                calculate_instrument_cash_vol_target(
                    account_daily_cash_vol_target=(
                        account_daily_cash_vol_target
                    ),
                    instrument_weight=weight,
                    instrument_diversification_multiplier=(
                        portfolio_spec
                        .instrument_diversification_multiplier
                    ),
                )
            )

            instrument_cash_vol_targets[
                symbol
            ] = (
                instrument_cash_vol_target
            )

            # 기존 day의 account-level target을
            # instrument-level target으로 교체.
            day = replace(
                original_day,
                daily_cash_vol_target=(
                    instrument_cash_vol_target
                ),
            )

            spec = (
                instrument.instrument_spec
            )

            # ---------------------------------
            # Instrument daily execution
            # ---------------------------------

            result = (
                run_contract_aware_daily_step(
                    previous_account_value=(
                        opening_account_value
                    ),
                    current_position=(
                        positions[symbol]
                    ),
                    current_contract_positions=(
                        contract_positions[
                            symbol
                        ]
                    ),
                    active_contract=(
                        active_contracts[
                            symbol
                        ]
                    ),
                    roll_to_contract=(
                        day.roll_to_contract
                    ),
                    previous_adjusted_price=(
                        day.previous_adjusted_price
                    ),
                    current_adjusted_price=(
                        day.current_adjusted_price
                    ),
                    daily_cash_vol_target=(
                        day.daily_cash_vol_target
                    ),
                    price_volatility=(
                        day.price_volatility
                    ),
                    multiplier=(
                        spec.multiplier
                    ),
                    forecast=(
                        day.forecast
                    ),
                    quotes=(
                        day.quotes
                    ),
                    tick_size=(
                        spec.tick_size
                    ),
                    commission_per_contract=(
                        day.commission_per_contract
                    ),
                    slippage_ticks=(
                        day.slippage_ticks
                    ),
                    fx_to_base=(
                        day.fx_to_base
                    ),
                    position_buffer_fraction=(
                        position_buffer_fraction
                    ),
                )
            )


            # ---------------------------------
            # Instrument state update
            # ---------------------------------

            candidate_contract_positions[
                symbol
            ] = dict(
                result.new_contract_positions
            )

            candidate_positions[
                symbol
            ] = sum(
                result
                .new_contract_positions
                .values()
            )

            candidate_active_contracts[
                symbol
            ] = (
                result.active_contract
            )

            instrument_results[
                symbol
            ] = result

            # ---------------------------------
            # Portfolio aggregation
            # ---------------------------------

            portfolio_gross_pnl += (
                result.gross_pnl
            )

            portfolio_cost += (
                result.total_trading_cost
            )

            portfolio_net_pnl += (
                result.net_pnl
            )

        # =============================
        # END INSTRUMENT LOOP
        # =============================

        # 모든 instrument가 같은
        # opening account를 사용한 뒤
        # 마지막에 한 번만 계좌 갱신.
        closing_account_value = (
            opening_account_value
            + portfolio_net_pnl
        )

        risk_snapshot = None

        if risk_policy is not None:
            risk_snapshot = (
                _calculate_portfolio_day_risk_snapshot(
                    account_value=(
                        closing_account_value
                    ),
                    instruments=instruments,
                    day_index=day_index,
                    candidate_contract_positions=(
                        candidate_contract_positions
                    ),
                )
            )

            validate_risk_snapshot(
                snapshot=risk_snapshot,
                policy=risk_policy,
            )

        positions = candidate_positions

        contract_positions = (
            candidate_contract_positions
        )

        active_contracts = (
            candidate_active_contracts
        )

        account_value = (
            closing_account_value
        )

        results.append(
            PortfolioBacktestDayResult(
                date=current_date,

                opening_account_value=(
                    opening_account_value
                ),

                account_daily_cash_vol_target=(
                    account_daily_cash_vol_target
                ),

                instrument_cash_vol_targets=(
                    instrument_cash_vol_targets
                ),

                instrument_results=(
                    instrument_results
                ),

                gross_pnl=(
                    portfolio_gross_pnl
                ),

                trading_cost=(
                    portfolio_cost
                ),

                net_pnl=(
                    portfolio_net_pnl
                ),

                closing_account_value=(
                    account_value
                ),
                risk_snapshot=(
                    risk_snapshot
                ),
            )
        )

    # =================================
    # END DAY LOOP
    # =================================

    return results