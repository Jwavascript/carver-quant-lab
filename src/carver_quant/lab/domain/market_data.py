"""P1-01 시장 데이터 도메인 계약: 월물 메타데이터, Raw Snapshot manifest, 정산가 사건, 공급원 문제, 품질 보고서, PIT 조회 결과,
연구용 정산가 Series (ADR-0004 원칙 5·§6.5, ADR-0006 I6-3·I6-11, ADR-0007 C7-1·C7-3, ADR-0011 FP-11·FP-16, P0-03A TC-A15·TC-C3·TC-C4.
타입 이름은 가칭, D3A-01).

공급자 형식(필드 이름, 고정소수점 정수, 나노초)은 Adapter가 이 타입으로 번역한다. 시각은 UTC 순간만 받는다. 거래일은 공급자가 준
거래일 라벨(`date`)이며 UTC 날짜에서 만들지 않는다 (C7-3). 가격은 Decimal이며 float를 거치지 않는다.
정산가는 연구용 raw 관측값이다. 체결 가능한 가격이 아니다 (D3A-50).
"""

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum

from carver_quant.lab.domain.values import EXACT_DECIMAL_CONTEXT, require_decimal, require_identifier, require_int, require_utc_instant

_CODE = re.compile(r"[A-Z0-9]+")
_CURRENCY = re.compile(r"[A-Z]{3}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_ISSUE_CODE = re.compile(r"[A-Z0-9_]+")
# 요청 매개변수 이름이 이 패턴을 포함하면 자격증명으로 보고 받지 않는다 (CLAUDE.md §5).
_CREDENTIAL_NAME = re.compile(r"key|token|secret|passw|auth|credential|cookie|session", re.IGNORECASE)

RAW_SNAPSHOT_ID_PREFIX = "raw-sha256-"


class DataOrigin(Enum):
    REAL = "REAL"  # 공급자에게서 받은 원본
    SYNTHETIC = "SYNTHETIC"  # 테스트용으로 만든 값. 실데이터 판정에 쓰지 않는다


class VerificationLevel(Enum):
    CONFIRMED = "CONFIRMED"  # 원문·실행 결과로 확인함
    INFERRED = "INFERRED"  # 근거로부터 추론함
    UNVERIFIED = "UNVERIFIED"  # 확인하지 못함


class SettlementType(Enum):
    CASH = "CASH"
    PHYSICAL = "PHYSICAL"


class PriceUnit(Enum):
    INDEX_POINT = "INDEX_POINT"  # 지수 포인트. 가격 × 승수 = 계약 통화 금액


class SettlementPriceType(Enum):
    DAILY = "DAILY"  # 일별 정산가
    INTRADAY = "INTRADAY"  # 장중 정산가. 일별 최종 정산가로 쓰지 않는다


class SettlementRevisionStatus(Enum):
    PRELIMINARY = "PRELIMINARY"  # 잠정 정산가
    FINAL = "FINAL"  # 최종 정산가. 같은 거래일에 다른 최종가가 뒤에 오면 정정이다 (FR-04)
    WITHDRAWN = "WITHDRAWN"  # 공급자가 앞서 낸 정산 통계를 삭제함. 가격이 없을 수 있다


class AvailabilityEvidence(Enum):
    """이용 가능 시각의 근거. 위에서부터 강하다 (FR-05, ADR-0004 §6.5, D3A-13).

    SYSTEM_RECEIPT: 이 시스템이 원본을 받은 시각(`ingested_at`). 과거 데이터를 나중에 받으면 그 수신 시각이다.
    VENDOR_CAPTURE: 공급자 수집 서버가 받은 시각(`vendor_received_at`). 사용자가 실제로 받은 시각이 아니다.
    EXCHANGE_PUBLICATION: 거래소가 표시한 시각(`published_at`). 공급자나 사용자가 받은 시각이 아니다.
    연구용 PIT에서 어느 근거까지 받아들일지는 정하지 않았다 (ADR-0004 Q4-3, D3A-13). 조회하는 쪽이 명시한다.
    """

    SYSTEM_RECEIPT = "SYSTEM_RECEIPT"
    VENDOR_CAPTURE = "VENDOR_CAPTURE"
    EXCHANGE_PUBLICATION = "EXCHANGE_PUBLICATION"


_EVIDENCE_STRENGTH = {
    AvailabilityEvidence.SYSTEM_RECEIPT: 3,
    AvailabilityEvidence.VENDOR_CAPTURE: 2,
    AvailabilityEvidence.EXCHANGE_PUBLICATION: 1,
}


def evidence_at_least(level: AvailabilityEvidence, accepted: AvailabilityEvidence) -> bool:
    """`level`이 `accepted`와 같거나 더 강한 근거인가."""
    return _EVIDENCE_STRENGTH[level] >= _EVIDENCE_STRENGTH[accepted]


def recorded_availability_evidence(*, published_at: datetime | None, vendor_received_at: datetime | None) -> AvailabilityEvidence:
    """정산가 사건의 `availability_evidence`: 시스템 수신 전 시각 가운데 가장 강한 근거.

    공급자 수집 시각이 있으면 VENDOR_CAPTURE, 없고 거래소 시각만 있으면 EXCHANGE_PUBLICATION, 둘 다 없으면 SYSTEM_RECEIPT(이 시스템의
    수신 시각만 근거)다.
    """
    if vendor_received_at is not None:
        return AvailabilityEvidence.VENDOR_CAPTURE
    if published_at is not None:
        return AvailabilityEvidence.EXCHANGE_PUBLICATION
    return AvailabilityEvidence.SYSTEM_RECEIPT


def require_date(value: object, name: str) -> date:
    # datetime은 date의 하위 클래스다. 시각을 날짜 라벨로 받지 않는다.
    if not isinstance(value, date) or isinstance(value, datetime):
        raise ValueError(f"{name} must be a date, not a datetime.")

    return date(value.year, value.month, value.day)


def _require_member(value: object, kind: type[Enum], name: str) -> Enum:
    if not isinstance(value, kind):
        raise ValueError(f"{name} must be a {kind.__name__}.")

    return value


def _require_bool(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be a bool.")

    return value


def _require_positive_decimal(value: object, name: str) -> Decimal:
    result = require_decimal(value, name)
    if result <= 0:
        raise ValueError(f"{name} must be greater than 0.")

    return result


def _require_optional_instant(value: object, name: str) -> datetime | None:
    return None if value is None else require_utc_instant(value, name)


def _require_tuple(value: object, name: str) -> tuple:
    if not isinstance(value, tuple):
        raise ValueError(f"{name} must be a tuple.")

    return value


def _require_sorted_dates(values: object, name: str) -> tuple[date, ...]:
    dates = tuple(require_date(item, name) for item in _require_tuple(values, name))
    if any(left >= right for left, right in zip(dates, dates[1:])):
        raise ValueError(f"{name} must be strictly increasing.")

    return dates


@dataclass(frozen=True, kw_only=True)
class ReferenceProvenance:
    """참조 데이터의 출처, 기준 시각, 확인 수준 (I6-11, TC-A15). `sources`는 문서 URL이나 자료 이름이며 하나 이상이다."""

    sources: tuple[str, ...]
    as_of: datetime
    verification: VerificationLevel

    def __post_init__(self) -> None:
        sources = tuple(require_identifier(item, "source") for item in _require_tuple(self.sources, "sources"))
        if not sources or len(set(sources)) != len(sources):
            raise ValueError("sources must be a non-empty tuple without duplicates.")
        object.__setattr__(self, "sources", sources)
        require_utc_instant(self.as_of, "as_of")
        _require_member(self.verification, VerificationLevel, "verification")


@dataclass(frozen=True, kw_only=True)
class FuturesContractMetadata:
    """선물 월물 하나의 계약 메타데이터 (ADR-0006 I6-3·I6-6·I6-11).

    `contract_id`는 `{exchange}.{product_root}.{YYYY}-{MM}`이며 거래소·상품·연·월과 일치해야 한다. 단위: 가격과 tick 크기는
    `price_unit`, 승수는 `currency`/`price_unit`, tick value는 `currency`. 선언한 tick value는 tick 크기 × 승수와 정확히 같아야 한다
    (반올림 없음, 다르면 ValueError). `settlement_tick_size`는 정산가가 거래 tick이 아닌 청산 tick으로 정해질 때의 크기이며 모르면
    None이다 (outright tick으로 대신하지 않음). `last_trading_at`은 문서에서 확인한 마지막 거래 시각을 UTC로 받은 값이다 (이 코드는
    현지 시각을 변환하지 않는다, ADR-0007 C7-2, ADR-0010 Q10-7). 월물이 다른 시장의 거래일 규칙(예: 만기 월 이전 만기)을 가질 수 있어
    마지막 거래일과 월물 월의 관계는 검사하지 않는다.
    """

    exchange: str
    product_root: str
    contract_id: str
    contract_year: int
    contract_month: int
    multiplier: Decimal
    outright_tick_size: Decimal
    outright_tick_value: Decimal
    settlement_tick_size: Decimal | None
    currency: str
    price_unit: PriceUnit
    last_trading_date: date
    last_trading_at: datetime
    settlement_type: SettlementType
    metadata_version: str
    provenance: ReferenceProvenance

    def __post_init__(self) -> None:
        for name in ("exchange", "product_root"):
            value = require_identifier(getattr(self, name), name)
            if _CODE.fullmatch(value) is None:
                raise ValueError(f"{name} must use upper-case ASCII letters and digits only.")
            object.__setattr__(self, name, value)
        year = require_int(self.contract_year, "contract_year")
        month = require_int(self.contract_month, "contract_month")
        if not 1000 <= year <= 9999 or not 1 <= month <= 12:
            raise ValueError("contract_year must have four digits and contract_month must be 1 to 12.")
        object.__setattr__(self, "contract_year", year)
        object.__setattr__(self, "contract_month", month)
        contract_id = require_identifier(self.contract_id, "contract_id")
        if contract_id != f"{self.exchange}.{self.product_root}.{year:04d}-{month:02d}":
            raise ValueError("contract_id must match exchange, product_root, contract_year and contract_month.")
        object.__setattr__(self, "contract_id", contract_id)

        for name in ("multiplier", "outright_tick_size", "outright_tick_value"):
            object.__setattr__(self, name, _require_positive_decimal(getattr(self, name), name))
        if self.settlement_tick_size is not None:
            object.__setattr__(self, "settlement_tick_size", _require_positive_decimal(self.settlement_tick_size, "settlement_tick_size"))
        # tick value [통화] = tick 크기 [가격 단위] × 승수 [통화/가격 단위]. 정확한 곱이며 반올림이 생기면 Inexact로 실패한다.
        if EXACT_DECIMAL_CONTEXT.multiply(self.outright_tick_size, self.multiplier) != self.outright_tick_value:
            raise ValueError("outright_tick_value must equal outright_tick_size × multiplier exactly.")

        currency = require_identifier(self.currency, "currency")
        if _CURRENCY.fullmatch(currency) is None:
            raise ValueError("currency must be a three-letter upper-case code.")
        object.__setattr__(self, "currency", currency)
        _require_member(self.price_unit, PriceUnit, "price_unit")
        object.__setattr__(self, "last_trading_date", require_date(self.last_trading_date, "last_trading_date"))
        require_utc_instant(self.last_trading_at, "last_trading_at")
        _require_member(self.settlement_type, SettlementType, "settlement_type")
        object.__setattr__(self, "metadata_version", require_identifier(self.metadata_version, "metadata_version"))
        if type(self.provenance) is not ReferenceProvenance:
            raise ValueError("provenance must be a ReferenceProvenance.")


@dataclass(frozen=True, kw_only=True)
class RawSnapshotManifest:
    """보관한 원본 파일 하나의 manifest (FR-01, ADR-0011 FP-11·FP-12). 원본 바이트는 Adapter가 이 manifest와 함께 보관한다.

    `snapshot_id`는 `raw-sha256-` + 원본 바이트의 SHA-256(소문자 16진수)이다. 같은 바이트는 같은 ID다. `acquired_at`은 이 시스템이
    원본을 받은 시각이며 정산가 사건의 `ingested_at`이 된다. `encoding`은 원본 바이트의 형식 이름(예: `csv`, `csv.zst`)이며 해석은
    Adapter가 한다. `request`는 요청 매개변수 (이름, 값)이며 이름 순으로 정렬하고 같은 이름은 한 번만 쓴다. 자격증명처럼 보이는
    이름(key, token, secret, password, auth 등)은 받지 않는다 (CLAUDE.md §5). 값에 섞인 비밀정보는 검사하지 못한다.
    """

    snapshot_id: str
    data_origin: DataOrigin
    provider: str
    dataset: str
    schema: str
    encoding: str
    original_filename: str
    raw_sha256: str
    byte_size: int
    acquired_at: datetime
    acquisition_method: str
    request: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        for name in ("snapshot_id", "provider", "dataset", "schema", "encoding", "original_filename", "raw_sha256", "acquisition_method"):
            object.__setattr__(self, name, require_identifier(getattr(self, name), name))
        if _SHA256.fullmatch(self.raw_sha256) is None:
            raise ValueError("raw_sha256 must be 64 lower-case hexadecimal characters.")
        if self.snapshot_id != RAW_SNAPSHOT_ID_PREFIX + self.raw_sha256:
            raise ValueError("snapshot_id must be 'raw-sha256-' followed by raw_sha256.")
        _require_member(self.data_origin, DataOrigin, "data_origin")
        name = self.original_filename
        if name in (".", "..") or any(mark in name for mark in ("/", "\\", "\x00")):
            raise ValueError("original_filename must be a plain file name.")
        byte_size = require_int(self.byte_size, "byte_size")
        if byte_size < 0:
            raise ValueError("byte_size must not be negative.")
        object.__setattr__(self, "byte_size", byte_size)
        require_utc_instant(self.acquired_at, "acquired_at")

        pairs = []
        for pair in _require_tuple(self.request, "request"):
            if not isinstance(pair, tuple) or len(pair) != 2:
                raise ValueError("request must contain (name, value) pairs.")
            key, value = require_identifier(pair[0], "request name"), require_identifier(pair[1], "request value")
            if _CREDENTIAL_NAME.search(key) is not None:
                raise ValueError("request must not record credential parameters.")
            pairs.append((key, value))
        if any(left[0] >= right[0] for left, right in zip(pairs, pairs[1:])):
            raise ValueError("request names must be unique and sorted.")
        object.__setattr__(self, "request", tuple(pairs))


@dataclass(frozen=True, kw_only=True)
class SettlementEvent:
    """공급자 정산 통계 기록 하나를 번역한 정산가 사건 (TC-C4의 정산가 부분, FR-04).

    단위: `price`는 월물 메타데이터의 가격 단위. PRELIMINARY·FINAL은 가격이 있어야 하고, WITHDRAWN은 공급자가 준 가격이 있을 때만 가진다.
    시각은 모두 UTC 순간이다. `observed_at`은 정산가가 정해진 시각, `published_at`은 거래소가 표시한 시각, `vendor_received_at`은 공급자
    수집 시각이며 모르면 None이다. `ingested_at`은 이 시스템이 원본을 받은 시각이다. `availability_evidence`는 시스템 수신 전 시각
    가운데 가장 강한 근거이며 시각 필드와 맞아야 한다 (`recorded_availability_evidence`). `actual`이 False면 이론가, `at_trading_tick`이
    True면 거래 tick으로 정한 정산가다 (False면 청산 tick 또는 반올림하지 않은 잠정가일 수 있음). 같은 거래일의 여러 기록은 지우지 않고
    모두 둔다 (원본 수정 이력 보존).
    """

    contract_id: str
    trading_date: date
    price_type: SettlementPriceType
    price: Decimal | None
    revision_status: SettlementRevisionStatus
    actual: bool
    at_trading_tick: bool
    observed_at: datetime | None
    published_at: datetime | None
    vendor_received_at: datetime | None
    ingested_at: datetime
    source_record_id: str
    source_snapshot_id: str
    availability_evidence: AvailabilityEvidence

    def __post_init__(self) -> None:
        for name in ("contract_id", "source_record_id", "source_snapshot_id"):
            object.__setattr__(self, name, require_identifier(getattr(self, name), name))
        object.__setattr__(self, "trading_date", require_date(self.trading_date, "trading_date"))
        _require_member(self.price_type, SettlementPriceType, "price_type")
        _require_member(self.revision_status, SettlementRevisionStatus, "revision_status")
        if self.price is None:
            if self.revision_status is not SettlementRevisionStatus.WITHDRAWN:
                raise ValueError("a preliminary or final settlement must have a price.")
        else:
            object.__setattr__(self, "price", require_decimal(self.price, "price"))
        _require_bool(self.actual, "actual")
        _require_bool(self.at_trading_tick, "at_trading_tick")
        for name in ("observed_at", "published_at", "vendor_received_at"):
            _require_optional_instant(getattr(self, name), name)
        require_utc_instant(self.ingested_at, "ingested_at")
        _require_member(self.availability_evidence, AvailabilityEvidence, "availability_evidence")
        expected = recorded_availability_evidence(published_at=self.published_at, vendor_received_at=self.vendor_received_at)
        if self.availability_evidence is not expected:
            raise ValueError(f"availability_evidence must be {expected.name} for the recorded timestamps.")


def evidence_timestamps(event: SettlementEvent) -> tuple[tuple[AvailabilityEvidence, datetime | None], ...]:
    """정산가 사건의 근거별 시각 (강한 근거부터). 시스템 수신 시각은 항상 있고 나머지는 없을 수 있다."""
    return (
        (AvailabilityEvidence.SYSTEM_RECEIPT, event.ingested_at),
        (AvailabilityEvidence.VENDOR_CAPTURE, event.vendor_received_at),
        (AvailabilityEvidence.EXCHANGE_PUBLICATION, event.published_at),
    )


def earliest_accepted_evidence(event: SettlementEvent, accepted: AvailabilityEvidence) -> tuple[datetime, AvailabilityEvidence]:
    """받아들인 근거와 그보다 강한 근거의 시각 가운데 가장 이른 시각과 그 근거. 같은 시각이면 강한 근거다."""
    eligible = [(moment, level) for level, moment in evidence_timestamps(event) if moment is not None and evidence_at_least(level, accepted)]
    earliest = min(moment for moment, _ in eligible)
    return earliest, next(level for moment, level in eligible if moment == earliest)


class QualityStatus(Enum):
    PASSED = "PASSED"  # 검사한 범위에서 문제가 없다
    WARNING = "WARNING"  # 쓸 수는 있으나 알려야 할 문제나 미확인 사항이 있다
    NOT_ASSESSABLE = "NOT_ASSESSABLE"  # 판정에 필요한 입력(예: 거래소 달력)이 없다
    BLOCKED = "BLOCKED"  # 연구 데이터로 쓰면 안 되는 결함이 있다


_QUALITY_SEVERITY = {QualityStatus.PASSED: 0, QualityStatus.WARNING: 1, QualityStatus.NOT_ASSESSABLE: 2, QualityStatus.BLOCKED: 3}


def worst_quality_status(statuses) -> QualityStatus:
    """가장 심한 상태 (BLOCKED > NOT_ASSESSABLE > WARNING > PASSED). 비어 있으면 PASSED."""
    return max(statuses, key=_QUALITY_SEVERITY.__getitem__, default=QualityStatus.PASSED)


class QualityCheckName(Enum):
    SCHEMA = "SCHEMA"
    CONTRACT_IDENTITY = "CONTRACT_IDENTITY"
    DECIMAL_PRICE = "DECIMAL_PRICE"
    PRICE_UNIT = "PRICE_UNIT"
    TICK = "TICK"
    DATE_AND_EXPIRY = "DATE_AND_EXPIRY"
    TIMESTAMP_TIMEZONE = "TIMESTAMP_TIMEZONE"
    DUPLICATES_AND_CONFLICTS = "DUPLICATES_AND_CONFLICTS"
    MISSING_SESSIONS = "MISSING_SESSIONS"
    REVISION_ORDER = "REVISION_ORDER"
    SOURCE_INTEGRITY = "SOURCE_INTEGRITY"
    AVAILABILITY_EVIDENCE = "AVAILABILITY_EVIDENCE"
    COVERAGE = "COVERAGE"


@dataclass(frozen=True, kw_only=True)
class SourceIssue:
    """Adapter가 원본에서 찾은 문제 하나. `blocking`이면 그 행은 정산가 사건이 되지 않았고 품질 검사 `check`를 BLOCKED로 만든다.
    아니면 사건은 만들어졌거나 확인하지 못한 사항이며 WARNING이 된다. `record_ref`는 원본 안의 위치(예: `line:12`)다."""

    check: QualityCheckName
    code: str
    record_ref: str
    detail: str
    blocking: bool

    def __post_init__(self) -> None:
        _require_member(self.check, QualityCheckName, "check")
        for name in ("code", "record_ref", "detail"):
            object.__setattr__(self, name, require_identifier(getattr(self, name), name))
        if _ISSUE_CODE.fullmatch(self.code) is None:
            raise ValueError("code must use upper-case letters, digits and underscores.")
        _require_bool(self.blocking, "blocking")


@dataclass(frozen=True, kw_only=True)
class QualityFinding:
    """품질 검사의 발견 하나: 사유 코드, 그 상태, 해당 레코드·날짜 참조(정렬, 중복 없음)."""

    code: str
    status: QualityStatus
    refs: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", require_identifier(self.code, "code"))
        if _ISSUE_CODE.fullmatch(self.code) is None:
            raise ValueError("code must use upper-case letters, digits and underscores.")
        if _require_member(self.status, QualityStatus, "status") is QualityStatus.PASSED:
            raise ValueError("a finding cannot be PASSED.")
        refs = tuple(require_identifier(item, "ref") for item in _require_tuple(self.refs, "refs"))
        if not refs or any(left >= right for left, right in zip(refs, refs[1:])):
            raise ValueError("refs must be a non-empty, sorted tuple without duplicates.")
        object.__setattr__(self, "refs", refs)


@dataclass(frozen=True, kw_only=True)
class QualityCheck:
    """품질 검사 하나의 결과. 상태는 발견 가운데 가장 심한 것이고 발견이 없으면 PASSED다. 발견은 사유 코드 순이다."""

    name: QualityCheckName
    status: QualityStatus
    findings: tuple[QualityFinding, ...]

    def __post_init__(self) -> None:
        _require_member(self.name, QualityCheckName, "name")
        findings = _require_tuple(self.findings, "findings")
        if any(type(item) is not QualityFinding for item in findings):
            raise ValueError("findings must contain QualityFinding values.")
        if any(left.code >= right.code for left, right in zip(findings, findings[1:])):
            raise ValueError("findings must be sorted by code without duplicates.")
        if self.status is not worst_quality_status(item.status for item in findings):
            raise ValueError("status must be the most severe finding status (PASSED without findings).")

    @property
    def reasons(self) -> tuple[str, ...]:
        return tuple(item.code for item in self.findings)


@dataclass(frozen=True, kw_only=True)
class TradingCalendarReference:
    """한 거래소의 예상 거래일 목록 (결측 거래일 판정 입력, ADR-0007 X7-6). 출처와 확인 수준을 함께 가진다 (I6-11).

    `coverage_start`~`coverage_end`(포함) 안에서 목록에 없는 날은 휴장일, 목록에 있는데 최종가가 없는 날은 결측이다. 범위 밖은 이 목록이
    말하지 않는다. 반일장 같은 세부는 표현하지 않는다.
    """

    exchange: str
    coverage_start: date
    coverage_end: date
    dates: tuple[date, ...]
    provenance: ReferenceProvenance

    def __post_init__(self) -> None:
        object.__setattr__(self, "exchange", require_identifier(self.exchange, "exchange"))
        start, end = require_date(self.coverage_start, "coverage_start"), require_date(self.coverage_end, "coverage_end")
        if start > end:
            raise ValueError("coverage_start must not be later than coverage_end.")
        object.__setattr__(self, "coverage_start", start)
        object.__setattr__(self, "coverage_end", end)
        dates = _require_sorted_dates(self.dates, "dates")
        if any(not start <= item <= end for item in dates):
            raise ValueError("calendar dates must lie within the coverage range.")
        object.__setattr__(self, "dates", dates)
        if type(self.provenance) is not ReferenceProvenance:
            raise ValueError("provenance must be a ReferenceProvenance.")


class PitStatus(Enum):
    AVAILABLE = "AVAILABLE"  # cutoff까지 받아들인 근거로 보인 최종가가 있다
    NOT_AVAILABLE = "NOT_AVAILABLE"  # cutoff까지 보인 최종가가 없다 (잠정가만 있음, 철회됨, 보인 기록 없음)
    AMBIGUOUS = "AMBIGUOUS"  # 보인 기록끼리 상충해 하나를 고를 수 없다
    EVIDENCE_INSUFFICIENT = "EVIDENCE_INSUFFICIENT"  # 받아들인 근거의 시각이 없는 기록이 있어 cutoff 전에 보였는지 알 수 없다


class RevisionRole(Enum):
    ORIGINAL_FINAL = "ORIGINAL_FINAL"  # 같은 거래일에 보인 최종가가 모두 같은 가격
    CORRECTION = "CORRECTION"  # 같은 거래일에 먼저 보인 최종가와 다른 가격으로 정정된 최종가


@dataclass(frozen=True, kw_only=True)
class SettlementAsOf:
    """`get_final_settlement_asof`의 결과. AVAILABLE이면 사건·정정 여부·이용 가능 시각·쓴 근거가 있고 사유가 없다. 이용 가능 시각은
    그 사건에서 받아들인 근거 이상의 가장 이른 시각이고, 쓴 근거는 그 시각의 근거다. 다른 상태는 가격을 내지 않고 사유가 하나 이상 있다
    (fail closed). `cutoff_at`은 UTC로 바꾼 조회 시각이다.

    `event`는 원본 기록 그대로이며 cutoff 뒤의 시각(공급자 수집 시각, 시스템 수신 시각)을 담을 수 있다. cutoff 시점에 알려진 값으로
    쓰는 것은 가격, 정정 여부, `available_at`, `evidence_used`이며, 사건의 다른 시각 필드는 추적용이다.
    """

    contract_id: str
    trading_date: date
    cutoff_at: datetime
    accepted_evidence: AvailabilityEvidence
    status: PitStatus
    reasons: tuple[str, ...]
    event: SettlementEvent | None
    revision_role: RevisionRole | None
    available_at: datetime | None
    evidence_used: AvailabilityEvidence | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "contract_id", require_identifier(self.contract_id, "contract_id"))
        object.__setattr__(self, "trading_date", require_date(self.trading_date, "trading_date"))
        require_utc_instant(self.cutoff_at, "cutoff_at")
        _require_member(self.accepted_evidence, AvailabilityEvidence, "accepted_evidence")
        _require_member(self.status, PitStatus, "status")
        reasons = tuple(require_identifier(item, "reason") for item in _require_tuple(self.reasons, "reasons"))
        object.__setattr__(self, "reasons", reasons)
        parts = (self.event, self.revision_role, self.available_at, self.evidence_used)
        if self.status is PitStatus.AVAILABLE:
            if reasons or any(item is None for item in parts):
                raise ValueError("an AVAILABLE result has an event, revision role, availability time and evidence, and no reasons.")
            event = self.event
            if type(event) is not SettlementEvent or event.revision_status is not SettlementRevisionStatus.FINAL:
                raise ValueError("an AVAILABLE result carries a final settlement event.")
            if (event.contract_id, event.trading_date) != (self.contract_id, self.trading_date):
                raise ValueError("the event must belong to the queried contract and trading date.")
            _require_member(self.revision_role, RevisionRole, "revision_role")
            if require_utc_instant(self.available_at, "available_at") > self.cutoff_at:
                raise ValueError("available_at must not be later than cutoff_at.")
            if not evidence_at_least(_require_member(self.evidence_used, AvailabilityEvidence, "evidence_used"), self.accepted_evidence):
                raise ValueError("evidence_used must be at least as strong as accepted_evidence.")
            if (self.available_at, self.evidence_used) != earliest_accepted_evidence(event, self.accepted_evidence):
                raise ValueError("available_at and evidence_used must be the event's earliest timestamp on accepted or stronger evidence.")
        elif not reasons or any(item is not None for item in parts):
            raise ValueError("a result without a price has reasons and no event, revision role, time or evidence.")

    @property
    def price(self) -> Decimal | None:
        return None if self.event is None else self.event.price


class SeriesBasis(Enum):
    LATEST_FINAL_IN_SNAPSHOT = "LATEST_FINAL_IN_SNAPSHOT"  # Snapshot에 있는 마지막 최종가. 이용 가능 시각을 보지 않는다 (PIT 아님)
    AS_OF_CUTOFF = "AS_OF_CUTOFF"  # 한 cutoff에서 받아들인 근거로 보인 최종가 (PIT)


@dataclass(frozen=True, kw_only=True)
class ResearchSettlementPoint:
    """연구용 정산가 Series의 한 점. Raw Snapshot까지 추적할 수 있도록 원본 레코드와 Snapshot ID를 가진다 (FR-08).
    As-of Series의 점은 이용 가능 시각과 쓴 근거를 가지고, 최신 최종가 Series의 점은 가지지 않는다 (None)."""

    trading_date: date
    price: Decimal
    revision_role: RevisionRole
    source_record_id: str
    source_snapshot_id: str
    available_at: datetime | None
    evidence_used: AvailabilityEvidence | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "trading_date", require_date(self.trading_date, "trading_date"))
        object.__setattr__(self, "price", require_decimal(self.price, "price"))
        _require_member(self.revision_role, RevisionRole, "revision_role")
        for name in ("source_record_id", "source_snapshot_id"):
            object.__setattr__(self, name, require_identifier(getattr(self, name), name))
        if (self.available_at is None) != (self.evidence_used is None):
            raise ValueError("available_at and evidence_used are both present or both absent.")
        if self.available_at is not None:
            require_utc_instant(self.available_at, "available_at")
            _require_member(self.evidence_used, AvailabilityEvidence, "evidence_used")


@dataclass(frozen=True, kw_only=True)
class SeriesExclusion:
    """Series에 점이 없는 거래일과 그 이유 (결측을 채우지 않고 보고한다, ADR-0007 X7-2·X7-3)."""

    trading_date: date
    status: PitStatus
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "trading_date", require_date(self.trading_date, "trading_date"))
        if _require_member(self.status, PitStatus, "status") is PitStatus.AVAILABLE:
            raise ValueError("an excluded trading date cannot be AVAILABLE.")
        reasons = tuple(require_identifier(item, "reason") for item in _require_tuple(self.reasons, "reasons"))
        if not reasons:
            raise ValueError("an excluded trading date needs at least one reason.")
        object.__setattr__(self, "reasons", reasons)


@dataclass(frozen=True, kw_only=True)
class ResearchSettlementSeries:
    """월물 하나의 연구용 일별 최종 정산가 Series (FR-08). 거래일마다 점 하나 또는 제외 하나이며 날짜 순이다. 보간·forward fill이 없다.

    `basis`가 LATEST_FINAL_IN_SNAPSHOT이면 `cutoff_at`·`accepted_evidence`가 없고, AS_OF_CUTOFF이면 둘 다 있으며 모든 점의 이용 가능
    시각이 cutoff 이하이고 쓴 근거가 받아들인 근거 이상이다. `selection_policy`는 최종가를 고른 규칙의 버전이다.
    """

    contract_id: str
    basis: SeriesBasis
    cutoff_at: datetime | None
    accepted_evidence: AvailabilityEvidence | None
    selection_policy: str
    points: tuple[ResearchSettlementPoint, ...]
    excluded: tuple[SeriesExclusion, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "contract_id", require_identifier(self.contract_id, "contract_id"))
        object.__setattr__(self, "selection_policy", require_identifier(self.selection_policy, "selection_policy"))
        _require_member(self.basis, SeriesBasis, "basis")
        points, excluded = _require_tuple(self.points, "points"), _require_tuple(self.excluded, "excluded")
        if any(type(item) is not ResearchSettlementPoint for item in points) or any(type(item) is not SeriesExclusion for item in excluded):
            raise ValueError("points and excluded must contain ResearchSettlementPoint and SeriesExclusion values.")
        _require_sorted_dates(tuple(item.trading_date for item in points), "point trading dates")
        _require_sorted_dates(tuple(item.trading_date for item in excluded), "excluded trading dates")
        if {item.trading_date for item in points} & {item.trading_date for item in excluded}:
            raise ValueError("a trading date cannot be both a point and an exclusion.")
        if self.basis is SeriesBasis.LATEST_FINAL_IN_SNAPSHOT:
            if self.cutoff_at is not None or self.accepted_evidence is not None or any(item.available_at is not None for item in points):
                raise ValueError("a latest-final series has no cutoff, accepted evidence or availability times.")
            return
        cutoff = require_utc_instant(self.cutoff_at, "cutoff_at")
        accepted = _require_member(self.accepted_evidence, AvailabilityEvidence, "accepted_evidence")
        for item in points:
            if item.available_at is None or item.available_at > cutoff or not evidence_at_least(item.evidence_used, accepted):
                raise ValueError("every as-of point must have been available by cutoff_at on accepted evidence.")


@dataclass(frozen=True, kw_only=True)
class SettlementQualityReport:
    """월물 하나의 정산가 품질 보고서 (FR-06). 검사는 `QualityCheckName` 순서로 하나씩 있고, 전체 상태는 가장 심한 검사 상태다.

    `final_trading_dates`는 요청 기간 안에서 Snapshot의 최신 최종가가 있는 거래일, `missing_trading_dates`는 달력에 있는데 최종가가 없는
    거래일 (달력이 있을 때만), `unverified_gaps`는 달력이 없을 때 최종가가 없는 평일이다 (휴장인지 결측인지 모름). `excluded`는 기록이
    있지만 최신 최종가를 고를 수 없는 거래일, `corrected_trading_dates`는 최종가가 정정된 거래일이다 (모두 요청 기간 안). `evidence_counts`는
    최종가 기록의 근거별 개수, `not_established`는 이 보고서가 확인하지 않는 항목이다.
    """

    contract_id: str
    rule_version: str
    metadata_version: str
    snapshot_ids: tuple[str, ...]
    requested_start: date
    requested_end: date
    minimum_final_days: int
    status: QualityStatus
    checks: tuple[QualityCheck, ...]
    final_trading_dates: tuple[date, ...]
    missing_trading_dates: tuple[date, ...]
    unverified_gaps: tuple[date, ...]
    excluded: tuple[SeriesExclusion, ...]
    corrected_trading_dates: tuple[date, ...]
    evidence_counts: tuple[tuple[AvailabilityEvidence, int], ...]
    not_established: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in ("contract_id", "rule_version", "metadata_version"):
            object.__setattr__(self, name, require_identifier(getattr(self, name), name))
        snapshot_ids = tuple(require_identifier(item, "snapshot_id") for item in _require_tuple(self.snapshot_ids, "snapshot_ids"))
        if not snapshot_ids or any(left >= right for left, right in zip(snapshot_ids, snapshot_ids[1:])):
            raise ValueError("snapshot_ids must be a non-empty, sorted tuple without duplicates.")
        object.__setattr__(self, "snapshot_ids", snapshot_ids)
        start, end = require_date(self.requested_start, "requested_start"), require_date(self.requested_end, "requested_end")
        if start > end:
            raise ValueError("requested_start must not be later than requested_end.")
        if require_int(self.minimum_final_days, "minimum_final_days") < 0:
            raise ValueError("minimum_final_days must not be negative.")
        checks = _require_tuple(self.checks, "checks")
        if any(type(item) is not QualityCheck for item in checks) or tuple(item.name for item in checks) != tuple(QualityCheckName):
            raise ValueError("checks must contain one QualityCheck per QualityCheckName, in order.")
        if self.status is not worst_quality_status(item.status for item in checks):
            raise ValueError("status must be the most severe check status.")
        for name in ("final_trading_dates", "missing_trading_dates", "unverified_gaps", "corrected_trading_dates"):
            object.__setattr__(self, name, _require_sorted_dates(getattr(self, name), name))
        excluded = _require_tuple(self.excluded, "excluded")
        if any(type(item) is not SeriesExclusion for item in excluded):
            raise ValueError("excluded must contain SeriesExclusion values.")
        _require_sorted_dates(tuple(item.trading_date for item in excluded), "excluded trading dates")
        counts = _require_tuple(self.evidence_counts, "evidence_counts")
        if (
            any(not isinstance(item, tuple) or len(item) != 2 for item in counts)
            or tuple(item[0] for item in counts) != tuple(AvailabilityEvidence)
            or any(require_int(item[1], "count") < 0 for item in counts)
        ):
            raise ValueError("evidence_counts must list every AvailabilityEvidence once, in order, with a count.")
        not_established = _require_tuple(self.not_established, "not_established")
        object.__setattr__(self, "not_established", tuple(require_identifier(item, "not_established") for item in not_established))
