"""P0-03B Slice 1: period_trading_pnl (ADR-0001 §5.1.3, §6.2 식 (1), 단일 통화).

기대값 38·26·35 USD는 저장소 밖 독립 산술(Fraction)로 먼저 확인한 값이다.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from carver_quant.lab.accounting.fill_ledger import FillIntegrityError, FillLedger, FillVerdict, apply_fill
from carver_quant.lab.accounting.positions import actual_position
from carver_quant.lab.accounting.trading_pnl import period_trading_pnl
from carver_quant.lab.domain.records import (
    FillKey,
    FillOrigin,
    FillRecord,
    FuturesContractSpec,
    PositionBaseline,
    ValuationPrice,
)

UTC = timezone.utc
C1 = "FUT.ALPHA.C1"
C2 = "FUT.ALPHA.C2"
# 평가 시각: valuation_at(t−1), valuation_at(t), valuation_at(t+1)
V0 = datetime(2026, 10, 19, 21, 0, tzinfo=UTC)
V1 = datetime(2026, 10, 20, 21, 0, tzinfo=UTC)
V2 = datetime(2026, 10, 21, 21, 0, tzinfo=UTC)


def contract(contract_id, multiplier="10"):
    return FuturesContractSpec(contract_id=contract_id, instrument_id="FUT.ALPHA", currency="USD", multiplier=multiplier, lot_size=1)


def make_fill(fill_id, contract_id, quantity, price, fill_at, fee):
    return FillRecord(
        key=FillKey(account_id="A1", fill_source="BRK", fill_id=fill_id),
        client_order_id="C-" + fill_id,
        broker_order_id="B-" + fill_id,
        contract_id=contract_id,
        quantity=quantity,
        price=price,
        fill_at=fill_at,
        fee=fee,
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


def vprice(contract_id, value, valuation_at, available=None):
    """사용자가 지정한 raw 평가가격. 기본 시나리오에서는 평가 시각 30분 전에 이용 가능해진 값."""
    return ValuationPrice(
        contract_id=contract_id,
        price=value,
        valuation_at=valuation_at,
        data_available_at=available or valuation_at - timedelta(minutes=30),
        source_ref="fixture:" + contract_id,
    )


def pnl(ledger, start_positions, start_prices, end_prices, period_start=V0, period_end=V1, cutoff=None, currency="USD"):
    return period_trading_pnl(
        ledger=ledger,
        currency=currency,
        period_start=period_start,
        period_end=period_end,
        start_positions=start_positions,
        start_prices=start_prices,
        end_prices=end_prices,
        information_cutoff=cutoff or period_end,
    )


def test_normal_fill_and_valuation_net_38_usd():
    """입력: 주기 (V0, V1]. 시작 포지션 0. 체결 X-1 +2계약 @ 101 pt (14:00Z), 수수료 2 USD.
    평가가격 V[C1,t] = 103 pt, 계약승수 10 USD/pt/계약.
    출력: Gross 2 × (103 − 101) × 10 = 40 USD, Fee 2 USD, Net 38 USD.
    전제: 체결가와 평가가격은 같은 월물의 raw 가격. 수수료 통화 = 상품 통화 (ADR-0001 잠정 가정)."""
    ledger = ledger_with(make_fill("X-1", C1, 2, "101", datetime(2026, 10, 20, 14, 0, tzinfo=UTC), "2"))

    result = pnl(ledger, {C1: 0, C2: 0}, {}, {C1: vprice(C1, "103", V1)})

    assert result.currency == "USD"
    assert result.gross_pnl == Decimal("40")
    assert result.fees == Decimal("2")
    assert result.net_pnl == Decimal("38")


def test_duplicate_fill_does_not_change_pnl_or_fees():
    """입력: 위와 같은 X-1을 두 번 수신 (두 번째는 DUPLICATE).
    출력: Gross 40, Fee 2 (4가 아님), Net 38 USD. 수수료는 정확히 한 번 차감된다 (F8-1, F8-2)."""
    x1 = make_fill("X-1", C1, 2, "101", datetime(2026, 10, 20, 14, 0, tzinfo=UTC), "2")
    ledger = ledger_with(x1)
    resend = apply_fill(ledger, x1)
    assert resend.verdict is FillVerdict.DUPLICATE

    result = pnl(resend.ledger, {C1: 0, C2: 0}, {}, {C1: vprice(C1, "103", V1)})

    assert (result.gross_pnl, result.fees, result.net_pnl) == (Decimal("40"), Decimal("2"), Decimal("38"))


def test_fee_is_deducted_once_and_spread_is_not_deducted_again():
    """입력: X-1 +2 @ 101, 수수료 2 USD, 평가 103.
    출력: Net = Gross − Fee = 40 − 2 = 38 USD. 체결가 기준 손익에 스프레드·슬리피지를 다시 빼지 않고(ADR-0001 이중 차감 금지),
    수수료를 두 번 빼서 36 USD가 되지 않는다."""
    ledger = ledger_with(make_fill("X-1", C1, 2, "101", datetime(2026, 10, 20, 14, 0, tzinfo=UTC), "2"))

    result = pnl(ledger, {C1: 0, C2: 0}, {}, {C1: vprice(C1, "103", V1)})

    assert result.net_pnl == result.gross_pnl - result.fees
    assert result.net_pnl != Decimal("36")
    [c1] = [row for row in result.contributions if row.contract_id == C1]
    assert (c1.holding_pnl, c1.fill_pnl, c1.fees) == (Decimal("0"), Decimal("40"), Decimal("2"))


def test_roll_c1_minus_2_c2_plus_2_net_26_usd():
    """입력: 주기 (V0, V1]. 시작 C1 +2, C2 0. V[C1,t−1] = 99.0, V[C1,t] = 100.5, V[C2,t] = 102.0 pt.
    체결 X-71 C1 −2 @ 100.0, X-72 C2 +2 @ 101.5, 수수료 각 2 USD. 계약승수 10.
    출력: 보유분 C1 +30, 체결분 C1 −10, C2 +10 → Gross 30, Fee 4, Net 26 USD.
    두 다리는 월물별로 계산하며 롤 비용을 상쇄하지 않는다 (ADR-0001 §6.3, I6-9)."""
    ledger = ledger_with(
        make_fill("X-71", C1, -2, "100.0", datetime(2026, 10, 20, 14, 0, tzinfo=UTC), "2"),
        make_fill("X-72", C2, 2, "101.5", datetime(2026, 10, 20, 14, 1, tzinfo=UTC), "2"),
    )

    result = pnl(
        ledger,
        {C1: 2, C2: 0},
        {C1: vprice(C1, "99.0", V0)},
        {C1: vprice(C1, "100.5", V1), C2: vprice(C2, "102.0", V1)},
    )

    assert (result.gross_pnl, result.fees, result.net_pnl) == (Decimal("30"), Decimal("4"), Decimal("26"))
    rows = {row.contract_id: row for row in result.contributions}
    assert (rows[C1].holding_pnl, rows[C1].fill_pnl, rows[C1].fees) == (Decimal("30"), Decimal("-10"), Decimal("2"))
    assert (rows[C2].holding_pnl, rows[C2].fill_pnl, rows[C2].fees) == (Decimal("0"), Decimal("10"), Decimal("2"))


def test_fill_after_valuation_time_belongs_to_next_period_35_usd():
    """입력 (ADR-0009 AT-0009-7): 체결 X-7 +5 @ 104.1, 수수료 10 USD, fill_at = V1 + 30분.
    V[t] = 104, V[t+1] = 105 pt, 계약승수 10.
    출력: 주기 t (V0, V1]는 Gross 0, Fee 0, Net 0. 주기 t+1 (V1, V2]는 Gross 5 × (105 − 104.1) × 10 = 45,
    Fee 10, Net 35 USD. 단위: USD."""
    ledger = ledger_with(make_fill("X-7", C1, 5, "104.1", datetime(2026, 10, 20, 21, 30, tzinfo=UTC), "10"))

    period_t = pnl(ledger, {C1: 0, C2: 0}, {}, {C1: vprice(C1, "104", V1)})
    period_t1 = pnl(ledger, {C1: 0, C2: 0}, {}, {C1: vprice(C1, "105", V2)}, period_start=V1, period_end=V2)

    assert (period_t.gross_pnl, period_t.fees, period_t.net_pnl) == (Decimal("0"), Decimal("0"), Decimal("0"))
    assert (period_t1.gross_pnl, period_t1.fees, period_t1.net_pnl) == (Decimal("45"), Decimal("10"), Decimal("35"))


def test_period_boundary_is_left_open_right_closed():
    """입력: 체결 +1 @ 100, 수수료 1 USD, fill_at = V1 (주기 t의 오른쪽 끝).
    출력: 주기 (V0, V1]에 포함: 1 × (101 − 100) × 10 − 1 = 9 USD. 다음 주기 (V1, V2]에는 다시 넣지 않음:
    시작 포지션 1, 101 → 102이면 보유분 10 USD만 (I-3)."""
    ledger = ledger_with(make_fill("X-B", C1, 1, "100", V1, "1"))

    period_t = pnl(ledger, {C1: 0, C2: 0}, {}, {C1: vprice(C1, "101", V1)})
    period_t1 = pnl(ledger, {C1: 1, C2: 0}, {C1: vprice(C1, "101", V1)}, {C1: vprice(C1, "102", V2)}, period_start=V1, period_end=V2)

    assert period_t.net_pnl == Decimal("9")
    assert (period_t1.gross_pnl, period_t1.fees, period_t1.net_pnl) == (Decimal("10"), Decimal("0"), Decimal("10"))


def test_each_contract_uses_its_own_multiplier():
    """입력: 시작 C1 +1 (M 10), C2 +1 (M 50). C1 100 → 101, C2 200 → 202 pt. 체결 없음.
    출력: 1 × 1 × 10 + 1 × 2 × 50 = 110 USD. 공통 승수 10 (30)이나 50 (150)을 쓰지 않는다 (I6-6)."""
    ledger = ledger_with(specs=(contract(C1, "10"), contract(C2, "50")))

    result = pnl(
        ledger,
        {C1: 1, C2: 1},
        {C1: vprice(C1, "100", V0), C2: vprice(C2, "200", V0)},
        {C1: vprice(C1, "101", V1), C2: vprice(C2, "202", V1)},
    )

    assert result.net_pnl == Decimal("110")


def test_price_arriving_after_information_cutoff_is_rejected():
    """입력: valuation_at 16:30Z, 평가가격 도착 16:45Z, information_cutoff 16:30Z (계산은 17:00Z에 해도 같음).
    출력: ValueError. 16:30 기준 재현에서 16:45에 도착한 가격을 쓰지 않는다 (V-1, ADR-0001 I-1)."""
    valuation_at = datetime(2026, 10, 20, 16, 30, tzinfo=UTC)
    late = vprice(C1, "103", valuation_at, available=datetime(2026, 10, 20, 16, 45, tzinfo=UTC))
    ledger = ledger_with(make_fill("X-1", C1, 2, "101", datetime(2026, 10, 20, 14, 0, tzinfo=UTC), "2"))

    with pytest.raises(ValueError):
        pnl(ledger, {C1: 0, C2: 0}, {}, {C1: late}, period_end=valuation_at, cutoff=valuation_at)


def test_information_cutoff_after_valuation_time_is_rejected():
    """입력: information_cutoff가 valuation_at(t)보다 늦음 (사후 재평가).
    출력: ValueError. Slice 1은 사후 재평가 정책을 구현하지 않는다 (Q1-2, Q7-3, Q7-4 미결정)."""
    ledger = ledger_with()
    with pytest.raises(ValueError):
        pnl(ledger, {C1: 0, C2: 0}, {}, {}, cutoff=datetime(2026, 10, 20, 21, 1, tzinfo=UTC))


def test_fill_after_information_cutoff_inside_period_is_rejected():
    """입력: information_cutoff 20:00Z < valuation_at 21:00Z, 주기 안의 체결 fill_at 20:30Z.
    출력: ValueError. cutoff까지 알 수 없었던 체결을 쓰지 않는다 (V-1)."""
    ledger = ledger_with(make_fill("X-1", C1, 2, "101", datetime(2026, 10, 20, 20, 30, tzinfo=UTC), "2"))
    cutoff = datetime(2026, 10, 20, 20, 0, tzinfo=UTC)
    early_price = vprice(C1, "103", V1, available=datetime(2026, 10, 20, 19, 0, tzinfo=UTC))
    with pytest.raises(ValueError):
        pnl(ledger, {C1: 0, C2: 0}, {}, {C1: early_price}, cutoff=cutoff)


def test_price_for_other_valuation_time_is_rejected():
    """입력: 주기 끝 V1의 평가가격 자리에 V0 시각의 가격.
    출력: ValueError (평가 시각이 맞지 않는 가격을 쓰지 않음)."""
    ledger = ledger_with(make_fill("X-1", C1, 2, "101", datetime(2026, 10, 20, 14, 0, tzinfo=UTC), "2"))
    with pytest.raises(ValueError):
        pnl(ledger, {C1: 0, C2: 0}, {}, {C1: vprice(C1, "103", V0)})


def test_missing_price_or_start_position_is_not_replaced_by_default():
    """입력: (a) 시작 포지션 C1 +2인데 시작 평가가격 없음. (b) 체결이 있는데 주기 끝 평가가격 없음.
    (c) 장부 월물 C2의 시작 포지션 항목 없음.
    출력: 모두 ValueError. 0, 이전 값, 기본 가격으로 대체하지 않는다 (ADR-0001 §6.2 예외조건)."""
    fill = make_fill("X-1", C1, 2, "101", datetime(2026, 10, 20, 14, 0, tzinfo=UTC), "2")
    with pytest.raises(ValueError):
        pnl(ledger_with(), {C1: 2, C2: 0}, {}, {C1: vprice(C1, "103", V1)})
    with pytest.raises(ValueError):
        pnl(ledger_with(fill), {C1: 0, C2: 0}, {}, {})
    with pytest.raises(ValueError):
        pnl(ledger_with(fill), {C1: 0}, {}, {C1: vprice(C1, "103", V1)})


def test_contract_id_mismatch_in_price_inputs_is_rejected():
    """입력: (a) 키 C1 자리에 C2의 가격 객체. (b) 장부에 없는 월물 C3의 가격. (c) 가격 대신 Decimal 숫자.
    출력: 모두 ValueError. 체결가·평가가격·월물을 혼동하지 않는다."""
    ledger = ledger_with(make_fill("X-1", C1, 2, "101", datetime(2026, 10, 20, 14, 0, tzinfo=UTC), "2"))
    with pytest.raises(ValueError):
        pnl(ledger, {C1: 0, C2: 0}, {}, {C1: vprice(C2, "103", V1)})
    with pytest.raises(ValueError):
        pnl(ledger, {C1: 0, C2: 0}, {}, {C1: vprice(C1, "103", V1), "FUT.ALPHA.C3": vprice("FUT.ALPHA.C3", "1", V1)})
    with pytest.raises(ValueError):
        pnl(ledger, {C1: 0, C2: 0}, {}, {C1: Decimal("103")})


def test_currency_must_match_contracts():
    """입력: USD 월물 장부에 currency="KRW".
    출력: ValueError. 서로 다른 통화를 환산 없이 섞지 않는다 (X8-8). Slice 1은 단일 통화만."""
    ledger = ledger_with(make_fill("X-1", C1, 2, "101", datetime(2026, 10, 20, 14, 0, tzinfo=UTC), "2"))
    with pytest.raises(ValueError):
        pnl(ledger, {C1: 0, C2: 0}, {}, {C1: vprice(C1, "103", V1)}, currency="KRW")


def test_period_must_be_ordered_and_start_positions_integer():
    """입력: (a) 주기 시작 = 주기 끝. (b) 시작 포지션에 bool.
    출력: 둘 다 ValueError."""
    with pytest.raises(ValueError):
        pnl(ledger_with(), {C1: 0, C2: 0}, {}, {}, period_start=V1, period_end=V1)
    with pytest.raises(ValueError):
        pnl(ledger_with(), {C1: True, C2: 0}, {}, {})


def test_conflicting_ledger_cannot_produce_pnl():
    """입력: 같은 키에 체결가가 다른 재수신으로 CONFLICT가 기록된 장부.
    출력: FillIntegrityError. Backtest도 충돌을 무시하고 손익을 계산하지 않는다."""
    ledger = ledger_with(make_fill("X-1", C1, 2, "101", datetime(2026, 10, 20, 14, 0, tzinfo=UTC), "2"))
    conflict = apply_fill(ledger, make_fill("X-1", C1, 2, "101.5", datetime(2026, 10, 20, 14, 0, tzinfo=UTC), "2"))
    assert conflict.verdict is FillVerdict.CONFLICT

    with pytest.raises(FillIntegrityError):
        pnl(conflict.ledger, {C1: 0, C2: 0}, {}, {C1: vprice(C1, "103", V1)})


def test_result_is_exact_decimal_without_rounding():
    """입력: 체결 +3 @ 100.0001, 평가 100.0002, 승수 10, 수수료 0.0003 USD.
    출력: Gross 3 × 0.0001 × 10 = 0.0030, Net 0.0027 USD 정확히. float 오차나 반올림이 없다."""
    ledger = ledger_with(make_fill("X-1", C1, 3, "100.0001", datetime(2026, 10, 20, 14, 0, tzinfo=UTC), "0.0003"))

    result = pnl(ledger, {C1: 0, C2: 0}, {}, {C1: vprice(C1, "100.0002", V1)})

    assert isinstance(result.net_pnl, Decimal)
    assert result.gross_pnl == Decimal("0.003")
    assert result.net_pnl == Decimal("0.0027")


def test_start_price_published_after_period_start_is_rejected():
    """입력: 시작 포지션 C1 +1. 주기 시작 V0의 평가가격이 V0 + 2시간에야 이용 가능해짐 (cutoff는 V1).
    출력: ValueError. 평가 시각 V0의 가격은 V0까지 알 수 있었던 값이어야 한다 (V-1, 사후 재평가 금지).
    이 가격은 주기 t−1의 끝 가격으로도 쓸 수 없으므로, 인접 주기가 서로 다른 V[c,t−1]을 쓰는 일을 막는다."""
    late_start = vprice(C1, "100", V0, available=V0 + timedelta(hours=2))
    with pytest.raises(ValueError):
        pnl(ledger_with(), {C1: 1, C2: 0}, {C1: late_start}, {C1: vprice(C1, "101", V1)})


def test_exact_result_beyond_default_decimal_precision():
    """입력: 시작 C1 +3, V0 1.00, V1 123456789012345678901234568.89 pt, 승수 10. 체결 없음.
    출력: 3 × 123456789012345678901234567.89 × 10 = 3703703670370370367037037036.7 USD 정확히.
    Python 기본 28자리 정밀도라면 3703703670370370367037037037로 반올림된다 (독립 산술로 확인)."""
    result = pnl(
        ledger_with(),
        {C1: 3, C2: 0},
        {C1: vprice(C1, "1.00", V0)},
        {C1: vprice(C1, "123456789012345678901234568.89", V1)},
    )

    assert result.net_pnl == Decimal("3703703670370370367037037036.7")


def test_fills_on_two_contracts_use_their_own_multipliers():
    """입력: C1 (M 10) 체결 +1 @ 100, V[C1,t] 101. C2 (M 50) 체결 −1 @ 200, V[C2,t] 198. 수수료 각 1 USD.
    출력: 1 × (101 − 100) × 10 + (−1) × (198 − 200) × 50 − 2 = 108 USD (체결분 항도 월물별 승수, I6-6)."""
    ledger = ledger_with(
        make_fill("X-1", C1, 1, "100", datetime(2026, 10, 20, 14, 0, tzinfo=UTC), "1"),
        make_fill("X-2", C2, -1, "200", datetime(2026, 10, 20, 14, 1, tzinfo=UTC), "1"),
        specs=(contract(C1, "10"), contract(C2, "50")),
    )

    result = pnl(ledger, {C1: 0, C2: 0}, {}, {C1: vprice(C1, "101", V1), C2: vprice(C2, "198", V1)})

    assert (result.gross_pnl, result.fees, result.net_pnl) == (Decimal("110"), Decimal("2"), Decimal("108"))


def test_start_positions_derived_from_actual_position_compose():
    """입력: 기준 시각 T0 = 10-19 00:00Z에 C1 2, C2 0 (검증됨). 롤 체결 X-71, X-72는 주기 (V0, V1] 안.
    출력: 시작 포지션 = actual_position(기준, 장부, V0) = {C1: 2, C2: 0}, Net 26 USD.
    끝 포지션 = actual_position(기준, 장부, V1) = {C1: 0, C2: 2}. 주기 안 체결을 시작 포지션에 넣지 않는다."""
    ledger = ledger_with(
        make_fill("X-71", C1, -2, "100.0", datetime(2026, 10, 20, 14, 0, tzinfo=UTC), "2"),
        make_fill("X-72", C2, 2, "101.5", datetime(2026, 10, 20, 14, 1, tzinfo=UTC), "2"),
    )
    baseline = PositionBaseline(
        account_id="A1",
        as_of=datetime(2026, 10, 19, 0, 0, tzinfo=UTC),
        quantities={C1: 2, C2: 0},
        verification_ref="fixture:verified",
    )

    start_positions = actual_position(baseline, ledger, V0)
    result = pnl(
        ledger,
        start_positions,
        {C1: vprice(C1, "99.0", V0)},
        {C1: vprice(C1, "100.5", V1), C2: vprice(C2, "102.0", V1)},
    )

    assert start_positions == {C1: 2, C2: 0}
    assert result.net_pnl == Decimal("26")
    assert actual_position(baseline, ledger, V1) == {C1: 0, C2: 2}
