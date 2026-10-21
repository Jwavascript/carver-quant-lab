"""결정 시점의 주문 Snapshot과 그 Snapshot으로 하는 거래 전 위험 평가 (P0-03C Slice 2).

ADR-0001 I-1·B-1 (판단 입력은 `data_available_at ≤ decision_at`), ADR-0004 승인 원칙 5 (관측 시각과 이용 가능 시각 구분),
ADR-0009 §6.1·§6.2·R9-4, ADR-0012 BR-7. 주문마다 decision_at까지 이용 가능했던 마지막 기록 버전을 고른다. 늦게 도착한 사건은
과거 Snapshot에 넣지 않는다. 상태 전이를 다시 계산하지 않으며(주문 상태 기계 없음), 승인된 규칙에 어긋나는 기록은 고르지 않고
거부한다: 확인된 누적 체결·취소의 감소, 시스템 기록이 확인 수량을 만들거나 주문을 INTENT·PENDING_SUBMIT으로 되돌림 (결과는
브로커·시뮬레이터 확인으로만, §6.2, BR-3), 종료 상태 뒤의 변경, 시스템 기록에 의한 UNKNOWN 해소(R9-4), 취소·정정 요청이나
UNKNOWN보다 이른 시각의 보고가 그 상태를 바꿈 (R9-6, RP-3, R9-4), 같은 이용 가능 시각의 다른 상태, 주문 정체성(계좌·월물·수량)
변경, 같은 정정 주문의 다른 정정 수량, 같은 사건 ID의 다른 내용, 제출된 새 주문 기록 없이 사라진 정정 수량 (RP-1).

주문 상태만 PIT로 맞춘다. 체결 기록에는 이용 가능 시각이 없어(BR-7 미구현) Snapshot의 확인 누적 체결과 일치하는지만 검사하고,
기준 포지션 검증 시각, 한도 적용 시각, 장부 월물 사양의 시각은 검증하지 않는다 (`PIT_UNVERIFIED_INPUTS`). 영속 기록이 없으므로
사건 기록의 완전성은 호출 경계가 명시한다 (Q9-9, Q12-7). 확인되지 않으면 위험 판정은 NOT_ASSESSABLE이다.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from enum import Enum

from carver_quant.lab.accounting.fill_ledger import FillLedger
from carver_quant.lab.accounting.pretrade_risk import PreTradeRiskReport, RiskCheckStatus, assess_pretrade_risk
from carver_quant.lab.domain.order_events import OrderEvent
from carver_quant.lab.domain.orders import OrderRecord, OrderStatus, OrderStatusSource
from carver_quant.lab.domain.records import PositionBaseline, ValuationPrice
from carver_quant.lab.domain.risk import ContractMultiplier, ExposureLimit, TradingState
from carver_quant.lab.domain.values import require_identifier, require_utc_instant


class OrderEventIntegrityError(ValueError):
    """주문 사건 기록이 서로 모순되어 Snapshot을 정하지 않을 때. 어느 기록이 맞는지 고르지 않는다."""


class OrderLogCompleteness(Enum):
    VERIFIED_COMPLETE = "VERIFIED_COMPLETE"  # decision_at까지 이용 가능했던 주문 사건이 모두 들어 있음을 호출 경계가 확인 (근거 참조 필수)
    UNVERIFIED = "UNVERIFIED"  # 완전성을 확인하지 못함. 빠진 주문이 있을 수 있으므로 위험 판정에 쓰지 않음


# 이 Slice가 결정 시점 기준으로 검사하는 입력.
PIT_VERIFIED_INPUTS = (
    "ORDER_EVENT_AVAILABILITY",  # 주문 상태: available_at ≤ decision_at인 사건만
    "FILL_TIME_AND_ORDER_CONSISTENCY",  # 체결: fill_at ≤ decision_at, 주문별 합 = Snapshot의 확인 누적 체결
    "REFERENCE_PRICE_AVAILABILITY",  # 참조 가격: data_available_at·가격 시각 ≤ decision_at (Slice 1)
    "MULTIPLIER_AVAILABILITY",  # 승수 입력: data_available_at ≤ decision_at (Slice 1)
)

# 결정 시점 기준으로 검증하지 못하는 입력. 그래서 결과를 전체 PIT 판정이라고 하지 않는다.
PIT_UNVERIFIED_INPUTS = (
    "FILL_RECORD_AVAILABILITY",  # 체결 기록에 수신·이용 가능 시각이 없음 (ADR-0012 BR-7 미구현)
    "BASELINE_VERIFICATION_TIME",  # 검증된 기준 포지션의 검증 시각 (ADR-0013 Q13-2)
    "LIMIT_EFFECTIVE_TIME",  # 한도 입력의 적용 시각
    "LEDGER_CONTRACT_SPEC_TIME",  # 장부 월물 사양의 이용 가능 시각 (승수 입력은 검사함)
    "TARGET_POSITION_TIME",  # 목표 포지션 입력의 시각
    "TRADING_STATE_TIME",  # Trading State 입력의 시각
)

_TERMINAL_STATES = frozenset({OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED, OrderStatus.EXPIRED})
# 요청 결과나 상태 확인을 기다리는 상태. 그보다 이른 시각의 보고로는 이 상태를 바꿀 수 없다.
_AWAITING_CONFIRMATION = frozenset({OrderStatus.CANCEL_REQUESTED, OrderStatus.REPLACE_REQUESTED, OrderStatus.UNKNOWN})
# 제출 단계. 시스템 기록은 이 단계를 되돌리지 않는다 (BR-3: 로컬 판단에 의한 상태 되돌림 없음).
_SUBMISSION_STAGE = {OrderStatus.INTENT: 0, OrderStatus.PENDING_SUBMIT: 1}


@dataclass(frozen=True)
class SnapshotEntry:
    """주문 하나의 decision_at 기준 마지막 기록 버전과 그 사건."""

    record: OrderRecord
    event_id: str
    occurred_at: datetime
    available_at: datetime


@dataclass(frozen=True)
class OrderSnapshot:
    decision_at: datetime
    completeness: OrderLogCompleteness
    completeness_ref: str | None
    entries: tuple[SnapshotEntry, ...]
    late_event_ids: tuple[str, ...]

    def records(self) -> tuple[OrderRecord, ...]:
        return tuple(entry.record for entry in self.entries)


def _state(record: OrderRecord) -> tuple:
    return (
        record.status,
        record.status_source,
        record.filled_quantity,
        record.cancelled_quantity,
        record.broker_order_id,
        record.replacement_quantity,
        record.replacement_client_order_id,
    )


def _unique_events(events: Iterable[OrderEvent]) -> list[OrderEvent]:
    by_id: dict[str, OrderEvent] = {}
    for event in events:
        if not isinstance(event, OrderEvent):
            raise ValueError("events must contain OrderEvent values.")
        known = by_id.get(event.event_id)
        if known is None:
            by_id[event.event_id] = event
        elif known != event:
            raise OrderEventIntegrityError(f"event {event.event_id!r} was received with different content.")
    return list(by_id.values())


def _check_versions(client_order_id: str, versions: list[OrderEvent]) -> None:
    first = versions[0].record
    if first.status_source is OrderStatusSource.SYSTEM and (first.filled_quantity or first.cancelled_quantity):
        raise OrderEventIntegrityError(f"order {client_order_id!r} starts with confirmed quantities in a system record.")
    requested_replacements: dict[str, int] = {}
    for event in versions:
        replacement_id = event.record.replacement_client_order_id
        if replacement_id is not None:
            quantity = requested_replacements.setdefault(replacement_id, event.record.replacement_quantity)
            if quantity != event.record.replacement_quantity:
                raise OrderEventIntegrityError(
                    f"order {client_order_id!r} requested replacement {replacement_id!r} with different quantities."
                )
    for previous_event, current_event in zip(versions, versions[1:]):
        previous, current = previous_event.record, current_event.record
        if (current.account_id, current.contract_id, current.quantity) != (first.account_id, first.contract_id, first.quantity):
            raise OrderEventIntegrityError(f"order {client_order_id!r} changed its account, contract or quantity.")
        if current_event.available_at == previous_event.available_at and _state(current) != _state(previous):
            raise OrderEventIntegrityError(f"order {client_order_id!r} has two different states available at the same time.")
        if abs(current.filled_quantity) < abs(previous.filled_quantity) or abs(current.cancelled_quantity) < abs(previous.cancelled_quantity):
            raise OrderEventIntegrityError(f"order {client_order_id!r} has a confirmed cumulative quantity that decreased.")
        if previous.status in _TERMINAL_STATES and _state(current)[:4] != _state(previous)[:4]:
            raise OrderEventIntegrityError(f"order {client_order_id!r} changed after the terminal state {previous.status.name}.")
        if (
            previous.status is OrderStatus.UNKNOWN
            and current.status is not OrderStatus.UNKNOWN
            and current.status_source is OrderStatusSource.SYSTEM
        ):
            raise OrderEventIntegrityError(f"order {client_order_id!r} left UNKNOWN without a broker or simulator confirmation (R9-4).")
        if current.status_source is OrderStatusSource.SYSTEM:
            if abs(current.filled_quantity) > abs(previous.filled_quantity) or abs(current.cancelled_quantity) > abs(previous.cancelled_quantity):
                raise OrderEventIntegrityError(f"order {client_order_id!r} has fills or cancels confirmed by a system record (§6.2).")
            if _SUBMISSION_STAGE.get(current.status, 2) < _SUBMISSION_STAGE.get(previous.status, 2):
                raise OrderEventIntegrityError(f"order {client_order_id!r} was moved back to {current.status.name} by a system record (BR-3).")
        if (
            previous.status in _AWAITING_CONFIRMATION
            and current.status is not previous.status
            and current_event.occurred_at < previous_event.occurred_at
        ):
            raise OrderEventIntegrityError(
                f"order {client_order_id!r}: a report older than its {previous.status.name} record cannot change that state."
            )


def orders_as_of(
    events: Iterable[OrderEvent],
    decision_at: datetime,
    *,
    completeness: OrderLogCompleteness,
    completeness_ref: str | None = None,
) -> OrderSnapshot:
    """주문마다 decision_at까지 이용 가능했던 마지막 기록 버전을 고른다.

    규칙: 사건 e를 쓸 수 있는 조건은 `e.available_at ≤ decision_at` (ADR-0001 I-1, B-1: 같은 시각은 허용). 주문별로 쓸 수 있는
    사건 가운데 `available_at`이 가장 늦은 기록이 그 주문의 Snapshot이다. 쓸 수 있는 사건이 없는 주문은 Snapshot에 없고, 늦게
    도착한 사건 ID는 `late_event_ids`로 남긴다 (사건이 없었다고 주문이 없었다고 보지 않는다).
    같은 사건 ID의 같은 내용은 한 번만 쓴다. 기록 전체에서 모순(모듈 설명)을 찾으면 OrderEventIntegrityError.
    Snapshot의 마지막 기록이 그 전에 알려진 정정 주문(`replacement_client_order_id`)을 더 가리키지 않으면, 그 정정 주문이 요청한
    월물·수량으로 제출된 기록(INTENT가 아님)으로 Snapshot에 있어야 한다. 없으면 정정 수량이 사라지므로 OrderEventIntegrityError (RP-1).
    예외조건 (ValueError): 시간대 없는 decision_at, OrderEvent가 아닌 값, 여러 계좌의 사건, VERIFIED_COMPLETE인데 근거 참조 없음.
    """
    require_utc_instant(decision_at, "decision_at")
    if not isinstance(completeness, OrderLogCompleteness):
        raise ValueError("completeness must be an OrderLogCompleteness.")
    if completeness is OrderLogCompleteness.VERIFIED_COMPLETE:
        completeness_ref = require_identifier(completeness_ref, "completeness_ref")
    elif completeness_ref is not None:
        completeness_ref = require_identifier(completeness_ref, "completeness_ref")

    unique = _unique_events(events)
    if len({event.record.account_id for event in unique}) > 1:
        raise ValueError("order events must belong to one account.")
    by_order: dict[str, list[OrderEvent]] = {}
    for event in unique:
        by_order.setdefault(event.record.client_order_id, []).append(event)

    entries = []
    for client_order_id in sorted(by_order):
        versions = sorted(by_order[client_order_id], key=lambda event: event.available_at)
        _check_versions(client_order_id, versions)
        usable = [event for event in versions if event.available_at <= decision_at]
        if usable:
            latest = usable[-1]
            entries.append(
                SnapshotEntry(
                    record=latest.record,
                    event_id=latest.event_id,
                    occurred_at=latest.occurred_at,
                    available_at=latest.available_at,
                )
            )

    known_records = {entry.record.client_order_id: entry.record for entry in entries}
    for entry in entries:
        order = entry.record
        requested = {
            event.record.replacement_client_order_id: event.record.replacement_quantity
            for event in by_order[order.client_order_id]
            if event.available_at <= decision_at and event.record.replacement_client_order_id is not None
        }
        for replacement_id, quantity in sorted(requested.items()):
            if replacement_id == order.replacement_client_order_id:
                continue  # 아직 연결된 정정은 project_positions가 검사하고 한 번만 센다
            replacement = known_records.get(replacement_id)
            if (
                replacement is None
                or replacement.status is OrderStatus.INTENT
                or replacement.contract_id != order.contract_id
                or replacement.quantity != quantity
            ):
                raise OrderEventIntegrityError(
                    f"order {order.client_order_id!r} no longer carries its replacement {replacement_id!r}, and no submitted "
                    "record of it with the requested contract and quantity is known."
                )

    late = sorted(event.event_id for event in unique if event.available_at > decision_at)
    return OrderSnapshot(
        decision_at=decision_at,
        completeness=completeness,
        completeness_ref=completeness_ref,
        entries=tuple(entries),
        late_event_ids=tuple(late),
    )


@dataclass(frozen=True)
class PitRiskReport:
    """결정 시점 주문 Snapshot과 그 Snapshot으로 낸 거래 전 위험 결과. 검증한 입력과 검증하지 못한 입력을 함께 싣는다."""

    snapshot: OrderSnapshot
    risk: PreTradeRiskReport
    pit_verified: tuple[str, ...]
    pit_unverified: tuple[str, ...]


def assess_pretrade_risk_as_of(
    *,
    baseline: PositionBaseline,
    ledger: FillLedger,
    events: Iterable[OrderEvent],
    completeness: OrderLogCompleteness,
    completeness_ref: str | None = None,
    targets: Mapping[str, int],
    decision_at: datetime,
    trading_state: TradingState,
    reference_prices: Mapping[str, ValuationPrice],
    multipliers: Mapping[str, ContractMultiplier],
    limits: Mapping[str, ExposureLimit],
) -> PitRiskReport:
    """주문 사건에서 decision_at Snapshot을 만들고 그 주문 기록으로 `assess_pretrade_risk`(P0-03C Slice 1)를 실행한다.

    최신 주문 기록으로 과거 판단을 대신하지 않는다. 체결 장부는 그 시점에 알던 체결이어야 한다: 주문별 체결 합이 Snapshot의
    확인 누적 체결과 다르면 OrderIntegrityError (뒤에 알게 된 체결을 그 시점의 실제 포지션으로 만들지 않음). 사건 기록의
    완전성이 확인되지 않았으면 모든 월물의 위험 판정을 NOT_ASSESSABLE(ORDER_LOG_NOT_VERIFIED_COMPLETE)로 바꾼다.
    결과는 전체 PIT 판정이 아니며 `pit_unverified`에 검증하지 못한 입력이 늘 있다.
    예외조건: `orders_as_of`와 `assess_pretrade_risk`의 예외조건.
    """
    snapshot = orders_as_of(events, decision_at, completeness=completeness, completeness_ref=completeness_ref)
    report = assess_pretrade_risk(
        baseline=baseline,
        ledger=ledger,
        orders=snapshot.records(),
        targets=targets,
        decision_at=decision_at,
        trading_state=trading_state,
        reference_prices=reference_prices,
        multipliers=multipliers,
        limits=limits,
    )
    unverified = PIT_UNVERIFIED_INPUTS
    if completeness is not OrderLogCompleteness.VERIFIED_COMPLETE:
        unverified = unverified + ("ORDER_LOG_COMPLETENESS",)
        report = replace(
            report,
            views=tuple(
                replace(
                    view,
                    risk_status=RiskCheckStatus.NOT_ASSESSABLE,
                    risk_reasons=view.risk_reasons + ("ORDER_LOG_NOT_VERIFIED_COMPLETE",),
                )
                for view in report.views
            ),
        )
    return PitRiskReport(snapshot=snapshot, risk=report, pit_verified=PIT_VERIFIED_INPUTS, pit_unverified=unverified)
