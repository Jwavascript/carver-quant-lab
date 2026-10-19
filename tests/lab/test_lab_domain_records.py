"""P0-03B Slice 1: 도메인 기록의 입력 검증 (정수 수량, Decimal 금액, UTC 시각, 식별자)."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import IntEnum

import pytest

from carver_quant.lab.domain.records import (
    FillKey,
    FillOrigin,
    FillRecord,
    FuturesContractSpec,
    PositionBaseline,
    ValuationPrice,
)

UTC = timezone.utc
FILL_AT = datetime(2026, 10, 20, 14, 0, tzinfo=UTC)


def make_fill(**overrides):
    fields = dict(
        key=FillKey(account_id="A1", fill_source="BRK", fill_id="X-1"),
        client_order_id="C-1",
        broker_order_id="B-1",
        contract_id="FUT.ALPHA.C1",
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


def test_decimal_fields_keep_original_representation():
    """입력: 체결가 문자열 "101.0", 수수료 "2.00" (USD).
    출력: Decimal로 저장되며 원본 표현(소수 자릿수)이 그대로 남는다. 값 비교는 수치 기준.
    전제: Slice 1의 비교 규칙은 Decimal 수치 동일성이다 (반올림·허용 오차 없음)."""
    fill = make_fill(price="101.0", fee="2.00")

    assert isinstance(fill.price, Decimal)
    assert str(fill.price) == "101.0"
    assert str(fill.fee) == "2.00"
    assert fill.price == Decimal("101")


@pytest.mark.parametrize(
    "bad_price",
    [101.0, float("nan"), "NaN", "sNaN", "Infinity", "-inf", Decimal("NaN"), True, "", " 101", "abc", None, "1_000", "\u0661\u0660\u0661", "\uff11\uff10\uff11"],
)
def test_fill_price_rejects_float_non_finite_and_unclear_input(bad_price):
    """입력: float, NaN, Infinity, bool, 공백이 붙은 문자열, 숫자가 아닌 값.
    출력: ValueError. float의 암묵적 Decimal 변환을 허용하지 않는다.
    단위: pt."""
    with pytest.raises(ValueError):
        make_fill(price=bad_price)


@pytest.mark.parametrize("bad_quantity", [0, True, False, 2.0, "2", None])
def test_fill_quantity_must_be_non_zero_int(bad_quantity):
    """입력: 0, bool, float, 문자열 수량.
    출력: ValueError. 체결 수량은 0이 아닌 정수 계약 수다 (ADR-0001 §6.2 Δq ≠ 0)."""
    with pytest.raises(ValueError):
        make_fill(quantity=bad_quantity)


@pytest.mark.parametrize("bad_fee", ["-0.01", -1, 1.0, "Infinity"])
def test_fee_must_be_finite_non_negative_decimal(bad_fee):
    """입력: 음수, float, 무한대 수수료.
    출력: ValueError (ADR-0001 §6.2 fee ≥ 0). 단위: USD."""
    with pytest.raises(ValueError):
        make_fill(fee=bad_fee)


@pytest.mark.parametrize(
    "bad_time",
    [datetime(2026, 10, 20, 14, 0), datetime(2026, 10, 20, 23, 0, tzinfo=timezone(timedelta(hours=9))), "2026-10-20T14:00:00Z"],
)
def test_fill_at_must_be_utc_aware_datetime(bad_time):
    """입력: naive 시각, UTC가 아닌 오프셋, 문자열.
    출력: ValueError. 시각은 UTC instant만 받는다 (INV-05, 비UTC 처리는 D3A-17 미결정)."""
    with pytest.raises(ValueError):
        make_fill(fill_at=bad_time)


def test_simulated_fill_requires_execution_assumption_reference():
    """입력: origin=SIMULATED이고 체결 가정 참조가 없는 체결.
    출력: ValueError. 시뮬레이션 체결은 명시적 체결 가정에서만 생긴다 (D3A-50 (5))."""
    with pytest.raises(ValueError):
        make_fill(origin=FillOrigin.SIMULATED, execution_assumption_ref=None)

    simulated = make_fill(origin=FillOrigin.SIMULATED, execution_assumption_ref="assumption:test-1")
    assert simulated.origin is FillOrigin.SIMULATED


def test_broker_reported_fill_must_not_carry_execution_assumption():
    """입력: origin=BROKER_REPORTED인데 체결 가정 참조가 있는 체결.
    출력: ValueError. 실제 체결과 시뮬레이션 체결을 섞지 않는다."""
    with pytest.raises(ValueError):
        make_fill(execution_assumption_ref="assumption:test-1")


def test_origin_must_be_enum_member():
    """입력: origin에 문자열 "BROKER_REPORTED".
    출력: ValueError (열거값만 받음)."""
    with pytest.raises(ValueError):
        make_fill(origin="BROKER_REPORTED")


@pytest.mark.parametrize("field", ["account_id", "fill_source", "fill_id"])
def test_fill_key_parts_are_explicit_non_empty_strings(field):
    """입력: 멱등 키 (계좌, 출처, 체결 ID) 가운데 하나가 빈 문자열.
    출력: ValueError. 키의 세 부분을 명시적으로 구분한다 (ADR-0009 §6.4a)."""
    parts = dict(account_id="A1", fill_source="BRK", fill_id="X-1")
    parts[field] = ""
    with pytest.raises(ValueError):
        FillKey(**parts)


@pytest.mark.parametrize("bad_multiplier", ["0", "-10", "NaN", "Infinity", 10.0, True])
def test_contract_multiplier_must_be_positive_finite_decimal(bad_multiplier):
    """입력: 0, 음수, NaN, 무한대, float, bool 계약승수.
    출력: ValueError (ADR-0001 §6.2 M[c] > 0). 단위: USD/pt/계약."""
    with pytest.raises(ValueError):
        FuturesContractSpec(
            contract_id="FUT.ALPHA.C1",
            instrument_id="FUT.ALPHA",
            currency="USD",
            multiplier=bad_multiplier,
            lot_size=1,
        )


@pytest.mark.parametrize("bad_lot", [0, -1, True, 1.0])
def test_contract_lot_size_must_be_positive_int(bad_lot):
    """입력: 0, 음수, bool, float lot size.
    출력: ValueError (lot size는 1 이상의 정수)."""
    with pytest.raises(ValueError):
        FuturesContractSpec(
            contract_id="FUT.ALPHA.C1",
            instrument_id="FUT.ALPHA",
            currency="USD",
            multiplier="10",
            lot_size=bad_lot,
        )


def test_baseline_requires_verification_reference_and_int_quantities():
    """입력: 검증 근거 참조가 없는 기준 포지션, bool 수량, 중복 없는 정상 기준 포지션.
    출력: 앞의 둘은 ValueError. 정상 입력은 월물별 정수 수량을 그대로 보존한다.
    전제: 검증 절차는 구현하지 않으며, 검증된 기준임을 참조로 명시해야 한다 (R13-3, Q13-2)."""
    as_of = datetime(2026, 10, 19, 0, 0, tzinfo=UTC)
    with pytest.raises(ValueError):
        PositionBaseline(account_id="A1", as_of=as_of, quantities={"FUT.ALPHA.C1": 15}, verification_ref="")
    with pytest.raises(ValueError):
        PositionBaseline(account_id="A1", as_of=as_of, quantities={"FUT.ALPHA.C1": True}, verification_ref="v")

    baseline = PositionBaseline(
        account_id="A1", as_of=as_of, quantities={"FUT.ALPHA.C1": 15, "FUT.ALPHA.C2": 0}, verification_ref="v"
    )
    assert baseline.quantity("FUT.ALPHA.C1") == 15
    assert baseline.quantity("FUT.ALPHA.C2") == 0


def test_valuation_price_is_raw_decimal_with_availability_time():
    """입력: 사용자가 지정한 월물별 raw 평가가격 "103" pt, 이용 가능 시각, 출처.
    출력: Decimal 가격과 시각을 보존. float 가격은 ValueError.
    전제: 평가가격 선택 정책은 구현하지 않는다 (Q1-2, Q7-3, Q7-4 미결정)."""
    valuation_at = datetime(2026, 10, 20, 21, 0, tzinfo=UTC)
    available = datetime(2026, 10, 20, 20, 30, tzinfo=UTC)
    price = ValuationPrice(
        contract_id="FUT.ALPHA.C1", price="103", valuation_at=valuation_at, data_available_at=available, source_ref="fixture"
    )
    assert price.price == Decimal("103")
    with pytest.raises(ValueError):
        ValuationPrice(
            contract_id="FUT.ALPHA.C1", price=103.0, valuation_at=valuation_at, data_available_at=available, source_ref="fixture"
        )


def test_int_and_decimal_subclasses_are_normalized():
    """입력: IntEnum 수량 2, Decimal 하위 클래스 체결가 101.0.
    출력: 저장 값은 정확히 int 2와 Decimal("101.0") (원본 자릿수 유지). 하위 클래스를 그대로 담지 않는다."""

    class Quantity(IntEnum):
        TWO = 2

    class MyDecimal(Decimal):
        pass

    fill = make_fill(quantity=Quantity.TWO, price=MyDecimal("101.0"))

    assert type(fill.quantity) is int and fill.quantity == 2
    assert type(fill.price) is Decimal and str(fill.price) == "101.0"


def test_baseline_accepts_its_normalized_form_and_rejects_duplicate_contracts():
    """입력: (a) dataclasses.replace로 검증 참조만 바꾼 기준 포지션, (b) 월물이 중복된 (월물, 수량) 쌍 목록.
    출력: (a) 같은 수량을 유지한 새 기준 포지션, (b) ValueError."""
    as_of = datetime(2026, 10, 19, 0, 0, tzinfo=UTC)
    baseline = PositionBaseline(account_id="A1", as_of=as_of, quantities={"FUT.ALPHA.C1": 15}, verification_ref="v")

    renamed = replace(baseline, verification_ref="v2")

    assert renamed.quantity("FUT.ALPHA.C1") == 15
    with pytest.raises(ValueError):
        PositionBaseline(
            account_id="A1",
            as_of=as_of,
            quantities=(("FUT.ALPHA.C1", 15), ("FUT.ALPHA.C1", 3)),
            verification_ref="v",
        )
