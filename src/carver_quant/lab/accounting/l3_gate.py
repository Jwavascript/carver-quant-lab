"""L3 Trading State 안전 게이트: 위험 결과, 증거 검사를 거친 주문 상태, Trading State 기록으로 하는 차단 판정 (P0-03C Slice 3).

ADR-0003 §6.2·§6.2.1·§6.3·§6.5, ADR-0009 원칙 8·9·R9-12, ADR-0012 승인 원칙 15·AT-0012-1, ADR-0013 R13-6, ADR-0001 I-1.
결과는 월물마다 BLOCKED / NOT_ASSESSABLE / NO_BLOCK_FOUND다. NO_BLOCK_FOUND는 이 게이트가 검사한 범위에서 차단 사유를 찾지
못했다는 뜻이며 주문 제출 승인이나 전송 허가가 아니다 (`not_checked`에 검사하지 않은 단계가 늘 있다). Trading State를 정하거나
바꾸지 않는다. 상태 결정과 전이(해제 포함)는 L3 shell의 일이고 (ADR-0003 §6.1, ADR-0010 §6.2 초안의 `engine/live`), 이 함수는
그 결과 기록을 입력으로만 받는다. 배치: Slice 1처럼 `lab.accounting`에 두며 최종 소유 위치는 정하지 않았다 (Q10-4).

차단 (BLOCKED):
- Trading State HALTED (기록 또는 호출자 입력): 자동 주문 금지, 위험 축소 포함. 위험 한도 통과로 풀리지 않는다.
- UNKNOWN 주문, 또는 쓰지 않은 모순 증거(REJECTED: 출처·Broker Order ID 불일치)가 결정 시각까지 있었음 (§6.3, §6.5).
- 마지막 UNKNOWN 해소가 쓰는 Trading State 기록과 같거나 늦음: UNKNOWN으로 생긴 HALTED 조건은 원인 해소 뒤의 해제 기록으로만
  풀리므로 그 전의 NORMAL·RESTRICTED 기록으로 차단을 풀지 않는다 (§6.5, ADR-0009 원칙 9, AT-0012-1).
- RESTRICTED에서 위험 증가 후보. NORMAL·RESTRICTED에서 위험 축소를 포함한 후보: 검증된 위험 축소(S-1~S-7, §6.2.2)를 이 게이트가
  확인하지 않으므로 차단한다 (§6.2.1: 하나라도 확인하지 못하면 차단, §6.5 NORMAL 행).
- Slice 1·P0-03B Slice 2의 로컬 차단·무효 후보, 한도 초과.
판단 불가 (NOT_ASSESSABLE): 결정 시각까지 이용 가능한 Trading State 기록이 없음 (호출자의 NORMAL 입력만으로는 통과시키지 않는다.
HALTED·RESTRICTED 입력은 차단 쪽으로만 쓴다), 승인자 참조가 없는 NORMAL 기록, 주문 기록 완전성 미확인, Slice 1의 NOT_ASSESSABLE.
Trading State 기록은 decision_at까지 이용 가능한 것 가운데 상태 시각이 가장 늦은 기록을 쓴다. 그 기록의 상태 시각(같은 시각 포함)
이후에야 이용 가능해진 다른 기록은 그 결정이 반영할 수 없었으므로, 그쪽이 더 제한적이면 더 제한적인 상태를 적용한다 (해제였다고
확인할 수 없음).
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from carver_quant.lab.accounting.fill_ledger import FillLedger
from carver_quant.lab.accounting.order_projection import CandidateStatus
from carver_quant.lab.accounting.order_snapshot import OrderLogCompleteness, PitRiskReport, assess_pretrade_risk_as_of
from carver_quant.lab.accounting.pretrade_risk import RiskCheckStatus, WorstCasePosition
from carver_quant.lab.accounting.unknown_resolution import EvidenceDisposition, EvidenceSnapshot, orders_from_evidence_as_of
from carver_quant.lab.domain.order_events import OrderEvent
from carver_quant.lab.domain.order_evidence import OrderEvidence
from carver_quant.lab.domain.orders import OrderStatus, OrderStatusSource
from carver_quant.lab.domain.records import PositionBaseline, ValuationPrice
from carver_quant.lab.domain.risk import ContractMultiplier, ExposureLimit, TradingState
from carver_quant.lab.domain.trading_state import TradingStateRecord


class L3GateStatus(Enum):
    BLOCKED = "BLOCKED"  # 자동 주문을 막는 사유가 있음
    NOT_ASSESSABLE = "NOT_ASSESSABLE"  # 필요한 근거가 없거나 믿을 수 없어 판정하지 않음
    NO_BLOCK_FOUND = "NO_BLOCK_FOUND"  # 이 게이트의 검사 범위에서 차단 사유를 찾지 못함. 주문 제출 승인·전송 허가가 아니다


class CandidateRiskEffect(Enum):
    """새 주문 후보가 위험을 늘리기만 하는지 (ADR-0003 §6.2). 최악 경우 포지션 범위 [숏, 롱] 전체로 본다 (§6.3, S-2)."""

    NO_CANDIDATE = "NO_CANDIDATE"  # 후보 0 또는 후보를 만들지 않음
    RISK_INCREASING = "RISK_INCREASING"  # 매수는 모든 최악 경우 포지션이 ≥ 0, 매도는 ≤ 0: 어느 경우에도 0에서 멀어지기만 한다
    CONTAINS_RISK_REDUCTION = "CONTAINS_RISK_REDUCTION"  # 어떤 경우에 0 쪽으로 줄이는 부분(축소, 반전의 청산 다리)이 있음


# 이 게이트가 검사하지 않는 단계와 근거. NO_BLOCK_FOUND여도 남는다.
L3_GATE_NOT_CHECKED = (
    "L1_OTHER_RISK_METRICS",  # leverage·margin·상품 노출 비율·현금·drawdown·데이터 신선도 (ADR-0003 §6.2.2)
    "L2_POLICY_DECISION",  # ALLOW / REDUCE_TO_LIMIT / BLOCK_INCREASE (§6.1, Q3-2)
    "VERIFIED_RISK_REDUCTION",  # S-1·S-3·S-6·S-7·§6.2.2. 그래서 위험 축소를 포함한 후보는 차단한다
    "BROKER_RECONCILIATION",  # 브로커 대조를 하지 않는다 (S-3, R9-8, ADR-0012 §6.3a)
    "TRADING_STATE_RECORD_BASIS",  # 상태 기록의 원인 해소·대조·승인 내용은 호출 경계가 준 참조이며 확인하지 않는다
    "EVIDENCE_AUTHENTICITY",  # 증거의 출처·종류는 신뢰 경계 입력. 브로커 응답의 진위·인증을 확인하지 않는다
    "BROKER_SUBMISSION_STEPS",  # 제출 전 기록(BR-3)과 브로커·거래소 주문 제약 (ADR-0012)
)

_RESTRICTIVENESS = {TradingState.NORMAL: 0, TradingState.RESTRICTED: 1, TradingState.HALTED: 2}


@dataclass(frozen=True)
class L3GateView:
    contract_id: str
    candidate_quantity: int | None
    candidate_effect: CandidateRiskEffect
    status: L3GateStatus
    blocking_reasons: tuple[str, ...]
    unassessable_reasons: tuple[str, ...]


@dataclass(frozen=True)
class L3GateReport:
    """계좌 하나의 decision_at L3 게이트 결과. 판정에 쓴 Trading State 기록과 입력, 적용한 상태(가장 제한적인 쪽), 증거 판정,
    위험 결과를 함께 싣는다. 적용한 상태는 판정에 쓴 값일 뿐 계좌의 상태 전이가 아니다."""

    account_id: str
    decision_at: datetime
    trading_state_input: TradingState
    trading_state_record: TradingStateRecord | None
    trading_state_applied: TradingState
    late_state_record_ids: tuple[str, ...]
    evidence: EvidenceSnapshot
    risk: PitRiskReport
    views: tuple[L3GateView, ...]
    not_checked: tuple[str, ...]

    def view(self, contract_id: str) -> L3GateView:
        for view in self.views:
            if view.contract_id == contract_id:
                return view
        raise ValueError(f"no gate view for contract {contract_id!r}.")


def _current_state_record(
    records: Iterable[TradingStateRecord], account_id: str, decision_at: datetime
) -> tuple[TradingStateRecord | None, TradingState | None, tuple[str, ...]]:
    by_id: dict[str, TradingStateRecord] = {}
    for record in records:
        if not isinstance(record, TradingStateRecord):
            raise ValueError("trading_state_records must contain TradingStateRecord values.")
        if record.account_id != account_id:
            raise ValueError("a trading state record belongs to another account.")
        known = by_id.get(record.record_id)
        if known is None:
            by_id[record.record_id] = record
        elif known != record:
            raise ValueError(f"trading state record {record.record_id!r} was received with different content.")
    usable = sorted((record for record in by_id.values() if record.data_available_at <= decision_at), key=lambda r: r.effective_at)
    for previous, record in zip(usable, usable[1:]):
        same_time = record.effective_at == previous.effective_at
        if same_time and (record.state, record.cause_code, record.approver_ref) != (previous.state, previous.cause_code, previous.approver_ref):
            raise ValueError("two different trading state records take effect at the same time; the state is ambiguous.")
    late = tuple(sorted(record.record_id for record in by_id.values() if record.data_available_at > decision_at))
    if not usable:
        return None, None, late
    current = usable[-1]
    # 그 기록의 상태가 정해진 시각(같은 시각 포함) 이후에야 이용 가능해진 기록은 그 결정이 반영할 수 없었다. 더 제한적이면 그 상태를 쓴다.
    known_later = [record.state for record in usable if record is not current and record.data_available_at >= current.effective_at]
    return current, max([current.state, *known_later], key=_RESTRICTIVENESS.__getitem__), late


def _candidate_effect(worst: WorstCasePosition) -> CandidateRiskEffect:
    candidate = worst.candidate_quantity
    if not candidate:
        return CandidateRiskEffect.NO_CANDIDATE
    if candidate > 0:
        increasing = worst.worst_short_before >= 0
    else:
        increasing = worst.worst_long_before <= 0
    return CandidateRiskEffect.RISK_INCREASING if increasing else CandidateRiskEffect.CONTAINS_RISK_REDUCTION


def _last_unknown_resolution(events: tuple[OrderEvent, ...], decision_at: datetime) -> datetime | None:
    """decision_at까지 이용 가능했던 기록에서 UNKNOWN이 다른 상태로 바뀐 마지막 이용 가능 시각."""
    by_order: dict[str, list[OrderEvent]] = {}
    for event in events:
        if event.available_at <= decision_at:
            by_order.setdefault(event.record.client_order_id, []).append(event)
    latest = None
    for versions in by_order.values():
        unknown = False
        for event in sorted(versions, key=lambda version: version.available_at):
            if event.record.status is OrderStatus.UNKNOWN:
                unknown = True
            elif unknown:
                unknown = False
                latest = event.available_at if latest is None else max(latest, event.available_at)
    return latest


def assess_l3_gate(
    *,
    evidence: EvidenceSnapshot,
    risk: PitRiskReport,
    trading_state_records: Iterable[TradingStateRecord],
) -> L3GateReport:
    """증거 Snapshot으로 계산한 위험 결과에 L3 안전 판정을 붙인다. 위험 결과의 구조와 값은 바꾸지 않는다.

    입력: 증거 판정과 Snapshot(`orders_from_evidence_as_of`), 그 Snapshot의 주문으로 낸 위험 결과(`assess_pretrade_risk_as_of`),
    계좌의 Trading State 기록 (늦은 기록 포함 가능). 기록은 decision_at까지 이용 가능한 것 가운데 상태 시각이 가장 늦은 것을 쓴다.
    출력: 월물별 판정과 사유, 쓴 기록, 늦은 기록 ID, 검사하지 않은 단계. 규칙: 모듈 설명.
    예외조건 (ValueError): 위험 결과가 이 증거 Snapshot으로 계산되지 않음, 다른 계좌나 같은 ID의 다른 내용, 같은 상태 시각의 서로 다른 기록.
    """
    if not isinstance(evidence, EvidenceSnapshot):
        raise ValueError("evidence must be an EvidenceSnapshot.")
    if not isinstance(risk, PitRiskReport):
        raise ValueError("risk must be a PitRiskReport.")
    if risk.snapshot != evidence.snapshot or risk.risk.account_id != evidence.account_id:
        raise ValueError("the risk report must be computed from this evidence snapshot.")
    snapshot = evidence.snapshot
    decision_at = snapshot.decision_at
    record, recorded_state, late = _current_state_record(trading_state_records, evidence.account_id, decision_at)

    claimed = (risk.risk.trading_state,) if record is None else (risk.risk.trading_state, recorded_state)
    state = max(claimed, key=_RESTRICTIVENESS.__getitem__)
    blocking = []
    unassessable = []
    if state is TradingState.HALTED:
        blocking.append("TRADING_STATE_HALTED")
    if any(entry.record.status is OrderStatus.UNKNOWN for entry in snapshot.entries):
        blocking.append("UNKNOWN_ORDER_PRESENT")
    if any(assessment.disposition is EvidenceDisposition.REJECTED for assessment in evidence.usable_assessments()):
        blocking.append("ORDER_EVIDENCE_CONFLICT")
    if record is None:
        unassessable.append("TRADING_STATE_RECORD_MISSING")
    else:
        resolved_at = _last_unknown_resolution(evidence.events, decision_at)
        if record.state is not TradingState.HALTED and resolved_at is not None and record.effective_at <= resolved_at:
            blocking.append("UNKNOWN_RESOLVED_AFTER_TRADING_STATE_RECORD")
        if record.state is TradingState.NORMAL and record.approver_ref is None:
            unassessable.append("TRADING_STATE_APPROVAL_NOT_RECORDED")
    if snapshot.completeness is not OrderLogCompleteness.VERIFIED_COMPLETE:
        unassessable.append("ORDER_LOG_NOT_VERIFIED_COMPLETE")

    views = []
    for view in risk.risk.views:
        view_blocking = list(blocking)
        view_unassessable = list(unassessable)
        worst = view.worst_case
        effect = _candidate_effect(worst)
        if worst.candidate_quantity is None:
            view_blocking.extend(view.local_reasons or (view.local_status.name,))
        elif worst.candidate_quantity != 0:
            if view.local_status is not CandidateStatus.LOCAL_VALID:
                view_blocking.extend(view.local_reasons or (view.local_status.name,))
            if view.risk_status is RiskCheckStatus.LIMIT_EXCEEDED:
                view_blocking.append("LIMIT_EXCEEDED")
            elif view.risk_status is RiskCheckStatus.NOT_ASSESSABLE:
                view_unassessable.extend(view.risk_reasons)
            if effect is CandidateRiskEffect.CONTAINS_RISK_REDUCTION:
                view_blocking.append("RISK_REDUCTION_NOT_VERIFIED")
            elif state is TradingState.RESTRICTED:
                view_blocking.append("TRADING_STATE_RESTRICTED")
        view_blocking = tuple(dict.fromkeys(view_blocking))
        view_unassessable = tuple(dict.fromkeys(view_unassessable))
        if view_blocking:
            status = L3GateStatus.BLOCKED
        elif view_unassessable:
            status = L3GateStatus.NOT_ASSESSABLE
        else:
            status = L3GateStatus.NO_BLOCK_FOUND
        views.append(
            L3GateView(
                contract_id=view.contract_id,
                candidate_quantity=worst.candidate_quantity,
                candidate_effect=effect,
                status=status,
                blocking_reasons=view_blocking,
                unassessable_reasons=view_unassessable,
            )
        )

    unverified = tuple(item for item in risk.pit_unverified if record is None or item != "TRADING_STATE_TIME")
    return L3GateReport(
        account_id=evidence.account_id,
        decision_at=decision_at,
        trading_state_input=risk.risk.trading_state,
        trading_state_record=record,
        trading_state_applied=state,
        late_state_record_ids=late,
        evidence=evidence,
        risk=risk,
        views=tuple(views),
        not_checked=L3_GATE_NOT_CHECKED + unverified,
    )


def assess_l3_gate_as_of(
    *,
    baseline: PositionBaseline,
    ledger: FillLedger,
    evidence: Iterable[OrderEvidence],
    confirming_source: OrderStatusSource,
    completeness: OrderLogCompleteness,
    completeness_ref: str | None = None,
    targets: Mapping[str, int],
    decision_at: datetime,
    trading_state: TradingState,
    trading_state_records: Iterable[TradingStateRecord],
    reference_prices: Mapping[str, ValuationPrice],
    multipliers: Mapping[str, ContractMultiplier],
    limits: Mapping[str, ExposureLimit],
) -> L3GateReport:
    """증거 판정(`orders_from_evidence_as_of`) → 위험 결과(`assess_pretrade_risk_as_of`, Slice 2) → L3 판정(`assess_l3_gate`).

    위험 계산은 다시 쓰지 않고 Slice 1·2 함수를 그대로 부른다. `trading_state`는 Slice 1과 같은 호출자 입력이며 차단 쪽으로만 쓴다.
    예외조건: 세 함수의 예외조건. 장부가 FillLedger가 아니면 ValueError.
    """
    if not isinstance(ledger, FillLedger):
        raise ValueError("ledger must be a FillLedger.")
    checked = orders_from_evidence_as_of(
        evidence,
        decision_at,
        account_id=ledger.account_id,
        confirming_source=confirming_source,
        completeness=completeness,
        completeness_ref=completeness_ref,
    )
    risk = assess_pretrade_risk_as_of(
        baseline=baseline,
        ledger=ledger,
        events=checked.events,
        completeness=completeness,
        completeness_ref=completeness_ref,
        targets=targets,
        decision_at=decision_at,
        trading_state=trading_state,
        reference_prices=reference_prices,
        multipliers=multipliers,
        limits=limits,
    )
    return assess_l3_gate(evidence=checked, risk=risk, trading_state_records=trading_state_records)
