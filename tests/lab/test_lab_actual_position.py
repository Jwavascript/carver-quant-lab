"""P0-03B Slice 1: actual_position (ADR-0009 R9-2, R9-13, ADR-0013 AT-0013-11)."""

from datetime import datetime, timezone

import pytest

from carver_quant.lab.accounting.fill_ledger import FillIntegrityError, FillLedger, FillVerdict, apply_fill
from carver_quant.lab.accounting.positions import actual_position
from carver_quant.lab.domain.records import FillKey, FillOrigin, FillRecord, FuturesContractSpec, PositionBaseline

UTC = timezone.utc
C1 = "FUT.ALPHA.C1"
C2 = "FUT.ALPHA.C2"
T0 = datetime(2026, 10, 19, 0, 0, tzinfo=UTC)


def contract(contract_id):
    return FuturesContractSpec(contract_id=contract_id, instrument_id="FUT.ALPHA", currency="USD", multiplier="10", lot_size=1)


def make_fill(fill_id, contract_id, quantity, fill_at, price="100"):
    return FillRecord(
        key=FillKey(account_id="A1", fill_source="BRK", fill_id=fill_id),
        client_order_id="C-" + fill_id,
        broker_order_id="B-" + fill_id,
        contract_id=contract_id,
        quantity=quantity,
        price=price,
        fill_at=fill_at,
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


def baseline(c1=15, c2=0):
    return PositionBaseline(account_id="A1", as_of=T0, quantities={C1: c1, C2: c2}, verification_ref="fixture:verified")


def test_baseline_plus_fills_after_t0_counted_once():
    """입력: T0 검증 기준 C1 15계약 (T0 이전 체결 X-0 +5가 이미 포함됨), T0 뒤 체결 X-1 +10,
    X-1 재수신(DUPLICATE). 계산 시각 2026-10-20 00:00Z.
    출력: C1 실제 25계약 (X-0을 다시 더한 30, X-1을 두 번 더한 35가 아님), C2 0. 단위: 계약."""
    x0 = make_fill("X-0", C1, 5, datetime(2026, 10, 18, 15, 0, tzinfo=UTC))
    x1 = make_fill("X-1", C1, 10, datetime(2026, 10, 19, 14, 0, tzinfo=UTC))
    ledger = ledger_with(x0, x1)
    resend = apply_fill(ledger, x1)
    assert resend.verdict is FillVerdict.DUPLICATE

    positions = actual_position(baseline(), resend.ledger, datetime(2026, 10, 20, 0, 0, tzinfo=UTC))

    assert positions == {C1: 25, C2: 0}


def test_fills_after_as_of_are_excluded_and_contracts_are_not_mixed():
    """입력: 기준 C1 15, C2 0. T0 뒤 체결 C1 −2 (10-19 14:00Z), C2 +2 (10-19 14:01Z), C1 +1 (10-21).
    계산 시각 10-20 00:00Z.
    출력: C1 13, C2 2. 계산 시각 뒤 체결은 넣지 않고, 월물별 수량을 합치지 않는다 (R9-13, I6-3)."""
    ledger = ledger_with(
        make_fill("X-71", C1, -2, datetime(2026, 10, 19, 14, 0, tzinfo=UTC)),
        make_fill("X-72", C2, 2, datetime(2026, 10, 19, 14, 1, tzinfo=UTC)),
        make_fill("X-8", C1, 1, datetime(2026, 10, 21, 14, 0, tzinfo=UTC)),
    )

    positions = actual_position(baseline(), ledger, datetime(2026, 10, 20, 0, 0, tzinfo=UTC))

    assert positions == {C1: 13, C2: 2}


def test_fill_at_exactly_t0_is_rejected():
    """입력: fill_at = T0인 체결.
    출력: ValueError. 기준 시각과 같은 시각 체결의 귀속은 Q13-2 미결정이므로 Slice 1은 거부한다."""
    ledger = ledger_with(make_fill("X-T0", C1, 1, T0))
    with pytest.raises(ValueError):
        actual_position(baseline(), ledger, datetime(2026, 10, 20, 0, 0, tzinfo=UTC))


def test_as_of_before_baseline_is_rejected():
    """입력: 계산 시각이 기준 시각 T0보다 이름.
    출력: ValueError (기준 이전 포지션은 이 입력으로 알 수 없음)."""
    with pytest.raises(ValueError):
        actual_position(baseline(), ledger_with(), datetime(2026, 10, 18, 0, 0, tzinfo=UTC))


def test_baseline_must_list_every_ledger_contract_and_no_unknown_contract():
    """입력: (a) C2가 빠진 기준 포지션, (b) 장부에 없는 월물 C3이 들어간 기준 포지션.
    출력: 둘 다 ValueError. 빠진 월물을 0으로 채우지 않고, 모르는 월물을 받지 않는다."""
    as_of = datetime(2026, 10, 20, 0, 0, tzinfo=UTC)
    missing = PositionBaseline(account_id="A1", as_of=T0, quantities={C1: 15}, verification_ref="v")
    unknown = PositionBaseline(account_id="A1", as_of=T0, quantities={C1: 15, C2: 0, "FUT.ALPHA.C3": 1}, verification_ref="v")
    with pytest.raises(ValueError):
        actual_position(missing, ledger_with(), as_of)
    with pytest.raises(ValueError):
        actual_position(unknown, ledger_with(), as_of)


def test_baseline_for_other_account_is_rejected():
    """입력: 계좌 A2의 기준 포지션과 계좌 A1의 장부.
    출력: ValueError."""
    other = PositionBaseline(account_id="A2", as_of=T0, quantities={C1: 15, C2: 0}, verification_ref="v")
    with pytest.raises(ValueError):
        actual_position(other, ledger_with(), datetime(2026, 10, 20, 0, 0, tzinfo=UTC))


def test_ledger_with_conflict_cannot_be_used_for_positions():
    """입력: 같은 키에 수량이 다른 재수신으로 CONFLICT가 기록된 장부.
    출력: FillIntegrityError (ValueError 하위). 충돌을 무시하고 계속 계산하지 않는다.
    전제: HALTED 전이는 구현하지 않는다. 계산 코어는 거부만 한다."""
    x1 = make_fill("X-1", C1, 10, datetime(2026, 10, 19, 14, 0, tzinfo=UTC))
    ledger = ledger_with(x1)
    conflict = apply_fill(ledger, make_fill("X-1", C1, 11, datetime(2026, 10, 19, 14, 0, tzinfo=UTC)))
    assert conflict.verdict is FillVerdict.CONFLICT

    with pytest.raises(FillIntegrityError):
        actual_position(baseline(), conflict.ledger, datetime(2026, 10, 20, 0, 0, tzinfo=UTC))
    assert issubclass(FillIntegrityError, ValueError)
