"""P0-03C Slice 2 주문 사건: 시스템이 기록한 주문 상태의 한 버전과 그 시각 (ADR-0009 §6.1 추가 전용 기록, ADR-0012 BR-7).

사건은 주문 기록(`OrderRecord`)의 한 버전을 담는다: 계좌, Client Order ID, 월물, 상태, 확인된 누적 체결·취소 수량, 정정 정보,
상태 출처. `occurred_at`은 사건이 일어난 것으로 보고된 시각이고 `available_at`은 시스템이 그 정보를 이용할 수 있게 된 시각
(로컬 수신·기록 시각, BR-7·BR-3)이다. ADR-0001 I-1에 따라 `occurred_at ≤ available_at`이어야 한다.
보관 위치·형식(Q9-9), 영속화(Q12-7), `order_submitted_at`의 의미(D3A-23, Q12-13), 브로커 시각의 의미 구분(BR-7)은 정하지 않는다.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from carver_quant.lab.domain.orders import OrderRecord, OrderStatusSource
from carver_quant.lab.domain.values import require_identifier, require_utc_instant


class OrderEventKind(Enum):
    """사건을 만든 쪽. 주문 기록의 상태 출처와 같아야 한다 (ADR-0009 §6.2: 결과 상태는 브로커·시뮬레이터 확인으로만)."""

    SYSTEM_RECORD = "SYSTEM_RECORD"  # 시스템의 기록: 주문 의도, 제출·취소·정정 요청, 결과 불명확 분류
    BROKER_REPORT = "BROKER_REPORT"  # 브로커 응답, 상태 조회, 체결 통보
    SIMULATOR_REPORT = "SIMULATOR_REPORT"  # Paper 시뮬레이터 확인


_SOURCE_OF_KIND = {
    OrderEventKind.SYSTEM_RECORD: OrderStatusSource.SYSTEM,
    OrderEventKind.BROKER_REPORT: OrderStatusSource.BROKER,
    OrderEventKind.SIMULATOR_REPORT: OrderStatusSource.SIMULATOR,
}


@dataclass(frozen=True, kw_only=True)
class OrderEvent:
    """주문 하나의 기록 버전과 그 발생·이용 가능 시각 (Slice 2 표현).

    `record.status_event_ref`는 이 사건의 `event_id`다. 사건 하나가 주문의 상태 전체를 담으므로 Snapshot은 상태 전이를
    다시 계산하지 않고 마지막으로 알려진 버전을 고른다 (ADR-0009 §6.1: 전체 Event Sourcing·세부 상태 기계(대안 C)는 채택하지 않음).
    """

    event_id: str
    kind: OrderEventKind
    record: OrderRecord
    occurred_at: datetime
    available_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_id", require_identifier(self.event_id, "event_id"))
        if not isinstance(self.kind, OrderEventKind):
            raise ValueError("kind must be an OrderEventKind.")
        if not isinstance(self.record, OrderRecord):
            raise ValueError("record must be an OrderRecord.")
        require_utc_instant(self.occurred_at, "occurred_at")
        require_utc_instant(self.available_at, "available_at")
        if self.occurred_at > self.available_at:
            raise ValueError("an order event cannot be available before it occurred (ADR-0001 I-1).")
        if self.record.status_source is not _SOURCE_OF_KIND[self.kind]:
            raise ValueError(f"a {self.kind.name} event cannot carry a status from {self.record.status_source.name}.")
        if self.record.status_event_ref != self.event_id:
            raise ValueError("the order record must reference this event (status_event_ref = event_id).")
