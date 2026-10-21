"""P0-03C Slice 3: UNKNOWN 해소 증거와 L3 안전 게이트 (ADR-0009 §6.2·R9-4·R9-6·RP-4·RP-5·AT-0009-2, ADR-0012 BR-4·BR-12·§6.7·
AT-0012-1·AT-0012-5, ADR-0003 §6.2·§6.2.1·§6.3·§6.5, ADR-0001 I-1).

증거는 주문 사건 하나와 그 증거 종류(로컬 기록, 요청 응답, 상태 조회 결과, 체결 통보)다. 출처는 사건 기록의 출처(SYSTEM /
BROKER / SIMULATOR)로 따로 둔다. 기대값(5,000 / 10,000 / 15,000 USD 등)은 저장소 밖 독립 산술(Fraction)로 먼저 확인했다.
가상 선물이며 한도·가격·승수와 Trading State 기록은 테스트 입력이다. 브로커 진위·대조는 하지 않는다.
"""

import dataclasses
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from carver_quant.lab.accounting.fill_ledger import FillLedger, apply_fill
from carver_quant.lab.accounting.l3_gate import (
    L3_GATE_NOT_CHECKED,
    CandidateRiskEffect,
    L3GateStatus,
    assess_l3_gate,
    assess_l3_gate_as_of,
)
from carver_quant.lab.accounting.order_projection import OrderIntegrityError
from carver_quant.lab.accounting.order_snapshot import OrderEventIntegrityError, OrderLogCompleteness, assess_pretrade_risk_as_of
from carver_quant.lab.accounting.pretrade_risk import RiskCheckStatus, assess_pretrade_risk
from carver_quant.lab.accounting.unknown_resolution import EvidenceDisposition, orders_from_evidence_as_of
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
C1 = "FUT.ALPHA.C1"
C2 = "FUT.ALPHA.C2"
T0 = datetime(2026, 10, 21, 0, 0, tzinfo=UTC)
COMPLETE = OrderLogCompleteness.VERIFIED_COMPLETE
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


def ledger_with(*fills, c1_lot=1):
    ledger = FillLedger.empty(account_id="A1", contracts=(contract(C1, c1_lot), contract(C2)))
    for fill in fills:
        ledger = apply_fill(ledger, fill).ledger
    return ledger


def baseline(c1=0):
    return PositionBaseline(account_id="A1", as_of=T0, quantities={C1: c1, C2: 0}, verification_ref="fixture:verified")


def risk_inputs(decision, c1_price="100"):
    available = decision - timedelta(minutes=30)
    return dict(
        reference_prices={
            contract_id: ValuationPrice(contract_id=contract_id, price=c1_price if contract_id == C1 else "100", valuation_at=available,
                                        data_available_at=available, source_ref="fixture:price")
            for contract_id in (C1, C2)
            if contract_id != C1 or c1_price is not None
        },
        multipliers={
            contract_id: ContractMultiplier(contract_id=contract_id, multiplier="10", currency="USD", data_available_at=T0,
                                            source_ref="fixture:spec")
            for contract_id in (C1, C2)
        },
        limits={contract_id: ExposureLimit(contract_id=contract_id, currency="USD", max_exposure="20000", source_ref="test:limit")
                for contract_id in (C1, C2)},
    )


def gate(items, decision, *, targets=None, fills=(), records=(NORMAL_AT_0900,), plain=TradingState.NORMAL, completeness=COMPLETE,
         confirming=SRC.BROKER, c1=0, c1_price="100", c1_lot=1):
    return assess_l3_gate_as_of(
        baseline=baseline(c1),
        ledger=ledger_with(*fills, c1_lot=c1_lot),
        evidence=items,
        confirming_source=confirming,
        completeness=completeness,
        completeness_ref="fixture:complete-log" if completeness is COMPLETE else None,
        targets=targets or {C1: 0, C2: 0},
        decision_at=at(decision),
        trading_state=plain,
        trading_state_records=records,
        **risk_inputs(at(decision), c1_price),
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


def test_order_evidence_separates_source_and_kind():
    """입력: 정상 증거와 (a) 로컬 기록 종류인데 브로커 보고, (b) 체결 통보 종류인데 시스템 기록, (c) 요청 시각 없는 상태 조회,
    (d) 상태 조회가 아닌데 요청 시각 있음, (e) 요청 시각이 관측 시각 뒤, (f) 체결 0인 체결 통보, (g) 시간대 없는 요청 시각,
    (h) 주문 사건이 아닌 값.
    출력: 정상 증거는 출처(사건 기록의 출처)와 증거 종류를 따로 가진다. (a)~(h)는 ValueError."""
    query = evidence("E-3", "C-5", 5, S.ACCEPTED, K.STATUS_QUERY_RESPONSE, "09:57", requested="09:56")
    local = evidence("E-1", "C-5", 5, S.PENDING_SUBMIT, K.LOCAL_RECORD, "09:50")
    fill = evidence("E-4", "C-5", 5, S.PARTIALLY_FILLED, K.FILL_NOTIFICATION, "09:58", filled=3)
    assert (query.event.record.status_source, query.evidence_kind, query.requested_at) == (SRC.BROKER, K.STATUS_QUERY_RESPONSE, at("09:56"))
    assert (local.event.record.status_source, local.evidence_kind) == (SRC.SYSTEM, K.LOCAL_RECORD)

    bad = [
        lambda: dataclasses.replace(query, evidence_kind=K.LOCAL_RECORD, requested_at=None),
        lambda: dataclasses.replace(local, evidence_kind=K.FILL_NOTIFICATION),
        lambda: dataclasses.replace(query, requested_at=None),
        lambda: dataclasses.replace(fill, requested_at=at("09:57")),
        lambda: dataclasses.replace(query, requested_at=at("09:58")),
        lambda: evidence("E-5", "C-5", 5, S.ACCEPTED, K.FILL_NOTIFICATION, "09:58"),
        lambda: dataclasses.replace(query, requested_at=datetime(2026, 10, 21, 9, 56)),
        lambda: dataclasses.replace(query, event=query.event.record),
    ]
    for make in bad:
        with pytest.raises(ValueError):
            make()


def test_trading_state_record_carries_time_cause_and_approver():
    """입력: 정상 Trading State 기록과 (a) 이용 가능 시각이 상태 시각보다 앞섬, (b) 시간대 없는 시각, (c) Trading State가 아닌
    상태, (d) 빈 원인 코드.
    출력: 정상 기록은 계좌·상태·상태 시각·이용 가능 시각·원인 코드·승인자 참조를 가진다 (ADR-0003 §6.5). (a)~(d)는 ValueError
    (ADR-0001 I-1: 관측 ≤ 이용 가능)."""
    record = state_record("TS-9", TradingState.NORMAL, "09:00", "09:01")
    assert (record.state, record.effective_at, record.data_available_at, record.approver_ref) == (
        TradingState.NORMAL, at("09:00"), at("09:01"), "user:approval")

    for changes in (dict(data_available_at=at("08:59")), dict(effective_at=datetime(2026, 10, 21, 9, 0)), dict(state="NORMAL"),
                    dict(cause_code="")):
        with pytest.raises(ValueError):
            dataclasses.replace(record, **changes)


def test_case_1_fill_notice_alone_keeps_unknown_and_its_block():
    """CASE 1 (Slice 2 탐색 P6). 입력: 브로커 주문 +5가 09:55에 UNKNOWN. 09:57 체결 +3 통보(PARTIALLY_FILLED로 보고)가 09:58에
    이용 가능. 판단 10:00, 목표 C1 +10, C2 +2.
    출력: 체결 3은 확인된 체결로 남고(실제 3) 주문은 UNKNOWN 그대로다 (FILLS_ONLY. AT-0012-5 3행: 체결 한 건으로는 종료를 확인할 수
    없음). 최악 경우 롱 3 + 2 = 5, 노출 5,000 USD로 줄지 않는다. 모든 월물 BLOCKED(UNKNOWN_ORDER_PRESENT). 수정 전(Slice 2 경로)에는
    PARTIALLY_FILLED가 되어 UNKNOWN 차단이 사라지고 후보가 WITHIN_LIMIT였다."""
    items = unknown_c5() + [evidence("E-3", "C-5", 5, S.PARTIALLY_FILLED, K.FILL_NOTIFICATION, "09:57", "09:58", filled=3)]

    report = gate(items, "10:00", targets={C1: 10, C2: 2}, fills=[make_fill("X-1", "C-5", 3, "09:57")])

    record = report.evidence.snapshot.records()[0]
    assert (record.status, record.filled_quantity, record.status_source) == (S.UNKNOWN, 3, SRC.BROKER)
    notice = report.evidence.assessments[-1]
    assert (notice.event_id, notice.disposition, notice.reasons) == ("E-3", D.FILLS_ONLY, ("FILL_NOTIFICATION_DOES_NOT_CONFIRM_ORDER_STATUS",))
    view = report.risk.risk.view(C1)
    assert (view.worst_case.actual_quantity, view.worst_case.worst_long_before, view.exposure_before) == (3, 5, Decimal("5000"))
    assert_all_blocked(report, "UNKNOWN_ORDER_PRESENT")


def test_case_1_full_fill_notice_still_needs_a_status_query():
    """CASE 1 변형 (ADR-0009 AT-0009-2). 입력: UNKNOWN +5에 체결 +5 통보(FILLED로 보고). 판단 10:00.
    출력: 실제 5, 주문은 UNKNOWN(체결 5) 그대로, 최악 경우 롱 5. FILLED는 상태 조회로 확인될 때만이다 (R9-4). BLOCKED."""
    items = unknown_c5() + [evidence("E-3", "C-5", 5, S.FILLED, K.FILL_NOTIFICATION, "09:57", "09:58", filled=5)]

    report = gate(items, "10:00", fills=[make_fill("X-1", "C-5", 5, "09:57")])

    record = report.evidence.snapshot.records()[0]
    assert (record.status, record.filled_quantity) == (S.UNKNOWN, 5)
    assert report.risk.risk.view(C1).worst_case.worst_long_before == 5
    assert_all_blocked(report, "UNKNOWN_ORDER_PRESENT")


@pytest.mark.parametrize("history", ["submitted", "accepted_then_cancel_requested"])
def test_case_2_simulator_report_cannot_resolve_a_broker_order(history):
    """CASE 2 (Slice 2 탐색 P8). 입력: 확인 출처가 BROKER인 계좌의 주문 +5가 UNKNOWN. (a) 제출 뒤 timeout, (b) 브로커 접수와 취소
    요청 뒤 timeout. 09:57 시뮬레이터의 CANCELLED 조회 결과. 판단 10:00, 목표 C1 +10.
    출력: 시뮬레이터 보고는 REJECTED(SOURCE_MISMATCH)이고 쓰지 않는다. 주문은 UNKNOWN, 최악 경우 롱 5, 노출 5,000 USD (0이 아님).
    모든 월물 BLOCKED (UNKNOWN_ORDER_PRESENT, ORDER_EVIDENCE_CONFLICT). 수정 전에는 CANCELLED로 해소되어 최악 경우가 0이었다."""
    if history == "submitted":
        items = unknown_c5()
    else:
        items = [
            evidence("E-1", "C-5", 5, S.PENDING_SUBMIT, K.LOCAL_RECORD, "09:50"),
            evidence("E-2", "C-5", 5, S.ACCEPTED, K.REQUEST_RESPONSE, "09:51"),
            evidence("E-3", "C-5", 5, S.CANCEL_REQUESTED, K.LOCAL_RECORD, "09:53"),
            evidence("E-4", "C-5", 5, S.UNKNOWN, K.LOCAL_RECORD, "09:55"),
        ]
    items.append(evidence("E-9", "C-5", 5, S.CANCELLED, K.STATUS_QUERY_RESPONSE, "09:57", source=SRC.SIMULATOR, cancelled=5,
                          requested="09:56"))

    report = gate(items, "10:00", targets={C1: 10, C2: 0})

    rejected = report.evidence.assessments[-1]
    assert (rejected.event_id, rejected.source, rejected.disposition, rejected.reasons) == (
        "E-9", SRC.SIMULATOR, D.REJECTED, ("SOURCE_MISMATCH",))
    assert report.evidence.snapshot.records()[0].status is S.UNKNOWN
    view = report.risk.risk.view(C1)
    assert (view.worst_case.worst_long_before, view.exposure_before) == (5, Decimal("5000"))
    assert_all_blocked(report, "UNKNOWN_ORDER_PRESENT", "ORDER_EVIDENCE_CONFLICT")


def test_case_2_paper_account_does_not_take_broker_reports():
    """입력: 확인 출처가 SIMULATOR인 계좌의 UNKNOWN 주문에 브로커의 ACCEPTED 조회 결과.
    출력: REJECTED(SOURCE_MISMATCH), 주문은 UNKNOWN. 두 출처를 시간 순서만으로 잇지 않는다."""
    items = unknown_c5() + [evidence("E-3", "C-5", 5, S.ACCEPTED, K.STATUS_QUERY_RESPONSE, "09:57", requested="09:56")]

    checked = orders_from_evidence_as_of(items, at("10:00"), account_id="A1", confirming_source=SRC.SIMULATOR, completeness=COMPLETE,
                                         completeness_ref="x")

    assert (checked.assessments[-1].disposition, checked.assessments[-1].reasons) == (D.REJECTED, ("SOURCE_MISMATCH",))
    assert checked.snapshot.records()[0].status is S.UNKNOWN


def test_case_3_status_query_confirms_the_order_but_does_not_release_halted():
    """CASE 3. 입력: UNKNOWN +5 (09:55). 같은 Client Order ID의 상태 조회(09:56 요청) 결과 ACCEPTED (Broker Order ID B-77, 체결 0)가
    09:57에 이용 가능. 판단 10:00, 목표 C1 +10. Trading State 기록 (a) 09:00 NORMAL과 09:55 HALTED (UNKNOWN 진입), (b) 09:00 NORMAL만.
    출력: 조회 결과를 쓴다 (USED). 주문 ACCEPTED, 최악 경우 롱 5 그대로 (AT-0012-1). (a) 모든 월물 BLOCKED(TRADING_STATE_HALTED).
    (b) 모든 월물 BLOCKED(UNKNOWN_RESOLVED_AFTER_TRADING_STATE_RECORD): UNKNOWN 전의 NORMAL 기록은 그 뒤에 생긴 HALTED 조건을 풀지
    않는다. 주문 확인과 HALTED 해제는 별개다 (ADR-0003 §6.5, ADR-0009 원칙 9)."""
    items = unknown_c5() + [evidence("E-3", "C-5", 5, S.ACCEPTED, K.STATUS_QUERY_RESPONSE, "09:56", "09:57", requested="09:56",
                                     broker_id="B-77")]

    halted = gate(items, "10:00", targets={C1: 10, C2: 0}, records=(NORMAL_AT_0900, HALTED_AT_0955))
    stale_normal = gate(items, "10:00", targets={C1: 10, C2: 0}, records=(NORMAL_AT_0900,))

    record = halted.evidence.snapshot.records()[0]
    assert (record.status, record.broker_order_id) == (S.ACCEPTED, "B-77")
    assert halted.evidence.assessments[-1].disposition is D.USED
    assert halted.risk.risk.view(C1).worst_case.worst_long_before == 5
    assert halted.trading_state_record == HALTED_AT_0955
    assert_all_blocked(halted, "TRADING_STATE_HALTED")
    assert_all_blocked(stale_normal, "UNKNOWN_RESOLVED_AFTER_TRADING_STATE_RECORD")


def test_case_3_only_a_later_recorded_release_lets_the_gate_find_no_block():
    """CASE 3 이어서. 입력: (a)의 기록에 10:30 NORMAL 기록(원인 코드·승인자 참조 있음)을 더함. 판단 10:31, 목표 C1 +10.
    출력: 후보 +5 (기대 예상 5), 위험 증가, 노출 10,000 < 한도 20,000 → C1 NO_BLOCK_FOUND. 이 값은 이 게이트의 검사 범위에서 차단
    사유를 찾지 못했다는 뜻일 뿐이며, 검사하지 않은 단계(대조, 검증된 축소, L1 다른 지표, L2, 제출 절차, 증거 진위)를 늘 함께 돌려준다."""
    items = unknown_c5() + [evidence("E-3", "C-5", 5, S.ACCEPTED, K.STATUS_QUERY_RESPONSE, "09:56", "09:57", requested="09:56")]
    release = state_record("TS-3", TradingState.NORMAL, "10:30", cause="UNKNOWN_RESOLVED_RECONCILED", approver="user:release-1")

    report = gate(items, "10:31", targets={C1: 10, C2: 0}, records=(NORMAL_AT_0900, HALTED_AT_0955, release))

    view = report.view(C1)
    assert (view.candidate_quantity, view.candidate_effect, view.status) == (5, CandidateRiskEffect.RISK_INCREASING, G.NO_BLOCK_FOUND)
    assert report.risk.risk.view(C1).exposure_after == Decimal("10000")
    assert report.trading_state_record == release
    for step in ("BROKER_RECONCILIATION", "VERIFIED_RISK_REDUCTION", "L1_OTHER_RISK_METRICS", "L2_POLICY_DECISION",
                 "BROKER_SUBMISSION_STEPS", "EVIDENCE_AUTHENTICITY", "TRADING_STATE_RECORD_BASIS"):
        assert step in report.not_checked


@pytest.mark.parametrize(
    ("result", "reason"),
    [
        (dict(status=S.CANCELLED, cancelled=5), "RESOLUTION_WOULD_LOWER_UNKNOWN_WORST_CASE"),
        (dict(status=S.REJECTED), "RESOLUTION_WOULD_LOWER_UNKNOWN_WORST_CASE"),
        (dict(status=S.EXPIRED, cancelled=5), "RESOLUTION_WOULD_LOWER_UNKNOWN_WORST_CASE"),
        (dict(status=S.ACCEPTED, cancelled=2), "RESOLUTION_WOULD_LOWER_UNKNOWN_WORST_CASE"),
        (dict(status=S.PARTIALLY_FILLED, filled=2), "STATUS_QUERY_FILLS_DIFFER_FROM_CONFIRMED_FILLS"),
        (dict(status=S.ACCEPTED, requested="09:54"), "STATUS_QUERY_REQUESTED_BEFORE_UNKNOWN"),
        (dict(status=S.CANCEL_REQUESTED), "STATUS_NOT_AN_APPROVED_UNKNOWN_RESOLUTION"),
    ],
)
def test_case_3_query_results_outside_the_approved_resolution_are_deferred(result, reason):
    """CASE 3 변형. 입력: UNKNOWN +5에 대한 상태 조회 결과가 (a) CANCELLED, (b) REJECTED, (c) EXPIRED (최악 경우를 5에서 0으로 줄임),
    (d) 확인 취소 2인 ACCEPTED (5에서 3으로 줄임), (e) 확인된 체결(0)과 다른 누적 체결 2 (RP-4), (f) UNKNOWN 분류(09:55) 전인 09:54에
    요청한 조회, (g) 승인된 해소 예시에 없는 상태.
    출력: DEFERRED와 그 사유. 주문은 UNKNOWN, 최악 경우 롱 5, BLOCKED. 최악 경우를 줄이는 해소에는 상태 조회와 대조 일치가 함께
    필요하고 (AT-0012-5), 더 약한 조건은 미승인이다 (Q12-14). 이 Slice는 대조를 하지 않는다."""
    options = dict(result)  # 공유 매개변수 dict를 바꾸지 않는다
    requested = options.pop("requested", "09:56")
    items = unknown_c5() + [evidence("E-3", "C-5", 5, kind=K.STATUS_QUERY_RESPONSE, occurred="09:56", available="09:57",
                                     requested=requested, **options)]

    report = gate(items, "10:00")

    query = report.evidence.assessments[-1]
    assert (query.disposition, query.reasons) == (D.DEFERRED, (reason,))
    assert report.evidence.snapshot.records()[0].status is S.UNKNOWN
    assert report.risk.risk.view(C1).worst_case.worst_long_before == 5
    assert_all_blocked(report, "UNKNOWN_ORDER_PRESENT")


def test_case_3_late_request_response_does_not_resolve_unknown():
    """입력: UNKNOWN +5 (09:55) 뒤 제출 요청의 ACCEPTED 응답이 09:57에 도착.
    출력: DEFERRED(UNKNOWN_NEEDS_STATUS_QUERY). UNKNOWN 뒤 확인은 같은 Client Order ID의 상태 조회로 한다 (R9-4, R9-5, BR-4)."""
    items = unknown_c5() + [evidence("E-3", "C-5", 5, S.ACCEPTED, K.REQUEST_RESPONSE, "09:56", "09:57")]

    report = gate(items, "10:00")

    assert (report.evidence.assessments[-1].disposition, report.evidence.assessments[-1].reasons) == (
        D.DEFERRED, ("UNKNOWN_NEEDS_STATUS_QUERY",))
    assert_all_blocked(report, "UNKNOWN_ORDER_PRESENT")


def test_case_4_halted_blocks_orders_within_limit():
    """CASE 4. 입력: 주문 없음, 목표 C1 +5 (후보 +5, 노출 5,000 < 한도 20,000, WITHIN_LIMIT). (a) 09:30 HALTED 기록, (b) 기록은
    NORMAL이지만 호출자 입력이 HALTED.
    출력: 두 경우 모두 모든 월물 BLOCKED(TRADING_STATE_HALTED). 위험 한도 통과는 HALTED를 풀지 않는다 (ADR-0003 §6.5, R9-12)."""
    halted = state_record("TS-5", TradingState.HALTED, "09:30", cause="MANUAL_KILL_SWITCH", approver=None)

    by_record = gate([], "10:00", targets={C1: 5, C2: 0}, records=(NORMAL_AT_0900, halted))
    by_input = gate([], "10:00", targets={C1: 5, C2: 0}, plain=TradingState.HALTED)

    for report in (by_record, by_input):
        assert report.risk.risk.view(C1).risk_status is RiskCheckStatus.WITHIN_LIMIT
        assert report.risk.risk.view(C1).exposure_after == Decimal("5000")
        assert_all_blocked(report, "TRADING_STATE_HALTED")


@pytest.mark.parametrize(
    ("state", "target", "exposure", "effect", "reason"),
    [
        (TradingState.RESTRICTED, 4, "10000", CandidateRiskEffect.CONTAINS_RISK_REDUCTION, "RISK_REDUCTION_NOT_VERIFIED"),
        (TradingState.RESTRICTED, -4, "10000", CandidateRiskEffect.CONTAINS_RISK_REDUCTION, "RISK_REDUCTION_NOT_VERIFIED"),
        (TradingState.RESTRICTED, 12, "12000", CandidateRiskEffect.RISK_INCREASING, "TRADING_STATE_RESTRICTED"),
        (TradingState.NORMAL, 4, "10000", CandidateRiskEffect.CONTAINS_RISK_REDUCTION, "RISK_REDUCTION_NOT_VERIFIED"),
    ],
)
def test_case_5_restricted_increase_and_unverified_reductions_are_blocked(state, target, exposure, effect, reason):
    """CASE 5. 입력: 검증된 기준 포지션 C1 +10, 주문 없음. Trading State 기록 RESTRICTED에 목표 (a) +4 (축소 후보 −6), (b) −4 (반전
    −14), (c) +12 (증가 +2). (d) NORMAL 기록에 목표 +4.
    출력: 노출은 모두 한도 안 (10,000 / 10,000 / 12,000 / 10,000 USD). (a)(b)(d) C1 BLOCKED(RISK_REDUCTION_NOT_VERIFIED): 축소에는
    S-1·S-3·S-6·S-7과 포트폴리오 검사가 필요한데 이 게이트는 확인하지 않는다 (ADR-0003 §6.2.1: 하나라도 확인하지 못하면 차단, §6.5
    NORMAL 행). (c) C1 BLOCKED(TRADING_STATE_RESTRICTED)."""
    record = state_record("TS-6", state, "09:30", cause="DRAWDOWN_LIMIT", approver="user:approval" if state is TradingState.NORMAL else None)

    report = gate([], "10:00", targets={C1: target, C2: 0}, records=(record,), c1=10)

    risk = report.risk.risk.view(C1)
    assert (risk.risk_status, risk.exposure_after) == (RiskCheckStatus.WITHIN_LIMIT, Decimal(exposure))
    view = report.view(C1)
    assert (view.candidate_effect, view.status, view.blocking_reasons) == (effect, G.BLOCKED, (reason,))


def test_case_6_plain_normal_is_not_a_full_l3_pass():
    """CASE 6. 입력: 주문 없음, 목표 C1 +5 (위험 증가, 노출 5,000 < 20,000). 호출자 입력 NORMAL. Trading State 기록이 (a) 없음,
    (b) 10:05에야 이용 가능 (판단 10:00), (c) 승인자 참조 없는 NORMAL. (d) 대조군: 09:00에 이용 가능한 승인 NORMAL 기록.
    출력: (a)(b) NOT_ASSESSABLE(TRADING_STATE_RECORD_MISSING), (b)의 기록은 늦은 기록으로만 남는다 (미래 상태를 과거 판단에 쓰지
    않음). (c) NOT_ASSESSABLE(TRADING_STATE_APPROVAL_NOT_RECORDED). (d) C1 NO_BLOCK_FOUND. 결과 값에 주문 허가·전송 준비 값은 없다."""
    targets = {C1: 5, C2: 0}
    late = state_record("TS-7", TradingState.NORMAL, "09:00", "10:05")
    unapproved = state_record("TS-8", TradingState.NORMAL, "09:00", approver=None)

    missing = gate([], "10:00", targets=targets, records=())
    future = gate([], "10:00", targets=targets, records=(late,))
    no_approver = gate([], "10:00", targets=targets, records=(unapproved,))
    recorded = gate([], "10:00", targets=targets)

    for report, reason in ((missing, "TRADING_STATE_RECORD_MISSING"), (future, "TRADING_STATE_RECORD_MISSING"),
                           (no_approver, "TRADING_STATE_APPROVAL_NOT_RECORDED")):
        assert report.view(C1).status is G.NOT_ASSESSABLE
        assert report.view(C1).unassessable_reasons == (reason,)
    assert (future.trading_state_record, future.late_state_record_ids) == (None, ("TS-7",))
    assert recorded.view(C1).status is G.NO_BLOCK_FOUND
    assert set(L3GateStatus.__members__) == {"BLOCKED", "NOT_ASSESSABLE", "NO_BLOCK_FOUND"}


def test_case_6_unverified_order_log_is_not_a_full_l3_result():
    """입력: CASE 6 (d)와 같은데 주문 사건 기록의 완전성을 확인하지 못함 (UNVERIFIED).
    출력: 모든 월물 NOT_ASSESSABLE(ORDER_LOG_NOT_VERIFIED_COMPLETE). 빠진 주문이 있을 수 있으므로 완전한 L3 판정으로 처리하지 않는다."""
    report = gate([], "10:00", targets={C1: 5, C2: 0}, completeness=OrderLogCompleteness.UNVERIFIED)

    for view in report.views:
        assert view.status is G.NOT_ASSESSABLE
        assert "ORDER_LOG_NOT_VERIFIED_COMPLETE" in view.unassessable_reasons
    assert "ORDER_LOG_COMPLETENESS" in report.not_checked


def test_case_7_late_status_query_is_not_applied_to_the_earlier_decision():
    """CASE 7. 입력: UNKNOWN +5 (09:55). 상태 조회(10:01 요청) 결과 ACCEPTED가 10:05에 이용 가능. 판단 10:00과 10:05.
    출력: 10:00에는 UNKNOWN 그대로, 최악 경우 롱 5, BLOCKED(UNKNOWN_ORDER_PRESENT). 그 조회는 늦은 사건으로 보존되고 10:00 판단의
    증거 목록에 들어가지 않는다. 10:05에는 ACCEPTED (최악 경우 5)."""
    items = unknown_c5() + [evidence("E-3", "C-5", 5, S.ACCEPTED, K.STATUS_QUERY_RESPONSE, "10:02", "10:05", requested="10:01")]

    before = gate(items, "10:00")
    after = gate(items, "10:05")

    assert before.evidence.snapshot.records()[0].status is S.UNKNOWN
    assert before.evidence.snapshot.late_event_ids == ("E-3",)
    assert [assessment.event_id for assessment in before.evidence.usable_assessments()] == ["E-1", "E-2"]
    assert before.risk.risk.view(C1).worst_case.worst_long_before == 5
    assert_all_blocked(before, "UNKNOWN_ORDER_PRESENT")
    assert after.evidence.snapshot.records()[0].status is S.ACCEPTED
    assert after.risk.risk.view(C1).worst_case.worst_long_before == 5


def test_case_8_repeated_evidence_is_counted_once():
    """CASE 8. 입력: 체결 통보 E-3(+3)과 상태 조회 E-4(PARTIALLY_FILLED, 체결 3)를 각각 두 번 받고, 체결 X-1도 두 번 받음.
    출력: 사건마다 판정 하나 (E-3 FILLS_ONLY, E-4 USED). 체결 3을 한 번만 반영: 실제 3, 최악 경우 롱 3 + 2 = 5 (두 번 세면 6)."""
    notice = evidence("E-3", "C-5", 5, S.PARTIALLY_FILLED, K.FILL_NOTIFICATION, "09:57", "09:58", filled=3)
    query = evidence("E-4", "C-5", 5, S.PARTIALLY_FILLED, K.STATUS_QUERY_RESPONSE, "09:58", "09:59", filled=3, requested="09:58")
    fill = make_fill("X-1", "C-5", 3, "09:57")

    report = gate(unknown_c5() + [notice, notice, query, query], "10:00", fills=[fill, fill])

    assert [(a.event_id, a.disposition) for a in report.evidence.assessments] == [
        ("E-1", D.USED), ("E-2", D.USED), ("E-3", D.FILLS_ONLY), ("E-4", D.USED)]
    view = report.risk.risk.view(C1)
    assert (view.worst_case.actual_quantity, view.worst_case.worst_long_before) == (3, 5)


@pytest.mark.parametrize(
    "extra",
    [
        # 같은 사건 ID, 다른 내용
        [evidence("E-3", "C-5", 5, S.PARTIALLY_FILLED, K.FILL_NOTIFICATION, "09:57", filled=3),
         evidence("E-3", "C-5", 5, S.PARTIALLY_FILLED, K.FILL_NOTIFICATION, "09:57", filled=4)],
        # 같은 사건을 다른 증거 종류로 받음
        [evidence("E-3", "C-5", 5, S.ACCEPTED, K.STATUS_QUERY_RESPONSE, "09:57", requested="09:56"),
         evidence("E-3", "C-5", 5, S.ACCEPTED, K.REQUEST_RESPONSE, "09:57")],
        # 같은 이용 가능 시각의 모순된 조회 결과 (먼저 정렬되는 CANCEL_REQUESTED는 DEFERRED라 Slice 2에 가지 않는다)
        [evidence("E-3", "C-5", 5, S.CANCEL_REQUESTED, K.STATUS_QUERY_RESPONSE, "09:57", requested="09:56"),
         evidence("E-4", "C-5", 5, S.ACCEPTED, K.STATUS_QUERY_RESPONSE, "09:57", requested="09:56")],
        # DEFERRED 조회 결과의 주문 수량 변경
        [evidence("E-3", "C-5", 6, S.CANCELLED, K.STATUS_QUERY_RESPONSE, "09:57", cancelled=6, requested="09:56")],
        # 체결 통보(+3) 뒤 DEFERRED 조회 결과가 보고한 누적 체결 감소 (2)
        [evidence("E-3", "C-5", 5, S.PARTIALLY_FILLED, K.FILL_NOTIFICATION, "09:57", filled=3),
         evidence("E-4", "C-5", 5, S.PARTIALLY_FILLED, K.STATUS_QUERY_RESPONSE, "09:58", filled=2, requested="09:58")],
    ],
)
def test_case_8_conflicting_evidence_is_rejected_not_normalized(extra):
    """CASE 8. 입력: UNKNOWN +5에 (a) 같은 사건 ID의 다른 내용, (b) 같은 사건을 다른 증거 종류로 받음, (c) 같은 이용 가능 시각의
    CANCEL_REQUESTED와 ACCEPTED 조회 결과, (d) 주문 수량이 다른 조회 결과, (e) 보고된 누적 체결의 감소. (c)~(e)는 판정에서 빠지는 증거라
    Slice 2의 검사에 닿지 않는다.
    출력: OrderEventIntegrityError. 어느 쪽이 맞는지 고르지 않는다 (판정에서 빠진 증거도 검사한다)."""
    with pytest.raises(OrderEventIntegrityError):
        orders_from_evidence_as_of(unknown_c5() + extra, at("10:00"), account_id="A1", confirming_source=SRC.BROKER,
                                   completeness=COMPLETE, completeness_ref="x")


def test_case_8_evidence_of_another_account_is_rejected():
    """CASE 8. 입력: 같은 Client Order ID C-5인데 계좌 A2의 상태 조회 결과. 출력: ValueError (계좌 하나의 증거만 받는다)."""
    items = unknown_c5() + [evidence("E-3", "C-5", 5, S.ACCEPTED, K.STATUS_QUERY_RESPONSE, "09:57", requested="09:56", account_id="A2")]

    with pytest.raises(ValueError):
        gate(items, "10:00")


@pytest.mark.parametrize(
    ("report_item", "reason"),
    [
        (evidence("E-3", "C-1", 5, S.PARTIALLY_FILLED, K.FILL_NOTIFICATION, "09:57", source=SRC.SIMULATOR, filled=2), "SOURCE_MISMATCH"),
        (evidence("E-3", "C-1", 5, S.CANCELLED, K.STATUS_QUERY_RESPONSE, "09:57", cancelled=5, requested="09:56", broker_id="B-99"),
         "BROKER_ORDER_ID_MISMATCH"),
    ],
)
def test_case_8_source_or_broker_id_change_blocks_the_account(report_item, reason):
    """CASE 8. 입력: 브로커가 접수한 주문 C-1 +5 (Broker Order ID B-C-1)에 (a) 시뮬레이터의 체결 통보, (b) 다른 Broker Order ID(B-99)의
    CANCELLED 조회 결과. 판단 10:00.
    출력: REJECTED와 사유, 그 증거는 쓰지 않는다 (주문은 ACCEPTED, 최악 경우 롱 5). 모든 월물 BLOCKED(ORDER_EVIDENCE_CONFLICT)."""
    items = [
        evidence("E-1", "C-1", 5, S.PENDING_SUBMIT, K.LOCAL_RECORD, "09:50"),
        evidence("E-2", "C-1", 5, S.ACCEPTED, K.REQUEST_RESPONSE, "09:51"),
        report_item,
    ]

    report = gate(items, "10:00")

    assert (report.evidence.assessments[-1].disposition, report.evidence.assessments[-1].reasons) == (D.REJECTED, (reason,))
    assert report.evidence.snapshot.records()[0].status is S.ACCEPTED
    assert report.risk.risk.view(C1).worst_case.worst_long_before == 5
    assert_all_blocked(report, "ORDER_EVIDENCE_CONFLICT")


def test_case_8_trading_state_record_conflicts():
    """CASE 8. 입력: (a) 같은 Trading State 기록 두 번 (같은 내용), (b) 같은 기록 ID의 다른 내용, (c) 같은 상태 시각의 서로 다른 상태,
    (d) 다른 계좌의 기록.
    출력: (a) 한 번만 쓴다. (b)(c)(d) ValueError (상태를 고르지 않는다)."""
    halted_same_time = state_record("TS-9", TradingState.HALTED, "09:00", approver=None)
    other_account = state_record("TS-9", TradingState.NORMAL, "09:00", account_id="A2")

    assert gate([], "10:00", targets={C1: 5, C2: 0}, records=(NORMAL_AT_0900, NORMAL_AT_0900)).view(C1).status is G.NO_BLOCK_FOUND
    for records in ((NORMAL_AT_0900, dataclasses.replace(NORMAL_AT_0900, cause_code="other")), (NORMAL_AT_0900, halted_same_time),
                    (other_account,)):
        with pytest.raises(ValueError):
            gate([], "10:00", targets={C1: 5, C2: 0}, records=records)


def test_confirmed_labels_in_identifiers_change_nothing():
    """입력: 사건 ID가 "E-BROKER-CONFIRMED"인 체결 통보와 원인 코드·승인자 참조에 "CONFIRMED"가 들어간 NORMAL 기록 (UNKNOWN +5).
    출력: 판정은 증거 종류로만 정해진다. FILLS_ONLY, 주문 UNKNOWN, 모든 월물 BLOCKED. 문자열로 브로커 확인을 주장하지 않는다."""
    items = unknown_c5() + [evidence("E-BROKER-CONFIRMED", "C-5", 5, S.FILLED, K.FILL_NOTIFICATION, "09:57", filled=5)]
    record = state_record("TS-CONFIRMED", TradingState.NORMAL, "09:58", cause="CONFIRMED_RECONCILED", approver="CONFIRMED")

    report = gate(items, "10:00", fills=[make_fill("X-1", "C-5", 5, "09:57")], records=(record,))

    assert report.evidence.assessments[-1].disposition is D.FILLS_ONLY
    assert report.evidence.snapshot.records()[0].status is S.UNKNOWN
    assert_all_blocked(report, "UNKNOWN_ORDER_PRESENT")


def test_fill_notice_does_not_confirm_a_pending_cancel():
    """입력: 09:50 +10 접수, 09:56 취소 요청, 09:57 체결 +3 통보 (PARTIALLY_FILLED로 보고). 판단 10:00, 목표 C1 +5.
    출력: FILLS_ONLY. 주문은 CANCEL_REQUESTED(체결 3) 그대로, 최악 경우 롱 3 + 7 = 10, C1 BLOCKED(CANCEL_PENDING) (R9-6:
    취소 요청 중 체결은 반영하고 남은 수량은 계속 넣는다). 체결 통보는 취소 결과를 확인하지 않는다."""
    items = [
        evidence("E-1", "C-1", 10, S.PENDING_SUBMIT, K.LOCAL_RECORD, "09:49"),
        evidence("E-2", "C-1", 10, S.ACCEPTED, K.REQUEST_RESPONSE, "09:50"),
        evidence("E-3", "C-1", 10, S.CANCEL_REQUESTED, K.LOCAL_RECORD, "09:56"),
        evidence("E-4", "C-1", 10, S.PARTIALLY_FILLED, K.FILL_NOTIFICATION, "09:57", filled=3),
    ]

    report = gate(items, "10:00", targets={C1: 5, C2: 0}, fills=[make_fill("X-1", "C-1", 3, "09:57")])

    assert report.evidence.assessments[-1].disposition is D.FILLS_ONLY
    record = report.evidence.snapshot.records()[0]
    assert (record.status, record.filled_quantity) == (S.CANCEL_REQUESTED, 3)
    assert report.risk.risk.view(C1).worst_case.worst_long_before == 10
    assert report.view(C1).status is G.BLOCKED
    assert "CANCEL_PENDING" in report.view(C1).blocking_reasons


def pending_cancel_c1():
    """09:49 매수 +10 제출, 09:50 접수 응답 (B-C-1), 09:56 취소 요청 (시스템 기록, Broker Order ID 없음)."""
    return [
        evidence("E-1", "C-1", 10, S.PENDING_SUBMIT, K.LOCAL_RECORD, "09:49"),
        evidence("E-2", "C-1", 10, S.ACCEPTED, K.REQUEST_RESPONSE, "09:50"),
        evidence("E-3", "C-1", 10, S.CANCEL_REQUESTED, K.LOCAL_RECORD, "09:56"),
    ]


@pytest.mark.parametrize(
    "stale",
    [
        evidence("E-5", "C-1", 10, S.PARTIALLY_FILLED, K.REQUEST_RESPONSE, "09:55", "09:58", filled=3),
        evidence("E-5", "C-1", 10, S.PARTIALLY_FILLED, K.STATUS_QUERY_RESPONSE, "09:55", "09:58", filled=3, requested="09:54"),
        evidence("E-5", "C-1", 10, S.EXPIRED, K.REQUEST_RESPONSE, "09:55", "09:58", filled=3, cancelled=7),
        evidence("E-5", "C-1", 10, S.PARTIALLY_FILLED, K.STATUS_QUERY_RESPONSE, "09:57", "09:58", filled=3, requested="09:55"),
    ],
)
def test_review_h1_report_older_than_a_pending_cancel_is_deferred(stale):
    """검토 H1. 입력: 09:56 취소 요청 중인 +10 주문에 09:53 체결 +3 통보가 09:57에 도착 (FILLS_ONLY). 그 뒤 취소 요청보다 이른 09:55에
    관측된 (a) PARTIALLY_FILLED 응답, (b) 09:54에 요청한 PARTIALLY_FILLED 조회, (c) EXPIRED 응답, 또는 (d) 09:55에 요청해 09:57에
    관측한 PARTIALLY_FILLED 조회(상태 조회는 요청 시각 기준)가 09:58에 도착. 판단 10:00, 목표 C1 +12.
    출력: 그 보고는 DEFERRED(REPORT_PRECEDES_PENDING_REQUEST). 주문은 CANCEL_REQUESTED(체결 3), 최악 경우 롱 3 + 7 = 10, C1
    BLOCKED(CANCEL_PENDING) (R9-6, AT-0009-3). 수정 전에는 체결 통보 기록의 이른 발생 시각 때문에 Slice 2의 시각 검사를 비켜 가
    (a)(b) NO_BLOCK_FOUND, (c) 최악 경우 3이었다."""
    notice = evidence("E-4", "C-1", 10, S.PARTIALLY_FILLED, K.FILL_NOTIFICATION, "09:53", "09:57", filled=3)

    report = gate(pending_cancel_c1() + [notice, stale], "10:00", targets={C1: 12, C2: 0}, fills=[make_fill("X-1", "C-1", 3, "09:53")])

    assert (report.evidence.assessments[-1].disposition, report.evidence.assessments[-1].reasons) == (
        D.DEFERRED, ("REPORT_PRECEDES_PENDING_REQUEST",))
    record = report.evidence.snapshot.records()[0]
    assert (record.status, record.filled_quantity) == (S.CANCEL_REQUESTED, 3)
    assert report.risk.risk.view(C1).worst_case.worst_long_before == 10
    assert report.view(C1).blocking_reasons == ("CANCEL_PENDING",)


def test_review_h1_report_older_than_a_pending_replace_is_deferred():
    """검토 H1. 입력: 기존 C-9 +5를 09:56에 +8(C-9R)로 정정 요청. 09:53 체결 +2 통보가 09:57에 도착 (FILLS_ONLY), 그 뒤 09:55에 관측된
    PARTIALLY_FILLED(2) 응답이 09:58에 도착. 판단 10:00.
    출력: 그 응답은 DEFERRED(REPORT_PRECEDES_PENDING_REQUEST). C-9는 REPLACE_REQUESTED, 최악 경우 롱 2 + 3 + 8 = 13, C1 BLOCKED(REPLACE_PENDING) (RP-1, RP-3)."""
    items = [
        evidence("E-1", "C-9", 5, S.PENDING_SUBMIT, K.LOCAL_RECORD, "09:49"),
        evidence("E-2", "C-9", 5, S.ACCEPTED, K.REQUEST_RESPONSE, "09:50"),
        evidence("E-3", "C-9", 5, S.REPLACE_REQUESTED, K.LOCAL_RECORD, "09:56", replacement=8),
        evidence("E-3R", "C-9R", 8, S.PENDING_SUBMIT, K.LOCAL_RECORD, "09:56"),
        evidence("E-4", "C-9", 5, S.PARTIALLY_FILLED, K.FILL_NOTIFICATION, "09:53", "09:57", filled=2),
        evidence("E-5", "C-9", 5, S.PARTIALLY_FILLED, K.REQUEST_RESPONSE, "09:55", "09:58", filled=2),
    ]

    report = gate(items, "10:00", targets={C1: 12, C2: 0}, fills=[make_fill("X-1", "C-9", 2, "09:53")])

    stale = next(a for a in report.evidence.assessments if a.event_id == "E-5")
    assert (stale.disposition, stale.reasons) == (D.DEFERRED, ("REPORT_PRECEDES_PENDING_REQUEST",))
    assert report.evidence.snapshot.records()[0].status is S.REPLACE_REQUESTED
    assert report.risk.risk.view(C1).worst_case.worst_long_before == 13
    assert report.view(C1).blocking_reasons == ("REPLACE_PENDING",)


@pytest.mark.parametrize(
    ("middle", "report_item", "status"),
    [
        (evidence("E-3", "C-1", 5, S.CANCEL_REQUESTED, K.LOCAL_RECORD, "09:56"),
         evidence("E-4", "C-1", 5, S.CANCELLED, K.REQUEST_RESPONSE, "09:57", cancelled=5, broker_id="B-99"), S.CANCEL_REQUESTED),
        (evidence("E-3", "C-1", 5, S.UNKNOWN, K.LOCAL_RECORD, "09:56"),
         evidence("E-4", "C-1", 5, S.ACCEPTED, K.STATUS_QUERY_RESPONSE, "09:57", requested="09:57", broker_id="B-99"), S.UNKNOWN),
    ],
)
def test_review_h2_first_known_broker_order_id_is_kept(middle, report_item, status):
    """검토 H2. 입력: C-1 +5 접수 응답 (Broker Order ID B-C-1), Broker Order ID 없는 시스템 기록 (a) 취소 요청, (b) UNKNOWN, 그 뒤 B-99의
    (a) CANCELLED 응답, (b) ACCEPTED 상태 조회. 판단 10:00, 목표 C1 +5.
    출력: REJECTED(BROKER_ORDER_ID_MISMATCH): 바로 앞 기록이 아니라 처음 알려진 B-C-1과 비교한다. 주문은 (a) CANCEL_REQUESTED, (b) UNKNOWN,
    최악 경우 롱 5, 모든 월물 BLOCKED(ORDER_EVIDENCE_CONFLICT). 수정 전 (a)는 CANCELLED/B-99, 최악 경우 0, NO_BLOCK_FOUND였다."""
    items = [
        evidence("E-1", "C-1", 5, S.PENDING_SUBMIT, K.LOCAL_RECORD, "09:49"),
        evidence("E-2", "C-1", 5, S.ACCEPTED, K.REQUEST_RESPONSE, "09:50"),
        middle,
        report_item,
    ]

    report = gate(items, "10:00", targets={C1: 5, C2: 0})

    assert (report.evidence.assessments[-1].disposition, report.evidence.assessments[-1].reasons) == (
        D.REJECTED, ("BROKER_ORDER_ID_MISMATCH",))
    assert report.evidence.snapshot.records()[0].status is status
    assert report.risk.risk.view(C1).worst_case.worst_long_before == 5
    assert_all_blocked(report, "ORDER_EVIDENCE_CONFLICT")


def test_review_h2_system_record_for_another_broker_order_is_an_integrity_error():
    """검토 H2. 입력: B-C-1로 접수된 주문에 Broker Order ID B-99를 적은 시스템 UNKNOWN 기록.
    출력: OrderEventIntegrityError. 시스템 기록을 버려 UNKNOWN을 잃지 않는다."""
    items = [
        evidence("E-1", "C-1", 5, S.PENDING_SUBMIT, K.LOCAL_RECORD, "09:49"),
        evidence("E-2", "C-1", 5, S.ACCEPTED, K.REQUEST_RESPONSE, "09:50"),
        evidence("E-3", "C-1", 5, S.UNKNOWN, K.LOCAL_RECORD, "09:56", broker_id="B-99"),
    ]

    with pytest.raises(OrderEventIntegrityError):
        orders_from_evidence_as_of(items, at("10:00"), account_id="A1", confirming_source=SRC.BROKER, completeness=COMPLETE,
                                   completeness_ref="x")


def at_0012_5_events():
    """ADR-0012 AT-0012-5. C-301 +5 접수 (09:50), 체결 X-11 +2 통보 (09:51), 취소 요청 (09:52, 체결 2), 브로커 취소 확정 (09:53 발생,
    09:54 이용 가능): 누적 체결 3, 취소 2."""
    return [
        evidence("E-1", "C-301", 5, S.PENDING_SUBMIT, K.LOCAL_RECORD, "09:49"),
        evidence("E-2", "C-301", 5, S.ACCEPTED, K.REQUEST_RESPONSE, "09:50"),
        evidence("E-3", "C-301", 5, S.PARTIALLY_FILLED, K.FILL_NOTIFICATION, "09:51", filled=2),
        evidence("E-4", "C-301", 5, S.CANCEL_REQUESTED, K.LOCAL_RECORD, "09:52", filled=2),
        evidence("E-5", "C-301", 5, S.CANCELLED, K.REQUEST_RESPONSE, "09:53", "09:54", filled=3, cancelled=2),
    ]


def test_review_h3_cancel_confirmation_with_other_fills_marks_the_order_unknown():
    """검토 H3 (ADR-0012 AT-0012-5, BR-12, ADR-0009 RP-4). 입력: AT-0012-5의 취소 확정(누적 체결 3 ≠ 확인된 체결 2). (a) 판단 09:55, 장부 체결
    X-11 2. (b) 09:55 체결 X-12 +1 통보(누적 3)가 09:56에 도착, 판단 10:00. (c) (b)에 상태 조회(09:57 요청) 결과 CANCELLED(체결 3, 취소 2)가
    09:58에 도착.
    출력: 취소 확정은 MARKED_UNKNOWN(REPORTED_FILLS_DIFFER_FROM_CONFIRMED_FILLS): 그 확정으로 최악 경우를 줄이지 않는다. (a) UNKNOWN(체결 2),
    최악 경우 롱 2 + 3 = 5. (b) UNKNOWN(체결 3), 최악 경우 3 + 2 = 5 (체결 한 건으로 해소하지 않음). (c) 조회는
    DEFERRED(RESOLUTION_WOULD_LOWER_UNKNOWN_WORST_CASE): 줄이는 해소에는 대조 일치도 필요하다. 모두 BLOCKED(UNKNOWN_ORDER_PRESENT).
    수정 전 (b)는 CANCELLED, 최악 경우 3, NO_BLOCK_FOUND였다."""
    x11, x12 = make_fill("X-11", "C-301", 2, "09:51"), make_fill("X-12", "C-301", 1, "09:55")
    x12_notice = evidence("E-6", "C-301", 5, S.PARTIALLY_FILLED, K.FILL_NOTIFICATION, "09:55", "09:56", filled=3)
    query = evidence("E-7", "C-301", 5, S.CANCELLED, K.STATUS_QUERY_RESPONSE, "09:57", "09:58", filled=3, cancelled=2, requested="09:57")

    row_2 = gate(at_0012_5_events(), "09:55", targets={C1: 5, C2: 0}, fills=[x11])
    row_3 = gate(at_0012_5_events() + [x12_notice], "10:00", targets={C1: 5, C2: 0}, fills=[x11, x12])
    queried = gate(at_0012_5_events() + [x12_notice, query], "10:00", targets={C1: 5, C2: 0}, fills=[x11, x12])

    confirmation = next(a for a in row_2.evidence.assessments if a.event_id == "E-5")
    assert (confirmation.disposition, confirmation.reasons) == (D.MARKED_UNKNOWN, ("REPORTED_FILLS_DIFFER_FROM_CONFIRMED_FILLS",))
    for report, filled in ((row_2, 2), (row_3, 3), (queried, 3)):
        record = report.evidence.snapshot.records()[0]
        assert (record.status, record.filled_quantity) == (S.UNKNOWN, filled)
        assert report.risk.risk.view(C1).worst_case.worst_long_before == 5
        assert_all_blocked(report, "UNKNOWN_ORDER_PRESENT")
    assert (queried.evidence.assessments[-1].disposition, queried.evidence.assessments[-1].reasons) == (
        D.DEFERRED, ("RESOLUTION_WOULD_LOWER_UNKNOWN_WORST_CASE",))


def test_review_h3_partial_cancel_report_with_other_fills_marks_unknown():
    """검토 H3. 입력: 접수된 +5 주문 (확인된 체결 0)에 09:56 요청 상태 조회 결과 PARTIALLY_FILLED(누적 체결 1, 확인 취소 2)가 09:57에 도착.
    출력: MARKED_UNKNOWN: 확인 취소를 늘리는 보고의 누적 체결이 확인된 체결과 달라 남은 수량을 줄이지 않는다 (RP-4). 주문 UNKNOWN(체결 0),
    최악 경우 롱 5, BLOCKED."""
    items = [
        evidence("E-1", "C-1", 5, S.PENDING_SUBMIT, K.LOCAL_RECORD, "09:49"),
        evidence("E-2", "C-1", 5, S.ACCEPTED, K.REQUEST_RESPONSE, "09:50"),
        evidence("E-3", "C-1", 5, S.PARTIALLY_FILLED, K.STATUS_QUERY_RESPONSE, "09:56", "09:57", filled=1, cancelled=2, requested="09:56"),
    ]

    report = gate(items, "10:00")

    assert report.evidence.assessments[-1].disposition is D.MARKED_UNKNOWN
    assert (report.evidence.snapshot.records()[0].status, report.risk.risk.view(C1).worst_case.worst_long_before) == (S.UNKNOWN, 5)
    assert_all_blocked(report, "UNKNOWN_ORDER_PRESENT")


def test_unknown_recorded_after_a_pending_cancel_keeps_the_later_bound():
    """입력: 09:56 취소 요청 중인 +10 주문에 09:53 체결 +3 통보(09:57 도착). 09:54에 분류된 UNKNOWN 시스템 기록이 09:58에야 기록됨. 09:55에
    요청한 상태 조회 결과 PARTIALLY_FILLED(3)가 09:59에 도착. 판단 10:00.
    출력: 조회는 DEFERRED(STATUS_QUERY_REQUESTED_BEFORE_UNKNOWN). 대기 상태가 이어지면 구간 시작 시각(09:56)을 앞으로 당기지 않으므로,
    취소 요청 전에 요청한 조회로 UNKNOWN을 해소하지 않는다. 주문은 UNKNOWN(체결 3)."""
    items = pending_cancel_c1() + [
        evidence("E-4", "C-1", 10, S.PARTIALLY_FILLED, K.FILL_NOTIFICATION, "09:53", "09:57", filled=3),
        evidence("E-5", "C-1", 10, S.UNKNOWN, K.LOCAL_RECORD, "09:54", "09:58", filled=3),
        evidence("E-6", "C-1", 10, S.PARTIALLY_FILLED, K.STATUS_QUERY_RESPONSE, "09:59", filled=3, requested="09:55"),
    ]

    report = gate(items, "10:00", fills=[make_fill("X-1", "C-1", 3, "09:53")])

    assert (report.evidence.assessments[-1].disposition, report.evidence.assessments[-1].reasons) == (
        D.DEFERRED, ("STATUS_QUERY_REQUESTED_BEFORE_UNKNOWN",))
    assert report.evidence.snapshot.records()[0].status is S.UNKNOWN


def test_unknown_episode_and_conflict_after_the_decision_do_not_block_it():
    """입력: 09:50 +5 접수, 승인 NORMAL(09:00). 판단 10:00 뒤에만 이용 가능한 (a) 10:10 UNKNOWN과 10:20 ACCEPTED 조회 결과, (b) 10:05
    시뮬레이터 보고(REJECTED 판정). 목표 C1 +10.
    출력: 10:00 판단은 늦은 증거를 쓰지 않는다: 주문 ACCEPTED, C1 후보 +5, 노출 10,000 < 20,000 → NO_BLOCK_FOUND (ADR-0001 I-1)."""
    accepted = [
        evidence("E-1", "C-1", 5, S.PENDING_SUBMIT, K.LOCAL_RECORD, "09:49"),
        evidence("E-2", "C-1", 5, S.ACCEPTED, K.REQUEST_RESPONSE, "09:50"),
    ]
    late_episode = [
        evidence("E-3", "C-1", 5, S.UNKNOWN, K.LOCAL_RECORD, "10:10"),
        evidence("E-4", "C-1", 5, S.ACCEPTED, K.STATUS_QUERY_RESPONSE, "10:15", "10:20", requested="10:15"),
    ]
    late_conflict = [evidence("E-3", "C-1", 5, S.CANCELLED, K.STATUS_QUERY_RESPONSE, "10:04", "10:05", source=SRC.SIMULATOR,
                              cancelled=5, requested="10:04")]

    for items in (accepted + late_episode, accepted + late_conflict):
        report = gate(items, "10:00", targets={C1: 10, C2: 0})
        assert report.evidence.snapshot.records()[0].status is S.ACCEPTED
        assert report.view(C1).status is G.NO_BLOCK_FOUND


def test_release_recorded_at_the_resolution_instant_does_not_cover_it():
    """입력: CASE 3의 UNKNOWN과 09:57에 이용 가능한 ACCEPTED 조회 결과. 승인 NORMAL 기록의 상태 시각도 09:57. 판단 10:00.
    출력: BLOCKED(UNKNOWN_RESOLVED_AFTER_TRADING_STATE_RECORD). 같은 시각이면 해소를 안 뒤의 해제인지 알 수 없다."""
    items = unknown_c5() + [evidence("E-3", "C-5", 5, S.ACCEPTED, K.STATUS_QUERY_RESPONSE, "09:56", "09:57", requested="09:56")]
    same_instant = state_record("TS-4", TradingState.NORMAL, "09:57", cause="UNKNOWN_RESOLVED")

    report = gate(items, "10:00", targets={C1: 10, C2: 0}, records=(same_instant,))

    assert_all_blocked(report, "UNKNOWN_RESOLVED_AFTER_TRADING_STATE_RECORD")


def test_review_h3_fill_known_only_to_the_ledger_does_not_pass():
    """검토 H3. 입력: AT-0012-5의 취소 확정 뒤 체결 X-12가 장부에만 있고 그 체결 통보 증거는 없음. 판단 10:00.
    출력: OrderIntegrityError (증거로 확인된 체결 2 ≠ 장부 3). 수정 전에는 CANCELLED, 최악 경우 3, NO_BLOCK_FOUND였다."""
    fills = [make_fill("X-11", "C-301", 2, "09:51"), make_fill("X-12", "C-301", 1, "09:55")]

    with pytest.raises(OrderIntegrityError):
        gate(at_0012_5_events(), "10:00", targets={C1: 5, C2: 0}, fills=fills)


@pytest.mark.parametrize(
    ("first", "reported"),
    [
        (S.ACCEPTED, dict(status=S.EXPIRED)),
        (S.PENDING_SUBMIT, dict(status=S.EXPIRED)),
        (S.ACCEPTED, dict(status=S.CANCELLED, cancelled=3)),
    ],
)
def test_review_m1_m4_fill_notice_sets_only_the_status_its_fills_imply(first, reported):
    """검토 M1·M4. 입력: 진행 중 주문 +5 ((a)(c) 접수, (b) 제출 대기)에 체결 +2 통보가 (a)(b) EXPIRED, (c) IOC처럼 CANCELLED(취소 3)로
    보고됨. 장부에 체결 2. 판단 10:00, 목표 C1 +5.
    출력: FILLS_ONLY. 주문은 PARTIALLY_FILLED(체결 2, 취소 0): 체결은 보존하고 통보에 적힌 종료·취소는 확인으로 쓰지 않는다. 최악 경우
    롱 2 + 3 = 5. 수정 전 (a)(b)는 EXPIRED로 최악 경우 2, (c)는 통보 전체가 빠져 OrderIntegrityError였다."""
    items = [evidence("E-1", "C-1", 5, S.PENDING_SUBMIT, K.LOCAL_RECORD, "09:49")]
    if first is S.ACCEPTED:
        items.append(evidence("E-2", "C-1", 5, S.ACCEPTED, K.REQUEST_RESPONSE, "09:50"))
    items.append(evidence("E-3", "C-1", 5, kind=K.FILL_NOTIFICATION, occurred="09:57", filled=2, **reported))

    report = gate(items, "10:00", targets={C1: 5, C2: 0}, fills=[make_fill("X-1", "C-1", 2, "09:57")])

    assert report.evidence.assessments[-1].disposition is D.FILLS_ONLY
    record = report.evidence.snapshot.records()[0]
    assert (record.status, record.filled_quantity, record.cancelled_quantity) == (S.PARTIALLY_FILLED, 2, 0)
    assert report.risk.risk.view(C1).worst_case.worst_long_before == 5


def test_review_m1_full_fill_notice_on_a_working_order_is_used_as_reported():
    """대조군. 입력: 접수된 +5 주문에 체결 +5 통보 (FILLED로 보고). 출력: USED, 주문 FILLED (체결 수량이 뜻하는 상태와 같음, AT-0012-3)."""
    items = [
        evidence("E-1", "C-1", 5, S.PENDING_SUBMIT, K.LOCAL_RECORD, "09:49"),
        evidence("E-2", "C-1", 5, S.ACCEPTED, K.REQUEST_RESPONSE, "09:50"),
        evidence("E-3", "C-1", 5, S.FILLED, K.FILL_NOTIFICATION, "09:57", filled=5),
    ]

    report = gate(items, "10:00", fills=[make_fill("X-1", "C-1", 5, "09:57")])

    assert report.evidence.assessments[-1].disposition is D.USED
    assert report.evidence.snapshot.records()[0].status is S.FILLED


@pytest.mark.parametrize("first_kind", [K.STATUS_QUERY_RESPONSE, K.REQUEST_RESPONSE])
def test_review_m2_terminal_report_followed_by_another_state_is_an_integrity_error(first_kind):
    """검토 M2. 입력: UNKNOWN +5에 09:57 REJECTED 보고 ((a) 상태 조회, (b) 요청 응답. 둘 다 DEFERRED) 뒤 09:59 ACCEPTED 상태 조회.
    출력: OrderEventIntegrityError. 종료 보고 뒤의 다른 상태를 시간 순서만으로 골라 UNKNOWN을 해소하지 않는다 (수정 전에는 ACCEPTED로 해소)."""
    requested = "09:56" if first_kind is K.STATUS_QUERY_RESPONSE else None
    items = unknown_c5() + [
        evidence("E-3", "C-5", 5, S.REJECTED, first_kind, "09:57", requested=requested),
        evidence("E-4", "C-5", 5, S.ACCEPTED, K.STATUS_QUERY_RESPONSE, "09:59", requested="09:58"),
    ]

    with pytest.raises(OrderEventIntegrityError, match="terminal"):
        orders_from_evidence_as_of(items, at("10:00"), account_id="A1", confirming_source=SRC.BROKER, completeness=COMPLETE,
                                   completeness_ref="x")


@pytest.mark.parametrize("via_unknown_report", [False, True])
def test_review_m3_unknown_during_replace_is_not_resolved_by_dropping_the_replacement(via_unknown_report):
    """검토 M3 (RP-5). 입력: 기존 C-9 +5를 09:55에 +8(C-9R)로 정정 요청, 09:56 응답 timeout으로 C-9 UNKNOWN(정정 수량 유지). 09:58 ACCEPTED
    상태 조회. (b)는 그 전에 정정 정보 없는 UNKNOWN 조회 결과(09:57)가 먼저 도착. 판단 10:00.
    출력: 조회 결과는 모두 DEFERRED(UNKNOWN_DURING_REPLACE_NOT_RESOLVED 포함). C-9는 UNKNOWN, 최악 경우 롱 5 + 8 = 13, BLOCKED.
    수정 전 (b)는 정정 정보가 빠진 UNKNOWN을 거쳐 C-9가 ACCEPTED로 해소되었다."""
    items = [
        evidence("E-1", "C-9", 5, S.ACCEPTED, K.REQUEST_RESPONSE, "09:50"),
        evidence("E-2", "C-9", 5, S.REPLACE_REQUESTED, K.LOCAL_RECORD, "09:55", replacement=8),
        evidence("E-3", "C-9R", 8, S.PENDING_SUBMIT, K.LOCAL_RECORD, "09:55"),
        evidence("E-4", "C-9", 5, S.UNKNOWN, K.LOCAL_RECORD, "09:56", replacement=8),
        evidence("E-6", "C-9", 5, S.ACCEPTED, K.STATUS_QUERY_RESPONSE, "09:58", requested="09:58"),
    ]
    if via_unknown_report:
        items.append(evidence("E-5", "C-9", 5, S.UNKNOWN, K.STATUS_QUERY_RESPONSE, "09:57", requested="09:57"))

    report = gate(items, "10:00")

    for assessment in report.evidence.assessments:
        if assessment.event_id in ("E-5", "E-6"):
            assert assessment.disposition is D.DEFERRED
            assert "UNKNOWN_DURING_REPLACE_NOT_RESOLVED" in assessment.reasons
    assert report.evidence.snapshot.records()[0].status is S.UNKNOWN
    assert report.risk.risk.view(C1).worst_case.worst_long_before == 13
    assert_all_blocked(report, "UNKNOWN_ORDER_PRESENT")


def test_review_m5_release_recorded_before_the_halt_was_known_does_not_apply():
    """검토 M5. 입력: Kill Switch HALTED (09:55 발생, 09:59 이용 가능)와 승인 NORMAL (09:56 발생, 09:57 이용 가능). 주문 없음, 목표 C1 +5.
    판단 10:00.
    출력: 적용한 상태 HALTED, 모든 월물 BLOCKED(TRADING_STATE_HALTED). NORMAL 기록은 HALTED 기록이 알려지기 전에 만들어졌으므로 그 해제로
    볼 수 없다 (수정 전에는 NORMAL을 써 NO_BLOCK_FOUND)."""
    halted = state_record("TS-H", TradingState.HALTED, "09:55", "09:59", cause="MANUAL_KILL_SWITCH", approver=None)
    normal = state_record("TS-N", TradingState.NORMAL, "09:56", "09:57", cause="DAILY_OPEN")

    report = gate([], "10:00", targets={C1: 5, C2: 0}, records=(halted, normal))

    assert (report.trading_state_record, report.trading_state_applied) == (normal, TradingState.HALTED)
    assert_all_blocked(report, "TRADING_STATE_HALTED")


@pytest.mark.parametrize(
    ("options", "status", "reasons"),
    [
        (dict(targets={C1: 25, C2: 0}), G.BLOCKED, ("LIMIT_EXCEEDED",)),
        (dict(targets={C1: 20, C2: 0}), G.NOT_ASSESSABLE, ("LIMIT_BOUNDARY_RULE_OPEN",)),
        (dict(targets={C1: 5, C2: 0}, c1_price=None), G.NOT_ASSESSABLE, ("REFERENCE_PRICE_MISSING",)),
        (dict(targets={C1: 5, C2: 0}, c1_lot=None), G.BLOCKED, ("LOT_SIZE_MISSING",)),
    ],
)
def test_gate_keeps_slice_1_limit_and_local_results(options, status, reasons):
    """입력: 주문 없음, 승인 NORMAL 기록, 위험 증가 후보. (a) 목표 +25 (노출 25,000 > 한도 20,000), (b) 목표 +20 (노출 = 한도), (c) C1 참조
    가격 없음, (d) C1 lot size 없음.
    출력: (a) BLOCKED(LIMIT_EXCEEDED), (b) NOT_ASSESSABLE(LIMIT_BOUNDARY_RULE_OPEN), (c) NOT_ASSESSABLE(REFERENCE_PRICE_MISSING),
    (d) BLOCKED(LOT_SIZE_MISSING). Slice 1의 한도·로컬 결과를 그대로 반영한다."""
    view = gate([], "10:00", **options).view(C1)

    assert (view.candidate_effect, view.status) == (CandidateRiskEffect.RISK_INCREASING, status)
    assert (view.blocking_reasons if status is G.BLOCKED else view.unassessable_reasons) == reasons


@pytest.mark.parametrize(
    ("target", "effect", "status"),
    [
        (4, CandidateRiskEffect.CONTAINS_RISK_REDUCTION, G.BLOCKED),
        (-4, CandidateRiskEffect.CONTAINS_RISK_REDUCTION, G.BLOCKED),
        (-12, CandidateRiskEffect.RISK_INCREASING, G.NO_BLOCK_FOUND),
    ],
)
def test_buy_side_reduction_and_reversal_from_a_short_position(target, effect, status):
    """입력: 검증된 기준 포지션 C1 −10, 승인 NORMAL 기록. 목표 (a) +4 (매수 +14, 반전), (b) −4 (매수 +6, 축소), (c) −12 (매도 −2, 증가).
    출력: (a)(b) CONTAINS_RISK_REDUCTION, BLOCKED(RISK_REDUCTION_NOT_VERIFIED). (c) RISK_INCREASING, 노출 12,000 < 20,000이라
    NO_BLOCK_FOUND (ADR-0003 §6.2: 반전은 청산 다리와 신규 다리)."""
    view = gate([], "10:00", targets={C1: target, C2: 0}, c1=-10).view(C1)

    assert (view.candidate_effect, view.status) == (effect, status)
    if status is G.BLOCKED:
        assert view.blocking_reasons == ("RISK_REDUCTION_NOT_VERIFIED",)


def test_query_requested_after_a_late_fill_but_before_the_unknown_is_deferred():
    """입력: 09:55 UNKNOWN. 09:52에 일어난 체결 +3 통보가 09:56에 도착 (FILLS_ONLY). 09:53에 요청한 상태 조회 결과 PARTIALLY_FILLED(3)가
    09:58에 도착. 판단 10:00.
    출력: DEFERRED(STATUS_QUERY_REQUESTED_BEFORE_UNKNOWN). 기준은 UNKNOWN 구간을 시작한 기록(09:55)이며 체결 통보의 발생 시각(09:52)이 아니다."""
    items = unknown_c5() + [
        evidence("E-3", "C-5", 5, S.PARTIALLY_FILLED, K.FILL_NOTIFICATION, "09:52", "09:56", filled=3),
        evidence("E-4", "C-5", 5, S.PARTIALLY_FILLED, K.STATUS_QUERY_RESPONSE, "09:57", "09:58", filled=3, requested="09:53"),
    ]

    report = gate(items, "10:00", fills=[make_fill("X-1", "C-5", 3, "09:52")])

    assert (report.evidence.assessments[-1].disposition, report.evidence.assessments[-1].reasons) == (
        D.DEFERRED, ("STATUS_QUERY_REQUESTED_BEFORE_UNKNOWN",))
    assert report.evidence.snapshot.records()[0].status is S.UNKNOWN


def test_case_8_evidence_only_of_another_account_is_rejected():
    """입력: 증거가 모두 계좌 A2의 것인데 계좌 A1로 판정 요청. 출력: ValueError (계좌 하나로만 이뤄진 기록이라 Slice 2의 계좌 혼합
    검사로는 잡히지 않는 경우)."""
    items = [evidence("E-1", "C-5", 5, S.PENDING_SUBMIT, K.LOCAL_RECORD, "09:50", account_id="A2")]

    with pytest.raises(ValueError):
        orders_from_evidence_as_of(items, at("10:00"), account_id="A1", confirming_source=SRC.BROKER, completeness=COMPLETE,
                                   completeness_ref="x")


def accepted_c1(quantity=5):
    """09:49 매수 제출, 09:50 접수 응답 (Broker Order ID B-C-1)."""
    return [
        evidence("E-1", "C-1", quantity, S.PENDING_SUBMIT, K.LOCAL_RECORD, "09:49"),
        evidence("E-2", "C-1", quantity, S.ACCEPTED, K.REQUEST_RESPONSE, "09:50"),
    ]


def cancel_pending_with_fill():
    """접수된 +5 주문에 09:51 체결 +2 통보, 09:56 취소 요청 (시스템 기록, 체결 2)."""
    return accepted_c1() + [
        evidence("E-3", "C-1", 5, S.PARTIALLY_FILLED, K.FILL_NOTIFICATION, "09:51", filled=2),
        evidence("E-4", "C-1", 5, S.CANCEL_REQUESTED, K.LOCAL_RECORD, "09:56", filled=2),
    ]


@pytest.mark.parametrize(
    ("stale", "reason"),
    [
        (evidence("E-5", "C-1", 5, S.UNKNOWN, K.REQUEST_RESPONSE, "09:55", "09:58", filled=2), "REPORTED_STATUS_UNKNOWN"),
        (evidence("E-5", "C-1", 5, S.UNKNOWN, K.STATUS_QUERY_RESPONSE, "09:57", "09:58", filled=2, requested="09:55"),
         "REPORTED_STATUS_UNKNOWN"),
        (evidence("E-5", "C-1", 5, S.CANCELLED, K.REQUEST_RESPONSE, "09:55", "09:58", filled=3, cancelled=2),
         "REPORTED_FILLS_DIFFER_FROM_CONFIRMED_FILLS"),
        (evidence("E-5", "C-1", 5, S.PARTIALLY_FILLED, K.REQUEST_RESPONSE, "09:55", "09:58", filled=3),
         "REPORTED_FILLS_DIFFER_FROM_CONFIRMED_FILLS"),
    ],
)
def test_review2_h1_stale_report_with_restrictive_content_marks_unknown(stale, reason):
    """2차 검토 HIGH-1. 입력: 체결 2가 확인된 +5 주문이 09:56부터 취소 요청 중. 취소 요청보다 이른 관측의 보고가 09:58에 도착: (a) UNKNOWN 응답,
    (b) 09:55에 요청한 조회의 UNKNOWN, (c) 체결 3·취소 2의 CANCELLED 응답, (d) 체결 3의 PARTIALLY_FILLED 응답. 판단 10:00, 목표 C1 +5, C2 +2.
    출력: MARKED_UNKNOWN과 사유. 주문은 UNKNOWN(확인된 체결 2), 최악 경우 롱 2 + 3 = 5, 모든 월물 BLOCKED. 오래된 보고라도 UNKNOWN이나
    확인되지 않은 체결을 알리면 버리지 않는다 (BR-6, RP-4). 1차 수정 뒤에는 DEFERRED로 버려져 두 월물이 NO_BLOCK_FOUND였다."""
    report = gate(cancel_pending_with_fill() + [stale], "10:00", targets={C1: 5, C2: 2}, fills=[make_fill("X-1", "C-1", 2, "09:51")])

    assert (report.evidence.assessments[-1].disposition, report.evidence.assessments[-1].reasons) == (D.MARKED_UNKNOWN, (reason,))
    record = report.evidence.snapshot.records()[0]
    assert (record.status, record.filled_quantity) == (S.UNKNOWN, 2)
    assert report.risk.risk.view(C1).worst_case.worst_long_before == 5
    assert_all_blocked(report, "UNKNOWN_ORDER_PRESENT")


@pytest.mark.parametrize(
    ("base", "notice", "fills"),
    [
        (accepted_c1(), evidence("E-5", "C-1", 5, S.UNKNOWN, K.FILL_NOTIFICATION, "09:57", filled=2), [("X-1", 2, "09:57")]),
        (accepted_c1(), evidence("E-5", "C-1", 5, S.UNKNOWN, K.FILL_NOTIFICATION, "09:57", filled=5), [("X-1", 5, "09:57")]),
        (cancel_pending_with_fill(), evidence("E-5", "C-1", 5, S.UNKNOWN, K.FILL_NOTIFICATION, "09:57", filled=3),
         [("X-1", 2, "09:51"), ("X-2", 1, "09:57")]),
    ],
)
def test_review2_h2_fill_notice_reporting_unknown_marks_the_order_unknown(base, notice, fills):
    """2차 검토 HIGH-2. 입력: (a)(b) 접수된 +5 주문, (c) 취소 요청 중 주문에 UNKNOWN 상태로 보고된 체결 통보 (누적 체결 2 / 5 / 3). 판단 10:00,
    목표 C1 +10, C2 +2.
    출력: MARKED_UNKNOWN(REPORTED_STATUS_UNKNOWN). 통보의 체결은 확인된 체결로 남고 주문은 UNKNOWN, 최악 경우 롱 5, 모든 월물 BLOCKED (BR-6,
    §6.3). 1차 수정 뒤에는 체결이 뜻하는 상태나 CANCEL_REQUESTED로 남아 NO_BLOCK_FOUND였다."""
    report = gate(base + [notice], "10:00", targets={C1: 10, C2: 2},
                  fills=[make_fill(fill_id, "C-1", quantity, fill_at) for fill_id, quantity, fill_at in fills])

    assert (report.evidence.assessments[-1].disposition, report.evidence.assessments[-1].reasons) == (
        D.MARKED_UNKNOWN, ("REPORTED_STATUS_UNKNOWN",))
    record = report.evidence.snapshot.records()[0]
    assert (record.status, record.filled_quantity) == (S.UNKNOWN, notice.event.record.filled_quantity)
    assert report.risk.risk.view(C1).worst_case.worst_long_before == 5
    assert_all_blocked(report, "UNKNOWN_ORDER_PRESENT")


@pytest.mark.parametrize(
    "items",
    [
        [evidence("E-1", "C-1", 5, S.PENDING_SUBMIT, K.LOCAL_RECORD, "09:49"),
         evidence("E-2", "C-1", 5, S.CANCEL_REQUESTED, K.LOCAL_RECORD, "09:51"),
         evidence("E-3", "C-1", 5, S.ACCEPTED, K.REQUEST_RESPONSE, "09:50", "09:52", broker_id="B-77"),
         evidence("E-4", "C-1", 5, S.CANCELLED, K.REQUEST_RESPONSE, "09:53", cancelled=5, broker_id="B-88")],
        unknown_c5() + [
            evidence("E-3", "C-5", 5, S.ACCEPTED, K.REQUEST_RESPONSE, "09:56", broker_id="B-77"),
            evidence("E-4", "C-5", 5, S.ACCEPTED, K.STATUS_QUERY_RESPONSE, "09:58", requested="09:57", broker_id="B-88")],
    ],
)
def test_review2_h3_broker_order_id_from_a_deferred_report_is_remembered(items):
    """2차 검토 HIGH-3. 입력: (a) 09:49 제출, 09:51 취소 요청, 09:50에 관측된 접수 응답(B-77)이 09:52에 도착(DEFERRED), 09:53 B-88의 CANCELLED
    응답. (b) UNKNOWN 뒤 늦은 접수 응답(B-77, DEFERRED)과 B-88의 ACCEPTED 상태 조회. 판단 10:00.
    출력: B-88 보고는 REJECTED(BROKER_ORDER_ID_MISMATCH). 쓰지 않은 증거의 Broker Order ID도 기억한다. 최악 경우 롱 5, 모든 월물
    BLOCKED(ORDER_EVIDENCE_CONFLICT). 1차 수정 뒤 (a)는 CANCELLED/B-88, 최악 경우 0, NO_BLOCK_FOUND였다 (한 주문에 브로커 주문 둘, AT-0012-2)."""
    report = gate(items, "10:00", targets={C1: 5, C2: 0})

    assert (report.evidence.assessments[-1].disposition, report.evidence.assessments[-1].reasons) == (
        D.REJECTED, ("BROKER_ORDER_ID_MISMATCH",))
    assert report.risk.risk.view(C1).worst_case.worst_long_before == 5
    assert_all_blocked(report, "ORDER_EVIDENCE_CONFLICT")


@pytest.mark.parametrize(
    ("restrictive", "applied", "reason"),
    [
        (state_record("TS-H", TradingState.HALTED, "09:55", "09:58", approver=None), TradingState.HALTED, "TRADING_STATE_HALTED"),
        (state_record("TS-H", TradingState.HALTED, "09:55", "09:56", approver=None), TradingState.HALTED, "TRADING_STATE_HALTED"),
        (state_record("TS-R", TradingState.RESTRICTED, "09:55", "09:58", approver=None), TradingState.RESTRICTED,
         "TRADING_STATE_RESTRICTED"),
    ],
)
def test_review2_h4_release_decided_before_the_restriction_was_known(restrictive, applied, reason):
    """2차 검토 HIGH-4. 입력: (a) HALTED(09:55 상태, 09:58 이용 가능), (b) HALTED(09:56 이용 가능), (c) RESTRICTED(09:58 이용 가능)와 승인
    NORMAL 기록(09:56 상태, 09:59 이용 가능). 주문 없음, 목표 C1 +5. 판단 10:00.
    출력: 적용한 상태 (a)(b) HALTED, (c) RESTRICTED, C1 BLOCKED. NORMAL이 정해진 09:56까지(같은 시각 포함) 그 기록이 이용 가능하지
    않았으므로 해제로 볼 수 없다. 1차 수정 뒤에는 (a)(c) NORMAL, NO_BLOCK_FOUND였다."""
    normal = state_record("TS-N", TradingState.NORMAL, "09:56", "09:59", cause="DAILY_OPEN")

    report = gate([], "10:00", targets={C1: 5, C2: 0}, records=(restrictive, normal))

    assert (report.trading_state_record, report.trading_state_applied) == (normal, applied)
    assert report.view(C1).status is G.BLOCKED
    assert reason in report.view(C1).blocking_reasons


@pytest.mark.parametrize(
    "items",
    [
        accepted_c1() + [
            evidence("E-3", "C-1", 5, S.REJECTED, K.STATUS_QUERY_RESPONSE, "09:57", "09:59", requested="09:56"),
            evidence("E-4", "C-1", 5, S.ACCEPTED, K.STATUS_QUERY_RESPONSE, "09:58", requested="09:58")],
        unknown_c5() + [
            evidence("E-3", "C-5", 5, S.EXPIRED, K.STATUS_QUERY_RESPONSE, "09:57", "09:59", cancelled=5, requested="09:56"),
            evidence("E-4", "C-5", 5, S.ACCEPTED, K.STATUS_QUERY_RESPONSE, "09:58", requested="09:57")],
        accepted_c1() + [
            evidence("E-3", "C-1", 5, S.ACCEPTED, K.REQUEST_RESPONSE, "09:57", "09:59", cancelled=2),
            evidence("E-4", "C-1", 5, S.ACCEPTED, K.STATUS_QUERY_RESPONSE, "09:58", requested="09:58")],
    ],
)
def test_review2_h5_reports_are_checked_in_observation_order(items):
    """2차 검토 HIGH-5 (BR-11). 입력: 도착 순서가 관측 순서와 다른 보고. (a) 접수된 주문에 09:57 관측의 REJECTED 조회가 09:59에, 09:58 관측의
    ACCEPTED 조회가 09:58에 도착. (b) UNKNOWN 주문에 09:57 관측의 EXPIRED(취소 5) 조회가 09:59에, 09:58 관측의 ACCEPTED 조회가 09:58에 도착.
    (c) 접수된 주문에 09:57 관측의 취소 2 응답이 09:59에, 09:58 관측의 취소 0 조회가 09:58에 도착.
    출력: OrderEventIntegrityError. 관측 순서로 보면 (a)(b) 종료 뒤에 다른 상태가, (c) 누적 취소의 감소가 있다. 1차 수정 뒤에는 (a) REJECTED로
    최악 경우 0, (b) UNKNOWN 해소 뒤 EXPIRED로 0, (c) 남은 수량 3이 되었다."""
    with pytest.raises(OrderEventIntegrityError, match="decreased in observation order|observed in another state"):
        orders_from_evidence_as_of(items, at("10:00"), account_id="A1", confirming_source=SRC.BROKER, completeness=COMPLETE,
                                   completeness_ref="x")


@pytest.mark.parametrize("has_intent", [True, False])
@pytest.mark.parametrize("reported", [dict(status=S.EXPIRED), dict(status=S.CANCELLED, cancelled=3)])
def test_review2_h6_fill_notice_on_an_intent_or_as_first_evidence(has_intent, reported):
    """2차 검토 HIGH-6. 입력: (a) 주문 의도(INTENT)만 기록된 +5 주문, (b) 기록이 없는 주문에 체결 +2 통보가 EXPIRED나 CANCELLED(취소 3)로
    보고됨. 장부 체결 2. 판단 10:00, 목표 C1 +5.
    출력: FILLS_ONLY. 주문은 PARTIALLY_FILLED(체결 2, 취소 0), 최악 경우 롱 2 + 3 = 5. 1차 수정 뒤에는 통보를 그대로 써 최악 경우 2, 후보 +3,
    NO_BLOCK_FOUND였다."""
    items = [evidence("E-1", "C-1", 5, S.INTENT, K.LOCAL_RECORD, "09:49")] if has_intent else []
    items.append(evidence("E-3", "C-1", 5, kind=K.FILL_NOTIFICATION, occurred="09:57", filled=2, **reported))

    report = gate(items, "10:00", targets={C1: 5, C2: 0}, fills=[make_fill("X-1", "C-1", 2, "09:57")])

    assert report.evidence.assessments[-1].disposition is D.FILLS_ONLY
    record = report.evidence.snapshot.records()[0]
    assert (record.status, record.filled_quantity, record.cancelled_quantity) == (S.PARTIALLY_FILLED, 2, 0)
    assert report.risk.risk.view(C1).worst_case.worst_long_before == 5


def test_unknown_report_during_a_replace_keeps_the_replacement():
    """2차 검토 LOW-1 (RP-5). 입력: C-9 +5를 09:55에 +8(C-9R)로 정정 요청 중. 09:57 정정 정보 없는 UNKNOWN 조회 결과, 09:58 ACCEPTED 조회 결과.
    판단 10:00.
    출력: 첫 보고는 MARKED_UNKNOWN: C-9는 정정 수량을 유지한 UNKNOWN. 그 뒤 조회는 DEFERRED(UNKNOWN_DURING_REPLACE_NOT_RESOLVED). 최악 경우 롱
    5 + 8 = 13, BLOCKED."""
    items = [
        evidence("E-1", "C-9", 5, S.ACCEPTED, K.REQUEST_RESPONSE, "09:50"),
        evidence("E-2", "C-9", 5, S.REPLACE_REQUESTED, K.LOCAL_RECORD, "09:55", replacement=8),
        evidence("E-3", "C-9R", 8, S.PENDING_SUBMIT, K.LOCAL_RECORD, "09:55"),
        evidence("E-5", "C-9", 5, S.UNKNOWN, K.STATUS_QUERY_RESPONSE, "09:57", requested="09:57"),
        evidence("E-6", "C-9", 5, S.ACCEPTED, K.STATUS_QUERY_RESPONSE, "09:58", requested="09:58"),
    ]

    report = gate(items, "10:00")

    dispositions = {a.event_id: (a.disposition, a.reasons) for a in report.evidence.assessments}
    assert dispositions["E-5"] == (D.MARKED_UNKNOWN, ("REPORTED_STATUS_UNKNOWN",))
    assert dispositions["E-6"] == (D.DEFERRED, ("UNKNOWN_DURING_REPLACE_NOT_RESOLVED",))
    record = report.evidence.snapshot.records()[0]
    assert (record.status, record.replacement_quantity) == (S.UNKNOWN, 8)
    assert report.risk.risk.view(C1).worst_case.worst_long_before == 13
    assert_all_blocked(report, "UNKNOWN_ORDER_PRESENT")


@pytest.mark.parametrize("later_unknown_kind", [K.STATUS_QUERY_RESPONSE, K.REQUEST_RESPONSE])
def test_review3_h1_later_observed_unknown_report_is_not_dropped(later_unknown_kind):
    """3차 검토 HIGH-1. 입력: UNKNOWN +5 (09:55). 도착 순서: (1) 09:58에 관측된 UNKNOWN 보고(상태 조회 09:57 요청 또는 요청 응답, 체결 2)가
    09:58, (2) 09:56 체결 +2 통보가 09:59, (3) 09:56에 요청해 09:57에 관측한 PARTIALLY_FILLED(2) 조회가 10:00에 도착. 10:30 승인 NORMAL 기록.
    판단 10:31, 목표 C1 +10.
    출력: (1)은 쓰지 않지만 해소 기준 시각을 09:58로 늦추므로 (3)은 DEFERRED(STATUS_QUERY_REQUESTED_BEFORE_UNKNOWN). 주문은 UNKNOWN(체결 2),
    모든 월물 BLOCKED. 관측 순서로 보면 (3)보다 늦게 UNKNOWN이 관측되었으므로 해소가 아니다. 2차 수정 뒤에는 PARTIALLY_FILLED로 해소되어
    NO_BLOCK_FOUND였다."""
    requested = "09:57" if later_unknown_kind is K.STATUS_QUERY_RESPONSE else None
    items = unknown_c5() + [
        evidence("E-3", "C-5", 5, S.UNKNOWN, later_unknown_kind, "09:58", filled=2, requested=requested),
        evidence("E-4", "C-5", 5, S.PARTIALLY_FILLED, K.FILL_NOTIFICATION, "09:56", "09:59", filled=2),
        evidence("E-5", "C-5", 5, S.PARTIALLY_FILLED, K.STATUS_QUERY_RESPONSE, "09:57", "10:00", filled=2, requested="09:56"),
    ]
    release = state_record("TS-3", TradingState.NORMAL, "10:30", cause="DAILY_OPEN", approver="user:release-1")

    report = gate(items, "10:31", targets={C1: 10, C2: 0}, fills=[make_fill("X-1", "C-5", 2, "09:56")], records=(NORMAL_AT_0900, release))

    dispositions = {a.event_id: (a.disposition, a.reasons) for a in report.evidence.assessments}
    assert dispositions["E-5"] == (D.DEFERRED, ("STATUS_QUERY_REQUESTED_BEFORE_UNKNOWN",))
    record = report.evidence.snapshot.records()[0]
    assert (record.status, record.filled_quantity) == (S.UNKNOWN, 2)
    assert_all_blocked(report, "UNKNOWN_ORDER_PRESENT")


@pytest.mark.parametrize(
    ("base", "report_item", "target", "status", "block"),
    [
        ("replace", evidence("E-5", "C-9", 5, S.PARTIALLY_FILLED, K.STATUS_QUERY_RESPONSE, "09:56", filled=2, requested="09:56"), 18,
         S.REPLACE_REQUESTED, "REPLACE_PENDING"),
        ("replace", evidence("E-5", "C-9", 5, S.ACCEPTED, K.STATUS_QUERY_RESPONSE, "09:56", requested="09:56"), 18,
         S.REPLACE_REQUESTED, "REPLACE_PENDING"),
        ("replace", evidence("E-5", "C-9", 5, S.ACCEPTED, K.REQUEST_RESPONSE, "09:56"), 18, S.REPLACE_REQUESTED, "REPLACE_PENDING"),
        ("cancel", evidence("E-5", "C-1", 5, S.ACCEPTED, K.REQUEST_RESPONSE, "09:57"), 10, S.CANCEL_REQUESTED, "CANCEL_PENDING"),
    ],
)
def test_review3_m1_non_result_report_does_not_end_a_pending_request(base, report_item, target, status, block):
    """3차 검토 MEDIUM-1 (RP-3, R9-6, AT-0009-3, AT-0009-9 1행). 입력: (a)~(c) 기존 C-9 +5를 09:55에 +8(C-9R, 제출 대기)로 정정 요청 중인데
    09:56에 C-9의 (a) PARTIALLY_FILLED(2) 조회, (b) ACCEPTED 조회, (c) ACCEPTED 응답이 도착. (d) 09:56 취소 요청 중인 +5 주문에 09:57에 관측된
    ACCEPTED 응답. 판단 10:00, 목표 (a)~(c) C1 +18, (d) +10.
    출력: FILLS_ONLY(REPORT_DOES_NOT_CONFIRM_PENDING_REQUEST). 요청 결과(종료 상태)가 아닌 보고는 대기 상태를 끝내지 않고 체결만 반영한다. 주문은
    (a)~(c) REPLACE_REQUESTED, (d) CANCEL_REQUESTED이고 C1 BLOCKED(REPLACE_PENDING / CANCEL_PENDING). 2차 수정 뒤에는 대기 상태가 끝나 위험 증가
    후보가 NO_BLOCK_FOUND였다 (최악 경우 13은 유지)."""
    if base == "replace":
        items = [
            evidence("E-1", "C-9", 5, S.PENDING_SUBMIT, K.LOCAL_RECORD, "09:49"),
            evidence("E-2", "C-9", 5, S.ACCEPTED, K.REQUEST_RESPONSE, "09:50"),
            evidence("E-3", "C-9", 5, S.REPLACE_REQUESTED, K.LOCAL_RECORD, "09:55", replacement=8),
            evidence("E-4", "C-9R", 8, S.PENDING_SUBMIT, K.LOCAL_RECORD, "09:55"),
        ]
        fills = [make_fill("X-1", "C-9", 2, "09:56")] if report_item.event.record.filled_quantity else []
    else:
        items = accepted_c1() + [evidence("E-3", "C-1", 5, S.CANCEL_REQUESTED, K.LOCAL_RECORD, "09:56")]
        fills = []

    report = gate(items + [report_item], "10:00", targets={C1: target, C2: 0}, fills=fills)

    assessment = next(a for a in report.evidence.assessments if a.event_id == "E-5")
    assert (assessment.disposition, assessment.reasons) == (D.FILLS_ONLY, ("REPORT_DOES_NOT_CONFIRM_PENDING_REQUEST",))
    assert report.evidence.snapshot.records()[0].status is status
    assert report.view(C1).status is G.BLOCKED
    assert block in report.view(C1).blocking_reasons


def test_review3_m2_one_broker_order_id_for_two_unrelated_orders_is_an_integrity_error():
    """3차 검토 MEDIUM-2 (AT-0012-2). 입력: C-1 +5가 B-1로 접수됨. 제출 대기 중인 C-2 +5에 B-1을 적은 CANCELLED 응답. 대조군: 정정 관계인 C-9와
    C-9R이 같은 Broker Order ID를 보고 (제자리 정정).
    출력: OrderEventIntegrityError. 정정 관계가 아닌 두 주문에 같은 브로커 주문을 묶지 않는다. 2차 수정 뒤에는 C-2가 CANCELLED가 되어 C1 최악
    경우 롱이 10에서 5로 줄고 +10 후보가 NO_BLOCK_FOUND였다. 대조군은 오류가 아니다."""
    shared = [
        evidence("E-1", "C-1", 5, S.PENDING_SUBMIT, K.LOCAL_RECORD, "09:49"),
        evidence("E-2", "C-1", 5, S.ACCEPTED, K.REQUEST_RESPONSE, "09:50", broker_id="B-1"),
        evidence("E-3", "C-2", 5, S.PENDING_SUBMIT, K.LOCAL_RECORD, "09:51"),
        evidence("E-4", "C-2", 5, S.CANCELLED, K.REQUEST_RESPONSE, "09:52", cancelled=5, broker_id="B-1"),
    ]
    in_place_replace = [
        evidence("E-1", "C-9", 5, S.PENDING_SUBMIT, K.LOCAL_RECORD, "09:49"),
        evidence("E-2", "C-9", 5, S.ACCEPTED, K.REQUEST_RESPONSE, "09:50"),
        evidence("E-3", "C-9", 5, S.REPLACE_REQUESTED, K.LOCAL_RECORD, "09:55", replacement=8),
        evidence("E-4", "C-9R", 8, S.PENDING_SUBMIT, K.LOCAL_RECORD, "09:55"),
        evidence("E-5", "C-9R", 8, S.ACCEPTED, K.REQUEST_RESPONSE, "09:56", broker_id="B-C-9"),
    ]

    with pytest.raises(OrderEventIntegrityError, match="unrelated orders"):
        orders_from_evidence_as_of(shared, at("10:00"), account_id="A1", confirming_source=SRC.BROKER, completeness=COMPLETE,
                                   completeness_ref="x")
    checked = orders_from_evidence_as_of(in_place_replace, at("10:00"), account_id="A1", confirming_source=SRC.BROKER,
                                         completeness=COMPLETE, completeness_ref="x")
    assert [record.broker_order_id for record in checked.snapshot.records()] == [None, "B-C-9"]


@pytest.mark.parametrize(
    "items",
    [
        # (a) 시스템 UNKNOWN 분류(09:55)와 같은 시각에 요청한 조회
        unknown_c5() + [evidence("E-3", "C-5", 5, S.ACCEPTED, K.STATUS_QUERY_RESPONSE, "09:56", requested="09:55")],
        # (b) UNKNOWN을 알린 조회(09:57 이용 가능)로 UNKNOWN이 된 주문에 같은 09:57에 요청한 조회
        [evidence("E-1", "C-5", 5, S.PENDING_SUBMIT, K.LOCAL_RECORD, "09:49"),
         evidence("E-2", "C-5", 5, S.ACCEPTED, K.REQUEST_RESPONSE, "09:50"),
         evidence("E-3", "C-5", 5, S.UNKNOWN, K.STATUS_QUERY_RESPONSE, "09:57", requested="09:56"),
         evidence("E-4", "C-5", 5, S.ACCEPTED, K.STATUS_QUERY_RESPONSE, "09:58", requested="09:57")],
        # (c) UNKNOWN 주문에 09:57에 이용 가능한 UNKNOWN 조회 결과가 다시 온 뒤 같은 09:57에 요청한 조회
        unknown_c5() + [evidence("E-3", "C-5", 5, S.UNKNOWN, K.STATUS_QUERY_RESPONSE, "09:57", requested="09:56"),
                        evidence("E-4", "C-5", 5, S.ACCEPTED, K.STATUS_QUERY_RESPONSE, "09:58", requested="09:57")],
    ],
)
def test_query_requested_at_the_unknown_instant_does_not_resolve_it(items):
    """최종 검사 A. 입력: UNKNOWN 기준 시각과 같은 시각에 요청한 ACCEPTED 상태 조회. (a) 시스템 UNKNOWN 분류 09:55, (b) 보고로 UNKNOWN이 된
    09:57, (c) 다시 온 UNKNOWN 조회 결과로 늦춰진 09:57. 10:30 승인 NORMAL 기록, 판단 10:31, 목표 C1 +10.
    출력: 조회는 DEFERRED(STATUS_QUERY_SAME_INSTANT_AS_UNKNOWN). 같은 시각이면 조회가 UNKNOWN 뒤의 상태를 본 것인지 확정할 수 없다 (브로커
    시각의 의미는 검증되지 않음, BR-7). 주문은 UNKNOWN, 최악 경우 롱 5 그대로, 모든 월물 BLOCKED(UNKNOWN_ORDER_PRESENT). 수정 전에는 해소되어
    승인 기록 뒤 NO_BLOCK_FOUND였다. ADR-0001 B-1(이용 가능 시각 = 판단 시각이면 쓴다)은 그대로다."""
    release = state_record("TS-3", TradingState.NORMAL, "10:30", cause="DAILY_OPEN", approver="user:release-1")

    report = gate(items, "10:31", targets={C1: 10, C2: 0}, records=(NORMAL_AT_0900, release))

    query = report.evidence.assessments[-1]
    assert (query.disposition, query.reasons) == (D.DEFERRED, ("STATUS_QUERY_SAME_INSTANT_AS_UNKNOWN",))
    assert report.evidence.snapshot.records()[0].status is S.UNKNOWN
    assert report.risk.risk.view(C1).worst_case.worst_long_before == 5
    assert_all_blocked(report, "UNKNOWN_ORDER_PRESENT")


def test_rejected_report_does_not_define_the_broker_order_id():
    """입력: 브로커 계좌의 C-1 +5에 시뮬레이터 접수 보고(B-SIM, REJECTED)가 09:50에 먼저 오고 09:51에 브로커 접수 응답(B-C-1). 판단 10:00.
    출력: 브로커 응답은 USED, 주문은 ACCEPTED(B-C-1). 쓰지 않은 다른 출처 보고의 식별자로 주문을 정하지 않는다. 차단은
    ORDER_EVIDENCE_CONFLICT로 남는다."""
    items = [
        evidence("E-1", "C-1", 5, S.PENDING_SUBMIT, K.LOCAL_RECORD, "09:49"),
        evidence("E-2", "C-1", 5, S.ACCEPTED, K.REQUEST_RESPONSE, "09:50", source=SRC.SIMULATOR, broker_id="B-SIM"),
        evidence("E-3", "C-1", 5, S.ACCEPTED, K.REQUEST_RESPONSE, "09:51"),
    ]

    report = gate(items, "10:00")

    assert [a.disposition for a in report.evidence.assessments] == [D.USED, D.REJECTED, D.USED]
    assert (report.evidence.snapshot.records()[0].status, report.evidence.snapshot.records()[0].broker_order_id) == (S.ACCEPTED, "B-C-1")
    assert_all_blocked(report, "ORDER_EVIDENCE_CONFLICT")


def test_gate_rejects_a_risk_report_built_from_other_orders():
    """입력: CASE 1의 증거 Snapshot(UNKNOWN)과, 같은 사건을 증거 검사 없이 Slice 2에 넣어 만든 위험 결과(PARTIALLY_FILLED).
    출력: ValueError. 게이트는 증거 검사를 거친 Snapshot으로 계산한 위험 결과만 받는다."""
    items = unknown_c5() + [evidence("E-3", "C-5", 5, S.PARTIALLY_FILLED, K.FILL_NOTIFICATION, "09:57", "09:58", filled=3)]
    checked = orders_from_evidence_as_of(items, at("10:00"), account_id="A1", confirming_source=SRC.BROKER, completeness=COMPLETE,
                                         completeness_ref="x")
    unchecked = assess_pretrade_risk_as_of(
        baseline=baseline(), ledger=ledger_with(make_fill("X-1", "C-5", 3, "09:57")), events=[item.event for item in items],
        completeness=COMPLETE, completeness_ref="x", targets={C1: 10, C2: 0}, decision_at=at("10:00"), trading_state=TradingState.NORMAL,
        **risk_inputs(at("10:00")),
    )

    assert unchecked.snapshot.records()[0].status is S.PARTIALLY_FILLED
    with pytest.raises(ValueError):
        assess_l3_gate(evidence=checked, risk=unchecked, trading_state_records=(NORMAL_AT_0900,))


@pytest.mark.parametrize(("c1_price", "exposure"), [("100", "15000"), ("-37.63", "5644.50")])
def test_regression_slice_1_exposure_through_the_gate(c1_price, exposure):
    """회귀 (Slice 1 CASE 1). 입력: C-1 +10 제출 기록, 접수 응답, 08:59 체결 +3 통보 (PARTIALLY_FILLED), 목표 +15. 참조 가격 100 또는
    −37.63 (선물 음수 가격 허용).
    출력: 위험 결과가 assess_pretrade_risk와 같다: 최악 경우 15·3, 노출 15,000 / 5,644.50 USD (= 15 × |P| × 10). 위험 증가 후보이고
    한도 안이므로 C1 NO_BLOCK_FOUND."""
    items = [
        evidence("E-1", "C-1", 10, S.PENDING_SUBMIT, K.LOCAL_RECORD, "08:00"),
        evidence("E-2", "C-1", 10, S.ACCEPTED, K.REQUEST_RESPONSE, "08:01"),
        evidence("E-3", "C-1", 10, S.PARTIALLY_FILLED, K.FILL_NOTIFICATION, "08:59", filled=3),
    ]
    fill = make_fill("X-1", "C-1", 3, "08:59")

    report = gate(items, "10:00", targets={C1: 15, C2: 0}, fills=[fill], c1_price=c1_price)
    direct = assess_pretrade_risk(
        baseline=baseline(), ledger=ledger_with(fill), orders=[items[-1].event.record], targets={C1: 15, C2: 0},
        decision_at=at("10:00"), trading_state=TradingState.NORMAL, **risk_inputs(at("10:00"), c1_price),
    )

    assert report.risk.risk.views == direct.views
    view = report.risk.risk.view(C1)
    assert (view.worst_case.worst_long_after, view.worst_case.worst_short_after, view.exposure_after) == (15, 3, Decimal(exposure))
    assert report.view(C1).status is G.NO_BLOCK_FOUND


def test_regression_slice_2_late_cancel_confirmation_through_evidence():
    """회귀 (Slice 2 CASE 1). 입력: 09:50 +10 접수 응답, 09:58 취소 요청, 취소 확정 응답(10:00 발생)이 10:05에 이용 가능.
    출력: 10:00 CANCEL_REQUESTED, 노출 10,000 USD, C1 BLOCKED(CANCEL_PENDING). 10:05 CANCELLED, 노출 0."""
    items = [
        evidence("E-1", "C-1", 10, S.ACCEPTED, K.REQUEST_RESPONSE, "09:50"),
        evidence("E-2", "C-1", 10, S.CANCEL_REQUESTED, K.LOCAL_RECORD, "09:58"),
        evidence("E-3", "C-1", 10, S.CANCELLED, K.REQUEST_RESPONSE, "10:00", "10:05", cancelled=10),
    ]

    before = gate(items, "10:00", targets={C1: 5, C2: 0})
    after = gate(items, "10:05", targets={C1: 0, C2: 0})

    assert before.risk.risk.view(C1).exposure_before == Decimal("10000")
    assert "CANCEL_PENDING" in before.view(C1).blocking_reasons
    assert after.evidence.snapshot.records()[0].status is S.CANCELLED
    assert after.risk.risk.view(C1).exposure_before == Decimal("0")


@pytest.mark.parametrize(
    ("rows", "exposure"),
    [
        ([], "13000"),
        ([evidence("E-4", "C-9", 5, S.UNKNOWN, K.LOCAL_RECORD, "09:59", replacement=8),
          evidence("E-5", "C-9R", 8, S.UNKNOWN, K.LOCAL_RECORD, "09:59")], "13000"),
        ([evidence("E-4", "C-9", 5, S.CANCELLED, K.REQUEST_RESPONSE, "09:59", cancelled=5),
          evidence("E-5", "C-9R", 8, S.ACCEPTED, K.REQUEST_RESPONSE, "09:59")], "8000"),
    ],
)
def test_regression_replace_rows_through_evidence(rows, exposure):
    """회귀 (ADR-0009 AT-0009-9 1~3행). 입력: 기존 +5 접수 뒤 +8로 정정 요청 (기존 C-9와 새 C-9R 기록). 1행 정정 요청 중, 2행 timeout으로
    둘 다 UNKNOWN, 3행 기존 취소 확정과 새 주문 접수. 판단 10:00.
    출력: 최악 경우 노출 13,000 / 13,000 / 8,000 USD (Slice 2와 같음)."""
    items = [
        evidence("E-1", "C-9", 5, S.ACCEPTED, K.REQUEST_RESPONSE, "09:50"),
        evidence("E-2", "C-9", 5, S.REPLACE_REQUESTED, K.LOCAL_RECORD, "09:58", replacement=8),
        evidence("E-3", "C-9R", 8, S.PENDING_SUBMIT, K.LOCAL_RECORD, "09:58"),
    ] + rows

    report = gate(items, "10:00")

    assert report.risk.risk.view(C1).exposure_before == Decimal(exposure)
    assert report.view(C1).status is G.BLOCKED
