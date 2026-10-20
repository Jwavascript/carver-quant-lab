"""예상 포지션, 주문 후보, 제출 전 로컬 검증 (P0-03B Slice 2).

ADR-0009 §5.1, §6.2, R9-1, R9-7, RP-1, RP-5, AT-0009-3, ADR-0003 §6.3, ADR-0012 BR-2·BR-12, ADR-0013 R13-5, ADR-0006 I6-5.
주문을 전송하지 않는다. 위험 증가·축소 판정, L1·L2 위험 한도, L3 Trading State 전이는 구현하지 않는다.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from carver_quant.lab.accounting.fill_ledger import FillLedger
from carver_quant.lab.accounting.positions import actual_position
from carver_quant.lab.domain.orders import OrderRecord, OrderStatus
from carver_quant.lab.domain.records import FillRecord, PositionBaseline
from carver_quant.lab.domain.values import require_int, require_utc_instant


class OrderIntegrityError(ValueError):
    """체결 기록과 주문 기록이 서로 맞지 않을 때 (ADR-0009 RP-4: 귀속할 주문이 없거나 계산이 맞지 않음)."""


class LocalValidationStatus(Enum):
    LOCAL_VALID = "LOCAL_VALID"
    LOCAL_INVALID = "LOCAL_INVALID"


class CandidateStatus(Enum):
    NO_ORDER_NEEDED = "NO_ORDER_NEEDED"  # 후보 0
    BLOCKED = "BLOCKED"  # 후보를 만들지 않음 (UNKNOWN 주문, 정정 요청 중, 취소 요청 중)
    LOCAL_INVALID = "LOCAL_INVALID"  # 후보는 기록했지만 제출 전 로컬 검사 실패
    LOCAL_VALID = "LOCAL_VALID"  # 로컬 검사 통과. 제출 승인이 아니다 (PENDING_SUBMISSION_CHECKS)


# 로컬 검사를 통과한 후보에도 남아 있는 ADR-0003 검사. 이 Slice는 이 검사들을 하지 않는다. 제출 전 단계의 전체 목록은
# 아니다 (ADR-0012 BR-3 제출 전 기록, 주문 유형·가격·시장 시간 같은 브로커 제약도 이 Slice 범위 밖).
PENDING_SUBMISSION_CHECKS = ("L1_L2_PRE_TRADE_RISK", "L3_TRADING_STATE")

# 기대 예상 포지션에 남은 수량을 넣는 진행 중 상태 (ADR-0009 §5.1 (a), R9-6).
_IN_PROGRESS_STATES = frozenset(
    {OrderStatus.PENDING_SUBMIT, OrderStatus.ACCEPTED, OrderStatus.PARTIALLY_FILLED, OrderStatus.CANCEL_REQUESTED}
)
_NOT_COMPUTABLE_REASONS = {OrderStatus.UNKNOWN: "UNKNOWN_ORDER", OrderStatus.REPLACE_REQUESTED: "REPLACE_PENDING"}
_REASON_ORDER = ("UNKNOWN_ORDER", "REPLACE_PENDING")


@dataclass(frozen=True)
class UnitProjection:
    """거래 단위(월물) 하나의 실제·진행 중 잔량·기대 예상·최악 경우 수량 (계약)."""

    contract_id: str
    actual_quantity: int
    open_remaining_quantity: int | None
    expected_projected_quantity: int | None
    worst_long_quantity: int
    worst_short_quantity: int
    not_computable_reasons: tuple[str, ...]


@dataclass(frozen=True)
class PositionProjection:
    account_id: str
    as_of: datetime
    units: tuple[UnitProjection, ...]
    unknown_client_order_ids: tuple[str, ...]

    def unit(self, contract_id: str) -> UnitProjection:
        for unit in self.units:
            if unit.contract_id == contract_id:
                return unit
        raise ValueError(f"no projection for contract {contract_id!r}.")


@dataclass(frozen=True)
class LocalValidation:
    contract_id: object
    quantity: object
    status: LocalValidationStatus
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class PreSubmissionResult:
    """후보 하나의 제출 전 결과. `worst_*_after`는 후보를 새 주문으로 더한 ADR-0003 §6.3 수량이다 (위험 판정 아님)."""

    contract_id: str
    target_quantity: int
    expected_projected_quantity: int | None
    candidate_quantity: int | None
    status: CandidateStatus
    reasons: tuple[str, ...]
    worst_long_after: int | None
    worst_short_after: int | None
    pending_checks: tuple[str, ...]


@dataclass(frozen=True)
class PreSubmissionReport:
    projection: PositionProjection
    results: tuple[PreSubmissionResult, ...]


def remaining_quantity(order: OrderRecord) -> int:
    """미체결 잔량 = 주문 수량 − 확인된 체결 수량 − 확인된 취소 수량 (ADR-0009 §5.1). 부호 있는 계약 수.

    기대 예상·최악 경우에 넣을지는 상태가 정한다 (project_positions). UNKNOWN 주문에는 확인된 잔량이 없으므로 ValueError다
    (최악 경우는 주문 수량 − 확인된 체결, BR-12).
    """
    if not isinstance(order, OrderRecord):
        raise ValueError("order must be an OrderRecord.")
    if order.status is OrderStatus.UNKNOWN:
        raise ValueError("an UNKNOWN order has no confirmed remaining quantity.")
    return order.quantity - order.filled_quantity - order.cancelled_quantity


def _worst_case_open_quantity(order: OrderRecord, replacement_recorded: bool) -> int:
    # 정정 주문이 따로 기록되어 있으면 그 기록의 상태로 집계하므로 여기서 정정 수량을 다시 더하지 않는다 (한 번만).
    replacement = 0 if replacement_recorded or order.replacement_quantity is None else order.replacement_quantity
    if order.status in _IN_PROGRESS_STATES:
        return remaining_quantity(order)
    if order.status is OrderStatus.REPLACE_REQUESTED:
        # RP-1: 기존 남은 수량 + 요청한 정정 수량 전체 (새 남은 수량으로 봄).
        return remaining_quantity(order) + replacement
    if order.status is OrderStatus.UNKNOWN:
        # ADR-0003 §6.3, BR-12: 확인되지 않은 수량 전부를 체결로 본다. 취소 보고로 줄이지 않는다 (Q12-14).
        # RP-5: 정정 응답 timeout이면 새 주문도 UNKNOWN이므로 정정 수량 전체를 더한다.
        return order.quantity - order.filled_quantity + replacement
    return 0  # INTENT(제출 전)와 종료 상태


def _checked_orders(orders: Iterable[OrderRecord], ledger: FillLedger) -> tuple[OrderRecord, ...]:
    checked = tuple(orders)
    contract_ids = ledger.contract_ids()
    seen = set()
    for order in checked:
        if not isinstance(order, OrderRecord):
            raise ValueError("orders must contain OrderRecord values.")
        if order.account_id != ledger.account_id:
            raise ValueError("an order belongs to another account.")
        if order.contract_id not in contract_ids:
            raise ValueError(f"order {order.client_order_id!r} has unknown contract_id {order.contract_id!r}.")
        if order.client_order_id in seen:
            raise ValueError(f"client_order_id {order.client_order_id!r} appears more than once.")
        seen.add(order.client_order_id)
    return checked


def _linked_replacements(orders: tuple[OrderRecord, ...]) -> frozenset[str]:
    """정정 주문이 자기 Client Order ID로 따로 기록된 기존 주문들의 Client Order ID.

    따로 기록된 정정 주문은 요청한 정정과 월물·수량이 같아야 하고 이미 제출된 상태여야 한다. 맞지 않으면 어느 쪽이
    맞는지 추정하지 않는다 (OrderIntegrityError).
    """
    by_id = {order.client_order_id: order for order in orders}
    seen = set()
    linked = set()
    for order in orders:
        replacement_id = order.replacement_client_order_id
        if replacement_id is None:
            continue
        if replacement_id in seen:
            raise ValueError(f"replacement_client_order_id {replacement_id!r} appears more than once.")
        seen.add(replacement_id)
        replacement = by_id.get(replacement_id)
        if replacement is None:
            continue
        if replacement.contract_id != order.contract_id or replacement.quantity != order.replacement_quantity:
            raise OrderIntegrityError(
                f"order {replacement_id!r} does not match the replacement requested by {order.client_order_id!r}."
            )
        if replacement.status is OrderStatus.INTENT:
            raise OrderIntegrityError(f"replacement {replacement_id!r} is recorded as not yet submitted.")
        linked.add(order.client_order_id)
    return frozenset(linked)


def _check_fill_attribution(
    orders: tuple[OrderRecord, ...], ledger: FillLedger, baseline: PositionBaseline, as_of: datetime
) -> None:
    by_id = {order.client_order_id: order for order in orders}
    fills_by_order: dict[str, list[FillRecord]] = {}
    for fill in ledger.applied:
        if fill.fill_at > as_of:
            raise ValueError("the ledger has a fill after as_of; order records may already include it.")
        order = by_id.get(fill.client_order_id)
        if order is None:
            if fill.fill_at > baseline.as_of:
                raise OrderIntegrityError(f"fill {fill.key.fill_id!r} cannot be attributed to a known order.")
            continue  # 기준 포지션에 이미 들어 있는 체결
        if fill.contract_id != order.contract_id:
            raise OrderIntegrityError(f"fill {fill.key.fill_id!r} is for another contract than its order.")
        if fill.broker_order_id is not None and order.broker_order_id is not None and fill.broker_order_id != order.broker_order_id:
            raise OrderIntegrityError(f"fill {fill.key.fill_id!r} has another broker order id than its order.")
        if (fill.quantity > 0) != (order.quantity > 0):
            raise OrderIntegrityError(f"fill {fill.key.fill_id!r} does not follow its order direction.")
        fills_by_order.setdefault(order.client_order_id, []).append(fill)
    for order in orders:
        total = sum(fill.quantity for fill in fills_by_order.get(order.client_order_id, ()))
        if total != order.filled_quantity:
            raise OrderIntegrityError(
                f"order {order.client_order_id!r} reports filled {order.filled_quantity} but the ledger has {total}."
            )


def project_positions(
    *,
    baseline: PositionBaseline,
    ledger: FillLedger,
    orders: Iterable[OrderRecord],
    as_of: datetime,
) -> PositionProjection:
    """월물별 실제·진행 중 잔량·기대 예상·최악 경우 포지션을 계산한다.

    공식 (월물 c, 계약 수):
        실제 A[c] = actual_position(기준, 장부, as_of) (R9-2)
        진행 중 잔량 R[c] = Σ 잔량(o), o는 PENDING_SUBMIT·ACCEPTED·PARTIALLY_FILLED·CANCEL_REQUESTED (§5.1 (a), R9-6)
        기대 예상 E[c] = A[c] + R[c] (R9-1). 같은 월물에 UNKNOWN·REPLACE_REQUESTED 주문이 있으면 계산 불가 (None)
        최악 경우 롱 = A[c] + Σ 매수 쪽 w(o), 숏 = A[c] + Σ 매도 쪽 w(o) (ADR-0003 §6.3, R9-7)
            w(o) = 잔량 (진행 중 상태), 잔량 + 정정 수량 (REPLACE_REQUESTED, RP-1),
            주문 − 확인된 체결 (+ 정정 수량) (UNKNOWN, BR-12, RP-5), 0 (INTENT, 종료 상태)
            정정 주문이 자기 Client Order ID로 따로 기록되어 있으면 정정 수량은 그 기록의 w로 한 번만 센다.
    입력: 검증된 기준 포지션, 반영 체결 장부, 주문 기록(현재 상태), 계산 시각.
    전제조건: 주문 기록의 체결 수량은 장부의 그 주문 체결 합과 같다. 장부의 모든 체결은 as_of 이전이다.
    예외조건: 계좌·월물 불일치, 같은 Client Order ID나 정정 주문 ID 중복, as_of 뒤의 체결은 ValueError. 체결과 주문이 맞지
    않으면 (합계·월물·방향·Broker Order ID 불일치, 기준 시각 뒤의 귀속 불가 체결) 또는 따로 기록된 정정 주문이 요청과 다르거나
    제출 전이면 OrderIntegrityError. 장부 충돌은 FillIntegrityError.
    """
    if not isinstance(ledger, FillLedger):
        raise ValueError("ledger must be a FillLedger.")
    require_utc_instant(as_of, "as_of")
    actual = actual_position(baseline, ledger, as_of)
    checked = _checked_orders(orders, ledger)
    _check_fill_attribution(checked, ledger, baseline, as_of)
    linked = _linked_replacements(checked)

    units = []
    for spec in ledger.contracts:
        contract_id = spec.contract_id
        actual_quantity = actual[contract_id]
        open_remaining = 0
        long_open = 0
        short_open = 0
        reasons = set()
        for order in checked:
            if order.contract_id != contract_id:
                continue
            worst = _worst_case_open_quantity(order, replacement_recorded=order.client_order_id in linked)
            if worst > 0:
                long_open += worst
            else:
                short_open += worst
            if order.status in _IN_PROGRESS_STATES:
                open_remaining += remaining_quantity(order)
            elif order.status in _NOT_COMPUTABLE_REASONS:
                reasons.add(_NOT_COMPUTABLE_REASONS[order.status])
        ordered_reasons = tuple(reason for reason in _REASON_ORDER if reason in reasons)
        units.append(
            UnitProjection(
                contract_id=contract_id,
                actual_quantity=actual_quantity,
                open_remaining_quantity=None if ordered_reasons else open_remaining,
                expected_projected_quantity=None if ordered_reasons else actual_quantity + open_remaining,
                worst_long_quantity=actual_quantity + long_open,
                worst_short_quantity=actual_quantity + short_open,
                not_computable_reasons=ordered_reasons,
            )
        )

    unknown_ids = set()
    for order in checked:
        if order.status is OrderStatus.UNKNOWN:
            unknown_ids.add(order.client_order_id)
            if order.replacement_client_order_id is not None and order.client_order_id not in linked:
                unknown_ids.add(order.replacement_client_order_id)  # RP-5: 따로 기록되지 않은 새 주문도 UNKNOWN
    return PositionProjection(
        account_id=ledger.account_id, as_of=as_of, units=tuple(units), unknown_client_order_ids=tuple(sorted(unknown_ids))
    )


def validate_new_order_quantity(*, ledger: FillLedger, contract_id: object, quantity: object) -> LocalValidation:
    """제출할 신규 주문 수량의 로컬 검사 (ADR-0013 R13-5, ADR-0006 I6-5, ADR-0012 BR-2 로컬 검증).

    검사: 장부에 있는 월물 ID인가, 0이 아닌 정수인가, lot size가 있는가, lot 배수인가.
    출력: LOCAL_VALID 또는 LOCAL_INVALID와 사유 (UNKNOWN_CONTRACT, QUANTITY_NOT_INTEGER, ZERO_QUANTITY, LOT_SIZE_MISSING,
    NOT_LOT_MULTIPLE). 수량을 반올림하거나 lot size를 1로 가정하지 않는다. 통과는 제출 승인이 아니다.
    """
    if not isinstance(ledger, FillLedger):
        raise ValueError("ledger must be a FillLedger.")
    reasons = []
    known_contract = isinstance(contract_id, str) and contract_id in ledger.contract_ids()
    if not known_contract:
        reasons.append("UNKNOWN_CONTRACT")
    is_integer = isinstance(quantity, int) and not isinstance(quantity, bool)
    if is_integer:
        quantity = int(quantity)  # int 하위 클래스의 비교·나머지 연산을 쓰지 않는다
    if not is_integer:
        reasons.append("QUANTITY_NOT_INTEGER")
    elif quantity == 0:
        reasons.append("ZERO_QUANTITY")
    if known_contract and is_integer and quantity != 0:
        lot_size = ledger.contract(contract_id).lot_size
        if lot_size is None:
            reasons.append("LOT_SIZE_MISSING")
        elif quantity % lot_size != 0:
            reasons.append("NOT_LOT_MULTIPLE")
    status = LocalValidationStatus.LOCAL_INVALID if reasons else LocalValidationStatus.LOCAL_VALID
    return LocalValidation(contract_id=contract_id, quantity=quantity, status=status, reasons=tuple(reasons))


def prepare_order_candidates(
    *,
    baseline: PositionBaseline,
    ledger: FillLedger,
    orders: Iterable[OrderRecord],
    targets: Mapping[str, int],
    as_of: datetime,
) -> PreSubmissionReport:
    """목표·실제·진행 중 주문에서 월물별 주문 후보를 계산하고 로컬 검사한다.

    공식: 후보[c] = 목표[c] − 기대 예상[c] (ADR-0009 R9-1). 후보는 lot 배수가 아니어도 기록하고 반올림하지 않는다 (R13-5).
    결과: NO_ORDER_NEEDED (후보 0), BLOCKED (계좌에 UNKNOWN 주문이 하나라도 있음 → 모든 월물, 그 월물의 기대 예상
    계산 불가, 또는 0이 아닌 후보인데 그 월물에 CANCEL_REQUESTED 주문이 있음 → 취소 확정 전에는 같은 월물에 새 주문을
    만들지 않음, ADR-0009 AT-0009-3), LOCAL_INVALID(사유), LOCAL_VALID (L1·L2 위험 검사와 L3 Trading State 확인은 남음).
    예외조건: 목표가 장부의 월물과 정확히 맞지 않음, 정수가 아님, lot size를 아는데 목표가 lot 배수가 아님 (I6-5) → ValueError.
    """
    orders = tuple(orders)
    projection = project_positions(baseline=baseline, ledger=ledger, orders=orders, as_of=as_of)
    cancel_pending = {order.contract_id for order in orders if order.status is OrderStatus.CANCEL_REQUESTED}
    if not isinstance(targets, Mapping):
        raise ValueError("targets must be a mapping of contract_id to int.")
    if set(targets) != ledger.contract_ids():
        raise ValueError("targets must list exactly the ledger contracts.")
    checked_targets = {}
    for contract_id, target in targets.items():
        target = require_int(target, "target position")
        lot_size = ledger.contract(contract_id).lot_size
        if lot_size is not None and target % lot_size != 0:
            raise ValueError(f"target position for {contract_id!r} must be a lot multiple (I6-5).")
        checked_targets[contract_id] = target

    results = []
    for unit in projection.units:
        target = checked_targets[unit.contract_id]
        if projection.unknown_client_order_ids or unit.expected_projected_quantity is None:
            reasons = ("UNKNOWN_ORDER_PRESENT",) if projection.unknown_client_order_ids else ()
            reasons += tuple(reason for reason in unit.not_computable_reasons if reason != "UNKNOWN_ORDER")
            results.append(_result(unit, target, None, CandidateStatus.BLOCKED, reasons))
            continue
        candidate = target - unit.expected_projected_quantity
        if candidate == 0:
            results.append(_result(unit, target, 0, CandidateStatus.NO_ORDER_NEEDED, ()))
            continue
        if unit.contract_id in cancel_pending:
            results.append(_result(unit, target, None, CandidateStatus.BLOCKED, ("CANCEL_PENDING",)))
            continue
        validation = validate_new_order_quantity(ledger=ledger, contract_id=unit.contract_id, quantity=candidate)
        status = (
            CandidateStatus.LOCAL_VALID
            if validation.status is LocalValidationStatus.LOCAL_VALID
            else CandidateStatus.LOCAL_INVALID
        )
        results.append(_result(unit, target, candidate, status, validation.reasons))

    return PreSubmissionReport(projection=projection, results=tuple(results))


def _result(
    unit: UnitProjection, target: int, candidate: int | None, status: CandidateStatus, reasons: tuple[str, ...]
) -> PreSubmissionResult:
    has_order = candidate is not None and candidate != 0
    return PreSubmissionResult(
        contract_id=unit.contract_id,
        target_quantity=target,
        expected_projected_quantity=unit.expected_projected_quantity,
        candidate_quantity=candidate,
        status=status,
        reasons=reasons,
        worst_long_after=unit.worst_long_quantity + max(candidate, 0) if has_order else None,
        worst_short_after=unit.worst_short_quantity + min(candidate, 0) if has_order else None,
        pending_checks=PENDING_SUBMISSION_CHECKS if status is CandidateStatus.LOCAL_VALID else (),
    )
