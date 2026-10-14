import math
from dataclasses import dataclass


@dataclass(frozen=True)
class PortfolioRiskSnapshot:
    gross_notional_exposure: float
    gross_leverage: float

    margin_required: float
    margin_usage: float


def calculate_contract_notional_base(
    price: float,
    multiplier: float,
    fx_to_base: float,
) -> float:
    values = [
        price,
        multiplier,
        fx_to_base,
    ]

    if not all(
        math.isfinite(value)
        for value in values
    ):
        raise ValueError(
            "Inputs must be finite."
        )

    if multiplier <= 0:
        raise ValueError(
            "multiplier must be positive."
        )

    if fx_to_base <= 0:
        raise ValueError(
            "fx_to_base must be positive."
        )

    # 음수 futures price도 가능하므로
    # exposure magnitude에는 abs(price)를 사용한다.
    return (
        abs(price)
        * multiplier
        * fx_to_base
    )


def calculate_position_notional_base(
    position: int,
    price: float,
    multiplier: float,
    fx_to_base: float,
) -> float:
    contract_notional = (
        calculate_contract_notional_base(
            price=price,
            multiplier=multiplier,
            fx_to_base=fx_to_base,
        )
    )

    return (
        abs(position)
        * contract_notional
    )


def calculate_margin_required(
    position: int,
    margin_per_contract_base: float,
) -> float:
    if not math.isfinite(
        margin_per_contract_base
    ):
        raise ValueError(
            "margin_per_contract_base "
            "must be finite."
        )

    if margin_per_contract_base < 0:
        raise ValueError(
            "margin_per_contract_base "
            "must be non-negative."
        )

    return (
        abs(position)
        * margin_per_contract_base
    )


def calculate_portfolio_risk_snapshot(
    account_value: float,
    notionals: list[float],
    margins: list[float],
) -> PortfolioRiskSnapshot:
    if (
        not math.isfinite(account_value)
        or account_value <= 0
    ):
        raise ValueError(
            "account_value must be "
            "finite and positive."
        )

    if not all(
        math.isfinite(value)
        and value >= 0
        for value in notionals
    ):
        raise ValueError(
            "Notionals must be "
            "finite and non-negative."
        )

    if not all(
        math.isfinite(value)
        and value >= 0
        for value in margins
    ):
        raise ValueError(
            "Margins must be "
            "finite and non-negative."
        )

    gross_notional_exposure = sum(
        notionals
    )

    margin_required = sum(
        margins
    )

    gross_leverage = (
        gross_notional_exposure
        / account_value
    )

    margin_usage = (
        margin_required
        / account_value
    )

    return PortfolioRiskSnapshot(
        gross_notional_exposure=(
            gross_notional_exposure
        ),
        gross_leverage=gross_leverage,
        margin_required=margin_required,
        margin_usage=margin_usage,
    )

@dataclass(frozen=True)
class PortfolioRiskPolicy:
    max_gross_leverage: float | None = None
    max_margin_usage: float | None = None

    def __post_init__(self) -> None:
        if self.max_gross_leverage is not None:
            if (
                not math.isfinite(
                    self.max_gross_leverage
                )
                or self.max_gross_leverage <= 0
            ):
                raise ValueError(
                    "max_gross_leverage must "
                    "be finite and positive."
                )

        if self.max_margin_usage is not None:
            if (
                not math.isfinite(
                    self.max_margin_usage
                )
                or self.max_margin_usage <= 0
            ):
                raise ValueError(
                    "max_margin_usage must "
                    "be finite and positive."
                )


def validate_risk_snapshot(
    snapshot: PortfolioRiskSnapshot,
    policy: PortfolioRiskPolicy,
) -> None:
    if (
        policy.max_gross_leverage
        is not None
        and snapshot.gross_leverage
        > policy.max_gross_leverage
    ):
        raise ValueError(
            "Gross leverage limit exceeded."
        )

    if (
        policy.max_margin_usage
        is not None
        and snapshot.margin_usage
        > policy.max_margin_usage
    ):
        raise ValueError(
            "Margin usage limit exceeded."
        )