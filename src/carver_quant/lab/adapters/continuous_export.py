"""P1-02 연속 선물 데이터셋 내보내기: 롤 계획, 롤 이벤트, Full-sample·As-of 조정 시계열, 품질 보고서, 처리 manifest, 실행 기록
(P1-02 명세 §7, ADR-0011 FP-11·FP-12·FP-16).

Adapter다 (ADR-0010 PK-5): `lab.domain`, 같은 패키지의 Raw Snapshot 모듈(manifest 해시), 표준 라이브러리만 import한다. 계산하지 않고 받은
도메인 값을 정해진 형식으로 쓴다. 조립(P1-01 조회 → 롤 결정 → 조정 시계열 → 품질 검사 → 내보내기)은 호출부가 한다.

형식 (형식 버전 1, P1-02 한정 선택. 규칙은 P1-01 `settlement_export`와 같다):
- UTF-8 JSON, 키 정렬, 공백 없는 구분자, 비ASCII 문자 그대로, 끝에 줄바꿈 하나. 같은 입력이면 같은 바이트다.
- 도메인 dataclass는 필드 이름 그대로 쓴다. Decimal은 지수 표기 없는 십진 문자열(원래 소수 자릿수 유지), 시각은 `YYYY-MM-DDTHH:MM:SS.ffffffZ`,
  날짜는 `YYYY-MM-DD`, 열거형은 값 문자열, 없음은 null이다. 실수(float)는 쓰지 않는다.
- 파일: `roll_plan.json`, `roll_events.json`, `continuous_series.json`(FULL_SAMPLE), cutoff마다 `continuous_series_asof_<cutoff>_<근거>.json`,
  `quality_report.json`, `processed_manifest.json`(입력 Raw Snapshot별 원본·manifest 해시, 월물 메타데이터 판본, 롤 계획 ID·해시, 선택 정책,
  조정 방식·알고리즘·품질 규칙 판본, 상위(P1-01) 판본, 달력 출처, 다른 결정적 산출물의 SHA-256), `run_log.json`(실행마다 달라지며 해시 목록에서 제외).
- 출력 디렉터리는 새로 만든다. 이미 있으면 쓰지 않는다. 같은 부모 아래 임시 디렉터리에 모두 쓰고 동기화한 뒤 이름을 바꾼다.
"""

import dataclasses
import hashlib
import json
import os
import platform
import shutil
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path

from carver_quant.lab.adapters.raw_snapshot import manifest_sha256
from carver_quant.lab.domain.continuous import (
    AdjustedPriceSeries,
    ContinuousQualityReport,
    ContinuousSeriesBasis,
    FuturesRollEvent,
    RollPlan,
    UnresolvedRoll,
)
from carver_quant.lab.domain.market_data import FuturesContractMetadata, RawSnapshotManifest, TradingCalendarReference
from carver_quant.lab.domain.values import require_identifier, require_utc_instant

EXPORT_FORMAT = "carver-lab-continuous-futures-dataset"  # 형식 이름 (가칭)
EXPORT_FORMAT_VERSION = 1
ROLL_PLAN_FILENAME = "roll_plan.json"
ROLL_EVENTS_FILENAME = "roll_events.json"
SERIES_FILENAME = "continuous_series.json"
QUALITY_FILENAME = "quality_report.json"
PROCESSED_MANIFEST_FILENAME = "processed_manifest.json"
RUN_LOG_FILENAME = "run_log.json"


class ContinuousExportError(Exception):
    """출력 디렉터리를 만들거나 쓸 수 없다. 기존 출력을 덮어쓰지 않는다."""


@dataclass(frozen=True, kw_only=True)
class ContinuousExport:
    """내보낸 결과: 출력 디렉터리, 롤 계획 파일·처리 manifest의 SHA-256, 결정적 산출물의 (파일 이름, SHA-256) (이름 순, run_log.json 제외)."""

    out_dir: Path
    roll_plan_sha256: str
    processed_manifest_sha256: str
    outputs: tuple[tuple[str, str], ...]


def _instant(moment: datetime) -> str:
    return require_utc_instant(moment, "instant").strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _plain(value: object) -> object:
    if value is None or isinstance(value, (bool, str, int)):
        return value
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("cannot write a non-finite Decimal.")
        return format(value, "f")
    if isinstance(value, datetime):
        return _instant(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {item.name: _plain(getattr(value, item.name)) for item in dataclasses.fields(value)}
    raise ValueError(f"cannot write {type(value).__name__} values.")


def _document(name: str, body: dict) -> bytes:
    payload = {"format": EXPORT_FORMAT, "format_version": EXPORT_FORMAT_VERSION, "document": name, **body}
    return (json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def asof_series_filename(series: AdjustedPriceSeries) -> str:
    """As-of 조정 시계열 파일 이름: cutoff(UTC, 마이크로초가 있으면 포함)와 받아들인 근거로 구분한다."""
    if type(series) is not AdjustedPriceSeries or series.basis is not ContinuousSeriesBasis.AS_OF_CUTOFF:
        raise ValueError("an as-of file name needs an AS_OF_CUTOFF series.")
    cutoff = series.as_of
    stamp = cutoff.strftime("%Y%m%dT%H%M%S") + (f".{cutoff.microsecond:06d}" if cutoff.microsecond else "")
    return f"continuous_series_asof_{stamp}Z_{series.accepted_evidence.value}.json"


def _write_file(path: Path, data: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        view = memoryview(data)
        while view:
            view = view[os.write(descriptor, view):]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _entry_fields(item) -> tuple:
    return (item.from_contract_id, item.to_contract_id, item.roll_reference_date, item.new_contract_first_date, item.selection_policy_id,
            item.evidence_cutoff_at)


def _check_inputs(plan, outcomes, full_sample, asof, report, manifests, metadata, calendar, upstream_versions) -> None:
    if type(plan) is not RollPlan or type(report) is not ContinuousQualityReport:
        raise ValueError("plan and report must be RollPlan and ContinuousQualityReport values.")
    if len(outcomes) != len(plan.entries):
        raise ValueError("roll outcomes must give one result per plan entry.")
    for entry, outcome in zip(plan.entries, outcomes):
        if type(outcome) is UnresolvedRoll:
            matches = outcome.entry == entry
        else:
            matches = (type(outcome) is FuturesRollEvent and _entry_fields(outcome) == _entry_fields(entry)
                       and outcome.accepted_evidence is plan.accepted_evidence and outcome.research_instrument_id == plan.research_instrument_id)
        if not matches:
            raise ValueError("roll outcomes must be the plan's entries, in order, on the plan's evidence.")
    if type(full_sample) is not AdjustedPriceSeries or full_sample.basis is not ContinuousSeriesBasis.FULL_SAMPLE:
        raise ValueError("full_sample must be a FULL_SAMPLE AdjustedPriceSeries.")
    if any(type(item) is not AdjustedPriceSeries or item.basis is not ContinuousSeriesBasis.AS_OF_CUTOFF for item in asof):
        raise ValueError("asof must contain AS_OF_CUTOFF series.")
    series = (full_sample, *asof)
    for item in series:
        identity = (item.roll_plan_id, item.research_instrument_id, item.initial_contract_id, item.accepted_evidence, item.method,
                    item.algorithm_version)
        if identity != (
            plan.plan_id, plan.research_instrument_id, plan.initial_contract_id, plan.accepted_evidence, full_sample.method,
            full_sample.algorithm_version,
        ):
            raise ValueError("every series must be built from the plan, on its evidence, with one adjustment algorithm.")
        if item.applied_rolls != outcomes[:len(item.applied_rolls)]:
            raise ValueError("every series must apply the plan's first roll outcomes as exported.")
    if len(full_sample.applied_rolls) != len(plan.entries):
        raise ValueError("the full-sample series must apply every planned roll.")
    if (
        report.roll_plan_id != plan.plan_id
        or report.research_instrument_id != plan.research_instrument_id
        or report.series_basis is not ContinuousSeriesBasis.FULL_SAMPLE
        or report.series_as_of != full_sample.as_of
    ):
        raise ValueError("the quality report must describe the full-sample series of this plan.")
    if not isinstance(manifests, Mapping) or set(manifests) != set(plan.contracts) or any(
        not isinstance(items, tuple) or not items or any(type(item) is not RawSnapshotManifest for item in items) for items in manifests.values()
    ):
        raise ValueError("manifests must map every plan contract to its raw snapshot manifests (statistics and definition).")
    all_ids = [item.snapshot_id for items in manifests.values() for item in items]
    if len(set(all_ids)) != len(all_ids):
        raise ValueError("a raw snapshot must belong to one contract and appear once.")
    # 모든 점과 롤 기준가는 그 월물의 Raw Snapshot까지 추적되어야 한다.
    known = {contract_id: {item.snapshot_id for item in items} for contract_id, items in manifests.items()}
    if any(point.source_snapshot_id not in known[point.selected_contract_id] for item in series for point in item.points) or any(
        outcome.old_source_snapshot_id not in known[outcome.from_contract_id]
        or outcome.new_source_snapshot_id not in known[outcome.to_contract_id]
        for outcome in outcomes if type(outcome) is FuturesRollEvent
    ):
        raise ValueError("every series point and roll reference price must refer to a raw snapshot of its contract.")
    if not isinstance(metadata, Mapping) or set(metadata) != set(plan.contracts) or any(
        type(item) is not FuturesContractMetadata or item.contract_id != key for key, item in metadata.items()
    ):
        raise ValueError("metadata must map every plan contract to its FuturesContractMetadata.")
    if calendar is not None and type(calendar) is not TradingCalendarReference:
        raise ValueError("calendar must be a TradingCalendarReference or None.")
    if not isinstance(upstream_versions, Mapping) or not upstream_versions:
        raise ValueError("upstream_versions must name the upstream (P1-01) versions used.")
    for key, value in upstream_versions.items():
        require_identifier(key, "upstream version name")
        require_identifier(value, "upstream version")


def write_continuous_dataset(
    out_dir,
    *,
    plan: RollPlan,
    roll_outcomes,
    full_sample: AdjustedPriceSeries,
    asof: tuple[AdjustedPriceSeries, ...],
    report: ContinuousQualityReport,
    manifests: Mapping[str, tuple[RawSnapshotManifest, ...]],
    metadata: Mapping[str, FuturesContractMetadata],
    calendar: TradingCalendarReference | None,
    upstream_versions: Mapping[str, str],
    run_started_at: datetime,
) -> ContinuousExport:
    """연속 선물 데이터셋 산출물을 새 출력 디렉터리에 쓴다.

    입력: 출력 디렉터리(아직 없어야 함), 롤 계획, 롤 결정 결과(계획 순서), FULL_SAMPLE 시계열, As-of 시계열들, 그 FULL_SAMPLE 시계열의 품질
    보고서, 월물마다 입력 Raw Snapshot manifest들(statistics·definition), 월물 메타데이터, 달력(없으면 None), 상위 판본 이름 → 값, 호출부가 정한 실행
    시작 시각(UTC, 실행 기록에만 쓴다).
    출력: `ContinuousExport`. 같은 입력이면 run_log.json을 뺀 파일이 바이트 단위로 같다.
    예외: 입력 타입·연결이 맞지 않음, As-of 파일 이름 중복 → ValueError. 출력 디렉터리가 이미 있거나 쓸 수 없음 → ContinuousExportError.
    """
    outcomes, asof = tuple(roll_outcomes), tuple(asof)
    _check_inputs(plan, outcomes, full_sample, asof, report, manifests, metadata, calendar, upstream_versions)
    run_started_at = require_utc_instant(run_started_at, "run_started_at")
    asof_names = [asof_series_filename(item) for item in asof]
    if len(set(asof_names)) != len(asof_names):
        raise ValueError("as-of series must have distinct cutoffs or accepted evidence.")

    plan_bytes = _document("roll_plan", _plain(plan))
    documents = {
        ROLL_PLAN_FILENAME: plan_bytes,
        ROLL_EVENTS_FILENAME: _document(
            "roll_events",
            {"roll_plan_id": plan.plan_id,
             "rolls": [{"status": "RESOLVED" if type(item) is FuturesRollEvent else "UNRESOLVED", "detail": _plain(item)} for item in outcomes]},
        ),
        SERIES_FILENAME: _document("adjusted_price_series", _plain(full_sample)),
        QUALITY_FILENAME: _document("continuous_quality_report", _plain(report)),
    }
    for name, series in zip(asof_names, asof):
        documents[name] = _document("adjusted_price_series", _plain(series))
    hashes = {name: hashlib.sha256(data).hexdigest() for name, data in documents.items()}
    plan_sha256 = hashes[ROLL_PLAN_FILENAME]
    documents[PROCESSED_MANIFEST_FILENAME] = _document(
        "processed_manifest",
        {
            "research_instrument_id": plan.research_instrument_id,
            "roll_plan": {"plan_id": plan.plan_id, "sha256": plan_sha256},
            "selection_policy_ids": sorted({entry.selection_policy_id for entry in plan.entries}),
            "accepted_evidence": plan.accepted_evidence.value,
            "adjustment": {"method": full_sample.method.value, "algorithm_version": full_sample.algorithm_version},
            "quality_rule_version": report.rule_version,
            "quality_status": report.status.value,
            "upstream_versions": dict(sorted(upstream_versions.items())),
            "raw_snapshots": [
                {
                    "contract_id": contract_id,
                    "snapshot_id": item.snapshot_id,
                    "raw_sha256": item.raw_sha256,
                    "manifest_sha256": manifest_sha256(item),
                    "data_origin": item.data_origin.value,
                    "provider": item.provider,
                    "dataset": item.dataset,
                    "schema": item.schema,
                    "acquired_at": _instant(item.acquired_at),
                }
                for contract_id in plan.contracts
                for item in sorted(manifests[contract_id], key=lambda item: item.snapshot_id)
            ],
            "contract_metadata": [_plain(metadata[contract_id]) for contract_id in plan.contracts],
            "calendar": None if calendar is None else _plain(calendar),
            "not_established": list(report.not_established),
            "outputs": hashes,
        },
    )
    processed_sha256 = hashlib.sha256(documents[PROCESSED_MANIFEST_FILENAME]).hexdigest()
    run_log = _document(
        "run_log",
        {"run_started_at": _instant(run_started_at), "python_version": platform.python_version(), "processed_manifest_sha256": processed_sha256},
    )

    out_dir = Path(out_dir)
    if out_dir.exists():
        raise ContinuousExportError(f"output directory {out_dir} already exists.")
    try:
        out_dir.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=f".{out_dir.name}.incoming-", dir=out_dir.parent))
    except OSError as error:
        raise ContinuousExportError(f"cannot prepare output directory {out_dir}: {error}") from error
    try:
        for name, data in (*documents.items(), (RUN_LOG_FILENAME, run_log)):
            _write_file(staging / name, data)
        _fsync_directory(staging)
        if out_dir.exists():
            raise FileExistsError(f"output directory {out_dir} already exists.")
        os.rename(staging, out_dir)
        _fsync_directory(out_dir.parent)
    except OSError as error:
        shutil.rmtree(staging, ignore_errors=True)
        raise ContinuousExportError(f"cannot write output directory {out_dir}: {error}") from error
    return ContinuousExport(
        out_dir=out_dir,
        roll_plan_sha256=plan_sha256,
        processed_manifest_sha256=processed_sha256,
        outputs=tuple(sorted(hashes.items())),
    )
