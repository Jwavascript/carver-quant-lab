from carver_quant.roll import ContractTrade


def apply_contract_trade(
    current_positions: dict[str, int],
    trade: ContractTrade,
) -> dict[str, int]:
    updated_positions = {
        contract: position
        for contract, position in current_positions.items()
        if position != 0
    }

    current_position = updated_positions.get(
        trade.contract,
        0,
    )

    new_position = current_position + trade.quantity

    if new_position == 0:
        updated_positions.pop(
            trade.contract,
            None,
        )
    else:
        updated_positions[trade.contract] = new_position

    return updated_positions

def apply_contract_trades(
    current_positions: dict[str, int],
    trades: list[ContractTrade],
) -> dict[str, int]:
    positions = {
        contract: position
        for contract, position in current_positions.items()
        if position != 0
    }

    for trade in trades:
        positions = apply_contract_trade(
            current_positions=positions,
            trade=trade,
        )

    return positions