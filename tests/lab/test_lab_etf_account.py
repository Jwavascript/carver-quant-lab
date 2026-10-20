"""P0-03B Slice 4: ETF 체결 → 실제 포지션 → 현금 이벤트 → NAV 통합 (ADR-0009 R9-2·R9-9·R9-11, ADR-0008 §6.2·§6.3·§6.4,
X8-1·X8-2·X8-7·X8-8, F8-1·F8-2 원칙, ADR-0001 §5.1.3·§6.2, ADR-0013 R13-1).

기대값(1,998·2,098·2,398 USD, 투자 손익 +98 등)은 저장소 밖 독립 산술(Fraction)로 먼저 확인했다. 체결은 가상 ETF의
시뮬레이션 체결(가정 참조 있음)이고, 시작 현금·평가가격도 출처와 시각을 명시한 테스트 입력이다. 실제 브로커 체결·현금으로
확인된 것이 아니며, COMPUTED는 운영용 NAV 확정이 아니다.
"""

import dataclasses
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from carver_quant.lab.accounting.cash_ledger import CashIntegrityError, CashLedger, CashVerdict, apply_cash_event
from carver_quant.lab.accounting.etf_account import (
    EtfAccount,
    FillCashIssueKind,
    PostingOutcome,
    FillCashReconciliationError,
    account_cash,
    account_nav,
    account_position,
    fill_cash_events,
    fill_cause_ref,
    open_etf_account,
    reconcile_fill_cash,
    record_cash_event,
    record_etf_fill,
)
from carver_quant.lab.accounting.etf_fill_ledger import EtfFillLedger, apply_etf_fill
from carver_quant.lab.accounting.fill_ledger import FillIntegrityError, FillVerdict
from carver_quant.lab.accounting.valuation import NAV_OPEN_POLICIES, NavStatus, nav_change, position_market_value
from carver_quant.lab.domain.cash import CashEvent, CashEventConfirmation, CashEventKind
from carver_quant.lab.domain.records import EtfSpec, FillKey, FillOrigin, FillRecord, PositionBaseline, ValuationPrice

UTC = timezone.utc
K = CashEventKind
ETF = "ETF.US1"
T0 = datetime(2026, 10, 19, 0, 0, tzinfo=UTC)
FUND_AT = datetime(2026, 10, 19, 13, 0, tzinfo=UTC)
V0 = datetime(2026, 10, 19, 21, 0, tzinfo=UTC)
BUY_AT = datetime(2026, 10, 20, 14, 30, tzinfo=UTC)
V1 = datetime(2026, 10, 20, 21, 0, tzinfo=UTC)
SELL_AT = datetime(2026, 10, 21, 14, 0, tzinfo=UTC)
V2 = datetime(2026, 10, 21, 21, 0, tzinfo=UTC)
DEPOSIT_AT = datetime(2026, 10, 22, 15, 0, tzinfo=UTC)
V3 = datetime(2026, 10, 22, 21, 0, tzinfo=UTC)


def etf_spec(unit_id=ETF, currency="USD", lot_size=1):
    return EtfSpec(unit_id=unit_id, currency=currency, lot_size=lot_size)


def make_fill(fill_id="E-1", quantity=10, price="100", fill_at=BUY_AT, fee="2", fee_currency="USD", unit_id=ETF, source="SIM"):
    return FillRecord(
        key=FillKey(account_id="A1", fill_source=source, fill_id=fill_id),
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


def flow(event_id, amount, occurred_at, currency="USD"):
    return CashEvent(
        account_id="A1",
        cash_event_id=event_id,
        kind=K.EXTERNAL_FLOW,
        cause_ref="transfer:" + event_id,
        currency=currency,
        amount=amount,
        occurred_at=occurred_at,
        confirmation=CashEventConfirmation.CONFIRMED,
    )


def baseline(quantity=0, unit_id=ETF):
    return PositionBaseline(account_id="A1", as_of=T0, quantities={unit_id: quantity}, verification_ref="fixture:verified")


def opened(deposit="2000", spec=None, base=None):
    """입금 2,000 USD(10-19 13:00)만 있는 계좌."""
    account = open_etf_account(baseline=base or baseline(), units=(spec or etf_spec(),))
    return record_cash_event(account, flow("CE-0", deposit, FUND_AT)).account


def after_buy(**kwargs):
    """CASE 1의 계좌: 입금 2,000 뒤 10주 매수 @ 100, 수수료 2."""
    return record_etf_fill(opened(**kwargs), make_fill()).account


def price(value, valuation_at, unit_id=ETF, available=None):
    return ValuationPrice(
        contract_id=unit_id,
        price=value,
        valuation_at=valuation_at,
        data_available_at=available or valuation_at - timedelta(minutes=30),
        source_ref="fixture:close",
    )


def nav(account, value, valuation_at, cutoff=None, unit_id=ETF):
    prices = {} if value is None else {unit_id: price(value, valuation_at, unit_id=unit_id)}
    return account_nav(
        account, prices=prices, currency="USD", valuation_at=valuation_at, information_cutoff=cutoff or valuation_at
    )


def external_account(*cash_events, fills=(make_fill(),)):
    """외부에서 받은 현금 이벤트로 만든 계좌 (체결 장부와 현금 장부를 따로 받은 경우)."""
    fill_ledger = EtfFillLedger.empty(account_id="A1", units=(etf_spec(),))
    for fill in fills:
        fill_ledger = apply_etf_fill(fill_ledger, fill).ledger
    cash = CashLedger.empty(account_id="A1")
    for event in (flow("CE-0", "2000", FUND_AT),) + cash_events:
        cash = apply_cash_event(cash, event).ledger
    return EtfAccount(baseline=baseline(), fills=fill_ledger, cash=cash)


def test_fill_cash_events_have_fixed_signs_and_deterministic_ids():
    """입력: 매수 +10주 @ 100, 수수료 2 / 매도 −4주 @ 110, 수수료 1.
    출력: 매수 → 매매대금 −1,000, 수수료 −2. 매도 → 매매대금 +440, 수수료 −1. 발생 시각 = fill_at, 통화 = ETF 통화,
    원인 참조 = 체결 키. 같은 체결로 다시 만들면 같은 ID의 같은 이벤트다 (재처리로 다른 ID가 생기지 않음)."""
    buy = fill_cash_events(make_fill(), etf_spec())
    sell = fill_cash_events(make_fill(fill_id="E-2", quantity=-4, price="110", fill_at=SELL_AT, fee="1"), etf_spec())

    assert [(event.kind, event.amount) for event in buy] == [(K.TRADE_CONSIDERATION, Decimal("-1000")), (K.COMMISSION, Decimal("-2"))]
    assert [(event.kind, event.amount) for event in sell] == [(K.TRADE_CONSIDERATION, Decimal("440")), (K.COMMISSION, Decimal("-1"))]
    reference = fill_cause_ref(make_fill().key)
    assert all(event.cause_ref == reference and event.occurred_at == BUY_AT and event.currency == "USD" for event in buy)
    assert [event.cash_event_id for event in buy] == [reference + ":TRADE_CONSIDERATION", reference + ":COMMISSION"]
    assert fill_cash_events(make_fill(), etf_spec()) == buy


def test_fill_cause_ref_does_not_collide_across_key_parts():
    """입력: 체결 키 (A1, BRK, X:1)과 (A1, BRK:X, 1).
    출력: 원인 참조와 이벤트 ID가 서로 다르다. 구분자가 든 ID라도 다른 체결의 현금 이벤트가 같은 ID를 갖지 않는다."""
    first = FillKey(account_id="A1", fill_source="BRK", fill_id="X:1")
    second = FillKey(account_id="A1", fill_source="BRK:X", fill_id="1")

    assert fill_cause_ref(first) != fill_cause_ref(second)


def test_case_1_purchase():
    """CASE 1. 입력: 입금 2,000 USD, ETF 10주 매수 @ 100 (수수료 2), V1 평가가격 100.
    출력: 실제 +10주, 매매대금 −1,000, 수수료 −2, 현금 998, 평가액 1,000, NAV 1,998 (= 현금 + 평가액).
    초기 NAV 2,000 대비 −2는 수수료뿐이다. 매수 대금을 투자 손실로 계산하지 않는다 (X8-1)."""
    account = after_buy()

    position = account_position(account, as_of=V1, information_cutoff=V1)
    cash = account_cash(account, currency="USD", as_of=V1, information_cutoff=V1)
    result = nav(account, "100", V1)
    change = nav_change(start=nav(account, None, V0), end=result)

    assert position == {ETF: 10}
    assert (cash.trade_consideration, cash.commission, cash.balance) == (Decimal("-1000"), Decimal("-2"), Decimal("998"))
    assert (result.market_value, result.nav) == (Decimal("1000"), Decimal("1998"))
    assert result.nav == result.cash.balance + result.market_value
    assert (change.nav_change, change.external_flow, change.investment_pnl) == (Decimal("-2"), Decimal("0"), Decimal("-2"))


def test_case_2_price_rise():
    """CASE 2. 입력: CASE 1 뒤 V2 평가가격 110.
    출력: 현금 998, 평가액 1,100, NAV 2,098. 초기 NAV 2,000 대비 외부 흐름 0, 투자 손익 +98 = 가격 손익 +100 − 수수료 2."""
    account = after_buy()

    result = nav(account, "110", V2)
    change = nav_change(start=nav(account, None, V0), end=result)

    assert (result.cash.balance, result.market_value, result.nav) == (Decimal("998"), Decimal("1100"), Decimal("2098"))
    assert (change.nav_change, change.external_flow, change.investment_pnl) == (Decimal("98"), Decimal("0"), Decimal("98"))


def test_case_3_deposit_is_not_investment_return():
    """CASE 3. 입력: CASE 2 뒤 외부 입금 300 (10-22 15:00), V3 평가가격 110.
    출력: 현금 1,298, 평가액 1,100, NAV 2,398. CASE 2 → 3: ΔNAV 300 = 외부 흐름 300, 투자 손익 0.
    초기 → CASE 3 누적: ΔNAV 398 − 외부 흐름 300 = 투자 손익 +98 그대로 (ADR-0008 §6.4, X8-7)."""
    account = record_cash_event(after_buy(), flow("CE-3", "300", DEPOSIT_AT)).account
    initial = nav(account, None, V0)
    case_2 = nav(account, "110", V2)

    result = nav(account, "110", V3)

    assert (result.cash.balance, result.market_value, result.nav) == (Decimal("1298"), Decimal("1100"), Decimal("2398"))
    step = nav_change(start=case_2, end=result)
    total = nav_change(start=initial, end=result)
    assert (step.nav_change, step.external_flow, step.investment_pnl) == (Decimal("300"), Decimal("300"), Decimal("0"))
    assert (total.nav_change, total.external_flow, total.investment_pnl) == (Decimal("398"), Decimal("300"), Decimal("98"))


def test_case_4_duplicate_fill_changes_nothing():
    """CASE 4. 입력: CASE 1의 같은 체결 E-1을 다시 받음.
    출력: DUPLICATE. 현금 이벤트를 만들지 않는다 (현금 장부 그대로). 실제 +10주, 현금 998, NAV 1,998 유지."""
    account = after_buy()

    posting = record_etf_fill(account, make_fill())

    assert (posting.fill_verdict, posting.outcome) == (FillVerdict.DUPLICATE, PostingOutcome.NO_CHANGE)
    assert posting.cash_events == ()
    assert posting.account.cash == account.cash
    assert account_position(posting.account, as_of=V1, information_cutoff=V1) == {ETF: 10}
    assert nav(posting.account, "100", V1).nav == Decimal("1998")


@pytest.mark.parametrize("changes", [{"quantity": 11}, {"price": "101"}])
def test_case_5_conflicting_fill_blocks_position_cash_and_nav(changes):
    """CASE 5. 입력: CASE 1 뒤 같은 체결 키로 수량 11 또는 가격 101인 기록.
    출력: CONFLICT. 현금 이벤트를 만들지 않고 충돌 증거를 보관한다. 기존 반영 기록과 현금 장부는 그대로다.
    통합 포지션·현금·NAV 계산은 모두 FillIntegrityError (조용히 고치지 않음)."""
    account = after_buy()

    posting = record_etf_fill(account, make_fill(**changes))

    assert (posting.fill_verdict, posting.outcome, posting.reasons) == (FillVerdict.CONFLICT, PostingOutcome.BLOCKED, ("FILL_CONFLICT",))
    assert posting.cash_events == ()
    assert posting.account.cash == account.cash
    assert posting.account.fills.applied == account.fills.applied
    assert posting.account.fills.conflicts[0].incoming == make_fill(**changes)
    with pytest.raises(FillIntegrityError):
        account_position(posting.account, as_of=V1, information_cutoff=V1)
    with pytest.raises(FillIntegrityError):
        account_cash(posting.account, currency="USD", as_of=V1, information_cutoff=V1)
    with pytest.raises(FillIntegrityError):
        nav(posting.account, "100", V1)


def test_case_6a_missing_commission_event_is_detected():
    """CASE 6 (a). 입력: 체결 장부에는 E-1이 있고, 따로 받은 현금 장부에는 매매대금만 있고 수수료 이벤트가 없음.
    출력: 대조 결과 MISSING(COMMISSION). 통합 현금·NAV는 FillCashReconciliationError로 확정하지 않는다."""
    consideration, _ = fill_cash_events(make_fill(), etf_spec())
    account = external_account(consideration)

    report = reconcile_fill_cash(account.fills, account.cash)

    assert not report.complete
    assert [(issue.kind, issue.event_kind) for issue in report.issues] == [(FillCashIssueKind.MISSING, K.COMMISSION)]
    with pytest.raises(FillCashReconciliationError):
        account_cash(account, currency="USD", as_of=V1, information_cutoff=V1)
    with pytest.raises(FillCashReconciliationError):
        nav(account, "100", V1)


def test_case_6b_commission_twice_is_not_deducted_twice():
    """CASE 6 (b). 입력: (i) 같은 수수료 이벤트(같은 ID)를 다시 받음, (ii) 같은 체결의 수수료가 다른 ID로 옴.
    출력: (i) DUPLICATE, 현금 998·NAV 1,998 그대로 (996·1,996이 아님). (ii) CONFLICT로 보관되고 NAV는 CashIntegrityError."""
    account = after_buy()
    _, commission = fill_cash_events(make_fill(), etf_spec())

    resent = record_cash_event(account, commission)
    other_id = record_cash_event(account, dataclasses.replace(commission, cash_event_id="BROKER-FEE-1"))

    assert resent.application.verdict is CashVerdict.DUPLICATE
    assert nav(resent.account, "100", V1).nav == Decimal("1998")
    assert other_id.application.verdict is CashVerdict.CONFLICT
    with pytest.raises(CashIntegrityError):
        nav(other_id.account, "100", V1)


@pytest.mark.parametrize(
    ("consideration", "commission"),
    [("-990", "-2"), ("-1001", "-1"), ("1000", "-2")],
)
def test_case_6c_amount_mismatch_is_detected_even_when_totals_agree(consideration, commission):
    """CASE 6 (c). 입력: 따로 받은 현금 장부의 E-1 이벤트 금액이 (a) 매매대금 −990, (b) 매매대금 −1,001 + 수수료 −1
    (합계 −1,002는 맞음), (c) 매수인데 매매대금 +1,000 (부호 혼동).
    출력: 모두 MISMATCHED (amount). 합계가 같아도 이벤트별로 체결 수량·가격·수수료와 맞지 않으면 완전하다고 보지 않는다."""
    expected_consideration, expected_commission = fill_cash_events(make_fill(), etf_spec())
    account = external_account(
        dataclasses.replace(expected_consideration, amount=Decimal(consideration)),
        dataclasses.replace(expected_commission, amount=Decimal(commission)),
    )

    report = reconcile_fill_cash(account.fills, account.cash)

    assert report.issues
    assert all(issue.kind is FillCashIssueKind.MISMATCHED and issue.differing_fields == ("amount",) for issue in report.issues)
    with pytest.raises(FillCashReconciliationError):
        nav(account, "100", V1)


def test_case_6d_consideration_recorded_again_under_another_id_is_a_conflict():
    """CASE 6 (d). 입력: CASE 1 뒤 같은 체결의 매매대금 −1,000이 다른 ID(BROKER-TRADE-1)로 다시 옴.
    출력: CONFLICT로 보관되고 더하지 않는다 (현금 −2이 되지 않음). 통합 현금·NAV는 CashIntegrityError."""
    account = after_buy()
    consideration, _ = fill_cash_events(make_fill(), etf_spec())

    posting = record_cash_event(account, dataclasses.replace(consideration, cash_event_id="BROKER-TRADE-1"))

    assert posting.application.verdict is CashVerdict.CONFLICT
    with pytest.raises(CashIntegrityError):
        account_cash(posting.account, currency="USD", as_of=V1, information_cutoff=V1)


def test_cash_event_without_an_applied_fill_is_unexpected():
    """입력: 체결 장부에 없는 체결(E-7)을 원인으로 하는 매매대금 이벤트가 현금 장부에 있음.
    출력: 대조 결과 UNEXPECTED. 통합 NAV는 확정하지 않는다."""
    orphan, _ = fill_cash_events(make_fill(fill_id="E-7"), etf_spec())
    account = external_account(*fill_cash_events(make_fill(), etf_spec()), orphan)

    report = reconcile_fill_cash(account.fills, account.cash)

    assert [(issue.kind, issue.event_kind) for issue in report.issues] == [(FillCashIssueKind.UNEXPECTED, K.TRADE_CONSIDERATION)]
    with pytest.raises(FillCashReconciliationError):
        nav(account, "100", V1)


def test_matching_external_events_reconcile_completely():
    """입력: 따로 받은 현금 장부의 E-1 이벤트가 기대 이벤트와 ID·원인·종류·금액·시각까지 같음.
    출력: 대조 완전 (기대 2건, 일치 2건, 문제 없음). NAV 1,998."""
    account = external_account(*fill_cash_events(make_fill(), etf_spec()))

    report = reconcile_fill_cash(account.fills, account.cash)

    assert report.complete
    assert (report.expected_events, report.matched_events) == (2, 2)
    assert nav(account, "100", V1).nav == Decimal("1998")


def test_commission_with_a_positive_amount_cannot_be_recorded():
    """입력: 수수료 이벤트 금액 +2 (부호 혼동).
    출력: ValueError (수수료 현금 이벤트는 ≤ 0)."""
    _, commission = fill_cash_events(make_fill(), etf_spec())
    with pytest.raises(ValueError):
        dataclasses.replace(commission, amount=Decimal("2"))


def test_sell_moves_cash_in_and_keeps_nav_identity():
    """입력: CASE 1 뒤 −4주 매도 @ 110 (수수료 1), V2 평가가격 110.
    출력: 실제 6주, 매매대금 +440, 수수료 합 −3, 현금 1,437, 평가액 660, NAV 2,097. 초기 대비 투자 손익 +97
    (V0→V1 −2, V1→V2 보유 10 × (110 − 100) + 체결 −4 × (110 − 110) − 1)."""
    account = record_etf_fill(after_buy(), make_fill(fill_id="E-2", quantity=-4, price="110", fill_at=SELL_AT, fee="1")).account

    result = nav(account, "110", V2)

    assert account_position(account, as_of=V2, information_cutoff=V2) == {ETF: 6}
    assert (result.cash.trade_consideration, result.cash.commission) == (Decimal("-560"), Decimal("-3"))
    assert (result.cash.balance, result.market_value, result.nav) == (Decimal("1437"), Decimal("660"), Decimal("2097"))
    assert nav_change(start=nav(account, None, V0), end=result).investment_pnl == Decimal("97")


def test_price_fall_is_a_loss():
    """입력: CASE 1 뒤 V2 평가가격 90.
    출력: NAV 1,898. 초기 대비 투자 손익 −102 = 10 × (90 − 100) − 2."""
    account = after_buy()

    result = nav(account, "90", V2)

    assert result.nav == Decimal("1898")
    assert nav_change(start=nav(account, None, V0), end=result).investment_pnl == Decimal("-102")


def test_negative_cash_needs_no_new_rule():
    """입력: 입금 500, 10주 매수 @ 100 (수수료 2), V1 평가가격 100.
    출력: 현금 −502, NAV 498. 음수 현금을 막는 규칙을 만들지 않는다 (사용 가능 현금 검사는 범위 밖)."""
    result = nav(after_buy(deposit="500"), "100", V1)

    assert (result.cash.balance, result.nav) == (Decimal("-502"), Decimal("498"))


def test_holding_not_on_lot_is_valued_without_rounding():
    """입력: lot 10 ETF, 검증된 기준 15주, 시뮬레이션 매수 +10주 @ 100 (수수료 2), V1 평가가격 100.
    출력: 실제 25주, 평가액 2,500, NAV 3,498. lot 배수로 반올림하지 않는다 (ADR-0013 R13-1)."""
    account = after_buy(spec=etf_spec(lot_size=10), base=baseline(15))

    result = nav(account, "100", V1)

    assert account_position(account, as_of=V1, information_cutoff=V1) == {ETF: 25}
    assert (result.market_value, result.nav) == (Decimal("2500"), Decimal("3498"))


def test_future_fill_price_and_valuation_boundaries():
    """입력: (a) 매수 체결 14:30, V1 평가, information_cutoff 14:00, (b) 정보 기준 시각 뒤에 이용 가능해진 평가가격,
    (c) 매수 전 시각 V0의 평가.
    출력: (a)·(b) ValueError (미래 체결·가격으로 평가하지 않음). (c) 체결이 들어 있는 장부로도 V0 NAV는 2,000 (뒤의 체결 제외)."""
    account = after_buy()

    with pytest.raises(ValueError, match="ETF fill"):
        nav(account, None, V1, cutoff=datetime(2026, 10, 20, 14, 0, tzinfo=UTC))
    with pytest.raises(ValueError, match="became available"):
        account_nav(
            account,
            prices={ETF: price("100", V1, available=V1 - timedelta(minutes=5))},
            currency="USD",
            valuation_at=V1,
            information_cutoff=V1 - timedelta(minutes=10),
        )
    assert nav(account, None, V0).nav == Decimal("2000")


def test_other_currency_is_not_summed():
    """입력: (a) USD ETF 체결의 수수료 통화가 KRW, (b) KRW ETF 5주를 매수한 계좌의 USD NAV.
    출력: (a) ValueError. (b) NOT_COMPUTABLE(FX_MISSING: KRW), NAV None (환율 없이 더하지 않음, X8-8)."""
    with pytest.raises(ValueError, match="fee_currency"):
        record_etf_fill(opened(), make_fill(fee_currency="KRW"))

    krw = etf_spec(unit_id="ETF.KR1", currency="KRW", lot_size=1)
    account = record_etf_fill(
        opened(spec=krw, base=baseline(unit_id="ETF.KR1")),
        make_fill(unit_id="ETF.KR1", quantity=5, price="30000", fee="1000", fee_currency="KRW"),
    ).account

    result = nav(account, "30000", V1, unit_id="ETF.KR1")

    assert result.status is NavStatus.NOT_COMPUTABLE
    assert result.fx_missing_currencies == ("KRW",)
    assert result.nav is None


def test_fills_at_or_before_the_baseline_time_are_not_posted():
    """입력: 기준 시각 T0과 같거나 이른 체결.
    출력: ValueError. 기준 포지션에 이미 든 체결과 시작 현금의 관계(검증된 기초 잔액)는 정하지 않았으므로 통합 계좌에 넣지 않는다."""
    for fill_at in (T0, T0 - timedelta(hours=1)):
        with pytest.raises(ValueError, match="baseline time"):
            record_etf_fill(opened(), make_fill(fill_at=fill_at))


def test_account_parts_must_belong_together():
    """입력: (a) 다른 계좌의 현금 장부, (b) 기준 포지션과 체결 장부의 종목이 다름.
    출력: 모두 ValueError."""
    account = after_buy()

    with pytest.raises(ValueError, match="account"):
        EtfAccount(baseline=account.baseline, fills=account.fills, cash=CashLedger.empty(account_id="A2"))
    with pytest.raises(ValueError, match="units"):
        EtfAccount(baseline=baseline(unit_id="ETF.US9"), fills=account.fills, cash=account.cash)


def test_computed_nav_is_not_an_operational_confirmation():
    """입력: CASE 1의 NAV.
    출력: COMPUTED이며 운영용 확정에 남은 조건(NAV_OPEN_POLICIES)을 함께 싣는다. CONFIRMED 상태는 없다."""
    result = nav(after_buy(), "100", V1)

    assert result.status is NavStatus.COMPUTED
    assert result.open_policies == NAV_OPEN_POLICIES
    assert "CONFIRMED" not in NavStatus.__members__


def test_nav_change_needs_two_computed_navs_in_time_order():
    """입력: (a) 평가가격이 없어 NOT_COMPUTABLE인 시작 NAV, (b) 끝이 시작보다 이른 두 NAV.
    출력: 모두 ValueError (계산되지 않은 NAV로 투자 손익을 만들지 않음)."""
    account = after_buy()

    with pytest.raises(ValueError):
        nav_change(start=nav(account, None, V1), end=nav(account, "110", V2))
    with pytest.raises(ValueError):
        nav_change(start=nav(account, "110", V2), end=nav(account, "100", V1))


@pytest.mark.parametrize("fill_at", [T0, T0 - timedelta(hours=1)])
def test_resent_fill_with_an_earlier_time_is_a_conflict(fill_at):
    """입력: CASE 1 뒤 같은 체결 키 E-1인데 체결 시각만 기준 시각 T0 또는 그 1시간 전으로 바뀐 기록 (검토 MEDIUM-1).
    출력: CONFLICT (differing_fields = ("fill_at",)). 충돌 증거를 보관하고 통합 포지션·NAV는 FillIntegrityError.
    기준 시각 검사는 새 체결에만 쓰며, 이미 있는 키의 재수신을 일반 오류로 넘기지 않는다 (R9-9, §6.4a)."""
    posting = record_etf_fill(after_buy(), make_fill(fill_at=fill_at))

    assert (posting.fill_verdict, posting.outcome) == (FillVerdict.CONFLICT, PostingOutcome.BLOCKED)
    assert posting.account.fills.conflicts[0].differing_fields == ("fill_at",)
    with pytest.raises(FillIntegrityError):
        account_position(posting.account, as_of=V1, information_cutoff=V1)
    with pytest.raises(FillIntegrityError):
        nav(posting.account, "100", V1)


def test_external_flow_citing_a_fill_cause_is_unexpected():
    """입력: CASE 1 뒤 체결 E-1의 원인 참조를 단 외부 흐름 −2 (BROKER-FEE-1, 검토 MEDIUM-2).
    출력: 대조 결과 UNEXPECTED(EXTERNAL_FLOW). NAV는 확정하지 않는다 (수수료를 두 번 빼 1,996이 되지 않음, F8-1 원칙)."""
    fee_as_flow = CashEvent(
        account_id="A1",
        cash_event_id="BROKER-FEE-1",
        kind=K.EXTERNAL_FLOW,
        cause_ref=fill_cause_ref(make_fill().key),
        currency="USD",
        amount="-2",
        occurred_at=BUY_AT,
        confirmation=CashEventConfirmation.CONFIRMED,
    )
    account = record_cash_event(after_buy(), fee_as_flow).account

    report = reconcile_fill_cash(account.fills, account.cash)

    assert [(issue.kind, issue.event_kind) for issue in report.issues] == [(FillCashIssueKind.UNEXPECTED, K.EXTERNAL_FLOW)]
    with pytest.raises(FillCashReconciliationError):
        nav(account, "100", V1)


@pytest.mark.parametrize(
    ("changes", "differing"),
    [
        ({"cash_event_id": "BROKER-TRADE-1"}, ("cash_event_id",)),
        ({"occurred_at": BUY_AT + timedelta(minutes=1)}, ("occurred_at",)),
        ({"currency": "KRW"}, ("currency",)),
    ],
)
def test_external_event_must_match_id_time_and_currency(changes, differing):
    """입력: 따로 받은 현금 장부의 E-1 매매대금이 원인·종류·금액은 맞지만 (a) ID, (b) 발생 시각, (c) 통화가 기대와 다름.
    출력: MISMATCHED와 다른 필드. 외부 이벤트는 금액뿐 아니라 ID·시각·통화까지 기대 이벤트와 같아야 한다."""
    consideration, commission = fill_cash_events(make_fill(), etf_spec())
    account = external_account(dataclasses.replace(consideration, **changes), commission)

    report = reconcile_fill_cash(account.fills, account.cash)

    assert [(issue.kind, issue.differing_fields) for issue in report.issues] == [(FillCashIssueKind.MISMATCHED, differing)]


def test_externally_assembled_account_with_a_pre_baseline_fill_is_refused():
    """입력: 직접 만든 계좌의 체결 장부에 기준 시각 1시간 전 체결과 그 현금 이벤트가 있음 (record_etf_fill을 거치지 않음).
    출력: ValueError. 기준에 이미 든 체결인지 알 수 없으므로 포지션과 현금을 함께 계산하지 않는다 (Q13-2)."""
    early = make_fill(fill_at=T0 - timedelta(hours=1))
    account = external_account(*fill_cash_events(early, etf_spec()), fills=(early,))

    with pytest.raises(ValueError, match="baseline time"):
        nav(account, "100", V1)


@pytest.mark.parametrize("bad_price", ["0", "-1"])
def test_etf_prices_must_be_positive_at_fill_cash_and_valuation(bad_price):
    """검사 A. 입력: ETF 체결 가격 또는 평가가격이 0 또는 음수.
    출력: 체결 반영(record_etf_fill), 현금 이벤트 생성(fill_cash_events), 평가(account_nav, position_market_value)가 모두
    ValueError. 계좌는 바뀌지 않는다 (Slice 4 사용자 결정: ETF 가격 > 0. 선물 가격 규칙은 그대로)."""
    account = opened()
    holdings = PositionBaseline(account_id="A1", as_of=V1, quantities={ETF: 10}, verification_ref="fixture:verified")

    with pytest.raises(ValueError, match="positive"):
        record_etf_fill(account, make_fill(price=bad_price))
    with pytest.raises(ValueError, match="positive"):
        fill_cash_events(make_fill(price=bad_price), etf_spec())
    with pytest.raises(ValueError, match="positive"):
        nav(after_buy(), bad_price, V1)
    with pytest.raises(ValueError, match="positive"):
        position_market_value(holdings=holdings, spec=etf_spec(), price=price(bad_price, V1), valuation_at=V1, information_cutoff=V1)
    assert account.fills.applied == () and len(account.cash.applied) == 1


def test_posting_outcome_is_separate_from_the_fill_verdict():
    """검사 B. 입력: (a) 새 체결 E-1, (b) 같은 체결 재수신, (c) 같은 키·다른 수량.
    출력: 체결 판정과 계좌 전체 반영 결과를 따로 돌려준다. (a) APPLIED·POSTED, (b) DUPLICATE·NO_CHANGE,
    (c) CONFLICT·BLOCKED(FILL_CONFLICT)."""
    posted = record_etf_fill(opened(), make_fill())
    resent = record_etf_fill(posted.account, make_fill())
    conflicting = record_etf_fill(posted.account, make_fill(quantity=11))

    assert (posted.fill_verdict, posted.outcome, posted.reasons) == (FillVerdict.APPLIED, PostingOutcome.POSTED, ())
    assert (resent.fill_verdict, resent.outcome, resent.reasons) == (FillVerdict.DUPLICATE, PostingOutcome.NO_CHANGE, ())
    assert (conflicting.fill_verdict, conflicting.outcome, conflicting.reasons) == (
        FillVerdict.CONFLICT,
        PostingOutcome.BLOCKED,
        ("FILL_CONFLICT",),
    )


def test_applied_fill_with_a_conflicting_cash_event_is_not_reported_as_success():
    """검사 B. 입력: 같은 체결의 매매대금이 다른 ID(BROKER-TRADE-1)로 먼저 기록된 계좌에 체결 E-1을 반영하고, 같은 체결을 한 번 더 보냄.
    출력: 체결 판정은 APPLIED지만 계좌 반영 결과는 BLOCKED(CASH_CONFLICT). 현금 장부에 충돌 증거(기존 기록, 반영하지 않은
    파생 기록)가 남고, 매매대금은 −1,000 한 번, 수수료는 −2 한 번만 들어 있다. NAV는 CashIntegrityError로 막힌다.
    재전송은 DUPLICATE·현금 장부 그대로이며 계좌는 여전히 BLOCKED다."""
    derived_consideration, _ = fill_cash_events(make_fill(), etf_spec())
    account = record_cash_event(opened(), dataclasses.replace(derived_consideration, cash_event_id="BROKER-TRADE-1")).account

    posting = record_etf_fill(account, make_fill())

    assert (posting.fill_verdict, posting.outcome, posting.reasons) == (FillVerdict.APPLIED, PostingOutcome.BLOCKED, ("CASH_CONFLICT",))
    assert posting.cash_verdicts == (CashVerdict.CONFLICT, CashVerdict.APPLIED)
    conflict = posting.account.cash.conflicts[0]
    assert (conflict.existing.cash_event_id, conflict.incoming) == ("BROKER-TRADE-1", derived_consideration)
    amounts = sorted((event.kind.value, event.amount) for event in posting.account.cash.applied if event.kind is not K.EXTERNAL_FLOW)
    assert amounts == [("COMMISSION", Decimal("-2")), ("TRADE_CONSIDERATION", Decimal("-1000"))]
    with pytest.raises(CashIntegrityError):
        nav(posting.account, "100", V1)

    again = record_etf_fill(posting.account, make_fill())

    assert (again.fill_verdict, again.outcome, again.cash_events) == (FillVerdict.DUPLICATE, PostingOutcome.BLOCKED, ())
    assert again.account.cash == posting.account.cash


def test_posting_is_blocked_when_fill_and_cash_do_not_reconcile():
    """검사 B. 입력: 체결 E-1의 원인 참조를 단 외부 흐름이 먼저 기록된 계좌에 E-1을 반영.
    출력: 장부 충돌은 없지만 대조가 완전하지 않으므로 계좌 반영 결과는 BLOCKED(FILL_CASH_NOT_RECONCILED)이고 NAV는 막힌다."""
    fee_as_flow = CashEvent(
        account_id="A1",
        cash_event_id="BROKER-FEE-1",
        kind=K.EXTERNAL_FLOW,
        cause_ref=fill_cause_ref(make_fill().key),
        currency="USD",
        amount="-2",
        occurred_at=BUY_AT,
        confirmation=CashEventConfirmation.CONFIRMED,
    )
    account = record_cash_event(opened(), fee_as_flow).account

    posting = record_etf_fill(account, make_fill())

    assert (posting.fill_verdict, posting.outcome, posting.reasons) == (
        FillVerdict.APPLIED,
        PostingOutcome.BLOCKED,
        ("FILL_CASH_NOT_RECONCILED",),
    )
    with pytest.raises(FillCashReconciliationError):
        nav(posting.account, "100", V1)
