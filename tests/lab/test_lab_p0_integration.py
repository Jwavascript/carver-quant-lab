"""P0 종료 통합 검증 (P0-03C Slice 6): 기존 공개 API를 그대로 이어 붙인 두 개의 독립 수직 시나리오.

TRACK A (가상 선물): 기준 포지션·진행 중 주문 → 주문 후보 → 최악 경우 노출 → PIT 주문 Snapshot → UNKNOWN 증거 판정 → L3 안전 게이트 →
Journal 저장·재시작 복구 → 읽기 전용 주문 대조. TRACK B (가상 ETF): 입금 → 체결 → 실제 포지션 → 현금 이벤트 → NAV → 투자 손익.
두 TRACK은 서로 연결하지 않는다: 선물 주문·위험 경로는 `FuturesContractSpec` 장부만 받고, ETF 현금·NAV 경로는 별도이며, 선물 일일
정산·증거금과 계좌 NAV의 연결은 구현되어 있지 않다 (P0-03B 명세 §9). 새 금융 공식이나 정책을 만들지 않고, 기대값은 저장소 밖
독립 산술(Fraction)로 먼저 확인했다. 한도·가격·승수·Trading State 기록·브로커 Snapshot은 테스트 입력이며 운영 정책이 아니다.
Journal 파일은 pytest 임시 경로에만 만든다. 실제 브로커·네트워크·주문 전송은 없다.
"""

import dataclasses
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from carver_quant.lab.accounting.cash_ledger import CashIntegrityError, CashVerdict
from carver_quant.lab.accounting.etf_account import (
    PostingOutcome,
    account_cash,
    account_nav,
    account_position,
    fill_cause_ref,
    open_etf_account,
    record_cash_event,
    record_etf_fill,
)
from carver_quant.lab.accounting.fill_ledger import FillIntegrityError, FillLedger, FillVerdict, apply_fill
from carver_quant.lab.accounting.l3_gate import L3_GATE_NOT_CHECKED, CandidateRiskEffect, L3GateStatus, assess_l3_gate_as_of
from carver_quant.lab.accounting.order_projection import CandidateStatus
from carver_quant.lab.accounting.order_reconciliation import reconcile_order_snapshot
from carver_quant.lab.accounting.order_snapshot import OrderLogCompleteness
from carver_quant.lab.accounting.pretrade_risk import REMAINING_PRE_SUBMISSION_STEPS, RiskCheckStatus
from carver_quant.lab.accounting.unknown_resolution import EvidenceDisposition, orders_from_evidence_as_of
from carver_quant.lab.accounting.valuation import NAV_OPEN_POLICIES, NavStatus, nav_change
from carver_quant.lab.adapters.order_journal import (
    JOURNAL_RECOVERY_NOT_ESTABLISHED,
    JournalRecoveryError,
    JournalRecoveryStatus,
    append_to_order_journal,
    create_order_journal,
    recover_order_journal,
)
from carver_quant.lab.domain.cash import CashEvent, CashEventConfirmation, CashEventKind
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
from carver_quant.lab.domain.records import (
    EtfSpec,
    FillKey,
    FillOrigin,
    FillRecord,
    FuturesContractSpec,
    PositionBaseline,
    ValuationPrice,
)
from carver_quant.lab.domain.risk import ContractMultiplier, ExposureLimit, TradingState
from carver_quant.lab.domain.trading_state import TradingStateRecord

UTC = timezone.utc
S = OrderStatus
K = OrderEvidenceKind
SRC = OrderStatusSource
G = L3GateStatus
R = JournalRecoveryStatus
M = ReconciliationStatus
C1 = "FUT.ALPHA.C1"
C2 = "FUT.ALPHA.C2"
T0 = datetime(2026, 10, 21, 0, 0, tzinfo=UTC)
COMPLETE = OrderLogCompleteness.VERIFIED_COMPLETE
UNVERIFIED = OrderLogCompleteness.UNVERIFIED
EVENT_KIND = {SRC.SYSTEM: OrderEventKind.SYSTEM_RECORD, SRC.BROKER: OrderEventKind.BROKER_REPORT, SRC.SIMULATOR: OrderEventKind.SIMULATOR_REPORT}


# ---------------------------------------------------------------- TRACK A fixtures (가상 선물, 2026-10-21 UTC)

def at(clock):
    """"HH:MM" 또는 "HH:MM:SS"의 2026-10-21 UTC 시각."""
    return datetime(2026, 10, 21, *(int(part) for part in clock.split(":")), tzinfo=UTC)


def evidence(event_id, client_order_id, quantity, status, kind, occurred, available=None, *, source=None, filled=0, cancelled=0,
             broker_id="default", requested=None):
    source = source or (SRC.SYSTEM if kind is K.LOCAL_RECORD else SRC.BROKER)
    if broker_id == "default":
        broker_id = None if source is SRC.SYSTEM else "B-" + client_order_id
    record = OrderRecord(
        account_id="A1",
        client_order_id=client_order_id,
        broker_order_id=broker_id,
        contract_id=C1,
        quantity=quantity,
        status=status,
        filled_quantity=filled,
        cancelled_quantity=cancelled,
        replacement_quantity=None,
        replacement_client_order_id=None,
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


def futures_contract(contract_id):
    return FuturesContractSpec(contract_id=contract_id, instrument_id="FUT.ALPHA", currency="USD", multiplier="10", lot_size=1)


def futures_fill(fill_id, client_order_id, quantity, fill_at):
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
    ledger = FillLedger.empty(account_id="A1", contracts=(futures_contract(C1), futures_contract(C2)))
    for fill in fills:
        ledger = apply_fill(ledger, fill).ledger
    return ledger


def risk_inputs(decision, c1_limit):
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
        limits={contract_id: ExposureLimit(contract_id=contract_id, currency="USD",
                                           max_exposure=c1_limit if contract_id == C1 else "20000", source_ref="test:limit")
                for contract_id in (C1, C2)},
    )


def gate(items, decision, *, targets, c1=0, fills=(), records=(NORMAL_AT_0900,), completeness=COMPLETE, c1_limit="20000"):
    return assess_l3_gate_as_of(
        baseline=PositionBaseline(account_id="A1", as_of=T0, quantities={C1: c1, C2: 0}, verification_ref="fixture:verified"),
        ledger=ledger_with(*fills),
        evidence=items,
        confirming_source=SRC.BROKER,
        completeness=completeness,
        completeness_ref="fixture:complete-log" if completeness is COMPLETE else None,
        targets=targets,
        decision_at=at(decision),
        trading_state=TradingState.NORMAL,
        trading_state_records=records,
        **risk_inputs(at(decision), c1_limit),
    )


def assert_all_blocked(report, *reasons):
    for view in report.views:
        assert view.status is G.BLOCKED
        for reason in reasons:
            assert reason in view.blocking_reasons


def open_buy_c7():
    """실제 포지션 +3(검증된 기준 포지션) 위에 진행 중인 매수 +7: 09:40 제출, 09:41 브로커 접수 (B-C-7)."""
    return [
        evidence("E-71", "C-7", 7, S.PENDING_SUBMIT, K.LOCAL_RECORD, "09:40"),
        evidence("E-72", "C-7", 7, S.ACCEPTED, K.REQUEST_RESPONSE, "09:41"),
    ]


def unknown_c5_items():
    """매수 +5: 09:50 제출, 09:55 응답 timeout으로 UNKNOWN, 09:57 체결 +3 통보(09:58 이용 가능), 10:01 요청한 상태 조회 결과
    PARTIALLY_FILLED 누적 3 (10:02 관측)이 10:20에야 이용 가능."""
    return [
        evidence("E-1", "C-5", 5, S.PENDING_SUBMIT, K.LOCAL_RECORD, "09:50"),
        evidence("E-2", "C-5", 5, S.UNKNOWN, K.LOCAL_RECORD, "09:55"),
        evidence("E-3", "C-5", 5, S.PARTIALLY_FILLED, K.FILL_NOTIFICATION, "09:57", "09:58", filled=3),
        evidence("E-4", "C-5", 5, S.PARTIALLY_FILLED, K.STATUS_QUERY_RESPONSE, "10:02", "10:20", filled=3, requested="10:01"),
    ]


UNKNOWN_C5_FILLS = (futures_fill("X-1", "C-5", 3, "09:57"),)


def broker_snapshot(*orders, observed="09:58", available="09:59", source=SRC.BROKER):
    return BrokerOrderSnapshot(
        snapshot_id="S-1",
        account_id="A1",
        source=source,
        scope=BrokerSnapshotScope.OPEN_ORDERS,
        queried_client_order_ids=(),
        completeness=BrokerSnapshotCompleteness.UNVERIFIED,
        completeness_ref=None,
        observed_at=at(observed),
        available_at=at(available),
        orders=tuple(orders),
    )


def broker_line(client_order_id, quantity, status, *, filled=0, remaining=None):
    return BrokerOrderReport(client_order_id=client_order_id, broker_order_id="B-" + client_order_id, contract_id=C1,
                             quantity=quantity, filled_quantity=filled,
                             remaining_quantity=quantity - filled if remaining is None else remaining, status=status)


def raw_sql(path, *statements):
    """저장소 함수를 거치지 않고 Journal 파일을 직접 바꾼다 (손상·변경 주입)."""
    connection = sqlite3.connect(path, autocommit=True)
    try:
        for statement in statements:
            connection.execute(statement)
    finally:
        connection.close()


CHILD_MAIN = (
    "import importlib.util, sys\n"
    "spec = importlib.util.spec_from_file_location('p0_integration_restart_case', sys.argv[1])\n"
    "module = importlib.util.module_from_spec(spec)\n"
    "spec.loader.exec_module(module)\n"
    "getattr(module, sys.argv[2])(*sys.argv[3:])\n"
)


def run_child(function_name, *arguments):
    """이 파일을 새 Python 프로세스에서 불러 함수 하나를 실행한다 (재시작 전의 프로세스)."""
    return subprocess.run([sys.executable, "-W", "error", "-c", CHILD_MAIN, __file__, function_name, *map(str, arguments)],
                          capture_output=True, text=True, timeout=300, check=False)


def child_write_track_a_journal(path):
    """A5 자식 프로세스: UNKNOWN 주문 증거와 NORMAL·HALTED 기록을 Journal에 저장하고 정상 종료한다."""
    create_order_journal(path)
    append_to_order_journal(path, [*unknown_c5_items(), NORMAL_AT_0900, HALTED_AT_0955])


# ---------------------------------------------------------------- TRACK A


def test_a1_worst_case_exposure_over_the_explicit_limit_is_blocked():
    """A1. 입력: 실제 포지션 C1 +3 (검증된 기준), 진행 중 매수 +7 (ACCEPTED), 목표 +15 → 신규 매수 후보 +5. 참조 가격 100pt, 승수 10,
    C1 한도 12,000 USD (테스트 입력). 로컬 기록 완전성 확인, 09:00 NORMAL 기록. 판단 10:00.
    출력: 신규 주문 전 최악 롱 10 (3 + 7), 신규 주문 포함 15, 노출 10,000 → 15,000 USD, LIMIT_EXCEEDED. 후보는 위험 증가이며 L3 게이트에서
    C1 BLOCKED (LIMIT_EXCEEDED). 후보는 체결이 아니다: 실제 수량은 3 그대로다. C2는 따로 판정한다."""
    report = gate(open_buy_c7(), "10:00", targets={C1: 15, C2: 0}, c1=3, c1_limit="12000")

    risk = report.risk.risk.view(C1)
    worst = risk.worst_case
    assert (worst.actual_quantity, worst.open_buy_quantity, worst.candidate_quantity) == (3, 7, 5)
    assert (worst.worst_long_before, worst.worst_long_after) == (10, 15)
    assert (risk.exposure_before, risk.exposure_after, risk.risk_status) == (Decimal("10000"), Decimal("15000"), RiskCheckStatus.LIMIT_EXCEEDED)
    view = report.view(C1)
    assert (view.candidate_quantity, view.candidate_effect, view.status) == (5, CandidateRiskEffect.RISK_INCREASING, G.BLOCKED)
    assert "LIMIT_EXCEEDED" in view.blocking_reasons
    assert report.risk.risk.view(C2).worst_case.worst_long_before == 0


def test_a2_within_the_limit_is_not_a_submission_approval():
    """A2. 입력: A1과 같고 C1 한도만 20,000 USD.
    출력: 노출 15,000 USD로 WITHIN_LIMIT이고 로컬 후보 검사도 LOCAL_VALID, 게이트 C1은 NO_BLOCK_FOUND다. 그래도 승인 상태는 없다:
    게이트·위험 판정의 값은 BLOCKED / NOT_ASSESSABLE / NO_BLOCK_FOUND, WITHIN_LIMIT / LIMIT_EXCEEDED / NOT_ASSESSABLE뿐이고, 결과에는
    남은 제출 전 단계(L1 다른 지표, L2 정책, 검증된 위험 축소, L3 상태, 브로커 제출 단계)와 게이트가 확인하지 않은 항목(브로커 대조,
    제출 단계, 증거 진위 등)이 그대로 남는다. 주문을 보내는 기능은 호출되지도, 존재하지도 않는다."""
    report = gate(open_buy_c7(), "10:00", targets={C1: 15, C2: 0}, c1=3, c1_limit="20000")

    risk = report.risk.risk.view(C1)
    assert (risk.exposure_after, risk.risk_status, risk.local_status) == (Decimal("15000"), RiskCheckStatus.WITHIN_LIMIT,
                                                                          CandidateStatus.LOCAL_VALID)
    assert risk.remaining_steps == REMAINING_PRE_SUBMISSION_STEPS
    assert {"L2_POLICY_DECISION", "L3_TRADING_STATE_GATE", "BROKER_SUBMISSION_STEPS"} <= set(risk.remaining_steps)
    assert report.view(C1).status is G.NO_BLOCK_FOUND
    assert set(L3_GATE_NOT_CHECKED) <= set(report.not_checked)
    assert {"BROKER_RECONCILIATION", "BROKER_SUBMISSION_STEPS", "EVIDENCE_AUTHENTICITY"} <= set(report.not_checked)
    assert {status.value for status in G} == {"BLOCKED", "NOT_ASSESSABLE", "NO_BLOCK_FOUND"}
    assert {status.value for status in RiskCheckStatus} == {"WITHIN_LIMIT", "LIMIT_EXCEEDED", "NOT_ASSESSABLE"}


def test_a3_unknown_order_stays_blocked_through_partial_and_late_evidence():
    """A3. 입력: 새 계좌 (기준 0). 매수 +5가 09:55 UNKNOWN. 09:57 체결 +3 통보 (체결 장부 X-1 +3). 10:01에 요청한 상태 조회 결과
    (PARTIALLY_FILLED 누적 3)가 10:20에야 이용 가능. 판단 10:00과 10:30, 목표 C1 +10. Trading State 기록 (a) 09:00 NORMAL, (b) 09:00 NORMAL과
    09:55 HALTED.
    출력: 10:00: 체결 통보는 FILLS_ONLY이고 주문은 UNKNOWN (누적 3), 늦은 조회는 이용 가능하지 않아 쓰지 않는다. 최악 롱 3 + 2 = 5, 노출
    5,000 USD, 후보는 만들지 않고 (UNKNOWN), 모든 월물 BLOCKED (UNKNOWN_ORDER_PRESENT). 10:10: 조회는 이미 관측(10:02)되었지만 아직 이용
    가능하지 않아 늦은 사건으로 남고 주문은 UNKNOWN, BLOCKED (검토 MEDIUM 회귀: 발생 시각이 아니라 이용 가능 시각으로 거른다).
    10:30: 조회 결과로 PARTIALLY_FILLED (남은 2)가 되어도 최악 롱 5 그대로이고, UNKNOWN 전의 NORMAL 기록으로는 풀리지 않아 BLOCKED
    (UNKNOWN_RESOLVED_AFTER_TRADING_STATE_RECORD). (b)는 두 시각 모두 BLOCKED (TRADING_STATE_HALTED). 09:55 HALTED 기록이 10:05에야
    이용 가능하면 10:00 판단에는 쓰지 않는다 (적용 상태 NORMAL, 늦은 기록으로 남음)."""
    items = unknown_c5_items()

    early = gate(items, "10:00", targets={C1: 10, C2: 0}, fills=UNKNOWN_C5_FILLS)

    assert [(a.event_id, a.disposition) for a in early.evidence.assessments][:3] == [
        ("E-1", EvidenceDisposition.USED), ("E-2", EvidenceDisposition.USED), ("E-3", EvidenceDisposition.FILLS_ONLY)]
    assert "E-4" not in {assessment.event_id for assessment in early.evidence.usable_assessments()}
    record = early.evidence.snapshot.records()[0]
    assert (record.status, record.filled_quantity) == (S.UNKNOWN, 3)
    risk = early.risk.risk.view(C1)
    assert (risk.worst_case.actual_quantity, risk.worst_case.worst_long_before, risk.exposure_before) == (3, 5, Decimal("5000"))
    assert (risk.local_status, risk.worst_case.candidate_quantity) == (CandidateStatus.BLOCKED, None)
    assert_all_blocked(early, "UNKNOWN_ORDER_PRESENT")

    mid = gate(items, "10:10", targets={C1: 10, C2: 0}, fills=UNKNOWN_C5_FILLS)
    assert mid.evidence.snapshot.records()[0].status is S.UNKNOWN and "E-4" in mid.evidence.snapshot.late_event_ids
    assert_all_blocked(mid, "UNKNOWN_ORDER_PRESENT")
    late_halt = dataclasses.replace(HALTED_AT_0955, data_available_at=at("10:05"))
    not_yet = gate(items, "10:00", targets={C1: 10, C2: 0}, fills=UNKNOWN_C5_FILLS, records=(NORMAL_AT_0900, late_halt))
    assert (not_yet.trading_state_applied, not_yet.late_state_record_ids) == (TradingState.NORMAL, ("TS-2",))

    late = gate(items, "10:30", targets={C1: 10, C2: 0}, fills=UNKNOWN_C5_FILLS)
    record = late.evidence.snapshot.records()[0]
    assert (record.status, record.filled_quantity) == (S.PARTIALLY_FILLED, 3)
    assert late.risk.risk.view(C1).worst_case.worst_long_before == 5
    assert_all_blocked(late, "UNKNOWN_RESOLVED_AFTER_TRADING_STATE_RECORD")
    for decision in ("10:00", "10:30"):
        assert_all_blocked(gate(items, decision, targets={C1: 10, C2: 0}, fills=UNKNOWN_C5_FILLS,
                                records=(NORMAL_AT_0900, HALTED_AT_0955)), "TRADING_STATE_HALTED")


def test_a4_simulator_cancel_does_not_normalize_a_broker_unknown():
    """A4. 입력: 브로커 확인 계좌의 매수 +5가 09:55 UNKNOWN. 09:57 시뮬레이터 출처의 CANCELLED 조회 결과 (09:56 요청). 판단 10:00, 목표 +10.
    출력: 시뮬레이터 보고는 REJECTED (SOURCE_MISMATCH)로 보존되고 쓰지 않는다. 주문은 UNKNOWN, 최악 롱 5, 노출 5,000 USD (0이 아님).
    모든 월물 BLOCKED (UNKNOWN_ORDER_PRESENT, ORDER_EVIDENCE_CONFLICT). 자동 정상화 없음."""
    items = unknown_c5_items()[:2] + [evidence("E-9", "C-5", 5, S.CANCELLED, K.STATUS_QUERY_RESPONSE, "09:57", source=SRC.SIMULATOR,
                                               cancelled=5, requested="09:56")]

    report = gate(items, "10:00", targets={C1: 10, C2: 0})

    rejected = report.evidence.assessments[-1]
    assert (rejected.event_id, rejected.disposition, rejected.reasons) == ("E-9", EvidenceDisposition.REJECTED, ("SOURCE_MISMATCH",))
    assert report.evidence.snapshot.records()[0].status is S.UNKNOWN
    view = report.risk.risk.view(C1)
    assert (view.worst_case.worst_long_before, view.exposure_before) == (5, Decimal("5000"))
    assert_all_blocked(report, "UNKNOWN_ORDER_PRESENT", "ORDER_EVIDENCE_CONFLICT")


def test_a5_journal_restart_reproduces_pit_risk_and_gate(tmp_path):
    """A5. 입력: 자식 프로세스가 A3의 증거와 09:00 NORMAL·09:55 HALTED 기록을 Journal에 저장하고 끝난다. 이 프로세스에서 복구해 판단
    10:00과 10:30의 PIT 주문 Snapshot·위험·L3를 다시 계산한다.
    출력: RECOVERED, 복구 기록은 저장한 값·순서 그대로. 두 판단의 L3 보고서(증거 판정, PIT 위험 결과 포함)가 재시작 전과 같다. 10:00에는
    UNKNOWN이 남고, 두 시각 모두 HALTED가 적용되어 BLOCKED. 복구 결과에는 완전성 값이 없고 (확인하지 않은 항목에 ORDER_LOG_COMPLETENESS),
    완전성을 확인하지 않은 채 넘기면 게이트에 ORDER_LOG_NOT_VERIFIED_COMPLETE가 남는다."""
    path = tmp_path / "orders.sqlite3"
    child = run_child("child_write_track_a_journal", path)
    assert child.returncode == 0, child.stderr

    recovery = recover_order_journal(path)

    assert recovery.status is R.RECOVERED
    assert recovery.order_evidence() == tuple(unknown_c5_items())
    assert recovery.trading_state_records() == (NORMAL_AT_0900, HALTED_AT_0955)
    for decision in ("10:00", "10:30"):
        after = gate(list(recovery.order_evidence()), decision, targets={C1: 10, C2: 0}, fills=UNKNOWN_C5_FILLS,
                     records=recovery.trading_state_records())
        assert after == gate(unknown_c5_items(), decision, targets={C1: 10, C2: 0}, fills=UNKNOWN_C5_FILLS,
                             records=(NORMAL_AT_0900, HALTED_AT_0955))
        assert after.trading_state_applied is TradingState.HALTED
        assert_all_blocked(after, "TRADING_STATE_HALTED")
    assert gate(list(recovery.order_evidence()), "10:00", targets={C1: 10, C2: 0}, fills=UNKNOWN_C5_FILLS,
                records=recovery.trading_state_records()).evidence.snapshot.records()[0].status is S.UNKNOWN
    assert not hasattr(recovery, "completeness") and "ORDER_LOG_COMPLETENESS" in recovery.not_established
    honest = gate(list(recovery.order_evidence()), "10:00", targets={C1: 10, C2: 0}, fills=UNKNOWN_C5_FILLS,
                  records=recovery.trading_state_records(), completeness=UNVERIFIED)
    assert all("ORDER_LOG_NOT_VERIFIED_COMPLETE" in view.unassessable_reasons for view in honest.views)


def test_a6_reconciliation_reports_the_mismatch_and_changes_nothing():
    """A6. 입력: (a) 로컬 매수 +5 접수 (09:51, B-C-5), 미체결 잔량 5. 브로커 미체결 목록 (09:58 관측)은 잔량 2. (b) A3의 UNKNOWN 계좌
    (HALTED 기록 포함)를 브로커가 PARTIALLY_FILLED 누적 3, 잔량 2로 보고. 판단 10:00.
    출력: (a) MISMATCH, 잔량 차이 −3, 누적 체결 0 / 0 MATCH (체결 +3을 추정하지 않음). 대조 전후 L3 판정이 같고 실제 수량 0 그대로.
    (b) 수량은 같아도 UNKNOWN이라 주문 UNVERIFIED이고, L3는 그대로 BLOCKED (UNKNOWN_ORDER_PRESENT, TRADING_STATE_HALTED)다. 대조
    결과는 L3 상태 전이에 연결되어 있지 않으므로 게이트는 계속 브로커 대조를 확인하지 않은 항목으로 싣고, 대조 결과 자체도 UNKNOWN 해소와
    Trading State 해제를 확인하지 않은 항목으로 싣는다. 대조 결과의 값은 MATCH / MISMATCH / UNVERIFIED뿐이며 실행 승인 결과는 없다."""
    accepted = [evidence("E-1", "C-5", 5, S.PENDING_SUBMIT, K.LOCAL_RECORD, "09:50"),
                evidence("E-2", "C-5", 5, S.ACCEPTED, K.REQUEST_RESPONSE, "09:51")]
    before = gate(accepted, "10:00", targets={C1: 5, C2: 0})
    local = orders_from_evidence_as_of(accepted, at("10:00"), account_id="A1", confirming_source=SRC.BROKER, completeness=UNVERIFIED)

    report = reconcile_order_snapshot(local, broker_snapshot(broker_line("C-5", 5, S.ACCEPTED, remaining=2)), at("10:00"))

    order = report.order("C-5")
    remaining, filled = order.field("remaining_quantity"), order.field("filled_quantity")
    assert (order.status, remaining.local_value, remaining.broker_value, remaining.difference) == (M.MISMATCH, 5, 2, -3)
    assert (filled.local_value, filled.broker_value, filled.status) == (0, 0, M.MATCH)
    after = gate(accepted, "10:00", targets={C1: 5, C2: 0})
    assert after == before and after.risk.risk.view(C1).worst_case.actual_quantity == 0

    halted_items, halted_records = unknown_c5_items(), (NORMAL_AT_0900, HALTED_AT_0955)
    halted_before = gate(halted_items, "10:00", targets={C1: 10, C2: 0}, fills=UNKNOWN_C5_FILLS, records=halted_records)
    unknown_local = orders_from_evidence_as_of(halted_items, at("10:00"), account_id="A1", confirming_source=SRC.BROKER,
                                               completeness=UNVERIFIED)
    unknown_report = reconcile_order_snapshot(
        unknown_local, broker_snapshot(broker_line("C-5", 5, S.PARTIALLY_FILLED, filled=3, remaining=2)), at("10:00"))
    unknown_order = unknown_report.order("C-5")
    assert [unknown_order.field(name).status for name in ("quantity", "filled_quantity", "remaining_quantity")] == [M.MATCH] * 3
    assert unknown_order.status is M.UNVERIFIED and "LOCAL_STATUS_UNKNOWN" in unknown_order.reasons
    halted_after = gate(halted_items, "10:00", targets={C1: 10, C2: 0}, fills=UNKNOWN_C5_FILLS, records=halted_records)
    assert halted_after == halted_before
    assert_all_blocked(halted_after, "UNKNOWN_ORDER_PRESENT", "TRADING_STATE_HALTED")
    assert "BROKER_RECONCILIATION" in halted_after.not_checked
    assert {"UNKNOWN_RESOLUTION", "TRADING_STATE_RELEASE", "ACTUAL_POSITION"} <= set(unknown_report.not_established)
    assert {status.value for status in M} == {"MATCH", "MISMATCH", "UNVERIFIED"}


def damage(path, kind):
    """A7 손상 주입: 내용 변경(CORRUPT), UNKNOWN 항목 삭제(INCOMPLETE), 같은 ID의 다른 내용 저장(CONFLICT), schema version 2."""
    if kind == "payload_changed":
        raw_sql(path, "UPDATE journal_entries SET payload = replace(payload, '\"quantity\":5', '\"quantity\":4') WHERE seq = 2")
    elif kind == "unknown_entry_deleted":
        raw_sql(path, "DELETE FROM journal_entries WHERE seq = 2")
    elif kind == "conflicting_record":
        original = unknown_c5_items()[1]
        changed = dataclasses.replace(original, event=dataclasses.replace(original.event, available_at=at("09:56")))
        append_to_order_journal(path, [changed])
    else:
        raw_sql(path, "PRAGMA user_version = 2")


@pytest.mark.parametrize("kind, status", [
    ("payload_changed", R.CORRUPT),
    ("unknown_entry_deleted", R.INCOMPLETE),
    ("conflicting_record", R.CONFLICT),
    ("unsupported_version", R.UNSUPPORTED_VERSION),
])
def test_a7_damaged_journals_never_feed_the_gate(tmp_path, kind, status):
    """A7. 입력: A5와 같은 Journal을 (a) 내용 변경, (b) UNKNOWN 항목 삭제, (c) 같은 사건 ID의 다른 내용 저장, (d) schema version 2로 바꾼다.
    출력: RECOVERED로 오인하지 않는다 (CORRUPT / INCOMPLETE / CONFLICT / UNSUPPORTED_VERSION과 사유). 기록을 꺼내면 JournalRecoveryError라
    복구 실패가 정상 주문 상태나 정상 게이트 입력으로 바뀌지 않는다 (특히 UNKNOWN이 빠진 기록으로 게이트를 계산할 수 없다)."""
    path = tmp_path / "orders.sqlite3"
    create_order_journal(path)
    append_to_order_journal(path, [*unknown_c5_items(), NORMAL_AT_0900, HALTED_AT_0955])
    damage(path, kind)

    recovery = recover_order_journal(path)

    assert recovery.status is status and recovery.reasons
    for accessor in (recovery.order_evidence, recovery.trading_state_records, recovery.order_events):
        with pytest.raises(JournalRecoveryError):
            accessor()


def test_a7_an_older_journal_copy_is_indistinguishable_locally_but_never_passes(tmp_path):
    """A7 한계. 입력: 제출 기록(PENDING_SUBMIT +5)과 NORMAL 기록만 있을 때 사본을 떠 두고, UNKNOWN과 HALTED 기록을 저장한 뒤 사본으로
    되돌린다. 판단 10:00, 목표 +10.
    출력: 로컬 검사로는 구분할 수 없어 RECOVERED이고 UNKNOWN·HALTED가 빠진다 (위변조·이전 사본 방지는 확인하지 않는 항목). 그래서
    완전성은 확인되지 않은 값으로 넣어야 하고, 그러면 위험 증가 후보는 NOT_ASSESSABLE (ORDER_LOG_NOT_VERIFIED_COMPLETE)이지
    NO_BLOCK_FOUND가 아니다. 이 기록 유실을 잡는 장치(재시작 브로커 대조)는 미구현이다."""
    path = tmp_path / "orders.sqlite3"
    create_order_journal(path)
    append_to_order_journal(path, [unknown_c5_items()[0], NORMAL_AT_0900])
    older = path.read_bytes()
    append_to_order_journal(path, [unknown_c5_items()[1], HALTED_AT_0955])
    path.write_bytes(older)

    recovery = recover_order_journal(path)

    assert recovery.status is R.RECOVERED and recovery.order_evidence() == (unknown_c5_items()[0],)
    assert {"TAMPER_RESISTANCE", "BROKER_RECONCILIATION"} <= set(JOURNAL_RECOVERY_NOT_ESTABLISHED)
    report = gate(list(recovery.order_evidence()), "10:00", targets={C1: 10, C2: 0}, records=recovery.trading_state_records(),
                  completeness=UNVERIFIED)
    view = report.view(C1)
    assert (view.candidate_quantity, view.status) == (5, G.NOT_ASSESSABLE)
    assert "ORDER_LOG_NOT_VERIFIED_COMPLETE" in view.unassessable_reasons


# ---------------------------------------------------------------- TRACK B fixtures (가상 ETF, USD)

ETF = "ETF.US1"
ETF_T0 = datetime(2026, 10, 19, 0, 0, tzinfo=UTC)
FUND_AT = datetime(2026, 10, 19, 13, 0, tzinfo=UTC)
V0 = datetime(2026, 10, 19, 21, 0, tzinfo=UTC)
BUY_AT = datetime(2026, 10, 20, 14, 30, tzinfo=UTC)
V1 = datetime(2026, 10, 20, 21, 0, tzinfo=UTC)
V2 = datetime(2026, 10, 21, 21, 0, tzinfo=UTC)
DEPOSIT_AT = datetime(2026, 10, 22, 15, 0, tzinfo=UTC)
V3 = datetime(2026, 10, 22, 21, 0, tzinfo=UTC)


def etf_fill(quantity=10, fill_id="E-1"):
    return FillRecord(
        key=FillKey(account_id="A1", fill_source="SIM", fill_id=fill_id),
        client_order_id="C-" + fill_id,
        broker_order_id=None,
        contract_id=ETF,
        quantity=quantity,
        price="100",
        fill_at=BUY_AT,
        fee="2",
        fee_currency="USD",
        origin=FillOrigin.SIMULATED,
        execution_assumption_ref="assumption:test-fixture",
        venue=None,
        liquidity_flag=None,
    )


def cash_event(event_id, kind, amount, occurred_at, *, cause_ref=None, currency="USD"):
    return CashEvent(account_id="A1", cash_event_id=event_id, kind=kind, cause_ref=cause_ref or "transfer:" + event_id,
                     currency=currency, amount=amount, occurred_at=occurred_at, confirmation=CashEventConfirmation.CONFIRMED)


def funded():
    """검증된 기준 포지션 0주 (10-19 00:00) 위에 시작 현금 2,000 USD 입금 (10-19 13:00)."""
    account = open_etf_account(
        baseline=PositionBaseline(account_id="A1", as_of=ETF_T0, quantities={ETF: 0}, verification_ref="fixture:verified"),
        units=(EtfSpec(unit_id=ETF, currency="USD", lot_size=1),),
    )
    return record_cash_event(account, cash_event("CE-0", CashEventKind.EXTERNAL_FLOW, "2000", FUND_AT)).account


def etf_price(value, valuation_at, available=None):
    return ValuationPrice(contract_id=ETF, price=value, valuation_at=valuation_at,
                          data_available_at=available or valuation_at - timedelta(minutes=30), source_ref="fixture:close")


def nav(account, value, valuation_at, cutoff=None):
    return account_nav(account, prices={} if value is None else {ETF: etf_price(value, valuation_at)}, currency="USD",
                       valuation_at=valuation_at, information_cutoff=cutoff or valuation_at)


# ---------------------------------------------------------------- TRACK B


def test_b1_to_b3_buy_revaluation_and_deposit_flow_through_cash_and_nav():
    """B1~B3. 입력: 시작 현금 2,000 USD (입금). B1: 10주 매수 @ 100 USD, 수수료 2 USD, 평가가격 100. B2: 평가가격 110. B3: 외부 입금
    300 USD 뒤 평가가격 110.
    출력: B1: 체결 APPLIED·POSTED, 매매대금 −1,000과 수수료 −2 현금 이벤트가 한 번씩 생긴다. 실제 포지션 10주, 현금 998, 평가액 1,000,
    NAV 1,998 (COMPUTED). B2: NAV 2,098, 시작(입금 직후 NAV 2,000)부터의 투자 손익 +98, 외부 흐름 0. B3: NAV 2,398, 시작부터 NAV 변화
    +398 = 외부 흐름 +300 + 투자 손익 +98 (입금은 투자 수익이 아님), B2→B3 투자 손익 0. COMPUTED는 운영용 확정이 아니다
    (NAV_OPEN_POLICIES: 평가가격 정책, 기준통화, 현금 대조, NAV 확정 규칙)."""
    start = nav(funded(), None, V0)
    posting = record_etf_fill(funded(), etf_fill())
    assert (posting.fill_verdict, posting.outcome, posting.reasons) == (FillVerdict.APPLIED, PostingOutcome.POSTED, ())
    assert [(event.kind, event.amount) for event in posting.cash_events] == [
        (CashEventKind.TRADE_CONSIDERATION, Decimal("-1000")), (CashEventKind.COMMISSION, Decimal("-2"))]
    bought = posting.account

    assert account_position(bought, as_of=V1, information_cutoff=V1) == {ETF: 10}
    assert account_cash(bought, currency="USD", as_of=V1, information_cutoff=V1).balance == Decimal("998")
    b1 = nav(bought, "100", V1)
    assert (start.nav, b1.status, b1.market_value, b1.nav) == (Decimal("2000"), NavStatus.COMPUTED, Decimal("1000"), Decimal("1998"))
    assert b1.open_policies == NAV_OPEN_POLICIES and {"CASH_RECONCILIATION", "NAV_CONFIRMATION_RULE"} <= set(b1.open_policies)

    b2 = nav(bought, "110", V2)
    up = nav_change(start=start, end=b2)
    assert (b2.nav, up.investment_pnl, up.external_flow) == (Decimal("2098"), Decimal("98"), Decimal("0"))

    deposited = record_cash_event(bought, cash_event("CE-1", CashEventKind.EXTERNAL_FLOW, "300", DEPOSIT_AT)).account
    b3 = nav(deposited, "110", V3)
    total = nav_change(start=start, end=b3)
    assert (b3.nav, total.nav_change, total.external_flow, total.investment_pnl) == (
        Decimal("2398"), Decimal("398"), Decimal("300"), Decimal("98"))
    assert nav_change(start=b2, end=b3).investment_pnl == Decimal("0")


def test_b4_duplicates_and_conflicts_are_kept_and_block_the_account():
    """B4. 입력: B1의 계좌에 (a) 같은 체결을 다시 보냄, (b) 같은 체결 키로 수량 20주, (c) 그 체결의 수수료 현금 이벤트를 같은 ID·다른
    금액(−3)으로 보냄, (d) 다른 ID의 수수료 이벤트를 같은 체결 원인으로 한 번 더 보냄 (수수료 이중 반영 시도). (e) 새 계좌에 그 체결의
    수수료 이벤트(−3)가 먼저 도착한 뒤 체결이 도착.
    출력: (a) DUPLICATE·NO_CHANGE, 현금 이벤트를 다시 만들지 않고 NAV 1,998 그대로 (두 번 셌다면 현금 −4). (b) 체결 CONFLICT·BLOCKED
    (FILL_CONFLICT), 두 기록을 보존하고 포지션·NAV 계산을 막는다 (FillIntegrityError). (c)(d) 현금 장부 CONFLICT, NAV 계산을 막는다
    (CashIntegrityError. 이중 수수료라면 현금 996). (e) 체결 판정은 APPLIED인데 계좌 결과는 BLOCKED (CASH_CONFLICT): 체결 반영과 계좌 전체
    판정을 구분한다."""
    bought = record_etf_fill(funded(), etf_fill()).account

    again = record_etf_fill(bought, etf_fill())
    assert (again.fill_verdict, again.outcome, again.cash_events) == (FillVerdict.DUPLICATE, PostingOutcome.NO_CHANGE, ())
    assert nav(again.account, "100", V1).nav == Decimal("1998")

    clash = record_etf_fill(bought, etf_fill(quantity=20))
    assert (clash.fill_verdict, clash.outcome, clash.reasons) == (FillVerdict.CONFLICT, PostingOutcome.BLOCKED, ("FILL_CONFLICT",))
    assert len(clash.account.fills.conflicts) == 1 and clash.account.fills.applied == (etf_fill(),)
    with pytest.raises(FillIntegrityError):
        nav(clash.account, "100", V1)

    cause = fill_cause_ref(etf_fill().key)
    other_amount = cash_event(f"{cause}:COMMISSION", CashEventKind.COMMISSION, "-3", BUY_AT, cause_ref=cause)
    second_fee = cash_event("fee-again", CashEventKind.COMMISSION, "-2", BUY_AT, cause_ref=cause)
    for event in (other_amount, second_fee):
        changed = record_cash_event(bought, event)
        assert changed.application.verdict is CashVerdict.CONFLICT
        with pytest.raises(CashIntegrityError):
            nav(changed.account, "100", V1)

    early_fee = record_cash_event(funded(), other_amount).account
    late_fill = record_etf_fill(early_fee, etf_fill())
    assert (late_fill.fill_verdict, late_fill.outcome, late_fill.reasons) == (FillVerdict.APPLIED, PostingOutcome.BLOCKED, ("CASH_CONFLICT",))


def test_b5_information_after_the_cutoff_is_not_used():
    """B5. 입력: B3까지의 계좌 (10-22 15:00 입금 300 포함). (a) 10-20 21:00 평가를 10-20 21:00 기준으로, (b) 정보 기준 시각을 매수
    체결(14:30)보다 이른 14:00으로, (c) 정보 기준 시각보다 늦게 이용 가능해진 평가가격, (d) 다른 통화(EUR) 입금이 있는 계좌.
    출력: (a) 나중에 일어난 입금은 과거 평가에 들어가지 않아 NAV 1,998 (발생 시각 기준). (b) 정보 기준 시각 뒤의 체결로 포지션·NAV를
    계산하지 않고 ValueError ("happened after information_cutoff"). (c) 평가 시각은 맞지만 정보 기준 시각 뒤에 이용 가능해진 가격은
    ValueError ("became available after information_cutoff"). 검토 MEDIUM 회귀: 각 경우가 그 검사 자체로 거부되는지 사유로 확인한다.
    (d) 환율 없이 통화를 더하지 않아 NOT_COMPUTABLE (FX_MISSING, nav 없음). 체결·현금 기록에는 이용 가능 시각이 없으므로
    이 경로의 시점 검사는 발생 시각 기준이며 늦게 받은 기록까지 막는 완전한 PIT 보장이 아니다 (TRACK A도 FILL_RECORD_AVAILABILITY를 미검증
    입력으로 싣는다)."""
    account = record_etf_fill(funded(), etf_fill()).account
    account = record_cash_event(account, cash_event("CE-1", CashEventKind.EXTERNAL_FLOW, "300", DEPOSIT_AT)).account

    assert nav(account, "100", V1).nav == Decimal("1998")
    before_buy = datetime(2026, 10, 20, 14, 0, tzinfo=UTC)
    with pytest.raises(ValueError, match="ETF fill 'E-1' happened after information_cutoff"):
        nav(account, "100", V1, cutoff=before_buy)
    with pytest.raises(ValueError, match="happened after information_cutoff"):
        account_position(account, as_of=V1, information_cutoff=before_buy)
    late_price = etf_price("100", V1 + timedelta(minutes=10), available=V1 + timedelta(minutes=5))
    with pytest.raises(ValueError, match="became available after information_cutoff"):
        account_nav(account, prices={ETF: late_price}, currency="USD", valuation_at=V1 + timedelta(minutes=10), information_cutoff=V1)

    euro = record_cash_event(account, cash_event("CE-2", CashEventKind.EXTERNAL_FLOW, "100", DEPOSIT_AT, currency="EUR")).account
    mixed = nav(euro, "110", V3)
    assert (mixed.status, mixed.reasons, mixed.nav, mixed.fx_missing_currencies) == (NavStatus.NOT_COMPUTABLE, ("FX_MISSING",), None, ("EUR",))
    assert "FILL_RECORD_AVAILABILITY" in gate(open_buy_c7(), "10:00", targets={C1: 15, C2: 0}, c1=3).risk.pit_unverified


def test_cross_track_invariants_hold():
    """교차 불변조건. 입력: 위 시나리오의 입력을 다시 계산한다.
    출력: 주문 후보 ≠ 실제 체결 (후보 +5인데 실제 수량은 3), 실제 포지션 ≠ 모든 주문이 체결되었다고 본 포지션 (3 대 15),
    위험 통과 ≠ 제출 승인 (WITHIN_LIMIT·NO_BLOCK_FOUND에도 남은 제출 전 단계), Journal 복구 성공 ≠ 기록 완전성, 주문 MATCH ≠ 계좌 대조 완료
    (실제 MATCH 주문도 보고서는 UNVERIFIED이고 포지션·현금·체결 목록·Trading State 해제를 확인하지 않은 항목으로 싣는다),
    UNKNOWN의 일부 증거 ≠ 해소, 현금 입금 ≠ 투자 손익, COMPUTED ≠ 브로커 확인, HALTED ≠ 자동 정상화, 늦은 정보는 과거 판단에 쓰지 않음.
    계좌가 다른 증거·대조는 섞지 않고 ValueError."""
    a2 = gate(open_buy_c7(), "10:00", targets={C1: 15, C2: 0}, c1=3)
    worst = a2.risk.risk.view(C1).worst_case
    assert (worst.candidate_quantity, worst.actual_quantity, worst.worst_long_after) == (5, 3, 15)
    assert a2.view(C1).status is G.NO_BLOCK_FOUND and "BROKER_SUBMISSION_STEPS" in a2.risk.risk.view(C1).remaining_steps
    assert {"ORDER_LOG_COMPLETENESS", "BROKER_RECONCILIATION"} <= set(JOURNAL_RECOVERY_NOT_ESTABLISHED)
    accepted = [evidence("E-1", "C-5", 5, S.PENDING_SUBMIT, K.LOCAL_RECORD, "09:50"),
                evidence("E-2", "C-5", 5, S.ACCEPTED, K.REQUEST_RESPONSE, "09:51")]
    matched = reconcile_order_snapshot(
        orders_from_evidence_as_of(accepted, at("10:00"), account_id="A1", confirming_source=SRC.BROKER, completeness=UNVERIFIED),
        broker_snapshot(broker_line("C-5", 5, S.ACCEPTED)), at("10:00"))
    assert (matched.order("C-5").status, matched.status) == (M.MATCH, M.UNVERIFIED)
    assert matched.not_established == RECONCILIATION_NOT_ESTABLISHED
    assert {"ACTUAL_POSITION", "CASH", "FILL_RECORDS", "TRADING_STATE_RELEASE"} <= set(matched.not_established)

    early = gate(unknown_c5_items(), "10:00", targets={C1: 10, C2: 0}, fills=UNKNOWN_C5_FILLS)
    assert early.evidence.snapshot.records()[0].status is S.UNKNOWN
    assert "E-4" in {a.event_id for a in early.evidence.assessments}
    assert "E-4" not in {a.event_id for a in early.evidence.usable_assessments()}
    halted = gate(unknown_c5_items(), "10:30", targets={C1: 10, C2: 0}, fills=UNKNOWN_C5_FILLS, records=(NORMAL_AT_0900, HALTED_AT_0955))
    assert halted.evidence.snapshot.records()[0].status is S.PARTIALLY_FILLED and halted.trading_state_applied is TradingState.HALTED
    assert_all_blocked(halted, "TRADING_STATE_HALTED")

    deposited = record_cash_event(record_etf_fill(funded(), etf_fill()).account,
                                  cash_event("CE-1", CashEventKind.EXTERNAL_FLOW, "300", DEPOSIT_AT)).account
    change = nav_change(start=nav(funded(), None, V0), end=nav(deposited, "110", V3))
    assert (change.external_flow, change.investment_pnl) == (Decimal("300"), Decimal("98"))
    assert "CASH_RECONCILIATION" in nav(deposited, "110", V3).open_policies

    other_account = dataclasses.replace(
        open_buy_c7()[0], event=dataclasses.replace(open_buy_c7()[0].event,
                                                    record=dataclasses.replace(open_buy_c7()[0].event.record, account_id="A2")))
    with pytest.raises(ValueError):
        gate([other_account], "10:00", targets={C1: 0, C2: 0})
    local = orders_from_evidence_as_of(open_buy_c7(), at("10:00"), account_id="A1", confirming_source=SRC.BROKER, completeness=UNVERIFIED)
    with pytest.raises(ValueError):
        reconcile_order_snapshot(local, dataclasses.replace(broker_snapshot(), account_id="A2"), at("10:00"))
