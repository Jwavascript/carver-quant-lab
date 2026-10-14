from dataclasses import dataclass


@dataclass(frozen=True)
class ContractTrade:
    contract: str
    quantity: int


def generate_roll_trades(
    old_contract: str,
    new_contract: str,
    position_to_roll: int,
) -> list[ContractTrade]:
    if position_to_roll == 0:
        return []

    return [
        ContractTrade(
            contract=old_contract,
            quantity=-position_to_roll,
        ),
        ContractTrade(
            contract=new_contract,
            quantity=position_to_roll,
        ),
    ]

def generate_roll_and_rebalance_trades(
    old_contract: str,
    new_contract: str,
    current_position: int,
    target_position: int,
) -> list[ContractTrade]:
    trades = []

    if current_position != 0:
        trades.append(
            ContractTrade(
                contract=old_contract,
                quantity=-current_position,
            )
        )

    if target_position != 0:
        trades.append(
            ContractTrade(
                contract=new_contract,
                quantity=target_position,
            )
        )

    return trades

def generate_contract_rebalance_trades(
    contract: str,
    current_position: int,
    target_position: int,
) -> list[ContractTrade]:
    trade_quantity = target_position - current_position

    if trade_quantity == 0:
        return []

    return [
        ContractTrade(
            contract=contract,
            quantity=trade_quantity,
        )
    ]