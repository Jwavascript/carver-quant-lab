from dataclasses import (
    dataclass,
    field,
)
from datetime import date


from carver_quant.contract_aware_backtest import (
    ContractAwareBacktestDayInput,
    run_contract_aware_backtest,
)
from carver_quant.forecast import EWMACConfig
from carver_quant.futures_data import (
    ContractPrice,
    RollEvent,
)
from carver_quant.instrument import InstrumentSpec
from carver_quant.research_pipeline import (
    PointInTimeResearchSignalPoint,
    ResearchSignalPoint,
    build_combined_ewmac_research_signals,
    build_ewmac_research_signals,
    build_point_in_time_combined_ewmac_signals,
)
from carver_quant.roll_execution import ContractQuote


@dataclass(frozen=True)
class ExecutionMarketDay:
    date: date

    daily_cash_vol_target: float

    quotes: dict[str, ContractQuote]

    commission_per_contract: float

    fx_to_base: float = 1.0

    slippage_ticks: int = 0

    margin_per_contract_base: dict[
        str,
        float,
    ] = field(
        default_factory=dict
    )


@dataclass(frozen=True)
class PreparedEWMACBacktest:
    signals: list[
        ResearchSignalPoint
        | PointInTimeResearchSignalPoint
    ]

    initial_active_contract: str

    days: list[
        ContractAwareBacktestDayInput
    ]

    day_dates: list[date]

def _prepare_backtest_from_signals(
        
    signals: list[ResearchSignalPoint],
    roll_events: list[RollEvent],
    execution_days: list[ExecutionMarketDay],
) -> PreparedEWMACBacktest:
    
    backtest_days = []
    day_dates = []

    execution_by_date: dict[
        date,
        ExecutionMarketDay,
    ] = {}

    for execution_day in execution_days:
        if execution_day.date in execution_by_date:
            raise ValueError(
                "Duplicate execution market date."
            )

        execution_by_date[
            execution_day.date
        ] = execution_day

    roll_by_date = {
        roll.date: roll
        for roll in roll_events
    }

    backtest_days: list[
        ContractAwareBacktestDayInput
    ] = []

    initial_active_contract = None

    for index in range(
        1,
        len(signals),
    ):
        previous_signal = signals[
            index - 1
        ]

        current_signal = signals[
            index
        ]

        # 전일 signal이 아직 warm-up 중이면
        # 오늘 거래할 수 없다.
        if (
            previous_signal.price_volatility
            is None
            or previous_signal.forecast
            is None
        ):
            continue

        # 오늘 실제 체결에 필요한
        # bid / ask 등의 execution data가 있어야 한다.
        if (
            current_signal.date
            not in execution_by_date
        ):
            raise ValueError(
                "Execution market data is missing "
                f"for {current_signal.date}."
            )

        execution_day = execution_by_date[
            current_signal.date
        ]

        # 실제 backtest를 시작하기 직전
        # 보유해야 하는 active contract.
        if initial_active_contract is None:
            initial_active_contract = (
                previous_signal.active_contract
            )

        roll_event = roll_by_date.get(
            current_signal.date
        )

        if roll_event is None:
            roll_to_contract = None
        else:
            roll_to_contract = (
                roll_event.new_contract
            )

        backtest_day = (
            ContractAwareBacktestDayInput(
                # t-1 → t 가격 변화로
                # 오늘 gross P&L 계산
                previous_adjusted_price=(
                    previous_signal.adjusted_price
                ),
                current_adjusted_price=(
                    current_signal.adjusted_price
                ),

                # 오늘 계좌 risk budget
                daily_cash_vol_target=(
                    execution_day
                    .daily_cash_vol_target
                ),

                # 중요:
                # t signal이 아니라
                # t-1에서 이미 알고 있던 값
                price_volatility=(
                    previous_signal
                    .price_volatility
                ),

                forecast=(
                    previous_signal.forecast
                ),

                # 실제 오늘 주문을 체결하기 위한
                # bid / ask
                quotes=execution_day.quotes,

                commission_per_contract=(
                    execution_day
                    .commission_per_contract
                ),

                roll_to_contract=(
                    roll_to_contract
                ),

                slippage_ticks=(
                    execution_day
                    .slippage_ticks
                ),

                fx_to_base=(
                    execution_day.fx_to_base
                ),
                margin_per_contract_base=(
                    execution_day
                    .margin_per_contract_base
                ),
            )
        )

        backtest_days.append(
            backtest_day
        )
        day_dates.append(
            current_signal.date
        )

    if not backtest_days:
        raise ValueError(
            "No tradable signals are available."
        )

    assert initial_active_contract is not None

    return PreparedEWMACBacktest(
        signals=signals,
        initial_active_contract=(
            initial_active_contract
        ),
        days=backtest_days,
        day_dates=day_dates,
    )

def _prepare_backtest_from_point_in_time_signals(
    pit_signals: list[
        PointInTimeResearchSignalPoint
    ],
    continuous_signals: list[
        ResearchSignalPoint
    ],
    roll_events: list[RollEvent],
    execution_days: list[
        ExecutionMarketDay
    ],
) -> PreparedEWMACBacktest:

    if not pit_signals:
        raise ValueError(
            "pit_signals must not be empty."
        )

    # ---------------------------------
    # P&L 전용 continuous price lookup
    # ---------------------------------

    continuous_by_date = {
        signal.date: signal
        for signal in continuous_signals
    }

    # ---------------------------------
    # 실제 execution data lookup
    # ---------------------------------

    execution_by_date: dict[
        date,
        ExecutionMarketDay,
    ] = {}

    for execution_day in execution_days:
        if (
            execution_day.date
            in execution_by_date
        ):
            raise ValueError(
                "Duplicate execution market date."
            )

        execution_by_date[
            execution_day.date
        ] = execution_day

    roll_by_date = {
        roll.date: roll
        for roll in roll_events
    }

    backtest_days: list[
        ContractAwareBacktestDayInput
    ] = []

    day_dates: list[date] = []

    initial_active_contract = None

    # =================================
    # REPLAY LOOP
    # =================================

    for index in range(
        1,
        len(pit_signals),
    ):
        previous_pit = (
            pit_signals[index - 1]
        )

        current_pit = (
            pit_signals[index]
        )

        # ---------------------------------
        # t-1 signal warm-up 확인
        # ---------------------------------

        if (
            previous_pit.price_volatility
            is None
            or previous_pit.forecast
            is None
        ):
            continue

        current_date = (
            current_pit.as_of_date
        )

        previous_date = (
            previous_pit.as_of_date
        )

        # ---------------------------------
        # 오늘 execution data
        # ---------------------------------

        execution_day = (
            execution_by_date.get(
                current_date
            )
        )

        if execution_day is None:
            raise ValueError(
                "Execution market data is "
                "missing for "
                f"{current_date}."
            )

        # ---------------------------------
        # P&L continuous price
        #
        # 중요:
        # PIT snapshot adjusted price를
        # 날짜 사이에서 빼지 않는다.
        # ---------------------------------

        previous_continuous = (
            continuous_by_date.get(
                previous_date
            )
        )

        current_continuous = (
            continuous_by_date.get(
                current_date
            )
        )

        if (
            previous_continuous is None
            or current_continuous is None
        ):
            raise ValueError(
                "Continuous adjusted price "
                "is missing for replay."
            )

        # ---------------------------------
        # 최초 active contract
        # ---------------------------------

        if initial_active_contract is None:
            initial_active_contract = (
                previous_pit
                .active_contract
            )

        # ---------------------------------
        # 오늘 roll 여부
        # ---------------------------------

        roll_event = roll_by_date.get(
            current_date
        )

        if roll_event is None:
            roll_to_contract = None
        else:
            roll_to_contract = (
                roll_event.new_contract
            )

        # ---------------------------------
        # Replay day 생성
        # ---------------------------------

        backtest_day = (
            ContractAwareBacktestDayInput(
                # P&L:
                # continuous path 사용
                previous_adjusted_price=(
                    previous_continuous
                    .adjusted_price
                ),

                current_adjusted_price=(
                    current_continuous
                    .adjusted_price
                ),

                daily_cash_vol_target=(
                    execution_day
                    .daily_cash_vol_target
                ),

                # Signal:
                # 반드시 t-1 PIT 값 사용
                price_volatility=(
                    previous_pit
                    .price_volatility
                ),

                forecast=(
                    previous_pit.forecast
                ),

                quotes=(
                    execution_day.quotes
                ),

                commission_per_contract=(
                    execution_day
                    .commission_per_contract
                ),

                roll_to_contract=(
                    roll_to_contract
                ),

                slippage_ticks=(
                    execution_day
                    .slippage_ticks
                ),

                fx_to_base=(
                    execution_day.fx_to_base
                ),

                margin_per_contract_base=(
                    execution_day
                    .margin_per_contract_base
                ),
            )
        )

        backtest_days.append(
            backtest_day
        )

        day_dates.append(
            current_date
        )

    if not backtest_days:
        raise ValueError(
            "No tradable point-in-time "
            "signals are available."
        )

    assert (
        initial_active_contract
        is not None
    )

    return PreparedEWMACBacktest(
        signals=pit_signals,

        initial_active_contract=(
            initial_active_contract
        ),

        days=backtest_days,

        day_dates=day_dates,
    )

def prepare_ewmac_backtest(
    prices: list[ContractPrice],
    initial_contract: str,
    roll_events: list[RollEvent],
    execution_days: list[ExecutionMarketDay],
    ewmac_config: EWMACConfig,
    volatility_span: int = 32,
) -> PreparedEWMACBacktest:
    signals = build_ewmac_research_signals(
        prices=prices,
        initial_contract=initial_contract,
        roll_events=roll_events,
        ewmac_config=ewmac_config,
        volatility_span=volatility_span,
    )

    return _prepare_backtest_from_signals(
        signals=signals,
        roll_events=roll_events,
        execution_days=execution_days,
    )


def run_ewmac_system_backtest(
    initial_account_value: float,
    prices: list[ContractPrice],
    initial_contract: str,
    roll_events: list[RollEvent],
    execution_days: list[ExecutionMarketDay],
    ewmac_config: EWMACConfig,
    instrument_spec: InstrumentSpec,
    volatility_span: int = 32,
):
    prepared = prepare_ewmac_backtest(
        prices=prices,
        initial_contract=initial_contract,
        roll_events=roll_events,
        execution_days=execution_days,
        ewmac_config=ewmac_config,
        volatility_span=volatility_span,
    )

    # v1 integrated system은 warm-up 이후
    # flat 상태에서 시작한다.
    return run_contract_aware_backtest(
        initial_account_value=(
            initial_account_value
        ),
        initial_position=0,
        initial_contract_positions={},
        initial_active_contract=(
            prepared.initial_active_contract
        ),
        days=prepared.days,
        instrument_spec=instrument_spec,
    )

def prepare_combined_ewmac_backtest(
    prices: list[ContractPrice],
    initial_contract: str,
    roll_events: list[RollEvent],
    execution_days: list[ExecutionMarketDay],
    fast_spans: tuple[int, ...] = (
        2,
        4,
        8,
        16,
        32,
        64,
    ),
    volatility_span: int = 32,
    long_run_window: int = 2560,
) -> PreparedEWMACBacktest:

    signals = (
        build_combined_ewmac_research_signals(
            prices=prices,
            initial_contract=initial_contract,
            roll_events=roll_events,
            fast_spans=fast_spans,
            volatility_span=volatility_span,
            long_run_window=long_run_window,
        )
    )

    return _prepare_backtest_from_signals(
        signals=signals,
        roll_events=roll_events,
        execution_days=execution_days,
    )

def prepare_point_in_time_combined_ewmac_backtest(
    prices: list[ContractPrice],
    initial_contract: str,
    roll_events: list[RollEvent],
    execution_days: list[
        ExecutionMarketDay
    ],
    fast_spans: tuple[int, ...] = (
        2,
        4,
        8,
        16,
        32,
        64,
    ),
    volatility_span: int = 32,
    long_run_window: int = 2560,
) -> PreparedEWMACBacktest:

    # ---------------------------------
    # SIGNAL PATH
    #
    # 각 날짜에서 그때까지 알려진
    # 정보만 이용한다.
    # ---------------------------------

    pit_signals = (
        build_point_in_time_combined_ewmac_signals(
            prices=prices,
            initial_contract=(
                initial_contract
            ),
            roll_events=roll_events,
            fast_spans=fast_spans,
            volatility_span=(
                volatility_span
            ),
            long_run_window=(
                long_run_window
            ),
        )
    )

    # ---------------------------------
    # P&L PRICE PATH
    #
    # 전체 back-adjusted series를 만들지만
    # forecast / volatility는 여기서
    # 절대 사용하지 않는다.
    #
    # 오직 adjacent adjusted-price
    # difference용이다.
    # ---------------------------------

    continuous_signals = (
        build_combined_ewmac_research_signals(
            prices=prices,
            initial_contract=(
                initial_contract
            ),
            roll_events=roll_events,
            fast_spans=fast_spans,
            volatility_span=(
                volatility_span
            ),
            long_run_window=(
                long_run_window
            ),
        )
    )

    return (
        _prepare_backtest_from_point_in_time_signals(
            pit_signals=pit_signals,
            continuous_signals=(
                continuous_signals
            ),
            roll_events=roll_events,
            execution_days=(
                execution_days
            ),
        )
    )