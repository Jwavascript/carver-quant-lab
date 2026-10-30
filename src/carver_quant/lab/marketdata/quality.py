"""P1-01 정산가 품질 검사와 월물 메타데이터 비교 (FR-06, ADR-0007 X7-1~X7-6, ADR-0006 I6-11).

순수 함수다. 원본 바이트의 해시는 Snapshot을 읽는 Adapter가 검증한다 (`load_raw_snapshot`). 이 모듈은 manifest와 사건의 연결, 출처 표시,
Adapter가 보고한 문제, 사건 사이의 모순을 본다. 결측 가격을 채우지 않고 보고만 한다.

품질 규칙 (`QUALITY_RULE_VERSION`). Adapter의 문제는 `check`에 따라 차단이면 BLOCKED, 아니면 WARNING이다. 그 밖의 규칙:
- CONTRACT_IDENTITY: 월물 ID가 메타데이터와 다른 사건 (차단), CONFIRMED가 아닌 메타데이터 (경고).
- DECIMAL_PRICE: 0 이하의 가격 (차단).
- TICK: 일별 실제 최종가만 검사한다. 거래 tick 정산 표시가 있으면 outright tick의 배수, 없으면 정산 tick의 배수여야 한다 (차단).
  정산 tick을 모르면 outright tick으로 대신 검사하지 않고 경고한다. 잠정가는 반올림 전 값일 수 있어 검사하지 않는다.
- DATE_AND_EXPIRY: 마지막 거래일 뒤의 거래일 (차단), 요청 기간 밖의 거래일 (경고), 달력 범위 안인데 달력에 없는 거래일 (경고).
- TIMESTAMP_TIMEZONE: 거래일 UTC 자정보다 이른 시각 (차단. 정산 기록은 그 거래일이 시작되기 전에 나올 수 없다는 하한 검사이며 거래일을
  UTC 날짜로 정하지 않는다), 거래소·공급자 시각보다 이른 시스템 수신 (차단), 거래소 시각보다 이른 공급자 수집 (경고, 시계 차이).
- DUPLICATES_AND_CONFLICTS: 같은 레코드 ID에 같은 내용 (경고) 또는 다른 내용 (차단), 같은 순서 위치에 다른 내용 (차단), 순서를 정할 수
  없는데 다른 내용 (차단).
- MISSING_SESSIONS: 달력이 요청 기간(마지막 거래일까지)을 덮으면 최종가가 없는 달력 거래일을 결측으로 보고하고 (경고), 달력이
  CONFIRMED가 아니면 경고한다. 달력이 없거나 기간을 덮지 않으면 NOT_ASSESSABLE이며, 달력이 없을 때는 최종가가 없는 평일을 미확인
  공백으로만 보고한다 (휴장인지 결측인지 단정하지 않음).
- REVISION_ORDER: 순서가 다른 위치에서 가격이 바뀐 최종가 (경고, 정정), 최종가 뒤의 잠정가 (차단), 공급자 수집 순서와 거래소 순서가
  반대인 기록 (차단), 철회로 끝난 거래일, 잠정가만 있는 거래일, 장중·이론 정산가만 있는 거래일 (경고).
- SOURCE_INTEGRITY: 합성 데이터 (차단), manifest에 없는 Snapshot의 사건 (차단), Snapshot 획득 시각과 다른 시스템 수신 시각 (차단).
- AVAILABILITY_EVIDENCE: 공급자 수집 시각이 없는 일별 실제 최종가 (경고).
- COVERAGE: 요청 기간에서 Snapshot의 최신 최종가가 있는 거래일 수가 최소값보다 적음 (차단).
"""

from collections import defaultdict
from datetime import date, timedelta

from carver_quant.lab.domain.market_data import (
    AvailabilityEvidence,
    DataOrigin,
    FuturesContractMetadata,
    QualityCheck,
    QualityCheckName,
    QualityFinding,
    QualityStatus,
    RawSnapshotManifest,
    SettlementEvent,
    SettlementQualityReport,
    SettlementRevisionStatus,
    SourceIssue,
    TradingCalendarReference,
    VerificationLevel,
    require_date,
    worst_quality_status,
)
from carver_quant.lab.domain.values import EXACT_DECIMAL_CONTEXT, require_int
from carver_quant.lab.marketdata.settlements import (
    is_daily_settlement_record,
    latest_final_series,
    source_order_inverted,
    source_order_key,
    utc_midnight,
)

QUALITY_RULE_VERSION = "p1-01-settlement-quality/1"

# 품질 보고서가 확인하지 않는 것. 보고서가 PASSED여도 이 항목들은 따로 확인해야 한다.
SETTLEMENT_DATA_NOT_ESTABLISHED = (
    "USER_RECEIPT_TIME",  # 공급자 수집 시각은 사용자가 실제로 받은 시각이 아니다. 연구용 근거 수준은 미결정 (ADR-0004 Q4-3, D3A-13)
    "OFFICIAL_SETTLEMENT_MATCH",  # 거래소가 공표한 정산가 자료와 대조하지 않았다
    "EXCHANGE_CALENDAR",  # 거래소 휴장일·반일장. 달력은 입력이며 이 코드가 만들지 않는다
    "SETTLEMENT_TICK_RULE",  # 정산 tick·반올림 규칙은 메타데이터가 주는 만큼만 검사한다
    "EXECUTABLE_PRICE",  # 정산가는 연구용 raw 관측값이다. 체결 가능한 가격이 아니다 (D3A-50)
    "CONTINUOUS_SERIES",  # 단일 월물이다. 연속 선물, back-adjustment, 롤이 아니다
)

_COMPARED_METADATA_FIELDS = (
    "exchange",
    "product_root",
    "contract_id",
    "contract_year",
    "contract_month",
    "multiplier",
    "outright_tick_size",
    "outright_tick_value",
    "settlement_tick_size",
    "currency",
    "price_unit",
    "last_trading_date",
    "last_trading_at",
    "settlement_type",
)

# 최신 최종가 Series의 제외 사유 → REVISION_ORDER 경고 코드. 상충(AMBIGUOUS)은 DUPLICATES_AND_CONFLICTS·REVISION_ORDER 차단으로 보고한다.
_EXCLUSION_WARNINGS = {
    "SETTLEMENT_WITHDRAWN": "SETTLEMENT_WITHDRAWN",
    "PRELIMINARY_ONLY": "PRELIMINARY_WITHOUT_FINAL",
    "ONLY_INTRADAY_OR_THEORETICAL": "NO_DAILY_ACTUAL_SETTLEMENT",
}

_BLOCKED, _WARNING = QualityStatus.BLOCKED, QualityStatus.WARNING


def compare_contract_metadata(declared: FuturesContractMetadata, *, reference: FuturesContractMetadata) -> tuple[str, ...]:
    """선언한 월물 메타데이터를 기준 기록(예: 공식 자료에서 옮긴 값)과 비교한다.

    입력: 선언 메타데이터, 기준 메타데이터. 출력: 값이 다른 금융 필드의 이름 (필드 순서). Decimal은 수치로 비교하고, 판본·출처
    (`metadata_version`, `provenance`)는 비교하지 않는다. 예외: 입력이 `FuturesContractMetadata`가 아니면 ValueError.
    """
    if type(declared) is not FuturesContractMetadata or type(reference) is not FuturesContractMetadata:
        raise ValueError("declared and reference must be FuturesContractMetadata values.")

    return tuple(name for name in _COMPARED_METADATA_FIELDS if getattr(declared, name) != getattr(reference, name))


def _require_values(values: object, kind: type, name: str) -> tuple:
    if not isinstance(values, (tuple, list)) or any(type(item) is not kind for item in values):
        raise ValueError(f"{name} must be a tuple or list of {kind.__name__} values.")

    return tuple(values)


def _on_grid(price, tick) -> bool:
    return EXACT_DECIMAL_CONTEXT.remainder(price, tick) == 0


def _record_content(event: SettlementEvent) -> tuple:
    # 같은 원본 레코드를 다른 Snapshot에서 다시 받으면 Snapshot ID와 수신 시각만 다르다.
    return (
        event.contract_id,
        event.trading_date,
        event.price_type,
        event.price,
        event.revision_status,
        event.actual,
        event.at_trading_tick,
        event.observed_at,
        event.published_at,
        event.vendor_received_at,
    )


def _weekdays(start: date, end: date) -> list[date]:
    days = [start + timedelta(days=offset) for offset in range((end - start).days + 1)]
    return [day for day in days if day.weekday() < 5]


def assess_settlement_quality(
    *,
    metadata: FuturesContractMetadata,
    manifests,
    events,
    issues,
    requested_start: date,
    requested_end: date,
    minimum_final_days: int,
    calendar: TradingCalendarReference | None,
) -> SettlementQualityReport:
    """월물 하나의 정산가 사건을 품질 규칙으로 검사한다 (FR-06).

    입력: 월물 메타데이터, 사건이 나온 Raw Snapshot manifest(하나 이상, 해시는 읽을 때 검증된 것), 정산가 사건, Adapter가 보고한 문제,
    요청 기간(거래일 라벨, 포함), 최소 유효 거래일 수(기본값 없음), 거래소 달력(없으면 None, 지어내지 않음).
    출력: `SettlementQualityReport`. 가격을 바꾸거나 채우지 않는다.
    예외: 잘못된 타입, 시작일 > 종료일, 음수 최소값, 중복 manifest, 다른 거래소의 달력 → ValueError.
    """
    if type(metadata) is not FuturesContractMetadata:
        raise ValueError("metadata must be a FuturesContractMetadata.")
    manifests = _require_values(manifests, RawSnapshotManifest, "manifests")
    events = _require_values(events, SettlementEvent, "events")
    issues = _require_values(issues, SourceIssue, "issues")
    start, end = require_date(requested_start, "requested_start"), require_date(requested_end, "requested_end")
    if start > end:
        raise ValueError("requested_start must not be later than requested_end.")
    minimum = require_int(minimum_final_days, "minimum_final_days")
    if minimum < 0:
        raise ValueError("minimum_final_days must not be negative.")
    by_snapshot = {item.snapshot_id: item for item in manifests}
    if not manifests or len(by_snapshot) != len(manifests):
        raise ValueError("manifests must contain at least one snapshot, each once.")
    if calendar is not None and (type(calendar) is not TradingCalendarReference or calendar.exchange != metadata.exchange):
        raise ValueError("calendar must be a TradingCalendarReference for the contract's exchange.")

    found = {name: {} for name in QualityCheckName}

    def flag(check: QualityCheckName, status: QualityStatus, code: str, ref: str) -> None:
        previous, refs = found[check].get(code, (QualityStatus.PASSED, set()))
        refs.add(ref)
        found[check][code] = (worst_quality_status((previous, status)), refs)

    for issue in issues:
        flag(issue.check, _BLOCKED if issue.blocking else _WARNING, issue.code, issue.record_ref)

    for manifest in manifests:
        if manifest.data_origin is DataOrigin.SYNTHETIC:
            flag(QualityCheckName.SOURCE_INTEGRITY, _BLOCKED, "DATA_ORIGIN_SYNTHETIC", manifest.snapshot_id)
    if metadata.provenance.verification is not VerificationLevel.CONFIRMED:
        flag(QualityCheckName.CONTRACT_IDENTITY, _WARNING, "METADATA_NOT_CONFIRMED", metadata.metadata_version)

    own = []
    for event in events:
        ref = event.source_record_id
        manifest = by_snapshot.get(event.source_snapshot_id)
        if manifest is None:
            flag(QualityCheckName.SOURCE_INTEGRITY, _BLOCKED, "UNKNOWN_SOURCE_SNAPSHOT", ref)
        elif event.ingested_at != manifest.acquired_at:
            flag(QualityCheckName.SOURCE_INTEGRITY, _BLOCKED, "INGESTED_AT_NOT_ACQUISITION_TIME", ref)
        if event.contract_id != metadata.contract_id:
            flag(QualityCheckName.CONTRACT_IDENTITY, _BLOCKED, "CONTRACT_ID_MISMATCH", ref)
        else:
            own.append(event)

    covered = calendar is not None and calendar.coverage_start <= start and min(end, metadata.last_trading_date) <= calendar.coverage_end
    calendar_dates = set(calendar.dates) if calendar is not None else set()
    for event in own:
        ref = event.source_record_id
        if event.price is not None and event.price <= 0:
            flag(QualityCheckName.DECIMAL_PRICE, _BLOCKED, "NON_POSITIVE_PRICE", ref)

        if event.trading_date > metadata.last_trading_date:
            flag(QualityCheckName.DATE_AND_EXPIRY, _BLOCKED, "AFTER_LAST_TRADING_DATE", ref)
        if not start <= event.trading_date <= end:
            flag(QualityCheckName.DATE_AND_EXPIRY, _WARNING, "OUTSIDE_REQUESTED_RANGE", ref)
        elif (
            calendar is not None
            and calendar.coverage_start <= event.trading_date <= calendar.coverage_end
            and event.trading_date not in calendar_dates
        ):
            flag(QualityCheckName.DATE_AND_EXPIRY, _WARNING, "NOT_IN_EXPECTED_CALENDAR", ref)

        source_times = [moment for moment in (event.observed_at, event.published_at, event.vendor_received_at) if moment is not None]
        if any(moment < utc_midnight(event.trading_date) for moment in (*source_times, event.ingested_at)):
            flag(QualityCheckName.TIMESTAMP_TIMEZONE, _BLOCKED, "TIMESTAMP_BEFORE_TRADING_DATE", ref)
        if any(event.ingested_at < moment for moment in source_times):
            flag(QualityCheckName.TIMESTAMP_TIMEZONE, _BLOCKED, "INGESTED_BEFORE_SOURCE_TIME", ref)
        if event.published_at is not None and event.vendor_received_at is not None and event.vendor_received_at < event.published_at:
            flag(QualityCheckName.TIMESTAMP_TIMEZONE, _WARNING, "VENDOR_CAPTURE_BEFORE_PUBLICATION", ref)

    relevant = [event for event in own if is_daily_settlement_record(event)]
    finals = [event for event in relevant if event.revision_status is SettlementRevisionStatus.FINAL]
    counts = {level: 0 for level in AvailabilityEvidence}
    for event in finals:
        ref = event.source_record_id
        if event.at_trading_tick:
            if not _on_grid(event.price, metadata.outright_tick_size):
                flag(QualityCheckName.TICK, _BLOCKED, "OFF_TRADING_TICK", ref)
        elif metadata.settlement_tick_size is None:
            flag(QualityCheckName.TICK, _WARNING, "SETTLEMENT_TICK_SIZE_UNVERIFIED", ref)
        elif not _on_grid(event.price, metadata.settlement_tick_size):
            flag(QualityCheckName.TICK, _BLOCKED, "OFF_SETTLEMENT_TICK", ref)

        counts[event.availability_evidence] += 1
        if event.availability_evidence is AvailabilityEvidence.EXCHANGE_PUBLICATION:
            flag(QualityCheckName.AVAILABILITY_EVIDENCE, _WARNING, "EXCHANGE_TIME_ONLY", ref)
        elif event.availability_evidence is AvailabilityEvidence.SYSTEM_RECEIPT:
            flag(QualityCheckName.AVAILABILITY_EVIDENCE, _WARNING, "SYSTEM_RECEIPT_ONLY", ref)

    by_record = defaultdict(list)
    for event in events:
        by_record[event.source_record_id].append(event)
    for record_id, group in by_record.items():
        if len(group) > 1:
            same = len({_record_content(event) for event in group}) == 1
            flag(QualityCheckName.DUPLICATES_AND_CONFLICTS, _WARNING if same else _BLOCKED,
                 "DUPLICATE_RECORDS" if same else "SOURCE_RECORD_ID_CONFLICT", record_id)

    by_day = defaultdict(list)
    for event in relevant:
        by_day[event.trading_date].append(event)
    corrected = []
    for day, group in sorted(by_day.items()):
        label = day.isoformat()
        if source_order_inverted(group, known_by=None):
            flag(QualityCheckName.REVISION_ORDER, _BLOCKED, "SOURCE_ORDER_INVERSION", label)
        key = source_order_key(group, known_by=None)
        if key is None:
            if len({(event.revision_status, event.price) for event in group}) > 1:
                flag(QualityCheckName.DUPLICATES_AND_CONFLICTS, _BLOCKED, "UNORDERED_RECORDS", label)
            continue
        positions = defaultdict(set)
        for event in group:
            positions[key(event)].add((event.revision_status, event.price))
        if any(len(contents) > 1 for contents in positions.values()):
            flag(QualityCheckName.DUPLICATES_AND_CONFLICTS, _BLOCKED, "CONFLICTING_RECORDS_AT_SAME_TIME", label)
        day_finals = [event for event in group if event.revision_status is SettlementRevisionStatus.FINAL]
        if len({event.price for event in day_finals}) > 1 and len({key(event) for event in day_finals}) > 1:
            flag(QualityCheckName.REVISION_ORDER, _WARNING, "FINAL_CORRECTED", label)
            if start <= day <= end:
                corrected.append(day)
        if day_finals and any(
            event.revision_status is SettlementRevisionStatus.PRELIMINARY and key(event) > min(key(item) for item in day_finals)
            for event in group
        ):
            flag(QualityCheckName.REVISION_ORDER, _BLOCKED, "PRELIMINARY_AFTER_FINAL", label)

    latest = latest_final_series(own, metadata.contract_id)
    for exclusion in latest.excluded:
        for reason in exclusion.reasons:
            if reason in _EXCLUSION_WARNINGS:
                flag(QualityCheckName.REVISION_ORDER, _WARNING, _EXCLUSION_WARNINGS[reason], exclusion.trading_date.isoformat())

    final_days = tuple(point.trading_date for point in latest.points if start <= point.trading_date <= end)
    final_set = set(final_days)
    last_day = min(end, metadata.last_trading_date)
    missing, gaps = (), ()
    if calendar is None:
        flag(QualityCheckName.MISSING_SESSIONS, QualityStatus.NOT_ASSESSABLE, "NO_EXCHANGE_CALENDAR", "calendar")
        gaps = tuple(day for day in _weekdays(start, last_day) if day not in final_set) if start <= last_day else ()
    elif not covered:
        flag(QualityCheckName.MISSING_SESSIONS, QualityStatus.NOT_ASSESSABLE, "CALENDAR_DOES_NOT_COVER_RANGE", "calendar")
    else:
        missing = tuple(day for day in calendar.dates if start <= day <= last_day and day not in final_set)
        for day in missing:
            flag(QualityCheckName.MISSING_SESSIONS, _WARNING, "MISSING_TRADING_DATES", day.isoformat())
    if calendar is not None and calendar.provenance.verification is not VerificationLevel.CONFIRMED:
        flag(QualityCheckName.MISSING_SESSIONS, _WARNING, "CALENDAR_NOT_CONFIRMED", "calendar")

    if len(final_days) < minimum:
        flag(QualityCheckName.COVERAGE, _BLOCKED, "INSUFFICIENT_FINAL_DAYS", f"final_days:{len(final_days)},minimum:{minimum}")

    checks = []
    for name in QualityCheckName:
        findings = tuple(
            QualityFinding(code=code, status=status, refs=tuple(sorted(refs))) for code, (status, refs) in sorted(found[name].items())
        )
        checks.append(QualityCheck(name=name, status=worst_quality_status(item.status for item in findings), findings=findings))
    return SettlementQualityReport(
        contract_id=metadata.contract_id,
        rule_version=QUALITY_RULE_VERSION,
        metadata_version=metadata.metadata_version,
        snapshot_ids=tuple(sorted(by_snapshot)),
        requested_start=start,
        requested_end=end,
        minimum_final_days=minimum,
        status=worst_quality_status(item.status for item in checks),
        checks=tuple(checks),
        final_trading_dates=final_days,
        missing_trading_dates=missing,
        unverified_gaps=gaps,
        excluded=tuple(item for item in latest.excluded if start <= item.trading_date <= end),
        corrected_trading_dates=tuple(corrected),
        evidence_counts=tuple((level, counts[level]) for level in AvailabilityEvidence),
        not_established=SETTLEMENT_DATA_NOT_ESTABLISHED,
    )
