"""P1-01 정산가 PIT 조회와 연구용 Series (FR-04, FR-05, FR-08. ADR-0004 원칙 5·§6.5, ADR-0007 X7-1~X7-4, D3A-50).

순수 함수다. 공급자 형식을 모르며 `lab.domain`만 import한다.

선택 정책 (`SELECTION_POLICY`):
- 대상: 같은 월물·거래일의 일별 정산 기록 가운데 실제 정산가와 철회 기록. 장중 정산가와 이론가는 최종가로 쓰지 않는다.
- 보임: 받아들인 근거(`accepted_evidence`)와 그보다 강한 근거의 시각 가운데 가장 이른 시각이 cutoff 이하인 기록이 cutoff에 보인다.
  받아들인 근거 수준의 시각이 없고 더 강한 근거의 시각이 cutoff 뒤인 기록은 cutoff 전에 보였는지 알 수 없다 (근거 없음). 다만 더 약한
  근거의 시각이 cutoff 뒤이면 그보다 늦은 강한 근거도 cutoff 뒤이므로 (거래소 표시 → 공급자 수집 → 수신 순서, 시계 차이는 보지 않음)
  아직 보이지 않은 기록이다. 정산 기록은 그 거래일의 UTC 자정 전에 나오지 않으므로 (품질 검사 TIMESTAMP_TIMEZONE), 거래일 UTC 자정이
  cutoff 뒤인 근거 없는 기록도 보지 않는다.
- 순서: 보인 기록을 공급원 순서로 놓는다. cutoff까지 알려진 시각만 쓴다: 모든 보인 기록의 공급자 수집 시각이 있고 cutoff 이하이면 그
  시각, 아니면 거래소 시각이 그렇다면 그 시각이다 (cutoff 뒤의 시각으로 순서를 정하면 미래 정보가 들어온다). 두 시각을 모두 쓸 수
  있는데 내용이 다른 두 기록의 순서가 서로 반대이면 AMBIGUOUS다. 공급자 sequence 번호로 순서를 정하지 않는다. 순서를 정할 수 없는데
  내용(상태·가격)이 다르거나, 마지막 순서 위치에 내용이 다른 기록이 있으면 AMBIGUOUS다.
- 결과: 마지막 기록이 FINAL이면 그 가격이다 (같은 거래일에 보인 최종가 가운데 다른 가격이 있으면 CORRECTION). PRELIMINARY이면 최종가가
  없고 (보인 최종가가 있으면 AMBIGUOUS), WITHDRAWN이면 최종가가 없다. 근거 없는 기록이 있으면 답이 바뀔 수 있으므로
  EVIDENCE_INSUFFICIENT다. 보인 기록이 없으면 NOT_AVAILABLE이며, 아직 보이지 않은 기록이 있다는 사실을 사유로 드러내지 않는다.
- Snapshot의 최신 최종가 Series는 모든 기록을 보인 것으로 놓고 같은 규칙을 쓴다. 이용 가능 시각을 보지 않으므로 PIT가 아니다.
- 결측 거래일을 채우지 않는다. 가격을 바꾸거나 반올림하지 않는다.
"""

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timezone

from carver_quant.lab.domain.market_data import (
    AvailabilityEvidence,
    PitStatus,
    ResearchSettlementPoint,
    ResearchSettlementSeries,
    RevisionRole,
    SeriesBasis,
    SeriesExclusion,
    SettlementAsOf,
    SettlementEvent,
    SettlementPriceType,
    SettlementRevisionStatus,
    earliest_accepted_evidence,
    evidence_at_least,
    evidence_timestamps,
    require_date,
)
from carver_quant.lab.domain.values import require_identifier

SELECTION_POLICY = "p1-01-final-settlement-selection/1"

# 공급원 순서에 쓰는 시각. 앞의 것을 먼저 쓴다.
_ORDER_FIELDS = ("vendor_received_at", "published_at")


@dataclass(frozen=True)
class _Seen:
    event: SettlementEvent
    available_at: datetime | None  # 최신 최종가 Series에서는 None (이용 가능 시각을 보지 않음)
    evidence: AvailabilityEvidence | None


@dataclass(frozen=True)
class _Decision:
    status: PitStatus
    reasons: tuple[str, ...]
    chosen: _Seen | None = None
    role: RevisionRole | None = None


def is_daily_settlement_record(event: SettlementEvent) -> bool:
    """최종가 선택의 대상인가: 일별 정산 기록 가운데 실제 정산가이거나 철회 기록이다. 철회는 이론가 표시와 관계없이 대상이다."""
    return event.price_type is SettlementPriceType.DAILY and (event.actual or event.revision_status is SettlementRevisionStatus.WITHDRAWN)


def _order_fields(events, known_by: datetime | None) -> list[str]:
    return [
        name
        for name in _ORDER_FIELDS
        if all(getattr(item, name) is not None and (known_by is None or getattr(item, name) <= known_by) for item in events)
    ]


def source_order_key(events, *, known_by: datetime | None) -> Callable[[SettlementEvent], datetime] | None:
    """같은 거래일 기록들의 공급원 순서 키. `known_by`(cutoff, 없으면 None)까지 알려진 시각만 쓴다: 모든 기록의 공급자 수집 시각이
    있고 `known_by` 이하이면 그 시각, 아니면 거래소 시각이 그렇다면 그 시각이다. 둘 다 아니면 순서를 정할 수 없어 None이다."""
    names = _order_fields(events, known_by)
    if not names:
        return None
    name = names[0]
    return lambda item: getattr(item, name)


def source_order_inverted(events, *, known_by: datetime | None) -> bool:
    """두 순서 시각을 모두 쓸 수 있을 때, 내용(상태·가격)이 다른 두 기록의 공급자 수집 순서와 거래소 순서가 서로 반대인가."""
    if len(_order_fields(events, known_by)) < len(_ORDER_FIELDS):
        return False
    return any(
        first.vendor_received_at < second.vendor_received_at and first.published_at > second.published_at
        for first in events
        for second in events
        if _content(first) != _content(second)
    )


def utc_midnight(day: date) -> datetime:
    """거래일 라벨과 같은 날짜의 UTC 자정. 거래일을 만드는 데 쓰지 않고, 정산 기록 시각의 하한 검사에만 쓴다."""
    return datetime(day.year, day.month, day.day, tzinfo=timezone.utc)


def _content(event: SettlementEvent) -> tuple:
    return event.revision_status, event.price


def _require_events(events: object) -> tuple[SettlementEvent, ...]:
    if not isinstance(events, (tuple, list)) or any(type(item) is not SettlementEvent for item in events):
        raise ValueError("events must be a tuple or list of SettlementEvent values.")

    return tuple(events)


def _require_cutoff(value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("cutoff_at must be a timezone-aware datetime.")

    return value.astimezone(timezone.utc)


def _require_accepted(value: object) -> AvailabilityEvidence:
    if not isinstance(value, AvailabilityEvidence):
        raise ValueError("accepted_evidence must be an AvailabilityEvidence.")

    return value


def _visibility(event: SettlementEvent, cutoff: datetime, accepted: AvailabilityEvidence) -> tuple[_Seen | None, bool]:
    """(cutoff에 보이면 그 기록, 보이지 않는데 cutoff 전에 보였는지 알 수 없으면 True)."""
    # 시스템 수신 시각은 항상 있으므로 받아들인 근거 이상의 시각이 하나는 있다.
    moment, level = earliest_accepted_evidence(event, accepted)
    if moment <= cutoff:
        return _Seen(event, moment, level), False
    times = evidence_timestamps(event)
    if dict(times)[accepted] is not None:
        return None, False
    # 더 약한 근거의 시각이 cutoff 뒤이면 그 뒤에 오는 강한 근거도 cutoff 뒤다: 아직 보이지 않은 기록이다.
    weaker_after_cutoff = any(
        weak_time is not None and weak_time > cutoff for weak_level, weak_time in times if not evidence_at_least(weak_level, accepted)
    )
    return None, not weaker_after_cutoff


def _decide(seen: list[_Seen], *, undated: bool, excluded_seen: bool, known_by: datetime | None) -> _Decision:
    if not seen:
        if undated:
            return _Decision(PitStatus.EVIDENCE_INSUFFICIENT, ("MISSING_EVIDENCE_TIME",))
        if excluded_seen:
            return _Decision(PitStatus.NOT_AVAILABLE, ("ONLY_INTRADAY_OR_THEORETICAL",))
        return _Decision(PitStatus.NOT_AVAILABLE, ("NO_VISIBLE_RECORD",))

    events = [item.event for item in seen]
    if source_order_inverted(events, known_by=known_by):
        return _Decision(PitStatus.AMBIGUOUS, ("SOURCE_ORDER_INVERSION",))
    key = source_order_key(events, known_by=known_by)
    if key is None:
        if len({_content(item.event) for item in seen}) > 1:
            return _Decision(PitStatus.AMBIGUOUS, ("UNORDERED_RECORDS",))
        last = seen
    else:
        latest = max(key(item.event) for item in seen)
        last = [item for item in seen if key(item.event) == latest]
    if len({_content(item.event) for item in last}) > 1:
        all_final = all(item.event.revision_status is SettlementRevisionStatus.FINAL for item in last)
        return _Decision(PitStatus.AMBIGUOUS, ("CONFLICTING_FINALS_AT_SAME_TIME" if all_final else "CONFLICTING_RECORDS_AT_SAME_TIME",))
    if undated:
        return _Decision(PitStatus.EVIDENCE_INSUFFICIENT, ("MISSING_EVIDENCE_TIME",))

    # 같은 내용의 기록(중복 수신)은 가장 먼저 보인 것을 쓴다.
    chosen = min(
        last,
        key=lambda item: (item.available_at or item.event.ingested_at, item.event.source_snapshot_id, item.event.source_record_id),
    )
    status = chosen.event.revision_status
    if status is SettlementRevisionStatus.WITHDRAWN:
        return _Decision(PitStatus.NOT_AVAILABLE, ("SETTLEMENT_WITHDRAWN",))
    finals = [item.event for item in seen if item.event.revision_status is SettlementRevisionStatus.FINAL]
    if status is SettlementRevisionStatus.PRELIMINARY:
        if finals:
            return _Decision(PitStatus.AMBIGUOUS, ("PRELIMINARY_AFTER_FINAL",))
        return _Decision(PitStatus.NOT_AVAILABLE, ("PRELIMINARY_ONLY",))
    corrected = any(item.price != chosen.event.price for item in finals)
    return _Decision(PitStatus.AVAILABLE, (), chosen, RevisionRole.CORRECTION if corrected else RevisionRole.ORIGINAL_FINAL)


def _decide_as_of(records: list[SettlementEvent], cutoff: datetime, accepted: AvailabilityEvidence) -> tuple[_Decision, bool]:
    """한 거래일 기록들의 cutoff 시점 판정과, 그 거래일이 cutoff에 알려졌는지(보인 기록 또는 근거 없는 기록이 있는지)."""
    seen, undated, excluded_seen = [], False, False
    for event in records:
        item, missing = _visibility(event, cutoff, accepted)
        if not is_daily_settlement_record(event):
            excluded_seen = excluded_seen or item is not None
        elif item is not None:
            seen.append(item)
        elif missing and utc_midnight(event.trading_date) <= cutoff:
            undated = True
    decision = _decide(seen, undated=undated, excluded_seen=excluded_seen, known_by=cutoff)
    return decision, bool(seen) or undated or excluded_seen


def _by_trading_date(events: tuple[SettlementEvent, ...], contract_id: str) -> list[tuple[date, list[SettlementEvent]]]:
    groups = defaultdict(list)
    for event in events:
        if event.contract_id == contract_id:
            groups[event.trading_date].append(event)
    return sorted(groups.items())


def _append(day: date, decision: _Decision, points: list, excluded: list) -> None:
    if decision.status is not PitStatus.AVAILABLE:
        excluded.append(SeriesExclusion(trading_date=day, status=decision.status, reasons=decision.reasons))
        return
    chosen = decision.chosen
    points.append(
        ResearchSettlementPoint(
            trading_date=day,
            price=chosen.event.price,
            revision_role=decision.role,
            source_record_id=chosen.event.source_record_id,
            source_snapshot_id=chosen.event.source_snapshot_id,
            available_at=chosen.available_at,
            evidence_used=chosen.evidence,
        )
    )


def get_final_settlement_asof(
    events, contract_id: str, trading_date: date, cutoff_at: datetime, *, accepted_evidence: AvailabilityEvidence
) -> SettlementAsOf:
    """월물 하나·거래일 하나의 최종 정산가를 cutoff 시점에 알 수 있었던 대로 돌려준다 (FR-05).

    입력: 정산가 사건들, 월물 ID, 거래일 라벨(`date`), cutoff(시간대가 있는 시각, UTC로 바꾼다), 받아들일 가장 약한 근거(기본값 없음,
    ADR-0004 Q4-3·D3A-13은 미결정). 출력: `SettlementAsOf`. 받아들인 근거로 cutoff까지 보인 최종가만 AVAILABLE이며 그 가격(가격 단위는
    메타데이터), 정정 여부, 이용 가능 시각, 쓴 근거를 준다. 다른 상태는 가격 없이 사유를 준다 (fail closed).
    예외: 시간대 없는 cutoff, 잘못된 타입 → ValueError.
    """
    events = _require_events(events)
    contract_id = require_identifier(contract_id, "contract_id")
    trading_date = require_date(trading_date, "trading_date")
    cutoff = _require_cutoff(cutoff_at)
    accepted = _require_accepted(accepted_evidence)
    records = [item for item in events if item.contract_id == contract_id and item.trading_date == trading_date]
    decision, _ = _decide_as_of(records, cutoff, accepted)
    chosen = decision.chosen
    return SettlementAsOf(
        contract_id=contract_id,
        trading_date=trading_date,
        cutoff_at=cutoff,
        accepted_evidence=accepted,
        status=decision.status,
        reasons=decision.reasons,
        event=None if chosen is None else chosen.event,
        revision_role=decision.role,
        available_at=None if chosen is None else chosen.available_at,
        evidence_used=None if chosen is None else chosen.evidence,
    )


def latest_final_series(events, contract_id: str) -> ResearchSettlementSeries:
    """Snapshot에 있는 기록으로 거래일마다 마지막 최종가를 고른 Series (`LATEST_FINAL_IN_SNAPSHOT`).

    PIT가 아니다: 이용 가능 시각을 보지 않으므로 과거 시점에 알려진 값으로 쓰면 안 된다 (그때는 `asof_final_series`).
    입력: 정산가 사건들, 월물 ID. 출력: 거래일 순 점(원본 레코드·Snapshot 참조, 정정 여부)과 제외(최종가를 고를 수 없는 거래일과 사유).
    예외: 잘못된 타입 → ValueError.
    """
    events = _require_events(events)
    contract_id = require_identifier(contract_id, "contract_id")
    points, excluded = [], []
    for day, records in _by_trading_date(events, contract_id):
        relevant = [item for item in records if is_daily_settlement_record(item)]
        seen = [_Seen(item, None, None) for item in relevant]
        _append(day, _decide(seen, undated=False, excluded_seen=len(relevant) < len(records), known_by=None), points, excluded)
    return ResearchSettlementSeries(
        contract_id=contract_id,
        basis=SeriesBasis.LATEST_FINAL_IN_SNAPSHOT,
        cutoff_at=None,
        accepted_evidence=None,
        selection_policy=SELECTION_POLICY,
        points=tuple(points),
        excluded=tuple(excluded),
    )


def asof_final_series(events, contract_id: str, cutoff_at: datetime, *, accepted_evidence: AvailabilityEvidence) -> ResearchSettlementSeries:
    """한 cutoff 시점에 받아들인 근거로 알 수 있었던 최종가 Series (`AS_OF_CUTOFF`, PIT).

    입력: 정산가 사건들, 월물 ID, cutoff(시간대가 있는 시각), 받아들일 가장 약한 근거(기본값 없음). 출력: cutoff에 알려진 거래일(보인
    기록이나 근거 없는 기록이 있는 거래일)마다 점 하나 또는 제외 하나. cutoff에 아무 기록도 보이지 않은 거래일은 넣지 않는다 (미래
    기록의 존재를 드러내지 않음). 예외: 시간대 없는 cutoff, 잘못된 타입 → ValueError.
    """
    events = _require_events(events)
    contract_id = require_identifier(contract_id, "contract_id")
    cutoff = _require_cutoff(cutoff_at)
    accepted = _require_accepted(accepted_evidence)
    points, excluded = [], []
    for day, records in _by_trading_date(events, contract_id):
        decision, known = _decide_as_of(records, cutoff, accepted)
        if known:
            _append(day, decision, points, excluded)
    return ResearchSettlementSeries(
        contract_id=contract_id,
        basis=SeriesBasis.AS_OF_CUTOFF,
        cutoff_at=cutoff,
        accepted_evidence=accepted,
        selection_policy=SELECTION_POLICY,
        points=tuple(points),
        excluded=tuple(excluded),
    )
