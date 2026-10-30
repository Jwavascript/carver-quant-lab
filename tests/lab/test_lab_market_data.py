"""P1-01 시장 데이터 (합성 fixture): Raw Snapshot, 월물 메타데이터, Databento statistics Adapter, 품질 검사, PIT 조회, 연구 Series,
재현 가능한 산출물 (ADR-0004 §6.4·§6.5, ADR-0006 I6-3·I6-11, ADR-0007 C7-1·C7-3·X7, ADR-0011 FP-11·FP-16).

모든 정산가는 **합성 값**이다 (1000 pt 부근, 가상 instrument ID 4242). 실제 MES 시세가 아니며 `DataOrigin.SYNTHETIC`으로 표시한다.
실데이터 통합 테스트는 `test_lab_market_data_real.py`에 따로 있다. 기대값(tick value 1.25, 고정소수점 변환, 나노초 올림, 9월 셋째 금요일
등)은 저장소 밖 독립 산술로 먼저 확인했다. 조립(Snapshot 읽기 → 번역 → 품질·PIT → 내보내기)은 테스트가 한다 (조립 계층 `lab.app`의
분류는 미승인, ADR-0010 Q10-4). 파일은 pytest 임시 경로에만 만든다.
"""

import csv
import dataclasses
import hashlib
import io
import json
import shutil
import stat
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from carver_quant.lab.adapters.databento_statistics import (
    ADAPTER_VERSION,
    STATISTICS_COLUMNS,
    DatabentoInstrumentMapping,
    parse_databento_statistics,
)
from carver_quant.lab.adapters.raw_snapshot import (
    RawSnapshotError,
    RawSnapshotIntegrityError,
    encode_manifest,
    load_raw_snapshot,
    manifest_sha256,
    store_raw_snapshot,
)
from carver_quant.lab.adapters.settlement_export import SettlementExportError, write_settlement_dataset
from carver_quant.lab.domain.market_data import (
    AvailabilityEvidence,
    DataOrigin,
    FuturesContractMetadata,
    PitStatus,
    PriceUnit,
    QualityCheckName,
    QualityStatus,
    ReferenceProvenance,
    RevisionRole,
    SeriesBasis,
    SettlementRevisionStatus,
    SettlementType,
    TradingCalendarReference,
    VerificationLevel,
)
from carver_quant.lab.marketdata.quality import QUALITY_RULE_VERSION, assess_settlement_quality, compare_contract_metadata
from carver_quant.lab.marketdata.settlements import SELECTION_POLICY, asof_final_series, get_final_settlement_asof, latest_final_series

UTC = timezone.utc
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
E = AvailabilityEvidence
Q = QualityStatus
P = PitStatus
CONTRACT = "CME.MES.2026-09"
OTHER_CONTRACT = "CME.MES.2026-12"
INSTRUMENT = 4242  # 가상 instrument ID (합성 fixture)
INGESTED = datetime(2026, 10, 22, 9, 0, tzinfo=UTC)
FINAL, ACTUAL, TRADING_TICK, INTRADAY = 1, 2, 4, 8
UNDEF_TIMESTAMP = 2**64 - 1
UNDEF_PRICE = 2**63 - 1

MES_SEP26 = FuturesContractMetadata(
    exchange="CME",
    product_root="MES",
    contract_id=CONTRACT,
    contract_year=2026,
    contract_month=9,
    multiplier="5",
    outright_tick_size="0.25",
    outright_tick_value="1.25",
    settlement_tick_size=None,
    currency="USD",
    price_unit=PriceUnit.INDEX_POINT,
    last_trading_date=date(2026, 9, 18),
    last_trading_at=datetime(2026, 9, 18, 13, 30, tzinfo=UTC),
    settlement_type=SettlementType.CASH,
    metadata_version="cme-mes-2026-09/1",
    provenance=ReferenceProvenance(sources=("fixture:task-specification",), as_of=datetime(2026, 10, 22, tzinfo=UTC),
                                   verification=VerificationLevel.UNVERIFIED),
)
MAPPING = DatabentoInstrumentMapping(dataset="GLBX.MDP3", raw_symbol="MESU6", databento_instrument_id=INSTRUMENT, contract_id=CONTRACT,
                                     price_unit=PriceUnit.INDEX_POINT, source="fixture:synthetic", verification=VerificationLevel.UNVERIFIED)


def ns(moment):
    delta = moment - EPOCH
    return (delta.days * 86400 + delta.seconds) * 10**9 + delta.microseconds * 1000


def at(day, hour, minute, second=0, micro=0):
    return datetime(day.year, day.month, day.day, hour, minute, second, micro, tzinfo=UTC)


def row(day, price, *, recv, event=None, flags=FINAL | ACTUAL, sequence=1, symbol="MESU6", instrument_id=INSTRUMENT, stat_type=3,
        update_action=1, ts_ref=None, recv_ns=None, event_ns=None):
    """합성 statistics 레코드 한 줄. 가격은 문자열 소수 → 1e-9 고정소수점 정수 (float 없음). 거래소 시각은 기본으로 수집 1ms 전."""
    raw_price = UNDEF_PRICE if price is None else int(Decimal(price).scaleb(9))
    received = recv_ns if recv_ns is not None else (UNDEF_TIMESTAMP if recv is None else ns(recv))
    happened = event_ns if event_ns is not None else (ns(event) if event is not None else
                                                      (UNDEF_TIMESTAMP if recv is None else ns(recv) - 1_000_000))
    return {
        "ts_recv": received, "ts_event": happened, "rtype": 24, "publisher_id": 1, "instrument_id": instrument_id,
        "ts_ref": ns(at(day, 0, 0)) if ts_ref is None else ts_ref, "price": raw_price, "quantity": 2**63 - 1,
        "sequence": sequence, "ts_in_delta": 0, "stat_type": stat_type, "channel_id": 0, "update_action": update_action,
        "stat_flags": flags, "symbol": symbol,
    }


def csv_bytes(rows, columns=STATISTICS_COLUMNS):
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=list(columns), lineterminator="\n", extrasaction="ignore")
    writer.writeheader()
    for item in rows:
        writer.writerow(item)
    return out.getvalue().encode("utf-8")


def session(day, price, *, sequence, prelim_price=None):
    """한 거래일: 20:05Z 잠정가, 21:30Z 최종가 (합성)."""
    return [row(day, prelim_price or price, recv=at(day, 20, 5), flags=ACTUAL, sequence=sequence),
            row(day, price, recv=at(day, 21, 30), sequence=sequence + 1)]


def weekdays(start, count):
    days, current = [], start
    while len(days) < count:
        if current.weekday() < 5:
            days.append(current)
        current += timedelta(days=1)
    return days


def snapshot(tmp_path, rows, *, columns=STATISTICS_COLUMNS, acquired_at=INGESTED):
    return store_raw_snapshot(
        tmp_path / "raw", csv_bytes(rows, columns), data_origin=DataOrigin.SYNTHETIC, provider="databento", dataset="GLBX.MDP3",
        schema="statistics", encoding="csv", original_filename="synthetic-mesu6-statistics.csv", acquired_at=acquired_at,
        acquisition_method="SYNTHETIC_FIXTURE",
        request=(("end", "2026-09-01"), ("schema", "statistics"), ("start", "2026-07-01"), ("stype_in", "raw_symbol"),
                 ("symbols", "MESU6")),
    )


def load(tmp_path, manifest):
    """보관할 때 받은 manifest의 해시로 고정해 읽는다."""
    return load_raw_snapshot(tmp_path / "raw", manifest.snapshot_id, expected_manifest_sha256=manifest_sha256(manifest))


def parsed(tmp_path, rows, *, metadata=MES_SEP26, columns=STATISTICS_COLUMNS, acquired_at=INGESTED):
    manifest = snapshot(tmp_path, rows, columns=columns, acquired_at=acquired_at)
    _, raw = load(tmp_path, manifest)
    return manifest, parse_databento_statistics(raw, manifest=manifest, mapping=MAPPING, metadata=metadata)


def calendar_of(dates, start, end, verification=VerificationLevel.UNVERIFIED):
    return TradingCalendarReference(exchange="CME", coverage_start=start, coverage_end=end, dates=tuple(dates),
                                    provenance=ReferenceProvenance(sources=("fixture:synthetic-calendar",), as_of=INGESTED,
                                                                   verification=verification))


def quality(manifest, result, *, metadata=MES_SEP26, calendar=None, minimum=1, start=date(2026, 7, 1), end=date(2026, 8, 31)):
    return assess_settlement_quality(metadata=metadata, manifests=(manifest,), events=result.events, issues=result.issues,
                                     requested_start=start, requested_end=end, minimum_final_days=minimum, calendar=calendar)


def check(report, name):
    return next(item for item in report.checks if item.name is QualityCheckName[name])


def blocking(result):
    return [issue.code for issue in result.issues if issue.blocking]


JUL1, JUL2, JUL6 = date(2026, 7, 1), date(2026, 7, 2), date(2026, 7, 6)


def test_contract_metadata_tick_value_identity_and_wrong_ticks():
    """요구 1·2·3. 입력: MES 2026년 9월물 메타데이터 (승수 5, tick 0.25, 선언 tick value 1.25), 잘못된 변형.
    출력: tick value = Decimal("0.25") × Decimal("5") = Decimal("1.25"). 월물 ID는 거래소·상품·연·월에서 나온 `CME.MES.2026-09`와
    같아야 한다 (다르면 ValueError). tick 0.5에 tick value 1.25처럼 서로 맞지 않는 선언, 시간대 없는 마지막 거래 시각, float 승수는
    ValueError. 서로는 맞지만 기준과 다른 tick 0.5 / value 2.5는 비교에서 두 필드 불일치로 드러난다. 9월 셋째 금요일은 2026-09-18이다."""
    assert MES_SEP26.outright_tick_value == Decimal("0.25") * Decimal("5") == Decimal("1.25")
    assert MES_SEP26.last_trading_date == date(2026, 9, 18) and MES_SEP26.last_trading_date.weekday() == 4
    with pytest.raises(ValueError):
        dataclasses.replace(MES_SEP26, contract_id="CME.MES.2026-12")
    with pytest.raises(ValueError):
        dataclasses.replace(MES_SEP26, outright_tick_size="0.5")
    with pytest.raises(ValueError):
        dataclasses.replace(MES_SEP26, last_trading_at=datetime(2026, 9, 18, 13, 30))
    with pytest.raises(ValueError):
        dataclasses.replace(MES_SEP26, multiplier=5.0)
    wrong = dataclasses.replace(MES_SEP26, outright_tick_size="0.5", outright_tick_value="2.5")
    assert compare_contract_metadata(wrong, reference=MES_SEP26) == ("outright_tick_size", "outright_tick_value")
    assert compare_contract_metadata(MES_SEP26, reference=MES_SEP26) == ()


def test_symbol_instrument_and_contract_mapping_is_verified(tmp_path):
    """요구 2 (FR-03). 입력: 연속 월물 symbol `MES.c.0`(같은 instrument ID), 다른 월물 `MESZ6`, 다른 instrument ID 9999 레코드와 정상 레코드.
    그리고 메타데이터와 맞지 않는 대응표 (MESU5, 다른 월물 ID), 연속 symbol 대응표.
    출력: 정상 레코드만 사건이 되고 나머지는 차단 문제로 남는다 (연속·front-month symbol을 같은 ID라도 특정 월물로 받지 않음). 품질 검사
    CONTRACT_IDENTITY는 BLOCKED이며 확인되지 않은 대응표도 사유로 남는다. 메타데이터와 다르거나 연속 symbol인 대응표는 ValueError."""
    rows = [row(JUL1, "1000.25", recv=at(JUL1, 21, 30), sequence=1),
            row(JUL1, "1000.25", recv=at(JUL1, 21, 31), sequence=2, symbol="MES.c.0"),
            row(JUL1, "1000.25", recv=at(JUL1, 21, 32), sequence=3, symbol="MESZ6"),
            row(JUL1, "1000.25", recv=at(JUL1, 21, 33), sequence=4, instrument_id=9999)]
    manifest, result = parsed(tmp_path, rows)

    assert [event.source_record_id.split(":")[-2] for event in result.events] == ["1"]
    assert sorted(blocking(result)) == ["IDENTITY_CONTINUOUS_SYMBOL", "IDENTITY_INSTRUMENT_ID_MISMATCH", "IDENTITY_SYMBOL_MISMATCH"]
    identity = check(quality(manifest, result), "CONTRACT_IDENTITY")
    assert identity.status is Q.BLOCKED and "MAPPING_NOT_CONFIRMED" in identity.reasons
    _, raw = load(tmp_path, manifest)
    for mapping in (dataclasses.replace(MAPPING, raw_symbol="MESU5"), dataclasses.replace(MAPPING, contract_id="CME.MES.2026-12")):
        with pytest.raises(ValueError):
            parse_databento_statistics(raw, manifest=manifest, mapping=mapping, metadata=MES_SEP26)
    with pytest.raises(ValueError):
        dataclasses.replace(MAPPING, raw_symbol="MES.c.0")


def test_settlement_tick_is_not_the_outright_tick(tmp_path):
    """요구 3·4. 입력: (a) 거래 tick 정산 표시(bit 2)인 최종가 1000.10, (b) 표시 없는(청산 tick) 최종가 1000.10, 정산 tick 미확인,
    (c) 정산 tick 0.01로 확인된 메타데이터, (d) 그 메타데이터에서 1000.105.
    출력: (a) 거래 tick(0.25)에 맞지 않아 TICK BLOCKED (OFF_TRADING_TICK). (b) outright tick으로 검사하지 않고 WARNING
    (SETTLEMENT_TICK_SIZE_UNVERIFIED). (c) PASSED. (d) BLOCKED (OFF_SETTLEMENT_TICK)."""
    flagged_manifest, flagged = parsed(tmp_path, [row(JUL1, "1000.10", recv=at(JUL1, 21, 30), flags=FINAL | ACTUAL | TRADING_TICK)])
    tick = check(quality(flagged_manifest, flagged), "TICK")
    assert (tick.status, tick.reasons) == (Q.BLOCKED, ("OFF_TRADING_TICK",))

    clearing_manifest, clearing = parsed(tmp_path / "b", [row(JUL1, "1000.10", recv=at(JUL1, 21, 30))])
    tick = check(quality(clearing_manifest, clearing), "TICK")
    assert (tick.status, tick.reasons) == (Q.WARNING, ("SETTLEMENT_TICK_SIZE_UNVERIFIED",))
    known = dataclasses.replace(MES_SEP26, settlement_tick_size="0.01")
    assert check(quality(clearing_manifest, clearing, metadata=known), "TICK").status is Q.PASSED
    odd_manifest, odd = parsed(tmp_path / "d", [row(JUL1, "1000.105", recv=at(JUL1, 21, 30))], metadata=known)
    tick = check(quality(odd_manifest, odd, metadata=known), "TICK")
    assert (tick.status, tick.reasons) == (Q.BLOCKED, ("OFF_SETTLEMENT_TICK",))


def test_preliminary_final_and_withdrawn_records_are_distinguished(tmp_path):
    """요구 5. 입력: 같은 거래일의 잠정가(1000.00, 20:05Z), 최종가(1000.25, 21:30Z), 다른 날의 최종가와 그 뒤의 삭제(update_action 2,
    가격 없음), 잠정가만 있는 날.
    출력: 상태는 PRELIMINARY / FINAL / WITHDRAWN이며 가격은 1e-9 고정소수점에서 float 없이 정확한 Decimal이다 (원래 자릿수 9). 21:00Z
    조회는 잠정가만 보여 NOT_AVAILABLE (PRELIMINARY_ONLY)이고 가격을 내지 않는다. 철회로 끝난 날은 NOT_AVAILABLE (SETTLEMENT_WITHDRAWN).
    품질 검사 REVISION_ORDER는 잠정가만 있는 날과 철회로 끝난 날을 경고한다."""
    rows = session(JUL1, "1000.25", sequence=1, prelim_price="1000.00") + [
        row(JUL2, "1000.50", recv=at(JUL2, 21, 30), sequence=5),
        row(JUL2, None, recv=at(JUL2, 22, 0), sequence=6, update_action=2),
        row(JUL6, "1000.75", recv=at(JUL6, 20, 5), flags=ACTUAL, sequence=7)]
    manifest, result = parsed(tmp_path, rows)

    assert [(e.trading_date, e.revision_status, e.price) for e in result.events] == [
        (JUL1, SettlementRevisionStatus.PRELIMINARY, Decimal("1000.00")),
        (JUL1, SettlementRevisionStatus.FINAL, Decimal("1000.25")),
        (JUL2, SettlementRevisionStatus.FINAL, Decimal("1000.50")),
        (JUL2, SettlementRevisionStatus.WITHDRAWN, None),
        (JUL6, SettlementRevisionStatus.PRELIMINARY, Decimal("1000.75"))]
    assert str(result.events[1].price) == "1000.250000000"
    early = get_final_settlement_asof(result.events, CONTRACT, JUL1, at(JUL1, 21, 0), accepted_evidence=E.VENDOR_CAPTURE)
    assert (early.status, early.price, early.reasons) == (P.NOT_AVAILABLE, None, ("PRELIMINARY_ONLY",))
    withdrawn = get_final_settlement_asof(result.events, CONTRACT, JUL2, at(JUL2, 23, 0), accepted_evidence=E.VENDOR_CAPTURE)
    assert (withdrawn.status, withdrawn.price, withdrawn.reasons) == (P.NOT_AVAILABLE, None, ("SETTLEMENT_WITHDRAWN",))
    revision = check(quality(manifest, result), "REVISION_ORDER")
    assert (revision.status, revision.reasons) == (Q.WARNING, ("PRELIMINARY_WITHOUT_FINAL", "SETTLEMENT_WITHDRAWN"))


def test_intraday_theoretical_and_late_preliminary_records_are_not_daily_finals(tmp_path):
    """요구 5 보강. 입력: (a) 이론가 최종가(bit 1 꺼짐)와 장중 최종가(bit 3)만 있는 거래일, (b) 최종가(21:30Z) 뒤에 잠정가(22:00Z)가 온 거래일.
    출력: (a) 최종가가 없다 (NOT_AVAILABLE, ONLY_INTRADAY_OR_THEORETICAL). Series에서 제외되고 REVISION_ORDER 경고. (b) 21:45Z에는 최종가가
    보이지만 23:00Z에는 AMBIGUOUS (PRELIMINARY_AFTER_FINAL)이며 품질 검사 REVISION_ORDER가 BLOCKED다 (조용히 고르지 않음)."""
    rows = [row(JUL1, "1000.25", recv=at(JUL1, 21, 30), flags=FINAL, sequence=1),
            row(JUL1, "1000.25", recv=at(JUL1, 21, 31), flags=FINAL | ACTUAL | INTRADAY, sequence=2),
            row(JUL2, "1000.50", recv=at(JUL2, 21, 30), sequence=3),
            row(JUL2, "1000.00", recv=at(JUL2, 22, 0), flags=ACTUAL, sequence=4)]
    manifest, result = parsed(tmp_path, rows)

    none = get_final_settlement_asof(result.events, CONTRACT, JUL1, at(JUL1, 23, 0), accepted_evidence=E.VENDOR_CAPTURE)
    assert (none.status, none.reasons) == (P.NOT_AVAILABLE, ("ONLY_INTRADAY_OR_THEORETICAL",))
    before = get_final_settlement_asof(result.events, CONTRACT, JUL2, at(JUL2, 21, 45), accepted_evidence=E.VENDOR_CAPTURE)
    after = get_final_settlement_asof(result.events, CONTRACT, JUL2, at(JUL2, 23, 0), accepted_evidence=E.VENDOR_CAPTURE)
    assert (before.status, before.price) == (P.AVAILABLE, Decimal("1000.50"))
    assert (after.status, after.price, after.reasons) == (P.AMBIGUOUS, None, ("PRELIMINARY_AFTER_FINAL",))
    latest = latest_final_series(result.events, CONTRACT)
    assert (latest.points, [(x.trading_date, x.status) for x in latest.excluded]) == ((), [(JUL1, P.NOT_AVAILABLE), (JUL2, P.AMBIGUOUS)])
    revision = check(quality(manifest, result), "REVISION_ORDER")
    assert (revision.status, revision.reasons) == (Q.BLOCKED, ("NO_DAILY_ACTUAL_SETTLEMENT", "PRELIMINARY_AFTER_FINAL"))


def test_asof_query_never_returns_a_final_before_its_evidence_time(tmp_path):
    """요구 6·FR-05. 입력: 잠정가(20:05Z)와 최종가. 최종가의 공급자 수집 시각은 21:30:00.000000500Z (나노초), 이 시스템 수신은 2026-10-22.
    출력: 수집 시각은 마이크로초로 올림되어 21:30:00.000001Z다 (앞당기지 않음). 20:00Z에는 아무것도 보이지 않아 NO_VISIBLE_RECORD이며 뒤에
    올 기록이 있다는 사실을 드러내지 않는다. 21:30:00.000000Z 조회는 NOT_AVAILABLE, 21:30:00.000001Z는 AVAILABLE 1000.25 (근거
    VENDOR_CAPTURE). 시스템 수신만 근거로 받으면 7월 조회는 NOT_AVAILABLE이고 10-22 수신 이후에만 AVAILABLE이다. 근거 수준에는 기본값이
    없고, 시간대 없는 cutoff는 ValueError."""
    final_ns = ns(at(JUL1, 21, 30)) + 500
    rows = [row(JUL1, "1000.00", recv=at(JUL1, 20, 5), flags=ACTUAL, sequence=1),
            row(JUL1, "1000.25", recv=None, recv_ns=final_ns, event_ns=final_ns - 2_000_000, sequence=2)]
    _, result = parsed(tmp_path, rows)
    assert result.events[1].vendor_received_at == at(JUL1, 21, 30, 0, 1)

    nothing = get_final_settlement_asof(result.events, CONTRACT, JUL1, at(JUL1, 20, 0), accepted_evidence=E.VENDOR_CAPTURE)
    assert (nothing.status, nothing.reasons) == (P.NOT_AVAILABLE, ("NO_VISIBLE_RECORD",))
    before = get_final_settlement_asof(result.events, CONTRACT, JUL1, at(JUL1, 21, 30), accepted_evidence=E.VENDOR_CAPTURE)
    after = get_final_settlement_asof(result.events, CONTRACT, JUL1, at(JUL1, 21, 30, 0, 1), accepted_evidence=E.VENDOR_CAPTURE)
    assert (before.status, before.price) == (P.NOT_AVAILABLE, None)
    assert (after.status, after.price, after.evidence_used, after.available_at) == (
        P.AVAILABLE, Decimal("1000.25"), E.VENDOR_CAPTURE, at(JUL1, 21, 30, 0, 1))
    strict = get_final_settlement_asof(result.events, CONTRACT, JUL1, at(JUL1, 23, 0), accepted_evidence=E.SYSTEM_RECEIPT)
    assert (strict.status, strict.price) == (P.NOT_AVAILABLE, None)
    later = get_final_settlement_asof(result.events, CONTRACT, JUL1, INGESTED, accepted_evidence=E.SYSTEM_RECEIPT)
    assert (later.status, later.price, later.evidence_used) == (P.AVAILABLE, Decimal("1000.25"), E.SYSTEM_RECEIPT)
    with pytest.raises(TypeError):
        get_final_settlement_asof(result.events, CONTRACT, JUL1, INGESTED)
    with pytest.raises(ValueError):
        get_final_settlement_asof(result.events, CONTRACT, JUL1, datetime(2026, 7, 1, 23, 0), accepted_evidence=E.VENDOR_CAPTURE)


def test_ordering_uses_only_timestamps_known_at_the_cutoff(tmp_path):
    """FR-05 미래 정보 차단 (독립 검토 HIGH-1). 입력: 최종가 A 1000.25 (거래소 21:00Z)와 B 1000.50 (거래소 21:05Z, 공급자 수집 21:20Z). A의
    공급자 수집 시각만 21:15Z / 21:30Z로 다른 두 변형. 거래소 시각 근거로 조회. 그리고 공급자 수집 시각이 없는 잠정가·최종가, 시계 차이로
    공급자 수집(21:00Z)이 거래소 시각(21:01Z)보다 이른 최종가.
    출력: 21:10Z에는 두 공급자 수집 시각이 모두 미래이므로 거래소 시각으로만 순서를 정해 두 변형 모두 B 1000.50 (CORRECTION)이다 (cutoff 뒤의
    값에 따라 답이 바뀌지 않음). 22:00Z에는 수집 순서도 알려진다: 변형 1(순서 일치)은 B, 변형 2(수집 순서가 거래소 순서와 반대)는 AMBIGUOUS
    (SOURCE_ORDER_INVERSION)이고 품질 검사 REVISION_ORDER가 BLOCKED다. 공급자 수집 시각이 없으면 거래소 시각으로 순서를 정한다. 시계 차이가
    있는 기록은 받아들인 근거 이상의 가장 이른 시각(수집 21:00Z)부터 보이고 TIMESTAMP_TIMEZONE 경고가 남는다."""
    early_answers, late_answers = [], []
    for name, a_received in (("one", at(JUL1, 21, 15)), ("two", at(JUL1, 21, 30))):
        rows = [row(JUL1, "1000.25", recv=a_received, event=at(JUL1, 21, 0), sequence=1),
                row(JUL1, "1000.50", recv=at(JUL1, 21, 20), event=at(JUL1, 21, 5), sequence=2)]
        manifest, result = parsed(tmp_path / name, rows)
        early = get_final_settlement_asof(result.events, CONTRACT, JUL1, at(JUL1, 21, 10), accepted_evidence=E.EXCHANGE_PUBLICATION)
        series = asof_final_series(result.events, CONTRACT, at(JUL1, 21, 10), accepted_evidence=E.EXCHANGE_PUBLICATION)
        early_answers.append((early.status, early.price, early.revision_role, [(p.trading_date, p.price) for p in series.points]))
        late = get_final_settlement_asof(result.events, CONTRACT, JUL1, at(JUL1, 22, 0), accepted_evidence=E.EXCHANGE_PUBLICATION)
        late_answers.append((late.status, late.price, late.reasons, check(quality(manifest, result), "REVISION_ORDER")))
    assert early_answers[0] == early_answers[1] == (P.AVAILABLE, Decimal("1000.50"), RevisionRole.CORRECTION, [(JUL1, Decimal("1000.50"))])
    assert late_answers[0][:3] == (P.AVAILABLE, Decimal("1000.50"), ())
    assert "SOURCE_ORDER_INVERSION" not in late_answers[0][3].reasons
    assert late_answers[1][:3] == (P.AMBIGUOUS, None, ("SOURCE_ORDER_INVERSION",))
    assert late_answers[1][3].status is Q.BLOCKED and "SOURCE_ORDER_INVERSION" in late_answers[1][3].reasons

    exchange_only = [row(JUL2, "1000.00", recv=None, event=at(JUL2, 20, 0), flags=ACTUAL, sequence=3),
                     row(JUL2, "1000.75", recv=None, event=at(JUL2, 21, 0), sequence=4),
                     row(JUL6, "1001.00", recv=at(JUL6, 21, 0), event=at(JUL6, 21, 1), sequence=5)]
    manifest, result = parsed(tmp_path / "three", exchange_only)
    answer = get_final_settlement_asof(result.events, CONTRACT, JUL2, at(JUL2, 22, 0), accepted_evidence=E.EXCHANGE_PUBLICATION)
    assert (answer.status, answer.price, answer.evidence_used) == (P.AVAILABLE, Decimal("1000.75"), E.EXCHANGE_PUBLICATION)
    # 시계 차이로 공급자 수집(21:00Z)이 거래소 시각(21:01Z)보다 이르면, 받아들인 근거 이상의 가장 이른 시각(수집 시각)을 쓴다.
    skewed = get_final_settlement_asof(result.events, CONTRACT, JUL6, at(JUL6, 21, 0, 30), accepted_evidence=E.EXCHANGE_PUBLICATION)
    assert (skewed.status, skewed.available_at, skewed.evidence_used) == (P.AVAILABLE, at(JUL6, 21, 0), E.VENDOR_CAPTURE)
    timing = check(quality(manifest, result), "TIMESTAMP_TIMEZONE")
    assert (timing.status, timing.reasons) == (Q.WARNING, ("VENDOR_CAPTURE_BEFORE_PUBLICATION",))


def test_later_correction_does_not_leak_into_earlier_cutoffs(tmp_path):
    """요구 7·FR-04. 입력: 7-1 최종가 1000.25 (7-1 21:30Z 수집), 같은 거래일의 정정 최종가 1000.50 (7-2 09:00Z 수집).
    출력: 7-1 23:00Z 조회는 1000.25 (ORIGINAL_FINAL), 7-2 10:00Z 조회는 1000.50 (CORRECTION). Snapshot의 최신 최종가 Series
    (LATEST_FINAL_IN_SNAPSHOT)는 1000.50이지만, 7-1 23:00Z 기준 As-of Series는 1000.25다 (최신값을 과거로 소급하지 않음). 원래 최종가
    기록은 정규화 결과에 그대로 남고 품질 검사 REVISION_ORDER는 정정을 WARNING으로 보고한다."""
    rows = session(JUL1, "1000.25", sequence=1) + [row(JUL1, "1000.50", recv=at(JUL2, 9, 0), sequence=3)]
    manifest, result = parsed(tmp_path, rows)

    first = get_final_settlement_asof(result.events, CONTRACT, JUL1, at(JUL1, 23, 0), accepted_evidence=E.VENDOR_CAPTURE)
    second = get_final_settlement_asof(result.events, CONTRACT, JUL1, at(JUL2, 10, 0), accepted_evidence=E.VENDOR_CAPTURE)
    assert (first.price, first.revision_role) == (Decimal("1000.25"), RevisionRole.ORIGINAL_FINAL)
    assert (second.price, second.revision_role) == (Decimal("1000.50"), RevisionRole.CORRECTION)
    latest = latest_final_series(result.events, CONTRACT)
    asof = asof_final_series(result.events, CONTRACT, at(JUL1, 23, 0), accepted_evidence=E.VENDOR_CAPTURE)
    assert (latest.basis, [(p.trading_date, p.price, p.revision_role) for p in latest.points]) == (
        SeriesBasis.LATEST_FINAL_IN_SNAPSHOT, [(JUL1, Decimal("1000.50"), RevisionRole.CORRECTION)])
    assert (asof.basis, asof.cutoff_at, [(p.trading_date, p.price) for p in asof.points]) == (
        SeriesBasis.AS_OF_CUTOFF, at(JUL1, 23, 0), [(JUL1, Decimal("1000.25"))])
    assert [e.price for e in result.events if e.revision_status is SettlementRevisionStatus.FINAL] == [Decimal("1000.25"), Decimal("1000.50")]
    revision = check(quality(manifest, result), "REVISION_ORDER")
    assert (revision.status, revision.reasons) == (Q.WARNING, ("FINAL_CORRECTED",))


def test_receipts_from_several_snapshots_keep_the_source_order(tmp_path):
    """FR-04·FR-05. 입력: Snapshot A(10-22 09:00Z 획득)에 7-1 최종가 1000.25, 정정 1000.50 (7-2 09:00Z 수집), 7-2 최종가. Snapshot B(10-23
    09:00Z 획득)에 7-1 원래 최종가와 7-2 최종가만 다시 있음. 다른 월물의 같은 시각 기록 하나. 시스템 수신 근거로 조회.
    출력: 10-22 08:00Z에는 보인 기록이 없다. 10-23 12:00Z에 7-1은 정정 1000.50 (CORRECTION, 이용 가능 시각 10-22 09:00Z) — 늦게 받은
    Snapshot의 옛 최종가가 정정을 덮지 않는다 (순서는 수신 순서가 아니라 공급원 순서). 7-2는 처음 받은 Snapshot A의 기록 (이용 가능 시각
    10-22 09:00Z). 다른 월물 기록은 조회·Series에 섞이지 않고 품질 검사에서 CONTRACT_ID_MISMATCH로 차단된다. 두 Snapshot에 같은 원본
    레코드가 있는 것은 DUPLICATE_RECORDS 경고다."""
    final = row(JUL1, "1000.25", recv=at(JUL1, 21, 30), sequence=2)
    correction = row(JUL1, "1000.50", recv=at(JUL2, 9, 0), sequence=3)
    next_day = row(JUL2, "1000.75", recv=at(JUL2, 21, 30), sequence=4)
    first = snapshot(tmp_path, [final, correction, next_day])
    second = snapshot(tmp_path, [final, next_day], acquired_at=INGESTED + timedelta(days=1))
    events, issues = [], []
    for manifest in (first, second):
        _, raw = load(tmp_path, manifest)
        result = parse_databento_statistics(raw, manifest=manifest, mapping=MAPPING, metadata=MES_SEP26)
        events += result.events
        issues += result.issues
    corrected = next(event for event in events if event.price == Decimal("1000.50"))
    events.append(dataclasses.replace(corrected, contract_id=OTHER_CONTRACT, price=Decimal("1100.00"), source_record_id="synthetic:other"))

    early = get_final_settlement_asof(events, CONTRACT, JUL1, at(date(2026, 10, 22), 8, 0), accepted_evidence=E.SYSTEM_RECEIPT)
    assert (early.status, early.reasons) == (P.NOT_AVAILABLE, ("NO_VISIBLE_RECORD",))
    cutoff = at(date(2026, 10, 23), 12, 0)
    late = get_final_settlement_asof(events, CONTRACT, JUL1, cutoff, accepted_evidence=E.SYSTEM_RECEIPT)
    assert (late.price, late.revision_role, late.available_at, late.event.source_snapshot_id) == (
        Decimal("1000.50"), RevisionRole.CORRECTION, INGESTED, first.snapshot_id)
    repeated = get_final_settlement_asof(events, CONTRACT, JUL2, cutoff, accepted_evidence=E.SYSTEM_RECEIPT)
    assert (repeated.price, repeated.available_at, repeated.event.source_snapshot_id) == (Decimal("1000.75"), INGESTED, first.snapshot_id)
    assert [(p.trading_date, p.price) for p in latest_final_series(events, CONTRACT).points] == [(JUL1, Decimal("1000.50")), (JUL2, Decimal("1000.75"))]

    report = assess_settlement_quality(metadata=MES_SEP26, manifests=(first, second), events=events, issues=issues,
                                       requested_start=JUL1, requested_end=JUL2, minimum_final_days=1, calendar=None)
    duplicates = check(report, "DUPLICATES_AND_CONFLICTS")
    assert (duplicates.status, duplicates.reasons) == (Q.WARNING, ("DUPLICATE_RECORDS",))
    identity = check(report, "CONTRACT_IDENTITY")
    assert identity.status is Q.BLOCKED and "CONTRACT_ID_MISMATCH" in identity.reasons


def test_conflicting_finals_at_the_same_time_are_ambiguous_and_duplicates_are_counted_once(tmp_path):
    """요구 8. 입력: (a) 같은 수집 시각에 다른 최종가 1000.25와 1000.50 (sequence만 다름), (b) 똑같은 레코드 두 줄.
    출력: (a) PIT 조회는 AMBIGUOUS이고 가격이 없다 (sequence로 고르지 않음). 최신 Series에서 그 거래일은 빠지고, 품질 검사
    DUPLICATES_AND_CONFLICTS는 BLOCKED. (b) 한 번만 사건이 되고 WARNING (DUPLICATE_RECORDS)."""
    rows = [row(JUL1, "1000.25", recv=at(JUL1, 21, 30), sequence=1), row(JUL1, "1000.50", recv=at(JUL1, 21, 30), sequence=2)]
    manifest, result = parsed(tmp_path, rows)
    clash = get_final_settlement_asof(result.events, CONTRACT, JUL1, at(JUL1, 23, 0), accepted_evidence=E.VENDOR_CAPTURE)
    assert (clash.status, clash.price, clash.reasons) == (P.AMBIGUOUS, None, ("CONFLICTING_FINALS_AT_SAME_TIME",))
    latest = latest_final_series(result.events, CONTRACT)
    assert (latest.points, [(x.trading_date, x.status, x.reasons) for x in latest.excluded]) == (
        (), [(JUL1, P.AMBIGUOUS, ("CONFLICTING_FINALS_AT_SAME_TIME",))])
    report = quality(manifest, result)
    assert check(report, "DUPLICATES_AND_CONFLICTS").status is Q.BLOCKED
    assert check(report, "REVISION_ORDER").status is Q.PASSED  # 같은 시각의 상충은 정정이 아니다

    same = row(JUL2, "1000.50", recv=at(JUL2, 21, 30), sequence=7)
    dup_manifest, dup = parsed(tmp_path / "dup", [same, same])
    assert len(dup.events) == 1
    duplicates = check(quality(dup_manifest, dup), "DUPLICATES_AND_CONFLICTS")
    assert (duplicates.status, duplicates.reasons) == (Q.WARNING, ("DUPLICATE_RECORDS",))


def test_utc_dates_dst_offsets_and_trading_dates_are_kept_apart(tmp_path):
    """요구 9 (ADR-0007 C7-1·C7-2·C7-3). 입력: (a) 거래일 7-1의 최종가가 UTC로 7-2 01:15Z에 수집됨, (b) 수집 20:45Z인 최종가를 현지
    15:40에 UTC−5(CDT)와 UTC−6(CST) 오프셋으로 각각 표현한 cutoff, (c) 거래일 7-2인데 7-1 21:00Z에 수집된 최종가, (d) 자정이 아닌 ts_ref.
    출력: (a) 거래일은 ts_ref(7-1)이지 수신 시각의 UTC 날짜(7-2)가 아니다. (b) 같은 현지 시계라도 오프셋이 다르면 다른 순간이므로 결과가 다르다
    (20:40Z → NOT_AVAILABLE, 21:40Z → AVAILABLE). 코드는 오프셋을 추측하지 않고 받은 순간으로만 비교한다. (c) 거래일 UTC 자정보다 이른 기록은
    TIMESTAMP_TIMEZONE BLOCKED. (d) SCHEMA 문제 (SCHEMA_TS_REF_NOT_DATE)이며 사건이 되지 않는다."""
    late_manifest, late = parsed(tmp_path, [row(JUL1, "1000.25", recv=at(JUL2, 1, 15), sequence=1)])
    assert late.events[0].trading_date == JUL1
    assert get_final_settlement_asof(late.events, CONTRACT, JUL1, at(JUL2, 1, 20), accepted_evidence=E.VENDOR_CAPTURE).status is P.AVAILABLE

    _, result = parsed(tmp_path / "b", [row(JUL1, "1000.25", recv=at(JUL1, 20, 45), sequence=1)])
    cdt = datetime(2026, 7, 1, 15, 40, tzinfo=timezone(timedelta(hours=-5)))
    cst = datetime(2026, 7, 1, 15, 40, tzinfo=timezone(timedelta(hours=-6)))
    assert get_final_settlement_asof(result.events, CONTRACT, JUL1, cdt, accepted_evidence=E.VENDOR_CAPTURE).status is P.NOT_AVAILABLE
    answer = get_final_settlement_asof(result.events, CONTRACT, JUL1, cst, accepted_evidence=E.VENDOR_CAPTURE)
    assert (answer.status, answer.cutoff_at, answer.cutoff_at.utcoffset()) == (P.AVAILABLE, at(JUL1, 21, 40), timedelta(0))

    early_manifest, early = parsed(tmp_path / "c", [row(JUL2, "1000.25", recv=at(JUL1, 21, 0), sequence=1)])
    timing = check(quality(early_manifest, early), "TIMESTAMP_TIMEZONE")
    assert (timing.status, timing.reasons) == (Q.BLOCKED, ("TIMESTAMP_BEFORE_TRADING_DATE",))

    odd_manifest, odd = parsed(tmp_path / "d", [row(JUL1, "1000.25", recv=at(JUL1, 21, 30), ts_ref=ns(at(JUL1, 5, 0)))])
    assert (odd.events, blocking(odd)) == ((), ["SCHEMA_TS_REF_NOT_DATE"])
    assert check(quality(odd_manifest, odd), "SCHEMA").status is Q.BLOCKED


def test_incomplete_timestamps_never_make_a_price_available(tmp_path):
    """요구 10. 입력: (a) 7-1: 공급자 수집 시각이 없고(UNDEF) 거래소 시각 20:30Z만 있는 최종가, (b) 7-2: 두 시각이 모두 없는 최종가,
    (c) 7-6: 수집 시각 21:30Z인 최종가와, 수집 시각 없이 거래소 시각 21:40Z만 있는 같은 날 최종가.
    출력: (a) 공급자 수집 근거를 요구하면 23:00Z에 EVIDENCE_INSUFFICIENT (가격 없음)이고, 거래소 시각까지 받아들이면 AVAILABLE (근거
    EXCHANGE_PUBLICATION). 12:00Z에는 거래소 시각도 미래이므로 아직 없는 기록이다 (NO_VISIBLE_RECORD, 존재를 드러내지 않음). (b) 거래소
    시각까지 받아들여도 EVIDENCE_INSUFFICIENT. (c) 보이는 최종가가 있어도 근거 없는 같은 날 기록 때문에 EVIDENCE_INSUFFICIENT. 7-1 23:00Z
    As-of Series에는 7-1만 근거 부족으로 제외되어 있다 (아직 시작하지 않은 7-2, 미래 기록뿐인 7-6은 없음). 시각과 맞지 않는 근거 표시는
    ValueError. 품질 검사 AVAILABILITY_EVIDENCE는 WARNING."""
    rows = [row(JUL1, "1000.25", recv=None, event=at(JUL1, 20, 30), sequence=1),
            row(JUL2, "1000.50", recv=None, event_ns=UNDEF_TIMESTAMP, sequence=2),
            row(JUL6, "1000.75", recv=at(JUL6, 21, 30), sequence=3),
            row(JUL6, "1000.75", recv=None, event=at(JUL6, 21, 40), sequence=4)]
    manifest, result = parsed(tmp_path, rows)
    assert [e.availability_evidence for e in result.events] == [E.EXCHANGE_PUBLICATION, E.SYSTEM_RECEIPT, E.VENDOR_CAPTURE,
                                                               E.EXCHANGE_PUBLICATION]
    with pytest.raises(ValueError):
        dataclasses.replace(result.events[0], availability_evidence=E.VENDOR_CAPTURE)

    vendor = get_final_settlement_asof(result.events, CONTRACT, JUL1, at(JUL1, 23, 0), accepted_evidence=E.VENDOR_CAPTURE)
    assert (vendor.status, vendor.price, vendor.reasons) == (P.EVIDENCE_INSUFFICIENT, None, ("MISSING_EVIDENCE_TIME",))
    exchange = get_final_settlement_asof(result.events, CONTRACT, JUL1, at(JUL1, 23, 0), accepted_evidence=E.EXCHANGE_PUBLICATION)
    assert (exchange.status, exchange.price, exchange.evidence_used) == (P.AVAILABLE, Decimal("1000.25"), E.EXCHANGE_PUBLICATION)
    noon = get_final_settlement_asof(result.events, CONTRACT, JUL1, at(JUL1, 12, 0), accepted_evidence=E.VENDOR_CAPTURE)
    assert (noon.status, noon.reasons) == (P.NOT_AVAILABLE, ("NO_VISIBLE_RECORD",))
    bare = get_final_settlement_asof(result.events, CONTRACT, JUL2, at(JUL2, 23, 0), accepted_evidence=E.EXCHANGE_PUBLICATION)
    assert (bare.status, bare.price) == (P.EVIDENCE_INSUFFICIENT, None)
    mixed = get_final_settlement_asof(result.events, CONTRACT, JUL6, at(JUL6, 23, 0), accepted_evidence=E.VENDOR_CAPTURE)
    assert (mixed.status, mixed.price) == (P.EVIDENCE_INSUFFICIENT, None)
    series = asof_final_series(result.events, CONTRACT, at(JUL1, 23, 0), accepted_evidence=E.VENDOR_CAPTURE)
    assert (series.points, [(x.trading_date, x.status) for x in series.excluded]) == ((), [(JUL1, P.EVIDENCE_INSUFFICIENT)])
    evidence = check(quality(manifest, result), "AVAILABILITY_EVIDENCE")
    assert (evidence.status, evidence.reasons) == (Q.WARNING, ("EXCHANGE_TIME_ONLY", "SYSTEM_RECEIPT_ONLY"))


def test_missing_sessions_are_reported_and_never_filled(tmp_path):
    """요구 11 (ADR-0007 X7-2·X7-3·X7-6). 입력: 최종가가 7-1, 7-6에만 있음. (a) 7-1~7-6을 덮는 합성 달력 (7-1, 7-2, 7-6), 확인 수준
    UNVERIFIED와 CONFIRMED, (b) 달력 없음, (c) 7-2까지만 덮는 달력, (d) 7-1, 7-6만 거래일인 CONFIRMED 달력, (e) 7-6을 휴장으로 둔 달력.
    출력: (a) MISSING_SESSIONS WARNING, 빠진 거래일 7-2 (확인되지 않은 달력이라는 사유도 남고, CONFIRMED 달력에서도 결측 사유가 남음).
    Series에는 7-1, 7-6만 있고 7-2를 앞 값으로 채우지 않는다. (b) 달력이 없어 NOT_ASSESSABLE이고, 평일 공백(7-2, 7-3)은 휴장인지 결측인지
    모르는 미확인 공백으로만 보고한다. (c) 요청 기간을 덮지 않아 NOT_ASSESSABLE. (d) PASSED. (e) 달력에 없는 날의 최종가는 DATE_AND_EXPIRY
    경고 (NOT_IN_EXPECTED_CALENDAR)."""
    rows = session(JUL1, "1000.25", sequence=1) + session(JUL6, "1001.00", sequence=3)
    manifest, result = parsed(tmp_path, rows)

    known = quality(manifest, result, calendar=calendar_of((JUL1, JUL2, JUL6), JUL1, JUL6), end=JUL6)
    assert (check(known, "MISSING_SESSIONS").status, check(known, "MISSING_SESSIONS").reasons, known.missing_trading_dates) == (
        Q.WARNING, ("CALENDAR_NOT_CONFIRMED", "MISSING_TRADING_DATES"), (JUL2,))
    holiday = quality(manifest, result, calendar=calendar_of((JUL1, JUL2), JUL1, JUL6, VerificationLevel.CONFIRMED), end=JUL6)
    assert (check(holiday, "DATE_AND_EXPIRY").status, check(holiday, "DATE_AND_EXPIRY").reasons) == (Q.WARNING, ("NOT_IN_EXPECTED_CALENDAR",))
    confirmed = quality(manifest, result, calendar=calendar_of((JUL1, JUL2, JUL6), JUL1, JUL6, VerificationLevel.CONFIRMED), end=JUL6)
    missing = check(confirmed, "MISSING_SESSIONS")
    assert (missing.status, missing.reasons, missing.findings[0].refs) == (Q.WARNING, ("MISSING_TRADING_DATES",), ("2026-07-02",))
    assert [p.trading_date for p in latest_final_series(result.events, CONTRACT).points] == [JUL1, JUL6]
    blind = quality(manifest, result, end=JUL6)
    assert (check(blind, "MISSING_SESSIONS").status, blind.unverified_gaps, blind.missing_trading_dates) == (
        Q.NOT_ASSESSABLE, (JUL2, date(2026, 7, 3)), ())
    short = quality(manifest, result, calendar=calendar_of((JUL1, JUL2), JUL1, JUL2), end=JUL6)
    assert check(short, "MISSING_SESSIONS").status is Q.NOT_ASSESSABLE and short.missing_trading_dates == ()
    complete = quality(manifest, result, calendar=calendar_of((JUL1, JUL6), JUL1, JUL6, VerificationLevel.CONFIRMED), end=JUL6)
    assert check(complete, "MISSING_SESSIONS").status is Q.PASSED


def test_raw_snapshot_is_preserved_and_any_change_is_detected(tmp_path):
    """요구 13·FR-01. 입력: 합성 원본 바이트를 보관하고, (a) 같은 바이트·같은 획득 정보로 다시 보관, (b) 같은 바이트를 다른 획득 시각으로
    보관, (c) 보관된 원본 한 바이트 변경, (d) 내용이 다른 원본, (e) 자격증명처럼 보이는 요청 매개변수, (f) Snapshot 디렉터리에 다른 파일
    추가, (g) Snapshot을 다른 ID 디렉터리로 복사, (h) manifest를 정규 형식으로 다시 써서 출처를 REAL로 바꿈, 정규 형식이 아닌 manifest,
    해석할 수 없는 형식 이름, (i) zstd로 압축된 원본.
    출력: Snapshot ID = "raw-sha256-" + SHA-256(원본)이고 원본 바이트가 그대로(쓰기 권한 없는 파일로) 돌아온다. (a) 같은 manifest (멱등).
    (b) RawSnapshotError (덮어쓰지 않음). (c)(f)(g) RawSnapshotIntegrityError. (d) 다른 Snapshot ID. (e) ValueError (자격증명을 기록하지
    않음). (h) 기록해 둔 manifest 해시로 읽으면 RawSnapshotIntegrityError, 정규 형식이 아니거나 형식 이름이 잘못된 manifest는 해시 없이도
    RawSnapshotIntegrityError. (i) 압축된 원본을 그대로 보관하고 같은 사건으로 번역한다."""
    rows = session(JUL1, "1000.25", sequence=1)
    raw = csv_bytes(rows)
    manifest = snapshot(tmp_path, rows)
    assert manifest.snapshot_id == "raw-sha256-" + hashlib.sha256(raw).hexdigest() and manifest.raw_sha256 == hashlib.sha256(raw).hexdigest()
    assert load(tmp_path, manifest) == (manifest, raw)
    assert snapshot(tmp_path, rows) == manifest
    with pytest.raises(RawSnapshotError):
        snapshot(tmp_path, rows, acquired_at=INGESTED + timedelta(hours=1))
    other = snapshot(tmp_path, session(JUL2, "1000.50", sequence=1))
    assert other.snapshot_id != manifest.snapshot_id
    with pytest.raises(ValueError):
        store_raw_snapshot(tmp_path / "keyed", raw, data_origin=DataOrigin.SYNTHETIC, provider="databento", dataset="GLBX.MDP3",
                           schema="statistics", encoding="csv", original_filename="x.csv", acquired_at=INGESTED,
                           acquisition_method="SYNTHETIC_FIXTURE", request=(("api_key", "redacted"),))

    stored = tmp_path / "raw" / manifest.snapshot_id / "raw.csv"
    assert stat.S_IMODE(stored.stat().st_mode) & 0o222 == 0  # 쓰기 권한 없음 (읽기 권한은 umask를 따름)
    stored.chmod(0o600)
    changed = bytearray(stored.read_bytes())
    changed[-2] = ord("9") if changed[-2] != ord("9") else ord("8")
    stored.write_bytes(bytes(changed))
    with pytest.raises(RawSnapshotIntegrityError):
        load(tmp_path, manifest)

    copied = tmp_path / "raw" / ("raw-sha256-" + "f" * 64)
    shutil.copytree(tmp_path / "raw" / other.snapshot_id, copied)
    with pytest.raises(RawSnapshotIntegrityError):
        load_raw_snapshot(tmp_path / "raw", copied.name, expected_manifest_sha256=None)
    (tmp_path / "raw" / other.snapshot_id / "extra.txt").write_bytes(b"x")
    with pytest.raises(RawSnapshotIntegrityError):
        load(tmp_path, other)

    third = snapshot(tmp_path, session(JUL6, "1000.75", sequence=1))
    written = tmp_path / "raw" / third.snapshot_id / "manifest.json"
    written.chmod(0o600)
    written.write_bytes(encode_manifest(dataclasses.replace(third, data_origin=DataOrigin.REAL)))
    with pytest.raises(RawSnapshotIntegrityError):
        load(tmp_path, third)
    # 정규 형식이 아닌 manifest와 해석할 수 없는 형식 이름은 고정 해시 없이 읽어도 무결성 오류다.
    for text in (json.dumps(json.loads(encode_manifest(third)), indent=1) + "\n",
                 encode_manifest(third).decode("utf-8").replace('"encoding":"csv"', '"encoding":"CSV"')):
        written.write_bytes(text.encode("utf-8"))
        with pytest.raises(RawSnapshotIntegrityError):
            load_raw_snapshot(tmp_path / "raw", third.snapshot_id, expected_manifest_sha256=None)

    compression = pytest.importorskip("compression.zstd")
    packed = compression.compress(raw)
    zst = store_raw_snapshot(tmp_path / "zst", packed, data_origin=DataOrigin.SYNTHETIC, provider="databento", dataset="GLBX.MDP3",
                             schema="statistics", encoding="csv.zst", original_filename="synthetic.csv.zst", acquired_at=INGESTED,
                             acquisition_method="SYNTHETIC_FIXTURE", request=())
    assert load_raw_snapshot(tmp_path / "zst", zst.snapshot_id, expected_manifest_sha256=manifest_sha256(zst))[1] == packed
    unpacked = parse_databento_statistics(packed, manifest=zst, mapping=MAPPING, metadata=MES_SEP26)
    plain = parse_databento_statistics(raw, manifest=manifest, mapping=MAPPING, metadata=MES_SEP26)
    assert [(e.trading_date, e.price, e.revision_status) for e in unpacked.events] == [
        (e.trading_date, e.price, e.revision_status) for e in plain.events]


def test_schema_problems_and_other_statistics_are_handled_explicitly(tmp_path):
    """FR-06 SCHEMA. 입력: (a) symbol 열이 없는 파일, (b) 가격이 정수가 아닌 텍스트 "1000.25", (c) 정산가가 아닌 통계(stat_type 9)와
    값 없는 가격(INT64_MAX)의 정산가.
    출력: (a) SCHEMA_COLUMNS 문제로 사건이 없고 SCHEMA BLOCKED. (b) SCHEMA_INVALID_INTEGER. (c) 다른 통계는 건너뛰고 종류별로 센다. 값 없는
    정산가는 PRICE_UNDEFINED 문제이며 0이나 이전 값으로 채우지 않는다."""
    no_symbol = [c for c in STATISTICS_COLUMNS if c != "symbol"]
    manifest, result = parsed(tmp_path, session(JUL1, "1000.25", sequence=1), columns=no_symbol)
    assert (result.events, blocking(result)) == ((), ["SCHEMA_COLUMNS"])
    assert check(quality(manifest, result), "SCHEMA").status is Q.BLOCKED

    bad = row(JUL1, "1000.25", recv=at(JUL1, 21, 30), sequence=1)
    bad["price"] = "1000.25"
    _, text_price = parsed(tmp_path / "b", [bad])
    assert (text_price.events, blocking(text_price)) == ((), ["SCHEMA_INVALID_INTEGER"])

    _, mixed = parsed(tmp_path / "c", [row(JUL1, "1000.25", recv=at(JUL1, 21, 30), sequence=1),
                                       row(JUL1, "5000", recv=at(JUL1, 22, 0), sequence=2, stat_type=9),
                                       row(JUL2, None, recv=at(JUL2, 21, 30), sequence=3)])
    assert (len(mixed.events), mixed.rows_total, mixed.rows_by_stat_type, blocking(mixed)) == (1, 3, ((3, 2), (9, 1)), ["PRICE_UNDEFINED"])
    assert mixed.adapter_version == ADAPTER_VERSION


def test_adapter_rejects_unknown_flags_actions_rtypes_conflicting_ids_and_foreign_bytes(tmp_path):
    """FR-02·FR-06 Adapter 방어. 입력: 정상 최종가와 함께 (a) 해석하지 않는 stat_flags bit(16), (b) update_action 3, (c) rtype 23, (d) 같은
    레코드 ID(같은 수집 시각·sequence)에 가격은 같고 상태만 다른 두 줄, (e) 20자를 넘는 정수 텍스트, (f) manifest와 다른 바이트, (g) 열 수가
    다른 행, (h) 같은 열 이름이 두 번 있는 header, (i) 다른 공급자의 Snapshot과 다른 dataset의 대응표.
    출력: (a)~(e)는 사건이 되지 않고 각각 차단 문제로 남는다 (d는 두 줄 모두 버림, e는 예외 없이 SCHEMA_INVALID_INTEGER). 정상 최종가 하나만
    사건이 된다. (f)(i) ValueError. (g) SCHEMA_ROW_LENGTH. (h) SCHEMA_COLUMNS."""
    long_number = row(JUL1, "1000.25", recv=at(JUL1, 21, 40), sequence=6)
    long_number["quantity"] = "1" * 5000
    rows = [row(JUL1, "1000.25", recv=at(JUL1, 21, 30), sequence=1),
            row(JUL1, "1000.25", recv=at(JUL1, 21, 31), flags=FINAL | ACTUAL | 16, sequence=2),
            row(JUL1, "1000.25", recv=at(JUL1, 21, 32), update_action=3, sequence=3),
            dict(row(JUL1, "1000.25", recv=at(JUL1, 21, 33), sequence=4), rtype=23),
            row(JUL1, "1000.25", recv=at(JUL1, 21, 35), sequence=5),
            row(JUL1, "1000.25", recv=at(JUL1, 21, 35), flags=ACTUAL, sequence=5),
            long_number]
    manifest, result = parsed(tmp_path, rows)
    assert [event.source_record_id.split(":")[-2] for event in result.events] == ["1"]
    assert sorted(blocking(result)) == ["SCHEMA_INVALID_INTEGER", "SCHEMA_RTYPE", "SCHEMA_STAT_FLAGS", "SCHEMA_UPDATE_ACTION",
                                        "SOURCE_RECORD_ID_CONFLICT"]
    _, raw = load(tmp_path, manifest)
    with pytest.raises(ValueError):
        parse_databento_statistics(csv_bytes(rows[:1]), manifest=manifest, mapping=MAPPING, metadata=MES_SEP26)
    with pytest.raises(ValueError):
        parse_databento_statistics(raw, manifest=manifest, mapping=dataclasses.replace(MAPPING, dataset="XNAS.ITCH"), metadata=MES_SEP26)

    def stored(name, data, provider="databento"):
        manifest = store_raw_snapshot(tmp_path / name, data, data_origin=DataOrigin.SYNTHETIC, provider=provider, dataset="GLBX.MDP3",
                                      schema="statistics", encoding="csv", original_filename="synthetic.csv", acquired_at=INGESTED,
                                      acquisition_method="SYNTHETIC_FIXTURE", request=())
        return parse_databento_statistics(data, manifest=manifest, mapping=MAPPING, metadata=MES_SEP26)

    assert blocking(stored("long_row", csv_bytes(rows[:1]) + b"1,2,3\n")) == ["SCHEMA_ROW_LENGTH"]
    assert blocking(stored("twice", csv_bytes(rows[:1], columns=(*STATISTICS_COLUMNS, "symbol")))) == ["SCHEMA_COLUMNS"]
    with pytest.raises(ValueError):
        stored("vendor", csv_bytes(rows[:1]), provider="another-vendor")


def test_quality_flags_broken_links_impossible_times_expiry_range_and_conflicts(tmp_path):
    """FR-06. 입력: 정상 최종가(7-1, 7-6, 7-7), 가격 0인 7-8 최종가, 6-30 잠정가, 9-21(마지막 거래일 2026-09-18 뒤) 최종가와 그 정정, 시각이
    하나도 없는 7-2 잠정가·최종가. 사건 일부를 바꿈: 7-1 수신 시각을 Snapshot 획득 시각과 다르게, 7-6 공급자 수집 시각을 수신 뒤로, 7-7
    Snapshot ID를 없는 것으로. 그리고 7-1 원래 기록과 같은 ID에 다른 가격을 가진 다른 Snapshot.
    출력: SOURCE_INTEGRITY는 INGESTED_AT_NOT_ACQUISITION_TIME·UNKNOWN_SOURCE_SNAPSHOT (차단), TIMESTAMP_TIMEZONE은
    INGESTED_BEFORE_SOURCE_TIME (차단), DATE_AND_EXPIRY는 AFTER_LAST_TRADING_DATE (차단)와 OUTSIDE_REQUESTED_RANGE, DECIMAL_PRICE는
    NON_POSITIVE_PRICE (차단), 순서를 정할 수 없는 7-2는 UNORDERED_RECORDS (차단). 요청 기간 밖의 최종가·제외·정정은 보고서의 유효 거래일,
    제외 목록, 정정 목록에 넣지 않는다. 다른 Snapshot의 같은 ID 다른 내용은 SOURCE_RECORD_ID_CONFLICT (차단)다."""
    jul7, jul8, jun30, sep21 = date(2026, 7, 7), date(2026, 7, 8), date(2026, 6, 30), date(2026, 9, 21)
    rows = [row(JUL1, "1000.25", recv=at(JUL1, 21, 30), sequence=1),
            row(jun30, "1000.00", recv=at(jun30, 21, 30), flags=ACTUAL, sequence=2),
            row(sep21, "1000.50", recv=at(sep21, 21, 30), sequence=3),
            row(JUL2, "1000.00", recv=None, event_ns=UNDEF_TIMESTAMP, flags=ACTUAL, sequence=4),
            row(JUL2, "1000.50", recv=None, event_ns=UNDEF_TIMESTAMP, sequence=5),
            row(JUL6, "1000.75", recv=at(JUL6, 21, 30), sequence=6),
            row(jul7, "1001.00", recv=at(jul7, 21, 30), sequence=7),
            row(jul8, "0", recv=at(jul8, 21, 30), sequence=8),
            row(sep21, "1000.75", recv=at(date(2026, 9, 22), 9, 0), sequence=9)]
    manifest, result = parsed(tmp_path, rows)
    events = list(result.events)
    events[0] = dataclasses.replace(events[0], ingested_at=INGESTED + timedelta(hours=1))
    events[5] = dataclasses.replace(events[5], vendor_received_at=INGESTED + timedelta(days=1))
    events[6] = dataclasses.replace(events[6], source_snapshot_id="raw-sha256-" + "0" * 64)
    report = assess_settlement_quality(metadata=MES_SEP26, manifests=(manifest,), events=events, issues=result.issues,
                                       requested_start=JUL1, requested_end=date(2026, 8, 31), minimum_final_days=1, calendar=None)

    assert (check(report, "SOURCE_INTEGRITY").status, check(report, "SOURCE_INTEGRITY").reasons) == (
        Q.BLOCKED, ("DATA_ORIGIN_SYNTHETIC", "INGESTED_AT_NOT_ACQUISITION_TIME", "UNKNOWN_SOURCE_SNAPSHOT"))
    assert (check(report, "TIMESTAMP_TIMEZONE").status, check(report, "TIMESTAMP_TIMEZONE").reasons) == (
        Q.BLOCKED, ("INGESTED_BEFORE_SOURCE_TIME",))
    assert (check(report, "DATE_AND_EXPIRY").status, check(report, "DATE_AND_EXPIRY").reasons) == (
        Q.BLOCKED, ("AFTER_LAST_TRADING_DATE", "OUTSIDE_REQUESTED_RANGE"))
    assert (check(report, "DECIMAL_PRICE").status, check(report, "DECIMAL_PRICE").reasons) == (Q.BLOCKED, ("NON_POSITIVE_PRICE",))
    conflicts = check(report, "DUPLICATES_AND_CONFLICTS")
    assert (conflicts.status, conflicts.reasons) == (Q.BLOCKED, ("UNORDERED_RECORDS",))
    assert "FINAL_CORRECTED" in check(report, "REVISION_ORDER").reasons
    assert (report.final_trading_dates, [x.trading_date for x in report.excluded], report.corrected_trading_dates) == (
        (JUL1, JUL6, jul7, jul8), [JUL2], ())

    rival_manifest, rival = parsed(tmp_path, [row(JUL1, "1000.30", recv=at(JUL1, 21, 30), sequence=1)],
                                   acquired_at=INGESTED + timedelta(days=2))
    both = assess_settlement_quality(metadata=MES_SEP26, manifests=(manifest, rival_manifest), events=result.events + rival.events,
                                     issues=result.issues + rival.issues, requested_start=JUL1, requested_end=date(2026, 8, 31),
                                     minimum_final_days=1, calendar=None)
    conflicts = check(both, "DUPLICATES_AND_CONFLICTS")
    assert conflicts.status is Q.BLOCKED and "SOURCE_RECORD_ID_CONFLICT" in conflicts.reasons


def test_quality_report_blocks_synthetic_origin_and_thin_coverage(tmp_path):
    """FR-06 SOURCE_INTEGRITY·COVERAGE, 완료 판정 보호. 입력: 합성 Snapshot의 정상 최종가 2일, 최소 유효 거래일 20.
    출력: SOURCE_INTEGRITY BLOCKED (DATA_ORIGIN_SYNTHETIC), COVERAGE BLOCKED (2 < 20). 보고서 전체는 BLOCKED다. 합성 데이터는 어떤 경우에도
    실데이터 판정을 통과하지 않는다."""
    manifest, result = parsed(tmp_path, session(JUL1, "1000.25", sequence=1) + session(JUL2, "1000.50", sequence=3))
    report = quality(manifest, result, minimum=20)
    assert (check(report, "SOURCE_INTEGRITY").status, check(report, "SOURCE_INTEGRITY").reasons) == (Q.BLOCKED, ("DATA_ORIGIN_SYNTHETIC",))
    assert (check(report, "COVERAGE").status, report.final_trading_dates) == (Q.BLOCKED, (JUL1, JUL2))
    assert report.status is Q.BLOCKED and report.rule_version == QUALITY_RULE_VERSION
    assert "USER_RECEIPT_TIME" in report.not_established
    assert {"MAPPING_NOT_CONFIRMED", "METADATA_NOT_CONFIRMED"} <= set(check(report, "CONTRACT_IDENTITY").reasons)
    assert check(report, "PRICE_UNIT").reasons == ("PRICE_UNIT_NOT_CONFIRMED",)


def test_domain_results_reject_contradictions(tmp_path):
    """도메인 불변조건. 입력: 정상 PIT 결과·As-of Series·manifest·사건을 모순되게 바꾼 값.
    출력: cutoff보다 늦은 이용 가능 시각, 받아들인 근거보다 약한 근거, 사건의 가장 이른 시각과 다른 이용 가능 시각, cutoff 뒤에 보인 As-of 점,
    원본 해시와 맞지 않는 Snapshot ID, 가격 없는 최종가는 모두 ValueError."""
    manifest, result = parsed(tmp_path, [row(JUL1, "1000.25", recv=at(JUL1, 21, 30), sequence=1)])
    answer = get_final_settlement_asof(result.events, CONTRACT, JUL1, at(JUL1, 23, 0), accepted_evidence=E.VENDOR_CAPTURE)
    series = asof_final_series(result.events, CONTRACT, at(JUL1, 23, 0), accepted_evidence=E.VENDOR_CAPTURE)
    assert (answer.status, answer.available_at, len(series.points)) == (P.AVAILABLE, at(JUL1, 21, 30), 1)
    contradictions = [
        lambda: dataclasses.replace(answer, cutoff_at=at(JUL1, 21, 29)),
        lambda: dataclasses.replace(answer, accepted_evidence=E.SYSTEM_RECEIPT),
        lambda: dataclasses.replace(answer, available_at=at(JUL1, 21, 0)),
        lambda: dataclasses.replace(answer, accepted_evidence=E.EXCHANGE_PUBLICATION),
        lambda: dataclasses.replace(series, cutoff_at=at(JUL1, 21, 29)),
        lambda: dataclasses.replace(manifest, snapshot_id="raw-sha256-" + "0" * 64),
        lambda: dataclasses.replace(result.events[0], price=None),
    ]
    for build in contradictions:
        with pytest.raises(ValueError):
            build()


def test_large_fixed_point_prices_stay_exact_through_export(tmp_path):
    """가격은 float를 거치지 않는다. 입력: 고정소수점 정수 2^63 − 2 (= 9223372036.854775806, float로는 정확히 나타낼 수 없는 값)인 합성 최종가.
    출력: 사건 가격, 정규화 파일, 최신 최종가 Series 파일의 가격이 모두 정확히 9223372036.854775806이다."""
    manifest, result = parsed(tmp_path, [row(JUL1, "9223372036.854775806", recv=at(JUL1, 21, 30), sequence=1)])
    assert result.events[0].price == Decimal("9223372036.854775806") and float(result.events[0].price) != result.events[0].price
    report = quality(manifest, result)
    write_settlement_dataset(tmp_path / "out", metadata=MES_SEP26, manifests=(manifest,), adapter_version=result.adapter_version,
                             events=result.events, report=report, latest=latest_final_series(result.events, CONTRACT), asof=(),
                             run_started_at=INGESTED)
    normalized = json.loads((tmp_path / "out" / "normalized_settlements.json").read_text(encoding="utf-8"))
    latest = json.loads((tmp_path / "out" / "research_settlements_latest_final.json").read_text(encoding="utf-8"))
    assert normalized["events"][0]["price"] == latest["points"][0]["price"] == "9223372036.854775806"


def test_export_refuses_untraceable_or_mismatched_inputs(tmp_path):
    """FR-08 추적성. 입력: 같은 cutoff·근거의 As-of Series 두 개, 다른 월물의 Series, 다른 Snapshot으로 만든 품질 보고서, 함께 넘기지 않은
    Snapshot을 가리키는 사건과 점, 다른 월물의 사건.
    출력: 모두 ValueError이며 출력 디렉터리를 만들지 않는다."""
    manifest, result = parsed(tmp_path, session(JUL1, "1000.25", sequence=1))
    other_manifest, other = parsed(tmp_path, session(JUL2, "1000.50", sequence=1))
    report = quality(manifest, result)
    latest = latest_final_series(result.events, CONTRACT)
    asof = asof_final_series(result.events, CONTRACT, at(JUL1, 23, 0), accepted_evidence=E.VENDOR_CAPTURE)
    other_report = quality(other_manifest, result)
    foreign_event = dataclasses.replace(result.events[1], contract_id=OTHER_CONTRACT)
    cases = [
        dict(manifests=(manifest,), events=result.events, report=report, latest=latest, asof=(asof, asof)),
        dict(manifests=(manifest,), events=result.events, report=report, latest=latest_final_series(result.events, OTHER_CONTRACT), asof=()),
        dict(manifests=(other_manifest,), events=other.events, report=report, latest=latest_final_series(other.events, CONTRACT), asof=()),
        dict(manifests=(other_manifest,), events=result.events, report=other_report, latest=latest, asof=()),
        dict(manifests=(manifest,), events=(result.events[0], foreign_event), report=report, latest=latest, asof=()),
    ]
    for case in cases:
        with pytest.raises(ValueError):
            write_settlement_dataset(tmp_path / "out", metadata=MES_SEP26, adapter_version=result.adapter_version, run_started_at=INGESTED,
                                     **case)
        assert not (tmp_path / "out").exists()


def test_build_is_reproducible_and_series_trace_back_to_the_raw_snapshot(tmp_path):
    """요구 12·FR-07·FR-08. 입력: 합성 거래일 20일(7-1부터 평일)의 잠정·최종가 Snapshot과 그 20일을 덮는 합성 달력. 같은 Snapshot으로 두 번
    조립·내보내기 (실행 시각만 다름), As-of cutoff 7-10 23:00Z (공급자 수집 근거).
    출력: run_log.json을 뺀 산출물이 바이트 단위로 같고, 처리 manifest가 각 산출물의 SHA-256과 원본·manifest 해시, 획득 시각, Adapter·품질
    규칙·메타데이터 판본·선택 정책을 기록한다. 최신 최종가 Series와 As-of Series는 파일 이름과 basis로 구분되고 모든 점이 원본 Snapshot ID를
    가진다. As-of Series에는 cutoff까지 보인 8개 거래일만 있고 뒤의 거래일은 제외 목록에도 없다. 실행 기록은 실행마다 다르다. 이미 있는 출력
    디렉터리에는 쓰지 않는다."""
    days = weekdays(JUL1, 20)
    rows = [item for index, day in enumerate(days) for item in session(day, str(Decimal("1000") + Decimal("0.25") * index), sequence=2 * index + 1)]
    manifest = snapshot(tmp_path, rows)
    cutoff = at(date(2026, 7, 10), 23, 0)

    def build(name, started):
        loaded, raw = load(tmp_path, manifest)
        result = parse_databento_statistics(raw, manifest=loaded, mapping=MAPPING, metadata=MES_SEP26)
        report = assess_settlement_quality(metadata=MES_SEP26, manifests=(loaded,), events=result.events, issues=result.issues,
                                           requested_start=days[0], requested_end=days[-1], minimum_final_days=20,
                                           calendar=calendar_of(days, days[0], days[-1]))
        latest = latest_final_series(result.events, CONTRACT)
        asof = asof_final_series(result.events, CONTRACT, cutoff, accepted_evidence=E.VENDOR_CAPTURE)
        export = write_settlement_dataset(tmp_path / name, metadata=MES_SEP26, manifests=(loaded,), adapter_version=result.adapter_version,
                                          events=result.events, report=report, latest=latest, asof=(asof,), run_started_at=started)
        return report, export

    report, first = build("out1", datetime(2026, 10, 22, 10, 0, tzinfo=UTC))
    _, second = build("out2", datetime(2026, 10, 22, 11, 0, tzinfo=UTC))
    with pytest.raises(SettlementExportError):
        build("out1", datetime(2026, 10, 22, 12, 0, tzinfo=UTC))

    files = sorted(p.name for p in (tmp_path / "out1").iterdir())
    assert files == sorted(["normalized_settlements.json", "research_settlements_latest_final.json",
                            "research_settlements_asof_20260710T230000Z_VENDOR_CAPTURE.json", "quality_report.json",
                            "processed_manifest.json", "run_log.json"])
    for name in files:
        same = (tmp_path / "out1" / name).read_bytes() == (tmp_path / "out2" / name).read_bytes()
        assert same is (name != "run_log.json")
    manifest_doc = json.loads((tmp_path / "out1" / "processed_manifest.json").read_text(encoding="utf-8"))
    assert manifest_doc["raw_snapshots"] == [{"acquired_at": "2026-10-22T09:00:00.000000Z", "data_origin": "SYNTHETIC",
                                              "manifest_sha256": manifest_sha256(manifest), "raw_sha256": manifest.raw_sha256,
                                              "snapshot_id": manifest.snapshot_id}]
    assert manifest_sha256(manifest) == hashlib.sha256((tmp_path / "raw" / manifest.snapshot_id / "manifest.json").read_bytes()).hexdigest()
    assert (manifest_doc["adapter_version"], manifest_doc["quality_rule_version"], manifest_doc["metadata_version"],
            manifest_doc["selection_policy"]) == (ADAPTER_VERSION, QUALITY_RULE_VERSION, "cme-mes-2026-09/1", SELECTION_POLICY)
    for name, digest in manifest_doc["outputs"].items():
        assert hashlib.sha256((tmp_path / "out1" / name).read_bytes()).hexdigest() == digest
    assert "run_log.json" not in manifest_doc["outputs"] and len(manifest_doc["outputs"]) == 4
    assert first.processed_manifest_sha256 == second.processed_manifest_sha256
    run_log = json.loads((tmp_path / "out1" / "run_log.json").read_text(encoding="utf-8"))
    assert (run_log["run_started_at"], run_log["processed_manifest_sha256"]) == ("2026-10-22T10:00:00.000000Z", first.processed_manifest_sha256)

    latest = json.loads((tmp_path / "out1" / "research_settlements_latest_final.json").read_text(encoding="utf-8"))
    asof = json.loads((tmp_path / "out1" / "research_settlements_asof_20260710T230000Z_VENDOR_CAPTURE.json").read_text(encoding="utf-8"))
    assert (latest["basis"], latest["cutoff_at"], len(latest["points"])) == ("LATEST_FINAL_IN_SNAPSHOT", None, 20)
    assert (asof["basis"], asof["cutoff_at"], asof["excluded"]) == ("AS_OF_CUTOFF", "2026-07-10T23:00:00.000000Z", [])
    assert [point["trading_date"] for point in asof["points"]] == [day.isoformat() for day in days[:8]]
    assert (asof["points"][0]["available_at"], asof["points"][0]["evidence_used"]) == ("2026-07-01T21:30:00.000000Z", "VENDOR_CAPTURE")
    assert {point["source_snapshot_id"] for point in latest["points"] + asof["points"]} == {manifest.snapshot_id}
    assert latest["points"][0]["price"] == "1000.000000000" and latest["points"][1]["price"] == "1000.250000000"
    assert report.status is Q.BLOCKED and check(report, "COVERAGE").status is Q.PASSED and report.missing_trading_dates == ()
