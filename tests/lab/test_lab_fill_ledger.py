"""P0-03B Slice 1: apply_fill의 체결 반영 판정 (ADR-0009 R9-9, §6.4a)."""

from dataclasses import fields, replace
from datetime import datetime, timezone

import pytest

from carver_quant.lab.accounting.fill_ledger import FillLedger, FillVerdict, apply_fill
from carver_quant.lab.domain.records import (
    FILL_COMPARISON_FIELDS,
    FillKey,
    FillOrigin,
    FillRecord,
    FuturesContractSpec,
)

UTC = timezone.utc
C1 = "FUT.ALPHA.C1"
C2 = "FUT.ALPHA.C2"
FILL_AT = datetime(2026, 10, 20, 14, 0, tzinfo=UTC)


def contract(contract_id, multiplier="10", lot_size=1):
    return FuturesContractSpec(
        contract_id=contract_id, instrument_id="FUT.ALPHA", currency="USD", multiplier=multiplier, lot_size=lot_size
    )


def empty_ledger(*specs):
    return FillLedger.empty(account_id="A1", contracts=specs or (contract(C1), contract(C2)))


def make_fill(fill_id="X-1", **overrides):
    fields = dict(
        key=FillKey(account_id="A1", fill_source="BRK", fill_id=fill_id),
        client_order_id="C-1",
        broker_order_id="B-1",
        contract_id=C1,
        quantity=2,
        price="101",
        fill_at=FILL_AT,
        fee="2",
        fee_currency="USD",
        origin=FillOrigin.BROKER_REPORTED,
        execution_assumption_ref=None,
        venue=None,
        liquidity_flag=None,
    )
    fields.update(overrides)
    return FillRecord(**fields)


def test_first_valid_fill_is_applied():
    """입력: 빈 장부, 체결 X-1 (+2계약 @ 101 pt, 수수료 2 USD).
    출력: APPLIED, 장부에 체결 1건. 입력 장부는 바뀌지 않는다 (불변)."""
    ledger = empty_ledger()
    result = apply_fill(ledger, make_fill())

    assert result.verdict is FillVerdict.APPLIED
    assert result.existing is None
    assert result.differing_fields == ()
    assert len(result.ledger.applied) == 1
    assert ledger.applied == ()


def test_identical_resend_is_duplicate_and_does_not_reapply():
    """입력: 같은 키 (A1, BRK, X-1), 모든 비교 필드가 같은 체결을 두 번.
    출력: 두 번째는 DUPLICATE. 반영 체결은 1건 그대로, 중복 수신만 기록된다 (R9-9)."""
    first = apply_fill(empty_ledger(), make_fill())
    second = apply_fill(first.ledger, make_fill())

    assert second.verdict is FillVerdict.DUPLICATE
    assert second.ledger.applied == first.ledger.applied
    assert len(second.ledger.duplicates) == 1
    assert second.ledger.conflicts == ()


def test_equal_decimal_values_with_different_text_are_duplicate():
    """입력: 체결가 "101.0"으로 반영된 체결과, 체결가 "101", 수수료 "2.00"인 같은 키의 재수신.
    출력: DUPLICATE. Slice 1 비교 규칙: Decimal 수치가 같으면 같다 (반올림·허용 오차 없음).
    저장된 기록은 처음 받은 원본 표현 "101.0"을 유지한다."""
    first = apply_fill(empty_ledger(), make_fill(price="101.0"))
    second = apply_fill(first.ledger, make_fill(price="101", fee="2.00"))

    assert second.verdict is FillVerdict.DUPLICATE
    assert str(second.ledger.applied[0].price) == "101.0"
    assert str(second.incoming.price) == "101"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("price", "101.01"),
        ("fill_at", datetime(2026, 10, 20, 14, 0, 2, tzinfo=UTC)),
        ("quantity", 3),
        ("contract_id", C2),
        ("fee", "2.5"),
        ("fee_currency", "KRW"),
        ("client_order_id", "C-9"),
        ("broker_order_id", "B-9"),
        ("venue", "XF"),
        ("liquidity_flag", "MAKER"),
    ],
)
def test_same_key_with_different_content_is_conflict(field, value):
    """입력: 같은 키 (A1, BRK, X-1)인데 §6.4a 비교 필드 하나가 다른 재수신.
    출력: CONFLICT. 두 번째 기록은 반영하지 않고, 기존·새 기록과 다른 필드 이름을 증거로 남긴다.
    전제: "수량과 가격이 같으니 중복"으로 처리하지 않는다 (AT-0009-10)."""
    first = apply_fill(empty_ledger(), make_fill())
    second = apply_fill(first.ledger, make_fill(**{field: value}))

    assert second.verdict is FillVerdict.CONFLICT
    assert second.ledger.applied == first.ledger.applied
    assert second.differing_fields == (field,)
    assert second.existing == first.ledger.applied[0]
    assert len(second.ledger.conflicts) == 1
    conflict = second.ledger.conflicts[0]
    assert conflict.existing == first.ledger.applied[0]
    assert conflict.incoming == second.incoming


def test_same_fill_id_from_other_source_is_a_different_key():
    """입력: 같은 체결 ID X-1이 출처 BRK와 출처 SIM-1에서 옴 (SIM-1은 시뮬레이션, 가정 참조 있음).
    출력: 둘 다 APPLIED. 멱등 키는 (계좌, 출처, 체결 ID)다 (§6.4a)."""
    first = apply_fill(empty_ledger(), make_fill())
    simulated = make_fill(
        key=FillKey(account_id="A1", fill_source="SIM-1", fill_id="X-1"),
        origin=FillOrigin.SIMULATED,
        execution_assumption_ref="assumption:test-1",
        broker_order_id=None,
    )
    second = apply_fill(first.ledger, simulated)

    assert second.verdict is FillVerdict.APPLIED
    assert len(second.ledger.applied) == 2


def test_unknown_contract_is_rejected():
    """입력: 장부에 없는 월물 FUT.ALPHA.C3의 체결.
    출력: ValueError. 활성 월물을 추측하지 않는다 (I6-3)."""
    with pytest.raises(ValueError):
        apply_fill(empty_ledger(), make_fill(contract_id="FUT.ALPHA.C3"))


def test_fill_for_other_account_is_rejected():
    """입력: 계좌 A1 장부에 계좌 A2의 체결.
    출력: ValueError (단일 계좌 장부)."""
    with pytest.raises(ValueError):
        apply_fill(empty_ledger(), make_fill(key=FillKey(account_id="A2", fill_source="BRK", fill_id="X-1")))


def test_fee_currency_other_than_contract_currency_is_rejected_for_new_fill():
    """입력: USD 월물의 새 체결인데 수수료 통화가 KRW.
    출력: ValueError. Slice 1은 단일 통화이고 ADR-0001 잠정 가정(수수료 통화 = 상품 통화)을 따른다 (Q1-4, Q8-11)."""
    with pytest.raises(ValueError):
        apply_fill(empty_ledger(), make_fill(fee_currency="KRW"))


def test_simulated_fill_below_lot_is_rejected_but_broker_fill_is_recorded():
    """입력: lot size 10인 가상 월물. (a) 시뮬레이션 체결 +3계약, (b) 브로커 보고 체결 +3계약.
    출력: (a) ValueError (승인된 시뮬레이션 정책 전까지 lot 미만 시뮬레이션 체결 금지, R13-1, Q13-5).
    (b) APPLIED (실제 체결 수량은 lot 배수를 요구하지 않음, R13-1)."""
    ledger = empty_ledger(contract(C1, lot_size=10))
    with pytest.raises(ValueError):
        apply_fill(
            ledger,
            make_fill(quantity=3, origin=FillOrigin.SIMULATED, execution_assumption_ref="assumption:test-1", broker_order_id=None),
        )
    assert apply_fill(ledger, make_fill(quantity=3)).verdict is FillVerdict.APPLIED


def test_ledger_rejects_duplicate_contract_specs():
    """입력: 같은 월물 ID 사양 두 개.
    출력: ValueError (월물 사양은 월물 ID마다 하나)."""
    with pytest.raises(ValueError):
        FillLedger.empty(account_id="A1", contracts=(contract(C1), contract(C1, multiplier="50")))


def test_same_key_with_different_origin_is_conflict():
    """입력: 브로커 보고로 반영된 X-1과, 같은 키로 온 시뮬레이션 기록 (가정 참조 있음).
    출력: CONFLICT, 다른 필드 ("origin", "execution_assumption_ref"). 실제 체결과 시뮬레이션을 섞지 않는다."""
    first = apply_fill(empty_ledger(), make_fill())
    second = apply_fill(
        first.ledger,
        make_fill(origin=FillOrigin.SIMULATED, execution_assumption_ref="assumption:test-1"),
    )

    assert second.verdict is FillVerdict.CONFLICT
    assert second.differing_fields == ("origin", "execution_assumption_ref")


def test_comparison_fields_cover_every_fill_field_except_key():
    """입력: FillRecord의 필드 목록.
    출력: 비교 필드 = 모든 필드 − key. ADR-0009 §6.4a의 비교 대상(주문 ID, 거래 단위, 수량, 체결가, fill_at,
    수수료 금액·통화, 체결 시장·유동성 구분)이 빠지지 않는다."""
    assert set(FILL_COMPARISON_FIELDS) == {field.name for field in fields(FillRecord)} - {"key"}
    assert len(FILL_COMPARISON_FIELDS) == len(set(FILL_COMPARISON_FIELDS))


def test_ledger_rejects_hand_built_states_that_break_idempotency():
    """입력: apply_fill을 거치지 않고 만든 장부. (a) 같은 키의 체결 두 건, (b) 다른 계좌의 체결,
    (c) 장부에 없는 월물의 체결, (d) 반영되지 않은 키의 중복 수신 기록, (e) replace로 같은 키 추가.
    출력: 모두 ValueError. 장부 자체가 키당 한 건, 단일 계좌, 알려진 월물을 보장한다."""
    c1 = contract(C1)
    x1 = make_fill()
    other_account = make_fill(key=FillKey(account_id="A2", fill_source="BRK", fill_id="X-2"))
    unknown_contract = make_fill(fill_id="X-3", contract_id="FUT.ALPHA.C3")
    common = dict(account_id="A1", contracts=(c1,), conflicts=())
    with pytest.raises(ValueError):
        FillLedger(applied=(x1, make_fill(quantity=3)), duplicates=(), **common)
    with pytest.raises(ValueError):
        FillLedger(applied=(other_account,), duplicates=(), **common)
    with pytest.raises(ValueError):
        FillLedger(applied=(unknown_contract,), duplicates=(), **common)
    with pytest.raises(ValueError):
        FillLedger(applied=(), duplicates=(x1,), **common)
    ledger = apply_fill(empty_ledger(c1), x1).ledger
    with pytest.raises(ValueError):
        replace(ledger, applied=ledger.applied + (make_fill(quantity=3),))


def test_key_subclass_cannot_bypass_idempotency():
    """입력: X-1 반영 뒤, 같은 (A1, BRK, X-1) 값을 가진 FillKey 하위 클래스 키로 같은 체결을 다시 보냄.
    출력: DUPLICATE (두 번째 APPLIED가 아님). 키는 정확한 FillKey로 정규화되므로 수량·손익이 두 번 반영되지 않는다.
    직접 생성한 장부에 두 기록을 넣어도 ValueError."""

    class OtherKey(FillKey):
        pass

    first = apply_fill(empty_ledger(), make_fill())
    resend = make_fill(key=OtherKey(account_id="A1", fill_source="BRK", fill_id="X-1"))

    assert type(resend.key) is FillKey
    assert apply_fill(first.ledger, resend).verdict is FillVerdict.DUPLICATE
    with pytest.raises(ValueError):
        FillLedger(account_id="A1", contracts=(contract(C1), contract(C2)), applied=(make_fill(), resend), duplicates=(), conflicts=())


def test_identifier_string_subclass_cannot_hide_a_conflict():
    """입력: X-1 반영 뒤, client_order_id가 "어떤 값과도 같다"고 답하는 str 하위 클래스인 재수신 (실제 값은 "C-9").
    출력: CONFLICT (differing_fields = ("client_order_id",)). 식별자는 일반 str로 정규화되어 비교된다."""

    class AlwaysEqual(str):
        def __eq__(self, other):
            return True

        __hash__ = str.__hash__

    first = apply_fill(empty_ledger(), make_fill())
    second = apply_fill(first.ledger, make_fill(client_order_id=AlwaysEqual("C-9")))

    assert type(second.incoming.client_order_id) is str
    assert second.verdict is FillVerdict.CONFLICT
    assert second.differing_fields == ("client_order_id",)
