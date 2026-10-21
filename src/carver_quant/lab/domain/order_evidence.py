"""P0-03C Slice 3 주문 증거: 주문 사건 하나와 그 사건이 어떤 종류의 증거인지 (ADR-0009 §6.2, R9-4, ADR-0012 BF-4·BF-5·BF-8~BF-11, BR-7).

출처(누가 보고했는가)는 사건의 `kind`와 기록의 `status_source`(SYSTEM / BROKER / SIMULATOR)이고, 증거 종류(무엇을 알려 주는
보고인가)는 `evidence_kind`다. 둘을 따로 둔다. ADR-0009 §6.2에 따라 결과 상태는 브로커 응답·상태 조회·체결 통보로만 바뀐다.
체결 통보는 확인된 누적 체결 수량만 알려 준다. 통보에 적힌 다른 상태나 취소는 확인으로 쓰지 않는다: 확인을 기다리는 주문(UNKNOWN,
취소·정정 요청 중)의 상태는 그대로이고, 진행 중 주문은 그 체결 수량이 뜻하는 상태(부분 체결, 전량 체결)만 갖는다 (ADR-0012
AT-0012-5, ADR-0009 AT-0009-2. 판정은 `accounting.unknown_resolution`).
출처와 종류는 호출 경계가 명시하는 신뢰 경계 입력이다. 이 모듈은 브로커 응답의 진위나 인증을 확인하지 않는다.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from carver_quant.lab.domain.order_events import OrderEvent, OrderEventKind
from carver_quant.lab.domain.values import require_utc_instant


class OrderEvidenceKind(Enum):
    LOCAL_RECORD = "LOCAL_RECORD"  # 시스템 자체 기록: 주문 의도, 제출·취소·정정 요청, UNKNOWN 분류. 확인이 아니다
    REQUEST_RESPONSE = "REQUEST_RESPONSE"  # 제출·취소·정정 요청에 대한 응답 (BF-8~BF-10: 접수, 거부, 취소·정정 확정)
    STATUS_QUERY_RESPONSE = "STATUS_QUERY_RESPONSE"  # 주문 상태 조회 결과 (BF-4, BF-11)
    FILL_NOTIFICATION = "FILL_NOTIFICATION"  # 체결 통보 (BF-5). 확인된 누적 체결 수량만 알려 준다


@dataclass(frozen=True, kw_only=True)
class OrderEvidence:
    """주문 사건 하나와 그 증거 종류. 상태 조회 결과는 로컬 요청 시각 `requested_at`을 함께 가진다 (BR-7).

    시각: 요청 ≤ 관측(`event.occurred_at`) ≤ 이용 가능(`event.available_at`) (ADR-0001 I-1, ADR-0004 승인 원칙 5).
    선택 필드도 None을 명시해서 넘긴다.
    """

    event: OrderEvent
    evidence_kind: OrderEvidenceKind
    requested_at: datetime | None

    def __post_init__(self) -> None:
        if not isinstance(self.event, OrderEvent):
            raise ValueError("event must be an OrderEvent.")
        if not isinstance(self.evidence_kind, OrderEvidenceKind):
            raise ValueError("evidence_kind must be an OrderEvidenceKind.")
        if (self.event.kind is OrderEventKind.SYSTEM_RECORD) != (self.evidence_kind is OrderEvidenceKind.LOCAL_RECORD):
            raise ValueError("a local record is exactly a system record; broker and simulator reports are not local records.")
        if self.evidence_kind is OrderEvidenceKind.STATUS_QUERY_RESPONSE:
            require_utc_instant(self.requested_at, "requested_at")
            if self.requested_at > self.event.occurred_at:
                raise ValueError("a status query cannot observe the order before it was requested.")
        elif self.requested_at is not None:
            raise ValueError("only a status query response carries requested_at.")
        if self.evidence_kind is OrderEvidenceKind.FILL_NOTIFICATION and self.event.record.filled_quantity == 0:
            raise ValueError("a fill notification reports at least one confirmed fill.")
