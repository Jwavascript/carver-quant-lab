from datetime import date

import pytest

from carver_quant.contract_aware_backtest import (
    ContractAwareBacktestDayInput,
)
from carver_quant.instrument import (
    InstrumentSpec,
)
from carver_quant.portfolio import (
    PortfolioSpec,
)
from carver_quant.portfolio_backtest import (
    PreparedPortfolioInstrument,
    run_prepared_portfolio_backtest,
)
from carver_quant.roll_execution import (
    ContractQuote,
)
from carver_quant.system_backtest import (
    PreparedEWMACBacktest,
)
from carver_quant.risk_guardrail import (
    PortfolioRiskPolicy,
)

from carver_quant.performance import (
    calculate_instrument_attribution,
    summarise_portfolio_performance,
)


def make_day(
    previous_price,
    current_price,
    price_volatility,
    forecast,
    contract,
    margin_per_contract_base=None,
):
    if margin_per_contract_base is None:
        margin_per_contract_base = {}

    return ContractAwareBacktestDayInput(
        previous_adjusted_price=(
            previous_price
        ),

        current_adjusted_price=(
            current_price
        ),

        daily_cash_vol_target=1000.0,

        price_volatility=(
            price_volatility
        ),

        forecast=forecast,

        quotes={
            contract: ContractQuote(
                bid=current_price,
                ask=current_price,
            )
        },

        commission_per_contract=0.0,

        roll_to_contract=None,

        slippage_ticks=0,

        fx_to_base=1.0,

        margin_per_contract_base=(
            margin_per_contract_base
        ),
    )

def make_prepared(
    contract,
    days,
):
    return PreparedEWMACBacktest(
        signals=[],
        initial_active_contract=contract,
        days=days,
        day_dates=[
            date(2026, 1, 3),
            date(2026, 1, 4),
        ],
    )

def test_two_instrument_pnl_is_combined_into_one_account():
    es = PreparedPortfolioInstrument(
        instrument_spec=InstrumentSpec(
            symbol="ES",
            currency="USD",
            multiplier=10.0,
            tick_size=0.25,
        ),
        prepared_backtest=make_prepared(
            contract="ESM6",
            days=[
                make_day(
                    previous_price=100.0,
                    current_price=100.0,
                    price_volatility=10.0,
                    forecast=10.0,
                    contract="ESM6",
                ),
                make_day(
                    previous_price=100.0,
                    current_price=102.0,
                    price_volatility=10.0,
                    forecast=10.0,
                    contract="ESM6",
                ),
            ],
        ),
    )

    zn = PreparedPortfolioInstrument(
        instrument_spec=InstrumentSpec(
            symbol="ZN",
            currency="USD",
            multiplier=10.0,
            tick_size=0.01,
        ),
        prepared_backtest=make_prepared(
            contract="ZNM6",
            days=[
                make_day(
                    previous_price=200.0,
                    current_price=200.0,
                    price_volatility=12.5,
                    forecast=10.0,
                    contract="ZNM6",
                ),
                make_day(
                    previous_price=200.0,
                    current_price=199.0,
                    price_volatility=12.5,
                    forecast=10.0,
                    contract="ZNM6",
                ),
            ],
        ),
    )

    portfolio = PortfolioSpec(
        instrument_weights={
            "ES": 0.5,
            "ZN": 0.5,
        },
        instrument_diversification_multiplier=1.0,
    )

    results = (
        run_prepared_portfolio_backtest(
            initial_account_value=100_000.0,
            portfolio_spec=portfolio,
            instruments={
                "ES": es,
                "ZN": zn,
            },
        )
    )

    attribution = (
        calculate_instrument_attribution(
            results
        )
    )
    assert (
        attribution["ES"].gross_pnl
        == pytest.approx(100.0)
    )

    assert (
        attribution["ZN"].gross_pnl
        == pytest.approx(-40.0)
    )

    assert (
        attribution["ES"].net_pnl
        == pytest.approx(100.0)
    )

    assert (
        attribution["ZN"].net_pnl
        == pytest.approx(-40.0)
    )

    summary = (
        summarise_portfolio_performance(
            results
        )
    )

    assert (
    summary.total_gross_pnl
    == pytest.approx(60.0)
    )

    assert (
        summary.total_trading_cost
        == pytest.approx(0.0)
    )

    assert (
        summary.total_net_pnl
        == pytest.approx(60.0)
    )

    assert (
        summary.total_return
        == pytest.approx(
            60.0 / 100_000.0
        )
    )



    assert len(results) == 2

    # Day 1:
    # ES target = 5
    # ZN target = 4
    assert (
        results[0]
        .instrument_results["ES"]
        .target_position
        == 5
    )

    assert (
        results[0]
        .instrument_results["ZN"]
        .target_position
        == 4
    )

    assert (
        results[0].closing_account_value
        == pytest.approx(
            100_000.0
        )
    )

    # Day 2:
    #
    # ES:
    # 5 contracts × +2 points × 10
    # = +100
    #
    # ZN:
    # 4 contracts × -1 point × 10
    # = -40
    #
    # portfolio = +60
    assert (
        results[1]
        .instrument_results["ES"]
        .gross_pnl
        == pytest.approx(100.0)
    )

    assert (
        results[1]
        .instrument_results["ZN"]
        .gross_pnl
        == pytest.approx(-40.0)
    )

    assert results[1].gross_pnl == pytest.approx(
        60.0
    )

    assert results[1].trading_cost == pytest.approx(
        0.0
    )

    assert results[1].net_pnl == pytest.approx(
        60.0
    )

    assert (
        results[1].closing_account_value
        == pytest.approx(
            100_060.0
        )
    )

def test_instrument_order_does_not_change_account_result():
    def build_instruments():
        es = PreparedPortfolioInstrument(
            instrument_spec=InstrumentSpec(
                symbol="ES",
                currency="USD",
                multiplier=10.0,
                tick_size=0.25,
            ),
            prepared_backtest=make_prepared(
                "ESM6",
                [
                    make_day(
                        100.0,
                        100.0,
                        10.0,
                        10.0,
                        "ESM6",
                    ),
                    make_day(
                        100.0,
                        102.0,
                        10.0,
                        10.0,
                        "ESM6",
                    ),
                ],
            ),
        )

        zn = PreparedPortfolioInstrument(
            instrument_spec=InstrumentSpec(
                symbol="ZN",
                currency="USD",
                multiplier=10.0,
                tick_size=0.01,
            ),
            prepared_backtest=make_prepared(
                "ZNM6",
                [
                    make_day(
                        200.0,
                        200.0,
                        12.5,
                        10.0,
                        "ZNM6",
                    ),
                    make_day(
                        200.0,
                        199.0,
                        12.5,
                        10.0,
                        "ZNM6",
                    ),
                ],
            ),
        )

        return es, zn

    portfolio = PortfolioSpec(
        instrument_weights={
            "ES": 0.5,
            "ZN": 0.5,
        },
        instrument_diversification_multiplier=1.0,
    )

    es, zn = build_instruments()

    forward = run_prepared_portfolio_backtest(
        initial_account_value=100_000.0,
        portfolio_spec=portfolio,
        instruments={
            "ES": es,
            "ZN": zn,
        },
    )

    es, zn = build_instruments()

    reversed_order = (
        run_prepared_portfolio_backtest(
            initial_account_value=100_000.0,
            portfolio_spec=portfolio,
            instruments={
                "ZN": zn,
                "ES": es,
            },
        )
    )

    assert (
        forward[-1].closing_account_value
        == pytest.approx(
            reversed_order[-1]
            .closing_account_value
        )
    )

    assert (
        forward[-1].net_pnl
        == pytest.approx(
            reversed_order[-1].net_pnl
        )
    )

def test_unsynchronized_instrument_dates_are_rejected():
    es = PreparedEWMACBacktest(
        signals=[],
        initial_active_contract="ESM6",
        days=[
            make_day(
                100.0,
                100.0,
                10.0,
                10.0,
                "ESM6",
            )
        ],
        day_dates=[
            date(2026, 1, 3),
        ],
    )

    zn = PreparedEWMACBacktest(
        signals=[],
        initial_active_contract="ZNM6",
        days=[
            make_day(
                200.0,
                200.0,
                10.0,
                10.0,
                "ZNM6",
            )
        ],
        day_dates=[
            date(2026, 1, 4),
        ],
    )

    portfolio = PortfolioSpec(
        instrument_weights={
            "ES": 0.5,
            "ZN": 0.5,
        },
        instrument_diversification_multiplier=1.0,
    )

    with pytest.raises(
        ValueError,
        match="synchronized",
    ):
        run_prepared_portfolio_backtest(
            initial_account_value=100_000.0,
            portfolio_spec=portfolio,
            instruments={
                "ES": PreparedPortfolioInstrument(
                    instrument_spec=InstrumentSpec(
                        symbol="ES",
                        currency="USD",
                        multiplier=10.0,
                        tick_size=0.25,
                    ),
                    prepared_backtest=es,
                ),
                "ZN": PreparedPortfolioInstrument(
                    instrument_spec=InstrumentSpec(
                        symbol="ZN",
                        currency="USD",
                        multiplier=10.0,
                        tick_size=0.01,
                    ),
                    prepared_backtest=zn,
                ),
            },
        )

def test_portfolio_runner_applies_position_buffering():
    prepared = PreparedEWMACBacktest(
        signals=[],
        initial_active_contract="TEST",
        days=[
            ContractAwareBacktestDayInput(
                previous_adjusted_price=100.0,
                current_adjusted_price=100.0,

                # 한 상품 weight=1, IDM=1이므로
                # 그대로 88 사용
                daily_cash_vol_target=88.0,

                price_volatility=1.0,
                forecast=15.0,

                quotes={
                    "TEST": ContractQuote(
                        bid=100.0,
                        ask=100.0,
                    )
                },

                commission_per_contract=0.0,
                roll_to_contract=None,
                slippage_ticks=0,
                fx_to_base=1.0,
            ),
        ],
        day_dates=[
            date(2026, 1, 3),
        ],
    )

    instrument = PreparedPortfolioInstrument(
        instrument_spec=InstrumentSpec(
            symbol="TEST",
            currency="USD",
            multiplier=10.0,
            tick_size=0.01,
        ),
        prepared_backtest=prepared,
    )

    portfolio = PortfolioSpec(
        instrument_weights={
            "TEST": 1.0,
        },
        instrument_diversification_multiplier=1.0,
    )

    no_buffer = (
        run_prepared_portfolio_backtest(
            initial_account_value=100_000.0,
            portfolio_spec=portfolio,
            instruments={
                "TEST": instrument,
            },
            position_buffer_fraction=None,
        )
    )

    buffered = (
        run_prepared_portfolio_backtest(
            initial_account_value=100_000.0,
            portfolio_spec=portfolio,
            instruments={
                "TEST": instrument,
            },
            position_buffer_fraction=0.10,
        )
    )

    no_buffer_result = (
        no_buffer[0]
        .instrument_results["TEST"]
    )

    buffered_result = (
        buffered[0]
        .instrument_results["TEST"]
    )

    # average position = 88 / (1 × 10)
    #                  = 8.8
    #
    # optimal unrounded
    # = 8.8 × 15 / 10
    # = 13.2
    #
    # no buffer:
    # round(13.2) = 13
    assert (
        no_buffer_result.target_position
        == 13
    )

    # buffer:
    # width = 8.8 × 0.10 = 0.88
    #
    # lower = round(13.2 - 0.88)
    #       = 12
    #
    # 현재 position=0이므로
    # optimal 13까지 가지 않고
    # lower edge인 12까지만 간다.
    assert (
        buffered_result.target_position
        == 12
    )

    assert (
        no_buffer_result.directional_trade
        == 13
    )

    assert (
        buffered_result.directional_trade
        == 12
    )

def test_portfolio_without_risk_policy_has_no_risk_snapshot():
    prepared = PreparedEWMACBacktest(
        signals=[],
        initial_active_contract="TEST",
        days=[
            make_day(
                previous_price=100.0,
                current_price=100.0,
                price_volatility=10.0,
                forecast=10.0,
                contract="TEST",
            )
        ],
        day_dates=[
            date(2026, 1, 3),
        ],
    )

    instrument = PreparedPortfolioInstrument(
        instrument_spec=InstrumentSpec(
            symbol="TEST",
            currency="USD",
            multiplier=10.0,
            tick_size=0.01,
        ),
        prepared_backtest=prepared,
    )

    portfolio = PortfolioSpec(
        instrument_weights={
            "TEST": 1.0,
        },
        instrument_diversification_multiplier=1.0,
    )

    results = run_prepared_portfolio_backtest(
        initial_account_value=100_000.0,
        portfolio_spec=portfolio,
        instruments={
            "TEST": instrument,
        },
        risk_policy=None,
    )

    assert (
        results[0].risk_snapshot
        is None
    )

def test_portfolio_risk_snapshot_uses_actual_position_quote_and_margin():
    prepared = PreparedEWMACBacktest(
        signals=[],
        initial_active_contract="TEST",
        days=[
            make_day(
                previous_price=100.0,
                current_price=100.0,
                price_volatility=10.0,
                forecast=10.0,
                contract="TEST",
                margin_per_contract_base={
                    "TEST": 500.0,
                },
            )
        ],
        day_dates=[
            date(2026, 1, 3),
        ],
    )

    instrument = PreparedPortfolioInstrument(
        instrument_spec=InstrumentSpec(
            symbol="TEST",
            currency="USD",
            multiplier=10.0,
            tick_size=0.01,
        ),
        prepared_backtest=prepared,
    )

    portfolio = PortfolioSpec(
        instrument_weights={
            "TEST": 1.0,
        },
        instrument_diversification_multiplier=1.0,
    )

    results = run_prepared_portfolio_backtest(
        initial_account_value=100_000.0,
        portfolio_spec=portfolio,
        instruments={
            "TEST": instrument,
        },
        risk_policy=PortfolioRiskPolicy(
            max_gross_leverage=1.0,
            max_margin_usage=0.50,
        ),
    )

    snapshot = (
        results[0].risk_snapshot
    )

    assert snapshot is not None

    assert (
        results[0]
        .instrument_results["TEST"]
        .target_position
        == 10
    )

    assert (
        snapshot.gross_notional_exposure
        == pytest.approx(
            10_000.0
        )
    )

    assert (
        snapshot.gross_leverage
        == pytest.approx(
            0.10
        )
    )

    assert (
        snapshot.margin_required
        == pytest.approx(
            5_000.0
        )
    )

    assert (
        snapshot.margin_usage
        == pytest.approx(
            0.05
        )
    )

def test_portfolio_rejects_gross_leverage_limit_breach():
    prepared = PreparedEWMACBacktest(
        signals=[],
        initial_active_contract="TEST",
        days=[
            make_day(
                previous_price=100.0,
                current_price=100.0,
                price_volatility=10.0,
                forecast=10.0,
                contract="TEST",
                margin_per_contract_base={
                    "TEST": 500.0,
                },
            )
        ],
        day_dates=[
            date(2026, 1, 3),
        ],
    )

    instrument = PreparedPortfolioInstrument(
        instrument_spec=InstrumentSpec(
            symbol="TEST",
            currency="USD",
            multiplier=10.0,
            tick_size=0.01,
        ),
        prepared_backtest=prepared,
    )

    portfolio = PortfolioSpec(
        instrument_weights={
            "TEST": 1.0,
        },
        instrument_diversification_multiplier=1.0,
    )

    with pytest.raises(
        ValueError,
        match="Gross leverage",
    ):
        run_prepared_portfolio_backtest(
            initial_account_value=100_000.0,
            portfolio_spec=portfolio,
            instruments={
                "TEST": instrument,
            },
            risk_policy=PortfolioRiskPolicy(
                max_gross_leverage=0.09,
                max_margin_usage=0.50,
            ),
        )

def test_portfolio_rejects_margin_usage_limit_breach():
    prepared = PreparedEWMACBacktest(
        signals=[],
        initial_active_contract="TEST",
        days=[
            make_day(
                previous_price=100.0,
                current_price=100.0,
                price_volatility=10.0,
                forecast=10.0,
                contract="TEST",
                margin_per_contract_base={
                    "TEST": 500.0,
                },
            )
        ],
        day_dates=[
            date(2026, 1, 3),
        ],
    )

    instrument = PreparedPortfolioInstrument(
        instrument_spec=InstrumentSpec(
            symbol="TEST",
            currency="USD",
            multiplier=10.0,
            tick_size=0.01,
        ),
        prepared_backtest=prepared,
    )

    portfolio = PortfolioSpec(
        instrument_weights={
            "TEST": 1.0,
        },
        instrument_diversification_multiplier=1.0,
    )

    with pytest.raises(
        ValueError,
        match="Margin usage",
    ):
        run_prepared_portfolio_backtest(
            initial_account_value=100_000.0,
            portfolio_spec=portfolio,
            instruments={
                "TEST": instrument,
            },
            risk_policy=PortfolioRiskPolicy(
                max_gross_leverage=1.0,
                max_margin_usage=0.04,
            ),
        )

def test_risk_policy_requires_margin_for_non_zero_position():
    prepared = PreparedEWMACBacktest(
        signals=[],
        initial_active_contract="TEST",
        days=[
            make_day(
                previous_price=100.0,
                current_price=100.0,
                price_volatility=10.0,
                forecast=10.0,
                contract="TEST",

                # margin intentionally omitted
            )
        ],
        day_dates=[
            date(2026, 1, 3),
        ],
    )

    instrument = PreparedPortfolioInstrument(
        instrument_spec=InstrumentSpec(
            symbol="TEST",
            currency="USD",
            multiplier=10.0,
            tick_size=0.01,
        ),
        prepared_backtest=prepared,
    )

    portfolio = PortfolioSpec(
        instrument_weights={
            "TEST": 1.0,
        },
        instrument_diversification_multiplier=1.0,
    )

    with pytest.raises(
        ValueError,
        match="Missing margin",
    ):
        run_prepared_portfolio_backtest(
            initial_account_value=100_000.0,
            portfolio_spec=portfolio,
            instruments={
                "TEST": instrument,
            },
            risk_policy=PortfolioRiskPolicy(
                max_gross_leverage=1.0,
                max_margin_usage=0.50,
            ),
        )