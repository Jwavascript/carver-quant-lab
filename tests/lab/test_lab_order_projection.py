"""P0-03B Slice 2: 예상 포지션, 주문 후보, 제출 전 로컬 검증.

ADR-0009 §5.1, §6.2, R9-1, R9-7, RP-1, ADR-0003 §6.3, ADR-0012 BR-2·BR-12, ADR-0013 R13-1·R13-5, ADR-0006 I6-5.
기대값은 저장소 밖 독립 산술로 먼저 확인했다. 가상 선물이며 실제 시장의 주문 제약을 주장하지 않는다.
"""

from datetime import datetime, timezone

import pytest

from carver_quant.lab.accounting.fill_ledger import FillIntegrityError, FillLedger, apply_fill
from carver_quant.lab.accounting.order_projection import (
    CandidateStatus,
    LocalValidationStatus,
    OrderIntegrityError,
    prepare_order_candidates,
    project_positions,
    validate_new_order_quantity,
)
from carver_quant.lab.domain.orders import OrderRecord, OrderStatus, OrderStatusSource
from carver_quant.lab.domain.records import FillKey, FillOrigin, FillRecord, FuturesContractSpec, PositionBaseline

UTC = timezone.utc
S = OrderStatus
C1 = "FUT.ALPHA.C1"
C2 = "FUT.ALPHA.C2"
T0 = datetime(2026, 10, 19, 0, 0, tzinfo=UTC)
FILL_AT = datetime(2026, 10, 19, 14, 0, tzinfo=UTC)
AS_OF = datetime(2026, 10, 20, 0, 0, tzinfo=UTC)
SYSTEM_STATES = {S.INTENT, S.PENDING_SUBMIT, S.CANCEL_REQUESTED, S.REPLACE_REQUESTED, S.UNKNOWN}


def contract(contract_id, lot_size=1):
    return FuturesContractSpec(contract_id=contract_id, instrument_id="FUT.ALPHA", currency="USD", multiplier="10", lot_size=lot_size)


def make_order(client_order_id, contract_id, quantity, status, filled=0, cancelled=0, replacement=None, replacement_id=None):
    if replacement is not None and replacement_id is None:
        replacement_id = client_order_id + "R"
    return OrderRecord(
        account_id="A1",
        client_order_id=client_order_id,
        broker_order_id=None if status is S.INTENT else "B-" + client_order_id,
        contract_id=contract_id,
        quantity=quantity,
        status=status,
        filled_quantity=filled,
        cancelled_quantity=cancelled,
        replacement_quantity=replacement,
        replacement_client_order_id=replacement_id,
        status_source=OrderStatusSource.SYSTEM if status in SYSTEM_STATES else OrderStatusSource.BROKER,
        status_event_ref="event:" + client_order_id,
    )


def make_fill(fill_id, client_order_id, contract_id, quantity, fill_at=FILL_AT):
    return FillRecord(
        key=FillKey(account_id="A1", fill_source="BRK", fill_id=fill_id),
        client_order_id=client_order_id,
        broker_order_id="B-" + client_order_id,
        contract_id=contract_id,
        quantity=quantity,
        price="100",
        fill_at=fill_at,
        fee="1",
        fee_currency="USD",
        origin=FillOrigin.BROKER_REPORTED,
        execution_assumption_ref=None,
        venue=None,
        liquidity_flag=None,
    )


def ledger_with(*fills, specs=None):
    ledger = FillLedger.empty(account_id="A1", contracts=specs or (contract(C1), contract(C2)))
    for fill in fills:
        ledger = apply_fill(ledger, fill).ledger
    return ledger


def baseline(c1=0, c2=0):
    return PositionBaseline(account_id="A1", as_of=T0, quantities={C1: c1, C2: c2}, verification_ref="fixture:verified")


def prepare(ledger, orders, targets, base=None):
    return prepare_order_candidates(baseline=base or baseline(), ledger=ledger, orders=orders, targets=targets, as_of=AS_OF)


def result_for(report, contract_id):
    [result] = [row for row in report.results if row.contract_id == contract_id]
    return result


def test_s2_02_expected_projection_and_zero_candidate():
    """S2-02. 입력: 기준 0, 주문 C-1 +10 PARTIALLY_FILLED (체결 +3, 장부에 체결 +3), 목표 C1 +10, C2 0.
    출력: 실제 +3, 잔량 +7, 기대 예상 +10, 후보 0 → NO_ORDER_NEEDED. 최악 경우 롱 10, 숏 3 (ADR-0003 §6.3)."""
    ledger = ledger_with(make_fill("X-1", "C-1", C1, 3))
    orders = [make_order("C-1", C1, 10, S.PARTIALLY_FILLED, filled=3)]

    report = prepare(ledger, orders, {C1: 10, C2: 0})

    unit = report.projection.unit(C1)
    assert (unit.actual_quantity, unit.open_remaining_quantity, unit.expected_projected_quantity) == (3, 7, 10)
    assert (unit.worst_long_quantity, unit.worst_short_quantity) == (10, 3)
    result = result_for(report, C1)
    assert result.candidate_quantity == 0
    assert result.status is CandidateStatus.NO_ORDER_NEEDED


def test_confirmed_fills_are_not_subtracted_twice():
    """입력: S2-02와 같고, 같은 체결 X-1을 한 번 더 수신 (DUPLICATE).
    출력: 실제 +3, 잔량 +7, 기대 예상 +10 그대로 (7이나 13이 아님). 체결은 실제 포지션에 한 번, 잔량 차감에 한 번만 쓰인다."""
    fill = make_fill("X-1", "C-1", C1, 3)
    ledger = apply_fill(ledger_with(fill), fill).ledger
    orders = [make_order("C-1", C1, 10, S.PARTIALLY_FILLED, filled=3)]

    unit = project_positions(baseline=baseline(), ledger=ledger, orders=orders, as_of=AS_OF).unit(C1)

    assert (unit.actual_quantity, unit.open_remaining_quantity, unit.expected_projected_quantity) == (3, 7, 10)


def test_s2_03_actual_15_records_but_candidate_minus_15_fails_lot_check():
    """S2-03. 입력: lot 10 월물, 기준(검증된 실제) 15계약, 미체결 없음, 목표 0.
    출력: 실제 15는 그대로 유효 (ADR-0013 R13-1·R13-3). 기대 예상 15, 후보 −15를 기록하고 반올림하지 않는다.
    로컬 검사 LOCAL_INVALID(NOT_LOT_MULTIPLE). 최악 경우(후보 포함) 롱 15, 숏 0."""
    ledger = ledger_with(specs=(contract(C1, lot_size=10), contract(C2)))

    report = prepare(ledger, [], {C1: 0, C2: 0}, base=baseline(c1=15))

    assert report.projection.unit(C1).actual_quantity == 15
    result = result_for(report, C1)
    assert result.candidate_quantity == -15
    assert result.status is CandidateStatus.LOCAL_INVALID
    assert result.reasons == ("NOT_LOT_MULTIPLE",)
    assert (result.worst_long_after, result.worst_short_after) == (15, 0)


def test_s2_04_confirmed_remaining_makes_candidate_lot_multiple():
    """S2-04. 입력: lot 10, 기준 10계약, 주문 C-1 +10 PARTIALLY_FILLED (브로커 보고 체결 +5), 목표 30.
    출력: 실제 15, 잔량 +5, 기대 예상 20, 후보 +10 → LOCAL_VALID. 로컬 검사 통과일 뿐 제출 승인이 아니다
    (L1·L2 위험 검사와 L3 Trading State 확인이 남음). 최악 경우(후보 포함) 롱 15 + 5 + 10 = 30, 숏 15 (AT-0013-7 (iii))."""
    ledger = ledger_with(make_fill("X-1", "C-1", C1, 5), specs=(contract(C1, lot_size=10), contract(C2)))
    orders = [make_order("C-1", C1, 10, S.PARTIALLY_FILLED, filled=5)]

    report = prepare(ledger, orders, {C1: 30, C2: 0}, base=baseline(c1=10))

    unit = report.projection.unit(C1)
    assert (unit.actual_quantity, unit.open_remaining_quantity, unit.expected_projected_quantity) == (15, 5, 20)
    result = result_for(report, C1)
    assert result.candidate_quantity == 10
    assert result.status is CandidateStatus.LOCAL_VALID
    assert result.reasons == ()
    assert result.pending_checks == ("L1_L2_PRE_TRADE_RISK", "L3_TRADING_STATE")
    assert (result.worst_long_after, result.worst_short_after) == (30, 15)


def test_s2_05_unknown_order_blocks_candidates_and_counts_as_filled_in_worst_case():
    """S2-05. 입력: 실제 0, 주문 C-5 +5 제출 결과 UNKNOWN (시스템이 timeout 뒤 분류). C2에는 주문 없음. 목표 C1 +5, C2 +2.
    출력: C1 최악 경우 롱 +5 (전량 체결로 간주), 기대 예상은 계산 불가(UNKNOWN_ORDER).
    모든 월물의 후보 계산이 BLOCKED(UNKNOWN_ORDER_PRESENT) (ADR-0003 §6.3·§6.5, ADR-0009 R9-12)."""
    orders = [make_order("C-5", C1, 5, S.UNKNOWN)]

    report = prepare(ledger_with(), orders, {C1: 5, C2: 2})

    unit = report.projection.unit(C1)
    assert unit.worst_long_quantity == 5
    assert unit.expected_projected_quantity is None
    assert unit.not_computable_reasons == ("UNKNOWN_ORDER",)
    assert report.projection.unknown_client_order_ids == ("C-5",)
    for contract_id in (C1, C2):
        result = result_for(report, contract_id)
        assert result.status is CandidateStatus.BLOCKED
        assert result.candidate_quantity is None
        assert "UNKNOWN_ORDER_PRESENT" in result.reasons


def test_unknown_is_not_treated_as_rejected_or_cancelled_even_with_cancel_report():
    """입력: 주문 +10 UNKNOWN, 확인된 체결 +3 (장부에 있음), 브로커가 보고했던 취소 2.
    출력: 최악 경우 롱 = 실제 3 + (10 − 3) = 10. 취소 보고로 7을 5로 줄이지 않는다 (BR-12, Q12-14)."""
    ledger = ledger_with(make_fill("X-1", "C-1", C1, 3))
    orders = [make_order("C-1", C1, 10, S.UNKNOWN, filled=3, cancelled=2)]

    unit = project_positions(baseline=baseline(), ledger=ledger, orders=orders, as_of=AS_OF).unit(C1)

    assert unit.worst_long_quantity == 10
    assert unit.expected_projected_quantity is None


def test_s2_06_cancel_request_is_not_cancellation():
    """S2-06. 입력: 실제 0, 주문 +10 CANCEL_REQUESTED (체결 0, 취소 확정 0). 목표 +10.
    출력: 잔량 +10이 기대 예상과 최악 경우에 그대로 들어간다 (R9-6). 기대 예상 10, 후보 0 → NO_ORDER_NEEDED."""
    orders = [make_order("C-6", C1, 10, S.CANCEL_REQUESTED)]

    report = prepare(ledger_with(), orders, {C1: 10, C2: 0})

    unit = report.projection.unit(C1)
    assert (unit.open_remaining_quantity, unit.expected_projected_quantity, unit.worst_long_quantity) == (10, 10, 10)
    assert result_for(report, C1).status is CandidateStatus.NO_ORDER_NEEDED


def test_s2_07_partial_fill_and_confirmed_cancel_in_projection():
    """S2-07. 입력: 주문 +10 PARTIALLY_FILLED, 체결 +3 (장부), 확인된 취소 +2.
    출력: 잔량 +5, 기대 예상 = 3 + 5 = 8, 최악 경우 롱 8."""
    ledger = ledger_with(make_fill("X-1", "C-1", C1, 3))
    orders = [make_order("C-1", C1, 10, S.PARTIALLY_FILLED, filled=3, cancelled=2)]

    unit = project_positions(baseline=baseline(), ledger=ledger, orders=orders, as_of=AS_OF).unit(C1)

    assert (unit.open_remaining_quantity, unit.expected_projected_quantity, unit.worst_long_quantity) == (5, 8, 8)


def test_s2_08_contracts_are_projected_separately():
    """S2-08. 입력: C1 주문 +10 PARTIALLY_FILLED (체결 +3), C2 매도 주문 −4 ACCEPTED.
    출력: C1 기대 예상 10, 최악 롱 10·숏 3. C2 기대 예상 −4, 최악 롱 0·숏 −4. 월물끼리 합치지 않는다."""
    ledger = ledger_with(make_fill("X-1", "C-1", C1, 3))
    orders = [make_order("C-1", C1, 10, S.PARTIALLY_FILLED, filled=3), make_order("C-2", C2, -4, S.ACCEPTED)]

    projection = project_positions(baseline=baseline(), ledger=ledger, orders=orders, as_of=AS_OF)

    c1, c2 = projection.unit(C1), projection.unit(C2)
    assert (c1.expected_projected_quantity, c1.worst_long_quantity, c1.worst_short_quantity) == (10, 10, 3)
    assert (c2.expected_projected_quantity, c2.worst_long_quantity, c2.worst_short_quantity) == (-4, 0, -4)


def test_s2_09_zero_candidate_needs_no_new_order():
    """S2-09. 입력: 실제 0, 미체결 없음, 목표 0.
    출력: 후보 0, NO_ORDER_NEEDED, 로컬 검사·최악 경우 추가 없음."""
    result = result_for(prepare(ledger_with(), [], {C1: 0, C2: 0}), C1)

    assert result.candidate_quantity == 0
    assert result.status is CandidateStatus.NO_ORDER_NEEDED
    assert (result.worst_long_after, result.worst_short_after) == (None, None)


def test_s2_10_missing_lot_size_fails_local_check_without_default():
    """S2-10. 입력: lot size가 없는 월물 (None), 실제 0, 목표 +5.
    출력: 후보 +5, LOCAL_INVALID(LOT_SIZE_MISSING). lot size를 1로 가정하지 않는다."""
    ledger = ledger_with(specs=(contract(C1, lot_size=None), contract(C2)))

    result = result_for(prepare(ledger, [], {C1: 5, C2: 0}), C1)

    assert result.candidate_quantity == 5
    assert result.status is CandidateStatus.LOCAL_INVALID
    assert result.reasons == ("LOT_SIZE_MISSING",)


@pytest.mark.parametrize(
    ("contract_id", "quantity", "reasons"),
    [
        (C1, 2.0, ("QUANTITY_NOT_INTEGER",)),
        (C1, True, ("QUANTITY_NOT_INTEGER",)),
        (C1, "5", ("QUANTITY_NOT_INTEGER",)),
        (C1, 0, ("ZERO_QUANTITY",)),
        ("FUT.ALPHA.C9", 10, ("UNKNOWN_CONTRACT",)),
        (C1, 15, ("NOT_LOT_MULTIPLE",)),
        (C1, -20, ()),
    ],
)
def test_local_validation_reports_explicit_reasons(contract_id, quantity, reasons):
    """S2-10 등. 입력: lot 10 월물에 대한 신규 주문 수량 (float, bool, 문자열, 0, 모르는 월물, 15, −20).
    출력: LOCAL_INVALID와 사유, 또는 −20은 LOCAL_VALID. 자동 반올림·기본값 없음 (ADR-0013 R13-5, I6-5, BR-2)."""
    ledger = ledger_with(specs=(contract(C1, lot_size=10), contract(C2)))

    validation = validate_new_order_quantity(ledger=ledger, contract_id=contract_id, quantity=quantity)

    assert validation.reasons == reasons
    expected_status = LocalValidationStatus.LOCAL_VALID if not reasons else LocalValidationStatus.LOCAL_INVALID
    assert validation.status is expected_status


def test_actual_15_is_valid_in_ledger_but_new_order_15_is_validated_separately():
    """입력: lot 10, 기준 15계약 (검증됨), 같은 크기 15계약의 신규 주문 수량.
    출력: 실제 포지션 15는 유효. 신규 주문 15는 LOCAL_INVALID(NOT_LOT_MULTIPLE) (ADR-0013 AT-0013-10)."""
    ledger = ledger_with(specs=(contract(C1, lot_size=10), contract(C2)))

    projection = project_positions(baseline=baseline(c1=15), ledger=ledger, orders=[], as_of=AS_OF)
    validation = validate_new_order_quantity(ledger=ledger, contract_id=C1, quantity=15)

    assert projection.unit(C1).actual_quantity == 15
    assert validation.reasons == ("NOT_LOT_MULTIPLE",)


def test_replace_request_uses_sum_for_worst_case_and_blocks_that_contract():
    """입력 (AT-0009-9): 실제 0, 주문 C-9 +5 (체결 0)에 +8 정정 요청 (REPLACE_REQUESTED). C2는 주문 없음. 목표 C1 +5, C2 +2.
    출력: C1 최악 경우 롱 = 0 + 5 + 8 = 13 (RP-1, max 8이 아님). 기대 예상은 승인된 규칙이 없어 계산 불가(REPLACE_PENDING),
    C1 후보 BLOCKED. C2는 정상 계산: 후보 +2 → LOCAL_VALID."""
    orders = [make_order("C-9", C1, 5, S.REPLACE_REQUESTED, replacement=8)]

    report = prepare(ledger_with(), orders, {C1: 5, C2: 2})

    unit = report.projection.unit(C1)
    assert unit.worst_long_quantity == 13
    assert unit.expected_projected_quantity is None
    assert unit.not_computable_reasons == ("REPLACE_PENDING",)
    assert result_for(report, C1).status is CandidateStatus.BLOCKED
    assert result_for(report, C1).reasons == ("REPLACE_PENDING",)
    assert result_for(report, C2).candidate_quantity == 2
    assert result_for(report, C2).status is CandidateStatus.LOCAL_VALID


@pytest.mark.parametrize(
    ("status", "filled", "cancelled", "replacement", "remaining", "expected", "worst_long"),
    [
        (S.INTENT, 0, 0, None, 0, 3, 3),
        (S.PENDING_SUBMIT, 0, 0, None, 10, 13, 13),
        (S.ACCEPTED, 0, 0, None, 10, 13, 13),
        (S.REJECTED, 0, 0, None, 0, 3, 3),
        (S.PARTIALLY_FILLED, 3, 0, None, 7, 10, 10),
        (S.FILLED, 10, 0, None, 0, 3, 3),
        (S.CANCEL_REQUESTED, 3, 0, None, 7, 10, 10),
        (S.CANCELLED, 3, 7, None, 0, 3, 3),
        (S.REPLACE_REQUESTED, 3, 0, 8, None, None, 18),
        (S.EXPIRED, 3, 0, None, 0, 3, 3),
        (S.UNKNOWN, 3, 0, None, None, None, 10),
    ],
)
def test_each_adr_0009_state_contributes_per_the_state_table(status, filled, cancelled, replacement, remaining, expected, worst_long):
    """입력: 다른 주문 체결로 실제 +3 (C-0, FILLED +3). 시험 대상 주문 C-1 +10의 각 상태 (체결 수량은 장부와 일치).
    출력: ADR-0009 §6.2 표대로 잔량·기대 예상·최악 경우 롱이 정해진다. 종료 상태와 INTENT는 0, 진행 중 상태는 잔량,
    REPLACE_REQUESTED는 잔량 + 정정 수량 전체(RP-1)이며 기대 예상은 계산 불가, UNKNOWN은 주문 수량 − 확인된 체결이며 기대 예상은 계산 불가."""
    fills = [make_fill("X-0", "C-0", C1, 3)]
    if filled:
        fills.append(make_fill("X-1", "C-1", C1, filled))
    ledger = ledger_with(*fills)
    base_actual = 3 + filled
    orders = [
        make_order("C-0", C1, 3, S.FILLED, filled=3),
        make_order("C-1", C1, 10, status, filled=filled, cancelled=cancelled, replacement=replacement),
    ]

    unit = project_positions(baseline=baseline(), ledger=ledger, orders=orders, as_of=AS_OF).unit(C1)

    assert unit.actual_quantity == base_actual
    if expected is None:
        assert unit.open_remaining_quantity is None
        assert unit.expected_projected_quantity is None
    else:
        assert unit.open_remaining_quantity == remaining
        assert unit.expected_projected_quantity == expected + filled
    assert unit.worst_long_quantity == worst_long + filled


def test_duplicate_client_order_id_is_rejected():
    """입력: 같은 Client Order ID C-1의 주문 기록 두 건.
    출력: ValueError. 같은 주문을 두 번 집계하지 않는다."""
    orders = [make_order("C-1", C1, 10, S.ACCEPTED), make_order("C-1", C1, 10, S.ACCEPTED)]
    with pytest.raises(ValueError):
        project_positions(baseline=baseline(), ledger=ledger_with(), orders=orders, as_of=AS_OF)


@pytest.mark.parametrize(
    ("fills", "order"),
    [
        ([("X-1", "C-1", C1, 4)], ("C-1", C1, 10, S.PARTIALLY_FILLED, 3)),
        ([("X-1", "C-1", C1, -3)], ("C-1", C1, 10, S.PARTIALLY_FILLED, 3)),
        ([("X-1", "C-1", C2, 3)], ("C-1", C1, 10, S.PARTIALLY_FILLED, 3)),
        ([("X-1", "C-1", C1, 3), ("X-2", "C-1", C1, 3)], ("C-1", C1, 5, S.PARTIALLY_FILLED, 3)),
        ([("X-1", "C-X", C1, 3)], ("C-1", C1, 10, S.ACCEPTED, 0)),
    ],
)
def test_fill_and_order_records_must_agree(fills, order):
    """입력: (a) 장부 체결 +4인데 주문 체결 3, (b) 매수 주문에 매도 체결, (c) 다른 월물의 체결, (d) 장부 체결 합 6이 주문 수량 5를 넘음,
    (e) 기준 시각 뒤 체결의 주문(C-X)이 주문 목록에 없음.
    출력: OrderIntegrityError. 체결은 주문 ID로 귀속하고, 맞지 않으면 계산하지 않는다 (ADR-0009 RP-4)."""
    ledger = ledger_with(*[make_fill(*fill) for fill in fills])
    client_order_id, contract_id, quantity, status, filled = order
    orders = [make_order(client_order_id, contract_id, quantity, status, filled=filled)]
    with pytest.raises(OrderIntegrityError):
        project_positions(baseline=baseline(), ledger=ledger, orders=orders, as_of=AS_OF)
    assert issubclass(OrderIntegrityError, ValueError)


def test_fill_after_projection_time_is_rejected():
    """입력: 장부에 계산 시각 뒤의 체결이 있음.
    출력: ValueError (주문 기록이 이미 그 체결을 반영했을 수 있어 실제·잔량이 어긋남)."""
    ledger = ledger_with(make_fill("X-1", "C-1", C1, 3, fill_at=datetime(2026, 10, 20, 1, 0, tzinfo=UTC)))
    orders = [make_order("C-1", C1, 10, S.PARTIALLY_FILLED, filled=3)]
    with pytest.raises(ValueError):
        project_positions(baseline=baseline(), ledger=ledger, orders=orders, as_of=AS_OF)


def test_order_inputs_must_match_ledger_account_and_contracts():
    """입력: (a) 장부에 없는 월물의 주문, (b) 다른 계좌의 주문.
    출력: 둘 다 ValueError."""
    unknown_contract = make_order("C-1", "FUT.ALPHA.C9", 10, S.ACCEPTED)
    other_account = OrderRecord(
        account_id="A2",
        client_order_id="C-2",
        broker_order_id="B-2",
        contract_id=C1,
        quantity=10,
        status=S.ACCEPTED,
        filled_quantity=0,
        cancelled_quantity=0,
        replacement_quantity=None,
        replacement_client_order_id=None,
        status_source=OrderStatusSource.BROKER,
        status_event_ref="event:2",
    )
    for order in (unknown_contract, other_account):
        with pytest.raises(ValueError):
            project_positions(baseline=baseline(), ledger=ledger_with(), orders=[order], as_of=AS_OF)


def test_targets_must_be_complete_integers_and_lot_multiples():
    """입력: (a) C2 목표 누락, (b) bool 목표, (c) lot 10 월물에 목표 15.
    출력: 모두 ValueError. 목표 포지션의 lot 규칙(I6-5)은 그대로이고, 빠진 목표를 0으로 채우지 않는다."""
    ledger = ledger_with(specs=(contract(C1, lot_size=10), contract(C2)))
    for targets in ({C1: 10}, {C1: True, C2: 0}, {C1: 15, C2: 0}):
        with pytest.raises(ValueError):
            prepare(ledger, [], targets)


def test_conflicting_fill_ledger_still_blocks_projection():
    """입력: 같은 체결 키에 수량이 다른 재수신으로 CONFLICT가 기록된 장부.
    출력: FillIntegrityError. Slice 1의 충돌 차단이 Slice 2에서도 유지된다."""
    ledger = ledger_with(make_fill("X-1", "C-1", C1, 3))
    ledger = apply_fill(ledger, make_fill("X-1", "C-1", C1, 4)).ledger
    orders = [make_order("C-1", C1, 10, S.PARTIALLY_FILLED, filled=3)]
    with pytest.raises(FillIntegrityError):
        prepare(ledger, orders, {C1: 10, C2: 0})


def test_simulated_fill_with_unknown_lot_size_is_rejected():
    """입력: lot size가 없는 월물에 시뮬레이션 체결 +1, 같은 월물에 브로커 보고 체결 +1.
    출력: 시뮬레이션 체결은 ValueError (lot 배수인지 확인할 수 없음, R13-1), 브로커 체결은 반영된다."""
    ledger = ledger_with(specs=(contract(C1, lot_size=None), contract(C2)))
    simulated = FillRecord(
        key=FillKey(account_id="A1", fill_source="SIM-1", fill_id="S-1"),
        client_order_id="C-1",
        broker_order_id=None,
        contract_id=C1,
        quantity=1,
        price="100",
        fill_at=FILL_AT,
        fee="1",
        fee_currency="USD",
        origin=FillOrigin.SIMULATED,
        execution_assumption_ref="assumption:test-1",
        venue=None,
        liquidity_flag=None,
    )
    with pytest.raises(ValueError):
        apply_fill(ledger, simulated)
    assert len(apply_fill(ledger, make_fill("X-1", "C-1", C1, 1)).ledger.applied) == 1


def test_replace_with_separately_recorded_new_order_counts_new_quantity_once():
    """입력 (AT-0009-9 1행, 비원자적 표현): 실제 0, 기존 C-9 +5 REPLACE_REQUESTED (정정 +8 → C-9R),
    새 주문 C-9R +8 PENDING_SUBMIT이 따로 기록됨.
    출력: 최악 경우 롱 = 0 + 5 + 8 = 13 (새 수량을 두 번 더한 21이 아님). 기대 예상은 계산 불가(REPLACE_PENDING)."""
    orders = [make_order("C-9", C1, 5, S.REPLACE_REQUESTED, replacement=8), make_order("C-9R", C1, 8, S.PENDING_SUBMIT)]

    unit = project_positions(baseline=baseline(), ledger=ledger_with(), orders=orders, as_of=AS_OF).unit(C1)

    assert unit.worst_long_quantity == 13
    assert unit.expected_projected_quantity is None


@pytest.mark.parametrize("separate_new_order", [False, True])
def test_replace_timeout_keeps_old_plus_new_worst_case(separate_new_order):
    """입력 (AT-0009-9 2행, RP-5): 정정 응답 timeout으로 기존 C-9 +5가 UNKNOWN (정정 +8 → C-9R 유지).
    새 주문 C-9R이 따로 UNKNOWN으로 기록된 경우와 기록되지 않은 경우.
    출력: 두 경우 모두 최악 경우 롱 13 (5로 줄지 않음). 모든 후보 BLOCKED(UNKNOWN_ORDER_PRESENT)."""
    orders = [make_order("C-9", C1, 5, S.UNKNOWN, replacement=8)]
    if separate_new_order:
        orders.append(make_order("C-9R", C1, 8, S.UNKNOWN))

    report = prepare(ledger_with(), orders, {C1: 5, C2: 0})

    assert report.projection.unit(C1).worst_long_quantity == 13
    assert report.projection.unknown_client_order_ids == ("C-9", "C-9R")
    assert all(row.status is CandidateStatus.BLOCKED for row in report.results)


def test_confirmed_replace_leaves_only_the_new_order():
    """입력 (AT-0009-9 3행): 기존 C-9 +5 취소 확정 (CANCELLED, 체결 0, 취소 5), 새 주문 C-9R +8 ACCEPTED.
    출력: 최악 경우 롱 8, 진행 중 잔량 8, 기대 예상 8 (기존 주문은 종료)."""
    orders = [make_order("C-9", C1, 5, S.CANCELLED, cancelled=5), make_order("C-9R", C1, 8, S.ACCEPTED)]

    unit = project_positions(baseline=baseline(), ledger=ledger_with(), orders=orders, as_of=AS_OF).unit(C1)

    assert (unit.worst_long_quantity, unit.open_remaining_quantity, unit.expected_projected_quantity) == (8, 8, 8)


@pytest.mark.parametrize(
    "new_order",
    [("C-9R", C1, 7, S.PENDING_SUBMIT), ("C-9R", C2, 8, S.PENDING_SUBMIT)],
)
def test_replacement_record_must_match_the_requested_replacement(new_order):
    """입력: 기존 C-9 +5 REPLACE_REQUESTED (정정 +8 → C-9R)인데 따로 기록된 C-9R이 (a) +7이거나 (b) 다른 월물.
    출력: OrderIntegrityError (어느 수량이 맞는지 추정하지 않음)."""
    orders = [make_order("C-9", C1, 5, S.REPLACE_REQUESTED, replacement=8), make_order(*new_order)]
    with pytest.raises(OrderIntegrityError):
        project_positions(baseline=baseline(), ledger=ledger_with(), orders=orders, as_of=AS_OF)


def test_cancel_pending_holds_a_non_zero_candidate_for_that_contract():
    """입력: 실제 0, C1 주문 +10 CANCEL_REQUESTED, 목표 C1 0 (≠ 남은 수량 10), C2 +2.
    출력: C1 기대 예상 10 (잔량 포함). 목표 − 기대 예상 = −10 ≠ 0이지만 취소 확정 전에는 같은 상품에 새 주문을 만들지
    않으므로 후보 없이 BLOCKED(CANCEL_PENDING) (ADR-0009 AT-0009-3). 후보가 0이면 NO_ORDER_NEEDED (S2-06).
    C2는 정상 계산 (+2, LOCAL_VALID)."""
    orders = [make_order("C-6", C1, 10, S.CANCEL_REQUESTED)]

    report = prepare(ledger_with(), orders, {C1: 0, C2: 2})

    c1 = result_for(report, C1)
    assert c1.expected_projected_quantity == 10
    assert c1.status is CandidateStatus.BLOCKED
    assert c1.reasons == ("CANCEL_PENDING",)
    assert c1.candidate_quantity is None
    assert result_for(report, C2).status is CandidateStatus.LOCAL_VALID


def test_local_validation_normalizes_int_subclasses():
    """입력: 값 0인데 == 비교를 바꾼 int 하위 클래스 수량.
    출력: LOCAL_INVALID(ZERO_QUANTITY). 정수 하위 클래스는 일반 int로 바꿔 검사한다."""

    class NeverEqual(int):
        def __eq__(self, other):
            return False

        __hash__ = int.__hash__

    validation = validate_new_order_quantity(ledger=ledger_with(), contract_id=C1, quantity=NeverEqual(0))

    assert validation.reasons == ("ZERO_QUANTITY",)


@pytest.mark.parametrize(
    ("orders", "error"),
    [
        ([make_order("C-9", C1, 5, S.REPLACE_REQUESTED, replacement=8), make_order("C-9R", C1, 8, S.INTENT)], OrderIntegrityError),
        (
            [
                make_order("C-9", C1, 5, S.REPLACE_REQUESTED, replacement=8, replacement_id="C-X"),
                make_order("C-8", C1, 4, S.REPLACE_REQUESTED, replacement=6, replacement_id="C-X"),
            ],
            ValueError,
        ),
    ],
)
def test_replacement_link_cannot_drop_or_double_the_new_quantity(orders, error):
    """입력: (a) 정정 요청 중인데 따로 기록된 정정 주문 C-9R이 아직 INTENT (그대로 두면 최악 경우가 13이 아니라 5),
    (b) 두 주문이 같은 정정 주문 ID C-X를 가리킴 (그대로 두면 새 수량이 두 번 들어감).
    출력: (a) OrderIntegrityError, (b) ValueError. 최악 경우를 줄이거나 두 번 세지 않는다."""
    with pytest.raises(error):
        project_positions(baseline=baseline(), ledger=ledger_with(), orders=orders, as_of=AS_OF)
