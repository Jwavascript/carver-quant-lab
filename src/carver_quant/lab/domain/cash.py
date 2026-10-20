"""P0-03B Slice 3 현금 이벤트 (ADR-0008 §6.1·§6.3·§6.6, X8-1·X8-7, F8-1 원칙, ADR-0009 R9-9·R9-11).

Slice 3 한정 최소 모델이다. 종류는 ETF 매매대금, 수수료, 외부 입출금 셋뿐이다. 결제 예정일·결제 상태, 분배금, 선물 정산,
환전, 세금은 구현하지 않는다 (ADR-0008 Q8-4·Q8-5·Q8-6, ADR-0006 Q6-5). 수수료 현금 이벤트의 기록 형식(D3A-30)과
전역 회계 정책을 정하지 않는다.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum

from carver_quant.lab.domain.values import require_decimal, require_identifier, require_utc_instant


class CashEventKind(Enum):
    TRADE_CONSIDERATION = "TRADE_CONSIDERATION"  # ETF 매매대금: 매수 −q×F, 매도 +q×F. 손익이 아니다 (X8-1)
    COMMISSION = "COMMISSION"  # 거래 수수료 −fee (≤ 0). 부과 통화 현금에서 정확히 한 번 (F8-1 원칙)
    EXTERNAL_FLOW = "EXTERNAL_FLOW"  # 외부 입금(+)·출금(−). 투자 손익이 아니다 (X8-7)


class CashEventConfirmation(Enum):
    """기록이 확인된 사실인지를 호출 경계가 명시한다. 현금 장부는 CONFIRMED만 반영한다."""

    CONFIRMED = "CONFIRMED"  # 확인된 기록: 반영된 체결의 대금·수수료, 브로커가 확정한 거래, 명시적 테스트·시뮬레이션 입력
    UNCONFIRMED = "UNCONFIRMED"  # 확인되지 않은 보고 (예: 브로커의 잠정 기록). 사실로 반영하지 않는다


# 체결 하나에서 한 건씩만 생기는 종류 (ADR-0009 R9-11, R9-9, F8-1 원칙). 이 종류의 원인 참조는 체결 참조다.
FILL_CASH_EVENT_KINDS = frozenset({CashEventKind.TRADE_CONSIDERATION, CashEventKind.COMMISSION})


@dataclass(frozen=True, kw_only=True)
class CashEvent:
    """통화별 현금 이벤트 한 건 (ADR-0008 §6.1).

    `amount`는 `currency` 단위의 부호 있는 Decimal 금액이다 (현금 증가 +, 감소 −). `occurred_at`은 경제적 발생 시각
    (체결이면 `fill_at`)이며, 어느 시각까지의 잔액에 들어가는지를 정한다. `cause_ref`는 원인 참조 ID다: 매매대금·수수료는
    체결 참조, 외부 흐름은 송금 참조. 멱등 키는 (계좌, `cash_event_id`)다.
    """

    account_id: str
    cash_event_id: str
    kind: CashEventKind
    cause_ref: str
    currency: str
    amount: Decimal
    occurred_at: datetime
    confirmation: CashEventConfirmation

    def __post_init__(self) -> None:
        for name in ("account_id", "cash_event_id", "cause_ref", "currency"):
            object.__setattr__(self, name, require_identifier(getattr(self, name), name))
        if not isinstance(self.kind, CashEventKind):
            raise ValueError("kind must be a CashEventKind.")
        if not isinstance(self.confirmation, CashEventConfirmation):
            raise ValueError("confirmation must be a CashEventConfirmation.")
        amount = require_decimal(self.amount, "amount")
        if self.kind is CashEventKind.COMMISSION and amount > 0:
            raise ValueError("a commission takes cash out (fee >= 0, ADR-0001 §6.2); its amount must not be positive.")
        object.__setattr__(self, "amount", amount)
        require_utc_instant(self.occurred_at, "occurred_at")


# 같은 Cash Event ID의 재수신을 비교할 필드: 키(계좌, Cash Event ID)를 뺀 모든 필드.
CASH_EVENT_COMPARISON_FIELDS = ("kind", "cause_ref", "currency", "amount", "occurred_at", "confirmation")
