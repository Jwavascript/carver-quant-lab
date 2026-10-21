"""P0-03C Slice 2: 결정 시점의 주문 Snapshot (ADR-0001 I-1·B-1, ADR-0004 승인 원칙 5, ADR-0009 §6.1·§6.2·R9-4·RP-1,
ADR-0012 BR-7·BR-12, ADR-0003 §6.3).

주문 사건은 시스템이 기록한 주문 상태의 한 버전과 그 발생 시각·이용 가능 시각이다. Snapshot은 주문마다 decision_at까지
이용 가능했던 마지막 버전이며 상태 전이를 다시 계산하지 않는다. 기대값(10,000 / 5,000 / 13,000 USD 등)은 저장소 밖 독립
산술(Fraction)로 먼저 확인했다. 가상 선물이며 한도·가격·승수는 테스트 입력이다.
"""

import dataclasses
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from carver_quant.lab.accounting.fill_ledger import FillLedger, apply_fill
from carver_quant.lab.accounting.order_projection import CandidateStatus, OrderIntegrityError
from carver_quant.lab.accounting.order_snapshot import (
    PIT_UNVERIFIED_INPUTS,
    OrderEventIntegrityError,
    OrderLogCompleteness,
    assess_pretrade_risk_as_of,
    orders_as_of,
)
from carver_quant.lab.accounting.pretrade_risk import RiskCheckStatus, assess_pretrade_risk
from carver_quant.lab.domain.order_events import OrderEvent, OrderEventKind
from carver_quant.lab.domain.orders import OrderRecord, OrderStatus, OrderStatusSource
from carver_quant.lab.domain.records import FillKey, FillOrigin, FillRecord, FuturesContractSpec, PositionBaseline, ValuationPrice
from carver_quant.lab.domain.risk import ContractMultiplier, ExposureLimit, TradingState

UTC = timezone.utc
S = OrderStatus
C1 = "FUT.ALPHA.C1"
C2 = "FUT.ALPHA.C2"
T0 = datetime(2026, 10, 21, 0, 0, tzinfo=UTC)
SYSTEM_STATES = {S.INTENT, S.PENDING_SUBMIT, S.CANCEL_REQUESTED, S.REPLACE_REQUESTED, S.UNKNOWN}
COMPLETE = OrderLogCompleteness.VERIFIED_COMPLETE


def at(hhmm):
    hour, minute = hhmm.split(":")
    return datetime(2026, 10, 21, int(hour), int(minute), tzinfo=UTC)


def make_event(event_id, client_order_id, quantity, status, occurred, available=None, filled=0, cancelled=0,
               replacement=None, replacement_id=None, contract_id=C1, kind=None, account_id="A1", source=None):
    if replacement is not None and replacement_id is None:
        replacement_id = client_order_id + "R"
    source = source or (OrderStatusSource.SYSTEM if status in SYSTEM_STATES else OrderStatusSource.BROKER)
    record = OrderRecord(
        account_id=account_id,
        client_order_id=client_order_id,
        broker_order_id=None if status in (S.INTENT, S.PENDING_SUBMIT) else "B-" + client_order_id,
        contract_id=contract_id,
        quantity=quantity,
        status=status,
        filled_quantity=filled,
        cancelled_quantity=cancelled,
        replacement_quantity=replacement,
        replacement_client_order_id=replacement_id,
        status_source=source,
        status_event_ref=event_id,
    )
    default_kind = OrderEventKind.SYSTEM_RECORD if source is OrderStatusSource.SYSTEM else OrderEventKind.BROKER_REPORT
    return OrderEvent(
        event_id=event_id,
        kind=kind or default_kind,
        record=record,
        occurred_at=at(occurred),
        available_at=at(available or occurred),
    )


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


def assess_at(events, decision, targets=None, ledger=None, completeness=COMPLETE, state=TradingState.NORMAL, base=None):
    return assess_pretrade_risk_as_of(
        baseline=base or PositionBaseline(account_id="A1", as_of=T0, quantities={C1: 0, C2: 0}, verification_ref="fixture:verified"),
        ledger=ledger or ledger_with(),
        events=events,
        completeness=completeness,
        completeness_ref="fixture:complete-log" if completeness is COMPLETE else None,
        targets=targets or {C1: 0, C2: 0},
        decision_at=at(decision),
        trading_state=state,
        **risk_inputs(at(decision)),
    )


def case_1_events():
    """09:50 매수 +10 확인, 09:58 취소 요청, 10:05 취소 완료 통보 이용 가능 (발생 10:00)."""
    return [
        make_event("E-1", "C-1", 10, S.ACCEPTED, "09:50"),
        make_event("E-2", "C-1", 10, S.CANCEL_REQUESTED, "09:58"),
        make_event("E-3", "C-1", 10, S.CANCELLED, "10:00", available="10:05", cancelled=10),
    ]


def test_order_event_carries_times_source_and_identity():
    """입력: 정상 사건, 그리고 (a) 종류와 상태 출처 불일치, (b) 발생 시각 > 이용 가능 시각, (c) 이용 가능 시각 누락,
    (d) 시간대 없는 시각, (e) 기록의 사건 참조가 사건 ID와 다름, (f) 주문 기록이 아닌 값.
    출력: 정상 사건은 계좌·주문·월물·상태·확인 수량·두 시각을 가진다. (a)~(f)는 ValueError (ADR-0001 I-1: 발생 ≤ 이용 가능)."""
    event = make_event("E-1", "C-1", 10, S.ACCEPTED, "09:50", available="09:51")
    assert (event.record.account_id, event.record.client_order_id, event.record.contract_id) == ("A1", "C-1", C1)
    assert (event.occurred_at, event.available_at) == (at("09:50"), at("09:51"))

    record = event.record
    bad = [
        dict(kind=OrderEventKind.SYSTEM_RECORD),
        dict(occurred_at=at("09:52")),
        dict(available_at=None),
        dict(available_at=datetime(2026, 10, 21, 9, 51)),
        dict(record=dataclasses.replace(record, status_event_ref="E-9")),
        dict(record="ACCEPTED"),
    ]
    for changes in bad:
        with pytest.raises(ValueError):
            dataclasses.replace(event, **changes)


def test_case_1_late_cancel_confirmation_is_not_used_before_it_arrives():
    """CASE 1. 입력: 09:50 +10 확인, 09:58 취소 요청, 취소 완료는 10:00에 발생했지만 10:05에 이용 가능. 판단 10:00·10:04·10:05.
    출력: 10:00과 10:04 Snapshot은 CANCEL_REQUESTED (취소 미완료), 10:05부터 CANCELLED. 10:00 위험 계산에는 +10이 남아
    최악 경우 롱 10, 노출 10,000 USD이며 0이 아닌 후보는 BLOCKED(CANCEL_PENDING). 10:05에는 최악 경우 0."""
    events = case_1_events()

    assert orders_as_of(events, at("10:00"), completeness=COMPLETE, completeness_ref="x").records()[0].status is S.CANCEL_REQUESTED
    assert orders_as_of(events, at("10:04"), completeness=COMPLETE, completeness_ref="x").records()[0].status is S.CANCEL_REQUESTED
    assert orders_as_of(events, at("10:05"), completeness=COMPLETE, completeness_ref="x").records()[0].status is S.CANCELLED
    assert orders_as_of(events, at("10:00"), completeness=COMPLETE, completeness_ref="x").late_event_ids == ("E-3",)

    before = assess_at(events, "10:00", targets={C1: 5, C2: 0}).risk.view(C1)
    assert (before.worst_case.worst_long_before, before.exposure_before) == (10, Decimal("10000"))
    assert (before.local_status, before.local_reasons) == (CandidateStatus.BLOCKED, ("CANCEL_PENDING",))
    after = assess_at(events, "10:05", targets={C1: 0, C2: 0}).risk.view(C1)
    assert (after.worst_case.worst_long_before, after.exposure_before) == (0, Decimal("0"))


def test_case_2_late_fill_notice_is_not_an_actual_position_yet():
    """CASE 2. 입력: 09:50 +10 확인. 09:59 실제 부분 체결 +3, 그 통보는 10:03에 이용 가능. 판단 10:00·10:03.
    출력: (a) 10:00에 그때 알던 체결 장부(체결 없음)로 계산하면 실제 0, 진행 중 잔량 +10, 최악 경우 롱 10 (미확인 체결 가능성을
    잔량으로 포함해 과소평가하지 않음). (b) 10:00인데 뒤에 알게 된 체결 +3이 든 장부를 주면 Snapshot(확인 체결 0)과 맞지 않아
    OrderIntegrityError: 그 +3을 10:00의 확인된 실제 포지션으로 만들지 않는다. (c) 10:03에는 실제 3, 잔량 7, 최악 경우 10 (이중 반영 없음)."""
    events = [
        make_event("E-1", "C-1", 10, S.ACCEPTED, "09:50"),
        make_event("E-2", "C-1", 10, S.PARTIALLY_FILLED, "09:59", available="10:03", filled=3),
    ]
    later_ledger = ledger_with(make_fill("X-1", "C-1", 3, "09:59"))

    known_then = assess_at(events, "10:00", targets={C1: 10, C2: 0}).risk.view(C1).worst_case
    assert (known_then.actual_quantity, known_then.open_buy_quantity, known_then.worst_long_before) == (0, 10, 10)
    with pytest.raises(OrderIntegrityError):
        assess_at(events, "10:00", targets={C1: 10, C2: 0}, ledger=later_ledger)
    confirmed = assess_at(events, "10:03", targets={C1: 10, C2: 0}, ledger=later_ledger).risk.view(C1).worst_case
    assert (confirmed.actual_quantity, confirmed.open_buy_quantity, confirmed.worst_long_before) == (3, 7, 10)


def test_case_3_unknown_order_stays_unknown_until_confirmed():
    """CASE 3. 입력: 09:50 +5 제출, 09:55 결과 UNKNOWN, 상태 조회 결과(취소 확인)는 10:05에 이용 가능. 판단 10:00·10:05.
    출력: 10:00에는 UNKNOWN 그대로, 최악 경우 롱 5, 노출 5,000 USD. 모든 월물의 새 후보 BLOCKED, 상태 차단 UNKNOWN_ORDER_PRESENT
    (자동 재제출 없음). 10:05에는 브로커 확인으로 CANCELLED (BR-12, R9-4)."""
    events = [
        make_event("E-1", "C-5", 5, S.PENDING_SUBMIT, "09:50"),
        make_event("E-2", "C-5", 5, S.UNKNOWN, "09:55"),
        make_event("E-3", "C-5", 5, S.CANCELLED, "10:01", available="10:05", cancelled=5),
    ]

    report = assess_at(events, "10:00", targets={C1: 5, C2: 2}).risk
    view = report.view(C1)
    assert (view.worst_case.worst_long_before, view.exposure_before) == (5, Decimal("5000"))
    for contract_view in report.views:
        assert contract_view.local_status is CandidateStatus.BLOCKED
        assert "UNKNOWN_ORDER_PRESENT" in contract_view.state_blocks
    assert orders_as_of(events, at("10:05"), completeness=COMPLETE, completeness_ref="x").records()[0].status is S.CANCELLED


@pytest.mark.parametrize(
    ("events", "exposure"),
    [
        (
            [make_event("E-1", "C-9", 5, S.ACCEPTED, "09:50"),
             make_event("E-2", "C-9", 5, S.REPLACE_REQUESTED, "09:58", replacement=8),
             make_event("E-3", "C-9R", 8, S.PENDING_SUBMIT, "09:58")],
            "13000",
        ),
        (
            [make_event("E-1", "C-9", 5, S.ACCEPTED, "09:50"),
             make_event("E-2", "C-9", 5, S.REPLACE_REQUESTED, "09:58", replacement=8),
             make_event("E-3", "C-9R", 8, S.PENDING_SUBMIT, "09:58"),
             make_event("E-4", "C-9", 5, S.UNKNOWN, "09:59", replacement=8),
             make_event("E-5", "C-9R", 8, S.UNKNOWN, "09:59")],
            "13000",
        ),
        (
            [make_event("E-1", "C-9", 5, S.ACCEPTED, "09:50"),
             make_event("E-2", "C-9", 5, S.REPLACE_REQUESTED, "09:58", replacement=8),
             make_event("E-3", "C-9R", 8, S.PENDING_SUBMIT, "09:58"),
             make_event("E-4", "C-9", 5, S.CANCELLED, "09:59", cancelled=5),
             make_event("E-5", "C-9R", 8, S.ACCEPTED, "09:59")],
            "8000",
        ),
    ],
)
def test_case_4_replace_rows_keep_the_at_0009_9_worst_case(events, exposure):
    """CASE 4 (ADR-0009 AT-0009-9 1~3행). 입력: 기존 +5를 +8로 정정. 1행 정정 요청 중, 2행 timeout으로 둘 다 UNKNOWN,
    3행 정정 확정 (기존 취소 확정, 새 주문 접수). 판단 10:00.
    출력: 최악 경우 노출 13,000 / 13,000 / 8,000 USD (기존 잔량과 새 정정 수량을 빠뜨리거나 두 번 세지 않음)."""
    assert assess_at(events, "10:00").risk.view(C1).exposure_before == Decimal(exposure)


def test_case_4_staggered_confirmations_do_not_lower_the_worst_case_unduly():
    """CASE 4. 입력: 정정 요청(09:58, 기존 C-9 + 새 C-9R 기록) 뒤 확정 통보가 따로 도착. (a) 기존 취소 확정이 10:03, 새 주문 접수가
    10:05에 이용 가능. (b) 새 주문 접수가 10:03, 기존 취소 확정이 10:05에 이용 가능. 판단 10:04.
    출력: (a) 기존 0 + 새 주문 대기 8 = 최악 경우 8 (확인된 취소만 반영). (b) 기존 정정 요청 중 5 + 새 주문 8 = 13 (줄지 않음)."""
    base = [
        make_event("E-1", "C-9", 5, S.ACCEPTED, "09:50"),
        make_event("E-2", "C-9", 5, S.REPLACE_REQUESTED, "09:58", replacement=8),
        make_event("E-3", "C-9R", 8, S.PENDING_SUBMIT, "09:58"),
    ]
    old_first = base + [
        make_event("E-4", "C-9", 5, S.CANCELLED, "10:01", available="10:03", cancelled=5),
        make_event("E-5", "C-9R", 8, S.ACCEPTED, "10:01", available="10:05"),
    ]
    new_first = base + [
        make_event("E-4", "C-9", 5, S.CANCELLED, "10:01", available="10:05", cancelled=5),
        make_event("E-5", "C-9R", 8, S.ACCEPTED, "10:01", available="10:03"),
    ]

    assert assess_at(old_first, "10:04").risk.view(C1).worst_case.worst_long_before == 8
    assert assess_at(new_first, "10:04").risk.view(C1).worst_case.worst_long_before == 13


def test_replacement_known_only_inside_the_old_order_cannot_vanish():
    """입력: 정정 요청(09:58)이 기존 주문 안에만 정정 수량 +8을 기록했고 새 주문 C-9R의 기록이 없는데, 기존 주문의 취소 확정이
    10:03에 먼저 이용 가능. 판단 10:04.
    출력: OrderEventIntegrityError. 새 주문 기록 없이 정정 수량 +8이 Snapshot에서 사라지면 최악 경우가 부당하게 줄어든다."""
    events = [
        make_event("E-1", "C-9", 5, S.ACCEPTED, "09:50"),
        make_event("E-2", "C-9", 5, S.REPLACE_REQUESTED, "09:58", replacement=8),
        make_event("E-4", "C-9", 5, S.CANCELLED, "10:01", available="10:03", cancelled=5),
    ]

    with pytest.raises(OrderEventIntegrityError, match="replacement"):
        orders_as_of(events, at("10:04"), completeness=COMPLETE, completeness_ref="x")
    assert orders_as_of(events, at("10:00"), completeness=COMPLETE, completeness_ref="x").records()[0].replacement_quantity == 8


@pytest.mark.parametrize(
    ("available", "decision", "status"),
    [("10:00", "10:00", S.CANCELLED), ("10:01", "10:00", S.CANCEL_REQUESTED), ("10:05", "10:00", S.CANCEL_REQUESTED)],
)
def test_case_5_availability_boundaries(available, decision, status):
    """CASE 5. 입력: 취소 확정이 09:59에 발생하고 (a) 10:00, (b) 10:01, (c) 10:05에 이용 가능. 판단 10:00.
    출력: (a) 이용 가능 시각 = 판단 시각이면 쓴다 (ADR-0001 B-1). (b) 판단 뒤면 쓰지 않는다. (c) 발생은 판단 전이지만 이용 가능
    시각이 판단 뒤면 쓰지 않는다."""
    events = [
        make_event("E-1", "C-1", 10, S.ACCEPTED, "09:50"),
        make_event("E-2", "C-1", 10, S.CANCEL_REQUESTED, "09:58"),
        make_event("E-3", "C-1", 10, S.CANCELLED, "09:59", available=available, cancelled=10),
    ]

    assert orders_as_of(events, at(decision), completeness=COMPLETE, completeness_ref="x").records()[0].status is status


def test_case_6_duplicates_are_counted_once():
    """CASE 6. 입력: 같은 사건 E-2와 늦게 도착한 E-3을 각각 두 번 받음.
    출력: 주문은 Snapshot에 한 번만 있고 상태는 CANCEL_REQUESTED, 늦은 사건 목록에도 E-3이 한 번만 있다 (두 번 집계하지 않음)."""
    events = case_1_events() + [case_1_events()[1], case_1_events()[2]]

    snapshot = orders_as_of(events, at("10:00"), completeness=COMPLETE, completeness_ref="x")

    assert [(record.client_order_id, record.status) for record in snapshot.records()] == [("C-1", S.CANCEL_REQUESTED)]
    assert snapshot.late_event_ids == ("E-3",)


@pytest.mark.parametrize(
    "events",
    [
        # 같은 사건 ID, 다른 내용
        [make_event("E-1", "C-1", 10, S.ACCEPTED, "09:50"), make_event("E-1", "C-1", 10, S.ACCEPTED, "09:50", available="09:51")],
        # 확인된 누적 체결 감소
        [make_event("E-1", "C-1", 10, S.PARTIALLY_FILLED, "09:50", filled=3), make_event("E-2", "C-1", 10, S.ACCEPTED, "09:52")],
        # 확인된 누적 취소 감소
        [make_event("E-1", "C-1", 10, S.CANCELLED, "09:50", cancelled=10), make_event("E-2", "C-1", 10, S.CANCELLED, "09:52", cancelled=4, filled=6)],
        # 종료 상태 뒤의 다른 상태 (수량 감소 없이)
        [make_event("E-1", "C-1", 10, S.REJECTED, "09:50"), make_event("E-2", "C-1", 10, S.ACCEPTED, "09:52")],
        # 시스템이 UNKNOWN을 스스로 해소
        [make_event("E-1", "C-1", 10, S.UNKNOWN, "09:50"), make_event("E-2", "C-1", 10, S.PENDING_SUBMIT, "09:52")],
        # 같은 이용 가능 시각의 서로 다른 상태 (순서 불명확)
        [make_event("E-1", "C-1", 10, S.ACCEPTED, "09:50"), make_event("E-2", "C-1", 10, S.CANCEL_REQUESTED, "09:50")],
        # 같은 주문의 수량·월물 변경
        [make_event("E-1", "C-1", 10, S.ACCEPTED, "09:50"), make_event("E-2", "C-1", 12, S.ACCEPTED, "09:52")],
        [make_event("E-1", "C-1", 10, S.ACCEPTED, "09:50"), make_event("E-2", "C-1", 10, S.ACCEPTED, "09:52", contract_id=C2)],
    ],
)
def test_case_6_contradictory_events_are_rejected_not_normalized(events):
    """CASE 6. 입력: 같은 ID의 다른 내용, 확인된 누적 체결·취소 감소, 종료 상태 뒤 변경, 시스템의 UNKNOWN 해소(R9-4),
    같은 이용 가능 시각의 다른 상태, 같은 주문의 수량·월물 변경.
    출력: OrderEventIntegrityError. 어느 쪽이 맞는지 고르거나 정상 상태로 바꾸지 않는다. 주문 상태 기계를 새로 만들지 않고
    승인된 규칙(확인 수량은 누적, 종료 상태, UNKNOWN 유지)에 어긋나는 기록만 거부한다."""
    with pytest.raises(OrderEventIntegrityError):
        orders_as_of(events, at("10:00"), completeness=COMPLETE, completeness_ref="x")


def test_case_6_events_of_another_account_are_rejected():
    """입력: 계좌 A1과 A2의 주문 사건이 섞인 기록.
    출력: ValueError (단일 계좌 Snapshot)."""
    events = [make_event("E-1", "C-1", 10, S.ACCEPTED, "09:50"), make_event("E-2", "C-2", 10, S.ACCEPTED, "09:50", account_id="A2")]

    with pytest.raises(ValueError):
        orders_as_of(events, at("10:00"), completeness=COMPLETE, completeness_ref="x")


def test_unverified_event_log_is_not_assessable():
    """입력: Slice 1 CASE 2와 같은 위험 입력 (노출 15,000 < 한도 20,000)인데 주문 사건 기록의 완전성을 확인하지 못함 (UNVERIFIED).
    출력: 모든 월물이 NOT_ASSESSABLE(ORDER_LOG_NOT_VERIFIED_COMPLETE). 빠진 주문이 있을 수 있으므로 위험 증가 판단에 쓰지 않는다.
    VERIFIED_COMPLETE에는 확인 근거 참조가 필요하다."""
    events = [make_event("E-1", "C-1", 10, S.PARTIALLY_FILLED, "09:00", filled=3)]
    ledger = ledger_with(make_fill("X-1", "C-1", 3, "08:59"))

    verified = assess_at(events, "10:00", targets={C1: 15, C2: 0}, ledger=ledger)
    unverified = assess_at(events, "10:00", targets={C1: 15, C2: 0}, ledger=ledger, completeness=OrderLogCompleteness.UNVERIFIED)

    assert verified.risk.view(C1).risk_status is RiskCheckStatus.WITHIN_LIMIT
    for view in unverified.risk.views:
        assert view.risk_status is RiskCheckStatus.NOT_ASSESSABLE
        assert "ORDER_LOG_NOT_VERIFIED_COMPLETE" in view.risk_reasons
    assert "ORDER_LOG_COMPLETENESS" in unverified.pit_unverified
    with pytest.raises(ValueError):
        orders_as_of(events, at("10:00"), completeness=COMPLETE, completeness_ref=None)


def test_snapshot_reproduces_slice_1_when_each_order_has_one_known_version():
    """입력: Slice 1 CASE 1 (실제 +3, C-1 +10 PARTIALLY_FILLED 체결 3, 목표 +15)을 사건 하나(09:00 이용 가능)로 표현.
    출력: Snapshot 기록이 그 주문 기록과 같고, 위험 결과가 assess_pretrade_risk와 같다: 최악 경우 15·3, 노출 15,000."""
    events = [make_event("E-1", "C-1", 10, S.PARTIALLY_FILLED, "09:00", filled=3)]
    ledger = ledger_with(make_fill("X-1", "C-1", 3, "08:59"))
    base = PositionBaseline(account_id="A1", as_of=T0, quantities={C1: 0, C2: 0}, verification_ref="fixture:verified")

    pit = assess_at(events, "10:00", targets={C1: 15, C2: 0}, ledger=ledger).risk
    direct = assess_pretrade_risk(
        baseline=base, ledger=ledger, orders=[events[0].record], targets={C1: 15, C2: 0}, decision_at=at("10:00"),
        trading_state=TradingState.NORMAL, **risk_inputs(at("10:00")),
    )

    assert pit.views == direct.views
    assert (pit.view(C1).worst_case.worst_long_after, pit.view(C1).exposure_after) == (15, Decimal("15000"))


def test_final_order_records_do_not_reproduce_a_past_decision():
    """입력: CASE 1의 최종 기록(CANCELLED, 10:05에 이용 가능)을 10:00 판단에 그대로 넣은 경우와 10:00 Snapshot.
    출력: 최종 기록으로는 노출 0, Snapshot으로는 10,000. 최신 주문 기록을 과거 판단에 쓰면 위험을 과소평가하므로 이 경로는
    사건과 이용 가능 시각을 거쳐야 한다."""
    events = case_1_events()
    base = PositionBaseline(account_id="A1", as_of=T0, quantities={C1: 0, C2: 0}, verification_ref="fixture:verified")

    snapshot_view = assess_at(events, "10:00").risk.view(C1)
    final_view = assess_pretrade_risk(
        baseline=base, ledger=ledger_with(), orders=[events[-1].record], targets={C1: 0, C2: 0}, decision_at=at("10:00"),
        trading_state=TradingState.NORMAL, **risk_inputs(at("10:00")),
    ).view(C1)

    assert (snapshot_view.exposure_before, final_view.exposure_before) == (Decimal("10000"), Decimal("0"))


def test_order_known_only_after_the_decision_is_listed_not_denied():
    """입력: 주문 C-7의 유일한 사건이 10:02에 이용 가능. 판단 10:00.
    출력: 10:00 Snapshot에는 C-7이 없지만 그 사건은 늦게 도착한 사건으로 남는다 (사건이 없었다고 주문이 없었다고 보지 않음).
    완전성 확인은 호출 경계의 입력이다."""
    events = [make_event("E-7", "C-7", 4, S.ACCEPTED, "10:01", available="10:02")]

    snapshot = orders_as_of(events, at("10:00"), completeness=OrderLogCompleteness.UNVERIFIED)

    assert snapshot.records() == ()
    assert snapshot.late_event_ids == ("E-7",)


def test_pit_report_never_claims_full_point_in_time():
    """입력: 완전성을 확인한 CASE 1 판단.
    출력: 검증하지 못한 입력(체결 기록의 이용 가능 시각, 기준 포지션 검증 시각, 한도 적용 시각, 장부 월물 사양 시각)을 늘 함께
    돌려준다. 주문 상태만 PIT로 맞추고 전체 PIT라고 주장하지 않는다."""
    report = assess_at(case_1_events(), "10:00")

    assert report.pit_unverified == PIT_UNVERIFIED_INPUTS
    assert "FILL_RECORD_AVAILABILITY" in report.pit_unverified
    assert "ORDER_EVENT_AVAILABILITY" in report.pit_verified


@pytest.mark.parametrize(
    "events",
    [
        # 시스템의 취소 요청 기록이 확인 취소 수량을 스스로 채움
        [make_event("E-1", "C-1", 10, S.ACCEPTED, "09:50"), make_event("E-2", "C-1", 10, S.CANCEL_REQUESTED, "09:58", cancelled=10)],
        # 첫 기록부터 시스템이 확인 취소 수량을 가짐
        [make_event("E-1", "C-1", 10, S.PENDING_SUBMIT, "09:50", cancelled=10)],
        # 접수된 주문을 시스템이 주문 의도·제출 대기로 되돌림
        [make_event("E-1", "C-1", 10, S.PENDING_SUBMIT, "09:50"), make_event("E-2", "C-1", 10, S.ACCEPTED, "09:51"),
         make_event("E-3", "C-1", 10, S.INTENT, "09:52")],
        [make_event("E-1", "C-1", 10, S.PENDING_SUBMIT, "09:50"), make_event("E-2", "C-1", 10, S.ACCEPTED, "09:51"),
         make_event("E-3", "C-1", 10, S.PENDING_SUBMIT, "09:52")],
    ],
)
def test_system_records_cannot_confirm_quantities_or_revert_an_order(events):
    """검토 HIGH-1. 입력: (a) 시스템의 취소 요청 기록이 취소 10을 확인된 것처럼 기록, (b) 첫 시스템 기록에 확인 취소 10,
    (c)·(d) 브로커가 접수한 주문을 시스템 기록이 INTENT·PENDING_SUBMIT으로 되돌림.
    출력: OrderEventIntegrityError. 확인 수량과 결과는 브로커·시뮬레이터 확인으로만 생기고 (ADR-0009 §6.2), 로컬 판단으로 상태를
    되돌리지 않는다 (ADR-0012 BR-3). 그대로 두면 10:00 최악 경우가 10에서 0으로 줄어든다."""
    with pytest.raises(OrderEventIntegrityError):
        orders_as_of(events, at("10:00"), completeness=COMPLETE, completeness_ref="x")


def test_system_request_keeps_quantities_confirmed_earlier():
    """입력: 브로커가 부분 체결 3을 확인한 뒤(09:55) 시스템이 취소를 요청(09:58)하며 체결 3을 그대로 기록.
    출력: 받아들인다. Snapshot은 CANCEL_REQUESTED·체결 3 (이전에 확인된 수량을 옮겨 적는 것은 허용)."""
    events = [
        make_event("E-1", "C-1", 10, S.ACCEPTED, "09:50"),
        make_event("E-2", "C-1", 10, S.PARTIALLY_FILLED, "09:55", filled=3),
        make_event("E-3", "C-1", 10, S.CANCEL_REQUESTED, "09:58", filled=3),
    ]

    record = orders_as_of(events, at("10:00"), completeness=COMPLETE, completeness_ref="x").records()[0]

    assert (record.status, record.filled_quantity) == (S.CANCEL_REQUESTED, 3)


@pytest.mark.parametrize(
    "events",
    [
        # 같은 정정 주문 ID의 정정 수량이 8에서 5로 바뀜 (CE-2 과소평가)
        [make_event("E-1", "C-9", 5, S.PARTIALLY_FILLED, "09:50", filled=3),
         make_event("E-2", "C-9", 5, S.REPLACE_REQUESTED, "09:58", filled=3, replacement=8),
         make_event("E-3", "C-9", 5, S.REPLACE_REQUESTED, "09:59", filled=3, replacement=5)],
        # timeout(RP-5) 뒤 같은 정정 주문 ID의 수량이 1로 바뀜
        [make_event("E-1", "C-9", 5, S.ACCEPTED, "09:50"),
         make_event("E-2", "C-9", 5, S.REPLACE_REQUESTED, "09:58", replacement=8),
         make_event("E-3", "C-9", 5, S.UNKNOWN, "09:59", replacement=1)],
    ],
)
def test_requested_replacement_quantity_cannot_shrink(events):
    """검토 MEDIUM-2. 입력: 같은 정정 주문(C-9R)의 정정 수량이 뒤 기록에서 줄어듦.
    출력: OrderEventIntegrityError. 정정 주문 하나는 수량 하나다. 그대로 두면 최악 경우가 13에서 10·6으로 준다 (RP-1, CE-2)."""
    with pytest.raises(OrderEventIntegrityError):
        orders_as_of(events, at("10:00"), completeness=COMPLETE, completeness_ref="x")


@pytest.mark.parametrize(
    "replacement_event",
    [
        make_event("E-5", "C-9R", 8, S.INTENT, "10:03"),
        make_event("E-5", "C-9R", 1, S.ACCEPTED, "10:01"),
    ],
)
def test_unlinked_replacement_must_be_a_submitted_order_with_the_requested_quantity(replacement_event):
    """검토 MEDIUM-2. 입력: 정정 요청(C-9 +5 → C-9R +8, 기존 주문 안에만 기록) 뒤 기존 주문의 취소 확정이 10:01·10:03에 이용
    가능하고, C-9R은 (a) 아직 제출 전(INTENT)으로, (b) 수량 1의 접수로 기록됨. 판단 10:04.
    출력: OrderEventIntegrityError. 요청한 정정 주문은 제출된 주문이고 수량·월물이 요청과 같아야 한다. 그대로 두면 정정 수량 +8이
    사라져 최악 경우가 0 또는 1로 준다 (RP-1, CASE 4)."""
    events = [
        make_event("E-1", "C-9", 5, S.ACCEPTED, "09:50"),
        make_event("E-2", "C-9", 5, S.REPLACE_REQUESTED, "09:58", replacement=8),
        make_event("E-4", "C-9", 5, S.CANCELLED, "10:01", cancelled=5),
        replacement_event,
    ]

    with pytest.raises(OrderEventIntegrityError, match="replacement"):
        orders_as_of(events, at("10:04"), completeness=COMPLETE, completeness_ref="x")


@pytest.mark.parametrize(
    "events",
    [
        # 정정 요청(09:58) 뒤 그보다 이른 시각(09:57)의 접수 보고가 09:59에 도착
        [make_event("E-1", "C-9", 5, S.ACCEPTED, "09:50"),
         make_event("E-2", "C-9", 5, S.REPLACE_REQUESTED, "09:58", replacement=8),
         make_event("E-3", "C-9R", 8, S.PENDING_SUBMIT, "09:58"),
         make_event("E-4", "C-9", 5, S.ACCEPTED, "09:57", available="09:59")],
        # 취소 요청(09:56) 뒤 그보다 이른 시각(09:55)의 부분 체결 보고가 09:57에 도착
        [make_event("E-1", "C-1", 10, S.ACCEPTED, "09:50"),
         make_event("E-2", "C-1", 10, S.CANCEL_REQUESTED, "09:56"),
         make_event("E-3", "C-1", 10, S.PARTIALLY_FILLED, "09:55", available="09:57", filled=3)],
        # UNKNOWN(09:55) 뒤 그보다 이른 시각(09:51)의 접수 응답이 09:56에 도착
        [make_event("E-1", "C-1", 10, S.PENDING_SUBMIT, "09:50"),
         make_event("E-2", "C-1", 10, S.UNKNOWN, "09:55"),
         make_event("E-3", "C-1", 10, S.ACCEPTED, "09:51", available="09:56")],
    ],
)
def test_stale_report_cannot_erase_a_pending_request_or_unknown(events):
    """검토 MEDIUM-3. 입력: 정정 요청·취소 요청·UNKNOWN 기록 뒤, 그 기록보다 이른 시각에 일어난 일을 알리는 보고가 늦게 도착해
    상태를 바꾸려 함.
    출력: OrderEventIntegrityError. 요청·UNKNOWN 이전의 보고로는 그 요청의 결과나 UNKNOWN을 확인할 수 없다 (R9-6, RP-3, R9-4).
    그대로 두면 REPLACE_PENDING·CANCEL_PENDING·UNKNOWN 차단이 사라진다."""
    with pytest.raises(OrderEventIntegrityError):
        orders_as_of(events, at("10:00"), completeness=COMPLETE, completeness_ref="x")


def test_late_fill_recorded_with_the_pending_request_kept_is_accepted():
    """입력: 취소 요청(09:56) 뒤 09:55의 체결 +3 통보(브로커)가 09:57에 도착했고, 기록은 취소 요청 상태를 유지하며 체결 3을 더함.
    출력: 받아들인다. Snapshot은 CANCEL_REQUESTED·체결 3 (늦은 체결 통보 자체는 정상, R9-6, CE-3·RP-4)."""
    events = [
        make_event("E-1", "C-1", 10, S.ACCEPTED, "09:50"),
        make_event("E-2", "C-1", 10, S.CANCEL_REQUESTED, "09:56"),
        make_event("E-3", "C-1", 10, S.CANCEL_REQUESTED, "09:55", available="09:57", filled=3, source=OrderStatusSource.BROKER),
    ]

    record = orders_as_of(events, at("10:00"), completeness=COMPLETE, completeness_ref="x").records()[0]

    assert (record.status, record.filled_quantity) == (S.CANCEL_REQUESTED, 3)
