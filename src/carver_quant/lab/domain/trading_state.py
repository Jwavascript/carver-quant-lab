"""P0-03C Slice 3 Trading State 기록: 계좌 상태와 그 상태가 정해진 시각·원인·승인자 (ADR-0003 §6.5).

상태를 정하고 바꾸는 것은 L3 shell이다 (ADR-0003 §6.1). 이 기록은 그 결과를 판단 입력으로 받기 위한 표현이며, 원인 해소·대조·
승인의 내용을 검증하지 않는다 (신뢰 경계 입력). `effective_at`은 상태가 정해진 시각(ADR-0001 I-1의 관측 시각), `data_available_at`은
그 기록을 판단에 쓸 수 있게 된 시각이다. 자동 해제 예외(Q3-5)와 HALTED에서의 수동 축소(Q3-6)는 정하지 않는다.
"""

from dataclasses import dataclass
from datetime import datetime

from carver_quant.lab.domain.risk import TradingState
from carver_quant.lab.domain.values import require_identifier, require_optional_identifier, require_utc_instant


@dataclass(frozen=True, kw_only=True)
class TradingStateRecord:
    """계좌 하나의 Trading State 전이 기록 (시각, 원인 코드, 승인자. ADR-0003 §6.5). `approver_ref`는 승인 기록의 참조이며,
    시스템이 스스로 들어가는 상태(예: UNKNOWN에 따른 HALTED)에는 없을 수 있다. 선택 필드도 None을 명시해서 넘긴다."""

    record_id: str
    account_id: str
    state: TradingState
    effective_at: datetime
    data_available_at: datetime
    cause_code: str
    approver_ref: str | None

    def __post_init__(self) -> None:
        for name in ("record_id", "account_id", "cause_code"):
            object.__setattr__(self, name, require_identifier(getattr(self, name), name))
        object.__setattr__(self, "approver_ref", require_optional_identifier(self.approver_ref, "approver_ref"))
        if not isinstance(self.state, TradingState):
            raise ValueError("state must be a TradingState.")
        require_utc_instant(self.effective_at, "effective_at")
        require_utc_instant(self.data_available_at, "data_available_at")
        if self.effective_at > self.data_available_at:
            raise ValueError("a trading state record cannot be available before the state took effect (ADR-0001 I-1).")
