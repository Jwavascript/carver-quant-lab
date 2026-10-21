"""P0-03C Slice 4 주문 기록 Journal의 명시적 직렬화 (실험용 형식, 형식 버전 1).

기록 하나를 정규 JSON 텍스트 하나로 바꾸고 되돌린다. 순수 함수이며 I/O가 없다. 보관 위치·형식(ADR-0009 Q9-9, ADR-0011 Q11-10),
새 인코더의 수치 규칙(Q11-6), `content_hash` canonicalization(Q11-11)은 정하지 않았다. 이 형식은 그 결정을 대신하지 않는 Slice 4 한정
선택이다. ADR-0011 승인 원칙 4(새 시스템은 별도의 버전 있는 schema·인코더, FP-5·FP-16)를 따르고 V1 인코더를 쓰지 않는다. 제안 규칙
FP-8(클래스 경로가 아닌 기록 종류 이름), FP-10(UTC 고정 문자열 형식)은 이 형식 안에서만 실험적으로 쓴다.

규칙:
- 기록 종류는 ORDER_EVENT, ORDER_EVIDENCE, TRADING_STATE_RECORD이고 정확히 그 타입만 받는다 (하위 클래스 거부).
- 필드는 도메인 dataclass의 필드 이름 그대로이며 빠짐도 더함도 없다. 키는 정렬하고 공백을 넣지 않는다. 비ASCII 문자는 그대로 쓰고
  제어 문자는 JSON escape로 쓴다. UTF-8로 쓸 수 없는 문자(짝 없는 surrogate)는 거부한다.
- 식별자는 문자열, 수량은 JSON 정수(bool·실수·문자열 거부), 열거형은 값 문자열, 선택 필드의 없음은 null이다. 이 기록들에는 Decimal
  금액이 없고 실수는 어디에도 쓰지 않는다 (NaN·Infinity 거부).
- 시각은 UTC 순간을 `YYYY-MM-DDTHH:MM:SS.ffffffZ`(ASCII 숫자, 마이크로초 6자리)로 쓰고 다른 표기는 거부한다. 복원한 시각의 tzinfo는
  `timezone.utc`다 (같은 UTC 순간이며 시간대를 없애지 않음).
- 직렬화한 뒤 다시 읽은 기록이 원래 기록과 같아야 한다. 같지 않으면(정밀도 손실 등) 저장하지 않는다.
- 읽을 때는 도메인 생성자의 검증을 그대로 거치고, 다시 직렬화한 텍스트가 읽은 텍스트와 글자 단위로 같아야 한다 (정규 형식). 같은 키가
  두 번 나오면 거부한다. 고쳐 읽거나 기본값을 넣지 않는다.
"""

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

from carver_quant.lab.domain.order_events import OrderEvent, OrderEventKind
from carver_quant.lab.domain.order_evidence import OrderEvidence, OrderEvidenceKind
from carver_quant.lab.domain.orders import OrderRecord, OrderStatus, OrderStatusSource
from carver_quant.lab.domain.risk import TradingState
from carver_quant.lab.domain.trading_state import TradingStateRecord
from carver_quant.lab.domain.values import require_utc_instant

JOURNAL_FORMAT = "carver-lab-order-journal"  # 형식 이름 (가칭)
JOURNAL_FORMAT_VERSION = 1

JournalRecord = OrderEvent | OrderEvidence | TradingStateRecord


class JournalEncodingError(ValueError):
    """기록을 이 형식으로 정확히 직렬화하거나 역직렬화할 수 없을 때. 추측해서 저장하거나 복원하지 않는다."""


class JournalRecordType(Enum):
    ORDER_EVENT = "ORDER_EVENT"
    ORDER_EVIDENCE = "ORDER_EVIDENCE"
    TRADING_STATE_RECORD = "TRADING_STATE_RECORD"


@dataclass(frozen=True, kw_only=True)
class EncodedRecord:
    """직렬화한 기록: 기록 종류, 기록 키의 ID(사건 ID 또는 Trading State 기록 ID), 정규 JSON 텍스트."""

    record_type: JournalRecordType
    record_id: str
    payload: str


_RECORD_TYPES = {
    OrderEvent: JournalRecordType.ORDER_EVENT,
    OrderEvidence: JournalRecordType.ORDER_EVIDENCE,
    TradingStateRecord: JournalRecordType.TRADING_STATE_RECORD,
}
_INSTANT = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})\.([0-9]{6})Z")
# 필드 목록은 도메인 dataclass에서 끌어오지 않고 적어 둔다. 도메인에 필드가 늘면 직렬화가 조용히 바뀌지 않고 실패한다 (FP-16).
_ORDER_RECORD_FIELDS = frozenset({
    "account_id", "client_order_id", "broker_order_id", "contract_id", "quantity", "status", "filled_quantity", "cancelled_quantity",
    "replacement_quantity", "replacement_client_order_id", "status_source", "status_event_ref",
})
_ORDER_EVENT_FIELDS = frozenset({"event_id", "kind", "record", "occurred_at", "available_at"})
_ORDER_EVIDENCE_FIELDS = frozenset({"event", "evidence_kind", "requested_at"})
_TRADING_STATE_FIELDS = frozenset({"record_id", "account_id", "state", "effective_at", "data_available_at", "cause_code", "approver_ref"})


def _require_type(value: object, expected: type, what: str) -> None:
    if type(value) is not expected:
        raise JournalEncodingError(f"{what} must be exactly {expected.__name__}, not {type(value).__name__}.")


def _instant(value: datetime, name: str) -> str:
    require_utc_instant(value, name)
    return (f"{value.year:04d}-{value.month:02d}-{value.day:02d}T{value.hour:02d}:{value.minute:02d}:{value.second:02d}."
            f"{value.microsecond:06d}Z")


def _optional_instant(value: datetime | None, name: str) -> str | None:
    return None if value is None else _instant(value, name)


def _order_record_body(record: OrderRecord) -> dict:
    _require_type(record, OrderRecord, "an order record")
    return {
        "account_id": record.account_id,
        "client_order_id": record.client_order_id,
        "broker_order_id": record.broker_order_id,
        "contract_id": record.contract_id,
        "quantity": record.quantity,
        "status": record.status.value,
        "filled_quantity": record.filled_quantity,
        "cancelled_quantity": record.cancelled_quantity,
        "replacement_quantity": record.replacement_quantity,
        "replacement_client_order_id": record.replacement_client_order_id,
        "status_source": record.status_source.value,
        "status_event_ref": record.status_event_ref,
    }


def _order_event_body(event: OrderEvent) -> dict:
    _require_type(event, OrderEvent, "an order event")
    return {
        "event_id": event.event_id,
        "kind": event.kind.value,
        "record": _order_record_body(event.record),
        "occurred_at": _instant(event.occurred_at, "occurred_at"),
        "available_at": _instant(event.available_at, "available_at"),
    }


def _order_evidence_body(item: OrderEvidence) -> dict:
    _require_type(item, OrderEvidence, "order evidence")
    return {
        "event": _order_event_body(item.event),
        "evidence_kind": item.evidence_kind.value,
        "requested_at": _optional_instant(item.requested_at, "requested_at"),
    }


def _trading_state_body(record: TradingStateRecord) -> dict:
    _require_type(record, TradingStateRecord, "a trading state record")
    return {
        "record_id": record.record_id,
        "account_id": record.account_id,
        "state": record.state.value,
        "effective_at": _instant(record.effective_at, "effective_at"),
        "data_available_at": _instant(record.data_available_at, "data_available_at"),
        "cause_code": record.cause_code,
        "approver_ref": record.approver_ref,
    }


def _unique_keys(pairs: list[tuple[str, object]]) -> dict:
    body = {}
    for key, value in pairs:
        if key in body:
            raise JournalEncodingError(f"the payload repeats the field {key!r}.")
        body[key] = value
    return body


def _no_real_number(text: str) -> None:
    raise JournalEncodingError(f"the payload holds the number {text}; this format has no real numbers.")


def _fields(body: object, names: frozenset[str], what: str) -> dict:
    if type(body) is not dict or set(body) != names:
        raise JournalEncodingError(f"{what} must have exactly the fields {', '.join(sorted(names))}.")
    return body


def _text(value: object, name: str) -> str:
    if type(value) is not str:
        raise JournalEncodingError(f"{name} must be a JSON string.")
    return value


def _optional_text(value: object, name: str) -> str | None:
    return None if value is None else _text(value, name)


def _integer(value: object, name: str) -> int:
    if type(value) is not int:
        raise JournalEncodingError(f"{name} must be a JSON integer.")
    return value


def _optional_integer(value: object, name: str) -> int | None:
    return None if value is None else _integer(value, name)


def _member(enum_type: type[Enum], value: object, name: str) -> Enum:
    try:
        return enum_type(_text(value, name))
    except ValueError as exc:
        raise JournalEncodingError(f"{name} {value!r} is not a {enum_type.__name__} value.") from exc


def _read_instant(value: object, name: str) -> datetime:
    match = _INSTANT.fullmatch(_text(value, name))
    if match is None:
        raise JournalEncodingError(f"{name} must be a UTC instant written as YYYY-MM-DDTHH:MM:SS.ffffffZ.")
    try:
        return datetime(*(int(part) for part in match.groups()), tzinfo=timezone.utc)
    except ValueError as exc:
        raise JournalEncodingError(f"{name} is not a valid instant.") from exc


def _read_optional_instant(value: object, name: str) -> datetime | None:
    return None if value is None else _read_instant(value, name)


def _read_order_record(body: object) -> OrderRecord:
    fields = _fields(body, _ORDER_RECORD_FIELDS, "an order record")
    return OrderRecord(
        account_id=_text(fields["account_id"], "account_id"),
        client_order_id=_text(fields["client_order_id"], "client_order_id"),
        broker_order_id=_optional_text(fields["broker_order_id"], "broker_order_id"),
        contract_id=_text(fields["contract_id"], "contract_id"),
        quantity=_integer(fields["quantity"], "quantity"),
        status=_member(OrderStatus, fields["status"], "status"),
        filled_quantity=_integer(fields["filled_quantity"], "filled_quantity"),
        cancelled_quantity=_integer(fields["cancelled_quantity"], "cancelled_quantity"),
        replacement_quantity=_optional_integer(fields["replacement_quantity"], "replacement_quantity"),
        replacement_client_order_id=_optional_text(fields["replacement_client_order_id"], "replacement_client_order_id"),
        status_source=_member(OrderStatusSource, fields["status_source"], "status_source"),
        status_event_ref=_text(fields["status_event_ref"], "status_event_ref"),
    )


def _read_order_event(body: object) -> OrderEvent:
    fields = _fields(body, _ORDER_EVENT_FIELDS, "an order event")
    return OrderEvent(
        event_id=_text(fields["event_id"], "event_id"),
        kind=_member(OrderEventKind, fields["kind"], "kind"),
        record=_read_order_record(fields["record"]),
        occurred_at=_read_instant(fields["occurred_at"], "occurred_at"),
        available_at=_read_instant(fields["available_at"], "available_at"),
    )


def _read_order_evidence(body: object) -> OrderEvidence:
    fields = _fields(body, _ORDER_EVIDENCE_FIELDS, "order evidence")
    return OrderEvidence(
        event=_read_order_event(fields["event"]),
        evidence_kind=_member(OrderEvidenceKind, fields["evidence_kind"], "evidence_kind"),
        requested_at=_read_optional_instant(fields["requested_at"], "requested_at"),
    )


def _read_trading_state(body: object) -> TradingStateRecord:
    fields = _fields(body, _TRADING_STATE_FIELDS, "a trading state record")
    return TradingStateRecord(
        record_id=_text(fields["record_id"], "record_id"),
        account_id=_text(fields["account_id"], "account_id"),
        state=_member(TradingState, fields["state"], "state"),
        effective_at=_read_instant(fields["effective_at"], "effective_at"),
        data_available_at=_read_instant(fields["data_available_at"], "data_available_at"),
        cause_code=_text(fields["cause_code"], "cause_code"),
        approver_ref=_optional_text(fields["approver_ref"], "approver_ref"),
    )


_ENCODERS = {
    JournalRecordType.ORDER_EVENT: _order_event_body,
    JournalRecordType.ORDER_EVIDENCE: _order_evidence_body,
    JournalRecordType.TRADING_STATE_RECORD: _trading_state_body,
}
_DECODERS = {
    JournalRecordType.ORDER_EVENT: _read_order_event,
    JournalRecordType.ORDER_EVIDENCE: _read_order_evidence,
    JournalRecordType.TRADING_STATE_RECORD: _read_trading_state,
}


def _canonical(body: dict) -> str:
    return json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def record_key(record: JournalRecord) -> tuple[JournalRecordType, str]:
    """기록 키: (기록 종류, ID). OrderEvent·OrderEvidence는 사건 ID, TradingStateRecord는 기록 ID다.

    예외조건: 세 기록 타입이 아닌 값(하위 클래스 포함)은 JournalEncodingError.
    """
    record_type = _RECORD_TYPES.get(type(record))
    if record_type is None:
        raise JournalEncodingError(f"a journal stores OrderEvent, OrderEvidence and TradingStateRecord values, not {type(record).__name__}.")
    if record_type is JournalRecordType.ORDER_EVENT:
        return record_type, record.event_id
    if record_type is JournalRecordType.ORDER_EVIDENCE:
        return record_type, record.event.event_id
    return record_type, record.record_id


def encode_record(record: JournalRecord) -> EncodedRecord:
    """입력: OrderEvent / OrderEvidence / TradingStateRecord (정확히 그 타입). 출력: 기록 종류, ID, 정규 JSON 텍스트.

    예외조건 (JournalEncodingError): 다른 타입이나 하위 클래스(담긴 사건·주문 기록 포함), UTF-8로 쓸 수 없는 문자, 다시 읽은 기록이
    원래 기록과 다름 (예: 마이크로초보다 정밀한 시각).
    """
    record_type, record_id = record_key(record)
    payload = _canonical(_ENCODERS[record_type](record))
    try:
        payload.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise JournalEncodingError("the record holds characters that cannot be written as UTF-8.") from exc
    if decode_record(record_type, payload) != record:
        raise JournalEncodingError("the record does not survive serialization exactly, so it is not stored.")
    return EncodedRecord(record_type=record_type, record_id=record_id, payload=payload)


def decode_record(record_type: JournalRecordType, payload: str) -> JournalRecord:
    """입력: 기록 종류, 정규 JSON 텍스트. 출력: 도메인 기록 (도메인 생성자의 검증을 거친다).

    예외조건 (JournalEncodingError): 기록 종류가 아닌 값, 문자열이 아닌 내용, JSON이 아니거나 정규 형식이 아님, 필드 누락·추가, 같은 키
    두 번, 값의 타입·형식 위반(실수·NaN·bool 수량, 다른 시각 표기, 모르는 열거형 값), 도메인 규칙 위반.
    """
    if not isinstance(record_type, JournalRecordType):
        raise JournalEncodingError("record_type must be a JournalRecordType.")
    if type(payload) is not str:
        raise JournalEncodingError("the payload must be a str.")
    try:
        payload.encode("utf-8")
        body = json.loads(payload, object_pairs_hook=_unique_keys, parse_float=_no_real_number, parse_constant=_no_real_number)
        record = _DECODERS[record_type](body)
    except JournalEncodingError:
        raise
    except (ValueError, RecursionError) as exc:
        raise JournalEncodingError(f"the payload is not a valid {record_type.value} record: {exc}") from exc
    if _canonical(_ENCODERS[record_type](record)) != payload:
        raise JournalEncodingError("the payload is not in canonical form.")
    return record
