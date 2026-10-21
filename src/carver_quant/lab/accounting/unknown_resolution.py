"""주문 증거의 출처·종류 검사와 UNKNOWN 해소 근거 판정 (P0-03C Slice 3).

ADR-0009 §6.2·R9-4·R9-5·R9-6·RP-3~RP-5·AT-0009-2·AT-0009-3, ADR-0012 BR-4·BR-6·BR-11·BR-12·§6.7·AT-0012-1·AT-0012-2·AT-0012-5,
ADR-0003 §6.3. 증거마다 그 기록 버전을 그대로 쓸지(USED), 확인된 체결 수량만 반영할지(FILLS_ONLY), 주문을 UNKNOWN으로 둘지
(MARKED_UNKNOWN), 근거가 부족해 쓰지 않을지(DEFERRED), 출처나 주문 식별이 맞지 않아 쓰지 않을지(REJECTED)를 정하고, 쓰는 기록만으로
Slice 2의 `orders_as_of` Snapshot을 만든다. 주문 상태 기계를 새로 만들지 않는다. 이 모듈이 하는 일은 아래 규칙에 따라 기록 버전을
고르거나 막는 것뿐이다. 규칙은 주문마다 이용 가능 시각 순서로, 그때까지 쓰인 기록을 기준으로 적용한다. 쓰지 않는 증거라도 그 안의
제한적인 내용(UNKNOWN 상태, 확인되지 않은 체결 수량, 다른 Broker Order ID)은 버리지 않는다.

- 계좌의 확인 출처(BROKER 또는 SIMULATOR)가 아닌 보고는 REJECTED (§6.7: 계좌의 주문은 한 Adapter가 확인한다).
- 그 주문에 처음 알려진 Broker Order ID(REJECTED가 아닌 모든 증거 기준)와 다른 보고는 REJECTED (AT-0012-2: 비슷한 속성만으로 같은
  주문이라고 보지 않음). 그런 시스템 기록은 OrderEventIntegrityError. 한 Broker Order ID가 정정 관계(기존·새 주문)로 이어지지 않은
  두 주문에 묶여도 OrderEventIntegrityError.
- UNKNOWN을 알리는 보고(체결 통보 포함, 오래된 보고 포함)는 주문을 UNKNOWN으로 둔다 (BR-6: 번역할 수 없는 상태는 UNKNOWN, §6.3).
  이미 UNKNOWN인 주문에 온 그런 보고는 쓰지 않더라도, 그 뒤의 해소 기준 시각을 그 보고의 이용 가능 시각까지 늦춘다.
- 취소·정정 요청 중 상태는 종료 결과(CANCELLED·EXPIRED·REJECTED·FILLED)를 알리는 보고로만 끝난다. 그 밖의 보고(접수 응답, 진행 중
  상태 조회)는 상태와 확인 취소를 그대로 두고 체결만 반영한다 (R9-6, RP-3, AT-0009-3). 그래서 취소·정정 거부는 주문이 끝날 때까지
  대기 상태로 남는다 (요청과 응답을 잇는 계약이 없음).
- 체결 통보는 확인된 누적 체결만 알려 준다. 확인을 기다리는 주문(UNKNOWN, CANCEL_REQUESTED, REPLACE_REQUESTED)에서는 상태와 확인
  취소를 그대로 두고 (AT-0012-5 3행, AT-0009-2, R9-6, RP-3), 제출 전·진행 중 주문이나 첫 증거에서는 그 체결이 뜻하는 상태
  (PARTIALLY_FILLED, FILLED)만 정한다. 통보에 적힌 다른 상태·취소는 확인으로 쓰지 않는다 (FILLS_ONLY).
- 취소·정정 요청 구간이 시작되기 전에 관측된 보고(상태 조회는 요청 시각 기준)는 그 상태를 바꾸지 못한다 (R9-6, RP-3). 확인된 체결과
  같은 체결을 알리면 DEFERRED, 다른 체결을 알리면 주문을 UNKNOWN으로 둔다 (RP-4).
- 남은 수량을 없애는 보고(CANCELLED·REJECTED·EXPIRED, 확인 취소 증가)의 누적 체결이 확인된 체결과 다르면 그 보고로 최악 경우를
  줄이지 않고 주문을 UNKNOWN으로 둔다 (RP-4, BR-12: 원래 수량 − 확인된 체결). 체결 수량만 다른 다른 보고는 Slice 2의 체결 귀속
  검사(장부 체결 합 = 기록의 확인 체결)를 받는다.
- UNKNOWN의 상태를 바꿀 수 있는 것은 상태 조회 결과뿐이다 (R9-4, R9-5, BR-4). 요청 응답은 DEFERRED. 상태 조회도 다음을 모두
  만족할 때만 쓴다: UNKNOWN 기준 시각보다 뒤에 요청함 (같은 시각이면 선후를 확정할 수 없어 DEFERRED), 누적 체결이 이미 확인된 체결과
  같음 (RP-4), 정정 중 UNKNOWN이 아님 (RP-5),
  결과가 확인 취소 0인 ACCEPTED·PARTIALLY_FILLED·FILLED (최악 경우가 원래 주문 수량보다 줄지 않는 결과. AT-0012-1, AT-0009-2). 최악
  경우를 줄이는 해소(CANCELLED·REJECTED·EXPIRED, 확인 취소)에는 상태 조회와 대조 일치가 함께 필요하고 (AT-0012-5), 그보다 약한
  조건은 미승인이다 (Q12-14). 이 Slice는 대조를 하지 않으므로 DEFERRED이고 주문은 UNKNOWN으로 남는다.
- UNKNOWN으로 두는 파생 기록의 발생 시각은 그 보고를 받은 시각(이용 가능 시각)이다: 시스템이 UNKNOWN으로 분류한 시각.
- 판정에서 빠지는 증거까지 포함해 주문마다 검사한다: 같은 사건 ID의 다른 내용, 주문 월물·수량 변경, 같은 이용 가능 시각의 다른
  보고, 이용 가능 순서로 본 누적 체결(모든 증거)·누적 취소(체결 통보 제외)의 감소, 확인 출처의 종료 보고 뒤의 다른 보고(체결 통보
  제외), 그리고 관측 시각 순서로 본 확인 출처 보고(체결 통보 제외)의 누적 체결·취소 감소와 종료 뒤의 다른 상태는
  OrderEventIntegrityError (어느 쪽이 맞는지 고르지 않는다, BR-11). 이 검사와 `orders_as_of`의 모순 검사는 늦게 도착한 증거에도
  적용되므로, 뒤에 알려진 모순이 과거 판단의 Snapshot 생성을 막을 수 있다 (Slice 2와 같다).
출처와 증거 종류는 호출 경계가 명시하는 신뢰 경계 입력이다. 브로커 응답의 진위나 인증을 확인하지 않는다.
"""

from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import datetime
from enum import Enum
from itertools import groupby

from carver_quant.lab.accounting.order_snapshot import OrderEventIntegrityError, OrderLogCompleteness, OrderSnapshot, orders_as_of
from carver_quant.lab.domain.order_events import OrderEvent
from carver_quant.lab.domain.order_evidence import OrderEvidence, OrderEvidenceKind
from carver_quant.lab.domain.orders import OrderRecord, OrderStatus, OrderStatusSource
from carver_quant.lab.domain.values import require_identifier, require_utc_instant

_AWAITING_CONFIRMATION = frozenset({OrderStatus.UNKNOWN, OrderStatus.CANCEL_REQUESTED, OrderStatus.REPLACE_REQUESTED})
_PENDING_REQUESTS = frozenset({OrderStatus.CANCEL_REQUESTED, OrderStatus.REPLACE_REQUESTED})
# 체결 통보가 그 체결 수량이 뜻하는 상태를 정할 수 있는 주문 (제출 전·진행 중).
_FILL_DERIVABLE_STATES = frozenset({OrderStatus.INTENT, OrderStatus.PENDING_SUBMIT, OrderStatus.ACCEPTED, OrderStatus.PARTIALLY_FILLED})
_TERMINAL_STATES = frozenset({OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED, OrderStatus.EXPIRED})
# 상태 조회로 UNKNOWN을 해소해도 최악 경우(주문 − 확인된 체결, BR-12)가 줄지 않는 결과 (AT-0012-1, AT-0009-2).
_UNKNOWN_RESOLUTIONS = frozenset({OrderStatus.ACCEPTED, OrderStatus.PARTIALLY_FILLED, OrderStatus.FILLED})
_LOWERING_RESULTS = frozenset({OrderStatus.CANCELLED, OrderStatus.REJECTED, OrderStatus.EXPIRED})


class EvidenceDisposition(Enum):
    USED = "USED"  # 그 기록 버전을 Snapshot 후보로 그대로 쓴다 (Slice 2의 검사를 받는다)
    FILLS_ONLY = "FILLS_ONLY"  # 확인된 누적 체결만 반영한다. 통보에 적힌 다른 상태·취소는 쓰지 않는다 (체결 통보)
    MARKED_UNKNOWN = "MARKED_UNKNOWN"  # 보고가 UNKNOWN을 알리거나 확인된 체결과 다른 체결을 알려 주문을 UNKNOWN으로 둔다 (BR-6, RP-4, BR-12)
    DEFERRED = "DEFERRED"  # 주문 상태를 확인하는 근거로 부족해 쓰지 않는다 (제한적인 내용은 없다)
    REJECTED = "REJECTED"  # 출처나 주문 식별이 계좌의 주문과 맞지 않아 쓰지 않는다 (L3 게이트의 차단 사유)


@dataclass(frozen=True)
class EvidenceAssessment:
    event_id: str
    client_order_id: str
    evidence_kind: OrderEvidenceKind
    source: OrderStatusSource
    available_at: datetime
    disposition: EvidenceDisposition
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class EvidenceSnapshot:
    """증거 판정과 그 판정으로 만든 decision_at 주문 Snapshot. `events`는 `orders_as_of`에 넘긴 사건(그대로 쓴 것과 파생 기록, 모든
    시각)이고, `assessments`는 늦게 도착한 증거까지 모든 증거의 판정이다."""

    account_id: str
    confirming_source: OrderStatusSource
    snapshot: OrderSnapshot
    events: tuple[OrderEvent, ...]
    assessments: tuple[EvidenceAssessment, ...]

    def usable_assessments(self) -> tuple[EvidenceAssessment, ...]:
        """decision_at까지 이용 가능했던 증거의 판정. 늦은 증거는 보존하되 그 판단에 쓰지 않는다."""
        return tuple(assessment for assessment in self.assessments if assessment.available_at <= self.snapshot.decision_at)


def _reported_state(record: OrderRecord) -> tuple:
    return (
        record.status,
        record.status_source,
        record.filled_quantity,
        record.cancelled_quantity,
        record.broker_order_id,
        record.replacement_quantity,
        record.replacement_client_order_id,
    )


def _same_order_state(current: OrderRecord, record: OrderRecord) -> bool:
    # 출처·사건 참조·Broker Order ID를 뺀 주문 상태. 같으면 그 보고는 아무것도 바꾸지 않는다.
    keys = ("status", "filled_quantity", "cancelled_quantity", "replacement_quantity", "replacement_client_order_id")
    return all(getattr(current, key) == getattr(record, key) for key in keys)


def _unique_evidence(evidence: Iterable[OrderEvidence]) -> list[OrderEvidence]:
    by_id: dict[str, OrderEvidence] = {}
    for item in evidence:
        if not isinstance(item, OrderEvidence):
            raise ValueError("evidence must contain OrderEvidence values.")
        known = by_id.get(item.event.event_id)
        if known is None:
            by_id[item.event.event_id] = item
        elif known != item:
            raise OrderEventIntegrityError(f"evidence {item.event.event_id!r} was received with different content.")
    return list(by_id.values())


def _check_reports(client_order_id: str, items: list[OrderEvidence], confirming_source: OrderStatusSource) -> None:
    first = items[0].event.record
    terminal = None
    previous_item = None
    filled = cancelled = 0  # 지금까지 보고된 누적 체결, 체결 통보가 아닌 증거가 보고한 누적 취소 (체결 통보의 취소는 보고가 아님)
    for item in items:
        record = item.event.record
        if (record.contract_id, record.quantity) != (first.contract_id, first.quantity):
            raise OrderEventIntegrityError(f"order {client_order_id!r} changed its contract or quantity.")
        if previous_item is not None:
            previous = previous_item.event.record
            if item.event.available_at == previous_item.event.available_at and _reported_state(record) != _reported_state(previous):
                raise OrderEventIntegrityError(f"order {client_order_id!r} has two different reports available at the same time.")
        reports_cancels = item.evidence_kind is not OrderEvidenceKind.FILL_NOTIFICATION
        if abs(record.filled_quantity) < filled or (reports_cancels and abs(record.cancelled_quantity) < cancelled):
            raise OrderEventIntegrityError(f"order {client_order_id!r} has a reported cumulative quantity that decreased.")
        filled = abs(record.filled_quantity)
        if reports_cancels:
            cancelled = abs(record.cancelled_quantity)
        if record.status_source is confirming_source and reports_cancels:
            reported = (record.status, record.filled_quantity, record.cancelled_quantity)
            if terminal is not None and reported != terminal:
                raise OrderEventIntegrityError(f"order {client_order_id!r} was reported in another state after the terminal report.")
            if terminal is None and record.status in _TERMINAL_STATES:
                terminal = reported
        previous_item = item


def _check_observation_order(client_order_id: str, items: list[OrderEvidence], confirming_source: OrderStatusSource) -> None:
    # 도착 순서와 관계없이, 관측 시각 순서로 본 확인 출처의 보고는 누적 체결·취소가 줄지 않고 종료 뒤에는 같은 상태만 있어야 한다.
    # 체결 통보의 누적 체결은 엔진이 받은 순서로 센 값이라 제외한다. 같은 관측 시각의 보고끼리는 순서를 정하지 않는다.
    reports = sorted(
        (item for item in items
         if item.event.record.status_source is confirming_source and item.evidence_kind is not OrderEvidenceKind.FILL_NOTIFICATION),
        key=lambda item: item.event.occurred_at,
    )
    filled = cancelled = 0
    terminal = None
    for _, group in groupby(reports, key=lambda item: item.event.occurred_at):
        records = [item.event.record for item in group]
        for record in records:
            if abs(record.filled_quantity) < filled or abs(record.cancelled_quantity) < cancelled:
                raise OrderEventIntegrityError(f"order {client_order_id!r} has a cumulative quantity that decreased in observation order.")
            if terminal is not None and (record.status, record.filled_quantity, record.cancelled_quantity) != terminal:
                raise OrderEventIntegrityError(f"order {client_order_id!r} was observed in another state after a terminal report.")
        for record in records:
            filled = max(filled, abs(record.filled_quantity))
            cancelled = max(cancelled, abs(record.cancelled_quantity))
            if terminal is None and record.status in _TERMINAL_STATES:
                terminal = (record.status, record.filled_quantity, record.cancelled_quantity)


def _check_shared_broker_order_ids(broker_order_ids: dict[str, str], replacement_links: dict[str, set[str]]) -> None:
    # 한 Broker Order ID가 정정 관계(기존·새 주문)로 이어지지 않은 둘 이상의 주문에 묶이면 같은 주문이라고 고르지 않는다 (AT-0012-2).
    owners: dict[str, set[str]] = {}
    for client_order_id, broker_order_id in broker_order_ids.items():
        owners.setdefault(broker_order_id, set()).add(client_order_id)
    for broker_order_id, orders in owners.items():
        start = min(orders)
        reached = {start}
        frontier = [start]
        while frontier:
            for linked in replacement_links.get(frontier.pop(), ()):
                if linked in orders and linked not in reached:
                    reached.add(linked)
                    frontier.append(linked)
        if reached != orders:
            raise OrderEventIntegrityError(f"broker order id {broker_order_id!r} is reported for unrelated orders {sorted(orders)}.")


def _observed_from(item: OrderEvidence) -> datetime:
    # 보고가 반영할 수 있는 가장 이른 시각. 상태 조회는 요청 시각, 그 밖의 보고는 관측 시각 (BR-7).
    return item.requested_at if item.evidence_kind is OrderEvidenceKind.STATUS_QUERY_RESPONSE else item.event.occurred_at


def _marked_unknown(
    event: OrderEvent, current: OrderRecord, filled: int, broker_order_id: str | None, reason: str
) -> tuple[EvidenceDisposition, tuple[str, ...], OrderEvent]:
    marked = replace(
        current,
        status=OrderStatus.UNKNOWN,
        filled_quantity=filled,
        broker_order_id=broker_order_id or event.record.broker_order_id,
        status_source=event.record.status_source,
        status_event_ref=event.event_id,
    )
    return EvidenceDisposition.MARKED_UNKNOWN, (reason,), replace(event, record=marked, occurred_at=event.available_at)


def _fills_only(
    event: OrderEvent,
    current: OrderRecord | None,
    broker_order_id: str | None,
    reason: str = "FILL_NOTIFICATION_DOES_NOT_CONFIRM_ORDER_STATUS",
) -> tuple[EvidenceDisposition, tuple[str, ...], OrderEvent | None]:
    record = event.record
    if current is not None and current.status in _AWAITING_CONFIRMATION:
        base, status, cancelled = current, current.status, current.cancelled_quantity
    elif current is None and record.status is OrderStatus.UNKNOWN:
        return EvidenceDisposition.USED, (), event  # 첫 증거가 UNKNOWN을 알리는 체결 통보: 그대로 UNKNOWN
    elif current is None or current.status in _FILL_DERIVABLE_STATES:
        base = record if current is None else current
        cancelled = 0 if current is None else current.cancelled_quantity
        if record.quantity - record.filled_quantity - cancelled != 0:
            status = OrderStatus.PARTIALLY_FILLED
        elif cancelled == 0:
            status = OrderStatus.FILLED
        else:
            return EvidenceDisposition.DEFERRED, ("FILL_NOTIFICATION_CANNOT_SET_ORDER_STATUS",), None
    else:
        return EvidenceDisposition.USED, (), event  # 종료 상태의 주문: orders_as_of가 종료 뒤 변경을 검사한다
    derived = replace(
        base,
        status=status,
        filled_quantity=record.filled_quantity,
        cancelled_quantity=cancelled,
        replacement_quantity=base.replacement_quantity if status in _AWAITING_CONFIRMATION else None,
        replacement_client_order_id=base.replacement_client_order_id if status in _AWAITING_CONFIRMATION else None,
        broker_order_id=broker_order_id or record.broker_order_id,
        status_source=record.status_source,
        status_event_ref=event.event_id,
    )
    if derived == record:
        return EvidenceDisposition.USED, (), event
    return EvidenceDisposition.FILLS_ONLY, (reason,), replace(event, record=derived)


def _unknown_resolution(
    item: OrderEvidence, current: OrderRecord, awaiting_since: datetime
) -> tuple[EvidenceDisposition, tuple[str, ...], OrderEvent | None]:
    record = item.event.record
    if item.evidence_kind is OrderEvidenceKind.REQUEST_RESPONSE:
        return EvidenceDisposition.DEFERRED, ("UNKNOWN_NEEDS_STATUS_QUERY",), None
    reasons = []
    if item.requested_at < awaiting_since:
        reasons.append("STATUS_QUERY_REQUESTED_BEFORE_UNKNOWN")
    elif item.requested_at == awaiting_since:
        # 같은 시각이면 조회가 UNKNOWN 뒤의 상태를 본 것인지 확정할 수 없다 (브로커 시각의 의미는 검증되지 않음, BR-7).
        reasons.append("STATUS_QUERY_SAME_INSTANT_AS_UNKNOWN")
    if record.filled_quantity != current.filled_quantity:
        reasons.append("STATUS_QUERY_FILLS_DIFFER_FROM_CONFIRMED_FILLS")
    if current.replacement_client_order_id is not None:
        reasons.append("UNKNOWN_DURING_REPLACE_NOT_RESOLVED")
    if record.status in _LOWERING_RESULTS or record.cancelled_quantity != 0:
        reasons.append("RESOLUTION_WOULD_LOWER_UNKNOWN_WORST_CASE")
    elif record.status not in _UNKNOWN_RESOLUTIONS:
        reasons.append("STATUS_NOT_AN_APPROVED_UNKNOWN_RESOLUTION")
    if reasons:
        return EvidenceDisposition.DEFERRED, tuple(reasons), None
    return EvidenceDisposition.USED, (), item.event


def _dispose(
    item: OrderEvidence,
    current: OrderRecord | None,
    awaiting_since: datetime | None,
    broker_order_id: str | None,
    confirming_source: OrderStatusSource,
) -> tuple[EvidenceDisposition, tuple[str, ...], OrderEvent | None]:
    event, record, kind = item.event, item.event.record, item.evidence_kind
    if record.status_source is not OrderStatusSource.SYSTEM and record.status_source is not confirming_source:
        return EvidenceDisposition.REJECTED, ("SOURCE_MISMATCH",), None
    if broker_order_id is not None and record.broker_order_id not in (None, broker_order_id):
        if kind is OrderEvidenceKind.LOCAL_RECORD:
            raise OrderEventIntegrityError(f"order {record.client_order_id!r} has a system record for another broker order id.")
        return EvidenceDisposition.REJECTED, ("BROKER_ORDER_ID_MISMATCH",), None
    if kind is OrderEvidenceKind.LOCAL_RECORD:
        return EvidenceDisposition.USED, (), event  # 시스템 기록의 규칙(확인 수량·UNKNOWN 해소 불가)은 orders_as_of가 검사한다
    if current is not None and current.status is not OrderStatus.UNKNOWN and record.status is OrderStatus.UNKNOWN:
        filled = record.filled_quantity if kind is OrderEvidenceKind.FILL_NOTIFICATION else current.filled_quantity
        return _marked_unknown(event, current, filled, broker_order_id, "REPORTED_STATUS_UNKNOWN")
    if kind is OrderEvidenceKind.FILL_NOTIFICATION:
        return _fills_only(event, current, broker_order_id)
    if current is None or _same_order_state(current, record):
        return EvidenceDisposition.USED, (), event  # 첫 보고, 또는 같은 상태를 다시 알린 보고 (조회의 "찾지 못함"은 UNKNOWN 유지, BR-4)
    if current.status is OrderStatus.UNKNOWN:
        return _unknown_resolution(item, current, awaiting_since)
    if current.status in _AWAITING_CONFIRMATION and _observed_from(item) < awaiting_since:
        if record.filled_quantity != current.filled_quantity:
            return _marked_unknown(event, current, current.filled_quantity, broker_order_id, "REPORTED_FILLS_DIFFER_FROM_CONFIRMED_FILLS")
        return EvidenceDisposition.DEFERRED, ("REPORT_PRECEDES_PENDING_REQUEST",), None
    removes_remaining = record.status in _LOWERING_RESULTS or abs(record.cancelled_quantity) > abs(current.cancelled_quantity)
    if removes_remaining and record.filled_quantity != current.filled_quantity:
        return _marked_unknown(event, current, current.filled_quantity, broker_order_id, "REPORTED_FILLS_DIFFER_FROM_CONFIRMED_FILLS")
    if current.status in _PENDING_REQUESTS and record.status not in _TERMINAL_STATES:
        # 요청의 결과가 아닌 보고(접수 응답, 진행 중 상태 조회 등)는 취소·정정 요청 중 상태를 끝내지 않는다 (R9-6, RP-3, AT-0009-3).
        return _fills_only(event, current, broker_order_id, "REPORT_DOES_NOT_CONFIRM_PENDING_REQUEST")
    return EvidenceDisposition.USED, (), event


def orders_from_evidence_as_of(
    evidence: Iterable[OrderEvidence],
    decision_at: datetime,
    *,
    account_id: str,
    confirming_source: OrderStatusSource,
    completeness: OrderLogCompleteness,
    completeness_ref: str | None = None,
) -> EvidenceSnapshot:
    """주문 증거를 판정하고, 쓰는 기록만으로 decision_at의 주문 Snapshot을 만든다 (`orders_as_of` 재사용).

    입력: 한 계좌의 주문 증거, 판단 시각, 계좌 ID, 계좌의 확인 출처(BROKER 또는 SIMULATOR, 신뢰 경계 입력), 사건 기록의 완전성.
    출력: 증거별 판정(모든 시각)과 decision_at Snapshot. 판정은 주문마다 이용 가능 시각 순서로 그때까지 쓰인 기록에 따라 정해지므로,
    decision_at 뒤에 도착한 증거는 그 전 증거의 판정을 바꾸지 않고 Snapshot에도 들어가지 않는다 (ADR-0001 I-1). 다만 모순 검사는
    늦은 증거에도 적용된다 (모듈 설명).
    규칙: 모듈 설명. 확인 대기 구간(UNKNOWN, CANCEL_REQUESTED, REPLACE_REQUESTED)의 시작 시각은 그 구간을 시작한 기록의 발생 시각이며,
    대기 상태가 이어지면 앞 구간의 시작 시각보다 앞으로 가지 않는다.
    예외조건 (ValueError): 시간대 없는 decision_at, OrderEvidence가 아닌 값, 다른 계좌의 증거, BROKER·SIMULATOR가 아닌 확인 출처.
    모순(모듈 설명)과 `orders_as_of`의 모순 규칙은 OrderEventIntegrityError.
    """
    require_utc_instant(decision_at, "decision_at")
    account_id = require_identifier(account_id, "account_id")
    if confirming_source not in (OrderStatusSource.BROKER, OrderStatusSource.SIMULATOR):
        raise ValueError("confirming_source must be BROKER or SIMULATOR.")
    unique = _unique_evidence(evidence)
    if any(item.event.record.account_id != account_id for item in unique):
        raise ValueError("order evidence must belong to the account.")
    by_order: dict[str, list[OrderEvidence]] = {}
    for item in unique:
        by_order.setdefault(item.event.record.client_order_id, []).append(item)

    events = []
    assessments = []
    broker_order_ids: dict[str, str] = {}
    replacement_links: dict[str, set[str]] = {}
    for client_order_id in sorted(by_order):
        items = sorted(by_order[client_order_id], key=lambda item: (item.event.available_at, item.event.event_id))
        _check_reports(client_order_id, items, confirming_source)
        _check_observation_order(client_order_id, items, confirming_source)
        current = None
        awaiting_since = None
        broker_order_id = None
        for item in items:
            disposition, reasons, used = _dispose(item, current, awaiting_since, broker_order_id, confirming_source)
            assessments.append(
                EvidenceAssessment(
                    event_id=item.event.event_id,
                    client_order_id=client_order_id,
                    evidence_kind=item.evidence_kind,
                    source=item.event.record.status_source,
                    available_at=item.event.available_at,
                    disposition=disposition,
                    reasons=reasons,
                )
            )
            if disposition is EvidenceDisposition.REJECTED:
                continue
            record = item.event.record
            broker_order_id = broker_order_id or record.broker_order_id
            if record.replacement_client_order_id is not None:
                replacement_links.setdefault(client_order_id, set()).add(record.replacement_client_order_id)
                replacement_links.setdefault(record.replacement_client_order_id, set()).add(client_order_id)
            if used is not None:
                events.append(used)
                status = used.record.status
                if status not in _AWAITING_CONFIRMATION:
                    awaiting_since = None
                elif current is None or status is not current.status:
                    awaiting_since = used.occurred_at if awaiting_since is None else max(awaiting_since, used.occurred_at)
                current = used.record
            if (
                item.evidence_kind is not OrderEvidenceKind.LOCAL_RECORD
                and record.status is OrderStatus.UNKNOWN
                and current is not None
                and current.status is OrderStatus.UNKNOWN
            ):
                # UNKNOWN을 알린 보고는 쓰였든 아니든, 그 뒤의 해소는 그 보고를 받은 뒤에 요청한 조회여야 한다 (제한적 내용을 버리지 않음).
                awaiting_since = max(awaiting_since, item.event.available_at)
        if broker_order_id is not None:
            broker_order_ids[client_order_id] = broker_order_id
    _check_shared_broker_order_ids(broker_order_ids, replacement_links)

    snapshot = orders_as_of(events, decision_at, completeness=completeness, completeness_ref=completeness_ref)
    return EvidenceSnapshot(
        account_id=account_id,
        confirming_source=confirming_source,
        snapshot=snapshot,
        events=tuple(events),
        assessments=tuple(assessments),
    )
