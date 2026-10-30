"""P1-01 연구용 정산가 데이터셋 내보내기: 정규화 사건, 최신 최종가 Series, As-of Series, 품질 보고서, 처리 manifest, 실행 기록
(FR-07, FR-08, ADR-0011 FP-11·FP-12·FP-16).

Adapter다 (ADR-0010 PK-5): `lab.domain`, 같은 패키지의 Raw Snapshot 모듈(manifest 해시), 표준 라이브러리만 import한다. 계산하지 않고
받은 도메인 값을 정해진 형식으로 쓴다. 조립
(Snapshot 읽기 → 번역 → 품질·PIT → 내보내기)은 호출부가 한다. 조립 계층(`lab.app`)의 분류와 위치는 미승인이다 (ADR-0010 Q10-4·Q10-5).

형식 (형식 버전 1, P1-01 한정 선택. 새 인코더의 수치 규칙 Q11-6과 canonicalization Q11-11은 정하지 않았다):
- UTF-8 JSON, 키 정렬, 공백 없는 구분자, 비ASCII 문자는 그대로, 끝에 줄바꿈 하나. 같은 입력이면 같은 바이트다.
- 도메인 dataclass는 필드 이름 그대로 쓴다. Decimal은 지수 표기 없는 십진 문자열(원래 소수 자릿수 유지), 시각은
  `YYYY-MM-DDTHH:MM:SS.ffffffZ`, 날짜는 `YYYY-MM-DD`, 열거형은 값 문자열, 없음은 null이다. 실수(float)는 쓰지 않는다.
- 파일: `normalized_settlements.json`, `research_settlements_latest_final.json`(PIT 아님), cutoff마다
  `research_settlements_asof_<cutoff>_<근거>.json`, `quality_report.json`, `processed_manifest.json`(Raw Snapshot별 원본·manifest
  SHA-256과 출처 표시·획득 시각, Adapter·품질 규칙·메타데이터·선택 정책 판본, 다른 결정적 산출물의 SHA-256), `run_log.json`(실행 시각과
  Python 판본. 실행마다 다르며 manifest의 해시 목록에 들어가지 않는다).
- 출력 디렉터리는 새로 만든다. 이미 있으면 쓰지 않는다. 같은 부모 아래 임시 디렉터리에 모두 쓰고 동기화한 뒤 이름을 바꾼다.
"""

import dataclasses
import hashlib
import json
import os
import platform
import shutil
import tempfile
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path

from carver_quant.lab.adapters.raw_snapshot import manifest_sha256
from carver_quant.lab.domain.market_data import (
    FuturesContractMetadata,
    RawSnapshotManifest,
    ResearchSettlementSeries,
    SeriesBasis,
    SettlementEvent,
    SettlementQualityReport,
)
from carver_quant.lab.domain.values import require_identifier, require_utc_instant

EXPORT_FORMAT = "carver-lab-settlement-dataset"  # 형식 이름 (가칭)
EXPORT_FORMAT_VERSION = 1
NORMALIZED_FILENAME = "normalized_settlements.json"
LATEST_FILENAME = "research_settlements_latest_final.json"
QUALITY_FILENAME = "quality_report.json"
PROCESSED_MANIFEST_FILENAME = "processed_manifest.json"
RUN_LOG_FILENAME = "run_log.json"


class SettlementExportError(Exception):
    """출력 디렉터리를 만들거나 쓸 수 없다. 기존 출력을 덮어쓰지 않는다."""


@dataclass(frozen=True, kw_only=True)
class SettlementExport:
    """내보낸 결과: 출력 디렉터리, 처리 manifest의 SHA-256, 결정적 산출물의 (파일 이름, SHA-256) (이름 순, run_log.json 제외)."""

    out_dir: Path
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


def asof_filename(series: ResearchSettlementSeries) -> str:
    """As-of Series 파일 이름: cutoff(UTC, 마이크로초가 있으면 포함)와 받아들인 근거로 구분한다."""
    if type(series) is not ResearchSettlementSeries or series.basis is not SeriesBasis.AS_OF_CUTOFF:
        raise ValueError("an as-of file name needs an AS_OF_CUTOFF series.")
    cutoff = series.cutoff_at
    stamp = cutoff.strftime("%Y%m%dT%H%M%S") + (f".{cutoff.microsecond:06d}" if cutoff.microsecond else "")
    return f"research_settlements_asof_{stamp}Z_{series.accepted_evidence.value}.json"


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


def _check_inputs(metadata, manifests, adapter_version, events, report, latest, asof) -> None:
    if type(metadata) is not FuturesContractMetadata or type(report) is not SettlementQualityReport:
        raise ValueError("metadata and report must be FuturesContractMetadata and SettlementQualityReport values.")
    require_identifier(adapter_version, "adapter_version")
    if not manifests or any(type(item) is not RawSnapshotManifest for item in manifests):
        raise ValueError("manifests must contain at least one RawSnapshotManifest.")
    if any(type(item) is not SettlementEvent for item in events):
        raise ValueError("events must contain SettlementEvent values.")
    if type(latest) is not ResearchSettlementSeries or latest.basis is not SeriesBasis.LATEST_FINAL_IN_SNAPSHOT:
        raise ValueError("latest must be a LATEST_FINAL_IN_SNAPSHOT series.")
    if any(type(item) is not ResearchSettlementSeries or item.basis is not SeriesBasis.AS_OF_CUTOFF for item in asof):
        raise ValueError("asof must contain AS_OF_CUTOFF series.")

    contract_id = metadata.contract_id
    snapshot_ids = tuple(sorted(item.snapshot_id for item in manifests))
    if len(set(snapshot_ids)) != len(snapshot_ids) or report.snapshot_ids != snapshot_ids:
        raise ValueError("the report must cover exactly the given raw snapshots.")
    if report.contract_id != contract_id or report.metadata_version != metadata.metadata_version:
        raise ValueError("the report must belong to the same contract and metadata version.")
    series = (latest, *asof)
    if any(item.contract_id != contract_id or item.selection_policy != latest.selection_policy for item in series):
        raise ValueError("every series must belong to the contract and use the same selection policy.")
    if any(item.contract_id != contract_id for item in events):
        raise ValueError("every normalized event must belong to the contract.")
    # 연구 Series의 모든 점과 정규화 사건은 함께 보관하는 Raw Snapshot까지 추적되어야 한다 (FR-08).
    known = set(snapshot_ids)
    if any(item.source_snapshot_id not in known for item in events) or any(
        point.source_snapshot_id not in known for item in series for point in item.points
    ):
        raise ValueError("every event and series point must refer to one of the given raw snapshots.")


def write_settlement_dataset(
    out_dir,
    *,
    metadata: FuturesContractMetadata,
    manifests: tuple[RawSnapshotManifest, ...],
    adapter_version: str,
    events: tuple[SettlementEvent, ...],
    report: SettlementQualityReport,
    latest: ResearchSettlementSeries,
    asof: tuple[ResearchSettlementSeries, ...],
    run_started_at: datetime,
) -> SettlementExport:
    """정산가 데이터셋 산출물을 새 출력 디렉터리에 쓴다 (FR-07, FR-08).

    입력: 출력 디렉터리(아직 없어야 함), 월물 메타데이터, Raw Snapshot manifest들, Adapter 판본, 정규화 사건(받은 순서대로 쓴다), 품질
    보고서, 최신 최종가 Series, As-of Series들, 호출부가 정한 실행 시작 시각(UTC, 실행 기록에만 쓴다).
    출력: `SettlementExport`. 같은 입력이면 run_log.json을 뺀 파일이 바이트 단위로 같다.
    예외: 입력 타입·연결이 맞지 않음, As-of 파일 이름 중복 → ValueError. 출력 디렉터리가 이미 있거나 쓸 수 없음 → SettlementExportError.
    """
    manifests, events, asof = tuple(manifests), tuple(events), tuple(asof)
    _check_inputs(metadata, manifests, adapter_version, events, report, latest, asof)
    run_started_at = require_utc_instant(run_started_at, "run_started_at")
    asof_names = [asof_filename(item) for item in asof]
    if len(set(asof_names)) != len(asof_names):
        raise ValueError("as-of series must have distinct cutoffs or accepted evidence.")

    documents = {
        NORMALIZED_FILENAME: _document(
            "normalized_settlements",
            {"contract_id": metadata.contract_id, "adapter_version": adapter_version, "events": _plain(events)},
        ),
        LATEST_FILENAME: _document("research_settlement_series", _plain(latest)),
        QUALITY_FILENAME: _document("quality_report", _plain(report)),
    }
    for name, series in zip(asof_names, asof):
        documents[name] = _document("research_settlement_series", _plain(series))
    hashes = {name: hashlib.sha256(data).hexdigest() for name, data in documents.items()}
    snapshots = sorted(manifests, key=lambda item: item.snapshot_id)
    documents[PROCESSED_MANIFEST_FILENAME] = _document(
        "processed_manifest",
        {
            "contract_id": metadata.contract_id,
            "metadata_version": metadata.metadata_version,
            "metadata": _plain(metadata),
            "adapter_version": adapter_version,
            "quality_rule_version": report.rule_version,
            "selection_policy": latest.selection_policy,
            "quality_status": report.status.value,
            "not_established": list(report.not_established),
            "raw_snapshots": [
                {
                    "snapshot_id": item.snapshot_id,
                    "raw_sha256": item.raw_sha256,
                    "manifest_sha256": manifest_sha256(item),
                    "data_origin": item.data_origin.value,
                    "acquired_at": _instant(item.acquired_at),
                }
                for item in snapshots
            ],
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
        raise SettlementExportError(f"output directory {out_dir} already exists.")
    try:
        out_dir.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=f".{out_dir.name}.incoming-", dir=out_dir.parent))
    except OSError as error:
        raise SettlementExportError(f"cannot prepare output directory {out_dir}: {error}") from error
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
        raise SettlementExportError(f"cannot write output directory {out_dir}: {error}") from error
    return SettlementExport(
        out_dir=out_dir,
        processed_manifest_sha256=processed_sha256,
        outputs=tuple(sorted((name, digest) for name, digest in hashes.items())),
    )
