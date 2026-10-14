from dataclasses import dataclass

from carver_quant.contract_ledger import (
    apply_contract_trade,
    apply_contract_trades,
)
from carver_quant.costs import calculate_total_trading_cost
from carver_quant.execution import (
    execute_market_order,
    validate_market_order,
)
from carver_quant.roll import ContractTrade


@dataclass(frozen=True)
class ContractQuote:
    bid: float
    ask: float


@dataclass(frozen=True)
class RollExecution:
    contract: str
    quantity: int
    fill_price: float
    trading_cost: float


@dataclass(frozen=True)
class RollExecutionResult:
    executions: list[RollExecution]
    new_positions: dict[str, int]
    total_trading_cost: float


def execute_contract_trades(
    current_positions: dict[str, int],
    trades: list[ContractTrade],
    quotes: dict[str, ContractQuote],
    tick_size: float,
    multiplier: float,
    commission_per_contract: float,
    slippage_ticks: int = 0,
    fx_to_base: float = 1.0,
) -> RollExecutionResult:
    positions = apply_contract_trades(
        current_positions=current_positions,
        trades=[],
    )

    executions = []
    total_trading_cost = 0.0

    # 먼저 필요한 market data가 모두 있는지 검증
    for trade in trades:
        if trade.contract not in quotes:
            raise ValueError(
                f"Missing quote for contract: {trade.contract}"
            )

    # 2. 모든 주문과 quote를 실제 execution 전에 검사
    for trade in trades:
        quote = quotes[trade.contract]

        validate_market_order(
            requested_trade=trade.quantity,
            bid=quote.bid,
            ask=quote.ask,
            tick_size=tick_size,
        )

    # 3. 모든 검증이 끝난 뒤에만 execution 시작
    for trade in trades:
        quote = quotes[trade.contract]

        fill = execute_market_order(
            requested_trade=trade.quantity,
            bid=quote.bid,
            ask=quote.ask,
            tick_size=tick_size,
            slippage_ticks=slippage_ticks,
        )

        mid_price = (
            quote.bid + quote.ask
        ) / 2.0

        trading_cost = calculate_total_trading_cost(
            filled_quantity=fill.quantity,
            fill_price=fill.price,
            mid_price=mid_price,
            multiplier=multiplier,
            commission_per_contract=commission_per_contract,
            fx_to_base=fx_to_base,
        )

        positions = apply_contract_trade(
            current_positions=positions,
            trade=ContractTrade(
                contract=trade.contract,
            quantity=fill.quantity,
            ),
        )

        executions.append(
            RollExecution(
                contract=trade.contract,
                quantity=fill.quantity,
                fill_price=fill.price,
                trading_cost=trading_cost,
            )
        )   

        total_trading_cost += trading_cost
    

    return RollExecutionResult(
        executions=executions,
        new_positions=positions,
        total_trading_cost=total_trading_cost,
    )

def execute_roll_trades(
    current_positions: dict[str, int],
    trades: list[ContractTrade],
    quotes: dict[str, ContractQuote],
    tick_size: float,
    multiplier: float,
    commission_per_contract: float,
    slippage_ticks: int = 0,
    fx_to_base: float = 1.0,
) -> RollExecutionResult:
    return execute_contract_trades(
        current_positions=current_positions,
        trades=trades,
        quotes=quotes,
        tick_size=tick_size,
        multiplier=multiplier,
        commission_per_contract=commission_per_contract,
        slippage_ticks=slippage_ticks,
        fx_to_base=fx_to_base,
    )