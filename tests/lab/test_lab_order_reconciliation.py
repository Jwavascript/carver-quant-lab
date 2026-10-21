"""P0-03C Slice 5: 읽기 전용 주문 대조 (ADR-0012 BF-3·BF-4·BF-11·BR-4·BR-6·BR-7·BR-10·BR-12·§6.3a·AT-0012-5·AT-0012-11, ADR-0009
R9-4·R9-8·R9-13, ADR-0003 S-3·§6.5, ADR-0013 R13-1a).

로컬 기록은 기존 `orders_from_evidence_as_of`의 결정 시점 Snapshot이고, 브로커 Snapshot은 테스트가 명시적으로 넘기는 가상의 외부 보고다
(실제 브로커 호출·인증 없음). 대조는 비교한 항목의 일치·불일치·확인 불가만 말하며 주문·포지션·Trading State를 바꾸지 않는다.
기대 차이(−3, +2, −2, −10)와 상태는 저장소 밖 독립 산술로 먼저 확인했다. 가상 선물이며 한도·가격·승수·체결 장부는 테스트 입력이다.
"""

import dataclasses
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from carver_quant.lab.accounting.fill_ledger import FillLedger, apply_fill
from carver_quant.lab.accounting.l3_gate import L3GateStatus, assess_l3_gate_as_of
from carver_quant.lab.accounting.order_reconciliation import reconcile_order_snapshot
from carver_quant.lab.accounting.order_snapshot import OrderLogCompleteness
from carver_quant.lab.accounting.unknown_resolution import EvidenceDisposition, orders_from_evidence_as_of
from carver_quant.lab.adapters.order_journal import append_to_order_journal, create_order_journal, recover_order_journal
from carver_quant.lab.domain.order_events import OrderEvent, OrderEventKind
from carver_quant.lab.domain.order_evidence import OrderEvidence, OrderEvidenceKind
from carver_quant.lab.domain.orders import OrderRecord, OrderStatus, OrderStatusSource
from carver_quant.lab.domain.reconciliation import (
    RECONCILIATION_NOT_ESTABLISHED,
    BrokerOrderReport,
    BrokerOrderSnapshot,
    BrokerSnapshotCompleteness,
    BrokerSnapshotScope,
    ReconciliationStatus,
)
from carver_quant.lab.domain.records import FillKey, FillOrigin, FillRecord, FuturesContractSpec, PositionBaseline, ValuationPrice
from carver_quant.lab.domain.risk import ContractMultiplier, ExposureLimit, TradingState
from carver_quant.lab.domain.trading_state import TradingStateRecord

UTC = timezone.utc
S = OrderStatus
K = OrderEvidenceKind
SRC = OrderStatusSource
D = EvidenceDisposition
G = L3GateStatus
M = ReconciliationStatus
SCOPE = BrokerSnapshotScope
C1 = "FUT.ALPHA.C1"
C2 = "FUT.ALPHA.C2"
T0 = datetime(2026, 10, 21, 0, 0, tzinfo=UTC)
COMPLETE = OrderLogCompleteness.VERIFIED_COMPLETE
UNVERIFIED = OrderLogCompleteness.UNVERIFIED
EVENT_KIND = {SRC.SYSTEM: OrderEventKind.SYSTEM_RECORD, SRC.BROKER: OrderEventKind.BROKER_REPORT, SRC.SIMULATOR: OrderEventKind.SIMULATOR_REPORT}
FIELDS = ("client_order_id", "broker_order_id", "contract_id", "side", "quantity", "filled_quantity", "remaining_quantity", "status")


def at(clock):
    """"HH:MM" 또는 "HH:MM:SS"의 2026-10-21 UTC 시각."""
    return datetime(2026, 10, 21, *(int(part) for part in clock.split(":")), tzinfo=UTC)


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


def state_record(record_id, state, effective, *, approver="user:approval", cause="test:cause"):
    return TradingStateRecord(record_id=record_id, account_id="A1", state=state, effective_at=at(effective),
                              data_available_at=at(effective), cause_code=cause, approver_ref=approver)


NORMAL_AT_0900 = state_record("TS-1", TradingState.NORMAL, "09:00")
HALTED_AT_0955 = state_record("TS-2", TradingState.HALTED, "09:55", cause="UNKNOWN_ORDER", approver=None)


def contract(contract_id):
    return FuturesContractSpec(contract_id=contract_id, instrument_id="FUT.ALPHA", currency="USD", multiplier="10", lot_size=1)


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


def gate(items, decision, *, targets, fills=(), records=(NORMAL_AT_0900,)):
    return assess_l3_gate_as_of(
        baseline=PositionBaseline(account_id="A1", as_of=T0, quantities={C1: 0, C2: 0}, verification_ref="fixture:verified"),
        ledger=ledger_with(*fills),
        evidence=items,
        confirming_source=SRC.BROKER,
        completeness=COMPLETE,
        completeness_ref="fixture:complete-log",
        targets=targets,
        decision_at=at(decision),
        trading_state=TradingState.NORMAL,
        trading_state_records=records,
        **risk_inputs(at(decision)),
    )


def assert_all_blocked(report, *reasons):
    for view in report.views:
        assert view.status is G.BLOCKED
        for reason in reasons:
            assert reason in view.blocking_reasons


def accepted_c5():
    """09:50 매수 +5 제출 (PENDING_SUBMIT 로컬 기록), 09:51 브로커 접수 응답 (ACCEPTED, B-C-5)."""
    return [
        evidence("E-1", "C-5", 5, S.PENDING_SUBMIT, K.LOCAL_RECORD, "09:50"),
        evidence("E-2", "C-5", 5, S.ACCEPTED, K.REQUEST_RESPONSE, "09:51"),
    ]


def unknown_c5():
    """09:50 매수 +5 제출 (PENDING_SUBMIT), 09:55 응답 timeout으로 UNKNOWN. 둘 다 시스템 기록이다 (Broker Order ID 없음)."""
    return [
        evidence("E-1", "C-5", 5, S.PENDING_SUBMIT, K.LOCAL_RECORD, "09:50"),
        evidence("E-2", "C-5", 5, S.UNKNOWN, K.LOCAL_RECORD, "09:55"),
    ]


def local(items, decision="10:00", *, completeness=UNVERIFIED, confirming=SRC.BROKER):
    return orders_from_evidence_as_of(items, at(decision), account_id="A1", confirming_source=confirming, completeness=completeness,
                                      completeness_ref="fixture:complete-log" if completeness is COMPLETE else None)


def line(client_order_id, quantity, status, *, filled=0, remaining=None, broker_id="default", contract_id=C1):
    if remaining is None:
        remaining = quantity - filled
    if broker_id == "default":
        broker_id = "B-" + client_order_id
    return BrokerOrderReport(client_order_id=client_order_id, broker_order_id=broker_id, contract_id=contract_id, quantity=quantity,
                             filled_quantity=filled, remaining_quantity=remaining, status=status)


def snapshot(*orders, scope=SCOPE.OPEN_ORDERS, observed="09:58", available="09:59", source=SRC.BROKER, complete=False, queried=(),
             account_id="A1", snapshot_id="S-1"):
    return BrokerOrderSnapshot(
        snapshot_id=snapshot_id,
        account_id=account_id,
        source=source,
        scope=scope,
        queried_client_order_ids=tuple(queried),
        completeness=BrokerSnapshotCompleteness.COMPLETE_FOR_SCOPE if complete else BrokerSnapshotCompleteness.UNVERIFIED,
        completeness_ref="fixture:complete-listing" if complete else None,
        observed_at=at(observed),
        available_at=at(available),
        orders=tuple(orders),
    )


def reconcile(items, broker, decision="10:00", *, completeness=UNVERIFIED, confirming=SRC.BROKER):
    return reconcile_order_snapshot(local(items, decision, completeness=completeness, confirming=confirming), broker, at(decision))


def summary(field):
    return (field.local_value, field.broker_value, field.status, field.reason, field.difference)


def test_broker_order_report_contract():
    """입력: 정상 브로커 주문 보고(매수 부분 체결, 매도 부분 체결)와 계약을 어기는 보고: 수량 0, bool·실수 수량, 방향과 반대 부호의 체결·
    잔량, 체결 + 잔량 > 주문 수량, INTENT 상태(시스템만의 상태), 체결이 있는 ACCEPTED·PENDING_SUBMIT, 잔량 없는 ACCEPTED, 체결 없거나
    잔량 없는 PARTIALLY_FILLED, 전량이 아닌 FILLED, 잔량이 남은 FILLED·CANCELLED·EXPIRED·REJECTED, 체결이 있는 REJECTED, 빈 Broker
    Order ID, 앞뒤 공백 식별자, 열거형이 아닌 상태.
    출력: 정상 보고는 보고된 수량을 그대로 가진다 (lot 배수 요구 없음, 체결 + 잔량 < 주문 수량이어도 나머지를 추정하지 않음).
    나머지는 모두 ValueError."""
    buy = line("C-5", 5, S.PARTIALLY_FILLED, filled=2, remaining=1)
    sell = line("C-6", -5, S.PARTIALLY_FILLED, filled=-2, remaining=-3)
    assert (buy.quantity, buy.filled_quantity, buy.remaining_quantity) == (5, 2, 1)
    assert (sell.quantity, sell.filled_quantity, sell.remaining_quantity) == (-5, -2, -3)

    bad = [
        dict(quantity=0, remaining=0),
        dict(quantity=True, remaining=1),
        dict(filled=1.0, remaining=4),
        dict(filled=-1, remaining=5),
        dict(remaining=-1),
        dict(filled=3, remaining=3, status=S.PARTIALLY_FILLED),
        dict(status=S.INTENT),
        dict(filled=2, remaining=3),
        dict(filled=2, remaining=3, status=S.PENDING_SUBMIT),
        dict(remaining=0),
        dict(status=S.PARTIALLY_FILLED),
        dict(filled=5, remaining=0, status=S.PARTIALLY_FILLED),
        dict(filled=4, remaining=0, status=S.FILLED),
        dict(filled=5, remaining=0, status=S.FILLED, quantity=6),
        dict(filled=2, remaining=1, status=S.CANCELLED),
        dict(remaining=1, status=S.EXPIRED),
        dict(remaining=1, status=S.REJECTED),
        dict(filled=1, remaining=0, status=S.REJECTED),
        dict(broker_order_id=""),
        dict(client_order_id=" C-5"),
        dict(status="ACCEPTED"),
    ]
    for changes in bad:
        values = dict(client_order_id="C-5", broker_order_id="B-C-5", contract_id=C1, quantity=5, filled=0, remaining=5,
                      status=S.ACCEPTED)
        values.update(changes)
        with pytest.raises(ValueError):
            BrokerOrderReport(client_order_id=values["client_order_id"], broker_order_id=values["broker_order_id"],
                              contract_id=values["contract_id"], quantity=values["quantity"], filled_quantity=values["filled"],
                              remaining_quantity=values["remaining"], status=values["status"])


def test_broker_snapshot_contract():
    """입력: 정상 미체결 목록 Snapshot과 계약을 어기는 Snapshot: 시스템 출처, 관측 시각 > 이용 가능 시각, 시간대 없는 시각, 근거 참조
    없는 완전성 선언, 완전하다고 선언한 주문 조회 (BR-4), 조회 대상이 없는 주문 조회, 조회하지 않은 주문을 담은 주문 조회, Client
    Order ID 없는 주문 조회 결과, 주문 조회가 아닌데 조회 대상이 있음, 미체결 목록에 종료 주문, 같은 Client Order ID 두 줄, 같은
    Broker Order ID 두 줄, 보고가 아닌 값, 범위 열거형이 아닌 값.
    출력: 정상 Snapshot은 범위·출처·완전성·시각을 그대로 가진다. 나머지는 ValueError (식별자 중복·충돌을 고르지 않음)."""
    valid = snapshot(line("C-5", 5, S.ACCEPTED), complete=True)
    assert (valid.scope, valid.source, valid.completeness, valid.observed_at, valid.available_at) == (
        SCOPE.OPEN_ORDERS, SRC.BROKER, BrokerSnapshotCompleteness.COMPLETE_FOR_SCOPE, at("09:58"), at("09:59"))

    bad = [
        lambda: snapshot(source=SRC.SYSTEM),
        lambda: snapshot(observed="10:00", available="09:59"),
        lambda: dataclasses.replace(valid, observed_at=datetime(2026, 10, 21, 9, 58)),
        lambda: dataclasses.replace(valid, completeness_ref=None),
        lambda: snapshot(line("C-5", 5, S.ACCEPTED), scope=SCOPE.ORDER_QUERY, queried=("C-5",), complete=True),
        lambda: snapshot(scope=SCOPE.ORDER_QUERY),
        lambda: snapshot(line("C-6", 5, S.ACCEPTED), scope=SCOPE.ORDER_QUERY, queried=("C-5",)),
        lambda: snapshot(line(None, 5, S.ACCEPTED, broker_id="B-9"), scope=SCOPE.ORDER_QUERY, queried=("C-5",)),
        lambda: snapshot(queried=("C-5",)),
        lambda: snapshot(line("C-5", 5, S.FILLED, filled=5)),
        lambda: snapshot(line("C-5", 5, S.ACCEPTED), line("C-5", 5, S.ACCEPTED, broker_id="B-9")),
        lambda: snapshot(line("C-5", 5, S.ACCEPTED), line("C-6", 5, S.ACCEPTED, broker_id="B-C-5")),
        lambda: snapshot(valid.orders[0].__dict__),
        lambda: dataclasses.replace(valid, scope="OPEN_ORDERS"),
    ]
    for make in bad:
        with pytest.raises(ValueError):
            make()


def test_case_1_matching_open_order_matches_only_the_compared_fields():
    """CASE 1. 입력: 로컬 C-5 매수 +5 (09:50 제출, 09:51 브로커 접수 B-C-5, 체결 0). 브로커 미체결 목록 (09:58 관측, 09:59 이용
    가능): C-5 / B-C-5 / C1 / +5 / 체결 0 / 잔량 5 / ACCEPTED. 판단 10:00. (a) 목록 완전성 미선언, 로컬 기록 완전성 미확인, (b) 둘 다
    선언·확인.
    출력: C-5의 비교 필드(Client·Broker Order ID, 월물, 방향, 수량, 누적 체결, 잔량, 상태)가 모두 MATCH이고 주문 MATCH. (a) 보고서는
    UNVERIFIED (BROKER_SNAPSHOT_INCOMPLETE, LOCAL_ORDER_LOG_NOT_VERIFIED_COMPLETE): 브로커 기록 전체의 완전성은 별도다. (b) 보고서가
    MATCH여도 실제 포지션·체결 목록·현금, 브로커 시각의 의미·진위, UNKNOWN 해소, Trading State 해제는 확인하지 않은 것으로 남는다.
    HALTED 기록이 있는 계좌의 L3 판정은 대조와 무관하게 모든 월물 BLOCKED (TRADING_STATE_HALTED)."""
    items = accepted_c5()
    broker = snapshot(line("C-5", 5, S.ACCEPTED))

    report = reconcile(items, broker)

    order = report.order("C-5")
    assert (order.status, order.reasons, tuple(field.name for field in order.fields)) == (M.MATCH, (), FIELDS)
    assert all(field.status is M.MATCH for field in order.fields)
    assert [summary(order.field(name)) for name in ("side", "remaining_quantity", "status")] == [
        ("BUY", "BUY", M.MATCH, None, None), (5, 5, M.MATCH, None, 0), ("ACCEPTED", "ACCEPTED", M.MATCH, None, None)]
    assert (report.status, report.reasons) == (M.UNVERIFIED, ("BROKER_SNAPSHOT_INCOMPLETE", "LOCAL_ORDER_LOG_NOT_VERIFIED_COMPLETE"))
    assert (report.snapshot_id, report.snapshot_observed_at, report.snapshot_available_at, report.scope) == (
        "S-1", at("09:58"), at("09:59"), SCOPE.OPEN_ORDERS)

    complete = reconcile(items, snapshot(line("C-5", 5, S.ACCEPTED), complete=True), completeness=COMPLETE)
    assert (complete.status, complete.reasons, complete.order("C-5").status) == (M.MATCH, (), M.MATCH)
    assert complete.not_established == RECONCILIATION_NOT_ESTABLISHED == (
        "ACTUAL_POSITION", "FILL_RECORDS", "CASH", "ORDERS_OUTSIDE_SNAPSHOT_SCOPE", "SNAPSHOT_TIME_MEANING", "BROKER_AUTHENTICITY",
        "UNKNOWN_RESOLUTION", "TRADING_STATE_RELEASE")
    halted = gate(items, "10:00", targets={C1: 5, C2: 0}, records=(NORMAL_AT_0900, HALTED_AT_0955))
    assert halted == gate(items, "10:00", targets={C1: 5, C2: 0}, records=(NORMAL_AT_0900, HALTED_AT_0955))
    assert_all_blocked(halted, "TRADING_STATE_HALTED")


def test_case_2_remaining_quantity_mismatch_is_reported_without_guessing():
    """CASE 2. 입력: 로컬 C-5 ACCEPTED +5 (체결 0, 잔량 5). 브로커 보고 C-5 ACCEPTED +5, 체결 0, 잔량 2.
    출력: 주문 MISMATCH (REMAINING_QUANTITY_MISMATCH), 잔량 필드는 로컬 5 / 브로커 2 / 차이 −3. 누적 체결은 0 / 0으로 MATCH: 3계약이
    체결되었다고 추정하지 않고, 로컬 주문 기록을 2계약으로 고치지 않는다 (대조 결과는 원래 기록을 그대로 담는다)."""
    items = accepted_c5()
    before = local(items)

    report = reconcile_order_snapshot(before, snapshot(line("C-5", 5, S.ACCEPTED, remaining=2)), at("10:00"))

    order = report.order("C-5")
    assert (order.status, order.reasons) == (M.MISMATCH, ("REMAINING_QUANTITY_MISMATCH",))
    assert summary(order.field("remaining_quantity")) == (5, 2, M.MISMATCH, "REMAINING_QUANTITY_MISMATCH", -3)
    assert summary(order.field("filled_quantity")) == (0, 0, M.MATCH, None, 0)
    assert order.local == before.snapshot.records()[0] and before == local(items)
    assert (order.local.status, order.local.filled_quantity, order.local.cancelled_quantity) == (S.ACCEPTED, 0, 0)


def test_case_3_order_only_at_the_broker_is_reported_not_created():
    """CASE 3. 입력: 로컬에는 C-5 +5만 있음. 브로커 미체결 목록에 C-5와 로컬 기록이 없는 C-7 +4 (B-C-7).
    출력: C-7은 MISMATCH (ORDER_MISSING_LOCALLY)이며 로컬 기록 없이 브로커 보고만 담는다. 로컬 주문으로 만들지 않는다 (로컬 Snapshot과
    L3 판정은 대조 전과 같다). 보고서에는 로컬 기록이 완전하다고 확인되지 않았다는 사유가 있다 (누락·불완전한 복구 가능성)."""
    items = accepted_c5()
    before = local(items)

    report = reconcile_order_snapshot(before, snapshot(line("C-5", 5, S.ACCEPTED), line("C-7", 4, S.ACCEPTED)), at("10:00"))

    found = report.order("C-7")
    assert (found.status, found.reasons, found.local, found.broker.quantity, found.fields) == (
        M.MISMATCH, ("ORDER_MISSING_LOCALLY",), None, 4, ())
    assert (report.status, "LOCAL_ORDER_LOG_NOT_VERIFIED_COMPLETE" in report.reasons) == (M.MISMATCH, True)
    assert before == local(items) and [record.client_order_id for record in before.snapshot.records()] == ["C-5"]
    assert gate(items, "10:00", targets={C1: 5, C2: 0}).evidence.snapshot == local(items, completeness=COMPLETE).snapshot


@pytest.mark.parametrize("complete, status, reason", [
    (False, M.UNVERIFIED, "BROKER_SNAPSHOT_INCOMPLETE"),
    (True, M.MISMATCH, "ORDER_MISSING_AT_BROKER"),
])
def test_case_4_order_missing_from_the_broker_listing(complete, status, reason):
    """CASE 4. 입력: 로컬 C-5 ACCEPTED +5. 브로커 미체결 목록에는 C-5가 없다. (a) 목록 완전성 미선언, (b) 그 범위의 완전한 목록으로 선언.
    출력: (a) UNVERIFIED (BROKER_SNAPSHOT_INCOMPLETE): 목록에 없다는 것만으로 주문이 없다고 보지 않는다 (BR-4). (b) 명시적 불일치
    MISMATCH (ORDER_MISSING_AT_BROKER). 어느 경우에도 로컬 주문은 ACCEPTED 그대로이며 CANCELLED로 바꾸지 않는다."""
    items = accepted_c5()

    report = reconcile(items, snapshot(line("C-9", 2, S.ACCEPTED), complete=complete))

    order = report.order("C-5")
    assert (order.status, order.reasons, order.broker, order.fields) == (status, (reason,), None, ())
    assert order.local.status is S.ACCEPTED and local(items).snapshot.records()[0].status is S.ACCEPTED


def test_snapshot_scope_decides_what_absence_means():
    """입력: 로컬 C-5 ACCEPTED +5, C-6 FILLED +2 (09:52 체결 통보로 전량 체결), C-8 INTENT (제출 전). 브로커 Snapshot에는 어느 주문도
    없다: (a) C-5를 조회한 주문 조회 결과 (찾지 못함), (b) 완전하다고 선언한 미체결 목록, (c) 완전하다고 선언한 계좌 주문 기록 전체.
    출력: (a) C-5는 UNVERIFIED (NOT_FOUND_IS_NOT_PROOF_OF_ABSENCE, BR-4), 조회하지 않은 C-6은 UNVERIFIED (OUTSIDE_SNAPSHOT_SCOPE).
    (b) 미체결이어야 할 C-5만 MISMATCH, 종료된 C-6은 미체결 목록의 범위 밖이라 UNVERIFIED. (c) C-5와 C-6 모두 MISMATCH. 제출되지 않은
    C-8은 어느 범위에서도 UNVERIFIED (LOCAL_ORDER_NOT_SUBMITTED)."""
    items = accepted_c5() + [
        evidence("E-3", "C-6", 2, S.PENDING_SUBMIT, K.LOCAL_RECORD, "09:50"),
        evidence("E-4", "C-6", 2, S.FILLED, K.FILL_NOTIFICATION, "09:52", filled=2),
        evidence("E-5", "C-8", 1, S.INTENT, K.LOCAL_RECORD, "09:53"),
    ]
    cases = [
        (snapshot(scope=SCOPE.ORDER_QUERY, queried=("C-5",)), ("NOT_FOUND_IS_NOT_PROOF_OF_ABSENCE", "OUTSIDE_SNAPSHOT_SCOPE")),
        (snapshot(complete=True), ("ORDER_MISSING_AT_BROKER", "OUTSIDE_SNAPSHOT_SCOPE")),
        (snapshot(scope=SCOPE.ACCOUNT_ORDERS, complete=True), ("ORDER_MISSING_AT_BROKER", "ORDER_MISSING_AT_BROKER")),
    ]
    for broker, (c5_reason, c6_reason) in cases:
        report = reconcile(items, broker)
        assert [(order.client_order_id, order.reasons) for order in report.orders] == [
            ("C-5", (c5_reason,)), ("C-6", (c6_reason,)), ("C-8", ("LOCAL_ORDER_NOT_SUBMITTED",))]
        assert [order.status for order in report.orders] == [
            M.MISMATCH if c5_reason == "ORDER_MISSING_AT_BROKER" else M.UNVERIFIED,
            M.MISMATCH if c6_reason == "ORDER_MISSING_AT_BROKER" else M.UNVERIFIED,
            M.UNVERIFIED]


def test_case_5_unknown_order_quantities_compare_but_unknown_and_its_block_stay():
    """CASE 5. 입력: 로컬 C-5 +5가 09:55 UNKNOWN (시스템 기록, Broker Order ID 없음). 브로커 보고 C-5 / B-77 ACCEPTED +5, 체결 0, 잔량 5.
    판단 10:00, 목표 C1 +10.
    출력: 월물·방향·수량·누적 체결·잔량은 MATCH이지만 상태는 UNVERIFIED (LOCAL_STATUS_UNKNOWN), Broker Order ID는 로컬에 없어
    UNVERIFIED이므로 주문은 UNVERIFIED다. 대조는 UNKNOWN을 해소하지 않고 새 증거를 만들지 않는다: 같은 증거로 낸 L3 판정은 그대로
    UNKNOWN, 최악 경우 롱 5, 노출 5,000 USD, 모든 월물 BLOCKED (UNKNOWN_ORDER_PRESENT)."""
    items = unknown_c5()
    before = gate(items, "10:00", targets={C1: 10, C2: 0})

    report = reconcile(items, snapshot(line("C-5", 5, S.ACCEPTED, broker_id="B-77")))

    order = report.order("C-5")
    assert (order.status, order.reasons) == (M.UNVERIFIED, ("LOCAL_BROKER_ORDER_ID_NOT_RECORDED", "LOCAL_STATUS_UNKNOWN"))
    assert [order.field(name).status for name in ("quantity", "filled_quantity", "remaining_quantity")] == [M.MATCH] * 3
    assert summary(order.field("status")) == ("UNKNOWN", "ACCEPTED", M.UNVERIFIED, "LOCAL_STATUS_UNKNOWN", None)
    after = gate(items, "10:00", targets={C1: 10, C2: 0})
    assert after == before and after.evidence.snapshot.records()[0].status is S.UNKNOWN
    view = after.risk.risk.view(C1)
    assert (view.worst_case.worst_long_before, view.exposure_before) == (5, Decimal("5000"))
    assert_all_blocked(after, "UNKNOWN_ORDER_PRESENT")


def test_case_6_simulator_snapshot_is_not_taken_as_broker_confirmation():
    """CASE 6. 입력: 브로커가 확인 출처인 계좌의 C-5 (B-C-5). 시뮬레이터 출처의 Snapshot이 같은 내용을 보고한다. 반대로 시뮬레이터가 확인
    출처인 계좌에 브로커 출처 Snapshot.
    출력: 두 경우 모두 보고서 UNVERIFIED (SOURCE_MISMATCH)이고 주문도 UNVERIFIED (SOURCE_MISMATCH). Snapshot의 주문을 비교하지 않고
    브로커에만 있는 주문으로도 보고하지 않는다 (확인 결과로 채택하지 않음)."""
    sim_items = [evidence("E-1", "C-5", 5, S.PENDING_SUBMIT, K.LOCAL_RECORD, "09:50"),
                 evidence("E-2", "C-5", 5, S.ACCEPTED, K.REQUEST_RESPONSE, "09:51", source=SRC.SIMULATOR)]
    cases = [
        (accepted_c5(), SRC.BROKER, SRC.SIMULATOR),
        (sim_items, SRC.SIMULATOR, SRC.BROKER),
    ]
    for items, confirming, offered in cases:
        report = reconcile(items, snapshot(line("C-5", 5, S.ACCEPTED), line("C-7", 4, S.ACCEPTED), source=offered),
                           confirming=confirming)
        assert (report.status, report.reasons[0]) == (M.UNVERIFIED, "SOURCE_MISMATCH")
        assert [(order.client_order_id, order.status, order.reasons, order.broker) for order in report.orders] == [
            ("C-5", M.UNVERIFIED, ("SOURCE_MISMATCH",), None)]


def test_case_7_snapshot_available_after_the_decision_is_not_used():
    """CASE 7. 입력: 판단 10:00. 같은 내용의 브로커 Snapshot이 10:04 관측, 10:05 이용 가능. 경계: 10:00 정각에 이용 가능, 10:00보다
    1마이크로초 뒤에 이용 가능.
    출력: 10:05 Snapshot은 10:00 대조에 쓰지 않는다: 보고서와 주문 UNVERIFIED (SNAPSHOT_NOT_AVAILABLE_AT_DECISION), 브로커 줄을
    비교하지 않는다. 10:00의 로컬 Snapshot은 대조 전과 같다 (과거 Snapshot을 고치지 않음). 판단 10:05에는 같은 Snapshot을 쓴다
    (주문 MATCH). 이용 가능 시각 = 판단 시각이면 쓰고 (ADR-0001 B-1), 1마이크로초라도 늦으면 쓰지 않는다."""
    items = accepted_c5()
    late = snapshot(line("C-5", 5, S.ACCEPTED), observed="10:04", available="10:05")
    before = local(items)

    report = reconcile_order_snapshot(before, late, at("10:00"))

    assert (report.status, report.reasons[0]) == (M.UNVERIFIED, "SNAPSHOT_NOT_AVAILABLE_AT_DECISION")
    assert [(order.client_order_id, order.status, order.reasons, order.broker) for order in report.orders] == [
        ("C-5", M.UNVERIFIED, ("SNAPSHOT_NOT_AVAILABLE_AT_DECISION",), None)]
    assert before == local(items)
    assert reconcile(items, late, "10:05").order("C-5").status is M.MATCH
    on_time = dataclasses.replace(late, observed_at=at("09:59"), available_at=at("10:00"))
    just_late = dataclasses.replace(on_time, available_at=at("10:00") + timedelta(microseconds=1))
    assert reconcile(items, on_time).order("C-5").status is M.MATCH
    assert reconcile(items, just_late).order("C-5").reasons == ("SNAPSHOT_NOT_AVAILABLE_AT_DECISION",)


def test_case_8_filled_quantity_mismatch_leaves_the_position_alone():
    """CASE 8. 입력: 로컬 C-5 +5에 09:55 체결 +3 통보 (PARTIALLY_FILLED, 확인 누적 체결 3, 체결 장부 X-1 +3). 브로커 보고 C-5 FILLED,
    누적 체결 5, 잔량 0 (09:58 관측).
    출력: 주문 MISMATCH: 누적 체결 3 / 5 (차이 +2, FILLED_QUANTITY_MISMATCH), 잔량 2 / 0 (차이 −2), 상태 PARTIALLY_FILLED / FILLED.
    체결 장부와 실제 포지션은 바꾸지 않는다: 같은 입력의 L3 판정은 대조 전과 같고 실제 수량은 3 그대로다."""
    items = accepted_c5() + [evidence("E-3", "C-5", 5, S.PARTIALLY_FILLED, K.FILL_NOTIFICATION, "09:55", filled=3)]
    fills = [make_fill("X-1", "C-5", 3, "09:55")]
    before = gate(items, "10:00", targets={C1: 5, C2: 0}, fills=fills)

    report = reconcile(items, snapshot(line("C-5", 5, S.FILLED, filled=5, remaining=0), scope=SCOPE.ACCOUNT_ORDERS))

    order = report.order("C-5")
    assert (order.status, order.reasons) == (
        M.MISMATCH, ("FILLED_QUANTITY_MISMATCH", "REMAINING_QUANTITY_MISMATCH", "STATUS_MISMATCH"))
    assert summary(order.field("filled_quantity")) == (3, 5, M.MISMATCH, "FILLED_QUANTITY_MISMATCH", 2)
    assert summary(order.field("remaining_quantity")) == (2, 0, M.MISMATCH, "REMAINING_QUANTITY_MISMATCH", -2)
    after = gate(items, "10:00", targets={C1: 5, C2: 0}, fills=fills)
    assert after == before and after.risk.risk.view(C1).worst_case.actual_quantity == 3


CHILD_MAIN = (
    "import importlib.util, sys\n"
    "spec = importlib.util.spec_from_file_location('order_reconciliation_restart_case', sys.argv[1])\n"
    "module = importlib.util.module_from_spec(spec)\n"
    "spec.loader.exec_module(module)\n"
    "getattr(module, sys.argv[2])(*sys.argv[3:])\n"
)


def run_child(function_name, *arguments):
    """이 파일을 새 Python 프로세스에서 불러 함수 하나를 실행한다 (재시작 전의 프로세스)."""
    return subprocess.run([sys.executable, "-W", "error", "-c", CHILD_MAIN, __file__, function_name, *map(str, arguments)],
                          capture_output=True, text=True, timeout=300, check=False)


def restart_items():
    """CASE 9 입력: 접수된 C-5 +5, 응답 timeout으로 UNKNOWN인 C-6 +2 (C2)."""
    return accepted_c5() + [
        evidence("E-3", "C-6", 2, S.PENDING_SUBMIT, K.LOCAL_RECORD, "09:52", contract_id=C2),
        evidence("E-4", "C-6", 2, S.UNKNOWN, K.LOCAL_RECORD, "09:54", contract_id=C2),
    ]


def restart_snapshot():
    """CASE 9 외부 Snapshot: C-5 일치, C-6 잔량 2 보고, 로컬에 없는 C-7 +4."""
    return snapshot(line("C-5", 5, S.ACCEPTED), line("C-6", 2, S.ACCEPTED, contract_id=C2), line("C-7", 4, S.ACCEPTED))


def child_write_restart_journal(path):
    """CASE 9 자식 프로세스: 증거와 NORMAL 기록을 Journal에 저장하고 정상 종료한다."""
    create_order_journal(path)
    append_to_order_journal(path, [*restart_items(), NORMAL_AT_0900])


def test_case_9_reconciliation_after_a_restart_is_the_same(tmp_path):
    """CASE 9. 입력: 자식 프로세스가 C-5(접수)·C-6(UNKNOWN) 증거와 NORMAL 기록을 Slice 4 Journal에 저장하고 끝난다. 이 프로세스에서
    복구하고, 복구 기록과 같은 외부 Snapshot(C-5 일치, C-6 잔량 2, 로컬에 없는 C-7)으로 판단 10:00에 대조한다.
    출력: Journal은 RECOVERED이고 대조 보고서가 재시작 전(메모리의 같은 증거)과 같다: C-5 MATCH, C-6 UNVERIFIED (UNKNOWN), C-7
    MISMATCH, 보고서 MISMATCH. 복구 성공만으로 완전성을 인정하지 않는다: 복구 결과에는 완전성 값이 없고, 완전성을 확인하지 않은 채
    넘기면 보고서에 LOCAL_ORDER_LOG_NOT_VERIFIED_COMPLETE와 BROKER_SNAPSHOT_INCOMPLETE가 남는다."""
    path = tmp_path / "orders.sqlite3"
    child = run_child("child_write_restart_journal", path)
    assert child.returncode == 0, child.stderr

    recovery = recover_order_journal(path)

    assert recovery.status.name == "RECOVERED" and not hasattr(recovery, "completeness")
    after = reconcile(list(recovery.order_evidence()), restart_snapshot())
    before = reconcile(restart_items(), restart_snapshot())
    assert after == before
    assert [(order.client_order_id, order.status) for order in after.orders] == [
        ("C-5", M.MATCH), ("C-6", M.UNVERIFIED), ("C-7", M.MISMATCH)]
    assert (after.status, after.reasons) == (M.MISMATCH, ("BROKER_SNAPSHOT_INCOMPLETE", "LOCAL_ORDER_LOG_NOT_VERIFIED_COMPLETE"))


def test_case_10_an_older_journal_copy_is_compared_not_trusted(tmp_path):
    """CASE 10. 입력: C-5 제출·접수 증거와 NORMAL 기록만 있을 때 Journal 파일 사본을 떠 둔다. 그 뒤 09:56 체결 +3 통보를 저장하고, 사본으로
    파일을 되돌린다 (로컬 검사로는 검출되지 않음). 판단 10:00. 더 최신의 브로커 보고: (a) C-5 PARTIALLY_FILLED, 누적 체결 3, 잔량 2,
    (b) 사본과 같은 ACCEPTED, 잔량 5.
    출력: 복구는 RECOVERED이고 체결 통보가 빠진다. (a) 비교 가능한 차이를 찾는다: 누적 체결 0 / 3 (+3), 잔량 5 / 2 (−3) → MISMATCH.
    (b) 주문은 MATCH이지만 보고서는 UNVERIFIED: 로컬 기록이 완전하다고 확인되지 않았고 (과거 사본인지 증명할 수 없음) 목록 완전성도
    선언되지 않았다. 정상 복구와 주문 일치만으로 계좌가 정상이라고 판정하지 않는다."""
    path = tmp_path / "orders.sqlite3"
    create_order_journal(path)
    append_to_order_journal(path, [*accepted_c5(), NORMAL_AT_0900])
    older = path.read_bytes()
    append_to_order_journal(path, [evidence("E-3", "C-5", 5, S.PARTIALLY_FILLED, K.FILL_NOTIFICATION, "09:56", filled=3)])
    path.write_bytes(older)

    recovery = recover_order_journal(path)

    assert recovery.status.name == "RECOVERED" and "TAMPER_RESISTANCE" in recovery.not_established
    restored = list(recovery.order_evidence())
    newer = reconcile(restored, snapshot(line("C-5", 5, S.PARTIALLY_FILLED, filled=3, remaining=2)))
    order = newer.order("C-5")
    assert (order.status, summary(order.field("filled_quantity"))[4], summary(order.field("remaining_quantity"))[4]) == (
        M.MISMATCH, 3, -3)
    same = reconcile(restored, snapshot(line("C-5", 5, S.ACCEPTED)))
    assert (same.order("C-5").status, same.status) == (M.MATCH, M.UNVERIFIED)
    assert "LOCAL_ORDER_LOG_NOT_VERIFIED_COMPLETE" in same.reasons


def test_account_and_contract_mixups_are_not_compared_across():
    """입력: (a) 다른 계좌(A2)의 Snapshot, (b) 로컬 C1의 C-5를 브로커가 C2로 보고, (c) 로컬 매수 +5를 브로커가 매도 −5로 보고, (d) C1·C2에
    주문이 하나씩 있고 브로커도 월물별로 같은 값을 보고.
    출력: (a) ValueError (계좌를 섞어 대조하지 않음). (b) CONTRACT_MISMATCH. (c) SIDE_MISMATCH와 수량 차이 −10. (d) 월물마다 따로
    비교해 둘 다 MATCH (월물을 합산하지 않음)."""
    items = accepted_c5()
    with pytest.raises(ValueError):
        reconcile(items, snapshot(line("C-5", 5, S.ACCEPTED), account_id="A2"))
    moved = reconcile(items, snapshot(line("C-5", 5, S.ACCEPTED, contract_id=C2))).order("C-5")
    assert (moved.status, moved.reasons) == (M.MISMATCH, ("CONTRACT_MISMATCH",))
    flipped = reconcile(items, snapshot(line("C-5", -5, S.ACCEPTED))).order("C-5")
    assert (flipped.reasons, flipped.field("quantity").difference) == (
        ("SIDE_MISMATCH", "ORDER_QUANTITY_MISMATCH", "REMAINING_QUANTITY_MISMATCH"), -10)

    both = items + [evidence("E-3", "C-6", 3, S.PENDING_SUBMIT, K.LOCAL_RECORD, "09:50", contract_id=C2),
                    evidence("E-4", "C-6", 3, S.ACCEPTED, K.REQUEST_RESPONSE, "09:51", contract_id=C2)]
    report = reconcile(both, snapshot(line("C-5", 5, S.ACCEPTED), line("C-6", 3, S.ACCEPTED, contract_id=C2)))
    assert [(order.client_order_id, order.status, order.field("contract_id").local_value) for order in report.orders] == [
        ("C-5", M.MATCH, C1), ("C-6", M.MATCH, C2)]


def test_identifier_links_are_checked_not_guessed():
    """입력: (a) 로컬 C-5의 Broker Order ID는 B-C-5인데 브로커는 C-5를 B-9로 보고, (b) Client Order ID 없이 B-C-5로만 보고,
    (c) Client Order ID 없이 B-77 +5를 보고하고 로컬에는 Broker Order ID를 모르는 UNKNOWN C-6 +5 (같은 월물)가 있음, (d) (c)와 같지만
    로컬에 연결할 후보가 없음 (완전한 목록).
    출력: (a) MISMATCH (BROKER_ORDER_ID_MISMATCH). (b) Broker Order ID로 연결하고 Client Order ID는 UNVERIFIED
    (CLIENT_ORDER_ID_NOT_REPORTED). (c) 수량이 같아도 추측해 잇지 않는다: B-77 줄과 C-6 모두 UNVERIFIED (BROKER_ORDER_NOT_LINKED).
    (d) B-77은 MISMATCH (ORDER_MISSING_LOCALLY)."""
    items = accepted_c5()
    wrong = reconcile(items, snapshot(line("C-5", 5, S.ACCEPTED, broker_id="B-9"))).order("C-5")
    assert (wrong.status, wrong.reasons) == (M.MISMATCH, ("BROKER_ORDER_ID_MISMATCH",))
    by_broker_id = reconcile(items, snapshot(line(None, 5, S.ACCEPTED, broker_id="B-C-5"))).order("C-5")
    assert (by_broker_id.status, by_broker_id.reasons) == (M.UNVERIFIED, ("CLIENT_ORDER_ID_NOT_REPORTED",))

    unknown_c6 = [evidence("E-3", "C-6", 5, S.PENDING_SUBMIT, K.LOCAL_RECORD, "09:52"),
                  evidence("E-4", "C-6", 5, S.UNKNOWN, K.LOCAL_RECORD, "09:54")]
    report = reconcile(items + unknown_c6, snapshot(line("C-5", 5, S.ACCEPTED), line(None, 5, S.ACCEPTED, broker_id="B-77"),
                                                    complete=True))
    assert [(order.client_order_id, order.broker_order_id, order.status, order.reasons) for order in report.orders] == [
        ("C-5", "B-C-5", M.MATCH, ()),
        ("C-6", None, M.UNVERIFIED, ("BROKER_ORDER_NOT_LINKED",)),
        (None, "B-77", M.UNVERIFIED, ("BROKER_ORDER_NOT_LINKED",)),
    ]
    alone = reconcile(items, snapshot(line("C-5", 5, S.ACCEPTED), line(None, 5, S.ACCEPTED, broker_id="B-77"), complete=True))
    assert [(order.broker_order_id, order.status, order.reasons) for order in alone.orders][1] == (
        "B-77", M.MISMATCH, ("ORDER_MISSING_LOCALLY",))


def test_local_record_newer_than_the_snapshot_is_not_a_match():
    """입력: 로컬 C-5는 09:51 접수 기록이 마지막. 브로커 Snapshot은 그보다 이른 09:50에 관측 (09:59 이용 가능). (a) 같은 값, (b) 잔량 2.
    출력: 기준 시각이 같지 않으므로 (R9-13) 같은 값도 MATCH가 아니라 UNVERIFIED (NOT_SAME_REFERENCE_TIME). 다른 값은 설명된 차이로
    보지 않고 MISMATCH (BR-10)."""
    items = accepted_c5()
    same = reconcile(items, snapshot(line("C-5", 5, S.ACCEPTED), observed="09:50")).order("C-5")
    assert same.status is M.UNVERIFIED and set(same.reasons) == {"NOT_SAME_REFERENCE_TIME"}
    differs = reconcile(items, snapshot(line("C-5", 5, S.ACCEPTED, remaining=2), observed="09:50")).order("C-5")
    assert differs.status is M.MISMATCH and differs.field("remaining_quantity").reason == "REMAINING_QUANTITY_MISMATCH"


@pytest.mark.parametrize("arrival", ["fill_after_fill", "fill_after_cancel_request"])
def test_local_events_after_the_snapshot_prevent_a_match_whatever_their_arrival_order(arrival):
    """검토 HIGH 회귀 (R9-13). 입력: C-5 +5 접수 (09:51). 완전하다고 선언한 계좌 주문 기록 Snapshot은 09:58 관측. 로컬 기록 완전성도
    확인됨. (a) 체결 A (누적 2)가 09:59에 발생해 09:59에 도착하고, 그보다 이른 09:57에 발생한 체결 B (누적 3)가 09:59:30에 늦게
    도착한다. Snapshot은 PARTIALLY_FILLED 누적 3, 잔량 2. (b) 09:59에 취소를 요청하고, 09:57에 발생한 체결 (누적 2)이 09:59:30에 늦게
    도착한다. Snapshot은 CANCEL_REQUESTED 누적 2, 잔량 3 (09:58의 취소 대기는 우리 요청일 수 없음).
    출력: 마지막으로 도착한 기록의 발생 시각(09:57)은 Snapshot보다 이르지만, 로컬 상태에는 Snapshot 뒤(09:59)의 사건이 들어 있다.
    같은 값이어도 같은 기준 시각의 비교가 아니므로 주문과 보고서 모두 MATCH가 아니라 UNVERIFIED (NOT_SAME_REFERENCE_TIME)다. 수정
    전에는 도착 순서만으로 보고서가 MATCH였다 (예: 로컬은 A·B로 3, 브로커는 B·C로 3인데 C를 받지 못한 경우를 숨김)."""
    if arrival == "fill_after_fill":
        later = [evidence("E-3", "C-5", 5, S.PARTIALLY_FILLED, K.FILL_NOTIFICATION, "09:59", filled=2),
                 evidence("E-4", "C-5", 5, S.PARTIALLY_FILLED, K.FILL_NOTIFICATION, "09:57", "09:59:30", filled=3)]
        broker_line = line("C-5", 5, S.PARTIALLY_FILLED, filled=3, remaining=2)
    else:
        later = [evidence("E-3", "C-5", 5, S.CANCEL_REQUESTED, K.LOCAL_RECORD, "09:59", broker_id="B-C-5"),
                 evidence("E-4", "C-5", 5, S.PARTIALLY_FILLED, K.FILL_NOTIFICATION, "09:57", "09:59:30", filled=2)]
        broker_line = line("C-5", 5, S.CANCEL_REQUESTED, filled=2, remaining=3)
    broker = dataclasses.replace(snapshot(broker_line, scope=SCOPE.ACCOUNT_ORDERS, complete=True), available_at=at("09:59:45"))

    report = reconcile(accepted_c5() + later, broker, completeness=COMPLETE)

    order = report.order("C-5")
    assert local(accepted_c5() + later).snapshot.entries[0].occurred_at == at("09:57")
    assert (order.status, order.reasons, report.status, report.reasons) == (
        M.UNVERIFIED, ("NOT_SAME_REFERENCE_TIME",), M.UNVERIFIED, ())


def replace_chain():
    """C-5 +5 접수 (B-1), 09:53 +3으로 정정 요청 (새 주문 C-5R), C-5R 접수 (Broker Order ID를 유지하는 정정이라 같은 B-1)."""
    return [
        evidence("E-1", "C-5", 5, S.PENDING_SUBMIT, K.LOCAL_RECORD, "09:50"),
        evidence("E-2", "C-5", 5, S.ACCEPTED, K.REQUEST_RESPONSE, "09:51", broker_id="B-1"),
        evidence("E-3", "C-5", 5, S.REPLACE_REQUESTED, K.LOCAL_RECORD, "09:53", broker_id="B-1", replacement=3),
        evidence("E-4", "C-5R", 3, S.PENDING_SUBMIT, K.LOCAL_RECORD, "09:53"),
        evidence("E-5", "C-5R", 3, S.ACCEPTED, K.REQUEST_RESPONSE, "09:54", broker_id="B-1"),
    ]


def test_broker_order_id_conflicts_are_reported_not_hidden():
    """검토 MEDIUM 회귀 (식별자 충돌, BR-4). 입력: (a) 로컬 C-5는 B-1로 접수, C-6은 Broker Order ID 없이 UNKNOWN. C-6 주문 조회 결과가
    C-6을 B-1로 보고. (b) 로컬 C-5는 B-1. 완전한 계좌 주문 기록이 B-1을 로컬에 없는 C-9로 보고. (c) 정정으로 C-5와 C-5R이 B-1을 함께
    가짐. 완전한 목록이 Client Order ID 없이 B-1 한 줄을 보고. (d) (c)와 같지만 목록이 B-1을 C-5R로 보고 (C-5는 목록에 없음).
    출력: (a) 같은 Broker Order ID를 두 주문이 가진다: C-5와 C-6 모두 MISMATCH (BROKER_ORDER_ID_CONFLICT). C-6은 UNKNOWN 상태도
    확인 불가로 남는다. (b) C-5는 "브로커에 없음"이 아니라 MISMATCH (BROKER_ORDER_ID_CONFLICT), C-9는 ORDER_MISSING_LOCALLY. (c) 그
    줄과 두 로컬 주문 모두 UNVERIFIED (BROKER_ORDER_NOT_LINKED): 어느 주문인지 고르지 않고, 브로커가 보고한 Broker Order ID의 주문을
    "브로커에 없음"이라고 하지 않는다. (d) C-5R은 비교되고 (MATCH), 정정으로 이어진 C-5는 충돌이 아니라 UNVERIFIED
    (BROKER_ORDER_NOT_LINKED)."""
    owner = [evidence("E-1", "C-5", 5, S.PENDING_SUBMIT, K.LOCAL_RECORD, "09:50"),
             evidence("E-2", "C-5", 5, S.ACCEPTED, K.REQUEST_RESPONSE, "09:51", broker_id="B-1")]
    unknown_c6 = [evidence("E-3", "C-6", 5, S.PENDING_SUBMIT, K.LOCAL_RECORD, "09:52"),
                  evidence("E-4", "C-6", 5, S.UNKNOWN, K.LOCAL_RECORD, "09:54")]
    query = snapshot(line("C-6", 5, S.ACCEPTED, broker_id="B-1"), scope=SCOPE.ORDER_QUERY, queried=("C-6",))
    shared = reconcile(owner + unknown_c6, query)
    assert [(order.client_order_id, order.status, order.reasons) for order in shared.orders] == [
        ("C-5", M.MISMATCH, ("BROKER_ORDER_ID_CONFLICT",)),
        ("C-6", M.MISMATCH, ("BROKER_ORDER_ID_CONFLICT", "LOCAL_STATUS_UNKNOWN")),
    ]
    assert summary(shared.order("C-6").field("broker_order_id")) == (None, "B-1", M.MISMATCH, "BROKER_ORDER_ID_CONFLICT", None)

    elsewhere = reconcile(owner, snapshot(line("C-9", 5, S.ACCEPTED, broker_id="B-1"), scope=SCOPE.ACCOUNT_ORDERS, complete=True))
    assert [(order.client_order_id, order.status, order.reasons) for order in elsewhere.orders] == [
        ("C-5", M.MISMATCH, ("BROKER_ORDER_ID_CONFLICT",)), ("C-9", M.MISMATCH, ("ORDER_MISSING_LOCALLY",))]

    unlinkable = reconcile(replace_chain(), snapshot(line(None, 3, S.ACCEPTED, broker_id="B-1"), scope=SCOPE.ACCOUNT_ORDERS,
                                                     complete=True))
    assert [(order.client_order_id, order.status, order.reasons) for order in unlinkable.orders] == [
        ("C-5", M.UNVERIFIED, ("BROKER_ORDER_NOT_LINKED",)),
        ("C-5R", M.UNVERIFIED, ("BROKER_ORDER_NOT_LINKED",)),
        (None, M.UNVERIFIED, ("BROKER_ORDER_NOT_LINKED",)),
    ]
    assert unlinkable.orders[2].fields == ()

    renamed = reconcile(replace_chain(), snapshot(line("C-5R", 3, S.ACCEPTED, broker_id="B-1"), scope=SCOPE.ACCOUNT_ORDERS,
                                                  complete=True))
    assert [(order.client_order_id, order.status, order.reasons) for order in renamed.orders] == [
        ("C-5", M.UNVERIFIED, ("BROKER_ORDER_NOT_LINKED",)), ("C-5R", M.MATCH, ())]


def test_unknown_statuses_cancels_and_unverified_orders_never_add_up_to_a_match():
    """검토 MEDIUM 회귀 (테스트 공백). 입력: 로컬 기록과 목록의 완전성이 모두 선언·확인된 상태에서 (a) 로컬 UNKNOWN과 브로커 UNKNOWN
    (번역할 수 없는 상태, BR-6), (b) 로컬 ACCEPTED와 브로커 UNKNOWN, (c) 로컬 +5 접수 뒤 확인된 취소 2 (ACCEPTED, 잔량 3)를 브로커가
    잔량 5로 보고, (d) 같은 주문을 브로커가 잔량 3으로 보고.
    출력: (a) 상태 UNVERIFIED (LOCAL_STATUS_UNKNOWN), (b) 상태 UNVERIFIED (BROKER_STATUS_UNKNOWN): UNKNOWN끼리 같아도 일치가 아니다.
    (a)(b)의 보고서는 보고서 수준 사유가 없어도 확인 불가 주문 때문에 UNVERIFIED다. (c) 기록된 잔량은 확인된 취소를 뺀 3이므로 잔량
    3 / 5 MISMATCH (차이 +2). (d) 잔량 3 / 3 MATCH."""
    unknown = reconcile(unknown_c5(), snapshot(line("C-5", 5, S.UNKNOWN, broker_id="B-77"), complete=True), completeness=COMPLETE)
    assert summary(unknown.order("C-5").field("status")) == ("UNKNOWN", "UNKNOWN", M.UNVERIFIED, "LOCAL_STATUS_UNKNOWN", None)
    assert (unknown.status, unknown.reasons) == (M.UNVERIFIED, ())
    untranslatable = reconcile(accepted_c5(), snapshot(line("C-5", 5, S.UNKNOWN), complete=True), completeness=COMPLETE)
    assert (untranslatable.order("C-5").status, untranslatable.order("C-5").reasons) == (M.UNVERIFIED, ("BROKER_STATUS_UNKNOWN",))
    assert (untranslatable.status, untranslatable.reasons) == (M.UNVERIFIED, ())

    reduced = accepted_c5() + [evidence("E-3", "C-5", 5, S.ACCEPTED, K.REQUEST_RESPONSE, "09:52", cancelled=2)]
    wider = reconcile(reduced, snapshot(line("C-5", 5, S.ACCEPTED, remaining=5), complete=True), completeness=COMPLETE)
    assert summary(wider.order("C-5").field("remaining_quantity")) == (3, 5, M.MISMATCH, "REMAINING_QUANTITY_MISMATCH", 2)
    same = reconcile(reduced, snapshot(line("C-5", 5, S.ACCEPTED, remaining=3), complete=True), completeness=COMPLETE)
    assert (same.order("C-5").status, same.status) == (M.MATCH, M.MATCH)


def test_pending_local_request_is_not_confirmed_by_the_snapshot():
    """입력: 로컬 C-5 +5 접수 뒤 09:53 취소 요청 (CANCEL_REQUESTED). 브로커 보고: (a) 아직 ACCEPTED 잔량 5, (b) 계좌 주문 기록에
    CANCELLED 잔량 0.
    출력: (a) 상태는 UNVERIFIED (LOCAL_REQUEST_PENDING): 취소 요청의 결과를 Snapshot으로 확정하지 않는다. (b) 잔량 5 / 0 MISMATCH.
    어느 경우에도 로컬 주문은 CANCEL_REQUESTED 그대로다 (대조로 상태를 고치지 않음)."""
    items = accepted_c5() + [evidence("E-3", "C-5", 5, S.CANCEL_REQUESTED, K.LOCAL_RECORD, "09:53", broker_id="B-C-5")]
    pending = reconcile(items, snapshot(line("C-5", 5, S.ACCEPTED))).order("C-5")
    assert (pending.status, pending.reasons) == (M.UNVERIFIED, ("LOCAL_REQUEST_PENDING",))
    cancelled = reconcile(items, snapshot(line("C-5", 5, S.CANCELLED, remaining=0), scope=SCOPE.ACCOUNT_ORDERS)).order("C-5")
    assert (cancelled.status, cancelled.reasons) == (M.MISMATCH, ("REMAINING_QUANTITY_MISMATCH", "LOCAL_REQUEST_PENDING"))
    assert cancelled.local.status is S.CANCEL_REQUESTED


def test_p6_and_p8_stay_blocked_after_reconciliation():
    """회귀 (Slice 3 P6·P8). 입력: P6: UNKNOWN +5에 체결 +3 통보만 (체결 장부 X-1 +3), 브로커 보고 PARTIALLY_FILLED 누적 체결 3, 잔량 2.
    P8: 브로커 확인 계좌의 UNKNOWN +5에 시뮬레이터 CANCELLED 조회 결과 (REJECTED 증거), 브로커 보고 ACCEPTED 잔량 5. 판단 10:00.
    출력: 두 경우 모두 수량 필드는 MATCH, 주문은 UNVERIFIED (LOCAL_STATUS_UNKNOWN). L3 판정은 대조 전과 같다: P6 최악 경우 롱 3 + 2 = 5
    (브로커가 보고한 잔량 2로 줄지 않음), P8 REJECTED 증거 유지. 모든 월물 BLOCKED (P8은 ORDER_EVIDENCE_CONFLICT 포함)."""
    p6 = unknown_c5() + [evidence("E-3", "C-5", 5, S.PARTIALLY_FILLED, K.FILL_NOTIFICATION, "09:57", "09:58", filled=3)]
    p8 = unknown_c5() + [evidence("E-9", "C-5", 5, S.CANCELLED, K.STATUS_QUERY_RESPONSE, "09:57", source=SRC.SIMULATOR, cancelled=5,
                                  requested="09:56")]
    cases = [
        (p6, [make_fill("X-1", "C-5", 3, "09:57")], line("C-5", 5, S.PARTIALLY_FILLED, filled=3, remaining=2), ("UNKNOWN_ORDER_PRESENT",)),
        (p8, [], line("C-5", 5, S.ACCEPTED), ("UNKNOWN_ORDER_PRESENT", "ORDER_EVIDENCE_CONFLICT")),
    ]
    for items, fills, broker_line, blocking in cases:
        before = gate(items, "10:00", targets={C1: 10, C2: 0}, fills=fills)
        order = reconcile(items, snapshot(broker_line)).order("C-5")
        assert [order.field(name).status for name in ("quantity", "filled_quantity", "remaining_quantity")] == [M.MATCH] * 3
        assert order.status is M.UNVERIFIED and "LOCAL_STATUS_UNKNOWN" in order.reasons
        after = gate(items, "10:00", targets={C1: 10, C2: 0}, fills=fills)
        assert after == before and after.risk.risk.view(C1).worst_case.worst_long_before == 5
        assert_all_blocked(after, *blocking)
    assert gate(p8, "10:00", targets={C1: 10, C2: 0}).evidence.assessments[-1].disposition is D.REJECTED


def test_reconcile_rejects_inputs_it_cannot_compare():
    """입력: 시간대 없는 판단 시각, 판단 시각이 다른 로컬 Snapshot, 증거 Snapshot이 아닌 로컬 값, 브로커 Snapshot이 아닌 값.
    출력: 모두 ValueError (다른 시점이나 다른 종류의 기록을 섞어 대조하지 않음)."""
    current = local(accepted_c5())
    broker = snapshot(line("C-5", 5, S.ACCEPTED))
    bad = [
        lambda: reconcile_order_snapshot(current, broker, datetime(2026, 10, 21, 10, 0)),
        lambda: reconcile_order_snapshot(current, broker, at("10:01")),
        lambda: reconcile_order_snapshot(current.snapshot, broker, at("10:00")),
        lambda: reconcile_order_snapshot(current, broker.orders, at("10:00")),
    ]
    for call in bad:
        with pytest.raises(ValueError):
            call()
