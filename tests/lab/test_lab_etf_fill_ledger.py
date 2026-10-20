"""P0-03B Slice 4: ETF 체결 장부와 실제 포지션 (ADR-0009 R9-2·R9-9, §6.4a, ADR-0006 I6-4·I6-6, ADR-0013 R13-1).

ETF 체결은 기존 FillRecord로 표현하고, 상품 구분은 EtfSpec으로 만든 별도 ETF 체결 장부가 한다. 선물 FillLedger는 그대로다.
체결은 가상 ETF의 시뮬레이션 체결(가정 참조 있음)이며 실제 브로커 체결로 확인된 것이 아니다.
"""

import copy
import dataclasses
from datetime import datetime, timedelta, timezone

import pytest

from carver_quant.lab.accounting import etf_fill_ledger as etf_fill_ledger_module
from carver_quant.lab.accounting.etf_fill_ledger import EtfFillLedger, apply_etf_fill
from carver_quant.lab.accounting.fill_ledger import FillConflict, FillIntegrityError, FillLedger, FillVerdict, apply_fill
from carver_quant.lab.accounting.positions import actual_position
from carver_quant.lab.domain.records import (
    EtfSpec,
    FillKey,
    FillOrigin,
    FillRecord,
    FuturesContractSpec,
    PositionBaseline,
)

UTC = timezone.utc
ETF = "ETF.US1"
T0 = datetime(2026, 10, 19, 0, 0, tzinfo=UTC)
BUY_AT = datetime(2026, 10, 20, 14, 30, tzinfo=UTC)
SELL_AT = datetime(2026, 10, 21, 14, 0, tzinfo=UTC)
V2 = datetime(2026, 10, 21, 21, 0, tzinfo=UTC)


def etf_spec(lot_size=1, currency="USD"):
    return EtfSpec(unit_id=ETF, currency=currency, lot_size=lot_size)


def make_fill(fill_id="E-1", quantity=10, price="100", fill_at=BUY_AT, fee="2", fee_currency="USD", unit_id=ETF, account_id="A1"):
    return FillRecord(
        key=FillKey(account_id=account_id, fill_source="SIM", fill_id=fill_id),
        client_order_id="C-" + fill_id,
        broker_order_id=None,
        contract_id=unit_id,
        quantity=quantity,
        price=price,
        fill_at=fill_at,
        fee=fee,
        fee_currency=fee_currency,
        origin=FillOrigin.SIMULATED,
        execution_assumption_ref="assumption:test-fixture",
        venue=None,
        liquidity_flag=None,
    )


def ledger_with(*fills, spec=None):
    ledger = EtfFillLedger.empty(account_id="A1", units=(spec or etf_spec(),))
    for fill in fills:
        ledger = apply_etf_fill(ledger, fill).ledger
    return ledger


def baseline(quantity=0):
    return PositionBaseline(account_id="A1", as_of=T0, quantities={ETF: quantity}, verification_ref="fixture:verified")


def test_applied_etf_fill_becomes_actual_position():
    """입력: 기준 0주, 시뮬레이션 체결 E-1 +10주 @ 100 USD/주.
    출력: APPLIED. 실제 포지션 +10주 (R9-2: 검증된 기준 + 반영된 체결). 기존 actual_position을 그대로 쓴다."""
    result = apply_etf_fill(EtfFillLedger.empty(account_id="A1", units=(etf_spec(),)), make_fill())

    assert result.verdict is FillVerdict.APPLIED
    assert actual_position(baseline(), result.ledger, V2) == {ETF: 10}


def test_sell_is_negative_quantity():
    """입력: +10주 매수 뒤 −4주 매도 (E-2).
    출력: 실제 포지션 6주. 매수는 +, 매도는 −로 더한다."""
    ledger = ledger_with(make_fill(), make_fill(fill_id="E-2", quantity=-4, price="110", fill_at=SELL_AT, fee="1"))

    assert actual_position(baseline(), ledger, V2) == {ETF: 6}


def test_same_fill_twice_is_applied_once():
    """입력: 같은 체결 E-1을 두 번 받음.
    출력: 두 번째는 DUPLICATE. 실제 포지션 +10주 그대로 (+20 아님)."""
    ledger = ledger_with(make_fill())

    result = apply_etf_fill(ledger, make_fill())

    assert result.verdict is FillVerdict.DUPLICATE
    assert result.ledger.applied == ledger.applied
    assert actual_position(baseline(), result.ledger, V2) == {ETF: 10}


@pytest.mark.parametrize(("changes", "differing"), [({"quantity": 11}, ("quantity",)), ({"price": "101"}, ("price",))])
def test_conflicting_fill_is_kept_as_evidence_and_blocks_the_position(changes, differing):
    """입력: E-1 반영 뒤 같은 키로 수량 11 또는 가격 101인 기록.
    출력: CONFLICT. 반영 기록은 그대로이고 두 기록을 FillConflict로 보관한다. 실제 포지션 계산은 FillIntegrityError (R9-9)."""
    ledger = ledger_with(make_fill())

    result = apply_etf_fill(ledger, make_fill(**changes))

    assert result.verdict is FillVerdict.CONFLICT
    assert result.differing_fields == differing
    assert result.ledger.applied == ledger.applied
    assert result.ledger.conflicts[0].existing == make_fill()
    with pytest.raises(FillIntegrityError):
        actual_position(baseline(), result.ledger, V2)


def test_etf_fill_rules_follow_the_existing_contracts():
    """입력: (a) 수수료 통화 KRW (ETF 통화 USD), (b) lot 10 ETF에 5주 시뮬레이션 체결, (c) lot size 없는 ETF의 시뮬레이션 체결,
    (d) 장부에 없는 종목, (e) 다른 계좌의 체결.
    출력: 모두 ValueError. 수수료 통화 = 상품 통화(ADR-0001 잠정 가정), 시뮬레이션 체결의 lot 규칙(F-4, Q13-5)은 선물과 같다."""
    with pytest.raises(ValueError, match="fee_currency"):
        apply_etf_fill(ledger_with(), make_fill(fee_currency="KRW"))
    with pytest.raises(ValueError, match="lot multiple"):
        apply_etf_fill(ledger_with(spec=etf_spec(lot_size=10)), make_fill(quantity=5))
    with pytest.raises(ValueError, match="unknown lot size"):
        apply_etf_fill(ledger_with(spec=etf_spec(lot_size=None)), make_fill())
    with pytest.raises(ValueError, match="unknown unit"):
        apply_etf_fill(ledger_with(), make_fill(unit_id="ETF.US9"))
    with pytest.raises(ValueError, match="account"):
        apply_etf_fill(ledger_with(), make_fill(account_id="A2"))


def test_futures_and_etf_ledgers_stay_apart():
    """입력: (a) 선물 장부에 ETF 체결, (b) ETF 장부에 선물 월물 사양, (c) 선물 장부에 ETF 사양.
    출력: 모두 ValueError. ETF 체결이 선물 승수·월물 검증을 거치거나 선물 체결이 ETF로 해석되지 않는다 (I6-3, I6-6)."""
    futures = FuturesContractSpec(contract_id="FUT.ALPHA.C1", instrument_id="FUT.ALPHA", currency="USD", multiplier="10", lot_size=1)

    with pytest.raises(ValueError):
        apply_fill(FillLedger.empty(account_id="A1", contracts=(futures,)), make_fill())
    with pytest.raises(ValueError, match="EtfSpec"):
        EtfFillLedger.empty(account_id="A1", units=(futures,))
    with pytest.raises(ValueError, match="FuturesContractSpec"):
        FillLedger.empty(account_id="A1", contracts=(etf_spec(),))


def test_verified_holding_not_on_lot_is_not_rounded():
    """입력: lot 10 ETF, 검증된 기준 15주, 시뮬레이션 매수 +10주.
    출력: 실제 포지션 25주. lot 배수로 반올림하지 않는다 (ADR-0013 R13-1)."""
    ledger = ledger_with(make_fill(), spec=etf_spec(lot_size=10))

    assert actual_position(baseline(15), ledger, V2) == {ETF: 25}


def test_fill_at_the_baseline_time_is_rejected():
    """입력: 체결 시각 = 기준 시각 T0.
    출력: 실제 포지션 계산은 ValueError (Q13-2 결정 전 fail-fast, Slice 1과 같음)."""
    ledger = ledger_with(make_fill(fill_at=T0))

    with pytest.raises(ValueError, match="baseline time"):
        actual_position(baseline(), ledger, V2)


def test_etf_fill_ledger_is_built_only_through_apply():
    """입력: 충돌이 기록된 ETF 장부에 dataclasses.replace·copy.replace로 conflicts=(), 직접 생성, 하위 클래스 정의, 복사.
    출력: replace·직접 생성은 ValueError, 하위 클래스는 TypeError. 복사본도 충돌 증거를 가진다 (Gate A와 같은 장치)."""
    ledger = apply_etf_fill(ledger_with(make_fill()), make_fill(quantity=11)).ledger

    with pytest.raises(ValueError, match="can only be created"):
        dataclasses.replace(ledger, conflicts=())
    with pytest.raises(ValueError, match="can only be created"):
        copy.replace(ledger, conflicts=())
    with pytest.raises(ValueError, match="can only be created"):
        EtfFillLedger(account_id="A1", units=ledger.units, applied=ledger.applied, duplicates=(), conflicts=())
    with pytest.raises(TypeError):

        class LenientEtfLedger(EtfFillLedger):  # noqa: F841
            pass

    for duplicate in (copy.copy(ledger), copy.deepcopy(ledger)):
        assert duplicate.conflicts == ledger.conflicts
        with pytest.raises(FillIntegrityError):
            actual_position(baseline(), duplicate, V2)


def test_internal_construction_validates_etf_ledger_invariants():
    """입력: 내부 생성 경로로 만든 잘못된 ETF 장부: 같은 키 두 건, 다른 계좌, 수수료 통화 불일치, 반영되지 않은 키의 중복 수신,
    반영 기록을 가리키지 않는 충돌 기록, 같은 종목 사양 두 개.
    출력: 각각 해당 사유의 ValueError (방어적 이중 검사)."""
    other = make_fill(fill_id="E-9")
    orphan = FillConflict(existing=other, incoming=dataclasses.replace(other, quantity=3), differing_fields=("quantity",))
    cases = [
        (dict(applied=(make_fill(), make_fill(quantity=3))), "appears more than once"),
        (dict(applied=(make_fill(account_id="A2"),)), "another account"),
        (dict(applied=(make_fill(fee_currency="KRW"),)), "fee_currency"),
        (dict(applied=(make_fill(),), duplicates=(other,)), "duplicate record must equal"),
        (dict(applied=(make_fill(),), conflicts=(orphan,)), "must refer to the applied fill"),
        (dict(units=(etf_spec(), etf_spec())), "repeat"),
        (dict(applied=(make_fill(price="0"),)), "positive"),
    ]
    for kwargs, message in cases:
        fields = dict(account_id="A1", units=(etf_spec(),), applied=(), duplicates=(), conflicts=())
        fields.update(kwargs)
        with pytest.raises(ValueError, match=message):
            EtfFillLedger(**fields, _build_token=etf_fill_ledger_module._ETF_FILL_LEDGER_BUILD_TOKEN)


def test_fill_after_as_of_is_not_in_the_position():
    """입력: 매도 체결(10-21 14:00)이 든 장부, as_of = 매도 1분 전.
    출력: 실제 포지션 10주 (as_of 뒤의 체결은 넣지 않음, R9-13)."""
    ledger = ledger_with(make_fill(), make_fill(fill_id="E-2", quantity=-4, price="110", fill_at=SELL_AT, fee="1"))

    assert actual_position(baseline(), ledger, SELL_AT - timedelta(minutes=1)) == {ETF: 10}


@pytest.mark.parametrize("bad_price", ["0", "-100"])
def test_etf_fill_price_must_be_positive_while_the_futures_rule_is_unchanged(bad_price):
    """입력: (a) ETF 체결 가격 0 또는 −100 (USD/주), (b) 선물 월물 체결 가격 −37.63 pt.
    출력: (a) ValueError, 장부는 그대로 (ETF 가격은 0보다 커야 한다, Slice 4 사용자 결정).
    (b) 선물 장부는 APPLIED (선물 가격 규칙은 바꾸지 않음)."""
    ledger = ledger_with()
    futures = FuturesContractSpec(contract_id="FUT.ALPHA.C1", instrument_id="FUT.ALPHA", currency="USD", multiplier="10", lot_size=1)

    with pytest.raises(ValueError, match="positive"):
        apply_etf_fill(ledger, make_fill(price=bad_price))
    assert ledger.applied == ()
    futures_result = apply_fill(FillLedger.empty(account_id="A1", contracts=(futures,)), make_fill(price="-37.63", unit_id="FUT.ALPHA.C1"))
    assert futures_result.verdict is FillVerdict.APPLIED
