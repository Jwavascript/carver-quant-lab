"""P0-03C Slice 4: 추가 전용 주문 기록 Journal과 재시작 복구 (ADR-0009 §6.1·§6.4a, ADR-0012 BR-3·BR-11·승인 원칙 5·6·13·16,
ADR-0011 승인 원칙 4·FP-16, ADR-0010 PK-3·PK-5, ADR-0001 I-1).

저장소는 교체 가능한 실험용 로컬 구현(표준 라이브러리 sqlite3)이다. 저장 기술, 영속화 보장 수준(Q12-7), 보관 형식(Q9-9)을 정하지
않는다. 파일은 pytest 임시 경로에만 만든다. 연결 오류·프로세스 종료 주입은 전원 장애 시뮬레이션이 아니다.
복구한 기록을 기존 PIT·L3 함수에 그대로 넣어 저장 전 결과와 비교한다. 기대 노출(5,000 / 2,000 / 10,000 USD)은 저장소 밖 독립
산술(Fraction)로 먼저 확인했다. 가상 선물이며 한도·가격·승수·체결 장부는 테스트 입력이다 (Journal에 저장하지 않음).
"""

import dataclasses
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from carver_quant.lab.accounting.fill_ledger import FillLedger, apply_fill
from carver_quant.lab.accounting.l3_gate import CandidateRiskEffect, L3GateStatus, assess_l3_gate_as_of
from carver_quant.lab.accounting.order_snapshot import OrderLogCompleteness, assess_pretrade_risk_as_of
from carver_quant.lab.accounting.unknown_resolution import EvidenceDisposition
from carver_quant.lab.adapters.journal_codec import JournalEncodingError, JournalRecordType, decode_record, encode_record
from carver_quant.lab.adapters.order_journal import (
    JOURNAL_RECOVERY_NOT_ESTABLISHED,
    JournalAppendOutcome,
    JournalIntegrityError,
    JournalRecoveryError,
    JournalRecoveryStatus,
    JournalWriteError,
    append_to_order_journal,
    create_order_journal,
    recover_order_journal,
)
from carver_quant.lab.domain.order_events import OrderEvent, OrderEventKind
from carver_quant.lab.domain.order_evidence import OrderEvidence, OrderEvidenceKind
from carver_quant.lab.domain.orders import OrderRecord, OrderStatus, OrderStatusSource
from carver_quant.lab.domain.records import FillKey, FillOrigin, FillRecord, FuturesContractSpec, PositionBaseline, ValuationPrice
from carver_quant.lab.domain.risk import ContractMultiplier, ExposureLimit, TradingState
from carver_quant.lab.domain.trading_state import TradingStateRecord

UTC = timezone.utc
S = OrderStatus
K = OrderEvidenceKind
SRC = OrderStatusSource
D = EvidenceDisposition
G = L3GateStatus
A = JournalAppendOutcome
R = JournalRecoveryStatus
T = JournalRecordType
C1 = "FUT.ALPHA.C1"
C2 = "FUT.ALPHA.C2"
T0 = datetime(2026, 10, 21, 0, 0, tzinfo=UTC)
COMPLETE = OrderLogCompleteness.VERIFIED_COMPLETE
UNVERIFIED = OrderLogCompleteness.UNVERIFIED
EVENT_KIND = {SRC.SYSTEM: OrderEventKind.SYSTEM_RECORD, SRC.BROKER: OrderEventKind.BROKER_REPORT, SRC.SIMULATOR: OrderEventKind.SIMULATOR_REPORT}


def at(hhmm):
    hour, minute = hhmm.split(":")
    return datetime(2026, 10, 21, int(hour), int(minute), tzinfo=UTC)


def evidence(event_id, client_order_id, quantity, status, kind, occurred, available=None, *, source=None, filled=0, cancelled=0,
             broker_id="default", requested=None, replacement=None, contract_id=C1, account_id="A1"):
    source = source or (SRC.SYSTEM if kind is K.LOCAL_RECORD else SRC.BROKER)
    if broker_id == "default":
        broker_id = None if source is SRC.SYSTEM else "B-" + client_order_id
    record = OrderRecord(
        account_id=account_id,
        client_order_id=client_order_id,
        broker_order_id=broker_id,
        contract_id=contract_id,
        quantity=quantity,
        status=status,
        filled_quantity=filled,
        cancelled_quantity=cancelled,
        replacement_quantity=replacement,
        replacement_client_order_id=None if replacement is None else client_order_id + "R",
        status_source=source,
        status_event_ref=event_id,
    )
    event = OrderEvent(event_id=event_id, kind=EVENT_KIND[source], record=record, occurred_at=at(occurred),
                       available_at=at(available or occurred))
    return OrderEvidence(event=event, evidence_kind=kind, requested_at=at(requested) if requested else None)


def state_record(record_id, state, effective, available=None, *, approver="user:approval", cause="test:cause", account_id="A1"):
    return TradingStateRecord(record_id=record_id, account_id=account_id, state=state, effective_at=at(effective),
                              data_available_at=at(available or effective), cause_code=cause, approver_ref=approver)


NORMAL_AT_0900 = state_record("TS-1", TradingState.NORMAL, "09:00")
HALTED_AT_0955 = state_record("TS-2", TradingState.HALTED, "09:55", cause="UNKNOWN_ORDER", approver=None)


def contract(contract_id, lot_size=1):
    return FuturesContractSpec(contract_id=contract_id, instrument_id="FUT.ALPHA", currency="USD", multiplier="10", lot_size=lot_size)


def make_fill(fill_id, client_order_id, quantity, fill_at):
    return FillRecord(
        key=FillKey(account_id="A1", fill_source="BRK", fill_id=fill_id),
        client_order_id=client_order_id,
        broker_order_id="B-" + client_order_id,
        contract_id=C1,
        quantity=quantity,
        price="100",
        fill_at=at(fill_at),
        fee="1",
        fee_currency="USD",
        origin=FillOrigin.BROKER_REPORTED,
        execution_assumption_ref=None,
        venue=None,
        liquidity_flag=None,
    )


def ledger_with(*fills):
    ledger = FillLedger.empty(account_id="A1", contracts=(contract(C1), contract(C2)))
    for fill in fills:
        ledger = apply_fill(ledger, fill).ledger
    return ledger


def baseline():
    return PositionBaseline(account_id="A1", as_of=T0, quantities={C1: 0, C2: 0}, verification_ref="fixture:verified")


def risk_inputs(decision):
    available = decision - timedelta(minutes=30)
    return dict(
        reference_prices={
            contract_id: ValuationPrice(contract_id=contract_id, price="100", valuation_at=available, data_available_at=available,
                                        source_ref="fixture:price")
            for contract_id in (C1, C2)
        },
        multipliers={
            contract_id: ContractMultiplier(contract_id=contract_id, multiplier="10", currency="USD", data_available_at=T0,
                                            source_ref="fixture:spec")
            for contract_id in (C1, C2)
        },
        limits={contract_id: ExposureLimit(contract_id=contract_id, currency="USD", max_exposure="20000", source_ref="test:limit")
                for contract_id in (C1, C2)},
    )


def gate(items, decision, *, targets, fills=(), records=(NORMAL_AT_0900,), completeness=COMPLETE):
    return assess_l3_gate_as_of(
        baseline=baseline(),
        ledger=ledger_with(*fills),
        evidence=items,
        confirming_source=SRC.BROKER,
        completeness=completeness,
        completeness_ref="fixture:complete-log" if completeness is COMPLETE else None,
        targets=targets,
        decision_at=at(decision),
        trading_state=TradingState.NORMAL,
        trading_state_records=records,
        **risk_inputs(at(decision)),
    )


def slice_2_risk(events, decision):
    return assess_pretrade_risk_as_of(
        baseline=baseline(),
        ledger=ledger_with(),
        events=events,
        completeness=COMPLETE,
        completeness_ref="fixture:complete-log",
        targets={C1: 10, C2: 0},
        decision_at=at(decision),
        trading_state=TradingState.NORMAL,
        **risk_inputs(at(decision)),
    )


def unknown_c5():
    """09:50 매수 +5 제출 (PENDING_SUBMIT), 09:55 응답 timeout으로 UNKNOWN. 둘 다 시스템 기록이다."""
    return [
        evidence("E-1", "C-5", 5, S.PENDING_SUBMIT, K.LOCAL_RECORD, "09:50"),
        evidence("E-2", "C-5", 5, S.UNKNOWN, K.LOCAL_RECORD, "09:55"),
    ]


def assert_all_blocked(report, *reasons):
    for view in report.views:
        assert view.status is G.BLOCKED
        for reason in reasons:
            assert reason in view.blocking_reasons


def new_journal(directory, *records, name="orders.sqlite3"):
    path = Path(directory) / name
    create_order_journal(path)
    if records:
        append_to_order_journal(path, records)
    return path


def recovered(path):
    recovery = recover_order_journal(path)
    assert recovery.status is R.RECOVERED, recovery.reasons
    return recovery


def codes(result):
    return {reason.split(":")[0] for reason in result.reasons}


def file_digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def raw_sql(path, *statements):
    """저장소 함수를 거치지 않고 파일을 직접 바꾼다 (손상·변경 주입)."""
    connection = sqlite3.connect(path, autocommit=True)
    try:
        for statement in statements:
            sql, parameters = (statement, ()) if isinstance(statement, str) else statement
            connection.execute(sql, parameters)
    finally:
        connection.close()


def raw_rows(path, sql):
    connection = sqlite3.connect(path, autocommit=True)
    try:
        return connection.execute(sql).fetchall()
    finally:
        connection.close()


def faulty_connection(sql_prefix, *, nth=1, after=False):
    """장애 주입용 연결 (sqlite3 표준 `factory`). `sql_prefix`로 시작하는 n번째 SQL 실행 직전(after=False) 또는 직후(after=True)에
    연결 오류를 낸다."""

    class FaultyConnection(sqlite3.Connection):
        seen = 0

        def execute(self, sql, parameters=(), /):
            if not sql.startswith(sql_prefix):
                return super().execute(sql, parameters)
            type(self).seen += 1
            if type(self).seen != nth:
                return super().execute(sql, parameters)
            if after:
                super().execute(sql, parameters)
            raise sqlite3.OperationalError(f"injected fault {'after' if after else 'before'} {sql_prefix}")

    return FaultyConnection


def exiting_connection(when):
    """CASE 10 자식 프로세스용 연결: COMMIT 직전 또는 직후 프로세스를 정리 없이 끝낸다 (os._exit).
    page cache를 1쪽으로 줄여 커밋 전에 바뀐 쪽이 파일에 쓰이게 한다 (미완료 트랜잭션이 파일과 rollback journal에 남음)."""

    class ExitingConnection(sqlite3.Connection):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            super().execute("PRAGMA cache_size = 1")

        def execute(self, sql, parameters=(), /):
            if sql == "COMMIT" and when == "before":
                os._exit(17)
            cursor = super().execute(sql, parameters)
            if sql == "COMMIT" and when == "after":
                os._exit(17)
            return cursor

    return ExitingConnection


CHILD_MAIN = (
    "import importlib.util, sys\n"
    "spec = importlib.util.spec_from_file_location('order_journal_restart_case', sys.argv[1])\n"
    "module = importlib.util.module_from_spec(spec)\n"
    "spec.loader.exec_module(module)\n"
    "getattr(module, sys.argv[2])(*sys.argv[3:])\n"
)


def run_child(function_name, *arguments):
    """이 파일을 새 Python 프로세스에서 불러 함수 하나를 실행한다 (재시작 전의 프로세스)."""
    return subprocess.run([sys.executable, "-W", "error", "-c", CHILD_MAIN, __file__, function_name, *map(str, arguments)],
                          capture_output=True, text=True, timeout=300, check=False)


def sample_records():
    """직렬화 검사용 기록: 세 기록 종류와 네 증거 종류, 선택 필드의 None과 값, 정정 정보, 마이크로초와 timezone(timedelta(0))로 쓴
    UTC, 비ASCII·NUL 문자를 담은 식별자, 매도(음수)와 아주 큰 정수 수량."""
    zero = timezone(timedelta(0))
    instant = datetime(2026, 10, 21, 9, 55, 0, 123456, tzinfo=zero)
    replace_request = evidence("E-R", "C-9", 5, S.REPLACE_REQUESTED, K.LOCAL_RECORD, "09:52", replacement=8)
    precise = dataclasses.replace(
        evidence("E-\x00-P", "주문-1", -3, S.ACCEPTED, K.REQUEST_RESPONSE, "09:50", account_id="계좌-1").event,
        occurred_at=instant,
        available_at=instant + timedelta(microseconds=1),
    )
    halted = TradingStateRecord(record_id="TS-2", account_id="A1", state=TradingState.HALTED, effective_at=instant,
                                data_available_at=instant + timedelta(seconds=1, microseconds=530865), cause_code="UNKNOWN_ORDER",
                                approver_ref=None)
    return [
        replace_request.event,
        replace_request,
        evidence("E-Q", "C-9", 5, S.ACCEPTED, K.STATUS_QUERY_RESPONSE, "09:57", "09:58", requested="09:56"),
        evidence("E-F", "C-9", 5, S.PARTIALLY_FILLED, K.FILL_NOTIFICATION, "09:59", filled=2),
        evidence("E-C", "C-9", 5, S.CANCELLED, K.REQUEST_RESPONSE, "10:01", source=SRC.SIMULATOR, filled=2, cancelled=3),
        precise,
        evidence("E-BIG", "C-BIG", 10**30, S.PENDING_SUBMIT, K.LOCAL_RECORD, "09:50").event,
        halted,
        NORMAL_AT_0900,
    ]


def test_codec_and_journal_round_trip_every_record_type_exactly(tmp_path):
    """입력: OrderEvent, OrderEvidence(로컬 기록, 요청 응답, 상태 조회 결과, 체결 통보), TradingStateRecord (sample_records).
    출력: 직렬화 바이트를 역직렬화한 기록이 원래 기록과 같다. 같은 기록은 늘 같은 바이트다 (키 정렬, 고정 시각 형식
    `YYYY-MM-DDTHH:MM:SS.ffffffZ`, 수량은 JSON 정수, 비ASCII는 그대로, 제어 문자는 escape). 시각은 UTC 순간과 마이크로초 그대로다.
    기록 키는 OrderEvent·OrderEvidence가 사건 ID, TradingStateRecord가 기록 ID다. Journal에 저장하고 복구해도 종류별로 저장 순서와
    값이 같다."""
    records = sample_records()
    for record in records:
        encoded = encode_record(record)
        assert encoded == encode_record(record)
        restored = decode_record(encoded.record_type, encoded.payload)
        assert restored == record and type(restored) is type(record)
    assert [(encoded.record_type, encoded.record_id) for encoded in map(encode_record, (records[0], records[1], records[-1]))] == [
        (T.ORDER_EVENT, "E-R"), (T.ORDER_EVIDENCE, "E-R"), (T.TRADING_STATE_RECORD, "TS-1")]
    halted = encode_record(records[-2]).payload
    assert '"effective_at":"2026-10-21T09:55:00.123456Z"' in halted and '"approver_ref":null' in halted
    restored = decode_record(T.TRADING_STATE_RECORD, halted)
    assert (restored.effective_at.utcoffset(), restored.effective_at.microsecond, restored.data_available_at.microsecond) == (
        timedelta(0), 123456, 654321)
    precise = encode_record(records[5]).payload
    assert '"account_id":"계좌-1"' in precise and '"event_id":"E-\\u0000-P"' in precise and '"quantity":-3' in precise
    assert '"quantity":1000000000000000000000000000000' in encode_record(records[6]).payload

    recovery = recovered(new_journal(tmp_path, *records))
    assert recovery.order_events() == tuple(record for record in records if type(record) is OrderEvent)
    assert recovery.order_evidence() == tuple(record for record in records if type(record) is OrderEvidence)
    assert recovery.trading_state_records() == tuple(record for record in records if type(record) is TradingStateRecord)


class SubEvent(OrderEvent):
    pass


class SubRecord(OrderRecord):
    pass


class NanoInstant(datetime):
    """마이크로초보다 정밀한 값을 가진 시각 (예: 나노초 단위 시각 타입). 마이크로초까지만 같으면 같다고 보지 않는다."""

    def __eq__(self, other):
        return isinstance(other, NanoInstant) and datetime.__eq__(self, other)

    __hash__ = datetime.__hash__


def test_codec_refuses_values_it_cannot_store_exactly():
    """입력: (a) 지원하지 않는 값 (dict, 체결 기록, 문자열, None), (b) OrderEvent 하위 클래스, (c) OrderRecord 하위 클래스를 담은 사건,
    (d) UTF-8로 쓸 수 없는 문자(짝 없는 surrogate)를 담은 식별자, (e) 마이크로초보다 정밀한 시각.
    출력: 모두 JournalEncodingError. 문자열로 바꾸거나 정밀도를 잘라 저장하지 않는다."""
    event = unknown_c5()[1].event
    nano = NanoInstant(2026, 10, 21, 9, 55, tzinfo=UTC)
    bad = [
        {"event_id": "E-1"},
        make_fill("X-1", "C-5", 1, "09:57"),
        "E-1",
        None,
        SubEvent(event_id="E-2", kind=event.kind, record=event.record, occurred_at=event.occurred_at, available_at=event.available_at),
        dataclasses.replace(event, record=SubRecord(**{field.name: getattr(event.record, field.name)
                                                      for field in dataclasses.fields(OrderRecord)})),
        dataclasses.replace(NORMAL_AT_0900, account_id="A\ud800"),
        dataclasses.replace(event, occurred_at=nano, available_at=nano),
    ]
    for value in bad:
        with pytest.raises(JournalEncodingError):
            encode_record(value)


def test_codec_rejects_payloads_that_are_not_exactly_canonical():
    """입력: 정상 직렬화 바이트를 바꾼 값: 필드 누락·추가, 수량이 실수(5.0)·bool·문자열·NaN, 시간대 없는 시각, `+00:00` 표기, 마이크로초
    없음, 전각 숫자, 공백이 있는 JSON, 키 순서가 다른 JSON, 같은 키 두 번, 모르는 상태 값, 도메인 규칙 위반(이용 가능 시각이 발생
    시각보다 앞섬), JSON이 아닌 문자열. 그리고 다른 기록 종류로 읽기, 기록 종류가 아닌 값으로 읽기.
    출력: 모두 JournalEncodingError. 고쳐 읽거나 기본값을 넣지 않는다."""
    payload = encode_record(unknown_c5()[1]).payload
    assert decode_record(T.ORDER_EVIDENCE, payload) == unknown_c5()[1]
    changed = [
        payload.replace(',"requested_at":null', ""),
        payload[:-1] + ',"extra":1}',
        payload.replace('"quantity":5', '"quantity":5.0'),
        payload.replace('"quantity":5', '"quantity":true'),
        payload.replace('"quantity":5', '"quantity":"5"'),
        payload.replace('"quantity":5', '"quantity":NaN'),
        payload.replace("T09:55:00.000000Z", "T09:55:00.000000"),
        payload.replace("T09:55:00.000000Z", "T09:55:00.000000+00:00"),
        payload.replace("T09:55:00.000000Z", "T09:55:00Z"),
        payload.replace("2026-10-21T09:55", "２０２６-10-21T09:55"),
        payload.replace(",", ", "),
        json.dumps(dict(reversed(list(json.loads(payload).items()))), ensure_ascii=False, separators=(",", ":")),
        payload[:-1] + ',"evidence_kind":"LOCAL_RECORD"}',
        payload.replace('"status":"UNKNOWN"', '"status":"LOST"'),
        payload.replace('"available_at":"2026-10-21T09:55:00.000000Z"', '"available_at":"2026-10-21T09:54:00.000000Z"'),
        "not json",
    ]
    for value in changed:
        assert value != payload
        with pytest.raises(JournalEncodingError):
            decode_record(T.ORDER_EVIDENCE, value)
    for record_type in (T.ORDER_EVENT, T.TRADING_STATE_RECORD, "ORDER_EVIDENCE"):
        with pytest.raises(JournalEncodingError):
            decode_record(record_type, payload)


def test_journal_files_are_created_explicitly_and_failures_are_reported(tmp_path):
    """입력: (a) 같은 경로에 Journal을 두 번 만듦, (b) 없는 디렉터리에 만듦, (c) 없는 파일에 저장, (d) 없는 파일을 복구, (e) 읽는 도중
    연결 오류 (장애 주입), (f) 빈 묶음 저장, (g) 지원하지 않는 값이 섞인 묶음 저장.
    출력: (a)(b)(c) JournalWriteError이며 새 파일을 만들거나 기존 파일을 바꾸지 않는다. (d) UNREADABLE(JOURNAL_FILE_NOT_FOUND):
    빈 기록으로 정상 복구하지 않는다. (e) UNREADABLE(READ_FAILED). 정상 복구가 아니면 기록을 꺼낼 때 JournalRecoveryError.
    (f) ValueError, (g) JournalEncodingError이며 묶음의 어느 기록도 저장하지 않는다."""
    path = new_journal(tmp_path, *unknown_c5())
    held = file_digest(path)
    with pytest.raises(JournalWriteError):
        create_order_journal(path)
    with pytest.raises(JournalWriteError):
        create_order_journal(tmp_path / "missing" / "orders.sqlite3")
    assert not (tmp_path / "missing").exists()
    other = tmp_path / "other.sqlite3"
    with pytest.raises(JournalWriteError) as raised:
        append_to_order_journal(other, unknown_c5())
    assert raised.value.may_be_persisted is False and not other.exists()

    missing = recover_order_journal(other)
    assert (missing.status, missing.reasons, missing.entry_count) == (R.UNREADABLE, ("JOURNAL_FILE_NOT_FOUND",), None)
    assert not other.exists()
    failed_read = recover_order_journal(path, connection_factory=faulty_connection("SELECT"))
    assert (failed_read.status, codes(failed_read)) == (R.UNREADABLE, {"READ_FAILED"})
    for result in (missing, failed_read):
        for accessor in (result.order_events, result.order_evidence, result.trading_state_records):
            with pytest.raises(JournalRecoveryError):
                accessor()

    with pytest.raises(ValueError):
        append_to_order_journal(path, [])
    for value in ({"event_id": "E-3"}, make_fill("X-1", "C-5", 1, "09:57"), "E-3", None):
        with pytest.raises(JournalEncodingError):
            append_to_order_journal(path, [HALTED_AT_0955, value])
    assert file_digest(path) == held
    assert recovered(path).order_evidence() == tuple(unknown_c5())


def test_paths_with_uri_characters_open_the_named_file(tmp_path):
    """입력: 이름에 공백·`?`·`#`·`%`가 들어간 경로에 Journal을 만들고 저장한 뒤 복구한다 (sqlite3 URI로 연다).
    출력: 그 이름의 파일 하나만 생기고 (URI 해석 때문에 다른 파일을 열거나 다른 모드로 열지 않음) 저장한 기록이 복구된다."""
    path = new_journal(tmp_path, *unknown_c5(), name="a ?mode=ro#%20.sqlite3")

    assert [item.name for item in tmp_path.iterdir()] == ["a ?mode=ro#%20.sqlite3"]
    assert recovered(path).order_evidence() == tuple(unknown_c5())


def test_case_1_unknown_order_and_its_block_survive_a_restart(tmp_path):
    """CASE 1. 입력: 매수 +5 제출(09:50, PENDING_SUBMIT)과 응답 timeout(09:55, UNKNOWN) 로컬 증거, 같은 사건의 OrderEvent(Slice 2
    경로), 09:00 NORMAL 기록을 저장한 뒤 새로 복구. 판단 10:00, 목표 C1 +10.
    출력: RECOVERED. 복구한 증거·사건·Trading State 기록은 저장한 값과 순서까지 같다. UNKNOWN +5가 남아 최악 경우 롱 5, 노출 5,000 USD.
    L3 보고서 전체가 저장 전과 같고 모든 월물 BLOCKED(UNKNOWN_ORDER_PRESENT). Slice 2 위험 보고서도 저장 전과 같다."""
    items = unknown_c5()
    events = [item.event for item in items]
    path = new_journal(tmp_path, *items, *events, NORMAL_AT_0900)

    recovery = recovered(path)

    assert (recovery.order_evidence(), recovery.order_events(), recovery.trading_state_records()) == (
        tuple(items), tuple(events), (NORMAL_AT_0900,))
    after = gate(list(recovery.order_evidence()), "10:00", targets={C1: 10, C2: 0}, records=recovery.trading_state_records())
    assert after == gate(items, "10:00", targets={C1: 10, C2: 0})
    record = after.evidence.snapshot.records()[0]
    assert (record.client_order_id, record.status, record.quantity, record.filled_quantity) == ("C-5", S.UNKNOWN, 5, 0)
    view = after.risk.risk.view(C1)
    assert (view.worst_case.worst_long_before, view.exposure_before) == (5, Decimal("5000"))
    assert_all_blocked(after, "UNKNOWN_ORDER_PRESENT")
    assert slice_2_risk(list(recovery.order_events()), "10:00") == slice_2_risk(events, "10:00")


def test_case_2_late_status_query_gives_the_same_point_in_time_results_after_restart(tmp_path):
    """CASE 2. 입력: UNKNOWN +5 (C-5, 09:55). 도착 순서대로 저장: 로컬 기록 두 건, 다른 주문 C-7(C2, +2)의 제출 기록(10:03)과 접수 응답
    (10:04 관측, 10:05 이용 가능), 그 뒤 늦게 도착한 C-5 상태 조회 결과 ACCEPTED (09:56 요청, 09:57 관측, 10:10 이용 가능).
    출력: 복구한 순서는 저장(도착) 순서다. 발생 시각으로 재정렬하지 않는다. 판단 10:00·10:08: 조회 결과는 아직 이용 가능하지 않아
    C-5는 UNKNOWN. 판단 10:15: ACCEPTED로 해소, C1 최악 경우 롱 5 그대로 (AT-0012-1). C2 최악 경우 롱 0 / 2 / 2. 세 판단의 L3
    보고서가 저장 전과 같다."""
    items = unknown_c5() + [
        evidence("E-7", "C-7", 2, S.PENDING_SUBMIT, K.LOCAL_RECORD, "10:03", contract_id=C2),
        evidence("E-8", "C-7", 2, S.ACCEPTED, K.REQUEST_RESPONSE, "10:04", "10:05", contract_id=C2),
        evidence("E-3", "C-5", 5, S.ACCEPTED, K.STATUS_QUERY_RESPONSE, "09:57", "10:10", requested="09:56"),
    ]
    recovery = recovered(new_journal(tmp_path, *items, NORMAL_AT_0900))

    assert [item.event.event_id for item in recovery.order_evidence()] == ["E-1", "E-2", "E-7", "E-8", "E-3"]
    for decision, c5_status, c2_worst in (("10:00", S.UNKNOWN, 0), ("10:08", S.UNKNOWN, 2), ("10:15", S.ACCEPTED, 2)):
        after = gate(list(recovery.order_evidence()), decision, targets={C1: 10, C2: 0}, records=recovery.trading_state_records())
        assert after == gate(items, decision, targets={C1: 10, C2: 0})
        records = {record.client_order_id: record for record in after.evidence.snapshot.records()}
        assert records["C-5"].status is c5_status
        assert after.risk.risk.view(C1).worst_case.worst_long_before == 5
        assert after.risk.risk.view(C2).worst_case.worst_long_before == c2_worst
    assert after.risk.risk.view(C2).exposure_before == Decimal("2000")


def test_case_3_redelivered_records_are_stored_once(tmp_path):
    """CASE 3. 입력: 증거 두 건, 같은 사건의 OrderEvent 두 건(다른 기록 종류), NORMAL 기록을 저장하고 첫 묶음 안에서 E-1이 한 번 더 온다.
    그 뒤 같은 기록들을 다시 보낸다 (재전달).
    출력: 처음 온 기록은 APPENDED (항목 1~5), 다시 온 기록은 DUPLICATE이고 처음 항목 번호를 가리킨다. 재전달 뒤 기록 수·head가 같고
    파일 바이트가 바뀌지 않는다 (기존 기록을 바꾸지 않음). 복구한 기록은 한 번씩만 있고 L3 보고서는 한 번 저장했을 때와 같다."""
    items = unknown_c5()
    events = [item.event for item in items]
    path = new_journal(tmp_path)

    first = append_to_order_journal(path, [items[0], items[1], items[0], *events, NORMAL_AT_0900])
    assert [(result.outcome, result.seq) for result in first.results] == [
        (A.APPENDED, 1), (A.APPENDED, 2), (A.DUPLICATE, 1), (A.APPENDED, 3), (A.APPENDED, 4), (A.APPENDED, 5)]
    held = file_digest(path)
    again = append_to_order_journal(path, [items[1], NORMAL_AT_0900, items[1], events[0], items[0]])

    assert [(result.outcome, result.seq) for result in again.results] == [
        (A.DUPLICATE, 2), (A.DUPLICATE, 5), (A.DUPLICATE, 2), (A.DUPLICATE, 3), (A.DUPLICATE, 1)]
    assert (again.entry_count, again.head_digest) == (first.entry_count, first.head_digest) == (5, first.head_digest)
    assert file_digest(path) == held
    recovery = recovered(path)
    assert (recovery.entry_count, recovery.order_evidence(), recovery.order_events(), recovery.trading_state_records()) == (
        5, tuple(items), tuple(events), (NORMAL_AT_0900,))
    after = gate(list(recovery.order_evidence()), "10:00", targets={C1: 10, C2: 0}, records=recovery.trading_state_records())
    assert after == gate(items, "10:00", targets={C1: 10, C2: 0})


def conflict_inputs(kind):
    """CASE 4 입력: (기록 종류, ID, 먼저 저장한 기록, 유지되어야 할 기록, 같은 ID로 다시 온 다른 내용)."""
    original = unknown_c5()[1]
    shifted = dataclasses.replace(original, event=dataclasses.replace(original.event, available_at=at("09:56")))
    if kind == "evidence":
        return T.ORDER_EVIDENCE, "E-2", [unknown_c5()[0], original], original, shifted
    if kind == "event_and_evidence":
        return T.ORDER_EVIDENCE, "E-2", [original.event], original.event, shifted
    released = dataclasses.replace(HALTED_AT_0955, state=TradingState.NORMAL, approver_ref="user:approval")
    return T.TRADING_STATE_RECORD, "TS-2", [HALTED_AT_0955], HALTED_AT_0955, released


@pytest.mark.parametrize("kind", ["evidence", "event_and_evidence", "trading_state"])
@pytest.mark.parametrize("delivery", ["later_batch", "same_batch"])
def test_case_4_same_id_with_other_content_is_kept_as_a_conflict(tmp_path, kind, delivery):
    """CASE 4. 입력: (a) UNKNOWN 증거 E-2를 저장한 뒤 같은 사건 ID로 이용 가능 시각이 다른 증거, (b) OrderEvent E-2를 저장한 뒤 내용이
    다른 E-2를 담은 OrderEvidence, (c) HALTED 기록 TS-2를 저장한 뒤 같은 기록 ID의 NORMAL 기록 (승인자 있음). 다른 내용의 기록은
    다음 묶음으로 오거나, 먼저 기록과 같은 묶음 안에서 온다 (묶음 안에서도 차례로 판정. 검토 MEDIUM 회귀).
    출력: CONFLICT (DUPLICATE가 아님). 처음 기록은 그대로이고 받은 기록은 반영하지 않은 채 충돌 항목으로 함께 보관한다 (ADR-0009
    §6.4a). 복구 상태는 CONFLICT이고 사유가 있으며, 정상 기록을 꺼내면 JournalRecoveryError다 (어느 쪽이 맞는지 고르지 않고 정상
    상태를 만들지 않음). 같은 충돌 기록이 다시 와도 CONFLICT, 처음 기록이 다시 오면 DUPLICATE이며 파일은 바뀌지 않는다."""
    record_type, record_id, stored, kept, arrived = conflict_inputs(kind)
    path = new_journal(tmp_path, *(stored if delivery == "later_batch" else ()))
    kept_seq, arrived_seq = len(stored), len(stored) + 1

    *earlier, result = append_to_order_journal(path, [*(stored if delivery == "same_batch" else ()), arrived]).results

    assert [earlier_result.outcome for earlier_result in earlier] == [A.APPENDED] * len(earlier)
    assert (result.record_type, result.record_id, result.outcome, result.seq) == (record_type, record_id, A.CONFLICT, arrived_seq)
    recovery = recover_order_journal(path)
    assert (recovery.status, recovery.reasons, recovery.entry_count) == (R.CONFLICT, (f"RECORD_CONFLICT:{arrived_seq}",), arrived_seq)
    (conflict,) = recovery.conflicts
    assert (conflict.record_type, conflict.record_id, conflict.kept_seq, conflict.kept, conflict.arrived_seq, conflict.arrived) == (
        record_type, record_id, kept_seq, kept, arrived_seq, arrived)
    for accessor in (recovery.order_events, recovery.order_evidence, recovery.trading_state_records):
        with pytest.raises(JournalRecoveryError):
            accessor()
    held = file_digest(path)
    repeat = append_to_order_journal(path, [arrived, kept])
    assert [(result.outcome, result.seq) for result in repeat.results] == [(A.CONFLICT, arrived_seq), (A.DUPLICATE, kept_seq)]
    assert repeat.entry_count == arrived_seq and file_digest(path) == held


def test_case_5_failure_inside_a_batch_stores_none_of_it(tmp_path):
    """CASE 5. 입력: 로컬 증거 두 건이 있는 Journal에 세 건 묶음(상태 조회 결과, 체결 통보, HALTED 기록)을 저장하다가 두 번째 항목
    INSERT에서 연결 오류가 난다 (장애 주입).
    출력: JournalWriteError (may_be_persisted=False), 성공 보고 없음. 파일 바이트가 그대로이고 복구하면 묶음 전 두 건만 있다 (부분
    저장 없음). 같은 묶음을 다시 저장하면 세 건 모두 APPENDED (항목 3~5)."""
    path = new_journal(tmp_path, *unknown_c5())
    held = file_digest(path)
    batch = [
        evidence("E-3", "C-5", 5, S.ACCEPTED, K.STATUS_QUERY_RESPONSE, "09:57", requested="09:56"),
        evidence("E-4", "C-5", 5, S.PARTIALLY_FILLED, K.FILL_NOTIFICATION, "09:58", filled=2),
        HALTED_AT_0955,
    ]

    with pytest.raises(JournalWriteError) as raised:
        append_to_order_journal(path, batch, connection_factory=faulty_connection("INSERT INTO journal_entries", nth=2))

    assert raised.value.may_be_persisted is False
    assert file_digest(path) == held
    recovery = recovered(path)
    assert (recovery.entry_count, recovery.order_evidence(), recovery.trading_state_records()) == (2, tuple(unknown_c5()), ())
    retry = append_to_order_journal(path, batch)
    assert [(result.outcome, result.seq) for result in retry.results] == [(A.APPENDED, 3), (A.APPENDED, 4), (A.APPENDED, 5)]
    assert recovered(path).order_evidence() == tuple(unknown_c5() + batch[:2])


def swap_rows(path):
    """항목 1과 2의 내용(기록 종류, ID, 내용, 해시)을 맞바꾼다. 기록 수는 그대로다."""
    first, second = raw_rows(path, "SELECT record_type, record_id, entry_kind, payload, prev_digest, digest FROM journal_entries "
                                   "WHERE seq IN (1, 2) ORDER BY seq")
    update = "UPDATE journal_entries SET record_type = ?, record_id = ?, entry_kind = ?, payload = ?, prev_digest = ?, digest = ? WHERE seq = ?"
    raw_sql(path, "UPDATE journal_entries SET record_id = 'swap' WHERE seq = 1", (update, (*first, 2)), (update, (*second, 1)))


def add_row(path):
    """항목 4를 베껴 ID만 바꾼 항목 5를 더한다 (head는 그대로)."""
    raw_sql(path, "INSERT INTO journal_entries SELECT 5, record_type, 'TS-3', entry_kind, payload, digest, digest FROM journal_entries "
                  "WHERE seq = 4")


def overwrite_file(path):
    path.write_bytes(b"\x00not an order journal" * 64)


def store_payload_as_blob(path):
    """STRICT를 뺀 schema 문장으로 잠시 바꿔 항목 2의 내용을 같은 바이트의 BLOB으로 쓰고, 원래 schema 문장으로 되돌린다."""
    ((strict,),) = raw_rows(path, "SELECT sql FROM sqlite_schema WHERE name = 'journal_entries'")
    loose = strict.removesuffix(" STRICT")
    raw_sql(path, "PRAGMA writable_schema = ON", ("UPDATE sqlite_schema SET sql = ? WHERE name = 'journal_entries'", (loose,)))
    raw_sql(path, "UPDATE journal_entries SET payload = CAST(payload AS BLOB) WHERE seq = 2")
    raw_sql(path, "PRAGMA writable_schema = ON", ("UPDATE sqlite_schema SET sql = ? WHERE name = 'journal_entries'", (strict,)))


TAMPERING = {
    "payload_changed": (lambda path: raw_sql(path, "UPDATE journal_entries SET payload = replace(payload, '\"quantity\":5', "
                                                   "'\"quantity\":4') WHERE seq = 2"), R.CORRUPT, {"ENTRY_DIGEST_MISMATCH"}),
    "record_id_changed": (lambda path: raw_sql(path, "UPDATE journal_entries SET record_id = 'E-9' WHERE seq = 2"), R.CORRUPT,
                          {"ENTRY_DIGEST_MISMATCH", "RECORD_ID_MISMATCH"}),
    "rows_reordered": (swap_rows, R.CORRUPT, {"ENTRY_DIGEST_MISMATCH", "ENTRY_CHAIN_BROKEN"}),
    "unknown_record_deleted": (lambda path: raw_sql(path, "DELETE FROM journal_entries WHERE seq = 2"), R.INCOMPLETE, {"ENTRY_MISSING"}),
    "last_record_deleted": (lambda path: raw_sql(path, "DELETE FROM journal_entries WHERE seq = 4"), R.INCOMPLETE, {"ENTRY_MISSING"}),
    "count_raised": (lambda path: raw_sql(path, "UPDATE journal_meta SET entry_count = 5"), R.INCOMPLETE, {"ENTRY_MISSING"}),
    "row_added": (add_row, R.CORRUPT, {"ENTRY_BEYOND_HEAD"}),
    "head_changed": (lambda path: raw_sql(path, f"UPDATE journal_meta SET head_digest = '{'0' * 64}'"), R.CORRUPT,
                     {"HEAD_DIGEST_MISMATCH"}),
    "trigger_added": (lambda path: raw_sql(path, "CREATE TRIGGER quiet AFTER INSERT ON journal_entries BEGIN SELECT 1; END"),
                      R.CORRUPT, {"SCHEMA_OBJECTS_CHANGED"}),
    "file_overwritten": (overwrite_file, R.CORRUPT, {"DATABASE_FILE_CORRUPT"}),
    "all_deleted_count_zeroed": (lambda path: raw_sql(path, "DELETE FROM journal_entries", "UPDATE journal_meta SET entry_count = 0"),
                                 R.CORRUPT, {"HEAD_DIGEST_MISMATCH"}),
    "count_negative": (lambda path: raw_sql(path, "UPDATE journal_meta SET entry_count = -1"), R.CORRUPT, {"META_INVALID"}),
    "payload_stored_as_blob": (store_payload_as_blob, R.CORRUPT, {"SQLITE_QUICK_CHECK_FAILED"}),
}


@pytest.mark.parametrize("case", list(TAMPERING))
def test_case_6_changed_or_missing_entries_are_detected(tmp_path, case):
    """CASE 6. 입력: 증거 E-1(PENDING_SUBMIT), E-2(UNKNOWN), NORMAL, HALTED 네 항목을 저장한 Journal을 저장소 밖에서 바꾼다: 내용 변경
    (수량 5 → 4, 기록 수 그대로), ID 변경, 두 항목의 순서 교환(기록 수 그대로), UNKNOWN 항목 삭제, 마지막 항목 삭제, head의 기록 수
    증가, 항목 추가, head 해시 변경, schema 객체(trigger) 추가, 파일 전체를 다른 바이트로 덮어씀. 검토 MEDIUM 회귀: 모든 항목 삭제와
    head 기록 수 0 (head 해시는 그대로), 음수 기록 수, 내용 열의 타입 변경 (TEXT → 같은 바이트의 BLOB, SQLite 자체 검사만 잡음).
    출력: 내용·순서·구조가 바뀌면 CORRUPT, 항목이 빠지면 INCOMPLETE이고 사유 코드가 있다. 기록 수가 같아도 내용이 같다고 보지 않는다.
    기록을 꺼내면 JournalRecoveryError (UNKNOWN 기록이 빠진 상태로 정상 복구하지 않음). 새 기록 저장은 JournalIntegrityError이며
    파일을 바꾸지 않는다 (손상된 기록 위에 쌓지 않음)."""
    tamper, status, expected = TAMPERING[case]
    path = new_journal(tmp_path, *unknown_c5(), NORMAL_AT_0900, HALTED_AT_0955)
    tamper(path)
    held = file_digest(path)

    recovery = recover_order_journal(path)

    assert (recovery.status, codes(recovery)) == (status, expected)
    for accessor in (recovery.order_events, recovery.order_evidence, recovery.trading_state_records):
        with pytest.raises(JournalRecoveryError):
            accessor()
    with pytest.raises(JournalIntegrityError) as raised:
        append_to_order_journal(path, [evidence("E-3", "C-5", 5, S.ACCEPTED, K.STATUS_QUERY_RESPONSE, "09:57", requested="09:56")])
    assert (raised.value.status, codes(raised.value), raised.value.may_be_persisted) == (status, expected, False)
    assert file_digest(path) == held


def entry_digest(seq, record_type, record_id, entry_kind, payload, prev_digest):
    """항목 해시의 독립 계산 (형식 버전 1의 설명대로): 형식 이름·버전, 항목 번호, 기록 종류, ID, 항목 종류, 내용, 앞 항목 해시를 담은
    JSON 배열의 SHA-256."""
    material = json.dumps(["carver-lab-order-journal/1/entry", seq, record_type, record_id, entry_kind, payload, prev_digest],
                          ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def rechain(path, seq, entry_kind):
    """항목 하나의 항목 종류를 바꾸고 해시 사슬과 head 해시를 다시 계산해 맞춘다 (해시만으로는 검출되지 않는 변경)."""
    rows = raw_rows(path, "SELECT seq, record_type, record_id, entry_kind, payload, prev_digest FROM journal_entries ORDER BY seq")
    previous = rows[0][5]
    statements = []
    for number, record_type, record_id, kind, payload, _ in rows:
        kind = entry_kind if number == seq else kind
        digest = entry_digest(number, record_type, record_id, kind, payload, previous)
        statements.append(("UPDATE journal_entries SET entry_kind = ?, prev_digest = ?, digest = ? WHERE seq = ?",
                           (kind, previous, digest, number)))
        previous = digest
    raw_sql(path, *statements, ("UPDATE journal_meta SET head_digest = ?", (previous,)))


@pytest.mark.parametrize("case", ["evidence_disagrees_with_event", "unknown_record_relabelled_as_conflict"])
def test_case_6_rechained_entries_are_still_checked_for_consistency(tmp_path, case):
    """CASE 6 보완 (검토 MEDIUM 회귀). 입력: 해시 사슬과 head 해시까지 다시 계산해 맞춘 변경: (a) OrderEvent E-2(UNKNOWN)와 다른 내용의
    OrderEvidence E-2가 충돌 항목으로 보관된 Journal에서 그 충돌 항목을 받아들인 기록으로 바꿈, (b) UNKNOWN 증거 E-2 기록을 충돌
    항목으로 바꿈 (충돌할 기록 없이).
    출력: 해시는 맞아도 내용 검사로 CORRUPT: (a) CROSS_TYPE_MISMATCH (같은 사건의 OrderEvent와 OrderEvidence가 다름), (b)
    CONFLICT_ENTRY_INVALID. 서로 다른 사건 기록을 정상으로 복원하거나 UNKNOWN 기록을 충돌 항목으로 숨기지 않는다. 일반적인 위조
    검출은 아니다 (`TAMPER_RESISTANCE` 미확인)."""
    if case == "evidence_disagrees_with_event":
        _, _, stored, _, arrived = conflict_inputs("event_and_evidence")
        path = new_journal(tmp_path, *stored, arrived)
        rechain(path, 2, "RECORD")
        expected = {"CROSS_TYPE_MISMATCH"}
    else:
        path = new_journal(tmp_path, *unknown_c5(), NORMAL_AT_0900)
        rechain(path, 2, "CONFLICT")
        expected = {"CONFLICT_ENTRY_INVALID"}

    recovery = recover_order_journal(path)

    assert (recovery.status, codes(recovery)) == (R.CORRUPT, expected)
    with pytest.raises(JournalRecoveryError):
        recovery.order_evidence()


def test_case_6_missing_entries_are_reported_as_ranges(tmp_path):
    """CASE 6 보완 (검토 MEDIUM 회귀). 입력: (a) 네 항목 Journal의 head 기록 수를 7로, 다시 10**12로 바꾼다 (필드 하나의 손상),
    (b) 다른 Journal에서 항목 2와 3을 지운다.
    출력: INCOMPLETE이며 빠진 항목을 범위로 보고한다 (`ENTRY_MISSING:5-7`, `ENTRY_MISSING:5-1000000000000`, `ENTRY_MISSING:2-3`).
    빠진 번호마다 사유를 만들지 않으므로 손상된 기록 수가 커도 복구가 멈추지 않고 명시적 상태를 돌려준다. 수정 전에는 번호마다 사유를
    만들어 시간과 메모리가 기록 수에 비례했다 (500만에서 약 1.8초)."""
    path = new_journal(tmp_path, *unknown_c5(), NORMAL_AT_0900, HALTED_AT_0955)
    for count in (7, 10**12):
        raw_sql(path, ("UPDATE journal_meta SET entry_count = ?", (count,)))
        recovery = recover_order_journal(path)
        assert (recovery.status, recovery.reasons, recovery.entry_count) == (R.INCOMPLETE, (f"ENTRY_MISSING:5-{count}",), count)

    gap = new_journal(tmp_path, *unknown_c5(), NORMAL_AT_0900, HALTED_AT_0955, name="gap.sqlite3")
    raw_sql(gap, "DELETE FROM journal_entries WHERE seq IN (2, 3)")
    assert (recover_order_journal(gap).status, recover_order_journal(gap).reasons) == (R.INCOMPLETE, ("ENTRY_MISSING:2-3",))


@pytest.mark.parametrize("change, status, reason, version", [
    ("PRAGMA user_version = 2", R.UNSUPPORTED_VERSION, "SCHEMA_VERSION_UNSUPPORTED:2", 2),
    ("PRAGMA user_version = 0", R.UNSUPPORTED_VERSION, "SCHEMA_VERSION_UNSUPPORTED:0", 0),
    ("PRAGMA application_id = 0", R.UNREADABLE, "NOT_AN_ORDER_JOURNAL", None),
])
def test_case_7_unsupported_schema_version_blocks_recovery_and_writes(tmp_path, change, status, reason, version):
    """CASE 7. 입력: 정상 Journal의 파일 머리를 바꾼다: schema version 2 (이 코드가 모르는 다음 버전), version 0 (version 없음),
    응용 식별자 0 (주문 기록 Journal이 아님).
    출력: UNSUPPORTED_VERSION 또는 UNREADABLE과 사유. 아는 버전으로 가정해 읽지 않고 기록을 꺼내면 JournalRecoveryError. 새 기록
    저장은 JournalIntegrityError이고 파일을 바꾸지 않는다 (버전을 고쳐 쓰지 않음)."""
    path = new_journal(tmp_path, *unknown_c5(), NORMAL_AT_0900)
    raw_sql(path, change)
    held = file_digest(path)

    recovery = recover_order_journal(path)

    assert (recovery.status, recovery.reasons, recovery.schema_version) == (status, (reason,), version)
    with pytest.raises(JournalRecoveryError):
        recovery.order_evidence()
    with pytest.raises(JournalIntegrityError) as raised:
        append_to_order_journal(path, [HALTED_AT_0955])
    assert (raised.value.status, raised.value.reasons) == (status, (reason,))
    assert file_digest(path) == held


def test_case_7_other_sqlite_files_are_not_order_journals(tmp_path):
    """입력: 다른 용도의 SQLite 파일 (같은 이름의 표가 있어도 파일 머리의 응용 식별자가 없음).
    출력: UNREADABLE(NOT_AN_ORDER_JOURNAL). 저장은 JournalIntegrityError이고 파일은 그대로다."""
    path = tmp_path / "other.sqlite3"
    raw_sql(path, "CREATE TABLE journal_entries (seq INTEGER PRIMARY KEY, payload TEXT)", "INSERT INTO journal_entries VALUES (1, 'x')")
    held = file_digest(path)

    recovery = recover_order_journal(path)

    assert (recovery.status, recovery.reasons) == (R.UNREADABLE, ("NOT_AN_ORDER_JOURNAL",))
    with pytest.raises(JournalIntegrityError):
        append_to_order_journal(path, unknown_c5())
    assert file_digest(path) == held


def restart_cases():
    """CASE 8 입력 (Slice 3 CASE 1 = P6, CASE 2 = P8): 증거, 체결 장부의 체결, 목표."""
    p6 = unknown_c5() + [evidence("E-3", "C-5", 5, S.PARTIALLY_FILLED, K.FILL_NOTIFICATION, "09:57", "09:58", filled=3)]
    p8 = unknown_c5() + [evidence("E-9", "C-5", 5, S.CANCELLED, K.STATUS_QUERY_RESPONSE, "09:57", source=SRC.SIMULATOR, cancelled=5,
                                  requested="09:56")]
    return {"p6": (p6, [make_fill("X-1", "C-5", 3, "09:57")], {C1: 10, C2: 2}), "p8": (p8, [], {C1: 10, C2: 0})}


def child_write_restart_cases(directory):
    """CASE 8 자식 프로세스: P6·P8 증거와 09:00 NORMAL 기록을 각자의 Journal에 저장하고 정상 종료한다."""
    for name, (items, _, _) in restart_cases().items():
        new_journal(directory, *items, NORMAL_AT_0900, name=f"{name}.sqlite3")


def test_case_8_p6_and_p8_hold_after_a_process_restart(tmp_path):
    """CASE 8. 입력: 자식 프로세스가 P6(UNKNOWN +5에 체결 +3 통보만)과 P8(브로커 확인 계좌의 UNKNOWN +5에 시뮬레이터의 CANCELLED 조회
    결과) 증거와 09:00 NORMAL 기록을 각자의 Journal에 저장하고 끝난다. 이 프로세스에서 복구해 판단 10:00.
    출력: 두 Journal 모두 RECOVERED이고 L3 보고서가 재시작 전(같은 입력을 메모리에서 판정)과 같다. P6: 체결 통보는 FILLS_ONLY, 주문은
    UNKNOWN(체결 3), 최악 경우 롱 3 + 2 = 5. P8: 시뮬레이터 보고는 버려지지 않고 복원되어 REJECTED(SOURCE_MISMATCH)로 남고 주문은
    UNKNOWN, 최악 경우 롱 5. 모든 월물 BLOCKED (P8은 ORDER_EVIDENCE_CONFLICT도)."""
    child = run_child("child_write_restart_cases", tmp_path)
    assert child.returncode == 0, child.stderr

    reports = {}
    for name, (items, fills, targets) in restart_cases().items():
        recovery = recovered(tmp_path / f"{name}.sqlite3")
        assert recovery.order_evidence() == tuple(items)
        reports[name] = gate(list(recovery.order_evidence()), "10:00", targets=targets, fills=fills,
                             records=recovery.trading_state_records())
        assert reports[name] == gate(items, "10:00", targets=targets, fills=fills)

    p6, p8 = reports["p6"], reports["p8"]
    assert (p6.evidence.assessments[-1].event_id, p6.evidence.assessments[-1].disposition) == ("E-3", D.FILLS_ONLY)
    assert (p6.evidence.snapshot.records()[0].status, p6.evidence.snapshot.records()[0].filled_quantity) == (S.UNKNOWN, 3)
    assert (p6.risk.risk.view(C1).worst_case.actual_quantity, p6.risk.risk.view(C1).worst_case.worst_long_before) == (3, 5)
    assert_all_blocked(p6, "UNKNOWN_ORDER_PRESENT")
    rejected = p8.evidence.assessments[-1]
    assert (rejected.event_id, rejected.source, rejected.disposition, rejected.reasons) == (
        "E-9", SRC.SIMULATOR, D.REJECTED, ("SOURCE_MISMATCH",))
    assert p8.evidence.snapshot.records()[0].status is S.UNKNOWN
    assert (p8.risk.risk.view(C1).worst_case.worst_long_before, p8.risk.risk.view(C1).exposure_before) == (5, Decimal("5000"))
    assert_all_blocked(p8, "UNKNOWN_ORDER_PRESENT", "ORDER_EVIDENCE_CONFLICT")


def test_case_9_halted_record_is_restored_with_its_times_cause_and_approver(tmp_path):
    """CASE 9. 입력: 09:00 NORMAL (승인자 user:approval), 09:55:00.123456 HALTED (원인 UNKNOWN_ORDER, 승인자 없음, 09:55:01.654321에
    이용 가능, UTC를 timezone(timedelta(0))로 표현). 저장 뒤 복구하고 판단 10:00 (주문 없음, 목표 C1 +5).
    출력: 두 기록이 값·순서·마이크로초·UTC·원인·승인자(None 포함)까지 같다. HALTED가 그대로 적용되어 L3 보고서가 저장 전과 같고
    모든 월물 BLOCKED(TRADING_STATE_HALTED). 같은 기록 ID로 NORMAL 기록(승인자 있음)이 와도 CONFLICT이고 HALTED 기록이 유지된다
    (덮어쓰거나 자동 해제하지 않음)."""
    halted = sample_records()[-2]
    path = new_journal(tmp_path, NORMAL_AT_0900, halted)

    recovery = recovered(path)

    assert recovery.trading_state_records() == (NORMAL_AT_0900, halted)
    normal, restored = recovery.trading_state_records()
    assert (normal.approver_ref, restored.state, restored.cause_code, restored.approver_ref) == (
        "user:approval", TradingState.HALTED, "UNKNOWN_ORDER", None)
    assert (restored.effective_at, restored.data_available_at) == (datetime(2026, 10, 21, 9, 55, 0, 123456, tzinfo=UTC),
                                                                   datetime(2026, 10, 21, 9, 55, 1, 654321, tzinfo=UTC))
    assert restored.effective_at.utcoffset() == restored.data_available_at.utcoffset() == timedelta(0)
    report = gate([], "10:00", targets={C1: 5, C2: 0}, records=recovery.trading_state_records())
    assert report == gate([], "10:00", targets={C1: 5, C2: 0}, records=(NORMAL_AT_0900, halted))
    assert (report.trading_state_applied, report.trading_state_record) == (TradingState.HALTED, halted)
    assert_all_blocked(report, "TRADING_STATE_HALTED")

    released = dataclasses.replace(halted, state=TradingState.NORMAL, approver_ref="user:approval")
    assert append_to_order_journal(path, [released]).results[0].outcome is A.CONFLICT
    after = recover_order_journal(path)
    assert (after.status, after.conflicts[0].kept, after.conflicts[0].arrived) == (R.CONFLICT, halted, released)


@pytest.mark.parametrize("after", [False, True])
def test_case_10_fault_around_commit_never_reports_success(tmp_path, after):
    """CASE 10 (연결 오류 주입). 입력: 빈 Journal에 UNKNOWN 증거 두 건을 저장하다 COMMIT 직전 또는 직후 연결 오류가 난다.
    출력: 두 경우 모두 JournalWriteError이고 성공을 보고하지 않는다. 직전: may_be_persisted=False, 복구하면 기록이 없다. 직후:
    may_be_persisted=True (커밋 결과를 알 수 없음), 복구하면 두 건이 있다. 같은 기록을 다시 저장하면 직전은 APPENDED, 직후는
    DUPLICATE로 한 번만 저장된다 (재시도가 멱등). 전원 장애·디스크 캐시 손실은 시험하지 않는다."""
    path = new_journal(tmp_path)
    items = unknown_c5()

    with pytest.raises(JournalWriteError) as raised:
        append_to_order_journal(path, items, connection_factory=faulty_connection("COMMIT", after=after))

    assert raised.value.may_be_persisted is after
    assert recovered(path).order_evidence() == (tuple(items) if after else ())
    retry = append_to_order_journal(path, items)
    assert [result.outcome for result in retry.results] == [A.DUPLICATE if after else A.APPENDED] * 2
    assert recovered(path).order_evidence() == tuple(items)


def exit_batch():
    """CASE 10 자식 프로세스가 저장하는 묶음: 서로 다른 주문의 제출 기록 120건 (커밋 전에 page cache가 넘칠 만큼 큼)."""
    return [evidence(f"E-B{index}", f"C-B{index}", 1, S.PENDING_SUBMIT, K.LOCAL_RECORD, "09:50") for index in range(120)]


def child_append_and_exit(path, when):
    """CASE 10 자식 프로세스: 묶음을 저장하다 COMMIT 직전·직후 끝난다."""
    append_to_order_journal(path, exit_batch(), connection_factory=exiting_connection(when))
    raise AssertionError("the child process should have exited at COMMIT")


@pytest.mark.parametrize("when", ["before", "after"])
def test_case_10_process_exit_around_commit(tmp_path, when):
    """CASE 10 (프로세스 종료 주입). 입력: 증거 하나가 있는 Journal에 자식 프로세스가 제출 기록 120건을 저장하다 COMMIT 직전 또는 직후
    os._exit로 끝난다.
    출력: 직전: 끝나지 않은 트랜잭션이 파일과 rollback journal에 남아 있지만, 복구하면 처음 증거 하나만 있고 파일이 커밋된 바이트로
    돌아온다 (부분 저장 없음). 직후: 120건이 모두 있다. 프로세스 종료만 시험하며 전원 장애·디스크 캐시 손실은 시험하지 않는다 (Q12-7)."""
    path = new_journal(tmp_path, unknown_c5()[0])
    committed = file_digest(path)

    child = run_child("child_append_and_exit", path, when)

    assert child.returncode == 17, child.stderr
    rollback_journal = Path(f"{path}-journal")
    if when == "before":
        assert rollback_journal.exists() and file_digest(path) != committed
    recovery = recovered(path)
    assert recovery.order_evidence() == (unknown_c5()[0], *(exit_batch() if when == "after" else ()))
    if when == "before":
        assert file_digest(path) == committed and not rollback_journal.exists()


def test_recovery_does_not_establish_completeness_or_reconciliation(tmp_path):
    """입력: 주문 없이 09:00 NORMAL 기록만 저장한 Journal을 복구. 판단 10:00, 목표 C1 +5 (위험 증가 후보).
    출력: RECOVERED이며 복구는 파일 바이트를 바꾸지 않는다. 복구 결과에는 완전성 값이 없고 확인하지 않은 것을 명시한다 (주문 기록 완전성,
    브로커 대조, 위변조 방지, 전원 장애 내구성, 체결·현금·NAV 상태, Trading State의 운영상 권위). 완전성을 확인하지 않은 채(UNVERIFIED)
    L3에 넣으면 C1 후보는 NOT_ASSESSABLE(ORDER_LOG_NOT_VERIFIED_COMPLETE)이고 NO_BLOCK_FOUND가 아니다."""
    path = new_journal(tmp_path, NORMAL_AT_0900)
    held = file_digest(path)

    recovery = recovered(path)

    assert file_digest(path) == held
    assert recovery.not_established == JOURNAL_RECOVERY_NOT_ESTABLISHED == (
        "ORDER_LOG_COMPLETENESS", "BROKER_RECONCILIATION", "TAMPER_RESISTANCE", "POWER_LOSS_DURABILITY", "FILL_CASH_NAV_STATE",
        "TRADING_STATE_AUTHORITY")
    assert not hasattr(recovery, "completeness")
    report = gate(list(recovery.order_evidence()), "10:00", targets={C1: 5, C2: 0}, records=recovery.trading_state_records(),
                  completeness=UNVERIFIED)
    view = report.view(C1)
    assert (view.candidate_quantity, view.candidate_effect, view.status) == (5, CandidateRiskEffect.RISK_INCREASING, G.NOT_ASSESSABLE)
    assert "ORDER_LOG_NOT_VERIFIED_COMPLETE" in view.unassessable_reasons


def test_restoring_an_older_copy_is_not_detected_locally(tmp_path):
    """입력: PENDING_SUBMIT +5 증거와 NORMAL 기록만 있을 때 파일 사본을 떠 둔다. 그 뒤 UNKNOWN 증거를 저장하고, 사본으로 파일을 되돌린다
    (head까지 함께 되돌린 이전 사본). 판단 10:00, 목표 C1 +10.
    출력: 로컬 검사로는 검출되지 않아 RECOVERED이고 UNKNOWN 기록이 빠진다 (해시 사슬은 이전 사본 복원·위조를 막지 못함:
    `TAMPER_RESISTANCE`, `BROKER_RECONCILIATION` 미확인). 그래서 완전성은 확인되지 않은 값(UNVERIFIED)으로 넣어야 하며, 그러면 위험
    증가 후보(+5, 최악 경우 롱 5 → 10)는 NOT_ASSESSABLE(ORDER_LOG_NOT_VERIFIED_COMPLETE)이고 통과하지 않는다. 기록 유실을 잡는 장치는
    재시작 브로커 대조다 (ADR-0012 BR-3 (6), 미구현)."""
    path = new_journal(tmp_path, unknown_c5()[0], NORMAL_AT_0900)
    older = path.read_bytes()
    append_to_order_journal(path, [unknown_c5()[1]])
    path.write_bytes(older)

    recovery = recovered(path)

    assert recovery.order_evidence() == (unknown_c5()[0],)
    assert {"TAMPER_RESISTANCE", "BROKER_RECONCILIATION"} <= set(recovery.not_established)
    report = gate(list(recovery.order_evidence()), "10:00", targets={C1: 10, C2: 0}, records=recovery.trading_state_records(),
                  completeness=UNVERIFIED)
    view = report.view(C1)
    assert report.evidence.snapshot.records()[0].status is S.PENDING_SUBMIT
    risk = report.risk.risk.view(C1)
    assert (risk.worst_case.worst_long_before, view.candidate_quantity, risk.exposure_after) == (5, 5, Decimal("10000"))
    assert view.status is G.NOT_ASSESSABLE and "ORDER_LOG_NOT_VERIFIED_COMPLETE" in view.unassessable_reasons
