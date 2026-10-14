from dataclasses import dataclass
import math


from carver_quant.risk_guardrail import (
    PortfolioRiskPolicy,
)


SUPPORTED_EWMAC_FAST_SPANS = (
    2,
    4,
    8,
    16,
    32,
    64,
)

V1_TRADING_DAYS_PER_YEAR = 256


def _validate_positive_int(
    name: str,
    value: int,
) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value <= 0
    ):
        raise ValueError(
            f"{name} must be a positive integer."
        )


def _validate_optional_positive_float(
    name: str,
    value: float | None,
) -> None:
    if value is None:
        return

    if (
        isinstance(value, bool)
        or not math.isfinite(value)
        or value <= 0
    ):
        raise ValueError(
            f"{name} must be finite and positive."
        )


def _validate_optional_non_negative_float(
    name: str,
    value: float | None,
) -> None:
    if value is None:
        return

    if (
        isinstance(value, bool)
        or not math.isfinite(value)
        or value < 0
    ):
        raise ValueError(
            f"{name} must be finite and "
            "non-negative."
        )


@dataclass(frozen=True)
class BacktestConfig:
    fast_spans: tuple[int, ...] = (
        SUPPORTED_EWMAC_FAST_SPANS
    )

    volatility_span: int = 32

    long_run_window: int = 2560

    annual_volatility_target: (
        float | None
    ) = None

    position_buffer_fraction: (
        float | None
    ) = None

    risk_policy: (
        PortfolioRiskPolicy | None
    ) = None

    trading_days_per_year: int = (
        V1_TRADING_DAYS_PER_YEAR
    )

    def __post_init__(self) -> None:
        self._validate_fast_spans()

        _validate_positive_int(
            "volatility_span",
            self.volatility_span,
        )

        _validate_positive_int(
            "long_run_window",
            self.long_run_window,
        )

        _validate_optional_positive_float(
            "annual_volatility_target",
            self.annual_volatility_target,
        )

        _validate_optional_non_negative_float(
            "position_buffer_fraction",
            self.position_buffer_fraction,
        )

        if (
            self.risk_policy is not None
            and not isinstance(
                self.risk_policy,
                PortfolioRiskPolicy,
            )
        ):
            raise ValueError(
                "risk_policy must be a "
                "PortfolioRiskPolicy."
            )

        # V1의 risk_target.py와
        # performance.py는 현재 256일
        # convention을 사용한다.
        #
        # 아직 실제 계산식을
        # configurable하게 만들지 않았으므로
        # 다른 값을 허용하면 오히려
        # 거짓 configuration이 된다.
        if (
            self.trading_days_per_year
            != V1_TRADING_DAYS_PER_YEAR
        ):
            raise ValueError(
                "V1 supports exactly "
                "256 trading days per year."
            )

    def _validate_fast_spans(
        self,
    ) -> None:
        if not self.fast_spans:
            raise ValueError(
                "fast_spans must not be empty."
            )

        for span in self.fast_spans:
            _validate_positive_int(
                "fast span",
                span,
            )

            if (
                span
                not in
                SUPPORTED_EWMAC_FAST_SPANS
            ):
                raise ValueError(
                    "Unsupported EWMAC "
                    f"fast span: {span}."
                )

        if (
            len(set(self.fast_spans))
            != len(self.fast_spans)
        ):
            raise ValueError(
                "fast_spans must not "
                "contain duplicates."
            )

        if (
            self.fast_spans
            != tuple(
                sorted(self.fast_spans)
            )
        ):
            raise ValueError(
                "fast_spans must be in "
                "ascending order."
            )