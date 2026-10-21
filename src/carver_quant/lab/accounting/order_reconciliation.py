"""P0-03C Slice 5 읽기 전용 주문 대조: 결정 시점의 로컬 주문 Snapshot과 외부 브로커 Snapshot의 비교 (순수 함수).

ADR-0012 BR-4·BR-6·BR-7·BR-10·§6.3a, ADR-0009 R9-4·R9-8·R9-13, ADR-0003 S-3·§6.5, ADR-0001 I-1·B-1. 로컬 쪽은 기존
`orders_from_evidence_as_of`의 결과(EvidenceSnapshot)를 그대로 받는다. 결과는 비교한 항목의 일치·불일치·확인 불가와 그 사유뿐이다.
주문 상태·체결·포지션·Trading State를 바꾸지 않고, 증거나 주문 기록을 새로 만들지 않으며, UNKNOWN을 해소하지 않는다 (R9-4, Q12-14).
불일치에 따른 HALTED 전이(S-3, R9-8)와 대조 완료·HALTED 해제 판단(§6.5)은 L3 shell의 일이며 여기서 하지 않는다.

규칙:
- 브로커 Snapshot은 `available_at ≤ decision_at`일 때만 쓴다. 계좌의 확인 출처와 Snapshot의 출처가 다르면 쓰지 않는다.
- 주문은 Client Order ID로 잇는다. 보고에 Client Order ID가 없으면 Broker Order ID로만 잇고, 이을 근거가 없으면 수량이 같아도 잇지 않는다.
  같은 Broker Order ID를 정정으로 이어지지 않은 두 주문이 가지면 충돌이다 (BROKER_ORDER_ID_CONFLICT). 브로커가 Broker Order ID를
  보고한 주문을 "브로커에 없음"이라고 하지 않는다 (BR-4).
- 설명된 차이를 인정하지 않는다: 다른 값은 MISMATCH다 (BR-10, 브로커 시각의 의미가 확인되지 않음). 같은 값도 로컬 상태에 Snapshot의
  관측 시각보다 늦게 발생한 사건이 들어 있으면 같은 기준 시각의 비교가 아니므로 UNVERIFIED다 (R9-13). 그 시각은 마지막으로 도착한
  기록이 아니라 결정 시점까지 이용 가능했던 그 주문의 모든 기록 가운데 가장 늦은 발생 시각이다 (도착 순서가 바뀌어도 같음).
- 로컬 UNKNOWN의 상태는 비교하지 않는다 (UNVERIFIED). 기록된 잔량(주문 − 확인 체결 − 확인 취소)은 비교하지만 같아도 해소가 아니다.
  확인을 기다리는 로컬 요청(제출·취소·정정)의 결과도 Snapshot으로 확정하지 않는다.
- 목록에 없는 주문은 그 범위의 완전한 목록일 때만 불일치이며, 그것도 주문이 없다는 뜻이 아니다 (BR-4). 범위 밖이거나 완전성이
  선언되지 않았으면 UNVERIFIED다.
"""

from dataclasses import replace
from datetime import datetime

from carver_quant.lab.accounting.order_snapshot import OrderLogCompleteness, SnapshotEntry
from carver_quant.lab.accounting.unknown_resolution import EvidenceSnapshot
from carver_quant.lab.domain.orders import OrderRecord, OrderStatus
from carver_quant.lab.domain.reconciliation import (
    RECONCILIATION_NOT_ESTABLISHED,
    BrokerOrderReport,
    BrokerOrderSnapshot,
    BrokerSnapshotCompleteness,
    BrokerSnapshotScope,
    FieldComparison,
    OrderReconciliation,
    OrderReconciliationReport,
    ReconciliationStatus,
)
from carver_quant.lab.domain.values import require_utc_instant

MATCH = ReconciliationStatus.MATCH
MISMATCH = ReconciliationStatus.MISMATCH
UNVERIFIED = ReconciliationStatus.UNVERIFIED

_TERMINAL_STATES = frozenset({OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED, OrderStatus.EXPIRED})
# 시스템이 보낸 요청의 결과를 기다리는 상태. Snapshot이 다른 상태를 보고해도 그 요청의 결과로 확정하지 않는다.
_PENDING_REQUESTS = frozenset({OrderStatus.PENDING_SUBMIT, OrderStatus.CANCEL_REQUESTED, OrderStatus.REPLACE_REQUESTED})


def _side(quantity: int) -> str:
    return "BUY" if quantity > 0 else "SELL"


def _local_remaining(record: OrderRecord) -> int:
    """기록된 미체결 잔량. 종료 상태는 0이고, UNKNOWN은 확인되지 않은 나머지(주문 − 확인 체결 − 확인 취소)다."""
    if record.status in _TERMINAL_STATES:
        return 0
    return record.quantity - record.filled_quantity - record.cancelled_quantity


def _compared(name: str, local_value: str | int, broker_value: str | int, reason: str, *, quantity: bool = False) -> FieldComparison:
    status = MATCH if local_value == broker_value else MISMATCH
    return FieldComparison(
        name=name,
        local_value=local_value,
        broker_value=broker_value,
        status=status,
        reason=None if status is MATCH else reason,
        difference=broker_value - local_value if quantity else None,
    )


def _unverified(name: str, local_value: str | int | None, broker_value: str | int | None, reason: str) -> FieldComparison:
    return FieldComparison(name=name, local_value=local_value, broker_value=broker_value, status=UNVERIFIED, reason=reason,
                           difference=None)


def _status_field(local: OrderRecord, broker: BrokerOrderReport) -> FieldComparison:
    if local.status is OrderStatus.UNKNOWN:
        return _unverified("status", local.status.value, broker.status.value, "LOCAL_STATUS_UNKNOWN")
    if broker.status is OrderStatus.UNKNOWN:
        return _unverified("status", local.status.value, broker.status.value, "BROKER_STATUS_UNKNOWN")
    if local.status in _PENDING_REQUESTS and local.status is not broker.status:
        return _unverified("status", local.status.value, broker.status.value, "LOCAL_REQUEST_PENDING")
    return _compared("status", local.status.value, broker.status.value, "STATUS_MISMATCH")


def _order(client_order_id: str | None, broker_order_id: str | None, local: OrderRecord | None, broker: BrokerOrderReport | None,
           status: ReconciliationStatus, reasons: tuple[str, ...], fields: tuple[FieldComparison, ...] = ()) -> OrderReconciliation:
    return OrderReconciliation(client_order_id=client_order_id, broker_order_id=broker_order_id, local=local, broker=broker,
                               status=status, reasons=reasons, fields=fields)


def _held_by_unrelated_order(client_order_id: str, broker_order_id: str, by_broker_id: dict[str, list[SnapshotEntry]],
                             links: set[frozenset[str]]) -> bool:
    """정정으로 이어지지 않은 다른 로컬 주문이 이 Broker Order ID를 가졌는가."""
    return any(entry.record.client_order_id != client_order_id and frozenset({client_order_id, entry.record.client_order_id}) not in links
               for entry in by_broker_id.get(broker_order_id, ()))


def _broker_order_id_field(local: OrderRecord, broker: BrokerOrderReport, conflict: bool) -> FieldComparison:
    if local.broker_order_id is not None:
        return _compared("broker_order_id", local.broker_order_id, broker.broker_order_id, "BROKER_ORDER_ID_MISMATCH")
    if conflict:
        return FieldComparison(name="broker_order_id", local_value=None, broker_value=broker.broker_order_id, status=MISMATCH,
                               reason="BROKER_ORDER_ID_CONFLICT", difference=None)
    return _unverified("broker_order_id", None, broker.broker_order_id, "LOCAL_BROKER_ORDER_ID_NOT_RECORDED")


def _compare(entry: SnapshotEntry, broker: BrokerOrderReport, observed_at: datetime, reference_at: datetime,
             conflict: bool) -> OrderReconciliation:
    local = entry.record
    fields = [
        _unverified("client_order_id", local.client_order_id, None, "CLIENT_ORDER_ID_NOT_REPORTED")
        if broker.client_order_id is None
        else _compared("client_order_id", local.client_order_id, broker.client_order_id, "CLIENT_ORDER_ID_MISMATCH"),
        _broker_order_id_field(local, broker, conflict),
        _compared("contract_id", local.contract_id, broker.contract_id, "CONTRACT_MISMATCH"),
        _compared("side", _side(local.quantity), _side(broker.quantity), "SIDE_MISMATCH"),
        _compared("quantity", local.quantity, broker.quantity, "ORDER_QUANTITY_MISMATCH", quantity=True),
        _compared("filled_quantity", local.filled_quantity, broker.filled_quantity, "FILLED_QUANTITY_MISMATCH", quantity=True),
        _compared("remaining_quantity", _local_remaining(local), broker.remaining_quantity, "REMAINING_QUANTITY_MISMATCH",
                  quantity=True),
        _status_field(local, broker),
    ]
    if reference_at > observed_at:
        # 로컬 상태가 Snapshot보다 새로우면 같은 기준 시각의 비교가 아니다 (R9-13): 같은 값은 확인 불가, 다른 값은 불일치 그대로 (BR-10).
        fields = [replace(field, status=UNVERIFIED, reason="NOT_SAME_REFERENCE_TIME") if field.status is MATCH else field
                  for field in fields]
    statuses = {field.status for field in fields}
    status = MISMATCH if MISMATCH in statuses else UNVERIFIED if UNVERIFIED in statuses else MATCH
    reasons = tuple(dict.fromkeys(field.reason for field in fields if field.reason is not None))
    return _order(local.client_order_id, broker.broker_order_id, local, broker, status, reasons, tuple(fields))


def _absent(entry: SnapshotEntry, snapshot: BrokerOrderSnapshot, unlinked: list[BrokerOrderReport], reference_at: datetime,
            lines_by_broker_id: dict[str, BrokerOrderReport], links: set[frozenset[str]]) -> OrderReconciliation:
    """Client Order ID로 이어지지 않은 로컬 주문. 완전한 목록의 범위 안에서 있어야 할 주문일 때만 "브로커에 없음"이다."""
    record = entry.record
    reported = None if record.broker_order_id is None else lines_by_broker_id.get(record.broker_order_id)
    if record.status is OrderStatus.INTENT:
        reason = "LOCAL_ORDER_NOT_SUBMITTED"
    elif reported is not None:
        # 브로커가 이 주문의 Broker Order ID를 다른 Client Order ID로, 또는 Client Order ID 없이 보고했다. 브로커에 없다는 뜻이 아니다.
        if reported.client_order_id is not None and frozenset({record.client_order_id, reported.client_order_id}) not in links:
            return _order(record.client_order_id, record.broker_order_id, record, None, MISMATCH, ("BROKER_ORDER_ID_CONFLICT",))
        reason = "BROKER_ORDER_NOT_LINKED"
    elif snapshot.scope is BrokerSnapshotScope.ORDER_QUERY:
        queried = record.client_order_id in snapshot.queried_client_order_ids
        reason = "NOT_FOUND_IS_NOT_PROOF_OF_ABSENCE" if queried else "OUTSIDE_SNAPSHOT_SCOPE"
    elif snapshot.scope is BrokerSnapshotScope.OPEN_ORDERS and _local_remaining(record) == 0:
        reason = "OUTSIDE_SNAPSHOT_SCOPE"
    elif snapshot.completeness is not BrokerSnapshotCompleteness.COMPLETE_FOR_SCOPE:
        reason = "BROKER_SNAPSHOT_INCOMPLETE"
    elif reference_at > snapshot.observed_at:
        reason = "NOT_SAME_REFERENCE_TIME"
    elif record.broker_order_id is None and any(line.contract_id == record.contract_id for line in unlinked):
        reason = "BROKER_ORDER_NOT_LINKED"
    else:
        return _order(record.client_order_id, record.broker_order_id, record, None, MISMATCH, ("ORDER_MISSING_AT_BROKER",))
    return _order(record.client_order_id, record.broker_order_id, record, None, UNVERIFIED, (reason,))


def _broker_only(line: BrokerOrderReport, unpaired_local: list[OrderRecord],
                 by_broker_id: dict[str, list[SnapshotEntry]]) -> OrderReconciliation:
    """로컬 기록과 이을 수 없는 브로커 보고. 로컬 주문으로 만들지 않는다."""
    if line.client_order_id is None and (
        len(by_broker_id.get(line.broker_order_id, ())) > 1
        or any(record.broker_order_id is None and record.contract_id == line.contract_id for record in unpaired_local)
    ):
        return _order(None, line.broker_order_id, None, line, UNVERIFIED, ("BROKER_ORDER_NOT_LINKED",))
    return _order(line.client_order_id, line.broker_order_id, None, line, MISMATCH, ("ORDER_MISSING_LOCALLY",))


def _reconcile_orders(local: EvidenceSnapshot, snapshot: BrokerOrderSnapshot) -> tuple[OrderReconciliation, ...]:
    entries = local.snapshot.entries
    usable = [event for event in local.events if event.available_at <= local.snapshot.decision_at]
    # 주문마다 로컬 상태에 반영된 기록의 가장 늦은 발생 시각. 늦게 도착한 이른 보고가 그 뒤에 발생한 사건을 가리지 않게 한다.
    reference: dict[str, datetime] = {}
    for event in usable:
        client_order_id = event.record.client_order_id
        reference[client_order_id] = max(reference.get(client_order_id, event.occurred_at), event.occurred_at)
    links = {frozenset({event.record.client_order_id, event.record.replacement_client_order_id})
             for event in usable if event.record.replacement_client_order_id is not None}
    lines_by_broker_id = {line.broker_order_id: line for line in snapshot.orders}
    by_client = {entry.record.client_order_id: entry for entry in entries}
    by_broker_id: dict[str, list[SnapshotEntry]] = {}
    for entry in entries:
        if entry.record.broker_order_id is not None:
            by_broker_id.setdefault(entry.record.broker_order_id, []).append(entry)
    reported = {line.client_order_id for line in snapshot.orders if line.client_order_id is not None}

    paired: dict[str, BrokerOrderReport] = {}
    unpaired: list[BrokerOrderReport] = []
    for line in snapshot.orders:
        if line.client_order_id is not None:
            target = by_client.get(line.client_order_id)
        else:
            candidates = [entry for entry in by_broker_id.get(line.broker_order_id, ()) if entry.record.client_order_id not in reported]
            target = candidates[0] if len(candidates) == 1 else None
        if target is None or target.record.client_order_id in paired:
            unpaired.append(line)
        else:
            paired[target.record.client_order_id] = line

    unlinked = [line for line in unpaired if line.client_order_id is None]
    unpaired_local = [entry.record for entry in entries
                      if entry.record.client_order_id not in paired and entry.record.status is not OrderStatus.INTENT
                      and entry.record.status not in _TERMINAL_STATES]
    results = []
    for entry in entries:
        client_order_id = entry.record.client_order_id
        reference_at = max(reference.get(client_order_id, entry.occurred_at), entry.occurred_at)
        line = paired.get(client_order_id)
        if line is None:
            results.append(_absent(entry, snapshot, unlinked, reference_at, lines_by_broker_id, links))
        else:
            conflict = _held_by_unrelated_order(client_order_id, line.broker_order_id, by_broker_id, links)
            results.append(_compare(entry, line, snapshot.observed_at, reference_at, conflict))
    for line in sorted(unpaired, key=lambda line: (line.client_order_id or "", line.broker_order_id)):
        results.append(_broker_only(line, unpaired_local, by_broker_id))
    return tuple(results)


def reconcile_order_snapshot(local: EvidenceSnapshot, broker: BrokerOrderSnapshot, decision_at: datetime) -> OrderReconciliationReport:
    """결정 시점의 로컬 주문 Snapshot과 브로커 Snapshot을 주문별로 비교한다.

    입력: `orders_from_evidence_as_of`의 결과 (그 decision_at, 계좌, 확인 출처, 기록 완전성), 같은 계좌의 브로커 Snapshot, 판단 시각.
    출력: 주문별 대조(필드별 일치·불일치·확인 불가와 사유, 수량 차이 = 브로커 − 로컬)와 요약. 로컬 주문, 그다음 로컬 기록과 이을 수
    없는 브로커 보고의 순서다. 입력을 바꾸지 않고 증거·주문 기록·Trading State를 만들지 않는다.
    Snapshot을 쓸 수 없으면 (이용 가능 시각이 판단 시각 뒤, 출처가 계좌의 확인 출처와 다름) 브로커 보고를 비교하지 않고 모든 로컬 주문이
    UNVERIFIED다. 목록이 그 범위에서 완전하다고 선언되지 않았거나 로컬 기록의 완전성이 확인되지 않았으면 요약은 MATCH가 될 수 없다.
    예외조건 (ValueError): 시간대 없는 판단 시각, EvidenceSnapshot·BrokerOrderSnapshot이 아닌 값, 로컬 Snapshot의 판단 시각이 다름,
    다른 계좌의 Snapshot.
    """
    require_utc_instant(decision_at, "decision_at")
    if not isinstance(local, EvidenceSnapshot):
        raise ValueError("local must be an EvidenceSnapshot from orders_from_evidence_as_of.")
    if not isinstance(broker, BrokerOrderSnapshot):
        raise ValueError("broker must be a BrokerOrderSnapshot.")
    if local.snapshot.decision_at != decision_at:
        raise ValueError("the local order snapshot was taken for another decision time.")
    if broker.account_id != local.account_id:
        raise ValueError("the broker snapshot belongs to another account.")

    unusable = None
    if broker.available_at > decision_at:
        unusable = "SNAPSHOT_NOT_AVAILABLE_AT_DECISION"
    elif broker.source is not local.confirming_source:
        unusable = "SOURCE_MISMATCH"
    reasons = [] if unusable is None else [unusable]
    if broker.completeness is not BrokerSnapshotCompleteness.COMPLETE_FOR_SCOPE:
        reasons.append("BROKER_SNAPSHOT_INCOMPLETE")
    if local.snapshot.completeness is not OrderLogCompleteness.VERIFIED_COMPLETE:
        reasons.append("LOCAL_ORDER_LOG_NOT_VERIFIED_COMPLETE")

    if unusable is not None:
        orders = tuple(_order(entry.record.client_order_id, entry.record.broker_order_id, entry.record, None, UNVERIFIED, (unusable,))
                       for entry in local.snapshot.entries)
    else:
        orders = _reconcile_orders(local, broker)
    statuses = {order.status for order in orders}
    if MISMATCH in statuses:
        status = MISMATCH
    elif reasons or UNVERIFIED in statuses:
        status = UNVERIFIED
    else:
        status = MATCH
    return OrderReconciliationReport(
        account_id=local.account_id,
        decision_at=decision_at,
        snapshot_id=broker.snapshot_id,
        snapshot_observed_at=broker.observed_at,
        snapshot_available_at=broker.available_at,
        scope=broker.scope,
        status=status,
        reasons=tuple(reasons),
        orders=orders,
        not_established=RECONCILIATION_NOT_ESTABLISHED,
    )
