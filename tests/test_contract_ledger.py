from carver_quant.contract_ledger import (
    apply_contract_trade,
    apply_contract_trades,
)
from carver_quant.roll import (
    ContractTrade,
    generate_roll_trades,
)


def test_apply_contract_trade_closes_old_contract_position():
    current_positions = {
        "SEP": 20,
        "DEC": 0,
    }

    result = apply_contract_trade(
        current_positions=current_positions,
        trade=ContractTrade(
            contract="SEP",
            quantity=-20,
        ),
    )

    assert result == {}

def test_roll_moves_position_from_old_to_new_contract():
    current_positions = {
        "SEP": 20,
        "DEC": 0,
    }

    trades = generate_roll_trades(
        old_contract="SEP",
        new_contract="DEC",
        position_to_roll=20,
    )

    positions = current_positions

    for trade in trades:
        positions = apply_contract_trade(
            current_positions=positions,
            trade=trade,
        )

    assert positions == {
        "DEC": 20
    }

def test_apply_contract_trade_does_not_mutate_input_positions():
    current_positions = {
        "SEP": 20,
        "DEC": 0,
    }

    trade = ContractTrade(
        contract="SEP",
        quantity=-20,
    )

    result = apply_contract_trade(
        current_positions=current_positions,
        trade=trade,
    )

    assert current_positions == {
        "SEP": 20,
        "DEC": 0,
    }

    assert result == {}

def test_apply_contract_trade_adds_new_contract_when_missing():
    current_positions = {
        "SEP": 20,
    }

    result = apply_contract_trade(
        current_positions=current_positions,
        trade=ContractTrade(
            contract="DEC",
            quantity=20,
        ),
    )

    assert result == {
        "SEP": 20,
        "DEC": 20,
    }

def test_apply_contract_trade_removes_contract_when_position_becomes_zero():
    result = apply_contract_trade(
        current_positions={
            "SEP": 20,
        },
        trade=ContractTrade(
            contract="SEP",
            quantity=-20,
        ),
    )

    assert result == {}

def test_apply_contract_trades_moves_position_between_contracts():
    current_positions = {
        "SEP": 20,
    }

    trades = generate_roll_trades(
        old_contract="SEP",
        new_contract="DEC",
        position_to_roll=20,
    )

    result = apply_contract_trades(
        current_positions=current_positions,
        trades=trades,
    )

    assert result == {
        "DEC": 20,
    }

def test_apply_contract_trades_with_empty_list_normalizes_positions():
    current_positions = {
        "SEP": 20,
        "DEC": 0,
    }

    result = apply_contract_trades(
        current_positions=current_positions,
        trades=[],
    )

    assert result == {
        "SEP": 20,
    }

    assert current_positions == {
        "SEP": 20,
        "DEC": 0,
    }

def test_day_8_roll_keeps_instrument_position_while_moving_contract():
    current_instrument_position = 20

    current_contract_positions = {
        "SEP": 20,
    }

    roll_trades = generate_roll_trades(
        old_contract="SEP",
        new_contract="DEC",
        position_to_roll=20,
    )

    new_contract_positions = apply_contract_trades(
        current_positions=current_contract_positions,
        trades=roll_trades,
    )

    new_instrument_position = sum(
        new_contract_positions.values()
    )

    assert current_instrument_position == 20

    assert roll_trades == [
        ContractTrade(
            contract="SEP",
            quantity=-20,
        ),
        ContractTrade(
            contract="DEC",
            quantity=20,
        ),
    ]

    assert new_contract_positions == {
        "DEC": 20,
    }

    assert new_instrument_position == 20