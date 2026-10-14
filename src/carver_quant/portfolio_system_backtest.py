from dataclasses import dataclass

from carver_quant.futures_data import (
    ContractPrice,
    RollEvent,
)
from carver_quant.instrument import (
    InstrumentSpec,
)
from carver_quant.portfolio import (
    PortfolioSpec,
)
from carver_quant.portfolio_backtest import (
    PortfolioBacktestDayResult,
    PreparedPortfolioInstrument,
    run_prepared_portfolio_backtest,
)
from carver_quant.system_backtest import (
    ExecutionMarketDay,
    PreparedEWMACBacktest,
    prepare_point_in_time_combined_ewmac_backtest,
)

from carver_quant.data_quality import (
    validate_contract_prices,
    validate_execution_days,
    validate_roll_events,
)

from carver_quant.risk_guardrail import (
    PortfolioRiskPolicy,
)

from carver_quant.backtest_config import (
    BacktestConfig,
)

@dataclass(frozen=True)
class CombinedEWMACInstrumentInput:
    instrument_spec: InstrumentSpec

    prices: list[ContractPrice]

    initial_contract: str

    roll_events: list[RollEvent]

    execution_days: list[ExecutionMarketDay]

    fast_spans: tuple[int, ...] = (
        2,
        4,
        8,
        16,
        32,
        64,
    )

    volatility_span: int = 32

    long_run_window: int = 2560


@dataclass(frozen=True)
class PortfolioSystemBacktestResult:
    prepared_instruments: dict[
        str,
        PreparedPortfolioInstrument,
    ]

    days: list[
        PortfolioBacktestDayResult
    ]

def prepare_combined_ewmac_portfolio(
    instruments: dict[
        str,
        CombinedEWMACInstrumentInput,
    ],
    config: BacktestConfig | None = None,
) -> dict[
    str,
    PreparedPortfolioInstrument,
]:
    if not instruments:
        raise ValueError(
            "instruments must not be empty."
        )

    prepared: dict[
        str,
        PreparedPortfolioInstrument,
    ] = {}

    for symbol, instrument in (
        instruments.items()
    ):
        if (
            symbol
            != instrument.instrument_spec.symbol
        ):
            raise ValueError(
                "Instrument dictionary key must "
                "match InstrumentSpec.symbol."
            )
        validate_contract_prices(
            instrument.prices
        )

        validate_roll_events(
            instrument.roll_events
        )

        validate_execution_days(
            instrument.execution_days
        )

        if config is None:
            fast_spans = instrument.fast_spans
            volatility_span = (
                instrument.volatility_span
            )
            long_run_window = (
                instrument.long_run_window
            )
        else:
            fast_spans = config.fast_spans
            volatility_span = (
                config.volatility_span
            )
            long_run_window = (
                config.long_run_window
            )


        prepared_backtest = (
            prepare_point_in_time_combined_ewmac_backtest(
                prices=instrument.prices,
                initial_contract=(
                    instrument.initial_contract
                ),
                roll_events=(
                    instrument.roll_events
                ),
                execution_days=(
                    instrument.execution_days
                ),
                fast_spans=fast_spans,
                volatility_span=(
                    volatility_span
                ),
                long_run_window=(
                    long_run_window
                ),
            )
        )

        prepared[symbol] = (
            PreparedPortfolioInstrument(
                instrument_spec=(
                    instrument.instrument_spec
                ),
                prepared_backtest=(
                    prepared_backtest
                ),
            )
        )

    return prepared

def run_combined_ewmac_portfolio_backtest(
    initial_account_value: float,
    portfolio_spec: PortfolioSpec,
    instruments: dict[
        str,
        CombinedEWMACInstrumentInput,
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
    config: BacktestConfig | None = None,
) -> PortfolioSystemBacktestResult:
    if config is None:
        resolved_annual_volatility_target = (
            annual_volatility_target
        )

        resolved_position_buffer_fraction = (
            position_buffer_fraction
        )

        resolved_risk_policy = (
            risk_policy
        )

    else:
        if (
            annual_volatility_target is not None
            or position_buffer_fraction is not None
            or risk_policy is not None
        ):
            raise ValueError(
                "Do not combine BacktestConfig "
                "with legacy runner settings."
            )

        resolved_annual_volatility_target = (
            config.annual_volatility_target
        )

        resolved_position_buffer_fraction = (
            config.position_buffer_fraction
        )

        resolved_risk_policy = (
            config.risk_policy
        )
    prepared = (
        prepare_combined_ewmac_portfolio(
            instruments=instruments,
            config=config,
        )
    )

    days = run_prepared_portfolio_backtest(
        initial_account_value=(
            initial_account_value
        ),
        portfolio_spec=portfolio_spec,
        instruments=prepared,
        annual_volatility_target=(
            resolved_annual_volatility_target
        ),
        position_buffer_fraction=(
            resolved_position_buffer_fraction
        ),
        risk_policy=resolved_risk_policy,
    )
    return PortfolioSystemBacktestResult(
        prepared_instruments=prepared,
        days=days,
    )


