from dataclasses import dataclass
import math
from statistics import mean, stdev


from carver_quant.portfolio_backtest import (
    PortfolioBacktestDayResult,
)


TRADING_DAYS_PER_YEAR = 256


@dataclass(frozen=True)
class PerformanceSummary:
    total_gross_pnl: float
    total_trading_cost: float
    total_net_pnl: float

    total_return: float

    annualised_mean_return: float

    annualised_volatility: (
        float | None
    )

    sharpe_ratio: (
        float | None
    )

    max_drawdown: float

    average_drawdown: float


def calculate_daily_net_returns(
    days: list[
        PortfolioBacktestDayResult
    ],
) -> list[float]:
    returns = []

    for day in days:
        if (
            not math.isfinite(
                day.opening_account_value
            )
            or day.opening_account_value <= 0
        ):
            raise ValueError(
                "opening_account_value must "
                "be finite and positive."
            )

        if not math.isfinite(
            day.net_pnl
        ):
            raise ValueError(
                "net_pnl must be finite."
            )

        daily_return = (
            day.net_pnl
            / day.opening_account_value
        )

        returns.append(
            daily_return
        )

    return returns


def calculate_annualised_mean_return(
    daily_returns: list[float],
) -> float:
    if not daily_returns:
        raise ValueError(
            "daily_returns must not be empty."
        )

    return (
        mean(daily_returns)
        * TRADING_DAYS_PER_YEAR
    )


def calculate_annualised_volatility(
    daily_returns: list[float],
) -> float | None:
    if len(daily_returns) < 2:
        return None

    return (
        stdev(daily_returns)
        * math.sqrt(
            TRADING_DAYS_PER_YEAR
        )
    )


def calculate_sharpe_ratio(
    daily_returns: list[float],
) -> float | None:
    annualised_volatility = (
        calculate_annualised_volatility(
            daily_returns
        )
    )

    if (
        annualised_volatility is None
        or annualised_volatility == 0
    ):
        return None

    annualised_return = (
        calculate_annualised_mean_return(
            daily_returns
        )
    )

    return (
        annualised_return
        / annualised_volatility
    )


def calculate_drawdowns(
    equity_curve: list[float],
) -> list[float]:
    if not equity_curve:
        raise ValueError(
            "equity_curve must not be empty."
        )

    if (
        not math.isfinite(
            equity_curve[0]
        )
        or equity_curve[0] <= 0
    ):
        raise ValueError(
            "Initial equity must be "
            "finite and positive."
        )

    running_peak = equity_curve[0]

    drawdowns = []

    for equity in equity_curve:
        if not math.isfinite(equity):
            raise ValueError(
                "Equity values must be finite."
            )

        if equity > running_peak:
            running_peak = equity

        drawdown = (
            equity - running_peak
        ) / running_peak

        drawdowns.append(
            drawdown
        )

    return drawdowns


def summarise_portfolio_performance(
    days: list[
        PortfolioBacktestDayResult
    ],
) -> PerformanceSummary:
    if not days:
        raise ValueError(
            "days must not be empty."
        )

    daily_returns = (
        calculate_daily_net_returns(
            days
        )
    )

    initial_account_value = (
        days[0].opening_account_value
    )

    final_account_value = (
        days[-1].closing_account_value
    )

    total_return = (
        final_account_value
        / initial_account_value
        - 1.0
    )

    equity_curve = [
        initial_account_value,
        *[
            day.closing_account_value
            for day in days
        ],
    ]

    drawdowns = (
        calculate_drawdowns(
            equity_curve
        )
    )

    # 첫 값은 backtest 시작점이므로
    # 실제 trading day 평균에서는 제외한다.
    daily_drawdowns = (
        drawdowns[1:]
    )

    return PerformanceSummary(
        total_gross_pnl=sum(
            day.gross_pnl
            for day in days
        ),

        total_trading_cost=sum(
            day.trading_cost
            for day in days
        ),

        total_net_pnl=sum(
            day.net_pnl
            for day in days
        ),

        total_return=total_return,

        annualised_mean_return=(
            calculate_annualised_mean_return(
                daily_returns
            )
        ),

        annualised_volatility=(
            calculate_annualised_volatility(
                daily_returns
            )
        ),

        sharpe_ratio=(
            calculate_sharpe_ratio(
                daily_returns
            )
        ),

        max_drawdown=min(
            daily_drawdowns
        ),

        average_drawdown=mean(
            daily_drawdowns
        ),
    )

@dataclass(frozen=True)
class InstrumentPerformanceAttribution:
    symbol: str

    gross_pnl: float
    trading_cost: float
    net_pnl: float

    total_directional_blocks_traded: float

    annualised_directional_blocks_traded: float

    average_absolute_position: float

    afts_turnover: float | None

    systematic_trading_round_trip_turnover: (
        float | None
    )

def calculate_afts_turnover(
    directional_trades: list[int],
    absolute_positions: list[float],
) -> float | None:
    if not directional_trades:
        raise ValueError(
            "directional_trades must "
            "not be empty."
        )

    if (
        len(directional_trades)
        != len(absolute_positions)
    ):
        raise ValueError(
            "Trade and position lengths "
            "must match."
        )

    if not all(
        math.isfinite(value)
        and value >= 0
        for value in absolute_positions
    ):
        raise ValueError(
            "absolute_positions must be "
            "finite and non-negative."
        )

    total_blocks_traded = sum(
        abs(trade)
        for trade in directional_trades
    )

    average_absolute_position = mean(
        absolute_positions
    )

    if average_absolute_position == 0:
        return None

    annualised_blocks_traded = (
        total_blocks_traded
        * TRADING_DAYS_PER_YEAR
        / len(directional_trades)
    )

    return (
        annualised_blocks_traded
        / average_absolute_position
    )

def calculate_systematic_trading_turnover(
    directional_trades: list[int],
    absolute_positions: list[float],
) -> float | None:
    afts_turnover = (
        calculate_afts_turnover(
            directional_trades=(
                directional_trades
            ),
            absolute_positions=(
                absolute_positions
            ),
        )
    )

    if afts_turnover is None:
        return None

    return (
        afts_turnover / 2.0
    )

def calculate_instrument_attribution(
    days: list[
        PortfolioBacktestDayResult
    ],
) -> dict[
    str,
    InstrumentPerformanceAttribution,
]:
    if not days:
        raise ValueError(
            "days must not be empty."
        )

    symbols = set(
        days[0]
        .instrument_results
        .keys()
    )

    for day in days:
        if (
            set(
                day.instrument_results.keys()
            )
            != symbols
        ):
            raise ValueError(
                "Instrument symbols must "
                "match across all days."
            )

    attribution = {}

    for symbol in sorted(symbols):
        gross_pnl = 0.0
        trading_cost = 0.0
        net_pnl = 0.0

        directional_trades = []
        absolute_positions = []

        for day in days:
            result = (
                day.instrument_results[
                    symbol
                ]
            )

            gross_pnl += (
                result.gross_pnl
            )

            trading_cost += (
                result.total_trading_cost
            )

            net_pnl += (
                result.net_pnl
            )

            directional_trades.append(
                result.directional_trade
            )

            absolute_position = sum(
                abs(position)
                for position
                in (
                    result
                    .new_contract_positions
                    .values()
                )
            )

            absolute_positions.append(
                absolute_position
            )

        total_blocks_traded = sum(
            abs(trade)
            for trade in directional_trades
        )

        annualised_blocks_traded = (
            total_blocks_traded
            * TRADING_DAYS_PER_YEAR
            / len(days)
        )

        average_absolute_position = mean(
            absolute_positions
        )

        attribution[symbol] = (
            InstrumentPerformanceAttribution(
                symbol=symbol,

                gross_pnl=gross_pnl,

                trading_cost=(
                    trading_cost
                ),

                net_pnl=net_pnl,

                total_directional_blocks_traded=(
                    total_blocks_traded
                ),

                annualised_directional_blocks_traded=(
                    annualised_blocks_traded
                ),

                average_absolute_position=(
                    average_absolute_position
                ),

                afts_turnover=(
                    calculate_afts_turnover(
                        directional_trades=(
                            directional_trades
                        ),
                        absolute_positions=(
                            absolute_positions
                        ),
                    )
                ),

                systematic_trading_round_trip_turnover=(
                    calculate_systematic_trading_turnover(
                        directional_trades=(
                            directional_trades
                        ),
                        absolute_positions=(
                            absolute_positions
                        ),
                    )
                ),
            )
        )

    return attribution