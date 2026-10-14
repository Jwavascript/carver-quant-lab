def calculate_trade_quantity(
    target_position: int,
    current_position: int,
) -> int:
    return target_position - current_position