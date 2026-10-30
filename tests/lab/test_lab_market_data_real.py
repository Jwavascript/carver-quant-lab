"""P1-01 실데이터 통합 테스트 (요구 14). 실제 MESU6 Databento `statistics` Snapshot이 있을 때만 실행하고, 기본 실행에서는 skip한다.

합성 테스트(`test_lab_market_data.py`)와 분리되어 있으며 가격을 만들지 않는다. 원본은 저장소 밖에서 받아 `store_raw_snapshot`으로
보관한 것만 읽는다. 자격증명(API 키)은 이 테스트, 설정 파일, 저장소 어디에도 두지 않는다 (CLAUDE.md §5).

실행: 환경 변수 `CARVER_P1_01_REAL_DATA_CONFIG`에 저장소 밖 JSON 설정 파일 경로를 준다. 설정 키:
- `raw_root`: Raw Snapshot root (저장소 밖)
- `snapshots`: `{"snapshot_id": ..., "manifest_sha256": ...}` 목록. manifest 해시는 보관할 때 `manifest_sha256`으로 기록해 둔 값이다
- `databento_instrument_id`, `mapping_source`, `mapping_verification`: MESU6 대응표 (Databento symbology 등 출처와 확인 수준)
- `calendar`: 없으면 null. 있으면 `coverage_start`, `coverage_end`, `dates`, `sources`, `as_of`, `verification` (CME 휴장 달력 출처)
- `output_dir`: 산출물을 남길 저장소 밖 새 디렉터리. 없으면 null (pytest 임시 경로만 씀)

통과 조건 (P1-01 완료 조건의 데이터 부분): 원본이 REAL·databento·GLBX.MDP3·statistics이고 원본·manifest 해시가 맞음, 차단 문제 없음,
품질 보고서가 BLOCKED가 아님, 요청 기간 2026-07-01~2026-08-31에 최신 최종가가 있는 거래일 20일 이상, 최신 최종가의 모든 거래일에서 마지막
공급자 수집 시각 기준 PIT 답이 같은 기록·가격이고 그 이용 가능 시각 1µs 전에는 그 기록이 나오지 않음, 같은 Snapshot의 두 번 내보내기가
실행 기록 외에 바이트 단위로 같음. 받아들일 근거 수준(공급자 수집 시각)은 이 테스트의 검사용 선택이며 연구 정책으로 승인된 것이 아니다
(ADR-0004 Q4-3, D3A-13).
"""

import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from carver_quant.lab.adapters.databento_statistics import DatabentoInstrumentMapping, parse_databento_statistics
from carver_quant.lab.adapters.raw_snapshot import load_raw_snapshot
from carver_quant.lab.adapters.settlement_export import write_settlement_dataset
from carver_quant.lab.domain.market_data import (
    AvailabilityEvidence,
    DataOrigin,
    FuturesContractMetadata,
    PitStatus,
    PriceUnit,
    QualityStatus,
    ReferenceProvenance,
    SettlementType,
    TradingCalendarReference,
    VerificationLevel,
)
from carver_quant.lab.marketdata.quality import assess_settlement_quality
from carver_quant.lab.marketdata.settlements import asof_final_series, get_final_settlement_asof, latest_final_series

CONFIG_VARIABLE = "CARVER_P1_01_REAL_DATA_CONFIG"
CONTRACT = "CME.MES.2026-09"
REQUESTED_START, REQUESTED_END = date(2026, 7, 1), date(2026, 8, 31)
MINIMUM_FINAL_DAYS = 20
UTC = timezone.utc

# 작업 명세의 공식 메타데이터. CME 계약 사양 페이지는 이 환경에서 열리지 않아(403) CME 게시 FAQ·교육 자료·fact card로만 대조했다 (INFERRED).
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
    provenance=ReferenceProvenance(
        sources=(
            "https://www.cmegroup.com/articles/faqs/micro-e-mini-equity-index-futures-frequently-asked-questions.html",
            "https://www.cmegroup.com/education/courses/micro-e-mini-futures/micro-e-mini-futures-products-overview",
            "https://www.cmegroup.com/trading/equity-index/files/cme-micro-e-mini-futures-fact-card.pdf",
        ),
        as_of=datetime(2026, 10, 22, tzinfo=UTC),
        verification=VerificationLevel.INFERRED,
    ),
)


def _config() -> dict:
    path = os.environ.get(CONFIG_VARIABLE)
    if not path:
        pytest.skip(f"real MESU6 data is not configured ({CONFIG_VARIABLE} is unset); P1-01 real-data acceptance was not run")
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _instant(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)


def _calendar(spec: dict | None) -> TradingCalendarReference | None:
    if spec is None:
        return None
    return TradingCalendarReference(
        exchange="CME",
        coverage_start=date.fromisoformat(spec["coverage_start"]),
        coverage_end=date.fromisoformat(spec["coverage_end"]),
        dates=tuple(date.fromisoformat(item) for item in spec["dates"]),
        provenance=ReferenceProvenance(sources=tuple(spec["sources"]), as_of=_instant(spec["as_of"]),
                                       verification=VerificationLevel(spec["verification"])),
    )


def test_real_mesu6_settlements_meet_the_p1_01_data_criteria(tmp_path):
    """요구 14. 입력: 저장소 밖 설정이 가리키는 실제 MESU6 Raw Snapshot. 출력: 위 통과 조건. 실패하면 P1-01은 완료가 아니다."""
    config = _config()
    raw_root = Path(config["raw_root"])
    mapping = DatabentoInstrumentMapping(
        dataset="GLBX.MDP3",
        raw_symbol="MESU6",
        databento_instrument_id=config["databento_instrument_id"],
        contract_id=CONTRACT,
        price_unit=PriceUnit.INDEX_POINT,
        source=config["mapping_source"],
        verification=VerificationLevel(config["mapping_verification"]),
    )
    calendar = _calendar(config["calendar"])

    def build(out_dir: Path, started: datetime):
        manifests, events, issues, adapter_versions = [], [], [], set()
        for pinned in config["snapshots"]:
            manifest, raw = load_raw_snapshot(raw_root, pinned["snapshot_id"], expected_manifest_sha256=pinned["manifest_sha256"])
            assert (manifest.data_origin, manifest.provider, manifest.dataset, manifest.schema) == (
                DataOrigin.REAL, "databento", "GLBX.MDP3", "statistics")
            parsed = parse_databento_statistics(raw, manifest=manifest, mapping=mapping, metadata=MES_SEP26)
            manifests.append(manifest)
            events += parsed.events
            issues += parsed.issues
            adapter_versions.add(parsed.adapter_version)
        report = assess_settlement_quality(metadata=MES_SEP26, manifests=manifests, events=events, issues=issues,
                                           requested_start=REQUESTED_START, requested_end=REQUESTED_END,
                                           minimum_final_days=MINIMUM_FINAL_DAYS, calendar=calendar)
        latest = latest_final_series(events, CONTRACT)
        last_seen = max(event.vendor_received_at for event in events if event.vendor_received_at is not None)
        asof = asof_final_series(events, CONTRACT, last_seen, accepted_evidence=AvailabilityEvidence.VENDOR_CAPTURE)
        export = write_settlement_dataset(out_dir, metadata=MES_SEP26, manifests=manifests, adapter_version=adapter_versions.pop(),
                                          events=events, report=report, latest=latest, asof=(asof,), run_started_at=started)
        return events, issues, report, latest, export

    events, issues, report, latest, first = build(tmp_path / "first", datetime.now(UTC))
    assert [issue for issue in issues if issue.blocking] == []
    assert report.status is not QualityStatus.BLOCKED, [(c.name.value, c.status.value, c.reasons) for c in report.checks]
    assert len(report.final_trading_dates) >= MINIMUM_FINAL_DAYS

    # PIT: 마지막 수집 시각에는 최신 최종가와 같은 기록이 보이고, 그 기록의 이용 가능 시각 1µs 전에는 나오지 않는다 (미래 정보 차단).
    last_seen = max(event.vendor_received_at for event in events if event.vendor_received_at is not None)
    for point in latest.points:
        answer = get_final_settlement_asof(events, CONTRACT, point.trading_date, last_seen, accepted_evidence=AvailabilityEvidence.VENDOR_CAPTURE)
        assert (answer.status, answer.price, answer.event.source_record_id) == (PitStatus.AVAILABLE, point.price, point.source_record_id)
        earlier = get_final_settlement_asof(events, CONTRACT, point.trading_date, answer.available_at - timedelta(microseconds=1),
                                            accepted_evidence=AvailabilityEvidence.VENDOR_CAPTURE)
        assert earlier.event is None or earlier.event.source_record_id != answer.event.source_record_id

    *_, second = build(tmp_path / "second", datetime.now(UTC))
    assert first.processed_manifest_sha256 == second.processed_manifest_sha256
    for name, _ in first.outputs:
        assert (first.out_dir / name).read_bytes() == (second.out_dir / name).read_bytes()
    if config["output_dir"] is not None:
        build(Path(config["output_dir"]), datetime.now(UTC))
