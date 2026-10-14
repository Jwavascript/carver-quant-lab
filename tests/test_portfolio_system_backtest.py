from datetime import date, timedelta

import pytest

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
from carver_quant.roll_execution import (
    ContractQuote,
)
from carver_quant.system_backtest import (
    ExecutionMarketDay,
)
from carver_quant.research_pipeline import (
    PointInTimeResearchSignalPoint,
)

from carver_quant.backtest_config import (
    BacktestConfig,
)



def make_instrument_input(
    symbol: str,
    contract: str,
    values: list[float],
) -> CombinedEWMACInstrumentInput:
    start = date(2026, 1, 1)

    prices = [
        ContractPrice(
            date=start + timedelta(
                days=index
            ),
            contract=contract,
            close=value,
        )
        for index, value
        in enumerate(values)
    ]

    execution_days = [
        ExecutionMarketDay(
            date=start + timedelta(
                days=index
            ),

            # 아직은 account-level target을
            # 외부에서 고정값으로 공급한다.
            daily_cash_vol_target=1000.0,

            quotes={
                contract: ContractQuote(
                    bid=value,
                    ask=value,
                )
            },

            commission_per_contract=0.0,

            fx_to_base=1.0,

            slippage_ticks=0,
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
            tick_size=0.01,
        ),
        prices=prices,
        initial_contract=contract,
        roll_events=[],
        execution_days=execution_days,
    )

def test_raw_prices_to_multi_instrument_account_end_to_end():
    es = make_instrument_input(
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

    zn = make_instrument_input(
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

    portfolio = PortfolioSpec(
        instrument_weights={
            "ES": 0.5,
            "ZN": 0.5,
        },
        instrument_diversification_multiplier=1.2,
    )

    result = (
        run_combined_ewmac_portfolio_backtest(
            initial_account_value=100_000.0,
            portfolio_spec=portfolio,
            instruments={
                "ES": es,
                "ZN": zn,
            },
        )
    )

    assert len(result.days) == 5

    first_day = result.days[0]

    es_result = (
        first_day
        .instrument_results["ES"]
    )

    zn_result = (
        first_day
        .instrument_results["ZN"]
    )

    # ES 상승 추세
    assert es_result.target_position > 0

    # ZN 하락 추세
    assert zn_result.target_position < 0

    # 입력을 완전히 대칭으로 만들었으므로
    # position의 절대값도 같아야 한다.
    assert abs(
        es_result.target_position
    ) == abs(
        zn_result.target_position
    )

    for day in result.days:
        assert (
            day.closing_account_value
            == pytest.approx(
                day.opening_account_value
                + day.net_pnl
            )
        )

        instrument_gross = sum(
            instrument_result.gross_pnl
            for instrument_result
            in day.instrument_results.values()
        )

        assert day.gross_pnl == pytest.approx(
            instrument_gross
        )

    # ES long + 상승,
    # ZN short + 하락이므로
    # cost가 0인 이 예제에서는
    # 최종 계좌가 증가해야 한다.
    assert (
        result.days[-1]
        .closing_account_value
        > 100_000.0
    )

def test_raw_portfolio_result_is_independent_of_instrument_order():
    es = make_instrument_input(
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

    zn = make_instrument_input(
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

    portfolio = PortfolioSpec(
        instrument_weights={
            "ES": 0.5,
            "ZN": 0.5,
        },
        instrument_diversification_multiplier=1.2,
    )

    forward = (
        run_combined_ewmac_portfolio_backtest(
            initial_account_value=100_000.0,
            portfolio_spec=portfolio,
            instruments={
                "ES": es,
                "ZN": zn,
            },
        )
    )

    reverse = (
        run_combined_ewmac_portfolio_backtest(
            initial_account_value=100_000.0,
            portfolio_spec=portfolio,
            instruments={
                "ZN": zn,
                "ES": es,
            },
        )
    )

    

    assert (
        forward.days[-1]
        .closing_account_value
        == pytest.approx(
            reverse.days[-1]
            .closing_account_value
        )
    )

    assert (
        forward.days[-1].net_pnl
        == pytest.approx(
            reverse.days[-1].net_pnl
        )
    )

def test_instrument_dictionary_key_must_match_spec_symbol():
    es = make_instrument_input(
        symbol="ES",
        contract="ESM6",
        values=[
            100.0,
            101.0,
            103.0,
            106.0,
        ],
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
        run_combined_ewmac_portfolio_backtest(
            initial_account_value=100_000.0,
            portfolio_spec=portfolio,
            instruments={
                "WRONG": es,
            },
        )

def test_portfolio_risk_target_is_derived_from_account_value():
    es = make_instrument_input(
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

    zn = make_instrument_input(
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

    portfolio = PortfolioSpec(
        instrument_weights={
            "ES": 0.5,
            "ZN": 0.5,
        },
        instrument_diversification_multiplier=1.2,
    )

    result = (
        run_combined_ewmac_portfolio_backtest(
            initial_account_value=100_000.0,
            portfolio_spec=portfolio,
            instruments={
                "ES": es,
                "ZN": zn,
            },
            annual_volatility_target=0.20,
        )
    )

    first_day = result.days[0]

    # 100,000 × 20% / 16
    assert (
        first_day
        .account_daily_cash_vol_target
        == pytest.approx(
            1_250.0
        )
    )

    # 각 상품:
    # 1,250 × 0.5 × 1.2
    # = 750
    assert (
        first_day
        .instrument_cash_vol_targets["ES"]
        == pytest.approx(
            750.0
        )
    )

    assert (
        first_day
        .instrument_cash_vol_targets["ZN"]
        == pytest.approx(
            750.0
        )
    )

def test_next_day_risk_target_uses_previous_closing_account():
    es = make_instrument_input(
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

    zn = make_instrument_input(
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

    portfolio = PortfolioSpec(
        instrument_weights={
            "ES": 0.5,
            "ZN": 0.5,
        },
        instrument_diversification_multiplier=1.2,
    )

    result = (
        run_combined_ewmac_portfolio_backtest(
            initial_account_value=100_000.0,
            portfolio_spec=portfolio,
            instruments={
                "ES": es,
                "ZN": zn,
            },
            annual_volatility_target=0.20,
        )
    )

    for index in range(
        1,
        len(result.days),
    ):
        previous_day = (
            result.days[
                index - 1
            ]
        )

        current_day = (
            result.days[index]
        )

        assert (
            current_day
            .opening_account_value
            == pytest.approx(
                previous_day
                .closing_account_value
            )
        )

        expected_daily_target = (
            current_day
            .opening_account_value
            * 0.20
            / 16.0
        )

        assert (
            current_day
            .account_daily_cash_vol_target
            == pytest.approx(
                expected_daily_target
            )
        )

def test_portfolio_preparation_uses_point_in_time_signals():
    instrument_input = make_instrument_input(
        symbol="TEST",
        contract="TESTM6",
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

    prepared = (
        prepare_combined_ewmac_portfolio(
            instruments={
                "TEST": instrument_input,
            }
        )
    )

    signals = (
        prepared["TEST"]
        .prepared_backtest
        .signals
    )

    assert signals

    assert all(
        isinstance(
            signal,
            PointInTimeResearchSignalPoint,
        )
        for signal in signals
    )

def test_top_level_backtest_uses_backtest_config():
    es = make_instrument_input(
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

    result = (
        run_combined_ewmac_portfolio_backtest(
            initial_account_value=100_000.0,
            portfolio_spec=portfolio,
            instruments={
                "ES": es,
            },
            config=config,
        )
    )

    first_day = result.days[0]

    # 100,000 × 20% / 16
    assert (
        first_day.account_daily_cash_vol_target
        == pytest.approx(
            1_250.0
        )
    )

def test_top_level_backtest_rejects_config_and_legacy_settings_together():
    es = make_instrument_input(
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

    portfolio = PortfolioSpec(
        instrument_weights={
            "ES": 1.0,
        },
        instrument_diversification_multiplier=1.0,
    )

    config = BacktestConfig(
        annual_volatility_target=0.20,
    )

    with pytest.raises(
        ValueError,
        match="legacy runner settings",
    ):
        run_combined_ewmac_portfolio_backtest(
            initial_account_value=100_000.0,
            portfolio_spec=portfolio,
            instruments={
                "ES": es,
            },

            config=config,

            # 충돌하는 legacy API
            annual_volatility_target=0.15,
        )