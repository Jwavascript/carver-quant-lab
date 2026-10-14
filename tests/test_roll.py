import pytest

from carver_quant.costs import calculate_total_trading_cost
from carver_quant.execution import execute_market_order

from carver_quant.roll import (
    ContractTrade,
    generate_roll_trades,
    generate_roll_and_rebalance_trades,
    generate_contract_rebalance_trades,
)


def test_generate_roll_trades_for_long_position():
    trades = generate_roll_trades(
        old_contract="SEP",
        new_contract="DEC",
        position_to_roll=20,
    )

    assert trades == [
        ContractTrade(
            contract="SEP",
            quantity=-20,
        ),
        ContractTrade(
            contract="DEC",
            quantity=20,
        ),
    ]

def test_generate_roll_trades_for_short_position():
    trades = generate_roll_trades(
        old_contract="SEP",
        new_contract="DEC",
        position_to_roll=-20,
    )

    assert trades == [
        ContractTrade(
            contract="SEP",
            quantity=20,
        ),
        ContractTrade(
            contract="DEC",
            quantity=-20,
        ),
    ]

def test_generate_roll_trades_returns_empty_when_position_is_zero():
    trades = generate_roll_trades(
        old_contract="SEP",
        new_contract="DEC",
        position_to_roll=0,
    )

    assert trades == []

def test_day_8_roll_trades_have_execution_cost_even_without_direction_change():
    trades = generate_roll_trades(
        old_contract="SEP",
        new_contract="DEC",
        position_to_roll=20,
    )

    sep_trade = trades[0]
    dec_trade = trades[1]

    sep_fill = execute_market_order(
        requested_trade=sep_trade.quantity,
        bid=104.9,
        ask=105.1,
        tick_size=0.1,
    )

    sep_cost = calculate_total_trading_cost(
        filled_quantity=sep_fill.quantity,
        fill_price=sep_fill.price,
        mid_price=105.0,
        multiplier=10.0,
        commission_per_contract=1.0,
    )

    dec_fill = execute_market_order(
        requested_trade=dec_trade.quantity,
        bid=106.9,
        ask=107.1,
        tick_size=0.1,
    )

    dec_cost = calculate_total_trading_cost(
        filled_quantity=dec_fill.quantity,
        fill_price=dec_fill.price,
        mid_price=107.0,
        multiplier=10.0,
        commission_per_contract=1.0,
    )

    total_roll_cost = sep_cost + dec_cost

    assert sep_fill.quantity == -20
    assert sep_fill.price == pytest.approx(104.9)

    assert dec_fill.quantity == 20
    assert dec_fill.price == pytest.approx(107.1)

    assert sep_cost == pytest.approx(40.0)
    assert dec_cost == pytest.approx(40.0)
    assert total_roll_cost == pytest.approx(80.0)

def test_generate_roll_and_rebalance_trades_when_target_increases():
    trades = generate_roll_and_rebalance_trades(
        old_contract="SEP",
        new_contract="DEC",
        current_position=20,
        target_position=30,
    )

    assert trades == [
        ContractTrade(
            contract="SEP",
            quantity=-20,
        ),
        ContractTrade(
            contract="DEC",
            quantity=30,
        ),
    ]

def test_generate_roll_and_rebalance_trades_when_target_decreases():
    trades = generate_roll_and_rebalance_trades(
        old_contract="SEP",
        new_contract="DEC",
        current_position=20,
        target_position=10,
    )

    assert trades == [
        ContractTrade(
            contract="SEP",
            quantity=-20,
        ),
        ContractTrade(
            contract="DEC",
            quantity=10,
        ),
    ]

def test_generate_roll_and_rebalance_trades_when_direction_reverses():
    trades = generate_roll_and_rebalance_trades(
        old_contract="SEP",
        new_contract="DEC",
        current_position=20,
        target_position=-30,
    )

    assert trades == [
        ContractTrade(
            contract="SEP",
            quantity=-20,
        ),
        ContractTrade(
            contract="DEC",
            quantity=-30,
        ),
    ]

def test_generate_roll_and_rebalance_trades_when_opening_from_flat():
    trades = generate_roll_and_rebalance_trades(
        old_contract="SEP",
        new_contract="DEC",
        current_position=0,
        target_position=60,
    )

    assert trades == [
        ContractTrade(
            contract="DEC",
            quantity=60,
        ),
    ]

def test_generate_roll_and_rebalance_trades_when_closing_to_flat():
    trades = generate_roll_and_rebalance_trades(
        old_contract="SEP",
        new_contract="DEC",
        current_position=20,
        target_position=0,
    )

    assert trades == [
        ContractTrade(
            contract="SEP",
            quantity=-20,
        ),
    ]

def test_generate_contract_rebalance_trades_on_non_roll_day():
    trades = generate_contract_rebalance_trades(
        contract="SEP",
        current_position=60,
        target_position=20,
    )

    assert trades == [
        ContractTrade(
            contract="SEP",
            quantity=-40,
        ),
    ]