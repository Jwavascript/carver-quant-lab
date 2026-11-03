"""P1-02 실데이터 통합 테스트 (요구 24~29). MESU6·MESZ6 실제 Databento Snapshot이 있을 때만 실행하고, 기본 실행에서는 skip한다.

합성 테스트(`test_lab_continuous_futures.py`)와 분리되어 있으며 가격을 만들지 않는다. 원본은 저장소 밖에서 받아 `store_raw_snapshot`
(`data_origin=REAL`)으로 보관한 것만 읽는다. 자격증명은 이 테스트, 설정 파일, 저장소 어디에도 두지 않는다 (CLAUDE.md §5).

실행: 환경 변수 `CARVER_P1_02_REAL_DATA_CONFIG`에 저장소 밖 JSON 설정 파일 경로를 준다. 설정 키:
- `contracts`: 월물 ID마다 `raw_symbol`, `databento_instrument_id`, `mapping_source`, `mapping_verification`, `statistics`(`raw_root`,
  `snapshots`: `{"snapshot_id", "manifest_sha256"}` 목록), `definition`(`raw_root`, `snapshots`: 같은 형식의 목록. 기간을 나눠 받은 월물은 여럿)
- `roll`: `plan_id`, `roll_reference_date`, `new_contract_first_date`, `evidence_cutoff_at`(`YYYY-MM-DDTHH:MM:SS.ffffffZ`), `selection_policy_id`.
  연구용 시나리오이며 실거래 롤 정책이 아니다
- `asof_cutoffs`: As-of 시계열을 만들 cutoff 목록, `output_dir`: 산출물을 남길 저장소 밖 새 디렉터리 (없으면 null)

통과 조건 (P1-02 완료 조건의 실데이터 부분): 두 월물 원본이 REAL·databento·GLBX.MDP3이고 원본·manifest 해시가 맞음, 메타데이터가 definition
Snapshot의 instrument ID·symbol·만기·계약 크기·tick·통화와 맞음, 두 월물에 최종가가 모두 있는 거래일 10일 이상, 롤 기준가가 known_at에 보이고
gap이 그 뒤 기록으로 바뀌지 않음, 롤 경계 변화가 신월물 자신의 변화와 같음, 원본 가격이 선택 월물의 최종가 그대로임, 연속 시계열·월물별 P1-01
품질 보고서가 BLOCKED가 아님, As-of 시계열이 cutoff 뒤 정보를 쓰지 않음, 같은 입력의 두 번 내보내기가 실행 기록 외에 같음. 받아들이는 근거
(공급자 수집 시각, VENDOR_CAPTURE_PROXY)는 연구용으로만 제한 승인되었다.
"""

import csv
import io
import json
import os
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from carver_quant.lab.adapters.continuous_export import write_continuous_dataset
from carver_quant.lab.adapters.databento_statistics import ADAPTER_VERSION, DatabentoInstrumentMapping, parse_databento_statistics
from carver_quant.lab.adapters.raw_snapshot import load_raw_snapshot
from carver_quant.lab.domain.continuous import ContinuousSeriesBasis, FuturesRollEvent, RollPlan, RollPlanEntry
from carver_quant.lab.domain.market_data import (
    AvailabilityEvidence,
    DataOrigin,
    FuturesContractMetadata,
    PriceUnit,
    QualityStatus,
    ReferenceProvenance,
    SettlementType,
    VerificationLevel,
)
from carver_quant.lab.marketdata.quality import QUALITY_RULE_VERSION, assess_settlement_quality
from carver_quant.lab.marketdata.settlements import SELECTION_POLICY, asof_final_series, get_final_settlement_asof
from carver_quant.lab.research.continuous import build_adjusted_series, resolve_roll_event
from carver_quant.lab.research.continuous_quality import assess_continuous_series

CONFIG_VARIABLE = "CARVER_P1_02_REAL_DATA_CONFIG"
UTC = timezone.utc
EVIDENCE = AvailabilityEvidence.VENDOR_CAPTURE
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
CME_SOURCES = (
    "https://www.cmegroup.com/articles/faqs/micro-e-mini-equity-index-futures-frequently-asked-questions.html",
    "https://www.cmegroup.com/trading/equity-index/files/cme-micro-e-mini-futures-fact-card.pdf",
)


def _metadata(contract_id, year, month, last_day, last_at):
    # 작업 명세·CME 공개 자료 기준 값 (INFERRED). 아래 테스트가 definition Snapshot과 대조한다.
    return FuturesContractMetadata(
        exchange="CME", product_root="MES", contract_id=contract_id, contract_year=year, contract_month=month, multiplier="5",
        outright_tick_size="0.25", outright_tick_value="1.25", settlement_tick_size=None, currency="USD", price_unit=PriceUnit.INDEX_POINT,
        last_trading_date=last_day, last_trading_at=last_at, settlement_type=SettlementType.CASH, metadata_version=f"cme-mes-{year}-{month:02d}/1",
        provenance=ReferenceProvenance(sources=CME_SOURCES, as_of=datetime(2026, 11, 3, tzinfo=UTC), verification=VerificationLevel.INFERRED))


METADATA = {
    "CME.MES.2026-09": _metadata("CME.MES.2026-09", 2026, 9, date(2026, 9, 18), datetime(2026, 9, 18, 13, 30, tzinfo=UTC)),
    "CME.MES.2026-12": _metadata("CME.MES.2026-12", 2026, 12, date(2026, 12, 18), datetime(2026, 12, 18, 14, 30, tzinfo=UTC)),
}


def _config() -> dict:
    path = os.environ.get(CONFIG_VARIABLE)
    if not path:
        pytest.skip(f"real MESU6/MESZ6 data is not configured ({CONFIG_VARIABLE} is unset); P1-02 real-data acceptance was not run")
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _instant(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)


def check_definition(spec: dict, metadata: FuturesContractMetadata) -> tuple:
    """definition Snapshot(해시 고정)마다 모든 레코드가 메타데이터와 맞는지 확인하고 그 manifest들을 돌려준다 (1e-9 고정소수점 정수 비교, float 없음)."""
    manifests = []
    expiration = int((metadata.last_trading_at - EPOCH).total_seconds()) * 10**9
    expected = (spec["raw_symbol"], spec["databento_instrument_id"], expiration, int(metadata.multiplier.scaleb(9)),
                int(metadata.outright_tick_size.scaleb(9)), metadata.currency, metadata.product_root)
    for pinned in spec["definition"]["snapshots"]:
        manifest, raw = load_raw_snapshot(Path(spec["definition"]["raw_root"]), pinned["snapshot_id"],
                                          expected_manifest_sha256=pinned["manifest_sha256"])
        origin = (manifest.data_origin, manifest.provider, manifest.dataset, manifest.schema)
        assert origin == (DataOrigin.REAL, "databento", "GLBX.MDP3", "definition")
        rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8"), newline="")))
        assert rows and all(
            (row["raw_symbol"], int(row["instrument_id"]), int(row["expiration"]), int(row["unit_of_measure_qty"]),
             int(row["min_price_increment"]), row["currency"], row["asset"]) == expected
            for row in rows
        ), manifest.snapshot_id
        manifests.append(manifest)
    assert manifests
    return tuple(manifests)


def test_real_mesu6_to_mesz6_roll_meets_the_p1_02_data_criteria(tmp_path):
    """요구 24~29. 입력: 저장소 밖 설정이 가리키는 MESU6·MESZ6 실제 Snapshot과 연구용 롤 계획. 출력: 위 통과 조건. 실패하면 P1-02는 완료가 아니다."""
    config = _config()
    roll = config["roll"]
    contracts = tuple(config["contracts"])
    plan = RollPlan(plan_id=roll["plan_id"], research_instrument_id="CME.MES.CONTINUOUS", initial_contract_id=contracts[0], accepted_evidence=EVIDENCE,
                    entries=(RollPlanEntry(from_contract_id=contracts[0], to_contract_id=contracts[1],
                                           roll_reference_date=date.fromisoformat(roll["roll_reference_date"]),
                                           new_contract_first_date=date.fromisoformat(roll["new_contract_first_date"]),
                                           selection_policy_id=roll["selection_policy_id"], evidence_cutoff_at=_instant(roll["evidence_cutoff_at"])),))
    metadata = {contract_id: METADATA[contract_id] for contract_id in contracts}

    manifests, by_contract, events, reports = [], {}, [], {}
    for contract_id, spec in config["contracts"].items():
        definitions = check_definition(spec, metadata[contract_id])
        mapping = DatabentoInstrumentMapping(dataset="GLBX.MDP3", raw_symbol=spec["raw_symbol"], databento_instrument_id=spec["databento_instrument_id"],
                                             contract_id=contract_id, price_unit=PriceUnit.INDEX_POINT, source=spec["mapping_source"],
                                             verification=VerificationLevel(spec["mapping_verification"]))
        own_manifests, own_events, own_issues = [], [], []
        for pinned in spec["statistics"]["snapshots"]:
            manifest, raw = load_raw_snapshot(Path(spec["statistics"]["raw_root"]), pinned["snapshot_id"],
                                              expected_manifest_sha256=pinned["manifest_sha256"])
            assert (manifest.data_origin, manifest.provider, manifest.dataset, manifest.schema) == (DataOrigin.REAL, "databento", "GLBX.MDP3", "statistics")
            parsed = parse_databento_statistics(raw, manifest=manifest, mapping=mapping, metadata=metadata[contract_id])
            assert [issue for issue in parsed.issues if issue.blocking] == []
            own_manifests.append(manifest)
            own_events += parsed.events
            own_issues += parsed.issues
        days = sorted({event.trading_date for event in own_events})
        reports[contract_id] = assess_settlement_quality(metadata=metadata[contract_id], manifests=own_manifests, events=own_events, issues=own_issues,
                                                         requested_start=days[0], requested_end=days[-1], minimum_final_days=1, calendar=None)
        assert reports[contract_id].status is not QualityStatus.BLOCKED, (contract_id, [(c.name.value, c.reasons) for c in reports[contract_id].checks])
        manifests += [*own_manifests, *definitions]
        by_contract[contract_id] = (*own_manifests, *definitions)
        events += own_events

    (entry,) = plan.entries
    answers = [get_final_settlement_asof(events, contract_id, entry.roll_reference_date, entry.evidence_cutoff_at, accepted_evidence=EVIDENCE)
               for contract_id in (entry.from_contract_id, entry.to_contract_id)]
    outcome = resolve_roll_event(plan, entry, old_answer=answers[0], new_answer=answers[1])
    assert type(outcome) is FuturesRollEvent, outcome
    # gap는 known_at까지 보인 기록만으로 정해지며 그 뒤의 기록으로 바뀌지 않는다
    known = [event for event in events if event.vendor_received_at is not None and event.vendor_received_at <= entry.evidence_cutoff_at]
    again = [get_final_settlement_asof(known, contract_id, entry.roll_reference_date, entry.evidence_cutoff_at, accepted_evidence=EVIDENCE)
             for contract_id in (entry.from_contract_id, entry.to_contract_id)]
    assert resolve_roll_event(plan, entry, old_answer=again[0], new_answer=again[1]) == outcome
    full_as_of = max(event.vendor_received_at for event in events if event.vendor_received_at is not None)

    def inputs(cutoff):
        return {contract_id: asof_final_series(events, contract_id, cutoff, accepted_evidence=EVIDENCE) for contract_id in contracts}

    full_inputs = inputs(full_as_of)
    full = build_adjusted_series(plan, (outcome,), full_inputs, as_of=full_as_of, basis=ContinuousSeriesBasis.FULL_SAMPLE)
    report = assess_continuous_series(plan=plan, metadata=metadata, roll_outcomes=(outcome,), series=full, contract_series=full_inputs,
                                      contract_reports=reports, manifests=tuple(manifests), calendar=None)
    assert report.status is not QualityStatus.BLOCKED, [(c.name.value, c.status.value, c.reasons) for c in report.checks]
    assert len(report.overlaps[0].trading_dates) >= 10
    (boundary,) = report.roll_boundaries
    assert boundary.adjusted_change_points == boundary.new_contract_change_points
    assert boundary.spurious_jump_points == -outcome.roll_gap_points
    assert {point.availability_evidence for point in full.points} == {EVIDENCE}
    # 원본 가격은 선택 월물의 최종 정산가 그대로이며 조정 가격과 따로 남는다
    raw = {(contract_id, point.trading_date): point.price for contract_id, item in full_inputs.items() for point in item.points}
    assert all(raw[point.selected_contract_id, point.trading_date] == point.raw_price for point in full.points)

    asof = []
    for text in config["asof_cutoffs"]:
        cutoff = _instant(text)
        series = build_adjusted_series(plan, (outcome,), inputs(cutoff), as_of=cutoff, basis=ContinuousSeriesBasis.AS_OF_CUTOFF)
        visible = [event for event in events if event.vendor_received_at is not None and event.vendor_received_at <= cutoff]
        visible_inputs = {contract_id: asof_final_series(visible, contract_id, cutoff, accepted_evidence=EVIDENCE) for contract_id in contracts}
        assert series == build_adjusted_series(plan, (outcome,), visible_inputs, as_of=cutoff, basis=ContinuousSeriesBasis.AS_OF_CUTOFF)
        assert (len(series.applied_rolls) == 1) is (entry.evidence_cutoff_at <= cutoff)
        asof.append(series)

    def export(out_dir):
        return write_continuous_dataset(out_dir, plan=plan, roll_outcomes=(outcome,), full_sample=full, asof=tuple(asof), report=report,
                                        manifests=by_contract, metadata=metadata, calendar=None,
                                        upstream_versions={"databento_adapter": ADAPTER_VERSION, "settlement_quality_rule": QUALITY_RULE_VERSION,
                                                           "settlement_selection_policy": SELECTION_POLICY},
                                        run_started_at=datetime.now(UTC))

    first, second = export(tmp_path / "first"), export(tmp_path / "second")
    assert first.processed_manifest_sha256 == second.processed_manifest_sha256 and first.outputs == second.outputs
    if config["output_dir"] is not None:
        export(Path(config["output_dir"]))
