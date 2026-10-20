"""P0-03C Slice 1 위험 입력 기록: 계좌 Trading State, 위험 평가용 월물 승수, 최악 경우 노출 한도 (ADR-0003 §6.3·§6.5·§6.6).

한도 값, 기준 가격 `P_ref`의 선택 기준, 상태 전이는 정하지 않는다 (Q3-1, Q3-3, §6.5). 모두 호출자가 명시하는 입력이다.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum

from carver_quant.lab.domain.values import require_decimal, require_identifier, require_utc_instant


class TradingState(Enum):
    """계좌 단위 거래 상태 (ADR-0003 §6.5). 상태를 정하고 바꾸는 것은 L3(shell)이며, 계산 코어는 입력으로만 받는다."""

    NORMAL = "NORMAL"  # 거래 전 위험 검사(L1·L2)를 통과한 주문만 가능
    RESTRICTED = "RESTRICTED"  # 위험 증가 주문 금지. 검증된 위험 축소 주문만 허용 (§6.2.1, §6.2.2)
    HALTED = "HALTED"  # 자동 주문 금지 (위험 축소 주문 포함)


@dataclass(frozen=True, kw_only=True)
class ContractMultiplier:
    """위험 평가에 쓰는 월물 승수 `M[c]` (pt당 통화/계약). 출처와 이용 가능 시각이 있는 참조 입력이다 (I6-6, I6-11).

    월물 사양(`FuturesContractSpec`)과 승수·통화가 다르면 평가에서 쓰지 않는다. 기본값은 없다.
    """

    contract_id: str
    multiplier: Decimal
    currency: str
    data_available_at: datetime
    source_ref: str

    def __post_init__(self) -> None:
        for name in ("contract_id", "currency", "source_ref"):
            object.__setattr__(self, name, require_identifier(getattr(self, name), name))
        multiplier = require_decimal(self.multiplier, "multiplier")
        if multiplier <= 0:
            raise ValueError("multiplier must be greater than 0.")
        object.__setattr__(self, "multiplier", multiplier)
        require_utc_instant(self.data_available_at, "data_available_at")


@dataclass(frozen=True, kw_only=True)
class ExposureLimit:
    """월물 하나의 최악 경우 노출 한도 (`currency` 금액). 명시 입력이며 운영용 기본값은 없다 (ADR-0003 §6.6, Q3-1)."""

    contract_id: str
    currency: str
    max_exposure: Decimal
    source_ref: str

    def __post_init__(self) -> None:
        for name in ("contract_id", "currency", "source_ref"):
            object.__setattr__(self, name, require_identifier(getattr(self, name), name))
        max_exposure = require_decimal(self.max_exposure, "max_exposure")
        if max_exposure < 0:
            raise ValueError("max_exposure must not be negative.")
        object.__setattr__(self, "max_exposure", max_exposure)
