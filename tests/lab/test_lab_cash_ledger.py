"""P0-03B Slice 3: 현금 이벤트와 현금 장부 (ADR-0008 §6.1·§6.3·§6.6, X8-1·X8-2·X8-7·X8-8, F8-1·F8-2 원칙, ADR-0009 R9-9·R9-11).

기대값(998, 1,298 USD 등)은 저장소 밖 독립 산술(Fraction)로 먼저 확인했다. 가상 ETF이며 시장 사실을 주장하지 않는다.
"""

import copy
import dataclasses
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from carver_quant.lab.accounting import cash_ledger as cash_ledger_module
from carver_quant.lab.accounting.cash_ledger import (
    CashConflict,
    CashIntegrityError,
    CashLedger,
    CashVerdict,
    apply_cash_event,
    cash_balance,
)
from carver_quant.lab.domain.cash import CASH_EVENT_COMPARISON_FIELDS, CashEvent, CashEventConfirmation, CashEventKind

UTC = timezone.utc
K = CashEventKind
FUND_AT = datetime(2026, 10, 19, 13, 0, tzinfo=UTC)
V0 = datetime(2026, 10, 19, 21, 0, tzinfo=UTC)
BUY_AT = datetime(2026, 10, 20, 14, 30, tzinfo=UTC)
V1 = datetime(2026, 10, 20, 21, 0, tzinfo=UTC)
V2 = datetime(2026, 10, 21, 21, 0, tzinfo=UTC)
DEPOSIT_AT = datetime(2026, 10, 22, 15, 0, tzinfo=UTC)
V3 = datetime(2026, 10, 22, 21, 0, tzinfo=UTC)
FILL_REF = "fill:A1:BRK:E-1"


def make_event(event_id, kind, amount, occurred_at, cause_ref, currency="USD", confirmation=CashEventConfirmation.CONFIRMED, account_id="A1"):
    return CashEvent(
        account_id=account_id,
        cash_event_id=event_id,
        kind=kind,
        cause_ref=cause_ref,
        currency=currency,
        amount=amount,
        occurred_at=occurred_at,
        confirmation=confirmation,
    )


def funding():
    return make_event("CE-0", K.EXTERNAL_FLOW, "2000", FUND_AT, "transfer:T-0")


def consideration():
    return make_event("CE-1", K.TRADE_CONSIDERATION, "-1000", BUY_AT, FILL_REF)


def commission():
    return make_event("CE-2", K.COMMISSION, "-2", BUY_AT, FILL_REF)


def deposit():
    return make_event("CE-3", K.EXTERNAL_FLOW, "300", DEPOSIT_AT, "transfer:T-1")


def ledger_with(*events):
    ledger = CashLedger.empty(account_id="A1")
    for event in events:
        ledger = apply_cash_event(ledger, event).ledger
    return ledger


def balance(ledger, as_of, currency="USD", information_cutoff=None):
    return cash_balance(ledger, currency=currency, as_of=as_of, information_cutoff=information_cutoff or as_of)


def conflicting_ledger():
    ledger = ledger_with(funding(), consideration(), commission())
    return apply_cash_event(ledger, make_event("CE-2", K.COMMISSION, "-3", BUY_AT, FILL_REF)).ledger


def test_cash_event_kinds_are_the_slice_3_minimum():
    """입력: CashEventKind.
    출력: TRADE_CONSIDERATION, COMMISSION, EXTERNAL_FLOW 세 종류뿐이다 (분배금·선물 정산·환전·결제 상태 변경은 Slice 3 범위 밖)."""
    assert [kind.name for kind in CashEventKind] == ["TRADE_CONSIDERATION", "COMMISSION", "EXTERNAL_FLOW"]


def test_case_1_purchase_cash_events_and_balance():
    """CASE 1. 입력: 입금 2,000 USD, ETF 10주 매수 @ 100 → 매매대금 −1,000, 수수료 −2 (같은 체결 참조).
    출력: V1 잔액 998 USD = 대금 −1,000 + 수수료 −2 + 외부 흐름 2,000. 대금은 현금과 자산의 교환이며 손익 항목이 아니다 (X8-1)."""
    ledger = ledger_with(funding(), consideration(), commission())

    result = balance(ledger, V1)

    assert (result.trade_consideration, result.commission, result.external_flow) == (
        Decimal("-1000"),
        Decimal("-2"),
        Decimal("2000"),
    )
    assert result.balance == Decimal("998")
    assert (result.account_id, result.currency, result.as_of) == ("A1", "USD", V1)


def test_events_after_as_of_are_not_in_a_past_balance():
    """입력: CASE 1~3의 모든 이벤트 (입금 2,000 → 매수 → 입금 300)가 든 장부.
    출력: V0 잔액 2,000 (매수 전), V1·V2 잔액 998 (입금 300 전), V3 잔액 1,298. 나중에 발생한 이벤트를 과거 잔액에 넣지 않는다."""
    ledger = ledger_with(funding(), consideration(), commission(), deposit())

    balances = [balance(ledger, as_of).balance for as_of in (V0, V1, V2, V3)]

    assert balances == [Decimal("2000"), Decimal("998"), Decimal("998"), Decimal("1298")]


def test_event_after_information_cutoff_is_rejected():
    """입력: 매수 이벤트(14:30)가 든 장부, as_of V1(21:00), information_cutoff 14:00.
    출력: ValueError. 정보 기준 시각까지 알 수 없었던 이벤트를 잔액에 넣지도, 조용히 빼고 계산하지도 않는다 (V-1)."""
    ledger = ledger_with(funding(), consideration(), commission())

    with pytest.raises(ValueError, match="after information_cutoff"):
        balance(ledger, V1, information_cutoff=datetime(2026, 10, 20, 14, 0, tzinfo=UTC))


def test_same_event_twice_is_applied_once():
    """입력: 수수료 이벤트 CE-2를 두 번 받음.
    출력: 두 번째는 DUPLICATE. 잔액 998 (996이 아님). 수수료는 현금에서 한 번만 빠진다 (F8-1 원칙, R9-9)."""
    ledger = ledger_with(funding(), consideration(), commission())

    result = apply_cash_event(ledger, commission())

    assert result.verdict is CashVerdict.DUPLICATE
    assert result.ledger.applied == ledger.applied
    assert result.ledger.duplicates == (commission(),)
    assert balance(result.ledger, V1).balance == Decimal("998")


def test_same_id_with_different_content_is_a_conflict_that_blocks_the_balance():
    """입력: 반영된 CE-2(수수료 −2)와 같은 ID인데 금액이 −3인 기록.
    출력: CONFLICT (differing_fields = ("amount",)). 두 번째 기록은 반영하지 않고 두 기록을 보관한다. 잔액 계산은 CashIntegrityError."""
    ledger = ledger_with(funding(), consideration(), commission())

    result = apply_cash_event(ledger, make_event("CE-2", K.COMMISSION, "-3", BUY_AT, FILL_REF))

    assert result.verdict is CashVerdict.CONFLICT
    assert result.differing_fields == ("amount",)
    assert result.ledger.applied == ledger.applied
    assert result.ledger.conflicts[0].existing == commission()
    with pytest.raises(CashIntegrityError):
        balance(result.ledger, V1)


@pytest.mark.parametrize(
    "second",
    [
        make_event("CE-9", K.COMMISSION, "-2", BUY_AT, FILL_REF),
        make_event("CE-8", K.TRADE_CONSIDERATION, "-1000", BUY_AT, FILL_REF),
    ],
)
def test_second_fee_or_consideration_for_the_same_fill_is_a_conflict(second):
    """입력: 체결 E-1의 대금(CE-1)·수수료(CE-2)가 반영된 뒤, 같은 체결을 가리키는 같은 종류의 이벤트가 다른 ID로 옴.
    출력: CONFLICT (cash_event_id가 다름). 더하지 않으므로 잔액이 996이나 −2가 되지 않고, 판단될 때까지 잔액 계산을 막는다.
    체결 하나의 대금과 수수료는 각각 한 번만 현금에 들어간다 (R9-9, R9-11, F8-1 원칙)."""
    ledger = ledger_with(funding(), consideration(), commission())

    result = apply_cash_event(ledger, second)

    assert result.verdict is CashVerdict.CONFLICT
    assert result.differing_fields == ("cash_event_id",)
    assert result.ledger.applied == ledger.applied
    with pytest.raises(CashIntegrityError):
        balance(result.ledger, V1)


def test_external_flows_have_no_extra_uniqueness_rule():
    """입력: 서로 다른 송금 참조의 입금 두 건 (CE-3 300, CE-4 300).
    출력: 둘 다 APPLIED, V3 잔액 2,600. 외부 흐름은 이벤트 ID로만 멱등하다 (ADR에 없는 규칙을 만들지 않음)."""
    ledger = ledger_with(funding(), deposit())

    result = apply_cash_event(ledger, make_event("CE-4", K.EXTERNAL_FLOW, "300", DEPOSIT_AT, "transfer:T-2"))

    assert result.verdict is CashVerdict.APPLIED
    assert balance(result.ledger, V3).balance == Decimal("2600")


def test_commission_takes_cash_out():
    """입력: 수수료 이벤트 금액 +2, 0.
    출력: +2는 ValueError (수수료 ≥ 0, ADR-0001 §6.2이므로 수수료 현금 이벤트는 ≤ 0). 0은 받는다."""
    with pytest.raises(ValueError):
        make_event("CE-5", K.COMMISSION, "2", BUY_AT, FILL_REF)
    assert make_event("CE-5", K.COMMISSION, "0", BUY_AT, FILL_REF).amount == 0


@pytest.mark.parametrize(
    "amount",
    [2.0, float("nan"), Decimal("NaN"), Decimal("sNaN"), Decimal("Infinity"), Decimal("-Infinity"), "NaN", "Infinity", "1,000", "", True],
)
def test_amount_must_be_a_finite_decimal(amount):
    """입력: float, NaN, Infinity, 쉼표가 든 문자열, 빈 문자열, bool 금액.
    출력: ValueError. 금액은 Decimal로만 계산한다."""
    with pytest.raises(ValueError):
        make_event("CE-6", K.EXTERNAL_FLOW, amount, FUND_AT, "transfer:T-6")


def test_event_fields_are_validated():
    """입력: 종류·확인 상태에 문자열, 시간대 없는 발생 시각, 빈 원인 참조.
    출력: 모두 ValueError (해석되지 않은 값을 받지 않음)."""
    with pytest.raises(ValueError):
        make_event("CE-6", "EXTERNAL_FLOW", "1", FUND_AT, "transfer:T-6")
    with pytest.raises(ValueError):
        make_event("CE-6", K.EXTERNAL_FLOW, "1", FUND_AT, "transfer:T-6", confirmation="CONFIRMED")
    with pytest.raises(ValueError):
        make_event("CE-6", K.EXTERNAL_FLOW, "1", datetime(2026, 10, 19, 13, 0), "transfer:T-6")
    with pytest.raises(ValueError):
        make_event("CE-6", K.EXTERNAL_FLOW, "1", FUND_AT, "")


def test_unconfirmed_broker_cash_record_is_not_applied_as_a_fact():
    """입력: 브로커가 보고했지만 확인되지 않은 입금 300 (UNCONFIRMED).
    출력: ValueError. 장부와 잔액은 그대로다. 확인되지 않은 기록은 사실로 반영하지 않는다 (브로커 대조는 범위 밖, ADR-0012 BF-6)."""
    ledger = ledger_with(funding())
    unconfirmed = make_event(
        "CE-7", K.EXTERNAL_FLOW, "300", DEPOSIT_AT, "transfer:T-7", confirmation=CashEventConfirmation.UNCONFIRMED
    )

    with pytest.raises(ValueError, match="unconfirmed"):
        apply_cash_event(ledger, unconfirmed)
    assert balance(ledger, V3).balance == Decimal("2000")


def test_other_currency_events_are_kept_apart():
    """입력: USD 이벤트(CASE 1)와 KRW 입금 1,000,000이 든 장부.
    출력: USD 잔액 998과 KRW 잔액 1,000,000을 따로 계산한다. 두 통화를 더한 1,000,998을 만들지 않는다 (X8-8)."""
    krw = make_event("CE-K", K.EXTERNAL_FLOW, "1000000", FUND_AT, "transfer:T-K", currency="KRW")
    ledger = ledger_with(funding(), consideration(), commission(), krw)

    assert balance(ledger, V1).balance == Decimal("998")
    assert balance(ledger, V1, currency="KRW").balance == Decimal("1000000")


def test_event_for_another_account_is_rejected():
    """입력: 계좌 A1 장부에 계좌 A2의 이벤트.
    출력: ValueError."""
    with pytest.raises(ValueError):
        apply_cash_event(ledger_with(), make_event("CE-X", K.EXTERNAL_FLOW, "1", FUND_AT, "transfer:T-X", account_id="A2"))


def test_negative_cash_is_recorded_without_a_new_rule():
    """입력: 입금 2,000, 매수 대금 −3,000, 수수료 −2.
    출력: 잔액 −1,002. 음수 현금을 막는 규칙을 만들지 않는다 (사용 가능 현금 검사는 ADR-0003 L1, 범위 밖)."""
    ledger = ledger_with(
        funding(),
        make_event("CE-1", K.TRADE_CONSIDERATION, "-3000", BUY_AT, FILL_REF),
        make_event("CE-2", K.COMMISSION, "-2", BUY_AT, FILL_REF),
    )

    assert balance(ledger, V1).balance == Decimal("-1002")


def test_cash_ledger_is_built_only_through_apply():
    """입력: 충돌이 기록된 장부에 dataclasses.replace·copy.replace로 conflicts=(), 직접 생성, 하위 클래스 정의, 복사.
    출력: replace·직접 생성은 ValueError, 하위 클래스는 TypeError. 복사본은 충돌 증거를 그대로 가지며 잔액 계산이 막힌다
    (Slice 2 Gate A와 같은 장치)."""
    ledger = conflicting_ledger()

    with pytest.raises(ValueError, match="can only be created"):
        dataclasses.replace(ledger, conflicts=())
    with pytest.raises(ValueError, match="can only be created"):
        copy.replace(ledger, conflicts=())
    with pytest.raises(ValueError, match="can only be created"):
        CashLedger(account_id="A1", applied=ledger.applied, duplicates=(), conflicts=())
    with pytest.raises(TypeError):

        class LenientCashLedger(CashLedger):  # noqa: F841
            pass

    for duplicate in (copy.copy(ledger), copy.deepcopy(ledger)):
        assert duplicate.conflicts == ledger.conflicts
        with pytest.raises(CashIntegrityError):
            balance(duplicate, V1)


def internal_ledger(applied=(), duplicates=(), conflicts=()):
    """내부 생성 경로(apply_cash_event가 쓰는 표식)로 장부를 만든다. 불변조건 검사 자체를 시험하기 위한 것이다."""
    return CashLedger(
        account_id="A1",
        applied=applied,
        duplicates=duplicates,
        conflicts=conflicts,
        _build_token=cash_ledger_module._CASH_LEDGER_BUILD_TOKEN,
    )


def test_internal_construction_validates_ledger_invariants():
    """입력: 내부 생성 경로로 만든 잘못된 장부: 같은 ID 두 건, 다른 계좌, 확인되지 않은 기록, 같은 체결의 수수료 두 건,
    반영되지 않은 ID의 중복 수신, 반영 기록을 가리키지 않는 충돌 기록.
    출력: 각각 해당 사유의 ValueError (생성 제한과 별개인 방어적 이중 검사)."""
    other_fill_same_id = make_event("CE-2", K.COMMISSION, "-3", BUY_AT, "fill:A1:BRK:E-2")
    other_account = make_event("CE-X", K.EXTERNAL_FLOW, "1", FUND_AT, "transfer:T-X", account_id="A2")
    unconfirmed = make_event(
        "CE-7", K.EXTERNAL_FLOW, "300", DEPOSIT_AT, "transfer:T-7", confirmation=CashEventConfirmation.UNCONFIRMED
    )
    second_fee = make_event("CE-9", K.COMMISSION, "-2", BUY_AT, FILL_REF)
    orphan_conflict = CashConflict(
        existing=commission(), incoming=make_event("CE-2", K.COMMISSION, "-3", BUY_AT, FILL_REF), differing_fields=("amount",)
    )
    cases = [
        (dict(applied=(commission(), other_fill_same_id)), "id appears more than once"),
        (dict(applied=(other_account,)), "another account"),
        (dict(applied=(unconfirmed,)), "unconfirmed"),
        (dict(applied=(commission(), second_fee)), "same cause"),
        (dict(applied=(funding(),), duplicates=(commission(),)), "duplicate record must equal"),
        (dict(applied=(funding(),), conflicts=(orphan_conflict,)), "must refer to an applied event"),
    ]
    for kwargs, message in cases:
        with pytest.raises(ValueError, match=message):
            internal_ledger(**kwargs)


def test_conflict_evidence_is_immutable_and_validated():
    """입력: 충돌 기록 필드 변경 시도, 잘못 만든 충돌 기록 (다른 필드 목록이 실제와 다름, 같은 ID도 같은 체결의 같은 종류도 아닌 두 기록).
    출력: 변경은 FrozenInstanceError, 잘못된 기록은 ValueError."""
    conflict = conflicting_ledger().conflicts[0]

    with pytest.raises(dataclasses.FrozenInstanceError):
        conflict.incoming = conflict.existing
    with pytest.raises(ValueError):
        CashConflict(existing=conflict.existing, incoming=conflict.incoming, differing_fields=("occurred_at",))
    with pytest.raises(ValueError):
        CashConflict(
            existing=funding(),
            incoming=deposit(),
            differing_fields=("cash_event_id", "cause_ref", "amount", "occurred_at"),
        )


def test_cash_event_comparison_covers_every_field_but_the_key():
    """입력: CashEvent의 필드 목록.
    출력: 같은 ID 재수신의 비교 필드 = 키(계좌, Cash Event ID)를 뺀 모든 필드."""
    fields = {field.name for field in dataclasses.fields(CashEvent)}

    assert set(CASH_EVENT_COMPARISON_FIELDS) == fields - {"account_id", "cash_event_id"}
    assert len(CASH_EVENT_COMPARISON_FIELDS) == len(set(CASH_EVENT_COMPARISON_FIELDS))


def test_balance_inputs_are_explicit_utc_times_and_currency():
    """입력: (a) 시간대 없는 as_of, (b) information_cutoff > as_of, (c) 빈 통화.
    출력: 모두 ValueError."""
    ledger = ledger_with(funding())

    with pytest.raises(ValueError):
        cash_balance(ledger, currency="USD", as_of=datetime(2026, 10, 20, 21, 0), information_cutoff=V1)
    with pytest.raises(ValueError):
        cash_balance(ledger, currency="USD", as_of=V1, information_cutoff=V2)
    with pytest.raises(ValueError):
        cash_balance(ledger, currency="", as_of=V1, information_cutoff=V1)


def test_building_a_ledger_does_not_rescan_every_pair_of_events(monkeypatch):
    """입력: 입금 1건과 체결 200건(체결마다 대금·수수료)을 차례로 반영한 장부 (401건).
    출력: 같은 체결 검사 호출 수 ≤ 401² (이벤트 수의 제곱). 반영마다 모든 이벤트 쌍을 다시 비교하던 구현은 약 1,080만 번
    호출해 401건에 수 초가 걸렸다 (검토 MEDIUM-1, 장부 구성 비용이 세제곱으로 늘어남). 결과 잔액은 2,000 − 200 × 32 = −4,400."""
    calls = 0
    original = cash_ledger_module._same_fill_cause

    def counting(first, second):
        nonlocal calls
        calls += 1
        return original(first, second)

    monkeypatch.setattr(cash_ledger_module, "_same_fill_cause", counting)
    events = [funding()]
    for number in range(200):
        fill_ref = f"fill:A1:BRK:E-{number}"
        events.append(make_event(f"CE-C{number}", K.TRADE_CONSIDERATION, "-30", BUY_AT, fill_ref))
        events.append(make_event(f"CE-F{number}", K.COMMISSION, "-2", BUY_AT, fill_ref))

    ledger = ledger_with(*events)

    assert len(ledger.applied) == 401
    assert calls <= 401 * 401
    assert balance(ledger, V1).balance == Decimal("-4400")
