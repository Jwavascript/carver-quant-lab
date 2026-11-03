"""P1-02 연속 선물 품질 검사 (P1-02 명세 §6, ADR-0004 §6.4, ADR-0007 X7-2·X7-3·X7-6).

Research 계층의 순수 함수다. `lab.domain`과 같은 패키지만 import한다. 롤 계획, 롤 결정 결과, 조정 시계열, 월물별 입력과 P1-01 품질 보고서를
받아 검사하고 고치거나 채우지 않는다. 입력끼리 맞지 않으면(다른 계획·근거·처음 월물·알고리즘으로 만든 시계열, 롤 결정 결과와 다른 적용 롤,
다른 cutoff의 입력, 시계열이 쓴 Snapshot을 덮지 않는 월물 보고서) ValueError다. 시계열을 만들 수 없었으면(해결되지 않은 롤 등) 시계열이 필요한
검사는 NOT_ASSESSABLE이다. As-of 시계열의 보고서는 그 `as_of`에 알려진 롤(known_at ≤ as_of)만 판단한다 (뒤의 정보로 판정이 바뀌지 않음).

규칙 (`CONTINUOUS_QUALITY_RULE_VERSION`):
- CONTRACT_IDENTITY: 메타데이터의 월물 ID가 계획과 다름, 거래소·상품·통화·가격 단위·승수가 월물마다 다름 (차단), CONFIRMED가 아닌 메타데이터 (경고).
- ROLL_ORDER: 신월물이 구월물보다 먼저 만기, 기준일이나 신월물 첫 거래일이 구월물 마지막 거래일 뒤 (구월물을 만기 뒤에 선택함) (차단).
- EXPIRY: 선택한 월물의 마지막 거래일 뒤의 점이나 제외 (차단).
- REFERENCE_PRICES: known_at에 기준 가격을 정할 수 없는 롤 (차단).
- OVERLAP: 두 월물에 모두 최종가가 있는 거래일. 없거나 기준일이 빠짐 (경고).
- SELECTION_COVERAGE: 빈 시계열 (차단), 선택 월물의 쓸 수 없는 정산가, 롤 기준일 뒤 구월물 점, 아직 알려지지 않은 롤 뒤의 날 (경고).
- MISSING_SESSIONS: 시계열 범위(첫 점 ~ 마지막 점·제외)를 덮는 달력이 있으면 점도 제외도 없는 달력 거래일 (경고)과 달력에 없는 평일(휴장일로
  보고)을 나누고, 달력이 CONFIRMED가 아니면 경고. 달력이 없거나 덮지 않으면 NOT_ASSESSABLE이며 비어 있는 평일을 미확인 공백으로만 보고한다.
- PIT: `as_of`에 알려진 롤을 모두 적용했는지 (차단). 점·롤의 시각 상한은 도메인 타입이 보장한다.
- DECIMAL_PRECISION: 원본 정밀도(1e-9)보다 작은 자릿수가 생긴 값 (차단).
- ADJUSTMENT_ARITHMETIC: 일별 변화를 raw 가격으로 독립 재계산한다. 같은 월물이면 raw 변화, 롤 경계면 같은 `as_of` 입력에서 본 신월물 자신의
  기준일 → 첫 점 변화 + (신월물 기준일 정정분 − 구월물 기준일 정정분)과 같아야 한다 (다르면 차단. 정정분 = 그 `as_of`의 기준일 가격 − 롤의 고정
  기준가). 경계가 롤 기준일에 있지 않거나 신월물 기준일 가격이 입력에 없음 (차단), 기준일 가격이 known_at 뒤에 정정됨 (경고. 정정으로 설명되는
  어긋남만 경고이고, 산술 검사는 정정이 있어도 생략하지 않음).
- SOURCE_INTEGRITY: manifest에 없는 Snapshot을 가리키는 점·롤, 합성 데이터 (차단).
- CONTRACT_DATA_QUALITY: 월물별 P1-01 품질 보고서가 BLOCKED (차단), WARNING·NOT_ASSESSABLE (경고).
"""

from collections.abc import Mapping
from datetime import date, timedelta

from carver_quant.lab.domain.continuous import (
    AdjustedPriceSeries,
    AdjustmentMethod,
    ContinuousCheckName,
    ContinuousQualityCheck,
    ContinuousQualityReport,
    ContinuousSeriesBasis,
    FuturesRollEvent,
    RollBoundary,
    RollOverlap,
    RollPlan,
    UnresolvedRoll,
)
from carver_quant.lab.domain.market_data import (
    DataOrigin,
    FuturesContractMetadata,
    QualityFinding,
    QualityStatus,
    RawSnapshotManifest,
    ResearchSettlementSeries,
    SeriesBasis,
    SettlementQualityReport,
    TradingCalendarReference,
    VerificationLevel,
    worst_quality_status,
)
from carver_quant.lab.domain.values import EXACT_DECIMAL_CONTEXT
from carver_quant.lab.research.continuous import ALGORITHM_VERSION, AFTER_ROLL_REFERENCE_DATE, ROLL_NOT_YET_KNOWN, require_roll_outcomes

CONTINUOUS_QUALITY_RULE_VERSION = "p1-02-continuous-quality/1"

# 이 보고서가 확인하지 않는 것. 보고서가 PASSED여도 이 항목들은 따로 확인해야 한다.
CONTINUOUS_NOT_ESTABLISHED = (
    "EXECUTABLE_ROLL",  # 롤 기준일·gap은 주문·체결 시각이나 가격이 아니다
    "ROLL_POLICY",  # 실거래 롤 날짜·유동성 기준은 미결정이다. 계획은 연구용 시나리오다
    "ROLL_COST",  # 롤 거래비용은 계산하지 않는다 (ADR-0006 I6-9)
    "USER_RECEIPT_TIME",  # 공급자 수집 시각은 사용자가 실제로 받은 시각이 아니다
    "EXCHANGE_CALENDAR",  # 달력은 입력이며 이 코드가 만들지 않는다
    "SETTLEMENT_TICK_RULE",  # 정산 tick·반올림 규칙
    "TICK_VALUE",  # 이 단계는 index point 차이만 쓴다
)

_BLOCKED, _WARNING, _NOT_ASSESSABLE = QualityStatus.BLOCKED, QualityStatus.WARNING, QualityStatus.NOT_ASSESSABLE
_SOURCE_EXPONENT = -9  # 원본(Databento) 가격의 소수 자릿수 한계
_SPEC_FIELDS = ("exchange", "product_root", "currency", "price_unit", "multiplier")
_EXCLUSION_CODES = {AFTER_ROLL_REFERENCE_DATE: AFTER_ROLL_REFERENCE_DATE, ROLL_NOT_YET_KNOWN: ROLL_NOT_YET_KNOWN}


def _require_mapping(values: object, kind: type, keys: tuple[str, ...], name: str) -> Mapping:
    if not isinstance(values, Mapping) or set(values) != set(keys) or any(type(item) is not kind for item in values.values()):
        raise ValueError(f"{name} must map every plan contract to a {kind.__name__}.")

    return values


def _weekdays(start: date, end: date) -> list[date]:
    days = [start + timedelta(days=offset) for offset in range((end - start).days + 1)]
    return [day for day in days if day.weekday() < 5]


def _roll_ref(roll) -> str:
    entry = roll.entry if type(roll) is UnresolvedRoll else roll
    return f"{entry.from_contract_id}->{entry.to_contract_id}@{entry.roll_reference_date.isoformat()}"


def _check_linkage(plan, outcomes, series, contract_series, contract_reports) -> None:
    """입력끼리 같은 계획·근거·cutoff·Snapshot에서 나왔는지 확인한다. 아니면 ValueError."""
    cutoffs = {item.cutoff_at for item in contract_series.values()}
    if any(
        item.basis is not SeriesBasis.AS_OF_CUTOFF or item.accepted_evidence is not plan.accepted_evidence for item in contract_series.values()
    ):
        raise ValueError("contract series must be as-of settlement series on the plan's accepted evidence.")
    if len(cutoffs) != 1 or (series is not None and cutoffs != {series.as_of}):
        raise ValueError("contract series must share one cutoff, equal to the series' as_of.")
    used = {contract_id: {point.source_snapshot_id for point in item.points} for contract_id, item in contract_series.items()}
    if series is not None:
        if type(series) is not AdjustedPriceSeries or (
            series.roll_plan_id, series.research_instrument_id, series.initial_contract_id, series.accepted_evidence, series.method,
            series.algorithm_version,
        ) != (plan.plan_id, plan.research_instrument_id, plan.initial_contract_id, plan.accepted_evidence,
              AdjustmentMethod.FUTURES_ADDITIVE_BACK_ADJUSTED, ALGORITHM_VERSION):
            raise ValueError("series must be an AdjustedPriceSeries built from this plan with this module's algorithm.")
        applied = series.applied_rolls
        if any(type(item) is not FuturesRollEvent for item in outcomes[:len(applied)]) or applied != outcomes[:len(applied)]:
            raise ValueError("the series' applied rolls must be the plan's first resolved roll outcomes.")
        for point in series.points:
            used[point.selected_contract_id].add(point.source_snapshot_id)
        for roll in applied:
            used[roll.from_contract_id].add(roll.old_source_snapshot_id)
            used[roll.to_contract_id].add(roll.new_source_snapshot_id)
    for contract_id, report in contract_reports.items():
        if report.contract_id != contract_id or not used[contract_id] <= set(report.snapshot_ids):
            raise ValueError("each contract report must belong to its contract and cover every snapshot the series uses for it.")


def assess_continuous_series(
    *,
    plan: RollPlan,
    metadata: Mapping[str, FuturesContractMetadata],
    roll_outcomes,
    series: AdjustedPriceSeries | None,
    contract_series: Mapping[str, ResearchSettlementSeries],
    contract_reports: Mapping[str, SettlementQualityReport],
    manifests,
    calendar: TradingCalendarReference | None,
) -> ContinuousQualityReport:
    """연속 선물 시계열 하나를 품질 규칙으로 검사한다.

    입력: 롤 계획, 계획의 월물마다 메타데이터·입력 정산가 As-of Series(시계열과 같은 cutoff)·P1-01 품질 보고서, 롤 결정 결과(계획 순서), 조정
    시계열(만들 수 없었으면 None), 입력 Raw Snapshot manifest(하나 이상), 거래소 달력(없으면 None, 지어내지 않음).
    출력: `ContinuousQualityReport`. 값을 바꾸거나 채우지 않는다.
    예외: 잘못된 타입, 서로 맞지 않는 입력(모듈 설명), 다른 거래소의 달력, 빈 manifest → ValueError.
    """
    if type(plan) is not RollPlan:
        raise ValueError("plan must be a RollPlan.")
    contracts = plan.contracts
    metadata = _require_mapping(metadata, FuturesContractMetadata, contracts, "metadata")
    contract_series = _require_mapping(contract_series, ResearchSettlementSeries, contracts, "contract_series")
    contract_reports = _require_mapping(contract_reports, SettlementQualityReport, contracts, "contract_reports")
    outcomes = require_roll_outcomes(plan, roll_outcomes)
    _check_linkage(plan, outcomes, series, contract_series, contract_reports)
    if not isinstance(manifests, (tuple, list)) or not manifests or any(type(item) is not RawSnapshotManifest for item in manifests):
        raise ValueError("manifests must contain at least one RawSnapshotManifest.")
    if calendar is not None and (type(calendar) is not TradingCalendarReference
                                 or calendar.exchange != metadata[plan.initial_contract_id].exchange):
        raise ValueError("calendar must be a TradingCalendarReference for the contracts' exchange.")
    # As-of 시계열은 그 as_of에 알려진 롤만 판단한다. 시계열이 없거나 FULL_SAMPLE이면 계획의 모든 롤을 판단한다.
    judged = [
        (entry, outcome) for entry, outcome in zip(plan.entries, outcomes)
        if series is None or series.basis is ContinuousSeriesBasis.FULL_SAMPLE or entry.evidence_cutoff_at <= series.as_of
    ]

    found = {name: {} for name in ContinuousCheckName}

    def flag(check: ContinuousCheckName, status: QualityStatus, code: str, ref: str) -> None:
        previous, refs = found[check].get(code, (QualityStatus.PASSED, set()))
        refs.add(ref)
        found[check][code] = (worst_quality_status((previous, status)), refs)

    # CONTRACT_IDENTITY
    first = metadata[plan.initial_contract_id]
    for contract_id in contracts:
        item = metadata[contract_id]
        if item.contract_id != contract_id:
            flag(ContinuousCheckName.CONTRACT_IDENTITY, _BLOCKED, "METADATA_CONTRACT_MISMATCH", contract_id)
        if any(getattr(item, name) != getattr(first, name) for name in _SPEC_FIELDS):
            flag(ContinuousCheckName.CONTRACT_IDENTITY, _BLOCKED, "CONTRACT_SPEC_MISMATCH", contract_id)
        if item.provenance.verification is not VerificationLevel.CONFIRMED:
            flag(ContinuousCheckName.CONTRACT_IDENTITY, _WARNING, "METADATA_NOT_CONFIRMED", contract_id)

    # ROLL_ORDER (계획 전체), REFERENCE_PRICES·OVERLAP (판단하는 롤)
    for entry in plan.entries:
        ref = f"{entry.from_contract_id}->{entry.to_contract_id}@{entry.roll_reference_date.isoformat()}"
        old, new = metadata[entry.from_contract_id], metadata[entry.to_contract_id]
        if new.last_trading_date <= old.last_trading_date:
            flag(ContinuousCheckName.ROLL_ORDER, _BLOCKED, "NEW_CONTRACT_EXPIRES_FIRST", ref)
        if entry.roll_reference_date > old.last_trading_date:
            flag(ContinuousCheckName.ROLL_ORDER, _BLOCKED, "REFERENCE_AFTER_OLD_EXPIRY", ref)
        if entry.new_contract_first_date > old.last_trading_date:
            flag(ContinuousCheckName.ROLL_ORDER, _BLOCKED, "ROLL_AFTER_OLD_EXPIRY", ref)
    overlaps = []
    for entry, outcome in judged:
        ref = _roll_ref(outcome)
        if type(outcome) is UnresolvedRoll:
            flag(ContinuousCheckName.REFERENCE_PRICES, _BLOCKED, "REFERENCE_PRICE_UNAVAILABLE", f"{ref}:{','.join(outcome.reasons)}")
        old_days = {point.trading_date for point in contract_series[entry.from_contract_id].points}
        both = tuple(sorted(old_days & {point.trading_date for point in contract_series[entry.to_contract_id].points}))
        overlaps.append(RollOverlap(from_contract_id=entry.from_contract_id, to_contract_id=entry.to_contract_id, trading_dates=both))
        if not both:
            flag(ContinuousCheckName.OVERLAP, _WARNING, "NO_OVERLAP", ref)
        elif entry.roll_reference_date not in both:
            flag(ContinuousCheckName.OVERLAP, _WARNING, "REFERENCE_DATE_NOT_IN_OVERLAP", ref)

    # SOURCE_INTEGRITY, CONTRACT_DATA_QUALITY
    known_snapshots = {item.snapshot_id for item in manifests}
    for manifest in manifests:
        if manifest.data_origin is DataOrigin.SYNTHETIC:
            flag(ContinuousCheckName.SOURCE_INTEGRITY, _BLOCKED, "DATA_ORIGIN_SYNTHETIC", manifest.snapshot_id)
    for _, outcome in judged:
        if type(outcome) is FuturesRollEvent and not {outcome.old_source_snapshot_id, outcome.new_source_snapshot_id} <= known_snapshots:
            flag(ContinuousCheckName.SOURCE_INTEGRITY, _BLOCKED, "UNKNOWN_SOURCE_SNAPSHOT", _roll_ref(outcome))
    for contract_id in contracts:
        status = contract_reports[contract_id].status
        if status is QualityStatus.BLOCKED:
            flag(ContinuousCheckName.CONTRACT_DATA_QUALITY, _BLOCKED, "CONTRACT_DATA_BLOCKED", contract_id)
        elif status is QualityStatus.NOT_ASSESSABLE:
            flag(ContinuousCheckName.CONTRACT_DATA_QUALITY, _WARNING, "CONTRACT_DATA_NOT_FULLY_ASSESSED", contract_id)
        elif status is QualityStatus.WARNING:
            flag(ContinuousCheckName.CONTRACT_DATA_QUALITY, _WARNING, "CONTRACT_DATA_WARNINGS", contract_id)

    boundaries, missing, holidays, gaps = [], (), (), ()
    if series is None:
        for name in (ContinuousCheckName.EXPIRY, ContinuousCheckName.SELECTION_COVERAGE, ContinuousCheckName.MISSING_SESSIONS,
                     ContinuousCheckName.PIT, ContinuousCheckName.DECIMAL_PRECISION, ContinuousCheckName.ADJUSTMENT_ARITHMETIC):
            flag(name, _NOT_ASSESSABLE, "SERIES_NOT_BUILT", plan.plan_id)
    else:
        points = series.points
        for item in (*points, *series.excluded):
            if item.trading_date > metadata[item.selected_contract_id].last_trading_date:
                flag(ContinuousCheckName.EXPIRY, _BLOCKED, "SELECTED_AFTER_LAST_TRADING_DATE", item.trading_date.isoformat())
        if not points:
            flag(ContinuousCheckName.SELECTION_COVERAGE, _BLOCKED, "EMPTY_SERIES", plan.plan_id)
        for item in series.excluded:
            code = _EXCLUSION_CODES.get(item.reasons[0], "SELECTED_SETTLEMENT_UNUSABLE")
            flag(ContinuousCheckName.SELECTION_COVERAGE, _WARNING, code, item.trading_date.isoformat())

        if len(series.applied_rolls) != len(judged):
            flag(ContinuousCheckName.PIT, _BLOCKED, "KNOWN_ROLL_NOT_APPLIED", plan.plan_id)
        for point in points:
            if point.source_snapshot_id not in known_snapshots:
                flag(ContinuousCheckName.SOURCE_INTEGRITY, _BLOCKED, "UNKNOWN_SOURCE_SNAPSHOT", point.trading_date.isoformat())

        values = [price for roll in series.applied_rolls for price in (roll.old_reference_price, roll.new_reference_price)]
        for point in points:
            values += [point.raw_price, point.cumulative_adjustment_points, point.adjusted_price]
            if point.daily_price_change_points is not None:
                values.append(point.daily_price_change_points)
        if any(value.as_tuple().exponent < _SOURCE_EXPONENT for value in values):
            flag(ContinuousCheckName.DECIMAL_PRECISION, _BLOCKED, "PRECISION_BEYOND_SOURCE", plan.plan_id)

        by_pair = {(roll.from_contract_id, roll.to_contract_id): roll for roll in series.applied_rolls}
        for previous, current in zip(points, points[1:]):
            label = current.trading_date.isoformat()
            if previous.selected_contract_id == current.selected_contract_id:
                if current.daily_price_change_points != EXACT_DECIMAL_CONTEXT.subtract(current.raw_price, previous.raw_price):
                    flag(ContinuousCheckName.ADJUSTMENT_ARITHMETIC, _BLOCKED, "PRICE_CHANGE_MISMATCH", label)
                continue
            roll = by_pair.get((previous.selected_contract_id, current.selected_contract_id))
            if roll is None or previous.trading_date != roll.roll_reference_date:
                flag(ContinuousCheckName.ADJUSTMENT_ARITHMETIC, _BLOCKED, "ROLL_BOUNDARY_NOT_AT_REFERENCE_DATE", label)
                continue
            new_reference = next((point for point in contract_series[roll.to_contract_id].points
                                  if point.trading_date == roll.roll_reference_date), None)
            if new_reference is None:
                flag(ContinuousCheckName.ADJUSTMENT_ARITHMETIC, _BLOCKED, "NEW_REFERENCE_NOT_IN_INPUT", label)
                continue
            # 신월물 자신의 변화는 같은 as_of 입력에서 본 기준일 가격으로 계산한다 (롤의 고정 기준가가 아님).
            new_change = EXACT_DECIMAL_CONTEXT.subtract(current.raw_price, new_reference.price)
            naive = EXACT_DECIMAL_CONTEXT.subtract(current.raw_price, previous.raw_price)
            boundaries.append(RollBoundary(
                from_contract_id=roll.from_contract_id, to_contract_id=roll.to_contract_id, last_old_trading_date=previous.trading_date,
                first_new_trading_date=current.trading_date, naive_raw_change_points=naive, new_contract_change_points=new_change,
                adjusted_change_points=current.daily_price_change_points,
                spurious_jump_points=EXACT_DECIMAL_CONTEXT.subtract(naive, new_change)))
            # gap은 known_at의 기준가로 고정되므로, 기준일 가격이 그 뒤 정정되면 경계 변화가 신월물 자신의 변화와 정정분만큼 다르다:
            # 기대 경계 변화 = 신월물 자신의 변화 + (신월물 기준일 정정분 − 구월물 기준일 정정분). 정정이 없으면 신월물 자신의 변화다.
            # 이 값과 다르면 정정으로 설명되지 않는 산술 오류(차단)이고, 정정이 있으면 따로 경고한다 (gap·과거 결과는 고치지 않음).
            old_revision = EXACT_DECIMAL_CONTEXT.subtract(previous.raw_price, roll.old_reference_price)
            new_revision = EXACT_DECIMAL_CONTEXT.subtract(new_reference.price, roll.new_reference_price)
            expected = EXACT_DECIMAL_CONTEXT.add(new_change, EXACT_DECIMAL_CONTEXT.subtract(new_revision, old_revision))
            if current.daily_price_change_points != expected:
                flag(ContinuousCheckName.ADJUSTMENT_ARITHMETIC, _BLOCKED, "PRICE_CHANGE_MISMATCH", label)
            if old_revision != 0 or new_revision != 0:
                flag(ContinuousCheckName.ADJUSTMENT_ARITHMETIC, _WARNING, "REFERENCE_PRICE_REVISED_AFTER_KNOWN_AT", label)

        if points:
            covered = {point.trading_date for point in points} | {item.trading_date for item in series.excluded}
            start, end = points[0].trading_date, max(covered)
            if calendar is None:
                flag(ContinuousCheckName.MISSING_SESSIONS, _NOT_ASSESSABLE, "NO_EXCHANGE_CALENDAR", "calendar")
                gaps = tuple(day for day in _weekdays(start, end) if day not in covered)
            elif not calendar.coverage_start <= start or not end <= calendar.coverage_end:
                flag(ContinuousCheckName.MISSING_SESSIONS, _NOT_ASSESSABLE, "CALENDAR_DOES_NOT_COVER_RANGE", "calendar")
            else:
                trading_days = set(calendar.dates)
                missing = tuple(day for day in calendar.dates if start <= day <= end and day not in covered)
                holidays = tuple(day for day in _weekdays(start, end) if day not in trading_days)
                for day in missing:
                    flag(ContinuousCheckName.MISSING_SESSIONS, _WARNING, "MISSING_TRADING_DATES", day.isoformat())
            if calendar is not None and calendar.provenance.verification is not VerificationLevel.CONFIRMED:
                flag(ContinuousCheckName.MISSING_SESSIONS, _WARNING, "CALENDAR_NOT_CONFIRMED", "calendar")

    checks = []
    for name in ContinuousCheckName:
        findings = tuple(
            QualityFinding(code=code, status=status, refs=tuple(sorted(refs))) for code, (status, refs) in sorted(found[name].items())
        )
        checks.append(ContinuousQualityCheck(name=name, status=worst_quality_status(item.status for item in findings), findings=findings))
    return ContinuousQualityReport(
        research_instrument_id=plan.research_instrument_id,
        roll_plan_id=plan.plan_id,
        rule_version=CONTINUOUS_QUALITY_RULE_VERSION,
        series_basis=None if series is None else series.basis,
        series_as_of=None if series is None else series.as_of,
        status=worst_quality_status(item.status for item in checks),
        checks=tuple(checks),
        overlaps=tuple(overlaps),
        roll_boundaries=tuple(boundaries),
        missing_trading_dates=missing,
        calendar_holidays=holidays,
        unverified_gaps=gaps,
        not_established=CONTINUOUS_NOT_ESTABLISHED,
    )
