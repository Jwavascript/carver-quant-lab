"""P1-02 연속 선물과 롤 (합성 fixture): 명시적 롤 계획, 롤 gap, 가산 back-adjustment, 품질·PIT 검사, 결정적 산출물
(P1-02 명세, ADR-0004 §6.4, P0-03A TC-C6·TC-C7·INV-28).

모든 가격은 **합성 값**이다. 실제 MES 정산가가 아니다. 실데이터 통합 테스트는 `test_lab_continuous_futures_real.py`에 따로 있다. 기대값(작업
명세의 108·110·112, 양수·음수 gap, 음수 조정 가격, 두 번의 롤, 1e-9 정밀도)은 저장소 밖 독립 산술(Fraction)로 먼저 확인했다. 조립(P1-01 PIT
조회 → 롤 결정 → 조정 시계열 → 품질 → 내보내기)은 테스트가 한다 (`lab.app`은 미승인). 파일은 pytest 임시 경로에만 만든다.
"""

import csv
import dataclasses
import hashlib
import io
import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from carver_quant.lab.adapters.continuous_export import ContinuousExportError, asof_series_filename, write_continuous_dataset
from carver_quant.lab.adapters.databento_statistics import ADAPTER_VERSION, STATISTICS_COLUMNS, DatabentoInstrumentMapping, parse_databento_statistics
from carver_quant.lab.adapters.raw_snapshot import load_raw_snapshot, manifest_sha256, store_raw_snapshot
from carver_quant.lab.adapters.settlement_export import write_settlement_dataset
from carver_quant.lab.domain.continuous import (
    ContinuousCheckName,
    ContinuousExclusion,
    ContinuousSeriesBasis,
    FuturesRollEvent,
    RollPlan,
    RollPlanEntry,
    UnresolvedRoll,
)
from carver_quant.lab.domain.market_data import (
    AvailabilityEvidence,
    DataOrigin,
    FuturesContractMetadata,
    PriceUnit,
    QualityStatus,
    RawSnapshotManifest,
    ReferenceProvenance,
    SettlementEvent,
    SettlementPriceType,
    SettlementRevisionStatus,
    SettlementType,
    TradingCalendarReference,
    VerificationLevel,
)
from carver_quant.lab.marketdata.quality import QUALITY_RULE_VERSION, assess_settlement_quality
from carver_quant.lab.marketdata.settlements import SELECTION_POLICY, asof_final_series, get_final_settlement_asof, latest_final_series
from carver_quant.lab.research.continuous import ALGORITHM_VERSION, build_adjusted_series, resolve_roll_event
from carver_quant.lab.research.continuous_quality import CONTINUOUS_QUALITY_RULE_VERSION, assess_continuous_series

UTC = timezone.utc
E = AvailabilityEvidence
Q = QualityStatus
FULL, ASOF = ContinuousSeriesBasis.FULL_SAMPLE, ContinuousSeriesBasis.AS_OF_CUTOFF
U6, Z6, H7, M6 = "CME.MES.2026-09", "CME.MES.2026-12", "CME.MES.2027-03", "CME.MES.2026-06"
CONTINUOUS = "CME.MES.CONTINUOUS"
INGESTED = datetime(2026, 11, 3, 9, 0, tzinfo=UTC)
SNAP = {U6: "raw-sha256-" + "a" * 64, Z6: "raw-sha256-" + "b" * 64, H7: "raw-sha256-" + "c" * 64, M6: "raw-sha256-" + "d" * 64}
D1, D2, D3 = date(2026, 9, 8), date(2026, 9, 9), date(2026, 9, 10)


def meta(contract_id, year, month, last_day, last_at):
    return FuturesContractMetadata(
        exchange="CME", product_root="MES", contract_id=contract_id, contract_year=year, contract_month=month, multiplier="5",
        outright_tick_size="0.25", outright_tick_value="1.25", settlement_tick_size=None, currency="USD", price_unit=PriceUnit.INDEX_POINT,
        last_trading_date=last_day, last_trading_at=last_at, settlement_type=SettlementType.CASH, metadata_version=f"fixture-{contract_id}/1",
        provenance=ReferenceProvenance(sources=("fixture:synthetic",), as_of=INGESTED, verification=VerificationLevel.UNVERIFIED))


META = {
    U6: meta(U6, 2026, 9, date(2026, 9, 18), datetime(2026, 9, 18, 13, 30, tzinfo=UTC)),
    Z6: meta(Z6, 2026, 12, date(2026, 12, 18), datetime(2026, 12, 18, 14, 30, tzinfo=UTC)),
    H7: meta(H7, 2027, 3, date(2027, 3, 19), datetime(2027, 3, 19, 13, 30, tzinfo=UTC)),
    M6: meta(M6, 2026, 6, date(2026, 6, 18), datetime(2026, 6, 18, 13, 30, tzinfo=UTC)),
}


def at(day, hour, minute=0, second=0):
    return datetime(day.year, day.month, day.day, hour, minute, second, tzinfo=UTC)


def settle(contract, day, price, *, recv=None, published=None, status=SettlementRevisionStatus.FINAL, seq=1, snapshot=None):
    """합성 최종(또는 잠정) 정산가 사건. 기본 수집 시각은 그 거래일 21:30Z, 거래소 시각은 수집 1ms 전."""
    recv = recv or at(day, 21, 30)
    return SettlementEvent(
        contract_id=contract, trading_date=day, price_type=SettlementPriceType.DAILY, price=Decimal(price), revision_status=status,
        actual=True, at_trading_tick=False, observed_at=None, published_at=published or recv - timedelta(milliseconds=1),
        vendor_received_at=recv, ingested_at=INGESTED, source_record_id=f"synthetic:{contract}:{day.isoformat()}:{seq}",
        source_snapshot_id=snapshot or SNAP[contract], availability_evidence=E.VENDOR_CAPTURE)


def entry(reference, first, cutoff, old=U6, new=Z6):
    return RollPlanEntry(from_contract_id=old, to_contract_id=new, roll_reference_date=reference, new_contract_first_date=first,
                         selection_policy_id="research-explicit-roll/1", evidence_cutoff_at=cutoff)


def plan_of(*entries, initial=U6, plan_id="p1-02-synthetic-plan/1", evidence=E.VENDOR_CAPTURE):
    return RollPlan(plan_id=plan_id, research_instrument_id=CONTINUOUS, initial_contract_id=initial, accepted_evidence=evidence,
                    entries=tuple(entries))


ONE_ROLL = plan_of(entry(D2, D3, at(D2, 23)))


def outcomes_for(plan, events):
    result = []
    for item in plan.entries:
        old = get_final_settlement_asof(events, item.from_contract_id, item.roll_reference_date, item.evidence_cutoff_at,
                                        accepted_evidence=plan.accepted_evidence)
        new = get_final_settlement_asof(events, item.to_contract_id, item.roll_reference_date, item.evidence_cutoff_at,
                                        accepted_evidence=plan.accepted_evidence)
        result.append(resolve_roll_event(plan, item, old_answer=old, new_answer=new))
    return tuple(result)


def inputs_at(plan, events, as_of):
    return {contract: asof_final_series(events, contract, as_of, accepted_evidence=plan.accepted_evidence) for contract in plan.contracts}


def build(plan, events, as_of, basis=FULL):
    outcomes = outcomes_for(plan, events)
    return outcomes, build_adjusted_series(plan, outcomes, inputs_at(plan, events, as_of), as_of=as_of, basis=basis)


def manifest_for(snapshot_id):
    return RawSnapshotManifest(snapshot_id=snapshot_id, data_origin=DataOrigin.SYNTHETIC, provider="databento", dataset="GLBX.MDP3",
                               schema="statistics", encoding="csv", original_filename="synthetic.csv", raw_sha256=snapshot_id[11:],
                               byte_size=1, acquired_at=INGESTED, acquisition_method="SYNTHETIC_FIXTURE", request=())


def contract_reports_for(plan, events, snapshots=SNAP):
    reports = {}
    for contract in plan.contracts:
        own = [item for item in events if item.contract_id == contract]
        days = sorted({item.trading_date for item in own}) or [D1]
        reports[contract] = assess_settlement_quality(metadata=META[contract], manifests=(manifest_for(snapshots[contract]),), events=own,
                                                      issues=(), requested_start=days[0], requested_end=days[-1], minimum_final_days=1,
                                                      calendar=None)
    return reports


def quality(plan, events, as_of, series, outcomes, *, metadata=None, calendar=None, reports=None, contract_series=None, manifests=None):
    return assess_continuous_series(plan=plan, metadata=metadata or {contract: META[contract] for contract in plan.contracts},
                                    roll_outcomes=outcomes, series=series,
                                    contract_series=contract_series or inputs_at(plan, events, as_of),
                                    contract_reports=reports or contract_reports_for(plan, events),
                                    manifests=manifests or tuple(manifest_for(SNAP[contract]) for contract in plan.contracts), calendar=calendar)


def check(report, name):
    return next(item for item in report.checks if item.name is ContinuousCheckName[name])


def view(series):
    return [(p.trading_date, p.selected_contract_id, p.raw_price, p.cumulative_adjustment_points, p.adjusted_price, p.daily_price_change_points)
            for p in series.points]


EXAMPLE = [settle(U6, D1, "100"), settle(U6, D2, "102"), settle(Z6, D1, "108"), settle(Z6, D2, "110"), settle(Z6, D3, "112")]
END = at(date(2026, 9, 11), 0)


def test_task_example_back_adjustment_matches_the_hand_calculation():
    """작업 명세 §5 (요구 1·2·4·5). 입력: 9월물 100(Day 1), 102(Day 2, 롤 기준일), 12월물 108, 110(기준일), 112(Day 3, 신월물 첫 거래일).
    두 기준일 최종가가 모두 보인 뒤(23:00Z)를 known_at으로 둔 계획.
    출력: gap = 102 − 110 = −8. 조정 가격 108, 110, 112, 누적 조정 −8, −8, 0, 일별 변화 +2, +2 (모두 정확한 Decimal). 단순 연결(raw)은 Day 2 →
    Day 3에서 +10이지만 그중 8 point는 월물 교체로 생긴 가짜 점프다. 기준일의 조정 가격은 신월물 기준가(110)와 같고, 각 변화는 원래 월물 자신의
    raw 변화와 같다 (롤 경계는 12월물의 110 → 112)."""
    outcomes, series = build(ONE_ROLL, EXAMPLE, END)
    (roll,) = outcomes
    assert (type(roll), roll.roll_gap_points, roll.old_reference_price, roll.new_reference_price) == (
        FuturesRollEvent, Decimal("-8"), Decimal("102"), Decimal("110"))
    assert view(series) == [
        (D1, U6, Decimal("100"), Decimal("-8"), Decimal("108"), None),
        (D2, U6, Decimal("102"), Decimal("-8"), Decimal("110"), Decimal("2")),
        (D3, Z6, Decimal("112"), Decimal("0"), Decimal("112"), Decimal("2"))]
    assert series.points[1].adjusted_price == roll.new_reference_price
    report = quality(ONE_ROLL, EXAMPLE, END, series, outcomes)
    (boundary,) = report.roll_boundaries
    assert (boundary.naive_raw_change_points, boundary.new_contract_change_points, boundary.adjusted_change_points, boundary.spurious_jump_points) == (
        Decimal("10"), Decimal("2"), Decimal("2"), Decimal("8"))
    assert check(report, "ADJUSTMENT_ARITHMETIC").status is Q.PASSED
    assert (series.basis, series.algorithm_version, series.method.value) == (FULL, ALGORITHM_VERSION, "FUTURES_ADDITIVE_BACK_ADJUSTED")
    # 9월물은 실제로 Day 3에도 정산되지만, 신월물 첫 거래일부터는 선택하지 않으므로 시계열이 바뀌지 않는다.
    assert build(ONE_ROLL, [*EXAMPLE, settle(U6, D3, "104")], END)[1] == series


def test_positive_gap_negative_adjusted_prices_and_decimal_precision():
    """요구 3·6·7. 입력: (a) 신월물이 더 낮음: 9월물 100, 102 / 12월물 95, 97, 99. (b) 9월물 5, 12 / 12월물 2(기준일), 3. (c) 1e-9 정밀도:
    9월물 7543.250000000, 7551.500000000 / 12월물 7590.750000000(기준일), 7601.000000001.
    출력: (a) gap +5, 조정 95, 97, 99, 변화 +2, +2. (b) gap +10, 조정 −5, 2, 3 (음수 조정 가격도 정상 값), 변화 +7, +1. (c) gap −39.250000000,
    조정 7582.500000000, 7590.750000000, 7601.000000001, 롤 경계 변화 10.250000001 — 원래 소수 자릿수를 그대로 유지한다."""
    _, positive = build(ONE_ROLL, [settle(U6, D1, "100"), settle(U6, D2, "102"), settle(Z6, D2, "97"), settle(Z6, D3, "99")], END)
    assert [(p.adjusted_price, p.daily_price_change_points) for p in positive.points] == [
        (Decimal("95"), None), (Decimal("97"), Decimal("2")), (Decimal("99"), Decimal("2"))]
    assert positive.applied_rolls[0].roll_gap_points == Decimal("5")

    _, negative = build(ONE_ROLL, [settle(U6, D1, "5"), settle(U6, D2, "12"), settle(Z6, D2, "2"), settle(Z6, D3, "3")], END)
    assert [(p.adjusted_price, p.daily_price_change_points) for p in negative.points] == [
        (Decimal("-5"), None), (Decimal("2"), Decimal("7")), (Decimal("3"), Decimal("1"))]

    events = [settle(U6, D1, "7543.250000000"), settle(U6, D2, "7551.500000000"), settle(Z6, D2, "7590.750000000"),
              settle(Z6, D3, "7601.000000001")]
    outcomes, precise = build(ONE_ROLL, events, END)
    assert str(outcomes[0].roll_gap_points) == "-39.250000000"
    assert [str(p.adjusted_price) for p in precise.points] == ["7582.500000000", "7590.750000000", "7601.000000001"]
    assert str(precise.points[2].daily_price_change_points) == "10.250000001"
    assert check(quality(ONE_ROLL, events, END, precise, outcomes), "DECIMAL_PRECISION").status is Q.PASSED


def test_two_consecutive_rolls_accumulate_adjustments():
    """요구 8. 입력: 9월물 100, 101(롤 1 기준일) / 12월물 110(롤 1), 111, 112(롤 2 기준일) / 3월물 120(롤 2), 121.
    출력: gap −9, −8. 누적 조정 −17, −17, −8, −8, 0, 조정 가격 117, 118, 119, 120, 121, 일별 변화 모두 +1."""
    d4, d5 = date(2026, 9, 11), date(2026, 9, 14)
    plan = plan_of(entry(D2, D3, at(D2, 23)), entry(d4, d5, at(d4, 23), old=Z6, new=H7))
    events = [settle(U6, D1, "100"), settle(U6, D2, "101"), settle(Z6, D2, "110"), settle(Z6, D3, "111"), settle(Z6, d4, "112"),
              settle(H7, d4, "120"), settle(H7, d5, "121")]
    outcomes, series = build(plan, events, at(date(2026, 9, 15), 0))
    assert [roll.roll_gap_points for roll in outcomes] == [Decimal("-9"), Decimal("-8")]
    assert [(p.selected_contract_id, p.cumulative_adjustment_points, p.adjusted_price) for p in series.points] == [
        (U6, Decimal("-17"), Decimal("117")), (U6, Decimal("-17"), Decimal("118")), (Z6, Decimal("-8"), Decimal("119")),
        (Z6, Decimal("-8"), Decimal("120")), (H7, Decimal("0"), Decimal("121"))]
    assert [p.daily_price_change_points for p in series.points[1:]] == [Decimal("1")] * 4


def test_plans_reject_duplicate_and_conflicting_rolls_and_inputs_must_match_the_plan():
    """요구 9·13. 입력: 같은 롤 두 번, 같은 기준일에 다른 신월물, 앞 롤의 신월물 첫 거래일 전에 기준일이 오는 다음 롤, 연구용 ID = 월물 ID,
    다른 월물 Series를 넣은 입력, 월물 하나가 빠진 입력, 메타데이터의 월물 ID가 계획과 다름.
    출력: 계획·입력 모순은 ValueError (중복·상충 롤은 계획으로 만들 수 없음). 메타데이터 불일치는 CONTRACT_IDENTITY BLOCKED."""
    first = entry(D2, D3, at(D2, 23))
    for entries in ((first, first), (first, entry(D2, D3, at(D2, 23), new=H7)), (first, entry(D2, D3, at(D2, 23), old=Z6, new=H7))):
        with pytest.raises(ValueError):
            plan_of(*entries)
    with pytest.raises(ValueError):
        RollPlan(plan_id="p", research_instrument_id=U6, initial_contract_id=U6, accepted_evidence=E.VENDOR_CAPTURE, entries=(first,))
    outcomes = outcomes_for(ONE_ROLL, EXAMPLE)
    inputs = inputs_at(ONE_ROLL, EXAMPLE, END)
    for broken in ({U6: inputs[Z6], Z6: inputs[Z6]}, {U6: inputs[U6]}):
        with pytest.raises(ValueError):
            build_adjusted_series(ONE_ROLL, outcomes, broken, as_of=END, basis=FULL)
    series = build_adjusted_series(ONE_ROLL, outcomes, inputs, as_of=END, basis=FULL)
    report = quality(ONE_ROLL, EXAMPLE, END, series, outcomes, metadata={U6: META[U6], Z6: META[H7]})
    assert check(report, "CONTRACT_IDENTITY").status is Q.BLOCKED and "METADATA_CONTRACT_MISMATCH" in check(report, "CONTRACT_IDENTITY").reasons


def test_roll_order_and_expiry_are_checked_against_contract_metadata():
    """요구 10·11. 입력: (a) 9월물 → 6월물(먼저 만기)로 가는 계획, (b) 9월물 마지막 거래일(9-18) 뒤인 9-21을 신월물 첫 거래일로 둔 계획과,
    그 때문에 만기 뒤 날짜(9-21 이전 구간)에 9월물 점이 선택되는 합성 데이터.
    출력: (a) ROLL_ORDER BLOCKED (NEW_CONTRACT_EXPIRES_FIRST). (b) ROLL_ORDER BLOCKED (ROLL_AFTER_OLD_EXPIRY)이고, 만기 뒤의 9월물 점은 EXPIRY
    BLOCKED (SELECTED_AFTER_LAST_TRADING_DATE)."""
    backwards = plan_of(entry(D2, D3, at(D2, 23), new=M6))
    events = [settle(U6, D1, "100"), settle(U6, D2, "102"), settle(M6, D2, "99"), settle(M6, D3, "100")]
    outcomes, series = build(backwards, events, END)
    assert check(quality(backwards, events, END, series, outcomes), "ROLL_ORDER").reasons == ("NEW_CONTRACT_EXPIRES_FIRST",)

    reference, first = date(2026, 9, 17), date(2026, 9, 22)
    late = plan_of(entry(reference, first, at(reference, 23)))
    events = [settle(U6, reference, "100"), settle(U6, date(2026, 9, 21), "101"), settle(Z6, reference, "105"), settle(Z6, first, "106")]
    end = at(date(2026, 9, 23), 0)
    outcomes, series = build(late, events, end)
    report = quality(late, events, end, series, outcomes)
    assert check(report, "ROLL_ORDER").reasons == ("ROLL_AFTER_OLD_EXPIRY",)
    assert check(report, "EXPIRY").reasons == ("SELECTED_AFTER_LAST_TRADING_DATE",)
    assert report.status is Q.BLOCKED


def test_missing_reference_price_blocks_the_roll_and_nothing_is_estimated():
    """요구 12. 입력: 기준일(Day 2)에 12월물 최종가가 없음.
    출력: 롤은 UnresolvedRoll (NEW_REFERENCE_NOT_AVAILABLE)이며 gap을 추정하지 않는다. Full-sample 시계열은 만들 수 없다 (ValueError). 품질
    보고서는 REFERENCE_PRICES BLOCKED이고 시계열이 필요한 검사는 NOT_ASSESSABLE이다."""
    events = [settle(U6, D1, "100"), settle(U6, D2, "102"), settle(Z6, D1, "108"), settle(Z6, D3, "112")]
    outcomes = outcomes_for(ONE_ROLL, events)
    assert type(outcomes[0]) is UnresolvedRoll and outcomes[0].reasons[0] == "NEW_REFERENCE_NOT_AVAILABLE"
    for cutoff, basis in ((END, FULL), (at(D2, 23, 30), ASOF)):
        with pytest.raises(ValueError):
            build_adjusted_series(ONE_ROLL, outcomes, inputs_at(ONE_ROLL, events, cutoff), as_of=cutoff, basis=basis)
    report = quality(ONE_ROLL, events, END, None, outcomes)
    assert (check(report, "REFERENCE_PRICES").status, check(report, "ADJUSTMENT_ARITHMETIC").status, report.series_basis) == (
        Q.BLOCKED, Q.NOT_ASSESSABLE, None)
    assert check(report, "OVERLAP").reasons == ("REFERENCE_DATE_NOT_IN_OVERLAP",)
    # known_at 전의 As-of 보고서는 아직 알려지지 않은 그 롤을 판정하지 않는다 (뒤의 정보로 판정이 바뀌지 않음).
    early = at(D2, 22)
    series = build_adjusted_series(ONE_ROLL, outcomes, inputs_at(ONE_ROLL, events, early), as_of=early, basis=ASOF)
    assert check(quality(ONE_ROLL, events, early, series, outcomes), "REFERENCE_PRICES").status is Q.PASSED


def test_missing_trading_dates_are_separated_from_calendar_holidays():
    """요구 14. 입력: 9월물 9-03, 9-04, 9-09(기준일) 최종가, 12월물 9-09, 9-10. 합성 달력은 9월 평일 가운데 9-07(휴장)을 뺀 날이다 (9-08은
    거래일인데 데이터가 없음).
    출력: 달력이 있으면 결측 거래일은 9-08 하나 (MISSING_SESSIONS WARNING), 9-07은 휴장일로 따로 보고하고 결측으로 세지 않는다. 달력이 없으면
    NOT_ASSESSABLE이고 9-07, 9-08은 휴장인지 결측인지 모르는 미확인 공백으로만 보고한다. 빠진 날을 채우지 않는다."""
    days = [date(2026, 9, 3), date(2026, 9, 4), D2]
    events = [settle(U6, day, "100") for day in days] + [settle(Z6, D2, "105"), settle(Z6, D3, "106")]
    outcomes, series = build(ONE_ROLL, events, END)
    september = [date(2026, 9, day) for day in range(1, 31) if date(2026, 9, day).weekday() < 5 and day != 7]
    calendar = TradingCalendarReference(exchange="CME", coverage_start=date(2026, 9, 1), coverage_end=date(2026, 9, 30), dates=tuple(september),
                                        provenance=ReferenceProvenance(sources=("fixture:synthetic-calendar",), as_of=INGESTED,
                                                                       verification=VerificationLevel.UNVERIFIED))
    known = quality(ONE_ROLL, events, END, series, outcomes, calendar=calendar)
    assert (known.missing_trading_dates, known.calendar_holidays) == ((date(2026, 9, 8),), (date(2026, 9, 7),))
    assert check(known, "MISSING_SESSIONS").reasons == ("CALENDAR_NOT_CONFIRMED", "MISSING_TRADING_DATES")
    blind = quality(ONE_ROLL, events, END, series, outcomes)
    assert (check(blind, "MISSING_SESSIONS").status, blind.unverified_gaps) == (Q.NOT_ASSESSABLE, (date(2026, 9, 7), date(2026, 9, 8)))
    assert [p.trading_date for p in series.points] == [*days, D3]


def test_roll_is_not_used_before_its_known_at_and_future_data_do_not_change_past_snapshots():
    """요구 15·16. 입력: 작업 명세 예의 자료와 계획 (known_at Day 2 23:00Z). As-of cutoff 22:00Z(두 기준가는 21:30Z에 보였지만 롤은 아직 모름),
    23:00Z, Day 3 22:00Z. 같은 cutoff의 시계열을 cutoff 뒤 기록까지 포함한 자료와 cutoff까지 보인 기록만 남긴 자료로 각각 만든다.
    출력: 22:00Z에는 롤을 적용하지 않아 raw 그대로(100, 102, 누적 0)이고 12월물을 선택하지 않는다. 23:00Z에는 롤을 적용해 108, 110이며 Day 3는
    아직 없다. Day 3 22:00Z에는 112까지 있다. 미래 기록을 더해도 과거 cutoff의 시계열은 같다."""
    early = at(D2, 22)
    _, before = build(ONE_ROLL, EXAMPLE, early, ASOF)
    assert (before.applied_rolls, view(before)) == ((), [(D1, U6, Decimal("100"), Decimal("0"), Decimal("100"), None),
                                                          (D2, U6, Decimal("102"), Decimal("0"), Decimal("102"), Decimal("2"))])
    _, known = build(ONE_ROLL, EXAMPLE, at(D2, 23), ASOF)
    assert [p.adjusted_price for p in known.points] == [Decimal("108"), Decimal("110")]
    _, later = build(ONE_ROLL, EXAMPLE, at(D3, 22), ASOF)
    assert [p.adjusted_price for p in later.points] == [Decimal("108"), Decimal("110"), Decimal("112")]
    for cutoff in (early, at(D2, 23)):
        visible = [item for item in EXAMPLE if item.vendor_received_at <= cutoff]
        assert build(ONE_ROLL, EXAMPLE, cutoff, ASOF)[1] == build(ONE_ROLL, visible, cutoff, ASOF)[1]
    with pytest.raises(ValueError):
        build(ONE_ROLL, EXAMPLE, early, FULL)


def test_corrections_after_known_at_are_not_applied_retroactively():
    """요구 17. 입력: (a) 12월물 기준일 최종가가 known_at 뒤(Day 3 09:00Z)에 110 → 111로 정정, (b) 9월물 기준일 최종가가 known_at 뒤에 102 → 103으로 정정.
    출력: 두 경우 모두 롤 gap은 known_at에 보인 값으로 −8 그대로다. (a) 시계열은 정정이 없을 때와 같지만 (12월물 기준일 가격은 점이 아님),
    정정된 입력에서 본 12월물 자신의 변화(1)와 경계 변화(2)가 달라 REFERENCE_PRICE_REVISED_AFTER_KNOWN_AT 경고가 남는다. (b) 정정 전 cutoff의
    시계열은 102를 쓰고, 정정 뒤 Full-sample은 raw 103을 쓰므로 롤 경계 변화가 1 point 어긋나며 같은 경고가 남는다 (조용히 고치지 않음)."""
    correction = at(D3, 9)
    new_side = [*EXAMPLE, settle(Z6, D2, "111", recv=correction, seq=2)]
    outcomes, series = build(ONE_ROLL, new_side, END)
    assert outcomes[0].roll_gap_points == Decimal("-8") and view(series) == view(build(ONE_ROLL, EXAMPLE, END)[1])
    # 신월물 쪽 정정도 드러난다: 같은 as_of 입력에서 본 12월물 자신의 변화는 112 − 111 = 1인데 조정 시계열의 경계 변화는 2다.
    revised = quality(ONE_ROLL, new_side, END, series, outcomes)
    assert check(revised, "ADJUSTMENT_ARITHMETIC").reasons == ("REFERENCE_PRICE_REVISED_AFTER_KNOWN_AT",)
    assert (revised.roll_boundaries[0].new_contract_change_points, revised.roll_boundaries[0].adjusted_change_points) == (Decimal("1"), Decimal("2"))

    old_side = [*EXAMPLE, settle(U6, D2, "103", recv=correction, seq=2)]
    outcomes, series = build(ONE_ROLL, old_side, END)
    assert (outcomes[0].old_reference_price, outcomes[0].roll_gap_points) == (Decimal("102"), Decimal("-8"))
    assert [p.raw_price for p in build(ONE_ROLL, old_side, at(D3, 8), ASOF)[1].points] == [Decimal("100"), Decimal("102")]
    assert [p.adjusted_price for p in series.points] == [Decimal("108"), Decimal("111"), Decimal("112")]
    arithmetic = check(quality(ONE_ROLL, old_side, END, series, outcomes), "ADJUSTMENT_ARITHMETIC")
    assert (arithmetic.status, arithmetic.reasons) == (Q.WARNING, ("REFERENCE_PRICE_REVISED_AFTER_KNOWN_AT",))


def test_revised_reference_prices_are_explained_and_unexplained_mismatches_still_block():
    """M1 (P1-02C). 입력: 작업 명세 예(gap −8, 기준일 Day 2)에 known_at 뒤 정정 — 구월물만 102 → 103, 신월물만 110 → 111, 양쪽 모두 —
    과 정정과 별개로 롤 경계 변화가 틀린 시계열(검증을 거치지 않은 손상 데이터를 흉내 냄. 정상 빌더는 도메인 불변조건 때문에 만들 수 없다).
    출력 (저장소 밖 Fraction 손계산과 같음): 기대 경계 변화 = 신월물 자신의 변화 + 신월물 정정분 − 구월물 정정분.
    구월물만: 2 + 0 − 1 = 1, 신월물만: 1 + 1 − 0 = 2, 양쪽: 1 + 1 − 1 = 1. 시계열 변화와 같으므로 경고(REFERENCE_PRICE_REVISED_AFTER_KNOWN_AT)만
    남고, gap은 −8 그대로이며 정정 전 cutoff의 시계열은 바뀌지 않는다. 경계 변화가 3인 손상 시계열은 정정이 있어도(기대 2) 차단
    (PRICE_CHANGE_MISMATCH)되고, 정정이 없어도(기대 2) 차단된다."""
    correction, before = at(D3, 9), at(D3, 8)
    cases = {
        "old": ([settle(U6, D2, "103", recv=correction, seq=2)], Decimal("1"), Decimal("2")),
        "new": ([settle(Z6, D2, "111", recv=correction, seq=2)], Decimal("2"), Decimal("1")),
        "both": ([settle(U6, D2, "103", recv=correction, seq=2), settle(Z6, D2, "111", recv=correction, seq=2)], Decimal("1"), Decimal("1")),
    }
    past = build(ONE_ROLL, EXAMPLE, before, ASOF)[1]
    for name, (revisions, boundary_change, own_change) in cases.items():
        events = [*EXAMPLE, *revisions]
        outcomes, series = build(ONE_ROLL, events, END)
        assert outcomes[0].roll_gap_points == Decimal("-8") and outcomes[0].old_reference_price == Decimal("102"), name
        assert build(ONE_ROLL, events, before, ASOF)[1] == past, name
        report = quality(ONE_ROLL, events, END, series, outcomes)
        (boundary,) = report.roll_boundaries
        assert (boundary.adjusted_change_points, boundary.new_contract_change_points) == (boundary_change, own_change), name
        arithmetic = check(report, "ADJUSTMENT_ARITHMETIC")
        assert (arithmetic.status, arithmetic.reasons) == (Q.WARNING, ("REFERENCE_PRICE_REVISED_AFTER_KNOWN_AT",)), name

    for events, reasons in (([*EXAMPLE, *cases["new"][0]], ("PRICE_CHANGE_MISMATCH", "REFERENCE_PRICE_REVISED_AFTER_KNOWN_AT")),
                            (EXAMPLE, ("PRICE_CHANGE_MISMATCH",))):
        outcomes, series = build(ONE_ROLL, events, END)
        object.__setattr__(series.points[-1], "daily_price_change_points", Decimal("3"))  # 손상된 경계 변화 (불변조건 우회)
        arithmetic = check(quality(ONE_ROLL, events, END, series, outcomes), "ADJUSTMENT_ARITHMETIC")
        assert (arithmetic.status, arithmetic.reasons) == (Q.BLOCKED, reasons)


def test_trading_dates_between_reference_and_first_new_date_before_and_after_the_roll_is_known():
    """M2 (P1-02C). 입력: 기준일 R = Day 1, 신월물 첫 거래일 N = Day 3 (사이에 Day 2), known_at = Day 3 23:00Z. 9월물 100, 102, 104, 12월물 108,
    110, 112. 출력: (a) Day 2 22:00Z — 롤 미적용, 9월물 Day 1·2를 조정 없이 선택, 제외 없음. (b) Day 3 22:00Z — 여전히 미적용, Day 3 9월물은
    ROLL_NOT_YET_KNOWN 제외. (c) known_at — 롤 적용(gap 100 − 108 = −8), 9월물 Day 1(조정 108)과 12월물 Day 3(112)만 선택, 9월물 Day 2는
    AFTER_ROLL_REFERENCE_DATE 제외(12월물 Day 2로 대신하지 않음), 경계 변화 +4 = 12월물 자신의 R → N 변화. 앞 cutoff의 결과는 바뀌지 않는다."""
    plan = plan_of(entry(D1, D3, at(D3, 23)))
    events = [*EXAMPLE, settle(U6, D3, "104")]
    cutoffs = (at(D2, 22), at(D3, 22), at(D3, 23))
    built = {}
    for cutoff in cutoffs:
        outcomes, series = build(plan, events, cutoff, ASOF)
        visible = [item for item in events if item.vendor_received_at <= cutoff]
        assert series == build(plan, visible, cutoff, ASOF)[1]
        built[cutoff] = (outcomes, series)
    (_, early), (_, pending), (outcomes, known) = (built[cutoff] for cutoff in cutoffs)
    assert (early.applied_rolls, early.excluded) == ((), ())
    assert view(early) == [(D1, U6, Decimal("100"), Decimal("0"), Decimal("100"), None),
                           (D2, U6, Decimal("102"), Decimal("0"), Decimal("102"), Decimal("2"))]
    assert pending.applied_rolls == () and view(pending) == view(early)
    assert [(x.trading_date, x.selected_contract_id, x.reasons) for x in pending.excluded] == [(D3, U6, ("ROLL_NOT_YET_KNOWN",))]
    assert check(quality(plan, events, cutoffs[1], pending, outcomes), "SELECTION_COVERAGE").reasons == ("ROLL_NOT_YET_KNOWN",)

    assert outcomes[0].roll_gap_points == Decimal("-8") and len(known.applied_rolls) == 1
    assert view(known) == [(D1, U6, Decimal("100"), Decimal("-8"), Decimal("108"), None),
                           (D3, Z6, Decimal("112"), Decimal("0"), Decimal("112"), Decimal("4"))]
    assert [(x.trading_date, x.selected_contract_id, x.reasons) for x in known.excluded] == [(D2, U6, ("AFTER_ROLL_REFERENCE_DATE",))]
    report = quality(plan, events, cutoffs[2], known, outcomes)
    assert check(report, "SELECTION_COVERAGE").reasons == ("AFTER_ROLL_REFERENCE_DATE",)
    assert (check(report, "ADJUSTMENT_ARITHMETIC").status, report.roll_boundaries[0].new_contract_change_points) == (Q.PASSED, Decimal("4"))


def test_exchange_time_does_not_make_a_reference_price_available_early():
    """요구 18. 입력: 12월물 기준일 최종가의 거래소 시각(ts_event)은 21:00Z, 공급자 수집 시각(ts_recv)은 23:30Z. 롤 known_at은 23:00Z.
    출력: 연구용 근거(VENDOR_CAPTURE_PROXY, ts_recv)로는 known_at에 그 가격이 보이지 않아 롤이 해결되지 않는다 (ts_event로 앞당기지 않음).
    거래소 시각을 근거로 받아들이는 계획이었다면 보였을 것이므로, 차이는 근거 수준에서만 온다. 그때 두 기준가가 모두 보인 시각은 둘 중 늦은
    9월물 거래소 시각(21:29:59.999Z)이다."""
    events = [settle(U6, D1, "100"), settle(U6, D2, "102"), settle(Z6, D2, "110", recv=at(D2, 23, 30), published=at(D2, 21)),
              settle(Z6, D3, "112")]
    (vendor,) = outcomes_for(ONE_ROLL, events)
    assert type(vendor) is UnresolvedRoll and vendor.reasons[0] == "NEW_REFERENCE_NOT_AVAILABLE"
    exchange_plan = plan_of(entry(D2, D3, at(D2, 23)), evidence=E.EXCHANGE_PUBLICATION)
    (exchange,) = outcomes_for(exchange_plan, events)
    assert type(exchange) is FuturesRollEvent and exchange.reference_prices_available_at == at(D2, 21, 30) - timedelta(milliseconds=1)


def test_friday_final_captured_on_sunday_is_not_used_on_friday():
    """요구 19. 입력: 기준일 목요일 9-10, 신월물 첫 거래일 금요일 9-11. 12월물 금요일 잠정가는 금요일 20:05Z, 최종가는 일요일 9-13 11:35Z에 수집.
    출력: 금요일 23:59:59Z 시계열에는 롤이 적용되었지만 금요일 점이 없고 (12월물 금요일은 잠정가만 있어 제외), 일요일 12:00Z에는 금요일 점이 있다."""
    thursday, friday, sunday = D3, date(2026, 9, 11), date(2026, 9, 13)
    plan = plan_of(entry(thursday, friday, at(thursday, 23)))
    events = [settle(U6, D2, "100"), settle(U6, thursday, "102"), settle(Z6, thursday, "110"),
              settle(Z6, friday, "112", recv=at(friday, 20, 5), status=SettlementRevisionStatus.PRELIMINARY, seq=1),
              settle(Z6, friday, "112", recv=at(sunday, 11, 35), seq=2)]
    _, friday_night = build(plan, events, at(friday, 23, 59, 59), ASOF)
    assert [p.trading_date for p in friday_night.points] == [D2, thursday] and len(friday_night.applied_rolls) == 1
    assert [(x.trading_date, x.selected_contract_id, x.reasons) for x in friday_night.excluded] == [(friday, Z6, ("NOT_AVAILABLE", "PRELIMINARY_ONLY"))]
    _, sunday_noon = build(plan, events, at(sunday, 12), ASOF)
    assert [(p.trading_date, p.adjusted_price, p.available_at) for p in sunday_noon.points][-1] == (friday, Decimal("112"), at(sunday, 11, 35))


def test_old_contract_points_between_reference_and_first_new_date_are_excluded():
    """롤 경계 연속성. 입력: 기준일 Day 1, 신월물 첫 거래일 Day 3인 계획에서 9월물 Day 2 최종가가 있음.
    출력: Day 2의 9월물 점은 기준일과 gap 기준이 달라 제외(AFTER_ROLL_REFERENCE_DATE, SELECTION_COVERAGE 경고)되고, 경계 변화는 12월물의
    기준일 → 첫 거래일 변화와 같다."""
    plan = plan_of(entry(D1, D3, at(D1, 23)))
    outcomes, series = build(plan, EXAMPLE, END)
    assert [p.trading_date for p in series.points] == [D1, D3]
    assert [(x.trading_date, x.reasons) for x in series.excluded] == [(D2, ("AFTER_ROLL_REFERENCE_DATE",))]
    assert series.points[1].daily_price_change_points == Decimal("112") - Decimal("108")
    report = quality(plan, EXAMPLE, END, series, outcomes)
    assert (check(report, "SELECTION_COVERAGE").reasons, check(report, "ADJUSTMENT_ARITHMETIC").status) == (("AFTER_ROLL_REFERENCE_DATE",), Q.PASSED)


def test_reference_answers_must_be_the_rolls_own_pit_queries():
    """롤 기준가 입력 검증. 입력: 롤 항목과 맞지 않는 PIT 조회 결과 (다른 월물, 다른 거래일, 다른 cutoff, 다른 근거)와 계획에 없는 항목.
    출력: 모두 ValueError (다른 날짜·시각의 가격으로 gap을 만들지 않음)."""
    item = ONE_ROLL.entries[0]

    def answer(contract, day=D2, cutoff=item.evidence_cutoff_at, evidence=E.VENDOR_CAPTURE):
        return get_final_settlement_asof(EXAMPLE, contract, day, cutoff, accepted_evidence=evidence)

    for old, new in ((answer(Z6), answer(Z6)), (answer(U6, day=D1), answer(Z6)), (answer(U6), answer(Z6, day=D1)),
                     (answer(U6, cutoff=at(D2, 23, 30)), answer(Z6)), (answer(U6), answer(Z6, evidence=E.EXCHANGE_PUBLICATION))):
        with pytest.raises(ValueError):
            resolve_roll_event(ONE_ROLL, item, old_answer=old, new_answer=new)
    with pytest.raises(ValueError):
        resolve_roll_event(ONE_ROLL, entry(D1, D2, at(D1, 23)), old_answer=answer(U6, day=D1, cutoff=at(D1, 23)),
                           new_answer=answer(Z6, day=D1, cutoff=at(D1, 23)))


def test_dates_after_a_roll_not_yet_known_are_reported_not_dropped():
    """아직 알려지지 않은 롤. 입력: known_at이 Day 3 23:00Z인 계획, Day 3 22:00Z cutoff, 9월물 Day 3 최종가(21:30Z에 보임).
    출력: 롤을 적용하지 않고 Day 3부터 어느 월물도 선택하지 않으며, 보인 9월물 Day 3 기록은 ROLL_NOT_YET_KNOWN 제외로 남는다 (조용히 버리지
    않음). 품질 검사는 SELECTION_COVERAGE 경고로 보고한다."""
    plan = plan_of(entry(D2, D3, at(D3, 23)))
    events = [*EXAMPLE, settle(U6, D3, "104")]
    cutoff = at(D3, 22)
    outcomes, series = build(plan, events, cutoff, ASOF)
    assert (series.applied_rolls, [p.trading_date for p in series.points]) == ((), [D1, D2])
    assert [(x.trading_date, x.selected_contract_id, x.reasons) for x in series.excluded] == [(D3, U6, ("ROLL_NOT_YET_KNOWN",))]
    assert check(quality(plan, events, cutoff, series, outcomes), "SELECTION_COVERAGE").reasons == ("ROLL_NOT_YET_KNOWN",)


def test_quality_gate_rejects_series_that_do_not_follow_the_plan_and_flags_missing_rolls():
    """품질 검사 입력 연결. 입력: (a) 처음 월물이 다른 계획으로 만든 시계열, (b) 거래소 시각 근거로 만든 시계열, (c) 시계열이 쓴 Snapshot을 덮지
    않는 월물 보고서, (d) 시계열과 다른 cutoff의 월물 입력, (e) known_at 뒤의 as_of를 갖지만 롤을 적용하지 않은 시계열.
    출력: (a)~(d)는 ValueError (계획과 맞지 않는 시계열을 통과시키지 않음). (e)는 PIT BLOCKED (KNOWN_ROLL_NOT_APPLIED)."""
    outcomes = outcomes_for(ONE_ROLL, EXAMPLE)
    other_start = build(plan_of(initial=Z6), EXAMPLE, END)[1]
    exchange = build(plan_of(entry(D2, D3, at(D2, 23)), evidence=E.EXCHANGE_PUBLICATION), EXAMPLE, END)[1]
    full = build(ONE_ROLL, EXAMPLE, END)[1]
    stranger = {**SNAP, U6: "raw-sha256-" + "e" * 64}
    cases = [dict(series=other_start), dict(series=exchange), dict(series=full, reports=contract_reports_for(ONE_ROLL, EXAMPLE, stranger)),
             dict(series=full, contract_series=inputs_at(ONE_ROLL, EXAMPLE, at(D2, 23)))]
    for case in cases:
        with pytest.raises(ValueError):
            quality(ONE_ROLL, EXAMPLE, END, case["series"], outcomes, reports=case.get("reports"), contract_series=case.get("contract_series"))
    stale = dataclasses.replace(build(ONE_ROLL, EXAMPLE, at(D2, 22), ASOF)[1], as_of=at(D2, 23, 30))
    pit = check(quality(ONE_ROLL, EXAMPLE, at(D2, 23, 30), stale, outcomes), "PIT")
    assert (pit.status, pit.reasons) == (Q.BLOCKED, ("KNOWN_ROLL_NOT_APPLIED",))


def test_domain_rejects_cyclic_unordered_and_discontinuous_series():
    """도메인 불변조건 (각 경우는 그 규칙 하나만 어기도록 만든다). 입력: (a) 9월물 → 12월물 → 9월물로 돌아오는 적용 롤, (b) 앞 롤의 신월물 첫
    거래일 전에 기준일이 오는 다음 롤, (c) 롤 기준일과 신월물 첫 거래일 사이의 구월물 점, (d) 기준일 UTC 자정 전의 known_at, (e) as_of 뒤에
    보인 점 (롤 없음).
    출력: 모두 ValueError."""
    outcomes, full = build(ONE_ROLL, EXAMPLE, END)
    roll = outcomes[0]
    flat = dict(old_reference_price=Decimal("1"), new_reference_price=Decimal("1"), roll_gap_points=Decimal("0"))
    back = dataclasses.replace(roll, from_contract_id=Z6, to_contract_id=U6, roll_reference_date=D3, new_contract_first_date=date(2026, 9, 11),
                               evidence_cutoff_at=at(D3, 23), reference_prices_available_at=at(D3, 22), **flat)
    early = dataclasses.replace(roll, from_contract_id=Z6, to_contract_id=H7, roll_reference_date=D1, new_contract_first_date=D2, **flat)
    later = at(date(2026, 9, 12), 0)
    wide_plan = plan_of(entry(D1, D3, at(D1, 23)))
    wide_roll, wide = build(wide_plan, EXAMPLE, END)
    first, last = wide.points
    middle = dataclasses.replace(first, trading_date=D2, raw_price=Decimal("102"), adjusted_price=Decimal("110"),
                                 daily_price_change_points=Decimal("2"), change_from_trading_date=D1, source_record_id="synthetic:middle",
                                 available_at=at(D2, 21, 30))
    contradictions = [
        lambda: dataclasses.replace(full, as_of=later, applied_rolls=(roll, back), points=(), excluded=()),
        lambda: dataclasses.replace(full, as_of=later, applied_rolls=(roll, early), points=(), excluded=()),
        lambda: dataclasses.replace(wide, excluded=(), points=(first, middle, dataclasses.replace(
            last, daily_price_change_points=Decimal("2"), change_from_trading_date=D2))),
        lambda: dataclasses.replace(roll, evidence_cutoff_at=at(D1, 23), reference_prices_available_at=at(D1, 22)),
        lambda: dataclasses.replace(build(ONE_ROLL, EXAMPLE, at(D2, 22), ASOF)[1], as_of=at(D2, 21)),
    ]
    assert wide_roll[0].roll_gap_points == Decimal("-8")
    for make in contradictions:
        with pytest.raises(ValueError):
            make()


def test_builder_and_types_reject_inputs_that_break_the_pit_contract():
    """입력·도메인 방어 (각 경우는 규칙 하나만 어긴다). 입력: (a) as_of와 다른 cutoff의 월물 입력, (b) 거래소 시각 근거의 월물 입력, (c) 다른
    근거로 정한 롤 결과, (d) 다른 계획 항목의 롤 결과, (e) 받아들인 근거보다 약한 근거로 보인 점, (f) 다른 근거의 적용 롤, (g) 조정 가격 ≠ raw −
    누적 조정인 점, (h) 모든 점의 누적 조정이 롤과 맞지 않음, (i) 다른 월물의 제외, (j) known_at이 앞 롤보다 이른 계획, (k) 사슬이 끊긴 계획,
    (l) 같은 월물로 돌아오는 계획, (m) known_at이 기준일 UTC 자정 전인 항목.
    출력: 모두 ValueError. 다음 롤의 기준일이 앞 롤의 신월물 첫 거래일과 같은 계획은 받아들인다."""
    outcomes = outcomes_for(ONE_ROLL, EXAMPLE)
    inputs = inputs_at(ONE_ROLL, EXAMPLE, END)
    exchange_plan = plan_of(entry(D2, D3, at(D2, 23)), evidence=E.EXCHANGE_PUBLICATION)
    exchange_inputs = {c: asof_final_series(EXAMPLE, c, END, accepted_evidence=E.EXCHANGE_PUBLICATION) for c in ONE_ROLL.contracts}
    other_entry = plan_of(entry(D2, D3, at(D2, 23, 30)))
    series = build_adjusted_series(ONE_ROLL, outcomes, inputs, as_of=END, basis=FULL)
    first, second, third = series.points
    builds = [
        lambda: build_adjusted_series(ONE_ROLL, outcomes, inputs_at(ONE_ROLL, EXAMPLE, at(D3, 23)), as_of=END, basis=FULL),
        lambda: build_adjusted_series(ONE_ROLL, outcomes, exchange_inputs, as_of=END, basis=FULL),
        lambda: build_adjusted_series(ONE_ROLL, outcomes_for(exchange_plan, EXAMPLE), inputs, as_of=END, basis=FULL),
        lambda: build_adjusted_series(ONE_ROLL, outcomes_for(other_entry, EXAMPLE), inputs, as_of=END, basis=FULL),
        lambda: dataclasses.replace(series, points=(dataclasses.replace(first, availability_evidence=E.EXCHANGE_PUBLICATION), second, third)),
        lambda: dataclasses.replace(series, applied_rolls=(dataclasses.replace(outcomes[0], accepted_evidence=E.EXCHANGE_PUBLICATION),)),
        lambda: dataclasses.replace(first, adjusted_price=Decimal("109")),
        lambda: dataclasses.replace(series, points=(
            dataclasses.replace(first, cumulative_adjustment_points=Decimal("0"), adjusted_price=Decimal("100")),
            dataclasses.replace(second, cumulative_adjustment_points=Decimal("0"), adjusted_price=Decimal("102")),
            dataclasses.replace(third, daily_price_change_points=Decimal("10")))),
        lambda: dataclasses.replace(series, excluded=(ContinuousExclusion(trading_date=date(2026, 9, 7), selected_contract_id=Z6,
                                                                           reasons=("NOT_AVAILABLE",)),)),
        lambda: plan_of(entry(D2, D3, at(D3, 23)), entry(D3, date(2026, 9, 11), at(D3, 22), old=Z6, new=H7)),
        lambda: plan_of(entry(D2, D3, at(D2, 23)), entry(D3, date(2026, 9, 11), at(D3, 23), old=H7, new=M6)),
        lambda: plan_of(entry(D2, D3, at(D2, 23)), entry(D3, date(2026, 9, 11), at(D3, 23), old=Z6, new=U6)),
        lambda: entry(D2, D3, at(D1, 23)),
    ]
    for make in builds:
        with pytest.raises(ValueError):
            make()
    assert plan_of(entry(D2, D3, at(D2, 23)), entry(D3, date(2026, 9, 11), at(D3, 23), old=Z6, new=H7)).contracts == (U6, Z6, H7)


def test_quality_rules_flag_expiry_overlap_precision_sources_specs_and_calendar_coverage():
    """품질 규칙 보강. 입력: (a) 신월물 만기가 구월물과 같은 메타데이터, (b) 구월물 만기 뒤의 기준일, (c) 두 월물에 같은 날 최종가가 없음,
    (d) 점이 없는 As-of 시계열, (e) 원본보다 자릿수가 많은 가격(1e-10), (f) manifest에 없는 Snapshot, (g) 승수가 다른 월물 메타데이터,
    (h) 시계열 범위를 덮지 않는 달력, (i) 구월물 기준일 기록이 known_at 뒤 잠정가 때문에 모호해져 롤 경계가 기준일에 있지 않음.
    출력: (a) NEW_CONTRACT_EXPIRES_FIRST, (b) REFERENCE_AFTER_OLD_EXPIRY (차단), (c) NO_OVERLAP (경고), (d) EMPTY_SERIES (차단),
    (e) PRECISION_BEYOND_SOURCE (차단), (f) UNKNOWN_SOURCE_SNAPSHOT (차단), (g) CONTRACT_SPEC_MISMATCH (차단), (h) CALENDAR_DOES_NOT_COVER_RANGE
    (NOT_ASSESSABLE), (i) ROLL_BOUNDARY_NOT_AT_REFERENCE_DATE (차단). 합성 메타데이터는 METADATA_NOT_CONFIRMED 경고를 남긴다."""
    outcomes, series = build(ONE_ROLL, EXAMPLE, END)
    same_expiry = {U6: META[U6], Z6: dataclasses.replace(META[Z6], last_trading_date=META[U6].last_trading_date)}
    assert "NEW_CONTRACT_EXPIRES_FIRST" in check(quality(ONE_ROLL, EXAMPLE, END, series, outcomes, metadata=same_expiry), "ROLL_ORDER").reasons
    expired = plan_of(entry(date(2026, 9, 21), date(2026, 9, 22), at(date(2026, 9, 21), 23)))
    expired_events = [settle(U6, date(2026, 9, 21), "100"), settle(Z6, date(2026, 9, 21), "105"), settle(Z6, date(2026, 9, 22), "106")]
    expired_outcomes, expired_series = build(expired, expired_events, at(date(2026, 9, 23), 0))
    assert "REFERENCE_AFTER_OLD_EXPIRY" in check(quality(expired, expired_events, at(date(2026, 9, 23), 0), expired_series, expired_outcomes),
                                                 "ROLL_ORDER").reasons

    apart = [settle(U6, D1, "100"), settle(Z6, D3, "112")]
    apart_outcomes = outcomes_for(ONE_ROLL, apart)
    assert check(quality(ONE_ROLL, apart, END, None, apart_outcomes), "OVERLAP").reasons == ("NO_OVERLAP",)
    _, empty = build(ONE_ROLL, EXAMPLE, at(D1, 20), ASOF)
    assert check(quality(ONE_ROLL, EXAMPLE, at(D1, 20), empty, outcomes), "SELECTION_COVERAGE").reasons == ("EMPTY_SERIES",)

    fine = [settle(U6, D1, "100.0000000001"), *EXAMPLE[1:]]
    fine_outcomes, fine_series = build(ONE_ROLL, fine, END)
    assert check(quality(ONE_ROLL, fine, END, fine_series, fine_outcomes), "DECIMAL_PRECISION").reasons == ("PRECISION_BEYOND_SOURCE",)
    extra = "raw-sha256-" + "f" * 64
    both = {U6: contract_reports_for(ONE_ROLL, EXAMPLE)[U6],
            Z6: assess_settlement_quality(metadata=META[Z6], manifests=(manifest_for(SNAP[Z6]), manifest_for(extra)),
                                          events=[], issues=(), requested_start=D1, requested_end=D3, minimum_final_days=0, calendar=None)}
    known = (manifest_for(SNAP[U6]), manifest_for(SNAP[Z6]))
    for moved in (D3, D2):  # D3: 시계열 점의 Snapshot, D2: 롤 신월물 기준가의 Snapshot
        events = [settle(Z6, day, price, snapshot=extra if day == moved else None) if contract == Z6 else item
                  for item, contract, day, price in [(e, e.contract_id, e.trading_date, str(e.price)) for e in EXAMPLE]]
        moved_outcomes, moved_series = build(ONE_ROLL, events, END)
        integrity = check(quality(ONE_ROLL, events, END, moved_series, moved_outcomes, reports=both, manifests=known), "SOURCE_INTEGRITY")
        assert (integrity.status, integrity.reasons) == (Q.BLOCKED, ("DATA_ORIGIN_SYNTHETIC", "UNKNOWN_SOURCE_SNAPSHOT"))
    bigger = {U6: META[U6], Z6: dataclasses.replace(META[Z6], multiplier="50", outright_tick_value="12.5")}
    identity = check(quality(ONE_ROLL, EXAMPLE, END, series, outcomes, metadata=bigger), "CONTRACT_IDENTITY")
    assert {"CONTRACT_SPEC_MISMATCH", "METADATA_NOT_CONFIRMED"} <= set(identity.reasons) and identity.status is Q.BLOCKED
    short = TradingCalendarReference(exchange="CME", coverage_start=D2, coverage_end=D3, dates=(D2, D3),
                                     provenance=ReferenceProvenance(sources=("fixture:synthetic-calendar",), as_of=INGESTED,
                                                                    verification=VerificationLevel.CONFIRMED))
    assert check(quality(ONE_ROLL, EXAMPLE, END, series, outcomes, calendar=short), "MISSING_SESSIONS").reasons == ("CALENDAR_DOES_NOT_COVER_RANGE",)

    late_preliminary = [*EXAMPLE, settle(U6, D2, "102", recv=at(D3, 9), status=SettlementRevisionStatus.PRELIMINARY, seq=2)]
    late_outcomes, late_series = build(ONE_ROLL, late_preliminary, END)
    assert [(x.trading_date, x.reasons[0]) for x in late_series.excluded] == [(D2, "AMBIGUOUS")]
    arithmetic = check(quality(ONE_ROLL, late_preliminary, END, late_series, late_outcomes), "ADJUSTMENT_ARITHMETIC")
    assert (arithmetic.status, arithmetic.reasons) == (Q.BLOCKED, ("ROLL_BOUNDARY_NOT_AT_REFERENCE_DATE",))


# --- 산출물과 재현성 (Raw Snapshot → P1-01 Adapter → P1-02) ---

INSTRUMENTS = {U6: ("MESU6", 4242), Z6: ("MESZ6", 4343)}


def stat_row(day, price, recv, *, symbol, instrument_id, sequence, flags=3):
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    ns = lambda moment: int((moment - epoch).total_seconds()) * 10**9  # noqa: E731
    return {"ts_recv": ns(recv), "ts_event": ns(recv) - 1_000_000, "rtype": 24, "publisher_id": 1, "instrument_id": instrument_id,
            "ts_ref": ns(at(day, 0)), "price": int(Decimal(price).scaleb(9)), "quantity": 2**63 - 1, "sequence": sequence, "ts_in_delta": 0,
            "stat_type": 3, "channel_id": 0, "update_action": 1, "stat_flags": flags, "symbol": symbol}


def snapshot_rows(contract, prices):
    symbol, instrument_id = INSTRUMENTS[contract]
    return [stat_row(day, price, at(day, 21, 30), symbol=symbol, instrument_id=instrument_id, sequence=index + 1)
            for index, (day, price) in enumerate(prices)]


def store(root, contract, rows):
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=list(STATISTICS_COLUMNS), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return store_raw_snapshot(root, out.getvalue().encode("utf-8"), data_origin=DataOrigin.SYNTHETIC, provider="databento", dataset="GLBX.MDP3",
                              schema="statistics", encoding="csv", original_filename=f"synthetic-{INSTRUMENTS[contract][0]}.csv",
                              acquired_at=INGESTED, acquisition_method="SYNTHETIC_FIXTURE", request=(("symbols", INSTRUMENTS[contract][0]),))


def pipeline(tmp_path, name, plan, raw, *, started, cutoff=at(D2, 23)):
    """Raw Snapshot → P1-01 번역·품질 → 롤 결정 → Full-sample·As-of 시계열 → P1-02 품질 → 내보내기."""
    manifests, events, reports = [], [], {}
    for contract, manifest in raw.items():
        loaded, data = load_raw_snapshot(tmp_path / "raw", manifest.snapshot_id, expected_manifest_sha256=manifest_sha256(manifest))
        symbol, instrument_id = INSTRUMENTS[contract]
        mapping = DatabentoInstrumentMapping(dataset="GLBX.MDP3", raw_symbol=symbol, databento_instrument_id=instrument_id, contract_id=contract,
                                             price_unit=PriceUnit.INDEX_POINT, source="fixture:synthetic", verification=VerificationLevel.UNVERIFIED)
        parsed = parse_databento_statistics(data, manifest=loaded, mapping=mapping, metadata=META[contract])
        manifests.append(loaded)
        events += parsed.events
        reports[contract] = assess_settlement_quality(metadata=META[contract], manifests=(loaded,), events=parsed.events, issues=parsed.issues,
                                                      requested_start=D1, requested_end=D3, minimum_final_days=1, calendar=None)
    outcomes = outcomes_for(plan, events)
    full = build_adjusted_series(plan, outcomes, inputs_at(plan, events, END), as_of=END, basis=FULL)
    asof = build_adjusted_series(plan, outcomes, inputs_at(plan, events, cutoff), as_of=cutoff, basis=ASOF)
    report = assess_continuous_series(plan=plan, metadata={c: META[c] for c in plan.contracts}, roll_outcomes=outcomes, series=full,
                                      contract_series=inputs_at(plan, events, END), contract_reports=reports, manifests=tuple(manifests), calendar=None)
    parts = dict(plan=plan, roll_outcomes=outcomes, full_sample=full, asof=(asof,), report=report,
                 manifests={contract: (manifest,) for contract, manifest in zip(raw, manifests)},
                 metadata={c: META[c] for c in plan.contracts}, calendar=None,
                 upstream_versions={"databento_adapter": ADAPTER_VERSION, "settlement_quality_rule": QUALITY_RULE_VERSION,
                                    "settlement_selection_policy": SELECTION_POLICY})
    export = write_continuous_dataset(tmp_path / name, run_started_at=started, **parts)
    return export, report, events, parts


def test_dataset_is_reproducible_versioned_and_traceable(tmp_path):
    """요구 20·21·22. 입력: 9월물·12월물 합성 Raw Snapshot (작업 명세 예의 가격), 같은 계획으로 두 번 실행(실행 시각만 다름), 기준일·known_at이
    다른 계획, 12월물 원본에 행 하나를 더한 Snapshot.
    출력: run_log.json을 뺀 산출물이 바이트 단위로 같다. 처리 manifest는 두 월물의 원본·manifest 해시, 월물 메타데이터, 롤 계획 ID·해시, 선택
    정책, 조정 알고리즘·품질 규칙 판본, P1-01 판본과 각 산출물의 SHA-256을 기록하고, 시계열의 모든 점은 원본 Snapshot ID를 가진다. 계획을
    바꾸거나 원본을 바꾸면 처리 manifest 해시가 바뀐다. 이미 있는 출력 디렉터리에는 쓰지 않는다."""
    u_rows = snapshot_rows(U6, [(D1, "100"), (D2, "102")])
    z_rows = snapshot_rows(Z6, [(D1, "108"), (D2, "110"), (D3, "112")])
    raw = {U6: store(tmp_path / "raw", U6, u_rows), Z6: store(tmp_path / "raw", Z6, z_rows)}
    first, report, _, _ = pipeline(tmp_path, "out1", ONE_ROLL, raw, started=INGESTED)
    second, _, _, _ = pipeline(tmp_path, "out2", ONE_ROLL, raw, started=INGESTED + timedelta(hours=1))
    with pytest.raises(ContinuousExportError):
        pipeline(tmp_path, "out1", ONE_ROLL, raw, started=INGESTED)

    files = sorted(p.name for p in (tmp_path / "out1").iterdir())
    deterministic = sorted(["roll_plan.json", "roll_events.json", "continuous_series.json", "quality_report.json",
                            "continuous_series_asof_20260909T230000Z_VENDOR_CAPTURE.json"])
    assert files == sorted([*deterministic, "processed_manifest.json", "run_log.json"])
    assert [name for name, _ in first.outputs] == deterministic and first.outputs == second.outputs
    assert first.processed_manifest_sha256 == second.processed_manifest_sha256
    for name in files:
        assert ((tmp_path / "out1" / name).read_bytes() == (tmp_path / "out2" / name).read_bytes()) is (name != "run_log.json")
    manifest = json.loads((tmp_path / "out1" / "processed_manifest.json").read_text(encoding="utf-8"))
    assert first.processed_manifest_sha256 == hashlib.sha256((tmp_path / "out1" / "processed_manifest.json").read_bytes()).hexdigest()
    assert sorted(manifest["outputs"]) == deterministic
    assert [(item["contract_id"], item["snapshot_id"], item["raw_sha256"], item["manifest_sha256"]) for item in manifest["raw_snapshots"]] == [
        (U6, raw[U6].snapshot_id, raw[U6].raw_sha256, manifest_sha256(raw[U6])), (Z6, raw[Z6].snapshot_id, raw[Z6].raw_sha256, manifest_sha256(raw[Z6]))]
    assert (manifest["accepted_evidence"], manifest["quality_status"]) == ("VENDOR_CAPTURE", "BLOCKED")
    assert (check(report, "CONTRACT_DATA_QUALITY").status, check(report, "CONTRACT_DATA_QUALITY").reasons) == (Q.BLOCKED, ("CONTRACT_DATA_BLOCKED",))
    assert manifest["roll_plan"] == {"plan_id": ONE_ROLL.plan_id, "sha256": first.roll_plan_sha256}
    assert first.roll_plan_sha256 == hashlib.sha256((tmp_path / "out1" / "roll_plan.json").read_bytes()).hexdigest()
    assert (manifest["adjustment"], manifest["quality_rule_version"], manifest["selection_policy_ids"]) == (
        {"method": "FUTURES_ADDITIVE_BACK_ADJUSTED", "algorithm_version": ALGORITHM_VERSION}, CONTINUOUS_QUALITY_RULE_VERSION,
        ["research-explicit-roll/1"])
    assert manifest["upstream_versions"]["settlement_selection_policy"] == SELECTION_POLICY
    assert [item["contract_id"] for item in manifest["contract_metadata"]] == [U6, Z6] and manifest["calendar"] is None
    for name, digest in manifest["outputs"].items():
        assert hashlib.sha256((tmp_path / "out1" / name).read_bytes()).hexdigest() == digest
    series = json.loads((tmp_path / "out1" / "continuous_series.json").read_text(encoding="utf-8"))
    assert [(p["selected_contract_id"], p["raw_price"], p["adjusted_price"], p["daily_price_change_points"]) for p in series["points"]] == [
        (U6, "100.000000000", "108.000000000", None), (U6, "102.000000000", "110.000000000", "2.000000000"),
        (Z6, "112.000000000", "112.000000000", "2.000000000")]
    assert {p["source_snapshot_id"] for p in series["points"]} == {raw[U6].snapshot_id, raw[Z6].snapshot_id}
    events_doc = json.loads((tmp_path / "out1" / "roll_events.json").read_text(encoding="utf-8"))
    assert (events_doc["rolls"][0]["status"], events_doc["rolls"][0]["detail"]["roll_gap_points"]) == ("RESOLVED", "-8.000000000")
    assert report.status is Q.BLOCKED and check(report, "SOURCE_INTEGRITY").reasons == ("DATA_ORIGIN_SYNTHETIC",)

    changed_plan = plan_of(entry(D2, D3, at(D2, 23, 30)), plan_id="p1-02-synthetic-plan/2")
    third, _, _, _ = pipeline(tmp_path, "out3", changed_plan, raw, started=INGESTED)
    assert (third.roll_plan_sha256 != first.roll_plan_sha256, third.processed_manifest_sha256 != first.processed_manifest_sha256) == (True, True)
    extra = snapshot_rows(Z6, [(D1, "108"), (D2, "110"), (D3, "112"), (date(2026, 9, 11), "113")])
    changed_raw = {U6: raw[U6], Z6: store(tmp_path / "raw", Z6, extra)}
    fourth, _, _, _ = pipeline(tmp_path, "out4", ONE_ROLL, changed_raw, started=INGESTED)
    assert changed_raw[Z6].snapshot_id != raw[Z6].snapshot_id and fourth.processed_manifest_sha256 != first.processed_manifest_sha256


def test_export_refuses_datasets_that_contradict_their_plan(tmp_path):
    """내보내기 입력 연결 (독립 검토 F1). 입력: 정상 조립 결과에서 하나씩 바꾼 값 — (A) 시계열이 다른 gap(−7)의 롤을 적용, (B) 롤 결과의
    known_at이 계획과 다름, (C) 거래소 시각 근거로 만든 시계열, (D) 시계열 점이 다른 월물의 Snapshot을 가리킴, (E) 월물이 빠진 manifest.
    출력: 모두 ValueError이고 출력 디렉터리를 만들지 않는다."""
    raw = {U6: store(tmp_path / "raw", U6, snapshot_rows(U6, [(D1, "100"), (D2, "102")])),
           Z6: store(tmp_path / "raw", Z6, snapshot_rows(Z6, [(D1, "108"), (D2, "110"), (D3, "112")]))}
    _, _, events, parts = pipeline(tmp_path, "good", ONE_ROLL, raw, started=INGESTED)
    roll, full = parts["roll_outcomes"][0], parts["full_sample"]
    shifted = [dataclasses.replace(item, price=Decimal("103")) if (item.contract_id, item.trading_date) == (U6, D2) else item for item in events]
    other_gap = build_adjusted_series(ONE_ROLL, outcomes_for(ONE_ROLL, shifted), inputs_at(ONE_ROLL, shifted, END), as_of=END, basis=FULL)
    exchange_plan = plan_of(entry(D2, D3, at(D2, 23)), evidence=E.EXCHANGE_PUBLICATION)
    exchange = build_adjusted_series(exchange_plan, outcomes_for(exchange_plan, events), inputs_at(exchange_plan, events, END), as_of=END,
                                     basis=FULL)
    swapped = {U6: parts["manifests"][Z6], Z6: parts["manifests"][U6]}
    later = at(date(2026, 9, 12), 0)
    later_full = build_adjusted_series(ONE_ROLL, parts["roll_outcomes"], inputs_at(ONE_ROLL, events, later), as_of=later, basis=FULL)
    cases = [dict(full_sample=other_gap), dict(roll_outcomes=(dataclasses.replace(roll, evidence_cutoff_at=at(D3, 10)),)),
             dict(full_sample=exchange, asof=()), dict(manifests=swapped), dict(manifests={U6: parts["manifests"][U6]}),
             dict(asof=(parts["asof"][0], parts["asof"][0])), dict(full_sample=later_full)]
    assert other_gap.applied_rolls[0].roll_gap_points == Decimal("-7") and full.applied_rolls[0].roll_gap_points == Decimal("-8")
    for case in cases:
        with pytest.raises(ValueError):
            write_continuous_dataset(tmp_path / "bad", run_started_at=INGESTED, **{**parts, **case})
        assert not (tmp_path / "bad").exists()


def test_p1_02_does_not_change_p1_01_results(tmp_path):
    """요구 23. 입력: 9월물 합성 Snapshot의 P1-01 산출물을 P1-02 실행 전후에 같은 입력으로 만든다.
    출력: 두 P1-01 산출물(run_log.json 제외)이 바이트 단위로 같다. P1-02는 P1-01 사건·Series·Snapshot을 바꾸지 않는다."""
    raw = {U6: store(tmp_path / "raw", U6, snapshot_rows(U6, [(D1, "100"), (D2, "102")])),
           Z6: store(tmp_path / "raw", Z6, snapshot_rows(Z6, [(D1, "108"), (D2, "110"), (D3, "112")]))}

    def p1_01(name, events):
        own = tuple(item for item in events if item.contract_id == U6)
        report = assess_settlement_quality(metadata=META[U6], manifests=(raw[U6],), events=own, issues=(), requested_start=D1, requested_end=D2,
                                           minimum_final_days=1, calendar=None)
        write_settlement_dataset(tmp_path / name, metadata=META[U6], manifests=(raw[U6],), adapter_version=ADAPTER_VERSION, events=own,
                                 report=report, latest=latest_final_series(own, U6), asof=(), run_started_at=INGESTED)
        return {p.name: p.read_bytes() for p in (tmp_path / name).iterdir() if p.name != "run_log.json"}

    _, _, events, _ = pipeline(tmp_path, "p1_02", ONE_ROLL, raw, started=INGESTED)
    before = p1_01("p1_01_before", events)
    pipeline(tmp_path, "p1_02_again", ONE_ROLL, raw, started=INGESTED)
    assert p1_01("p1_01_after", events) == before
    assert load_raw_snapshot(tmp_path / "raw", raw[U6].snapshot_id, expected_manifest_sha256=manifest_sha256(raw[U6]))[0] == raw[U6]


def test_series_types_reject_contradictions_and_asof_names_carry_the_cutoff():
    """도메인 불변조건과 이름. 입력: 정상 시계열과 롤을 모순되게 바꾼 값. 출력: 롤 gap ≠ 구 − 신, known_at보다 늦게 보인 기준가, 롤 뒤 월물
    선택이 맞지 않는 점, 누적 조정이 롤과 맞지 않는 점, 다른 점과 이어지지 않는 일별 변화, as_of 뒤에 보인 점은 모두 ValueError. As-of 파일
    이름은 cutoff와 근거를 담는다."""
    outcomes, series = build(ONE_ROLL, EXAMPLE, at(D2, 23), ASOF)
    roll, point = outcomes[0], series.points[1]
    contradictions = [
        lambda: dataclasses.replace(roll, roll_gap_points=Decimal("8")),
        lambda: dataclasses.replace(roll, reference_prices_available_at=at(D2, 23, 30)),
        lambda: dataclasses.replace(series, points=(series.points[0], dataclasses.replace(point, selected_contract_id=Z6))),
        lambda: dataclasses.replace(series, points=(series.points[0], dataclasses.replace(point, cumulative_adjustment_points=Decimal("0"),
                                                                                           adjusted_price=Decimal("102")))),
        lambda: dataclasses.replace(series, points=(series.points[0], dataclasses.replace(point, daily_price_change_points=Decimal("3")))),
        lambda: dataclasses.replace(series, as_of=at(D2, 21, 31)),
    ]
    for make in contradictions:
        with pytest.raises(ValueError):
            make()
    assert asof_series_filename(series) == "continuous_series_asof_20260909T230000Z_VENDOR_CAPTURE.json"
