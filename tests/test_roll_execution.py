import pytest

from carver_quant.roll import (
    ContractTrade,
    generate_roll_trades,
    generate_roll_and_rebalance_trades,
    generate_contract_rebalance_trades,
)
from carver_quant.roll_execution import (
    ContractQuote,
    execute_contract_trades,
    execute_roll_trades,
)

from carver_quant.account_ledger import update_account_value
from carver_quant.pnl import (
    calculate_gross_pnl,
    calculate_net_pnl,
)


def test_execute_day_8_roll_trades():
    trades = generate_roll_trades(
        old_contract="SEP",
        new_contract="DEC",
        position_to_roll=20,
    )

    result = execute_roll_trades(
        current_positions={
            "SEP": 20,
        },
        trades=trades,
        quotes={
            "SEP": ContractQuote(
                bid=104.9,
                ask=105.1,
            ),
            "DEC": ContractQuote(
                bid=106.9,
                ask=107.1,
            ),
        },
        tick_size=0.1,
        multiplier=10.0,
        commission_per_contract=1.0,
    )

    assert len(result.executions) == 2

    assert result.executions[0].contract == "SEP"
    assert result.executions[0].quantity == -20
    assert result.executions[0].fill_price == pytest.approx(104.9)
    assert result.executions[0].trading_cost == pytest.approx(40.0)

    assert result.executions[1].contract == "DEC"
    assert result.executions[1].quantity == 20
    assert result.executions[1].fill_price == pytest.approx(107.1)
    assert result.executions[1].trading_cost == pytest.approx(40.0)

    assert result.new_positions == {
        "DEC": 20,
    }

    assert result.total_trading_cost == pytest.approx(80.0)

def test_execute_roll_trades_with_no_trades_has_zero_cost():
    current_positions = {
        "SEP": 20,
        "DEC": 0,
    }

    result = execute_roll_trades(
        current_positions=current_positions,
        trades=[],
        quotes={},
        tick_size=0.1,
        multiplier=10.0,
        commission_per_contract=1.0,
    )

    assert result.executions == []

    assert result.new_positions == {
        "SEP": 20,
    }

    assert result.total_trading_cost == pytest.approx(0.0)

    assert current_positions == {
        "SEP": 20,
        "DEC": 0,
    }

def test_execute_roll_trades_raises_when_quote_is_missing():
    trades = generate_roll_trades(
        old_contract="SEP",
        new_contract="DEC",
        position_to_roll=20,
    )

    with pytest.raises(
        ValueError,
        match="Missing quote for contract: DEC",
    ):
        execute_roll_trades(
            current_positions={
                "SEP": 20,
            },
            trades=trades,
            quotes={
                "SEP": ContractQuote(
                    bid=104.9,
                    ask=105.1,
                ),
            },
            tick_size=0.1,
            multiplier=10.0,
            commission_per_contract=1.0,
        )

def test_roll_validation_happens_before_any_execution(monkeypatch):
    trades = generate_roll_trades(
        old_contract="SEP",
        new_contract="DEC",
        position_to_roll=20,
    )

    execution_calls = []

    from carver_quant import roll_execution

    original_execute_market_order = (
        roll_execution.execute_market_order
    )

    def spy_execute_market_order(
        requested_trade,
        bid,
        ask,
        tick_size=None,
    ):
        execution_calls.append(requested_trade)

        return original_execute_market_order(
            requested_trade=requested_trade,
            bid=bid,
            ask=ask,
            tick_size=tick_size,
        )

    monkeypatch.setattr(
        roll_execution,
        "execute_market_order",
        spy_execute_market_order,
    )

    with pytest.raises(ValueError):
        execute_roll_trades(
            current_positions={
                "SEP": 20,
            },
            trades=trades,
            quotes={
                "SEP": ContractQuote(
                    bid=104.9,
                    ask=105.1,
                ),
                "DEC": ContractQuote(
                    bid=107.1,
                    ask=106.9,
                ),
            },
            tick_size=0.1,
            multiplier=10.0,
            commission_per_contract=1.0,
        )

    assert execution_calls == []

def test_day_6_opening_position_in_new_contract_from_flat():
    trades = generate_roll_and_rebalance_trades(
        old_contract="JUN",
        new_contract="SEP",
        current_position=0,
        target_position=60,
    )

    result = execute_roll_trades(
        current_positions={},
        trades=trades,
        quotes={
            "SEP": ContractQuote(
                bid=103.9,
                ask=104.1,
            ),
        },
        tick_size=0.1,
        multiplier=10.0,
        commission_per_contract=1.0,
    )

    assert len(result.executions) == 1

    execution = result.executions[0]

    assert execution.contract == "SEP"
    assert execution.quantity == 60
    assert execution.fill_price == pytest.approx(104.1)
    assert execution.trading_cost == pytest.approx(120.0)

    assert result.new_positions == {
        "SEP": 60,
    }

    assert result.total_trading_cost == pytest.approx(120.0)

def test_day_7_rebalances_position_in_same_contract():
    trades = generate_contract_rebalance_trades(
        contract="SEP",
        current_position=60,
        target_position=20,
    )

    result = execute_roll_trades(
        current_positions={
            "SEP": 60,
        },
        trades=trades,
        quotes={
            "SEP": ContractQuote(
                bid=105.9,
                ask=106.1,
            ),
        },
        tick_size=0.1,
        multiplier=10.0,
        commission_per_contract=1.0,
    )

    assert len(result.executions) == 1

    execution = result.executions[0]

    assert execution.contract == "SEP"
    assert execution.quantity == -40
    assert execution.fill_price == pytest.approx(105.9)
    assert execution.trading_cost == pytest.approx(80.0)

    assert result.new_positions == {
        "SEP": 20,
    }

    assert result.total_trading_cost == pytest.approx(80.0)

def test_day_7_full_accounting():
    gross_pnl = calculate_gross_pnl(
        position_held=60,
        previous_price=104.0,
        current_price=106.0,
        multiplier=10.0,
    )

    trades = generate_contract_rebalance_trades(
        contract="SEP",
        current_position=60,
        target_position=20,
    )

    execution_result = execute_roll_trades(
        current_positions={
            "SEP": 60,
        },
        trades=trades,
        quotes={
            "SEP": ContractQuote(
                bid=105.9,
                ask=106.1,
            ),
        },
        tick_size=0.1,
        multiplier=10.0,
        commission_per_contract=1.0,
    )

    net_pnl = calculate_net_pnl(
        gross_pnl=gross_pnl,
        total_trading_cost=execution_result.total_trading_cost,
    )

    closing_account_value = update_account_value(
        previous_account_value=50040.0,
        net_pnl=net_pnl,
    )

    assert gross_pnl == pytest.approx(1200.0)

    assert execution_result.new_positions == {
        "SEP": 20,
    }

    assert execution_result.total_trading_cost == pytest.approx(80.0)

    assert net_pnl == pytest.approx(1120.0)

    assert closing_account_value == pytest.approx(51160.0)

def test_execute_contract_trades_handles_normal_rebalance():
    trades = generate_contract_rebalance_trades(
        contract="SEP",
        current_position=60,
        target_position=20,
    )

    result = execute_contract_trades(
        current_positions={
            "SEP": 60,
        },
        trades=trades,
        quotes={
            "SEP": ContractQuote(
                bid=105.9,
                ask=106.1,
            ),
        },
        tick_size=0.1,
        multiplier=10.0,
        commission_per_contract=1.0,
    )

    assert result.new_positions == {
        "SEP": 20,
    }

    assert result.total_trading_cost == pytest.approx(80.0)

def test_day_9_full_accounting():
    gross_pnl = calculate_gross_pnl(
        position_held=20,
        previous_price=105.0,
        current_price=101.0,
        multiplier=10.0,
    )

    trades = generate_contract_rebalance_trades(
        contract="DEC",
        current_position=20,
        target_position=-30,
    )

    execution_result = execute_contract_trades(
        current_positions={
            "DEC": 20,
        },
        trades=trades,
        quotes={
            "DEC": ContractQuote(
                bid=100.9,
                ask=101.1,
            ),
        },
        tick_size=0.1,
        multiplier=10.0,
        commission_per_contract=1.0,
    )

    net_pnl = calculate_net_pnl(
        gross_pnl=gross_pnl,
        total_trading_cost=execution_result.total_trading_cost,
    )

    closing_account_value = update_account_value(
        previous_account_value=50880.0,
        net_pnl=net_pnl,
    )

    assert trades == [
        ContractTrade(
            contract="DEC",
            quantity=-50,
        ),
    ]

    assert gross_pnl == pytest.approx(-800.0)

    assert execution_result.new_positions == {
        "DEC": -30,
    }

    assert execution_result.total_trading_cost == pytest.approx(100.0)

    assert net_pnl == pytest.approx(-900.0)
    assert closing_account_value == pytest.approx(49980.0)

def test_day_10_full_accounting():
    gross_pnl = calculate_gross_pnl(
        position_held=-30,
        previous_price=101.0,
        current_price=103.0,
        multiplier=10.0,
    )

    trades = generate_contract_rebalance_trades(
        contract="DEC",
        current_position=-30,
        target_position=-12,
    )

    execution_result = execute_contract_trades(
        current_positions={
            "DEC": -30,
        },
        trades=trades,
        quotes={
            "DEC": ContractQuote(
                bid=102.9,
                ask=103.1,
            ),
        },
        tick_size=0.1,
        multiplier=10.0,
        commission_per_contract=1.0,
    )

    net_pnl = calculate_net_pnl(
        gross_pnl=gross_pnl,
        total_trading_cost=execution_result.total_trading_cost,
    )

    closing_account_value = update_account_value(
        previous_account_value=49980.0,
        net_pnl=net_pnl,
    )

    assert trades == [
        ContractTrade(
            contract="DEC",
            quantity=18,
        ),
    ]

    assert gross_pnl == pytest.approx(-600.0)

    assert execution_result.executions[0].fill_price == pytest.approx(103.1)

    assert execution_result.new_positions == {
        "DEC": -12,
    }

    assert execution_result.total_trading_cost == pytest.approx(36.0)

    assert net_pnl == pytest.approx(-636.0)
    assert closing_account_value == pytest.approx(49344.0)

def test_execute_contract_trades_applies_slippage():
    result = execute_contract_trades(
        current_positions={},
        trades=[
            ContractTrade(
                contract="SEP",
                quantity=10,
            ),
        ],
        quotes={
            "SEP": ContractQuote(
                bid=99.9,
                ask=100.1,
            ),
        },
        tick_size=0.1,
        multiplier=10.0,
        commission_per_contract=1.0,
        slippage_ticks=1,
    )

    assert len(result.executions) == 1

    execution = result.executions[0]

    assert execution.quantity == 10
    assert execution.fill_price == pytest.approx(100.2)

    assert execution.trading_cost == pytest.approx(30.0)
    assert result.total_trading_cost == pytest.approx(30.0)

    assert result.new_positions == {
        "SEP": 10,
    }

def test_execute_contract_trades_converts_trading_cost_to_krw():
    result = execute_contract_trades(
        current_positions={},
        trades=[
            ContractTrade(
                contract="SEP",
                quantity=10,
            ),
        ],
        quotes={
            "SEP": ContractQuote(
                bid=99.9,
                ask=100.1,
            ),
        },
        tick_size=0.1,
        multiplier=10.0,
        commission_per_contract=1.0,
        slippage_ticks=1,
        fx_to_base=1350.0,
    )

    assert len(result.executions) == 1

    execution = result.executions[0]

    assert execution.fill_price == pytest.approx(100.2)

    assert execution.trading_cost == pytest.approx(
        40500.0
    )

    assert result.total_trading_cost == pytest.approx(
        40500.0
    )

    assert result.new_positions == {
        "SEP": 10,
    }