"""P0-03B Slice 2: 주문 기록과 미체결 잔량 (ADR-0009 §5.1, §6.2).

주문 상태는 브로커·시뮬레이터가 확인한 결과 상태와, 시스템이 보낸 요청 상태를 구분한다. 계산 코드는 상태를 만들지 않는다.
"""

import pytest

from carver_quant.lab.accounting.order_projection import remaining_quantity
from carver_quant.lab.domain.orders import OrderRecord, OrderStatus, OrderStatusSource

S = OrderStatus
SYSTEM = OrderStatusSource.SYSTEM
BROKER = OrderStatusSource.BROKER
SIMULATOR = OrderStatusSource.SIMULATOR


def make_order(status, quantity=10, filled=0, cancelled=0, replacement=None, source=BROKER, broker_order_id="B-1", replacement_id=None):
    if replacement is not None and replacement_id is None:
        replacement_id = "C-1R"
    return OrderRecord(
        account_id="A1",
        client_order_id="C-1",
        broker_order_id=broker_order_id,
        contract_id="FUT.ALPHA.C1",
        quantity=quantity,
        status=status,
        filled_quantity=filled,
        cancelled_quantity=cancelled,
        replacement_quantity=replacement,
        replacement_client_order_id=replacement_id,
        status_source=source,
        status_event_ref="event:1",
    )


def test_adr_0009_order_states_are_all_recognized():
    """입력: ADR-0009 §6.2의 주문 상태 목록.
    출력: 11개 상태가 모두 있고 이름이 ADR과 같다 (구현이 쓰지 않는 상태도 잘못된 상태로 보지 않음)."""
    assert [status.name for status in OrderStatus] == [
        "INTENT",
        "PENDING_SUBMIT",
        "ACCEPTED",
        "REJECTED",
        "PARTIALLY_FILLED",
        "FILLED",
        "CANCEL_REQUESTED",
        "CANCELLED",
        "REPLACE_REQUESTED",
        "EXPIRED",
        "UNKNOWN",
    ]


def test_s2_01_remaining_after_partial_fill():
    """S2-01. 입력: 매수 주문 +10계약, 확인된 체결 +3, 확인된 취소 0 (PARTIALLY_FILLED, 브로커 확인).
    출력: 잔량 = 10 − 3 − 0 = +7계약 (ADR-0009 §5.1)."""
    assert remaining_quantity(make_order(S.PARTIALLY_FILLED, filled=3)) == 7


def test_s2_07_remaining_after_partial_fill_and_confirmed_cancel():
    """S2-07. 입력: 주문 +10, 확인된 부분 체결 +3, 확인된 취소 +2.
    출력: 잔량 = 10 − 3 − 2 = +5계약."""
    assert remaining_quantity(make_order(S.PARTIALLY_FILLED, filled=3, cancelled=2)) == 5


def test_sell_order_remaining_keeps_sign():
    """입력: 매도 주문 −10, 체결 −3, 취소 0.
    출력: 잔량 −7계약 (부호 있는 수량)."""
    assert remaining_quantity(make_order(S.PARTIALLY_FILLED, quantity=-10, filled=-3)) == -7


@pytest.mark.parametrize(
    ("filled", "cancelled", "replacement", "status"),
    [
        (-3, 0, None, S.PARTIALLY_FILLED),
        (3, -2, None, S.PARTIALLY_FILLED),
        (3, 0, -8, S.REPLACE_REQUESTED),
    ],
)
def test_filled_cancelled_and_replacement_must_follow_order_direction(filled, cancelled, replacement, status):
    """입력: 매수 주문 +10에 음수 체결, 음수 취소, 매도 방향의 정정 수량.
    출력: ValueError. 수량 부호가 주문 방향과 일치해야 한다."""
    with pytest.raises(ValueError):
        make_order(status, filled=filled, cancelled=cancelled, replacement=replacement, source=SYSTEM if status is S.REPLACE_REQUESTED else BROKER)


@pytest.mark.parametrize(("filled", "cancelled"), [(11, 0), (8, 3)])
def test_filled_plus_cancelled_cannot_exceed_order_quantity(filled, cancelled):
    """입력: 주문 +10에 체결 11, 또는 체결 8 + 취소 3.
    출력: ValueError. 누적 체결·취소가 주문 수량을 넘으면 차단한다 (AT-0009-1 예외조건)."""
    with pytest.raises(ValueError):
        make_order(S.UNKNOWN, filled=filled, cancelled=cancelled, source=SYSTEM)


@pytest.mark.parametrize("status", [S.ACCEPTED, S.REJECTED, S.PARTIALLY_FILLED, S.FILLED, S.CANCELLED, S.EXPIRED])
def test_result_states_cannot_be_created_by_the_system(status):
    """입력: 결과 상태(접수·거부·체결·취소 확정·만료)를 출처 SYSTEM으로 만든 기록.
    출력: ValueError. 결과 상태는 브로커 응답·조회·체결 통보나 시뮬레이터 확인으로만 생긴다 (ADR-0009 §6.2)."""
    filled = {S.PARTIALLY_FILLED: 3, S.FILLED: 10, S.CANCELLED: 3}.get(status, 0)
    cancelled = 7 if status is S.CANCELLED else 0
    with pytest.raises(ValueError):
        make_order(status, filled=filled, cancelled=cancelled, source=SYSTEM)
    assert make_order(status, filled=filled, cancelled=cancelled, source=SIMULATOR).status is status


def test_intent_is_only_a_system_record_without_fills_or_broker_id():
    """입력: (a) 브로커 출처 INTENT, (b) 체결이 있는 INTENT, (c) Broker Order ID가 있는 INTENT, (d) 정상 INTENT.
    출력: (a)~(c) ValueError, (d) 생성. 제출 전 주문 의도는 시스템 기록이다 (ADR-0009 §6.2, §6.4)."""
    with pytest.raises(ValueError):
        make_order(S.INTENT, source=BROKER, broker_order_id=None)
    with pytest.raises(ValueError):
        make_order(S.INTENT, filled=1, source=SYSTEM, broker_order_id=None)
    with pytest.raises(ValueError):
        make_order(S.INTENT, source=SYSTEM)
    assert make_order(S.INTENT, source=SYSTEM, broker_order_id=None).status is S.INTENT


@pytest.mark.parametrize(
    ("status", "filled", "cancelled"),
    [
        (S.ACCEPTED, 3, 0),
        (S.REJECTED, 3, 0),
        (S.PARTIALLY_FILLED, 0, 0),
        (S.PARTIALLY_FILLED, 3, 7),
        (S.FILLED, 5, 0),
        (S.CANCELLED, 3, 0),
    ],
)
def test_result_state_quantities_must_match_the_state_meaning(status, filled, cancelled):
    """입력: 상태 의미와 맞지 않는 수량 (접수인데 체결 있음, 거부인데 체결 있음, 부분 체결인데 체결 0 또는 잔량 0,
    전량 체결인데 체결 5/10, 취소 확정인데 잔량 7).
    출력: ValueError. 모순된 기록으로 잔량을 추정하지 않는다 (ADR-0009 §6.2 의미 칸)."""
    with pytest.raises(ValueError):
        make_order(status, filled=filled, cancelled=cancelled)


def test_replacement_quantity_only_for_replace_requested():
    """입력: (a) REPLACE_REQUESTED인데 정정 수량 없음, (b) ACCEPTED인데 정정 수량 있음.
    출력: 둘 다 ValueError. 정정 요청 수량은 정정 요청 중인 주문(또는 그 상태에서 UNKNOWN이 된 주문)에만 있다 (RP-1, RP-5)."""
    with pytest.raises(ValueError):
        make_order(S.REPLACE_REQUESTED, source=SYSTEM)
    with pytest.raises(ValueError):
        make_order(S.ACCEPTED, replacement=8)


def test_replacement_is_linked_by_its_own_client_order_id():
    """입력: (a) 정정 수량은 있는데 정정 주문 ID 없음, (b) 정정 주문 ID가 자기 자신, (c) 정정 수량 없이 정정 주문 ID만 있음,
    (d) 정정 요청 중 timeout으로 UNKNOWN이 된 주문이 정정 수량 +8과 정정 주문 ID를 유지.
    출력: (a)~(c) ValueError, (d) 생성. 정정 주문은 자기 Client Order ID로 연결해 한 번만 집계한다 (ADR-0009 §6.4, RP-5)."""
    with pytest.raises(ValueError):
        OrderRecord(
            account_id="A1", client_order_id="C-1", broker_order_id="B-1", contract_id="FUT.ALPHA.C1", quantity=10,
            status=S.REPLACE_REQUESTED, filled_quantity=0, cancelled_quantity=0, replacement_quantity=8,
            replacement_client_order_id=None, status_source=SYSTEM, status_event_ref="event:1",
        )
    with pytest.raises(ValueError):
        make_order(S.REPLACE_REQUESTED, replacement=8, replacement_id="C-1", source=SYSTEM)
    with pytest.raises(ValueError):
        make_order(S.ACCEPTED, replacement_id="C-1R")
    unknown = make_order(S.UNKNOWN, replacement=8, source=SYSTEM)
    assert (unknown.replacement_quantity, unknown.replacement_client_order_id) == (8, "C-1R")


def test_remaining_of_unknown_order_is_not_a_confirmed_remaining():
    """입력: 주문 +10 UNKNOWN (체결 3, 보고된 취소 2).
    출력: remaining_quantity는 ValueError. UNKNOWN 주문에는 확인된 잔량이 없다 (최악 경우는 10 − 3 = 7로 따로 계산, BR-12)."""
    with pytest.raises(ValueError):
        remaining_quantity(make_order(S.UNKNOWN, filled=3, cancelled=2, source=SYSTEM))


@pytest.mark.parametrize("bad", [True, 10.0, "10", 0])
def test_order_quantity_must_be_non_zero_int(bad):
    """입력: bool, float, 문자열, 0 주문 수량.
    출력: ValueError."""
    with pytest.raises(ValueError):
        make_order(S.ACCEPTED, quantity=bad)


def test_status_and_source_must_be_enum_members():
    """입력: 상태나 출처에 문자열.
    출력: ValueError (해석되지 않은 상태를 받지 않음)."""
    with pytest.raises(ValueError):
        make_order("ACCEPTED")
    with pytest.raises(ValueError):
        make_order(S.ACCEPTED, source="BROKER")
