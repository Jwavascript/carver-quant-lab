from dataclasses import dataclass

from carver_quant.account_ledger import update_account_value
from carver_quant.costs import calculate_total_trading_cost
from carver_quant.execution import execute_market_order
from carver_quant.pnl import calculate_gross_pnl, calculate_net_pnl
from carver_quant.position import calculate_target_position
from carver_quant.position_ledger import apply_fill
from carver_quant.trade import calculate_trade_quantity


@dataclass(frozen=True)
class DailyStepResult:
    gross_pnl: float
    target_position: int
    requested_trade: int

    filled_quantity: int
    fill_price: float | None
    new_position: int

    trading_cost: float
    net_pnl: float
    closing_account_value: float


def run_daily_step(
    previous_account_value: float,
    current_position: int,
    previous_adjusted_price: float,
    current_adjusted_price: float,
    daily_cash_vol_target: float,
    price_volatility: float,
    multiplier: float,
    forecast: float,
    execution_bid: float,
    execution_ask: float,
    tick_size: float,
    commission_per_contract: float,
) -> DailyStepResult:
    gross_pnl = calculate_gross_pnl(
        position_held=current_position,
        previous_price=previous_adjusted_price,
        current_price=current_adjusted_price,
        multiplier=multiplier,
    )

    target_position = calculate_target_position(
        daily_cash_vol_target=daily_cash_vol_target,
        price_volatility=price_volatility,
        multiplier=multiplier,
        forecast=forecast,
    )

    requested_trade = calculate_trade_quantity(
        target_position=target_position,
        current_position=current_position,
    )

    if requested_trade == 0:
        filled_quantity = 0
        fill_price = None
        new_position = current_position
        trading_cost = 0.0

    else:
        fill = execute_market_order(
            requested_trade=requested_trade,
            bid=execution_bid,
            ask=execution_ask,
            tick_size=tick_size,
        )

        filled_quantity = fill.quantity
        fill_price = fill.price

        new_position = apply_fill(
            current_position=current_position,
            filled_quantity=filled_quantity,
        )

        execution_mid = (
            execution_bid + execution_ask
        ) / 2.0

        trading_cost = calculate_total_trading_cost(
            filled_quantity=filled_quantity,
            fill_price=fill_price,
            mid_price=execution_mid,
            multiplier=multiplier,
            commission_per_contract=commission_per_contract,
        )

    net_pnl = calculate_net_pnl(
        gross_pnl=gross_pnl,
        total_trading_cost=trading_cost,
    )

    closing_account_value = update_account_value(
        previous_account_value=previous_account_value,
        net_pnl=net_pnl,
    )

    return DailyStepResult(
    gross_pnl=gross_pnl,
    target_position=target_position,
    requested_trade=requested_trade,
    filled_quantity=filled_quantity,
    fill_price=fill_price,
    new_position=new_position,
    trading_cost=trading_cost,
    net_pnl=net_pnl,
    closing_account_value=closing_account_value,
    )