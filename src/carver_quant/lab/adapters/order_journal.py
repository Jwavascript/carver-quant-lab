"""P0-03C Slice 4 주문 기록 Journal: 추가 전용 저장과 재시작 복구 (실험용 로컬 Persistence Adapter).

ADR-0009 §6.1 (주문·체결 이벤트의 추가 전용 기록), §6.4a (같은 키의 같은 내용은 중복 수신, 다른 내용은 두 기록을 보관하고 두 번째는
반영하지 않음), ADR-0012 BR-3 (1)~(3) (저장소의 영속화 확인 전에는 성공을 보고하지 않음), BR-11 (예고 없이 달라진 기록은 무결성
오류), 승인 원칙 16 (재시작 때 기록만 믿지 않음), ADR-0011 FP-16 (schema version). Persistence Adapter다 (ADR-0010 §6.2, PK-5):
`lab.domain`, 같은 패키지의 직렬화 모듈, 표준 라이브러리만 import하고 금융 계산 코어(`accounting`)를 import하지 않는다.
받은 기록을 고치거나 고르거나 버리지 않고 그대로 보관한다. 기록 사이의 금융적 모순(체결 감소, UNKNOWN 해소 규칙 등)은 판단하지 않으며,
복원한 기록을 받는 기존 순수 함수(`orders_as_of`, `orders_from_evidence_as_of`, `assess_l3_gate_as_of`)가 판단한다.

실험용 구현 선택 (운영 정책이 아니다. 저장소 종류·트랜잭션·디스크 동기화·영속화 보장 수준은 Q12-7, 보관 위치·형식은 Q9-9·Q11-10):
- 저장소: 표준 라이브러리 sqlite3, 파일 하나, rollback journal(DELETE), `synchronous = FULL`. 교체 가능한 로컬 실험 구현이다.
- 성공: 쓰기 트랜잭션(BEGIN IMMEDIATE)의 COMMIT이 오류 없이 끝난 뒤에만 결과를 돌려준다. SQLite가 보고한 커밋이 전원 장애·디스크
  캐시 손실 뒤에도 남는지는 검증하지 않았다 (BR-3: 저장소가 구현·검증되기 전에는 기록 보존을 보장하지 않음).
- 무결성: 항목마다 SHA-256 해시 사슬, head(기록 수, 마지막 해시), SQLite quick_check, schema 객체 비교. 우연한 손상·부분 변경·누락을
  검출할 뿐 위변조 방지가 아니다. 해시를 다시 계산한 위조, head까지 함께 되돌린 절단, 이전 사본 복원은 검출하지 못한다.
- 중복 수신은 저장소를 바꾸지 않는다 (수신 사실 자체는 기록하지 않음).
- 한 프로세스만 쓴다고 가정한다. 다중 프로세스 동시 쓰기는 범위 밖이다.
"""

import hashlib
import json
import os
import sqlite3
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from carver_quant.lab.adapters.journal_codec import (
    JOURNAL_FORMAT,
    JOURNAL_FORMAT_VERSION,
    EncodedRecord,
    JournalEncodingError,
    JournalRecord,
    JournalRecordType,
    decode_record,
    encode_record,
    record_key,
)
from carver_quant.lab.domain.order_events import OrderEvent
from carver_quant.lab.domain.order_evidence import OrderEvidence
from carver_quant.lab.domain.trading_state import TradingStateRecord


class JournalAppendOutcome(Enum):
    APPENDED = "APPENDED"  # 새 기록으로 저장함
    DUPLICATE = "DUPLICATE"  # 같은 키·같은 내용이 이미 있음. 저장소를 바꾸지 않음
    CONFLICT = "CONFLICT"  # 같은 키·다른 내용. 처음 기록은 그대로 두고 받은 기록은 반영하지 않은 채 충돌 항목으로 보관함


class JournalRecoveryStatus(Enum):
    RECOVERED = "RECOVERED"  # 저장된 기록을 손상·누락 없이 복원함. 브로커 기록이 완전하다는 뜻이 아니다
    CONFLICT = "CONFLICT"  # 기록은 온전하지만 같은 키에 다른 내용이 있다. 어느 쪽이 맞는지 고르지 않는다
    INCOMPLETE = "INCOMPLETE"  # Journal 자신이 가진다고 기록한 항목이 없다
    CORRUPT = "CORRUPT"  # 저장 내용이 손상·변경되었거나 형식에 맞지 않는다
    UNSUPPORTED_VERSION = "UNSUPPORTED_VERSION"  # 이 코드가 읽는 schema version이 아니다
    UNREADABLE = "UNREADABLE"  # 파일이 없거나, 읽을 수 없거나, 주문 기록 Journal이 아니다


# 복구가 확인하지 않는 것. RECOVERED여도 이 항목들은 따로 확인해야 한다.
JOURNAL_RECOVERY_NOT_ESTABLISHED = (
    "ORDER_LOG_COMPLETENESS",  # 브로커 쪽 주문 사건이 모두 기록되었는지. OrderLogCompleteness는 호출 경계가 정한다
    "BROKER_RECONCILIATION",  # 재시작 대조 (ADR-0012 BR-3 (6), BR-8). 미구현
    "TAMPER_RESISTANCE",  # 해시를 다시 계산한 위조, head까지 되돌린 절단, 이전 사본 복원은 검출하지 못함
    "POWER_LOSS_DURABILITY",  # 커밋한 기록이 전원 장애 뒤에도 남는지 (Q12-7)
    "FILL_CASH_NAV_STATE",  # 체결 장부·현금 장부·NAV는 저장하지 않음
    "TRADING_STATE_AUTHORITY",  # 복원한 Trading State 기록의 운영상 권위와 해제 정책 (ADR-0003 §6.5)
)


class JournalError(Exception):
    """주문 기록 Journal 오류의 공통 상위 타입."""


class JournalWriteError(JournalError):
    """기록을 확정하지 못했다. 성공을 보고하지 않는다 (BR-3 (3): 확인을 받지 못하면 주문을 보내지 않는다).

    `may_be_persisted`가 True이면 COMMIT을 보낸 뒤 실패해 저장 여부를 알 수 없다. 그 판단은 다시 복구한 결과로만 한다.
    """

    def __init__(self, message: str, *, may_be_persisted: bool) -> None:
        super().__init__(message)
        self.may_be_persisted = may_be_persisted


class JournalIntegrityError(JournalWriteError):
    """기존 Journal이 정상(RECOVERED 또는 CONFLICT)임을 확인하지 못해 쓰지 않았다. 손상·누락된 기록 위에 새 기록을 쌓지 않는다."""

    def __init__(self, status: "JournalRecoveryStatus", reasons: tuple[str, ...]) -> None:
        super().__init__(f"the journal is {status.name} ({', '.join(reasons)}); nothing was written.", may_be_persisted=False)
        self.status = status
        self.reasons = reasons


class JournalRecoveryError(JournalError):
    """정상 복구(RECOVERED)가 아닌 결과에서 기록을 꺼내려 했다."""


@dataclass(frozen=True, kw_only=True)
class JournalAppendResult:
    """기록 하나의 저장 판정. `seq`는 그 기록을 담은 항목 번호다: DUPLICATE는 처음 저장한 항목, CONFLICT는 보관한 충돌 항목."""

    record_type: JournalRecordType
    record_id: str
    outcome: JournalAppendOutcome
    seq: int


@dataclass(frozen=True, kw_only=True)
class JournalAppendReport:
    """커밋이 끝난 뒤의 저장 결과: 받은 순서대로의 판정, Journal의 기록 수와 마지막 해시."""

    results: tuple[JournalAppendResult, ...]
    entry_count: int
    head_digest: str


@dataclass(frozen=True, kw_only=True)
class JournalConflict:
    """같은 키에 다른 내용으로 온 기록. `kept`는 먼저 받아들여 유지되는 기록이며, 같은 사건의 상대 종류(OrderEvent ↔ OrderEvidence)일
    수 있다. `arrived`는 반영하지 않고 보관한 기록이다. 어느 쪽이 맞는지 판단하지 않는다."""

    record_type: JournalRecordType
    record_id: str
    kept_seq: int
    kept: JournalRecord
    arrived_seq: int
    arrived: JournalRecord


@dataclass(frozen=True, kw_only=True)
class JournalRecovery:
    """재시작 복구 결과. 기록은 RECOVERED일 때만, 저장(도착) 순서대로 꺼낼 수 있다.

    RECOVERED는 저장된 기록을 그대로 복원했다는 뜻일 뿐이다. 주문 기록의 완전성, 브로커 대조, 위변조 방지 등은 확인하지 않으며
    (`not_established`), 완전성 값(OrderLogCompleteness)을 만들지 않는다. 다른 상태에서는 사유(`reasons`)가 있고 기록을 내주지 않는다.
    """

    status: JournalRecoveryStatus
    reasons: tuple[str, ...]
    schema_version: int | None
    entry_count: int | None
    head_digest: str | None
    conflicts: tuple[JournalConflict, ...]
    not_established: tuple[str, ...]
    _records: tuple[JournalRecord, ...] = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.status, JournalRecoveryStatus):
            raise ValueError("status must be a JournalRecoveryStatus.")
        recovered = self.status is JournalRecoveryStatus.RECOVERED
        if recovered == bool(self.reasons):
            raise ValueError("a recovered journal has no reasons; any other status states its reasons.")
        if self._records and not recovered:
            raise ValueError("only a recovered journal gives out records.")
        if bool(self.conflicts) != (self.status is JournalRecoveryStatus.CONFLICT):
            raise ValueError("conflicts are reported exactly when the status is CONFLICT.")

    def order_events(self) -> tuple[OrderEvent, ...]:
        """OrderEvent로 저장한 기록만 돌려준다. OrderEvidence에 담긴 사건은 `order_evidence()`로 얻는다 (종류를 섞어 만들지 않음)."""
        return self._recovered(OrderEvent)

    def order_evidence(self) -> tuple[OrderEvidence, ...]:
        """OrderEvidence로 저장한 기록만 돌려준다. OrderEvent로만 저장한 사건에 증거 종류를 지어 붙이지 않는다."""
        return self._recovered(OrderEvidence)

    def trading_state_records(self) -> tuple[TradingStateRecord, ...]:
        return self._recovered(TradingStateRecord)

    def _recovered(self, record_class: type) -> tuple:
        if self.status is not JournalRecoveryStatus.RECOVERED:
            raise JournalRecoveryError(
                f"the journal was not recovered ({self.status.name}: {', '.join(self.reasons)}); it gives out no records."
            )
        return tuple(record for record in self._records if type(record) is record_class)


# 파일 머리의 응용 식별자 (실험용 값). 주문 기록 Journal이 아닌 SQLite 파일을 구분한다.
_APPLICATION_ID = 0x43514C4A
# 형식 버전 1의 schema 객체. sqlite_schema에 저장된 문장이 글자 단위로 같아야 한다.
_SCHEMA = (
    "CREATE TABLE journal_meta (singleton INTEGER PRIMARY KEY CHECK (singleton = 1), entry_count INTEGER NOT NULL, "
    "head_digest TEXT NOT NULL) STRICT",
    "CREATE TABLE journal_entries (seq INTEGER PRIMARY KEY, record_type TEXT NOT NULL, record_id TEXT NOT NULL, "
    "entry_kind TEXT NOT NULL, payload TEXT NOT NULL, prev_digest TEXT NOT NULL, digest TEXT NOT NULL) STRICT",
    "CREATE UNIQUE INDEX journal_records_by_key ON journal_entries (record_type, record_id) WHERE entry_kind = 'RECORD'",
)
_EXPECTED_OBJECTS = (
    ("index", "journal_records_by_key", "journal_entries", _SCHEMA[2]),
    ("table", "journal_entries", "journal_entries", _SCHEMA[1]),
    ("table", "journal_meta", "journal_meta", _SCHEMA[0]),
)
_RECORD = "RECORD"  # 받아들인 기록
_CONFLICT = "CONFLICT"  # 같은 키에 다른 내용으로 온 기록 (반영하지 않음)
_GENESIS_DIGEST = hashlib.sha256(f"{JOURNAL_FORMAT}/{JOURNAL_FORMAT_VERSION}/genesis".encode()).hexdigest()
_PARTNER_TYPE = {
    JournalRecordType.ORDER_EVENT: JournalRecordType.ORDER_EVIDENCE,
    JournalRecordType.ORDER_EVIDENCE: JournalRecordType.ORDER_EVENT,
}
_WRITABLE = (JournalRecoveryStatus.RECOVERED, JournalRecoveryStatus.CONFLICT)


@dataclass(frozen=True)
class _Accepted:
    seq: int
    payload: str
    record: JournalRecord


@dataclass(frozen=True, kw_only=True)
class _Inspection:
    status: JournalRecoveryStatus
    reasons: tuple[str, ...]
    schema_version: int | None = None
    entry_count: int | None = None
    head_digest: str | None = None
    records: tuple[JournalRecord, ...] = ()
    conflicts: tuple[JournalConflict, ...] = ()
    accepted: dict[tuple[JournalRecordType, str], _Accepted] = field(default_factory=dict)
    conflict_seqs: dict[tuple[JournalRecordType, str, str], int] = field(default_factory=dict)


def _entry_digest(seq: int, record_type: str, record_id: str, entry_kind: str, payload: str, prev_digest: str) -> str:
    """항목 해시: 형식 이름·버전, 항목 번호, 기록 종류, ID, 항목 종류, 내용, 앞 항목의 해시를 담은 JSON 배열의 SHA-256."""
    material = json.dumps(
        [f"{JOURNAL_FORMAT}/{JOURNAL_FORMAT_VERSION}/entry", seq, record_type, record_id, entry_kind, payload, prev_digest],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _event_of(record: JournalRecord) -> OrderEvent:
    return record.event if type(record) is OrderEvidence else record


def _conflicting(accepted: dict, record_type: JournalRecordType, record_id: str, payload: str, record: JournalRecord) -> _Accepted | None:
    """record와 모순되는 받아들인 기록: 같은 키의 다른 내용, 또는 같은 사건 ID인데 다른 사건을 담은 상대 종류."""
    same = accepted.get((record_type, record_id))
    if same is not None:
        return same if same.payload != payload else None
    partner_type = _PARTNER_TYPE.get(record_type)
    partner = None if partner_type is None else accepted.get((partner_type, record_id))
    if partner is None or _event_of(partner.record) == _event_of(record):
        return None
    return partner


def _missing(first: int, last: int) -> str:
    # 빠진 번호마다 사유를 만들지 않는다. 손상된 head의 기록 수가 아주 커도 복구가 멈추지 않는다.
    return f"ENTRY_MISSING:{first}" if first == last else f"ENTRY_MISSING:{first}-{last}"


def _verify(schema_version: int, entry_count: int, head_digest: str, rows: list[tuple]) -> _Inspection:
    """읽은 항목을 검사한다 (I/O 없음). 손상·변경은 CORRUPT, 빠진 항목은 INCOMPLETE, 충돌 항목만 있으면 CONFLICT."""
    damaged: list[str] = []
    missing: list[str] = []
    accepted: dict[tuple[JournalRecordType, str], _Accepted] = {}
    conflict_seqs: dict[tuple[JournalRecordType, str, str], int] = {}
    records: list[JournalRecord] = []
    conflicts: list[JournalConflict] = []
    expected = 1
    previous: str | None = _GENESIS_DIGEST
    for seq, record_type_text, record_id, entry_kind, payload, prev_digest, digest in rows:
        if seq < 1:
            damaged.append(f"ENTRY_SEQ_INVALID:{seq}")
            continue
        if seq > entry_count:
            damaged.append(f"ENTRY_BEYOND_HEAD:{seq}")
            continue
        if seq > expected:
            missing.append(_missing(expected, seq - 1))
            previous = None  # 빠진 항목 뒤에서는 사슬을 이을 수 없다. 항목 자신의 해시는 그대로 검사한다
        expected = seq + 1
        if _entry_digest(seq, record_type_text, record_id, entry_kind, payload, prev_digest) != digest:
            damaged.append(f"ENTRY_DIGEST_MISMATCH:{seq}")
        if previous is not None and prev_digest != previous:
            damaged.append(f"ENTRY_CHAIN_BROKEN:{seq}")
        previous = digest
        if seq == entry_count and digest != head_digest:
            damaged.append("HEAD_DIGEST_MISMATCH")
        try:
            record_type = JournalRecordType(record_type_text)
        except ValueError:
            damaged.append(f"ENTRY_FIELD_INVALID:{seq}")
            continue
        if entry_kind not in (_RECORD, _CONFLICT):
            damaged.append(f"ENTRY_FIELD_INVALID:{seq}")
            continue
        try:
            record = decode_record(record_type, payload)
        except JournalEncodingError:
            damaged.append(f"PAYLOAD_INVALID:{seq}")
            continue
        if record_key(record)[1] != record_id:
            damaged.append(f"RECORD_ID_MISMATCH:{seq}")
            continue
        kept = _conflicting(accepted, record_type, record_id, payload, record)
        if entry_kind == _RECORD:
            if (record_type, record_id) in accepted:
                damaged.append(f"DUPLICATE_RECORD_ENTRY:{seq}")
            elif kept is not None:
                damaged.append(f"CROSS_TYPE_MISMATCH:{seq}")
            else:
                accepted[(record_type, record_id)] = _Accepted(seq, payload, record)
                records.append(record)
        elif kept is None or (record_type, record_id, payload) in conflict_seqs:
            damaged.append(f"CONFLICT_ENTRY_INVALID:{seq}")
        else:
            conflict_seqs[(record_type, record_id, payload)] = seq
            conflicts.append(JournalConflict(record_type=record_type, record_id=record_id, kept_seq=kept.seq, kept=kept.record,
                                             arrived_seq=seq, arrived=record))
    if expected <= entry_count:
        missing.append(_missing(expected, entry_count))
    if entry_count == 0 and head_digest != _GENESIS_DIGEST:
        damaged.append("HEAD_DIGEST_MISMATCH")

    if damaged:
        status = JournalRecoveryStatus.CORRUPT
    elif missing:
        status = JournalRecoveryStatus.INCOMPLETE
    elif conflicts:
        status = JournalRecoveryStatus.CONFLICT
    else:
        status = JournalRecoveryStatus.RECOVERED
    return _Inspection(
        status=status,
        reasons=tuple(damaged + missing + [f"RECORD_CONFLICT:{conflict.arrived_seq}" for conflict in conflicts]),
        schema_version=schema_version,
        entry_count=entry_count,
        head_digest=head_digest,
        records=tuple(records),
        conflicts=tuple(conflicts),
        accepted=accepted,
        conflict_seqs=conflict_seqs,
    )


def _scalar(connection: sqlite3.Connection, sql: str) -> object:
    return connection.execute(sql).fetchone()[0]


def _inspect(connection: sqlite3.Connection) -> _Inspection:
    """열린 트랜잭션 안에서 파일 머리, SQLite 자체 검사, schema 객체, head, 항목을 읽고 검사한다. SQLite 오류는 부른 쪽이 처리한다."""
    if _scalar(connection, "PRAGMA application_id") != _APPLICATION_ID:
        return _Inspection(status=JournalRecoveryStatus.UNREADABLE, reasons=("NOT_AN_ORDER_JOURNAL",))
    version = _scalar(connection, "PRAGMA user_version")
    if version != JOURNAL_FORMAT_VERSION:
        return _Inspection(status=JournalRecoveryStatus.UNSUPPORTED_VERSION, reasons=(f"SCHEMA_VERSION_UNSUPPORTED:{version}",),
                           schema_version=version)
    if connection.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
        return _Inspection(status=JournalRecoveryStatus.CORRUPT, reasons=("SQLITE_QUICK_CHECK_FAILED",), schema_version=version)
    if tuple(connection.execute("SELECT type, name, tbl_name, sql FROM sqlite_schema ORDER BY type, name")) != _EXPECTED_OBJECTS:
        return _Inspection(status=JournalRecoveryStatus.CORRUPT, reasons=("SCHEMA_OBJECTS_CHANGED",), schema_version=version)
    meta = connection.execute("SELECT entry_count, head_digest FROM journal_meta").fetchall()
    if len(meta) != 1 or meta[0][0] < 0:
        return _Inspection(status=JournalRecoveryStatus.CORRUPT, reasons=("META_INVALID",), schema_version=version)
    entry_count, head_digest = meta[0]
    rows = connection.execute(
        "SELECT seq, record_type, record_id, entry_kind, payload, prev_digest, digest FROM journal_entries ORDER BY seq"
    ).fetchall()
    return _verify(version, entry_count, head_digest, rows)


def _failure(exc: BaseException) -> _Inspection:
    """읽기 중 오류의 분류: SQLite가 파일 손상을 보고하면 CORRUPT, 그 밖에는 UNREADABLE."""
    name = getattr(exc, "sqlite_errorname", None)
    if isinstance(name, str) and (name.startswith("SQLITE_CORRUPT") or name == "SQLITE_NOTADB"):
        return _Inspection(status=JournalRecoveryStatus.CORRUPT, reasons=(f"DATABASE_FILE_CORRUPT:{name}",))
    return _Inspection(status=JournalRecoveryStatus.UNREADABLE, reasons=(f"READ_FAILED:{name or type(exc).__name__}",))


def _connect(path: Path, mode: str, factory: type[sqlite3.Connection]) -> sqlite3.Connection:
    # 트랜잭션은 직접 연다 (autocommit=True: sqlite3 모듈이 암묵적으로 BEGIN·COMMIT하지 않음). mode=rw는 파일을 새로 만들지 않는다.
    return sqlite3.connect(f"{path.absolute().as_uri()}?mode={mode}", uri=True, autocommit=True, factory=factory)


def _begin_and_inspect(connection: sqlite3.Connection, begin: str) -> _Inspection:
    try:
        connection.execute("PRAGMA synchronous = FULL")
        connection.execute(begin)
        return _inspect(connection)
    except sqlite3.Error as exc:
        return _failure(exc)


def _rollback(connection: sqlite3.Connection) -> bool:
    """열린 트랜잭션을 되돌리고 열려 있었는지 돌려준다. ROLLBACK이 실패해도 연결을 닫으면 SQLite가 되돌린다."""
    pending = connection.in_transaction
    if pending:
        try:
            connection.execute("ROLLBACK")
        except sqlite3.Error:
            pass
    return pending


def _append_entry(connection: sqlite3.Connection, seq: int, encoded: EncodedRecord, entry_kind: str, prev_digest: str) -> str:
    digest = _entry_digest(seq, encoded.record_type.value, encoded.record_id, entry_kind, encoded.payload, prev_digest)
    connection.execute(
        "INSERT INTO journal_entries (seq, record_type, record_id, entry_kind, payload, prev_digest, digest) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (seq, encoded.record_type.value, encoded.record_id, entry_kind, encoded.payload, prev_digest, digest),
    )
    return digest


def _write(connection: sqlite3.Connection, inspection: _Inspection, records: list[JournalRecord],
           encoded: list[EncodedRecord]) -> tuple[list[JournalAppendResult], int, str]:
    accepted = dict(inspection.accepted)
    conflict_seqs = dict(inspection.conflict_seqs)
    count, head = inspection.entry_count, inspection.head_digest
    results = []
    for record, item in zip(records, encoded, strict=True):
        key = (item.record_type, item.record_id)
        same = accepted.get(key)
        if same is not None and same.payload == item.payload:
            outcome, seq = JournalAppendOutcome.DUPLICATE, same.seq
        elif _conflicting(accepted, item.record_type, item.record_id, item.payload, record) is None:
            count += 1
            head = _append_entry(connection, count, item, _RECORD, head)
            accepted[key] = _Accepted(count, item.payload, record)
            outcome, seq = JournalAppendOutcome.APPENDED, count
        else:
            outcome, seq = JournalAppendOutcome.CONFLICT, conflict_seqs.get((*key, item.payload))
            if seq is None:
                count += 1
                head = _append_entry(connection, count, item, _CONFLICT, head)
                conflict_seqs[(*key, item.payload)] = seq = count
        results.append(JournalAppendResult(record_type=item.record_type, record_id=item.record_id, outcome=outcome, seq=seq))
    if count != inspection.entry_count:
        updated = connection.execute("UPDATE journal_meta SET entry_count = ?, head_digest = ? WHERE singleton = 1", (count, head))
        if updated.rowcount != 1:
            raise sqlite3.DatabaseError("the journal head was not updated.")
    return results, count, head


def create_order_journal(path: str | os.PathLike[str], *, connection_factory: type[sqlite3.Connection] = sqlite3.Connection) -> None:
    """새 주문 기록 Journal 파일을 만든다 (기록 없음, 형식 버전 1). COMMIT이 끝난 뒤에 돌아온다.

    입력: 아직 없는 파일 경로. `connection_factory`는 sqlite3 표준 `factory`이며 장애 주입 시험에 쓴다.
    예외조건 (JournalWriteError): 경로에 이미 무언가 있음 (기존 파일을 덮어쓰거나 초기화하지 않음), 디렉터리가 없거나 쓸 수 없음,
    생성 중 오류. 오류가 나면 빈 파일이 남을 수 있고, 그 파일은 복구에서 UNREADABLE이다 (이 함수는 파일을 지우지 않는다).
    """
    target = Path(path)
    if target.exists() or target.is_symlink():
        raise JournalWriteError(f"{str(target)!r} already exists; an existing file is never overwritten or reset.", may_be_persisted=False)
    try:
        connection = _connect(target, "rwc", connection_factory)
    except sqlite3.Error as exc:
        raise JournalWriteError(f"the journal could not be created: {exc}", may_be_persisted=False) from exc
    committing = False
    try:
        connection.execute("PRAGMA synchronous = FULL")
        connection.execute("BEGIN IMMEDIATE")
        if _scalar(connection, "SELECT count(*) FROM sqlite_schema") != 0:
            raise sqlite3.DatabaseError("the file already holds a database.")
        for statement in _SCHEMA:
            connection.execute(statement)
        connection.execute(f"PRAGMA application_id = {_APPLICATION_ID}")
        connection.execute(f"PRAGMA user_version = {JOURNAL_FORMAT_VERSION}")
        connection.execute("INSERT INTO journal_meta (singleton, entry_count, head_digest) VALUES (1, 0, ?)", (_GENESIS_DIGEST,))
        committing = True
        connection.execute("COMMIT")
    except Exception as exc:
        pending = _rollback(connection)
        raise JournalWriteError(f"the journal could not be created: {exc}", may_be_persisted=committing and not pending) from exc
    finally:
        connection.close()


def append_to_order_journal(
    path: str | os.PathLike[str],
    records: list[JournalRecord] | tuple[JournalRecord, ...],
    *,
    connection_factory: type[sqlite3.Connection] = sqlite3.Connection,
) -> JournalAppendReport:
    """기록 묶음을 하나의 트랜잭션으로 저장한다. 모두 저장되거나 하나도 저장되지 않는다.

    입력: 기존 Journal 경로, OrderEvent / OrderEvidence / TradingStateRecord 묶음 (받은 순서가 저장 순서다. 발생 시각으로 재정렬하지 않음).
    출력: 기록별 판정과 커밋 뒤의 기록 수·마지막 해시. COMMIT이 오류 없이 끝난 뒤에만 돌아온다.
    판정: 기록 키는 (기록 종류, ID)다. 같은 키에 같은 내용(직렬화 텍스트)이 있으면 DUPLICATE이고 저장소를 바꾸지 않는다. 다른 내용이면
    CONFLICT: 처음 기록을 그대로 두고 받은 기록을 충돌 항목으로 보관한다 (같은 충돌 기록이 다시 오면 다시 쓰지 않음). 같은 사건 ID의
    OrderEvent와 OrderEvidence는 같은 사건을 담아야 하며, 다르면 CONFLICT다. 묶음 안에서도 같은 규칙을 차례로 적용한다.
    예외조건: 빈 묶음은 ValueError. 지원하지 않는 값이나 정확히 직렬화할 수 없는 기록은 JournalEncodingError (아무것도 쓰지 않음).
    파일이 없으면 JournalWriteError (새로 만들지 않음). 기존 Journal을 정상(RECOVERED·CONFLICT)으로 확인하지 못하면
    JournalIntegrityError (쓰지 않음). 쓰는 중 오류는 ROLLBACK 뒤 JournalWriteError이며, COMMIT을 보낸 뒤의 오류는 저장 여부를 알 수
    없으므로 `may_be_persisted=True`다.
    """
    items = list(records)
    if not items:
        raise ValueError("there are no records to append.")
    encoded = [encode_record(record) for record in items]
    target = Path(path)
    if not target.exists():
        raise JournalWriteError(f"the journal {str(target)!r} does not exist; create it explicitly.", may_be_persisted=False)
    try:
        connection = _connect(target, "rw", connection_factory)
    except sqlite3.Error as exc:
        raise JournalWriteError(f"the journal could not be opened: {exc}", may_be_persisted=False) from exc
    committing = False
    try:
        inspection = _begin_and_inspect(connection, "BEGIN IMMEDIATE")
        if inspection.status not in _WRITABLE:
            raise JournalIntegrityError(inspection.status, inspection.reasons)
        results, count, head = _write(connection, inspection, items, encoded)
        committing = True
        connection.execute("COMMIT")
    except JournalIntegrityError:
        _rollback(connection)
        raise
    except Exception as exc:
        pending = _rollback(connection)
        raise JournalWriteError(f"the records were not confirmed as stored: {exc}", may_be_persisted=committing and not pending) from exc
    finally:
        connection.close()
    return JournalAppendReport(results=tuple(results), entry_count=count, head_digest=head)


def recover_order_journal(
    path: str | os.PathLike[str],
    *,
    connection_factory: type[sqlite3.Connection] = sqlite3.Connection,
) -> JournalRecovery:
    """Journal을 다시 읽어 저장된 기록을 복원하고 검사한다 (재시작 복구). 실패는 예외가 아니라 상태와 사유로 돌려준다.

    검사: 파일 머리의 응용 식별자와 schema version, SQLite quick_check, schema 객체, head(기록 수·마지막 해시), 항목 번호의 연속성, 항목별
    해시와 사슬, 기록 종류와 ID, 기록 내용(엄격한 역직렬화, 도메인 검증, 정규 형식), 같은 키의 중복 항목, 같은 사건의 OrderEvent와
    OrderEvidence의 일치, 충돌 항목의 근거.
    출력: RECOVERED이면 저장(도착) 순서대로 기록을 꺼낼 수 있다. 기록을 만들거나 고치거나 버리지 않는다 (거부될 증거, UNKNOWN 기록
    포함). 완전성·브로커 대조·위변조 방지는 확인하지 않는다 (`not_established`).
    파일: 없으면 만들지 않는다 (UNREADABLE). SQLite가 끝나지 않은 트랜잭션을 rollback journal로 되돌릴 수 있도록 쓰기 가능 모드로 열지만,
    이 함수는 기록을 쓰지 않는다.
    """
    target = Path(path)
    try:
        if not target.exists():
            inspection = _Inspection(status=JournalRecoveryStatus.UNREADABLE, reasons=("JOURNAL_FILE_NOT_FOUND",))
        else:
            connection = _connect(target, "rw", connection_factory)
            try:
                inspection = _begin_and_inspect(connection, "BEGIN")
                _rollback(connection)
            finally:
                connection.close()
    except (sqlite3.Error, OSError) as exc:
        inspection = _failure(exc)
    usable = inspection.status in _WRITABLE
    return JournalRecovery(
        status=inspection.status,
        reasons=inspection.reasons,
        schema_version=inspection.schema_version,
        entry_count=inspection.entry_count,
        head_digest=inspection.head_digest,
        conflicts=inspection.conflicts if usable else (),
        not_established=JOURNAL_RECOVERY_NOT_ESTABLISHED,
        _records=inspection.records if inspection.status is JournalRecoveryStatus.RECOVERED else (),
    )
