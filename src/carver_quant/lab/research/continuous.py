"""P1-02 연구용 연속 선물: 롤 기준 가격 결정과 가산(Panama) back-adjustment (ADR-0004 §6.4, P0-03A TC-C6·TC-C7, P1-02 명세 §4·§5).

Research 계층의 순수 함수다. `lab.domain`만 import한다 (ADR-0010 PK-2·PK-3). 월물별 입력(P1-01 PIT 조회 결과와 As-of Series)은 호출부가
만들어 넘긴다. 이 모듈은 공급자 형식과 P1-01 구현을 모른다.

계산 (알고리즘 `ALGORITHM_VERSION`, 단위 index point, 정확한 Decimal):
- 롤 gap = 구월물 기준가 − 신월물 기준가. 기준가는 기준 거래일의 최종 정산가이며 롤의 known_at(`evidence_cutoff_at`)에 계획의 근거로 보인
  값이다. 둘 중 하나라도 보이지 않으면 gap을 추정하지 않는다 (`UnresolvedRoll`). known_at 뒤의 정정은 gap에 반영하지 않는다.
- 시계열은 `as_of`에 알려진 롤(known_at ≤ as_of)만 적용한다. 선택 월물: 처음 월물에서 시작해, 적용한 롤의 신월물 첫 거래일부터 그 신월물.
  아직 알려지지 않은 첫 롤의 신월물 첫 거래일부터는 어느 월물도 선택하지 않고, 그날 이후 보인 구월물 기록은 ROLL_NOT_YET_KNOWN으로 제외에 남긴다.
- 선택 월물의 P1-01 점(최종 정산가)만 쓴다. P1-01이 제외한 거래일은 제외로 남기고 다른 월물로 대신하지 않는다. 구월물 구간에서 롤 기준일 뒤·
  신월물 첫 거래일 전의 점은 gap의 기준과 달라 연속성을 깨므로 제외한다 (AFTER_ROLL_REFERENCE_DATE).
- 누적 조정(d) = 신월물 첫 거래일 > d 인 적용 롤 gap의 합. 조정 가격 = raw − 누적 조정. 일별 변화 = 조정 가격 − 같은 시계열 앞 점의 조정 가격.
  롤 경계의 변화는 신월물 자신의 기준일 → 첫 거래일 변화와 같다. 백분율 수익률은 계산하지 않는다.
"""

from collections.abc import Mapping
from datetime import datetime, timezone

from carver_quant.lab.domain.continuous import (
    AdjustedPricePoint,
    AdjustedPriceSeries,
    AdjustmentMethod,
    ContinuousExclusion,
    ContinuousSeriesBasis,
    FuturesRollEvent,
    RollPlan,
    RollPlanEntry,
    UnresolvedRoll,
    cumulative_adjustment,
)
from carver_quant.lab.domain.market_data import PitStatus, ResearchSettlementSeries, SeriesBasis, SettlementAsOf
from carver_quant.lab.domain.values import EXACT_DECIMAL_CONTEXT

ALGORITHM_VERSION = "p1-02-additive-back-adjustment/1"

AFTER_ROLL_REFERENCE_DATE = "AFTER_ROLL_REFERENCE_DATE"
ROLL_NOT_YET_KNOWN = "ROLL_NOT_YET_KNOWN"


def _require_plan(plan: object) -> RollPlan:
    if type(plan) is not RollPlan:
        raise ValueError("plan must be a RollPlan.")

    return plan


def _require_aware(value: object, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be a timezone-aware datetime.")

    return value.astimezone(timezone.utc)


def _inside(day, begin, end) -> bool:
    """거래일이 [begin, end) 구간 안인가 (None은 열린 끝)."""
    return (begin is None or day >= begin) and (end is None or day < end)


def _outcome_entry(plan: RollPlan, outcome: object) -> RollPlanEntry:
    if type(outcome) is UnresolvedRoll:
        return outcome.entry
    if type(outcome) is not FuturesRollEvent:
        raise ValueError("roll outcomes must be FuturesRollEvent or UnresolvedRoll values.")
    if outcome.research_instrument_id != plan.research_instrument_id or outcome.accepted_evidence is not plan.accepted_evidence:
        raise ValueError("a roll event must belong to the plan's research instrument and accepted evidence.")
    return RollPlanEntry(
        from_contract_id=outcome.from_contract_id,
        to_contract_id=outcome.to_contract_id,
        roll_reference_date=outcome.roll_reference_date,
        new_contract_first_date=outcome.new_contract_first_date,
        selection_policy_id=outcome.selection_policy_id,
        evidence_cutoff_at=outcome.evidence_cutoff_at,
    )


def require_roll_outcomes(plan: RollPlan, roll_outcomes: object) -> tuple:
    """계획 항목마다 하나씩, 계획 순서대로인 롤 결정 결과인지 확인한다. 아니면 ValueError."""
    outcomes = tuple(roll_outcomes) if isinstance(roll_outcomes, (tuple, list)) else None
    if outcomes is None or len(outcomes) != len(plan.entries):
        raise ValueError("roll outcomes must give one result per plan entry.")
    if any(_outcome_entry(plan, outcome) != entry for outcome, entry in zip(outcomes, plan.entries)):
        raise ValueError("roll outcomes must follow the plan entries in order.")
    return outcomes


def resolve_roll_event(plan: RollPlan, entry: RollPlanEntry, *, old_answer: SettlementAsOf, new_answer: SettlementAsOf):
    """롤 하나의 기준 가격과 gap을 정한다 (TC-C7).

    입력: 롤 계획, 그 계획의 롤 항목, 구월물·신월물의 기준 거래일 최종 정산가 PIT 조회 결과 (P1-01 `get_final_settlement_asof`, cutoff =
    항목의 `evidence_cutoff_at`, 근거 = 계획의 `accepted_evidence`).
    출력: 두 조회가 모두 AVAILABLE이면 `FuturesRollEvent` (gap = 구 − 신, index point), 아니면 `UnresolvedRoll` (사유: 어느 쪽이 왜 없는지).
    예외: 계획에 없는 항목, 월물·거래일·cutoff·근거가 항목과 맞지 않는 조회 결과 → ValueError.
    """
    plan = _require_plan(plan)
    if type(entry) is not RollPlanEntry or entry not in plan.entries:
        raise ValueError("entry must be one of the plan's roll entries.")
    for contract_id, answer in ((entry.from_contract_id, old_answer), (entry.to_contract_id, new_answer)):
        if (
            type(answer) is not SettlementAsOf
            or answer.contract_id != contract_id
            or answer.trading_date != entry.roll_reference_date
            or answer.cutoff_at != entry.evidence_cutoff_at
            or answer.accepted_evidence is not plan.accepted_evidence
        ):
            raise ValueError("reference answers must be PIT queries of the roll's contracts on its reference date at its evidence cutoff.")
    reasons = []
    for label, answer in (("OLD", old_answer), ("NEW", new_answer)):
        if answer.status is not PitStatus.AVAILABLE:
            reasons.append(f"{label}_REFERENCE_{answer.status.value}")
            reasons.extend(f"{label}_{reason}" for reason in answer.reasons)
    if reasons:
        return UnresolvedRoll(entry=entry, reasons=tuple(reasons))
    return FuturesRollEvent(
        research_instrument_id=plan.research_instrument_id,
        from_contract_id=entry.from_contract_id,
        to_contract_id=entry.to_contract_id,
        roll_reference_date=entry.roll_reference_date,
        new_contract_first_date=entry.new_contract_first_date,
        selection_policy_id=entry.selection_policy_id,
        evidence_cutoff_at=entry.evidence_cutoff_at,
        accepted_evidence=plan.accepted_evidence,
        old_reference_price=old_answer.price,
        new_reference_price=new_answer.price,
        roll_gap_points=EXACT_DECIMAL_CONTEXT.subtract(old_answer.price, new_answer.price),
        reference_prices_available_at=max(old_answer.available_at, new_answer.available_at),
        old_source_record_id=old_answer.event.source_record_id,
        old_source_snapshot_id=old_answer.event.source_snapshot_id,
        new_source_record_id=new_answer.event.source_record_id,
        new_source_snapshot_id=new_answer.event.source_snapshot_id,
    )


def build_adjusted_series(
    plan: RollPlan, roll_outcomes, contract_series: Mapping[str, ResearchSettlementSeries], *, as_of: datetime, basis: ContinuousSeriesBasis
) -> AdjustedPriceSeries:
    """가산 back-adjustment로 연구용 연속 시계열을 만든다 (TC-C6, PIT 구성).

    입력: 롤 계획, 계획 항목마다 롤 결정 결과(계획 순서), 계획의 월물마다 P1-01 As-of Series (cutoff = `as_of`, 근거 = 계획의 근거), 시간대가
    있는 `as_of`(UTC로 바꾼다), `basis` (FULL_SAMPLE은 자료 끝 시각을 `as_of`로 둔 사후 연구용이며 계획의 모든 롤이 알려져 있어야 한다).
    출력: `AdjustedPriceSeries` (단위 index point). known_at ≤ `as_of`인 롤만 적용한다.
    기준일 R과 신월물 첫 거래일 N 사이(R < d < N)의 거래일: 롤이 아직 알려지지 않은 `as_of`에서는 구월물 점을 조정 없이 선택하고(N부터 보인
    구월물 기록은 ROLL_NOT_YET_KNOWN 제외), 롤이 알려진 `as_of`에서는 그 구월물 점을 AFTER_ROLL_REFERENCE_DATE로 제외하며 신월물로 대신하지
    않는다. 뒤 `as_of`의 시계열이 과거를 다시 쓸 뿐, 앞 `as_of`의 결과는 바뀌지 않는다.
    예외: 입력이 계획과 맞지 않음, `as_of`에 알려진 롤의 기준 가격이 정해지지 않음, FULL_SAMPLE인데 아직 알려지지 않은 롤이 있음 → ValueError.
    """
    plan = _require_plan(plan)
    as_of = _require_aware(as_of, "as_of")
    if not isinstance(basis, ContinuousSeriesBasis):
        raise ValueError("basis must be a ContinuousSeriesBasis.")
    outcomes = require_roll_outcomes(plan, roll_outcomes)
    if not isinstance(contract_series, Mapping) or set(contract_series) != set(plan.contracts):
        raise ValueError("contract_series must give one settlement series per plan contract.")
    for contract_id, series in contract_series.items():
        if (
            type(series) is not ResearchSettlementSeries
            or series.contract_id != contract_id
            or series.basis is not SeriesBasis.AS_OF_CUTOFF
            or series.cutoff_at != as_of
            or series.accepted_evidence is not plan.accepted_evidence
        ):
            raise ValueError("each contract series must be that contract's as-of settlement series at as_of on the plan's evidence.")

    applied = []
    for entry, outcome in zip(plan.entries, outcomes):
        if entry.evidence_cutoff_at > as_of:
            break
        if type(outcome) is UnresolvedRoll:
            raise ValueError(f"roll {entry.from_contract_id} -> {entry.to_contract_id} is known by as_of but has no reference prices: "
                             + ", ".join(outcome.reasons))
        applied.append(outcome)
    if basis is ContinuousSeriesBasis.FULL_SAMPLE and len(applied) != len(plan.entries):
        raise ValueError("a full-sample series applies every planned roll; some rolls are not known by as_of.")

    # 구간: (월물, 시작 거래일(포함), 끝 거래일(제외), 다음 적용 롤의 기준일)
    segments, contract, start = [], plan.initial_contract_id, None
    for roll in applied:
        segments.append((contract, start, roll.new_contract_first_date, roll.roll_reference_date))
        contract, start = roll.to_contract_id, roll.new_contract_first_date
    pending = plan.entries[len(applied)] if len(applied) < len(plan.entries) else None
    segments.append((contract, start, None if pending is None else pending.new_contract_first_date, None))

    selected, excluded = [], []
    for contract, begin, end, next_reference in segments:
        series = contract_series[contract]
        for point in series.points:
            if not _inside(point.trading_date, begin, end):
                continue
            if next_reference is not None and point.trading_date > next_reference:
                excluded.append(ContinuousExclusion(trading_date=point.trading_date, selected_contract_id=contract,
                                                    reasons=(AFTER_ROLL_REFERENCE_DATE,)))
            else:
                selected.append((contract, point))
        for item in series.excluded:
            if _inside(item.trading_date, begin, end):
                excluded.append(ContinuousExclusion(trading_date=item.trading_date, selected_contract_id=contract,
                                                    reasons=(item.status.value, *item.reasons)))
    if pending is not None:
        # 아직 알려지지 않은 롤의 신월물 첫 거래일부터는 어느 월물도 선택하지 않는다. 그날 이후 보인 구월물 기록은 이유와 함께 남긴다.
        last_contract = segments[-1][0]
        series = contract_series[last_contract]
        for point in series.points:
            if point.trading_date >= pending.new_contract_first_date:
                excluded.append(ContinuousExclusion(trading_date=point.trading_date, selected_contract_id=last_contract,
                                                    reasons=(ROLL_NOT_YET_KNOWN,)))
        for item in series.excluded:
            if item.trading_date >= pending.new_contract_first_date:
                excluded.append(ContinuousExclusion(trading_date=item.trading_date, selected_contract_id=last_contract,
                                                    reasons=(ROLL_NOT_YET_KNOWN, item.status.value, *item.reasons)))

    points = []
    for contract, item in sorted(selected, key=lambda pair: pair[1].trading_date):
        previous = points[-1] if points else None
        cumulative = cumulative_adjustment(applied, item.trading_date)
        adjusted = EXACT_DECIMAL_CONTEXT.subtract(item.price, cumulative)
        points.append(
            AdjustedPricePoint(
                trading_date=item.trading_date,
                selected_contract_id=contract,
                raw_price=item.price,
                cumulative_adjustment_points=cumulative,
                adjusted_price=adjusted,
                daily_price_change_points=None if previous is None else EXACT_DECIMAL_CONTEXT.subtract(adjusted, previous.adjusted_price),
                change_from_trading_date=None if previous is None else previous.trading_date,
                source_record_id=item.source_record_id,
                source_snapshot_id=item.source_snapshot_id,
                available_at=item.available_at,
                availability_evidence=item.evidence_used,
            )
        )
    return AdjustedPriceSeries(
        research_instrument_id=plan.research_instrument_id,
        method=AdjustmentMethod.FUTURES_ADDITIVE_BACK_ADJUSTED,
        algorithm_version=ALGORITHM_VERSION,
        basis=basis,
        as_of=as_of,
        accepted_evidence=plan.accepted_evidence,
        roll_plan_id=plan.plan_id,
        initial_contract_id=plan.initial_contract_id,
        applied_rolls=tuple(applied),
        points=tuple(points),
        excluded=tuple(sorted(excluded, key=lambda item: item.trading_date)),
    )
