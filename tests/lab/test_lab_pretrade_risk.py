"""P0-03C Slice 1: 거래 전 최악 경우 노출과 명시 한도 비교 (ADR-0003 §6.2.2·§6.3·§6.5, ADR-0009 R9-7·RP-1, ADR-0012 BR-12).

최악 경우 수량은 P0-03B Slice 2의 project_positions·prepare_order_candidates 결과를 그대로 쓴다. 기대값(15,000 USD 등)은
저장소 밖 독립 산술(Fraction)로 먼저 확인했다. 가상 선물이며, 위험 한도·참조 가격·승수는 모두 테스트 입력이다 (운영 기본값 아님).
WITHIN_LIMIT는 이 검사 항목의 결과일 뿐 주문 제출 승인이 아니다.
"""

import dataclasses
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from carver_quant.lab.accounting.fill_ledger import FillLedger, apply_fill
from carver_quant.lab.accounting.order_projection import CandidateStatus, prepare_order_candidates, project_positions
from carver_quant.lab.accounting.pretrade_risk import (
    REMAINING_PRE_SUBMISSION_STEPS,
    PreTradeRiskView,
    RiskCheckStatus,
    assess_pretrade_risk,
    compare_exposure_to_limit,
    projected_exposure,
    worst_case_positions,
)
from carver_quant.lab.domain.orders import OrderRecord, OrderStatus, OrderStatusSource
from carver_quant.lab.domain.records import FillKey, FillOrigin, FillRecord, FuturesContractSpec, PositionBaseline, ValuationPrice
from carver_quant.lab.domain.risk import ContractMultiplier, ExposureLimit, TradingState

UTC = timezone.utc
S = OrderStatus
C1 = "FUT.ALPHA.C1"
C2 = "FUT.ALPHA.C2"
T0 = datetime(2026, 10, 19, 0, 0, tzinfo=UTC)
FILL_AT = datetime(2026, 10, 19, 14, 0, tzinfo=UTC)
CLOSE = datetime(2026, 10, 19, 21, 0, tzinfo=UTC)
AVAILABLE = datetime(2026, 10, 19, 21, 30, tzinfo=UTC)
DECISION_AT = datetime(2026, 10, 20, 0, 0, tzinfo=UTC)
SYSTEM_STATES = {S.INTENT, S.PENDING_SUBMIT, S.CANCEL_REQUESTED, S.REPLACE_REQUESTED, S.UNKNOWN}
MULTIPLIERS = {C1: "10", C2: "50"}
PRICES = {C1: "100", C2: "20"}


def contract(contract_id, lot_size=1):
    return FuturesContractSpec(
        contract_id=contract_id, instrument_id="FUT.ALPHA", currency="USD", multiplier=MULTIPLIERS[contract_id], lot_size=lot_size
    )


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


def make_fill(fill_id, client_order_id, contract_id, quantity):
    return FillRecord(
        key=FillKey(account_id="A1", fill_source="BRK", fill_id=fill_id),
        client_order_id=client_order_id,
        broker_order_id="B-" + client_order_id,
        contract_id=contract_id,
        quantity=quantity,
        price="100",
        fill_at=FILL_AT,
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


def reference_price(contract_id, value=None, valuation_at=CLOSE, available=AVAILABLE):
    return ValuationPrice(
        contract_id=contract_id,
        price=value or PRICES[contract_id],
        valuation_at=valuation_at,
        data_available_at=available,
        source_ref="fixture:close",
    )


def multiplier(contract_id, value=None, currency="USD", available=T0):
    return ContractMultiplier(
        contract_id=contract_id,
        multiplier=value or MULTIPLIERS[contract_id],
        currency=currency,
        data_available_at=available,
        source_ref="fixture:contract-spec",
    )


def limit(contract_id, amount, currency="USD"):
    return ExposureLimit(contract_id=contract_id, currency=currency, max_exposure=amount, source_ref="test:limit")


def assess(ledger, orders, targets, c1_limit="12000", state=TradingState.NORMAL, base=None, prices=None, multipliers=None, limits=None):
    return assess_pretrade_risk(
        baseline=base or baseline(),
        ledger=ledger,
        orders=orders,
        targets=targets,
        decision_at=DECISION_AT,
        trading_state=state,
        reference_prices=prices if prices is not None else {C1: reference_price(C1), C2: reference_price(C2)},
        multipliers=multipliers if multipliers is not None else {C1: multiplier(C1), C2: multiplier(C2)},
        limits=limits if limits is not None else {C1: limit(C1, c1_limit), C2: limit(C2, "100000")},
    )


def case_1(**kwargs):
    """실제 +3 (체결 X-1), 진행 중 매수 잔량 +7 (C-1 +10 PARTIALLY_FILLED), 목표 +15 → 새 매수 후보 +5."""
    ledger = ledger_with(make_fill("X-1", "C-1", C1, 3))
    orders = [make_order("C-1", C1, 10, S.PARTIALLY_FILLED, filled=3)]
    return assess(ledger, orders, {C1: 15, C2: 0}, **kwargs)


def test_case_1_new_buy_raises_worst_case_and_exceeds_the_test_limit():
    """CASE 1. 입력: 실제 +3, 진행 중 매수 잔량 +7, 새 매수 후보 +5, P_ref 100 pt, 승수 10 USD/pt/계약, 테스트 한도 12,000 USD.
    출력: 최악 경우 롱 10 → 15, 숏 3. 노출 = max(|15|, |3|) × |100| × 10 = 15,000 USD (기존 주문만이면 10,000) → LIMIT_EXCEEDED.
    로컬 검사(LOCAL_VALID)와 위험 결과는 따로 보고한다 (ADR-0003 §6.3)."""
    view = case_1().view(C1)

    worst = view.worst_case
    assert (worst.actual_quantity, worst.open_buy_quantity, worst.open_sell_quantity, worst.candidate_quantity) == (3, 7, 0, 5)
    assert (worst.worst_long_before, worst.worst_short_before, worst.worst_long_after, worst.worst_short_after) == (10, 3, 15, 3)
    assert (view.exposure_before, view.exposure_after, view.max_exposure) == (Decimal("10000"), Decimal("15000"), Decimal("12000"))
    assert (view.risk_status, view.risk_reasons) == (RiskCheckStatus.LIMIT_EXCEEDED, ())
    assert view.local_status is CandidateStatus.LOCAL_VALID
    assert (view.currency, view.state_blocks) == ("USD", ())


def test_case_2_within_limit_is_only_this_check():
    """CASE 2. 입력: CASE 1과 같고 테스트 한도 20,000 USD.
    출력: 이 노출 검사만 WITHIN_LIMIT. 남은 제출 전 단계(다른 L1 지표, L2 결정, 검증된 축소, L3, 브로커 단계)를 함께 돌려주고,
    결과에 제출 승인·전송 준비 상태는 없다."""
    view = case_1(c1_limit="20000").view(C1)

    assert view.risk_status is RiskCheckStatus.WITHIN_LIMIT
    assert view.remaining_steps == REMAINING_PRE_SUBMISSION_STEPS
    assert REMAINING_PRE_SUBMISSION_STEPS
    assert [status.name for status in RiskCheckStatus] == ["WITHIN_LIMIT", "LIMIT_EXCEEDED", "NOT_ASSESSABLE"]
    names = {field.name.upper() for field in dataclasses.fields(PreTradeRiskView)}
    assert not any("READY" in name or "APPROV" in name or "SEND" in name for name in names)


def test_case_3_unknown_order_keeps_its_worst_case_and_blocks_new_orders():
    """CASE 3. 입력: 실제 0, 제출 결과 UNKNOWN인 매수 +10 (C-5), 목표 C1 +10. 입력 Trading State는 NORMAL.
    출력: 최악 경우 롱 +10 유지 (체결 간주, 취소로 보지 않음), 기존 노출 10,000 USD. 모든 월물의 새 후보 BLOCKED,
    위험 판정 NOT_ASSESSABLE. UNKNOWN은 HALTED 조건이므로 상태 차단 사유로도 남긴다 (ADR-0003 §6.3·§6.5, BR-12)."""
    report = assess(ledger_with(), [make_order("C-5", C1, 10, S.UNKNOWN)], {C1: 10, C2: 0})

    view = report.view(C1)
    assert (view.worst_case.worst_long_before, view.worst_case.candidate_quantity) == (10, None)
    assert (view.exposure_before, view.exposure_after) == (Decimal("10000"), None)
    assert view.risk_status is RiskCheckStatus.NOT_ASSESSABLE
    assert "UNKNOWN_ORDER_PRESENT" in view.risk_reasons
    for contract_view in report.views:
        assert contract_view.local_status is CandidateStatus.BLOCKED
        assert "UNKNOWN_ORDER_PRESENT" in contract_view.state_blocks


def test_case_4_cancel_request_keeps_exposure_and_blocks_the_candidate():
    """CASE 4. 입력: 매수 +10 CANCEL_REQUESTED (취소 확인 전), 목표 C1 0.
    출력: 기존 주문을 위험 계산에서 빼지 않는다: 최악 경우 롱 10, 기존 노출 10,000 USD. 0이 아닌 후보(−10)는 Slice 2 A안대로
    BLOCKED(CANCEL_PENDING)이고 위험 판정은 NOT_ASSESSABLE."""
    view = assess(ledger_with(), [make_order("C-6", C1, 10, S.CANCEL_REQUESTED)], {C1: 0, C2: 0}).view(C1)

    assert (view.worst_case.open_buy_quantity, view.worst_case.worst_long_before) == (10, 10)
    assert view.exposure_before == Decimal("10000")
    assert (view.local_status, view.local_reasons) == (CandidateStatus.BLOCKED, ("CANCEL_PENDING",))
    assert (view.risk_status, view.risk_reasons) == (RiskCheckStatus.NOT_ASSESSABLE, ("CANCEL_PENDING",))


@pytest.mark.parametrize(
    ("orders", "exposure", "local"),
    [
        (
            [make_order("C-9", C1, 5, S.REPLACE_REQUESTED, replacement=8), make_order("C-9R", C1, 8, S.PENDING_SUBMIT)],
            "13000",
            ("REPLACE_PENDING",),
        ),
        (
            [make_order("C-9", C1, 5, S.UNKNOWN, replacement=8), make_order("C-9R", C1, 8, S.UNKNOWN)],
            "13000",
            ("UNKNOWN_ORDER_PRESENT",),
        ),
        (
            [make_order("C-9", C1, 5, S.CANCELLED, cancelled=5), make_order("C-9R", C1, 8, S.ACCEPTED)],
            "8000",
            (),
        ),
    ],
)
def test_case_5_replace_rows_keep_the_at_0009_9_worst_case(orders, exposure, local):
    """CASE 5 (ADR-0009 AT-0009-9 1~3행). 입력: 실제 0, 기존 +5를 +8로 정정 (1행 정정 요청 중, 2행 timeout으로 둘 다 UNKNOWN,
    3행 원자적 정정 확정). 목표 C1 +8.
    출력: 최악 경우 롱 13 / 13 / 8 → 기존 노출 13,000 / 13,000 / 8,000 USD. 기존 잔량과 새 수량을 빠뜨리거나 두 번 세지 않는다.
    1·2행 후보는 BLOCKED (REPLACE_PENDING, UNKNOWN_ORDER_PRESENT)."""
    view = assess(ledger_with(), orders, {C1: 8, C2: 0}, c1_limit="20000").view(C1)

    assert view.exposure_before == Decimal(exposure)
    assert view.local_reasons == local


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"prices": {C2: reference_price(C2)}}, "REFERENCE_PRICE_MISSING"),
        ({"multipliers": {C2: multiplier(C2)}}, "MULTIPLIER_MISSING"),
        ({"limits": {C1: limit(C1, "20000", currency="KRW"), C2: limit(C2, "100000")}}, "FX_MISSING"),
        ({"prices": {C1: reference_price(C1, available=DECISION_AT + timedelta(minutes=1)), C2: reference_price(C2)}},
         "REFERENCE_PRICE_NOT_AVAILABLE_AT_DECISION"),
        ({"prices": {C1: reference_price(C1, valuation_at=DECISION_AT + timedelta(hours=1), available=DECISION_AT), C2: reference_price(C2)}},
         "REFERENCE_PRICE_NOT_AVAILABLE_AT_DECISION"),
        ({"multipliers": {C1: multiplier(C1, available=DECISION_AT + timedelta(minutes=1)), C2: multiplier(C2)}},
         "MULTIPLIER_NOT_AVAILABLE_AT_DECISION"),
        ({"multipliers": {C1: multiplier(C1, value="50"), C2: multiplier(C2)}}, "CONTRACT_SPEC_MISMATCH"),
        ({"multipliers": {C1: multiplier(C1, currency="KRW"), C2: multiplier(C2)}}, "CONTRACT_SPEC_MISMATCH"),
        ({"limits": {C2: limit(C2, "100000")}}, "LIMIT_MISSING"),
    ],
)
def test_case_6_missing_or_unusable_inputs_are_not_assessable(changes, reason):
    """CASE 6. 입력: CASE 1에 (a) 가격 누락, (b) 승수 누락, (c) 다른 통화의 한도, (d) 결정 뒤 이용 가능해진 가격,
    (e) 결정 뒤 시각의 가격, (f) 결정 뒤 이용 가능해진 승수, (g) 월물 사양과 다른 승수, (h) 다른 통화의 승수, (i) 한도 누락.
    출력: 모두 NOT_ASSESSABLE과 해당 사유. 0·1·이전 값 같은 기본값으로 정상 판정하지 않는다 (ADR-0003 §6.2.2, §6.4, I-1)."""
    view = case_1(**changes).view(C1)

    assert view.risk_status is RiskCheckStatus.NOT_ASSESSABLE
    assert reason in view.risk_reasons


def test_missing_price_or_multiplier_leaves_exposure_uncomputed():
    """입력: CASE 1에 C1 가격 누락 / C1 승수 누락.
    출력: 두 경우 모두 기존·후보 노출이 None (0이 아님)."""
    for changes in ({"prices": {C2: reference_price(C2)}}, {"multipliers": {C2: multiplier(C2)}}):
        view = case_1(**changes).view(C1)

        assert (view.exposure_before, view.exposure_after) == (None, None)


def test_buy_and_sell_sides_are_both_worst_cases():
    """입력: 실제 +2, 진행 중 매수 +3 (ACCEPTED), 진행 중 매도 −4 (ACCEPTED), 목표 +2 → 새 매수 후보 +1.
    출력: 최악 경우 롱 2 + 3 + 1 = 6, 숏 2 − 4 = −2. 매도 주문으로 매수 노출을 상쇄하지 않는다. 노출 6 × 100 × 10 = 6,000 USD."""
    orders = [make_order("C-B", C1, 3, S.ACCEPTED), make_order("C-S", C1, -4, S.ACCEPTED)]

    view = assess(ledger_with(), orders, {C1: 2, C2: 0}, base=baseline(c1=2)).view(C1)

    worst = view.worst_case
    assert (worst.open_buy_quantity, worst.open_sell_quantity, worst.candidate_quantity) == (3, -4, 1)
    assert (worst.worst_long_after, worst.worst_short_after) == (6, -2)
    assert view.exposure_after == Decimal("6000")


def test_actual_short_position():
    """입력: 실제 −5, 진행 중 매도 −2, 목표 −10 → 새 매도 후보 −3.
    출력: 최악 경우 롱 −5, 숏 −10 → 노출 max(5, 10) × 100 × 10 = 10,000 USD."""
    view = assess(ledger_with(), [make_order("C-S", C1, -2, S.ACCEPTED)], {C1: -10, C2: 0}, base=baseline(c1=-5)).view(C1)

    assert (view.worst_case.worst_long_after, view.worst_case.worst_short_after) == (-5, -10)
    assert view.exposure_after == Decimal("10000")


def test_contracts_are_assessed_separately():
    """입력: C1 (승수 10, P 100), C2 (승수 50, P 20) 각각의 실제·후보와 한도. C2: 실제 +4, 목표 +5 → 후보 +1, 한도 4,000.
    출력: 월물마다 자기 승수·가격·한도로 계산한다. C2 노출 5 × 20 × 50 = 5,000 → LIMIT_EXCEEDED. 월물 노출을 합치거나 상쇄하지 않는다."""
    report = assess(
        ledger_with(),
        [],
        {C1: 1, C2: 5},
        base=baseline(c2=4),
        limits={C1: limit(C1, "20000"), C2: limit(C2, "4000")},
    )

    assert report.view(C1).exposure_after == Decimal("1000")
    assert report.view(C1).risk_status is RiskCheckStatus.WITHIN_LIMIT
    assert report.view(C2).exposure_after == Decimal("5000")
    assert report.view(C2).risk_status is RiskCheckStatus.LIMIT_EXCEEDED


def test_negative_futures_price_uses_its_absolute_value():
    """입력: CASE 1에 C1 참조 가격 −37.63 pt (선물 음수 가격을 거부하지 않음).
    출력: 노출 = 15 × |−37.63| × 10 = 5,644.50 USD."""
    view = case_1(prices={C1: reference_price(C1, value="-37.63"), C2: reference_price(C2)}).view(C1)

    assert view.exposure_after == Decimal("5644.50")
    assert view.risk_status is RiskCheckStatus.WITHIN_LIMIT


def test_zero_candidate_still_reports_the_actual_exposure():
    """입력: 실제 +10, 목표 +10 → 후보 0 (새 주문 없음). 한도 12,000 / 8,000.
    출력: NO_ORDER_NEEDED이지만 노출은 10,000 USD (주문 전후 같음). 한도 12,000이면 WITHIN_LIMIT, 8,000이면 기존 노출이 이미
    LIMIT_EXCEEDED. 후보 0을 노출 0으로 보지 않는다."""
    within = assess(ledger_with(), [], {C1: 10, C2: 0}, base=baseline(c1=10)).view(C1)
    exceeded = assess(ledger_with(), [], {C1: 10, C2: 0}, base=baseline(c1=10), c1_limit="8000").view(C1)

    assert (within.local_status, within.worst_case.candidate_quantity) == (CandidateStatus.NO_ORDER_NEEDED, 0)
    assert (within.exposure_before, within.exposure_after) == (Decimal("10000"), Decimal("10000"))
    assert within.risk_status is RiskCheckStatus.WITHIN_LIMIT
    assert exceeded.risk_status is RiskCheckStatus.LIMIT_EXCEEDED


def test_lot_failure_and_risk_result_are_reported_separately():
    """입력: lot 10 월물, 실제 15 (검증된 기준), 목표 0 → 후보 −15, 한도 20,000.
    출력: 로컬 검사는 LOCAL_INVALID(NOT_LOT_MULTIPLE), 위험 검사는 WITHIN_LIMIT (노출 15,000). 위험 통과가 lot 실패를 덮지 않는다."""
    ledger = ledger_with(specs=(contract(C1, lot_size=10), contract(C2)))

    view = assess(ledger, [], {C1: 0, C2: 0}, base=baseline(c1=15), c1_limit="20000").view(C1)

    assert (view.local_status, view.local_reasons) == (CandidateStatus.LOCAL_INVALID, ("NOT_LOT_MULTIPLE",))
    assert (view.exposure_after, view.risk_status) == (Decimal("15000"), RiskCheckStatus.WITHIN_LIMIT)


@pytest.mark.parametrize(
    ("state", "blocks"),
    [
        (TradingState.HALTED, ("TRADING_STATE_HALTED",)),
        (TradingState.RESTRICTED, ("TRADING_STATE_RESTRICTED",)),
        (TradingState.NORMAL, ()),
    ],
)
def test_trading_state_blocks_automatic_orders(state, blocks):
    """입력: CASE 1 (C1 새 후보 +5, C2 후보 0)을 Trading State HALTED / RESTRICTED / NORMAL에서 평가.
    출력: HALTED는 자동 주문을 모두 막고, RESTRICTED는 위험 증가 주문을 막는다 (검증된 위험 축소 S-1~S-7은 이 Slice가 확인하지
    않으므로 축소 후보도 막힌다). 새 주문이 없는 C2에는 상태 차단이 없다. 상태를 바꾸거나 NORMAL로 되돌리지 않는다 (ADR-0003 §6.5)."""
    report = case_1(state=state)

    assert report.view(C1).state_blocks == blocks
    assert report.view(C2).state_blocks == ()
    assert report.trading_state is state


def test_exposure_equal_to_the_limit_is_not_assessable():
    """입력: CASE 1 (노출 15,000)에 테스트 한도 15,000.
    출력: NOT_ASSESSABLE(LIMIT_BOUNDARY_RULE_OPEN). 한도와 같을 때 ≤ / < 중 무엇을 쓸지는 정해지지 않았다 (AT-0003-3·4)."""
    view = case_1(c1_limit="15000").view(C1)

    assert (view.risk_status, view.risk_reasons) == (RiskCheckStatus.NOT_ASSESSABLE, ("LIMIT_BOUNDARY_RULE_OPEN",))


def test_projected_exposure_formula_and_its_inputs():
    """입력: 최악 경우 롱 15·숏 3, P_ref 100, 승수 10 / 롱 −5·숏 −10, P_ref −37.63 / 잘못된 입력 (float, bool, 0 이하 승수, NaN).
    출력: 15,000과 3,763.0 (= 10 × 37.63 × 10). 잘못된 입력은 ValueError."""
    assert projected_exposure(worst_long=15, worst_short=3, reference_price=Decimal("100"), multiplier=Decimal("10")) == Decimal("15000")
    assert projected_exposure(worst_long=-5, worst_short=-10, reference_price=Decimal("-37.63"), multiplier=Decimal("10")) == Decimal("3763.0")
    bad_inputs = [
        dict(worst_long=15, worst_short=3, reference_price=100.0, multiplier=Decimal("10")),
        dict(worst_long=True, worst_short=3, reference_price=Decimal("100"), multiplier=Decimal("10")),
        dict(worst_long=15, worst_short=3, reference_price=Decimal("100"), multiplier=Decimal("0")),
        dict(worst_long=15, worst_short=3, reference_price=Decimal("NaN"), multiplier=Decimal("10")),
    ]
    for kwargs in bad_inputs:
        with pytest.raises(ValueError):
            projected_exposure(**kwargs)


def test_compare_exposure_to_limit():
    """입력: 노출 14,999 / 15,001 / 15,000, 한도 15,000.
    출력: WITHIN_LIMIT / LIMIT_EXCEEDED / NOT_ASSESSABLE(LIMIT_BOUNDARY_RULE_OPEN)."""
    assert compare_exposure_to_limit(exposure=Decimal("14999"), max_exposure=Decimal("15000")) == (RiskCheckStatus.WITHIN_LIMIT, ())
    assert compare_exposure_to_limit(exposure=Decimal("15001"), max_exposure=Decimal("15000")) == (RiskCheckStatus.LIMIT_EXCEEDED, ())
    assert compare_exposure_to_limit(exposure=Decimal("15000"), max_exposure=Decimal("15000")) == (
        RiskCheckStatus.NOT_ASSESSABLE,
        ("LIMIT_BOUNDARY_RULE_OPEN",),
    )


def test_risk_input_records_reject_invalid_values():
    """입력: 승수 0·음수·float·NaN, 한도 음수·float, 시간대 없는 이용 가능 시각.
    출력: 모두 ValueError. 승수·한도에 기본값이 없다."""
    for value in ("0", "-10", 10.0, "NaN"):
        with pytest.raises(ValueError):
            multiplier(C1, value=value)
    for amount in ("-1", 12000.0):
        with pytest.raises(ValueError):
            limit(C1, amount)
    with pytest.raises(ValueError):
        multiplier(C1, available=datetime(2026, 10, 19, 0, 0))


def test_assessment_inputs_must_match_the_account_and_contracts():
    """입력: (a) 장부에 없는 월물의 가격, (b) 키와 다른 월물의 승수 기록, (c) 문자열 Trading State, (d) 시간대 없는 결정 시각,
    (e) 결정 시각 뒤의 체결이 든 장부.
    출력: 모두 ValueError (미래 체결·잘못된 참조로 계산하지 않음)."""
    ledger = ledger_with()
    cases = [
        dict(prices={C1: reference_price(C1), C2: reference_price(C2), "FUT.ALPHA.C9": reference_price(C1)}),
        dict(multipliers={C1: multiplier(C2), C2: multiplier(C2)}),
        dict(state="NORMAL"),
    ]
    for kwargs in cases:
        with pytest.raises(ValueError):
            assess(ledger, [], {C1: 0, C2: 0}, **kwargs)
    with pytest.raises(ValueError):
        assess_pretrade_risk(
            baseline=baseline(),
            ledger=ledger,
            orders=[],
            targets={C1: 0, C2: 0},
            decision_at=datetime(2026, 10, 20, 0, 0),
            trading_state=TradingState.NORMAL,
            reference_prices={},
            multipliers={},
            limits={},
        )
    with pytest.raises(ValueError):
        assess(ledger, [], {C1: 0, C2: 0}, base=dataclasses.replace(baseline(), account_id="A2"))
    late = dataclasses.replace(make_fill("X-9", "C-9", C1, 1), fill_at=DECISION_AT + timedelta(minutes=1))
    with pytest.raises(ValueError):
        assess(ledger_with(late), [make_order("C-9", C1, 1, S.FILLED, filled=1)], {C1: 0, C2: 0})


def test_worst_case_positions_reuse_the_slice_2_projection():
    """입력: CASE 1의 Slice 2 결과 (prepare_order_candidates).
    출력: worst_case_positions의 기존 주문 최악 경우는 project_positions의 값과 같고, 후보 포함 값은 Slice 2 결과와 같다
    (계산식을 다시 구현하지 않음)."""
    ledger = ledger_with(make_fill("X-1", "C-1", C1, 3))
    orders = [make_order("C-1", C1, 10, S.PARTIALLY_FILLED, filled=3)]
    report = prepare_order_candidates(baseline=baseline(), ledger=ledger, orders=orders, targets={C1: 15, C2: 0}, as_of=DECISION_AT)
    projection = project_positions(baseline=baseline(), ledger=ledger, orders=orders, as_of=DECISION_AT)

    positions = {position.contract_id: position for position in worst_case_positions(report)}

    for unit in projection.units:
        assert (positions[unit.contract_id].worst_long_before, positions[unit.contract_id].worst_short_before) == (
            unit.worst_long_quantity,
            unit.worst_short_quantity,
        )
    c1_result = next(result for result in report.results if result.contract_id == C1)
    assert (positions[C1].worst_long_after, positions[C1].worst_short_after) == (c1_result.worst_long_after, c1_result.worst_short_after)


@pytest.mark.parametrize("state", [TradingState.HALTED, TradingState.RESTRICTED])
def test_state_blocks_also_cover_a_candidate_that_was_not_computed(state):
    """입력: CASE 4 (취소 요청 중이라 후보를 만들지 않음 = None)를 HALTED / RESTRICTED에서 평가.
    출력: 상태 차단 사유가 남는다. 후보가 None인 월물도 자동 주문이 나갈 수 있는 월물로 본다 (후보 0만 제외)."""
    view = assess(ledger_with(), [make_order("C-6", C1, 10, S.CANCEL_REQUESTED)], {C1: 0, C2: 0}, state=state).view(C1)

    assert view.worst_case.candidate_quantity is None
    assert view.state_blocks == ("TRADING_STATE_" + state.name,)


def test_restricted_state_also_blocks_an_unverified_reduction():
    """입력: RESTRICTED, 실제 +10, 목표 +5 → 위험 축소 후보 −5.
    출력: TRADING_STATE_RESTRICTED. 검증된 위험 축소(S-1~S-7, §6.2.2)를 이 Slice가 확인하지 않으므로 축소 후보도 자동으로 내지 않는다."""
    view = assess(ledger_with(), [], {C1: 5, C2: 0}, base=baseline(c1=10), state=TradingState.RESTRICTED).view(C1)

    assert view.worst_case.candidate_quantity == -5
    assert view.state_blocks == ("TRADING_STATE_RESTRICTED",)


def test_data_available_exactly_at_decision_time_is_usable():
    """입력: 참조 가격의 가격 시각·이용 가능 시각과 승수의 이용 가능 시각이 모두 decision_at.
    출력: 판정 가능 (노출 15,000 → LIMIT_EXCEEDED). data_available_at ≤ decision_at이면 쓸 수 있다 (ADR-0001 I-1)."""
    view = case_1(
        prices={C1: reference_price(C1, valuation_at=DECISION_AT, available=DECISION_AT), C2: reference_price(C2)},
        multipliers={C1: multiplier(C1, available=DECISION_AT), C2: multiplier(C2)},
    ).view(C1)

    assert (view.exposure_after, view.risk_status) == (Decimal("15000"), RiskCheckStatus.LIMIT_EXCEEDED)
