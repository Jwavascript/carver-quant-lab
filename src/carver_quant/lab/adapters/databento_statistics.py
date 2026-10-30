"""P1-01 Databento GLBX.MDP3 `statistics` CSV Adapter: 원본 행을 정산가 사건(`SettlementEvent`)과 공급원 문제(`SourceIssue`)로 번역한다
(FR-02, FR-03. 필드 대응은 docs/architecture/P1-01_MARKET_DATA_SPEC.md §3).

Adapter다 (ADR-0010 PK-5): `lab.domain`과 표준 라이브러리만 import한다. 최종가 선택, 품질 판정, PIT 조회를 하지 않는다. 공급자를 바꾸면
이 모듈만 바꾼다.

지원 형식 (`ADAPTER_VERSION`): Databento CSV 인코딩, 정수 가격·정수 나노초 시각(`pretty_px`·`pretty_ts` 끔), `map_symbols`로 붙은
`symbol` 열, 압축 없음(`csv`) 또는 zstd(`csv.zst`). 열 이름은 Databento 문서의 필드 목록에서 정했다 (INFERRED: 실제 파일로 확인하지
못함). 열 집합이 정확히 같지 않으면 읽지 않는다.

번역 규칙:
- `stat_type` 3(정산가) 행만 사건으로 만들고, 다른 통계는 종류별로 센다. `rtype`은 24(statistics)여야 한다.
- 가격: int64, 1 = 1e-9. 정수를 Decimal로 바꾸고 소수점만 옮긴다 (float 없음, 반올림 없음). `INT64_MAX`는 값 없음이다.
- 시각: uint64 나노초, `UINT64_MAX`는 값 없음이다. 마이크로초로 **올림**한다 (이용 가능 시각을 앞당기지 않음. 원래 나노초는 레코드
  ID에 남는다). `ts_recv` → `vendor_received_at`, `ts_event` → `published_at`. 정산가가 정해진 시각(`observed_at`)은 없다.
  `ingested_at`은 Snapshot 획득 시각이다.
- `ts_ref`(CME 5796 TradingReferenceDate)는 날짜 정밀도이므로 UTC 자정이어야 하고, 그 날짜가 거래일 라벨이다 (현지화하지 않음).
- `stat_flags`: bit 0 최종/잠정, bit 1 실제/이론, bit 2 거래 tick/청산 tick, bit 3 장중. 다른 bit가 켜져 있으면 해석하지 않는다.
  `update_action` 1 추가, 2 삭제(→ WITHDRAWN).
- 식별: `symbol`이 대응표의 원 symbol과, `instrument_id`가 대응표의 ID와 같아야 한다. `.`이 든 symbol(연속·부모 symbology)은 월물로
  받지 않는다. 대응표는 메타데이터와 맞아야 한다 (상품 코드 + 월 코드 + 연도 끝자리, 가격 단위).
- 같은 행이 여러 번 있으면 사건 하나로 만들고 경고를 남긴다. 같은 레코드 ID(dataset, instrument, `ts_recv`, sequence, stat_type)에
  내용이 다른 행이 있으면 그 ID의 행을 모두 사건으로 만들지 않고 차단 문제로 남긴다.
- 대응표·가격 단위가 CONFIRMED가 아니면 경고를 남긴다.
"""

import csv
import hashlib
import io
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from carver_quant.lab.domain.market_data import (
    FuturesContractMetadata,
    PriceUnit,
    QualityCheckName,
    RawSnapshotManifest,
    SettlementEvent,
    SettlementPriceType,
    SettlementRevisionStatus,
    SourceIssue,
    VerificationLevel,
    recorded_availability_evidence,
)
from carver_quant.lab.domain.values import EXACT_DECIMAL_CONTEXT, require_identifier, require_int

ADAPTER_VERSION = "databento-glbx-statistics-csv/1"
PROVIDER = "databento"
SCHEMA = "statistics"
SUPPORTED_ENCODINGS = ("csv", "csv.zst")
STATISTICS_COLUMNS = (
    "ts_recv",
    "ts_event",
    "rtype",
    "publisher_id",
    "instrument_id",
    "ts_ref",
    "price",
    "quantity",
    "sequence",
    "ts_in_delta",
    "stat_type",
    "channel_id",
    "update_action",
    "stat_flags",
    "symbol",
)

STATISTICS_RTYPE = 24
SETTLEMENT_STAT_TYPE = 3
UNDEF_PRICE = 2**63 - 1
UNDEF_TIMESTAMP = 2**64 - 1
_DAY_NS = 86_400 * 10**9
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_MONTH_CODES = "FGHJKMNQUVXZ"
_FLAG_FINAL, _FLAG_ACTUAL, _FLAG_TRADING_TICK, _FLAG_INTRADAY = 1, 2, 4, 8
_KNOWN_FLAGS = _FLAG_FINAL | _FLAG_ACTUAL | _FLAG_TRADING_TICK | _FLAG_INTRADAY
_INTEGER = re.compile(r"-?[0-9]+")
# 정수 열과 허용 범위 (Databento 필드 자료형).
_INTEGER_RANGES = {
    "ts_recv": (0, 2**64 - 1),
    "ts_event": (0, 2**64 - 1),
    "rtype": (0, 2**8 - 1),
    "publisher_id": (0, 2**16 - 1),
    "instrument_id": (0, 2**32 - 1),
    "ts_ref": (0, 2**64 - 1),
    "price": (-(2**63), 2**63 - 1),
    "quantity": (-(2**63), 2**63 - 1),
    "sequence": (0, 2**32 - 1),
    "ts_in_delta": (-(2**31), 2**31 - 1),
    "stat_type": (0, 2**16 - 1),
    "channel_id": (0, 2**16 - 1),
    "update_action": (0, 2**8 - 1),
    "stat_flags": (0, 2**8 - 1),
}


@dataclass(frozen=True, kw_only=True)
class DatabentoInstrumentMapping:
    """Databento 원 symbol·instrument ID와 내부 월물 ID의 대응 (FR-03). 출처와 확인 수준을 함께 가진다 (I6-11).

    원 symbol은 CME Globex 형식(상품 코드 + 월 코드 + 연도 끝자리, 예: `MESU6`)이다. 연도 끝자리는 10년마다 반복되므로 월물 연도는
    메타데이터가 정한다. `databento_instrument_id`는 공급자의 숫자 ID이며 ADR-0006의 논리 상품 ID가 아니다. `price_unit`은 공급자
    가격이 나타내는 단위이며 확인 수준은 `verification`을 따른다.
    """

    dataset: str
    raw_symbol: str
    databento_instrument_id: int
    contract_id: str
    price_unit: PriceUnit
    source: str
    verification: VerificationLevel

    def __post_init__(self) -> None:
        for name in ("dataset", "raw_symbol", "contract_id", "source"):
            object.__setattr__(self, name, require_identifier(getattr(self, name), name))
        if "." in self.raw_symbol:
            raise ValueError("raw_symbol must name one contract, not a continuous or parent symbol.")
        instrument_id = require_int(self.databento_instrument_id, "databento_instrument_id")
        if not 0 <= instrument_id <= 2**32 - 1:
            raise ValueError("databento_instrument_id must be an unsigned 32-bit integer.")
        object.__setattr__(self, "databento_instrument_id", instrument_id)
        if not isinstance(self.price_unit, PriceUnit) or not isinstance(self.verification, VerificationLevel):
            raise ValueError("price_unit must be a PriceUnit and verification a VerificationLevel.")


@dataclass(frozen=True, kw_only=True)
class ParsedStatistics:
    """한 Snapshot의 번역 결과: 정산가 사건(원본 순서), 공급원 문제, 읽은 데이터 행 수, stat_type별 행 수, Adapter 판본."""

    adapter_version: str
    snapshot_id: str
    rows_total: int
    rows_by_stat_type: tuple[tuple[int, int], ...]
    events: tuple[SettlementEvent, ...]
    issues: tuple[SourceIssue, ...]


def contract_raw_symbol(metadata: FuturesContractMetadata) -> str:
    """메타데이터의 월물을 CME Globex 원 symbol로 쓴다: 상품 코드 + 월 코드 + 연도 끝자리 (예: MES 2026년 9월 → `MESU6`)."""
    return f"{metadata.product_root}{_MONTH_CODES[metadata.contract_month - 1]}{metadata.contract_year % 10}"


def _instant(nanoseconds: int) -> datetime | None:
    if nanoseconds == UNDEF_TIMESTAMP:
        return None
    # 나노초 → 마이크로초 올림.
    return _EPOCH + timedelta(microseconds=-(-nanoseconds // 1000))


def _check_inputs(raw: object, manifest: object, mapping: object, metadata: object) -> None:
    if type(raw) is not bytes:
        raise ValueError("raw must be bytes.")
    if type(manifest) is not RawSnapshotManifest or type(mapping) is not DatabentoInstrumentMapping:
        raise ValueError("manifest must be a RawSnapshotManifest and mapping a DatabentoInstrumentMapping.")
    if type(metadata) is not FuturesContractMetadata:
        raise ValueError("metadata must be a FuturesContractMetadata.")
    if (manifest.provider, manifest.schema) != (PROVIDER, SCHEMA) or manifest.encoding not in SUPPORTED_ENCODINGS:
        raise ValueError("the snapshot is not a Databento statistics CSV file.")
    if manifest.dataset != mapping.dataset:
        raise ValueError("the snapshot dataset does not match the instrument mapping.")
    if len(raw) != manifest.byte_size or hashlib.sha256(raw).hexdigest() != manifest.raw_sha256:
        raise ValueError("raw bytes do not match the snapshot manifest.")
    if mapping.contract_id != metadata.contract_id or mapping.raw_symbol != contract_raw_symbol(metadata):
        raise ValueError("the instrument mapping does not match the contract metadata.")
    if mapping.price_unit is not metadata.price_unit:
        raise ValueError("the mapping price unit does not match the contract metadata.")


def _decode(raw: bytes, encoding: str) -> str:
    """원본 바이트를 텍스트로. 해석할 수 없으면 ValueError (호출부가 SCHEMA 문제로 남긴다)."""
    data = raw
    if encoding == "csv.zst":
        # 표준 라이브러리 (Python 3.14). zstd 없이 빌드된 Python에서는 ImportError로 이 형식만 읽지 못한다.
        from compression import zstd

        try:
            data = zstd.decompress(raw)
        except (zstd.ZstdError, EOFError) as error:
            raise ValueError(f"zstd decompression failed: {error}") from error
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError(f"the file is not UTF-8 text: {error}") from error


def _integers(record: dict[str, str]) -> tuple[dict[str, int], list[str]]:
    values, bad = {}, []
    for name, (low, high) in _INTEGER_RANGES.items():
        text = record[name]
        # 64비트 정수는 부호를 포함해 20자 이하다. 더 긴 텍스트는 int()로 바꾸지 않는다 (아주 긴 숫자는 int()가 거부한다).
        if len(text) > 20 or _INTEGER.fullmatch(text) is None or not low <= int(text) <= high:
            bad.append(name)
        else:
            values[name] = int(text)
    return values, bad


def parse_databento_statistics(
    raw: bytes, *, manifest: RawSnapshotManifest, mapping: DatabentoInstrumentMapping, metadata: FuturesContractMetadata
) -> ParsedStatistics:
    """Databento `statistics` CSV Snapshot 하나를 정산가 사건과 공급원 문제로 번역한다.

    입력: 원본 바이트(manifest의 해시와 같아야 함), Snapshot manifest, 대응표, 월물 메타데이터. 출력: `ParsedStatistics`. 형식이나
    값에 문제가 있는 행은 사건으로 만들지 않고 `SourceIssue`로 남긴다 (고치거나 추측하지 않음).
    예외: 다른 공급자·schema·형식의 Snapshot, 바이트와 manifest 불일치, 메타데이터와 맞지 않는 대응표 → ValueError.
    """
    _check_inputs(raw, manifest, mapping, metadata)
    snapshot_id = manifest.snapshot_id
    issues: list[SourceIssue] = []

    def issue(check: QualityCheckName, code: str, ref: str, detail: str, *, blocking: bool = True) -> None:
        record_ref = f"{snapshot_id}:{ref}"
        issues.append(SourceIssue(check=check, code=code, record_ref=record_ref, detail=detail.strip() or code, blocking=blocking))

    if mapping.verification is not VerificationLevel.CONFIRMED:
        detail = f"{mapping.raw_symbol} -> {mapping.contract_id}: {mapping.verification.value} ({mapping.source})"
        issue(QualityCheckName.CONTRACT_IDENTITY, "MAPPING_NOT_CONFIRMED", "mapping", detail, blocking=False)
        detail = f"provider prices read as {mapping.price_unit.value}: {mapping.verification.value} ({mapping.source})"
        issue(QualityCheckName.PRICE_UNIT, "PRICE_UNIT_NOT_CONFIRMED", "mapping", detail, blocking=False)

    def result(rows_total: int = 0, by_stat_type: dict | None = None, events: tuple = ()) -> ParsedStatistics:
        return ParsedStatistics(
            adapter_version=ADAPTER_VERSION,
            snapshot_id=snapshot_id,
            rows_total=rows_total,
            rows_by_stat_type=tuple(sorted((by_stat_type or {}).items())),
            events=events,
            issues=tuple(issues),
        )

    reader = None
    try:
        reader = csv.reader(io.StringIO(_decode(raw, manifest.encoding), newline=""))
        rows = list(reader)
    except (ValueError, csv.Error) as error:
        where = "file" if reader is None else f"csv_line:{reader.line_num}"
        issue(QualityCheckName.SCHEMA, "SCHEMA_UNREADABLE", where, str(error))
        return result()
    header = rows[0] if rows else None
    if header is None or len(set(header)) != len(header) or set(header) != set(STATISTICS_COLUMNS):
        issue(QualityCheckName.SCHEMA, "SCHEMA_COLUMNS", "header", f"expected columns {', '.join(STATISTICS_COLUMNS)}")
        return result()

    rows_total, by_stat_type = 0, {}
    candidates: dict[str, list[tuple[tuple[str, ...], SettlementEvent, str]]] = {}
    for row_number, values in enumerate(rows[1:], start=1):
        rows_total += 1
        ref = f"row:{row_number}"
        if len(values) != len(header):
            issue(QualityCheckName.SCHEMA, "SCHEMA_ROW_LENGTH", ref, f"{len(values)} fields for {len(header)} columns")
            continue
        record = dict(zip(header, values))
        number, bad = _integers(record)
        if bad:
            issue(QualityCheckName.SCHEMA, "SCHEMA_INVALID_INTEGER", ref, f"not an integer in range: {', '.join(bad)}")
            continue
        stat_type = number["stat_type"]
        by_stat_type[stat_type] = by_stat_type.get(stat_type, 0) + 1
        if number["rtype"] != STATISTICS_RTYPE:
            issue(QualityCheckName.SCHEMA, "SCHEMA_RTYPE", ref, f"rtype {number['rtype']} is not statistics ({STATISTICS_RTYPE})")
            continue
        symbol = record["symbol"]
        if "." in symbol:
            issue(QualityCheckName.CONTRACT_IDENTITY, "IDENTITY_CONTINUOUS_SYMBOL", ref, f"symbol {symbol!r} is not a single contract")
            continue
        if symbol != mapping.raw_symbol:
            issue(QualityCheckName.CONTRACT_IDENTITY, "IDENTITY_SYMBOL_MISMATCH", ref, f"symbol {symbol!r} is not {mapping.raw_symbol}")
            continue
        if number["instrument_id"] != mapping.databento_instrument_id:
            detail = f"instrument_id {number['instrument_id']} is not {mapping.databento_instrument_id}"
            issue(QualityCheckName.CONTRACT_IDENTITY, "IDENTITY_INSTRUMENT_ID_MISMATCH", ref, detail)
            continue
        if stat_type != SETTLEMENT_STAT_TYPE:
            continue

        ts_ref, flags, action, raw_price = number["ts_ref"], number["stat_flags"], number["update_action"], number["price"]
        if ts_ref == UNDEF_TIMESTAMP or ts_ref % _DAY_NS != 0:
            issue(QualityCheckName.SCHEMA, "SCHEMA_TS_REF_NOT_DATE", ref, f"ts_ref {ts_ref} is not a UTC midnight")
            continue
        if flags & ~_KNOWN_FLAGS:
            issue(QualityCheckName.SCHEMA, "SCHEMA_STAT_FLAGS", ref, f"stat_flags {flags} has bits this adapter does not interpret")
            continue
        if action not in (1, 2):
            issue(QualityCheckName.SCHEMA, "SCHEMA_UPDATE_ACTION", ref, f"update_action {action} is not add (1) or delete (2)")
            continue
        if raw_price == UNDEF_PRICE and action == 1:
            issue(QualityCheckName.DECIMAL_PRICE, "PRICE_UNDEFINED", ref, "a settlement record without a price")
            continue

        published_at, vendor_received_at = _instant(number["ts_event"]), _instant(number["ts_recv"])
        if action == 2:
            status = SettlementRevisionStatus.WITHDRAWN
        elif flags & _FLAG_FINAL:
            status = SettlementRevisionStatus.FINAL
        else:
            status = SettlementRevisionStatus.PRELIMINARY
        record_id = f"databento:{manifest.dataset}:{number['instrument_id']}:{number['ts_recv']}:{number['sequence']}:{stat_type}"
        event = SettlementEvent(
            contract_id=mapping.contract_id,
            trading_date=date(1970, 1, 1) + timedelta(days=ts_ref // _DAY_NS),
            price_type=SettlementPriceType.INTRADAY if flags & _FLAG_INTRADAY else SettlementPriceType.DAILY,
            # 1e-9 고정소수점: 정수의 소수점만 옮긴다. 정확한 문맥이라 반올림이 생기면 실패한다.
            price=None if raw_price == UNDEF_PRICE else Decimal(raw_price).scaleb(-9, context=EXACT_DECIMAL_CONTEXT),
            revision_status=status,
            actual=bool(flags & _FLAG_ACTUAL),
            at_trading_tick=bool(flags & _FLAG_TRADING_TICK),
            observed_at=None,
            published_at=published_at,
            vendor_received_at=vendor_received_at,
            ingested_at=manifest.acquired_at,
            source_record_id=record_id,
            source_snapshot_id=snapshot_id,
            availability_evidence=recorded_availability_evidence(published_at=published_at, vendor_received_at=vendor_received_at),
        )
        candidates.setdefault(record_id, []).append((tuple(values), event, ref))

    events = []
    for record_id, group in candidates.items():
        refs = ", ".join(ref for _, _, ref in group)
        if len({values for values, _, _ in group}) > 1:
            issue(QualityCheckName.DUPLICATES_AND_CONFLICTS, "SOURCE_RECORD_ID_CONFLICT", group[0][2], f"{record_id} differs at {refs}")
            continue
        events.append(group[0][1])
        if len(group) > 1:
            detail = f"{record_id} repeated at {refs}"
            issue(QualityCheckName.DUPLICATES_AND_CONFLICTS, "DUPLICATE_RECORDS", group[0][2], detail, blocking=False)
    return result(rows_total, by_stat_type, tuple(events))
