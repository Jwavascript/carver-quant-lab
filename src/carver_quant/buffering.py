from dataclasses import dataclass
import math

from carver_quant.position import (
    round_half_away_from_zero,
)


@dataclass(frozen=True)
class BufferDecision:
    buffer_width: float

    lower_position: int
    upper_position: int

    target_position: int
    trade: int


def calculate_buffered_position(
    current_position: int,
    optimal_unrounded_position: float,
    average_position: float,
    buffer_fraction: float = 0.10,
) -> BufferDecision:

    if not math.isfinite(
        optimal_unrounded_position
    ):
        raise ValueError(
            "optimal_unrounded_position "
            "must be finite."
        )

    if (
        not math.isfinite(
            average_position
        )
        or average_position <= 0
    ):
        raise ValueError(
            "average_position must be "
            "finite and positive."
        )

    if (
        not math.isfinite(
            buffer_fraction
        )
        or buffer_fraction < 0
    ):
        raise ValueError(
            "buffer_fraction must be "
            "finite and non-negative."
        )

    buffer_width = (
        average_position
        * buffer_fraction
    )

    lower_position = (
        round_half_away_from_zero(
            optimal_unrounded_position
            - buffer_width
        )
    )

    upper_position = (
        round_half_away_from_zero(
            optimal_unrounded_position
            + buffer_width
        )
    )

    if (
        lower_position
        <= current_position
        <= upper_position
    ):
        target_position = (
            current_position
        )

    elif current_position < lower_position:
        target_position = (
            lower_position
        )

    else:
        target_position = (
            upper_position
        )

    return BufferDecision(
        buffer_width=buffer_width,
        lower_position=lower_position,
        upper_position=upper_position,
        target_position=target_position,
        trade=(
            target_position
            - current_position
        ),
    )