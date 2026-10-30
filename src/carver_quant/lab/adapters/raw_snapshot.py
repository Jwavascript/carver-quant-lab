"""P1-01 Raw Snapshot 보관: 원본 바이트를 바꾸지 않고 내용 주소(SHA-256) 디렉터리에 manifest와 함께 둔다 (FR-01, ADR-0011 FP-11·FP-12).

Adapter다 (ADR-0010 PK-5): `lab.domain`과 표준 라이브러리만 import한다. 원본을 해석하지 않는다.

실험용 구현 선택 (P1-01 한정. 저장 위치·vintage 보관 방식은 ADR-0004 Q4-4, ADR-0011 Q11-8·Q11-10, 원본의 저장소 포함 여부는 공급자 약관 확인 전):
- 배치: `<root>/raw-sha256-<해시>/raw.<encoding>`(원본 바이트 그대로)과 `manifest.json`(정규 JSON, 형식 버전 1).
- 같은 바이트를 같은 획득 정보로 다시 보관하면 기존 manifest를 돌려준다 (멱등). 획득 정보가 다르면 덮어쓰지 않고 RawSnapshotError다.
  같은 바이트를 다른 시각에 다시 받은 기록은 이 형식으로 표현하지 않는다.
- 새 Snapshot은 같은 root 아래 임시 디렉터리에 쓰고 파일과 디렉터리를 디스크에 동기화한 뒤 이름을 바꿔 한 번에 나타나게 한다. 파일은
  쓰기 권한 없이 만든다 (모드 0444에서 umask가 빼는 읽기 권한은 그대로 따름). 실수로 덮어쓰는 것을 막을 뿐 위변조 방지가 아니다.
- 읽을 때 디렉터리 내용, manifest 형식(다시 직렬화한 텍스트가 같아야 함), 원본의 크기와 SHA-256을 확인한다. 다르면
  RawSnapshotIntegrityError다. 고쳐 읽지 않는다.
- Snapshot ID는 원본 바이트만 덮는다. manifest(출처 표시, 획득 시각 등)는 호출부가 기록해 둔 manifest SHA-256(`manifest_sha256`)을
  읽을 때 넘겨야 바뀐 것을 검출한다. 넘기지 않으면 정규 형식으로 다시 쓴 manifest는 검출하지 못한다. 해시를 함께 바꾼 위조는 막지 못한다.
"""

import hashlib
import json
import os
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from carver_quant.lab.domain.market_data import RAW_SNAPSHOT_ID_PREFIX, DataOrigin, RawSnapshotManifest
from carver_quant.lab.domain.values import require_identifier, require_utc_instant

RAW_SNAPSHOT_FORMAT = "carver-lab-raw-snapshot"  # 형식 이름 (가칭)
RAW_SNAPSHOT_FORMAT_VERSION = 1
MANIFEST_FILENAME = "manifest.json"

_SNAPSHOT_ID = re.compile(re.escape(RAW_SNAPSHOT_ID_PREFIX) + r"[0-9a-f]{64}")
_ENCODING = re.compile(r"[a-z0-9]+(?:\.[a-z0-9]+)*")
_INSTANT = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z")
_MANIFEST_KEYS = frozenset({
    "format",
    "format_version",
    "snapshot_id",
    "data_origin",
    "provider",
    "dataset",
    "schema",
    "encoding",
    "original_filename",
    "raw_sha256",
    "byte_size",
    "acquired_at",
    "acquisition_method",
    "request",
})


class RawSnapshotError(Exception):
    """Raw Snapshot을 보관하거나 읽을 수 없다. 덮어쓰거나 추측해서 복원하지 않는다."""


class RawSnapshotIntegrityError(RawSnapshotError):
    """보관된 Snapshot이 manifest와 맞지 않거나 형식이 깨졌다 (원본 변경, 파일 누락·추가, manifest 손상)."""


def raw_filename(encoding: str) -> str:
    """원본 바이트 파일 이름. `encoding`은 소문자·숫자와 점으로만 된 형식 이름이다."""
    if not isinstance(encoding, str) or _ENCODING.fullmatch(encoding) is None:
        raise ValueError("encoding must be lower-case letters and digits separated by dots.")

    return f"raw.{encoding}"


def _format_instant(moment: datetime) -> str:
    return require_utc_instant(moment, "instant").strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _parse_instant(text: object) -> datetime:
    if not isinstance(text, str) or _INSTANT.fullmatch(text) is None:
        raise RawSnapshotIntegrityError("manifest instants must be written as YYYY-MM-DDTHH:MM:SS.ffffffZ.")

    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)


def encode_manifest(manifest: RawSnapshotManifest) -> bytes:
    """manifest의 정규 JSON (키 정렬, 공백 없는 구분자, UTF-8, 끝에 줄바꿈 하나)."""
    if type(manifest) is not RawSnapshotManifest:
        raise ValueError("manifest must be a RawSnapshotManifest.")
    payload = {
        "format": RAW_SNAPSHOT_FORMAT,
        "format_version": RAW_SNAPSHOT_FORMAT_VERSION,
        "snapshot_id": manifest.snapshot_id,
        "data_origin": manifest.data_origin.value,
        "provider": manifest.provider,
        "dataset": manifest.dataset,
        "schema": manifest.schema,
        "encoding": manifest.encoding,
        "original_filename": manifest.original_filename,
        "raw_sha256": manifest.raw_sha256,
        "byte_size": manifest.byte_size,
        "acquired_at": _format_instant(manifest.acquired_at),
        "acquisition_method": manifest.acquisition_method,
        "request": [list(pair) for pair in manifest.request],
    }
    return (json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict:
    result = dict(pairs)
    if len(result) != len(pairs):
        raise RawSnapshotIntegrityError("manifest has a duplicated key.")
    return result


def decode_manifest(data: bytes) -> RawSnapshotManifest:
    """정규 JSON manifest를 읽는다. 형식·필드·값이 맞지 않거나 다시 직렬화한 바이트가 다르면 RawSnapshotIntegrityError."""
    try:
        payload = json.loads(data.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys, parse_float=_reject_float)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise RawSnapshotIntegrityError(f"manifest is not valid JSON: {error}") from error
    if not isinstance(payload, dict) or set(payload) != _MANIFEST_KEYS:
        raise RawSnapshotIntegrityError("manifest fields do not match the raw snapshot format.")
    if payload["format"] != RAW_SNAPSHOT_FORMAT or payload["format_version"] != RAW_SNAPSHOT_FORMAT_VERSION:
        raise RawSnapshotIntegrityError("unsupported raw snapshot manifest format.")
    request = payload["request"]
    if not isinstance(request, list) or any(not isinstance(pair, list) or len(pair) != 2 for pair in request):
        raise RawSnapshotIntegrityError("manifest request must be a list of [name, value] pairs.")
    try:
        manifest = RawSnapshotManifest(
            snapshot_id=payload["snapshot_id"],
            data_origin=DataOrigin(payload["data_origin"]),
            provider=payload["provider"],
            dataset=payload["dataset"],
            schema=payload["schema"],
            encoding=payload["encoding"],
            original_filename=payload["original_filename"],
            raw_sha256=payload["raw_sha256"],
            byte_size=payload["byte_size"],
            acquired_at=_parse_instant(payload["acquired_at"]),
            acquisition_method=payload["acquisition_method"],
            request=tuple(tuple(pair) for pair in request),
        )
        raw_filename(manifest.encoding)
    except ValueError as error:
        raise RawSnapshotIntegrityError(f"manifest values are invalid: {error}") from error
    if encode_manifest(manifest) != data:
        raise RawSnapshotIntegrityError("manifest is not in canonical form.")
    return manifest


def manifest_sha256(manifest: RawSnapshotManifest) -> str:
    """보관 형식으로 쓴 manifest 바이트의 SHA-256. 처리 manifest에 기록하고, 다시 읽을 때 `load_raw_snapshot`에 넘겨 비교한다."""
    return hashlib.sha256(encode_manifest(manifest)).hexdigest()


def _reject_float(text: str) -> float:
    raise ValueError(f"manifest must not contain JSON numbers with fractions or exponents: {text}")


def _write_read_only(path: Path, data: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
    try:
        view = memoryview(data)
        while view:
            written = os.write(descriptor, view)
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _require_snapshot_id(snapshot_id: object) -> str:
    value = require_identifier(snapshot_id, "snapshot_id")
    if _SNAPSHOT_ID.fullmatch(value) is None:
        raise ValueError("snapshot_id must be 'raw-sha256-' followed by 64 lower-case hexadecimal characters.")
    return value


def store_raw_snapshot(
    root,
    raw: bytes,
    *,
    data_origin: DataOrigin,
    provider: str,
    dataset: str,
    schema: str,
    encoding: str,
    original_filename: str,
    acquired_at: datetime,
    acquisition_method: str,
    request: tuple[tuple[str, str], ...],
) -> RawSnapshotManifest:
    """원본 바이트를 Raw Snapshot으로 보관하고 manifest를 돌려준다 (FR-01).

    입력: 보관 root, 원본 바이트(`bytes`), 획득 정보 (출처 표시, 공급자, dataset, schema, 형식 이름, 원래 파일 이름, UTC 획득 시각,
    획득 방법, 요청 매개변수). 출력: `RawSnapshotManifest` (ID = 원본 SHA-256).
    예외: 잘못된 입력·자격증명처럼 보이는 요청 이름 → ValueError. 같은 ID가 다른 획득 정보로 이미 있음, 쓰기 실패 → RawSnapshotError.
    보관된 기존 Snapshot이 손상됨 → RawSnapshotIntegrityError.
    """
    if type(raw) is not bytes:
        raise ValueError("raw must be bytes.")
    raw_name = raw_filename(encoding)
    digest = hashlib.sha256(raw).hexdigest()
    manifest = RawSnapshotManifest(
        snapshot_id=RAW_SNAPSHOT_ID_PREFIX + digest,
        data_origin=data_origin,
        provider=provider,
        dataset=dataset,
        schema=schema,
        encoding=encoding,
        original_filename=original_filename,
        raw_sha256=digest,
        byte_size=len(raw),
        acquired_at=acquired_at,
        acquisition_method=acquisition_method,
        request=request,
    )
    root = Path(root)
    target = root / manifest.snapshot_id
    if not target.exists():
        try:
            root.mkdir(parents=True, exist_ok=True)
            staging = Path(tempfile.mkdtemp(prefix=".incoming-", dir=root))
        except OSError as error:
            raise RawSnapshotError(f"cannot prepare the raw snapshot directory: {error}") from error
        try:
            _write_read_only(staging / raw_name, raw)
            _write_read_only(staging / MANIFEST_FILENAME, encode_manifest(manifest))
            _fsync_directory(staging)
            os.rename(staging, target)
            _fsync_directory(root)
            return manifest
        except OSError as error:
            shutil.rmtree(staging, ignore_errors=True)
            if not target.exists():
                raise RawSnapshotError(f"cannot store the raw snapshot: {error}") from error

    existing, _ = load_raw_snapshot(root, manifest.snapshot_id, expected_manifest_sha256=None)
    if existing != manifest:
        raise RawSnapshotError("a raw snapshot with the same bytes but different acquisition metadata already exists.")
    return existing


def load_raw_snapshot(root, snapshot_id: str, *, expected_manifest_sha256: str | None) -> tuple[RawSnapshotManifest, bytes]:
    """보관된 Raw Snapshot을 검증하고 (manifest, 원본 바이트)를 돌려준다.

    입력: 보관 root, Snapshot ID, 기록해 둔 manifest SHA-256 (없으면 None을 명시. 그때는 manifest 변경을 검출하지 못함).
    예외: 잘못된 ID·해시 형식 → ValueError. 디렉터리를 읽을 수 없음 → RawSnapshotError. 파일 누락·추가, manifest 손상·불일치, ID·크기·
    SHA-256 불일치 → RawSnapshotIntegrityError.
    """
    snapshot_id = _require_snapshot_id(snapshot_id)
    if expected_manifest_sha256 is not None and (
        not isinstance(expected_manifest_sha256, str) or re.fullmatch(r"[0-9a-f]{64}", expected_manifest_sha256) is None
    ):
        raise ValueError("expected_manifest_sha256 must be 64 lower-case hexadecimal characters or None.")
    directory = Path(root) / snapshot_id
    try:
        names = set(os.listdir(directory))
        manifest_bytes = (directory / MANIFEST_FILENAME).read_bytes() if MANIFEST_FILENAME in names else None
    except OSError as error:
        raise RawSnapshotError(f"cannot read raw snapshot {snapshot_id}: {error}") from error
    if manifest_bytes is None:
        raise RawSnapshotIntegrityError(f"raw snapshot {snapshot_id} has no manifest.")
    if expected_manifest_sha256 is not None and hashlib.sha256(manifest_bytes).hexdigest() != expected_manifest_sha256:
        raise RawSnapshotIntegrityError(f"raw snapshot {snapshot_id} manifest does not match the recorded manifest hash.")
    manifest = decode_manifest(manifest_bytes)
    raw_name = raw_filename(manifest.encoding)
    if manifest.snapshot_id != snapshot_id or names != {MANIFEST_FILENAME, raw_name}:
        raise RawSnapshotIntegrityError(f"raw snapshot {snapshot_id} does not contain exactly its manifest and raw file.")
    try:
        raw = (directory / raw_name).read_bytes()
    except OSError as error:
        raise RawSnapshotError(f"cannot read raw snapshot {snapshot_id}: {error}") from error
    if len(raw) != manifest.byte_size or hashlib.sha256(raw).hexdigest() != manifest.raw_sha256:
        raise RawSnapshotIntegrityError(f"raw snapshot {snapshot_id} bytes do not match the manifest hash.")
    return manifest, raw
