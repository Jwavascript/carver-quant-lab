from datetime import date, timedelta


import pytest


from carver_quant.backtest_config import (
    BacktestConfig,
)

from carver_quant.backtest_manifest import (
    build_backtest_manifest,
)

from carver_quant.backtest_result_bundle import (
    build_backtest_result_bundle,
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
    prepare_combined_ewmac_portfolio,
    run_combined_ewmac_portfolio_backtest,
)

from carver_quant.research_pipeline import (
    PointInTimeResearchSignalPoint,
)

from carver_quant.risk_guardrail import (
    PortfolioRiskPolicy,
)

from carver_quant.roll_execution import (
    ContractQuote,
)

from carver_quant.system_backtest import (
    ExecutionMarketDay,
)

TEST_FX_USD_TO_KRW = 1350.0


def make_v1_instrument(
    symbol: str,
    contract: str,
    values: list[float],
) -> CombinedEWMACInstrumentInput:
    start = date(
        2026,
        1,
        1,
    )

    prices = [
        ContractPrice(
            date=(
                start
                + timedelta(
                    days=index
                )
            ),
            contract=contract,
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

            # config에 annual target이 있으므로
            # production path에서는 이것보다
            # account 기반 dynamic target이
            # canonical이다.
            daily_cash_vol_target=1000.0,

            quotes={
                contract: ContractQuote(
                    bid=value - 0.25,
                    ask=value + 0.25,
                ),
            },

            commission_per_contract=2.0,

            fx_to_base=(
                TEST_FX_USD_TO_KRW
            ),

            slippage_ticks=1,

            margin_per_contract_base={
                contract: 100_000.0,
            },
        )
        for index, value
        in enumerate(values)
        if index >= 3
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

def test_v1_final_acceptance():
    es = make_v1_instrument(
        symbol="ES",
        contract="ESM6",
        values=[
            100.0,
            101.0,
            103.0,
            106.0,
            110.0,
            115.0,
            121.0,
            128.0,
        ],
    )

    zn = make_v1_instrument(
        symbol="ZN",
        contract="ZNM6",
        values=[
            200.0,
            199.0,
            197.0,
            194.0,
            190.0,
            185.0,
            179.0,
            172.0,
        ],
    )

    instruments = {
        "ES": es,
        "ZN": zn,
    }

    portfolio = PortfolioSpec(
        instrument_weights={
            "ES": 0.5,
            "ZN": 0.5,
        },

        instrument_diversification_multiplier=1.2,
    )

    config = BacktestConfig(
        fast_spans=(
            2,
            4,
            8,
            16,
            32,
            64,
        ),

        volatility_span=32,

        long_run_window=2560,

        annual_volatility_target=0.20,

        position_buffer_fraction=0.10,

        risk_policy=PortfolioRiskPolicy(
            max_gross_leverage=5.0,
            max_margin_usage=0.50,
        ),
    )

    # =====================================
    # 1. Production signal preparation
    # =====================================

    prepared = (
        prepare_combined_ewmac_portfolio(
            instruments=instruments,
            config=config,
        )
    )

    assert set(
        prepared.keys()
    ) == {
        "ES",
        "ZN",
    }

    for instrument in prepared.values():
        signals = (
            instrument
            .prepared_backtest
            .signals
        )

        assert signals

        # Production path는 반드시 PIT
        assert all(
            isinstance(
                signal,
                PointInTimeResearchSignalPoint,
            )
            for signal in signals
        )

    # =====================================
    # 2. Full portfolio backtest
    # =====================================

    initial_account_value = (
        100_000_000.0
    )

    result = (
        run_combined_ewmac_portfolio_backtest(
            initial_account_value=(
                initial_account_value
            ),

            portfolio_spec=portfolio,

            instruments=instruments,

            config=config,
        )
    )

    assert result.days

    # =====================================
    # 3. Daily accounting invariants
    # =====================================

    for index, day in enumerate(
        result.days
    ):
        instrument_gross = sum(
            instrument.gross_pnl
            for instrument
            in day.instrument_results.values()
        )

        instrument_cost = sum(
            instrument.total_trading_cost
            for instrument
            in day.instrument_results.values()
        )

        instrument_net = sum(
            instrument.net_pnl
            for instrument
            in day.instrument_results.values()
        )

        assert (
            day.gross_pnl
            == pytest.approx(
                instrument_gross
            )
        )

        assert (
            day.trading_cost
            == pytest.approx(
                instrument_cost
            )
        )

        assert (
            day.net_pnl
            == pytest.approx(
                instrument_net
            )
        )

        assert (
            day.net_pnl
            == pytest.approx(
                day.gross_pnl
                - day.trading_cost
            )
        )

        assert (
            day.closing_account_value
            == pytest.approx(
                day.opening_account_value
                + day.net_pnl
            )
        )

        if index == 0:
            assert (
                day.opening_account_value
                == pytest.approx(
                    initial_account_value
                )
            )

        else:
            previous_day = (
                result.days[
                    index - 1
                ]
            )

            assert (
                day.opening_account_value
                == pytest.approx(
                    previous_day
                    .closing_account_value
                )
            )

    # =====================================
    # 4. Execution really incurred costs
    # =====================================

    assert any(
        day.trading_cost > 0
        for day in result.days
    )

    # =====================================
    # 5. Risk snapshots are produced
    # =====================================

    assert all(
        day.risk_snapshot is not None
        for day in result.days
    )

    for day in result.days:
        snapshot = day.risk_snapshot

        assert snapshot is not None

        assert (
            snapshot.gross_leverage
            <= 5.0
        )

        assert (
            snapshot.margin_usage
            <= 0.50
        )

    # =====================================
    # 6. Manifest
    # =====================================

    manifest = build_backtest_manifest(
        initial_account_value=(
            initial_account_value
        ),

        account_base_currency="KRW",

        portfolio_spec=portfolio,

        instruments=instruments,

        config=config,
    )

    assert (
        manifest.account_base_currency
        == "KRW"
    )

    assert (
        len(
            manifest
            .input_fingerprint_sha256
        )
        == 64
    )

    assert tuple(
        instrument.symbol
        for instrument
        in manifest.instruments
    ) == (
        "ES",
        "ZN",
    )

    # =====================================
    # 7. Result bundle / performance
    # =====================================

    bundle = (
        build_backtest_result_bundle(
            result=result,
            manifest=manifest,
            code_version="v1-acceptance-test",
        )
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
        .total_gross_pnl
        == pytest.approx(
            sum(
                day.gross_pnl
                for day in result.days
            )
        )
    )

    assert (
        bundle.performance
        .total_trading_cost
        == pytest.approx(
            sum(
                day.trading_cost
                for day in result.days
            )
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

    # Account ledger와
    # PerformanceSummary가 일치
    assert (
        bundle.performance
        .total_net_pnl
        == pytest.approx(
            bundle.final_account_value
            - initial_account_value
        )
    )

    assert (
        len(
            bundle
            .result_fingerprint_sha256
        )
        == 64
    )

