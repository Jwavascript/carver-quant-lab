"""P0-03B Slice 3: ETF 평가액과 단일 통화 NAV (ADR-0008 §6.2·§6.3·§6.4, AT-0008-3·AT-0008-9, X8-1·X8-2·X8-3·X8-7·X8-8,
ADR-0006 I6-6, ADR-0013 R13-1).

NAV는 현금 장부의 단일 통화 잔액과 명시 평가가격으로 계산한 ETF 평가액의 합이다. 기대값 1,998·2,098·2,398 USD와
AT-0008-3의 1,997 USD는 저장소 밖 독립 산술(Fraction)로 먼저 확인했다. 가상 ETF이며 시장 사실을 주장하지 않는다.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from carver_quant.lab.accounting.cash_ledger import CashIntegrityError, CashLedger, apply_cash_event
from carver_quant.lab.accounting.valuation import NAV_OPEN_POLICIES, NavStatus, calculate_nav, position_market_value
from carver_quant.lab.domain.cash import CashEvent, CashEventConfirmation, CashEventKind
from carver_quant.lab.domain.records import EtfSpec, PositionBaseline, ValuationPrice

UTC = timezone.utc
K = CashEventKind
ETF = "ETF.US1"
ETF_KRW = "ETF.KR1"
FUND_AT = datetime(2026, 10, 19, 13, 0, tzinfo=UTC)
V0 = datetime(2026, 10, 19, 21, 0, tzinfo=UTC)
BUY_AT = datetime(2026, 10, 20, 14, 30, tzinfo=UTC)
V1 = datetime(2026, 10, 20, 21, 0, tzinfo=UTC)
V2 = datetime(2026, 10, 21, 21, 0, tzinfo=UTC)
DEPOSIT_AT = datetime(2026, 10, 22, 15, 0, tzinfo=UTC)
V3 = datetime(2026, 10, 22, 21, 0, tzinfo=UTC)
FILL_REF = "fill:A1:BRK:E-1"


def make_event(event_id, kind, amount, occurred_at, cause_ref, currency="USD"):
    return CashEvent(
        account_id="A1",
        cash_event_id=event_id,
        kind=kind,
        cause_ref=cause_ref,
        currency=currency,
        amount=amount,
        occurred_at=occurred_at,
        confirmation=CashEventConfirmation.CONFIRMED,
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


def etf_spec(unit_id=ETF, currency="USD", lot_size=1):
    return EtfSpec(unit_id=unit_id, currency=currency, lot_size=lot_size)


def holdings(quantities, as_of, account_id="A1"):
    return PositionBaseline(account_id=account_id, as_of=as_of, quantities=quantities, verification_ref="fixture:verified")


def price(value, valuation_at, unit_id=ETF, available=None):
    return ValuationPrice(
        contract_id=unit_id,
        price=value,
        valuation_at=valuation_at,
        data_available_at=available or valuation_at - timedelta(minutes=30),
        source_ref="fixture:close",
    )


def nav(ledger, quantity, value, valuation_at, cutoff=None):
    """ETF.US1 한 종목 계좌의 NAV. value가 None이면 평가가격을 주지 않는다."""
    prices = {} if value is None else {ETF: price(value, valuation_at)}
    return calculate_nav(
        ledger=ledger,
        holdings=holdings({ETF: quantity}, valuation_at),
        specs=(etf_spec(),),
        prices=prices,
        currency="USD",
        valuation_at=valuation_at,
        information_cutoff=cutoff or valuation_at,
    )


def test_initial_nav_is_the_deposit():
    """입력: 입금 2,000 USD, ETF 0주, V0, 평가가격 없음.
    출력: COMPUTED, NAV 2,000. 보유가 0인 종목은 평가가격이 없어도 된다."""
    result = nav(ledger_with(funding()), 0, None, V0)

    assert result.status is NavStatus.COMPUTED
    assert (result.cash.balance, result.market_value, result.nav) == (Decimal("2000"), Decimal("0"), Decimal("2000"))


def test_case_1_purchase_exchanges_cash_for_the_etf():
    """CASE 1. 입력: 입금 2,000, 10주 매수 @ 100 (대금 −1,000, 수수료 −2), V1 평가가격 100.
    출력: 현금 998, 평가액 1,000, NAV 1,998. 초기 NAV 2,000 대비 −2 = 체결분 10 × (100 − 100) − 수수료 2.
    매수 대금을 손실로 보면 NAV가 998이 되므로 틀린 값이다 (X8-1, ADR-0008 §6.3).
    COMPUTED는 이 Slice의 명시 입력으로 계산했다는 뜻이며, 운영용 확정에 남은 정책을 함께 돌려준다."""
    ledger = ledger_with(funding(), consideration(), commission())

    result = nav(ledger, 10, "100", V1)

    assert result.status is NavStatus.COMPUTED
    assert (result.cash.balance, result.market_value, result.nav) == (Decimal("998"), Decimal("1000"), Decimal("1998"))
    assert result.nav - Decimal("2000") == Decimal("-2")
    assert result.open_policies == NAV_OPEN_POLICIES
    assert result.reasons == ()


def test_case_2_price_rise():
    """CASE 2. 입력: CASE 1 뒤 거래 없음, V2 평가가격 110.
    출력: 현금 998, 평가액 1,100, NAV 2,098. V0~V2 외부 흐름 0이므로 초기 NAV 대비 투자 손익 = +98.
    분해: 가격 손익 +100 (평가액 1,100 + 매매대금 −1,000 = 10 × (110 − 100)), 수수료 −2."""
    ledger = ledger_with(funding(), consideration(), commission())
    initial = nav(ledger, 0, None, V0)

    result = nav(ledger, 10, "110", V2)

    assert (result.cash.balance, result.market_value, result.nav) == (Decimal("998"), Decimal("1100"), Decimal("2098"))
    flow = result.cash.external_flow - initial.cash.external_flow
    assert flow == 0
    assert result.nav - initial.nav - flow == Decimal("98")
    assert result.market_value + result.cash.trade_consideration == Decimal("100")
    assert result.cash.commission == Decimal("-2")


def test_case_3_deposit_is_not_investment_pnl():
    """CASE 3. 입력: CASE 2 뒤 외부 입금 300, V3 평가가격 110.
    출력: 현금 1,298, 평가액 1,100, NAV 2,398. NAV 증가 +300은 모두 외부 흐름이며 투자 손익 = ΔNAV − 외부 흐름 = 0
    (ADR-0008 §6.4, X8-7, AT-0008-9)."""
    ledger = ledger_with(funding(), consideration(), commission(), deposit())
    before = nav(ledger, 10, "110", V2)

    after = nav(ledger, 10, "110", V3)

    assert (after.cash.balance, after.market_value, after.nav) == (Decimal("1298"), Decimal("1100"), Decimal("2398"))
    flow = after.cash.external_flow - before.cash.external_flow
    assert (after.nav - before.nav, flow) == (Decimal("300"), Decimal("300"))
    assert after.nav - before.nav - flow == 0


def test_at_0008_3_usd_equity():
    """ADR-0008 AT-0008-3 (USD 부분). 입력: USD 현금 2,000, 100주 매수 @ 10.02 (대금 −1,002.00), 수수료 1.00, 평가가격 10.00.
    출력: 현금 997.00, 평가액 1,000.00, USD 순자산 1,997.00 (−3.00 = 체결분 100 × (10.00 − 10.02) − 수수료 1.00).
    환율 1,400을 쓰는 KRW 기준 NAV는 FX가 범위 밖이므로 계산하지 않는다."""
    ledger = ledger_with(
        funding(),
        make_event("CE-1", K.TRADE_CONSIDERATION, "-1002.00", BUY_AT, FILL_REF),
        make_event("CE-2", K.COMMISSION, "-1.00", BUY_AT, FILL_REF),
    )

    result = nav(ledger, 100, "10.00", V1)

    assert (result.cash.balance, result.market_value, result.nav) == (Decimal("997"), Decimal("1000"), Decimal("1997"))


def test_fee_is_deducted_once_even_when_resent():
    """입력: CASE 1에 수수료 CE-2를 한 번 더 받음 (DUPLICATE).
    출력: NAV 1,998 (1,996이 아님). 수수료는 현금 장부에서 한 번 빠지고 NAV에서 다시 빼지 않는다 (X8-2, F8-2 원칙)."""
    ledger = ledger_with(funding(), consideration(), commission(), commission())

    result = nav(ledger, 10, "100", V1)

    assert result.cash.commission == Decimal("-2")
    assert result.nav == Decimal("1998")


def test_missing_price_leaves_nav_not_computable():
    """입력: CASE 1 장부, 검증된 10주 보유, 평가가격 없음.
    출력: NOT_COMPUTABLE(VALUATION_PRICE_MISSING). nav와 평가액 합계는 None이다 (0이 아님). 이전 가격·체결가로 대신하지 않는다.
    현금 잔액 998은 그대로 기록한다."""
    ledger = ledger_with(funding(), consideration(), commission())

    result = nav(ledger, 10, None, V1)

    assert result.status is NavStatus.NOT_COMPUTABLE
    assert result.reasons == ("VALUATION_PRICE_MISSING",)
    assert result.unpriced_unit_ids == (ETF,)
    assert (result.nav, result.market_value) == (None, None)
    assert result.open_policies == ()
    assert result.cash.balance == Decimal("998")


def test_actual_zero_nav_is_computed():
    """입력: 입금 100, 출금 −100, ETF 없음 (사양·보유 모두 비어 있음).
    출력: COMPUTED, NAV 0. 계산 불가(None)와 실제 NAV 0을 구분한다."""
    ledger = ledger_with(
        make_event("CE-0", K.EXTERNAL_FLOW, "100", FUND_AT, "transfer:T-0"),
        make_event("CE-1", K.EXTERNAL_FLOW, "-100", BUY_AT, "transfer:T-1"),
    )

    result = calculate_nav(
        ledger=ledger, holdings=holdings({}, V1), specs=(), prices={}, currency="USD", valuation_at=V1, information_cutoff=V1
    )

    assert result.status is NavStatus.COMPUTED
    assert result.nav is not None
    assert result.nav == 0


@pytest.mark.parametrize("available", [V1 + timedelta(minutes=10), V1 - timedelta(minutes=10)])
def test_price_available_after_information_cutoff_is_rejected(available):
    """입력: V1 평가, information_cutoff = V1 − 20분, 평가가격 이용 가능 시각 V1 + 10분 또는 V1 − 10분.
    출력: ValueError. 정보 기준 시각 뒤에 이용 가능해진 가격은 쓰지 않는다 (V-1)."""
    ledger = ledger_with(funding(), consideration(), commission())

    with pytest.raises(ValueError, match="became available"):
        calculate_nav(
            ledger=ledger,
            holdings=holdings({ETF: 10}, V1),
            specs=(etf_spec(),),
            prices={ETF: price("100", V1, available=available)},
            currency="USD",
            valuation_at=V1,
            information_cutoff=V1 - timedelta(minutes=20),
        )


def test_price_for_another_valuation_time_is_rejected():
    """입력: V2 평가에 V1 평가가격 (마지막 가격).
    출력: ValueError. 평가가격을 자동으로 고르거나 이전 값으로 채우지 않는다."""
    ledger = ledger_with(funding(), consideration(), commission())

    with pytest.raises(ValueError, match="valuation time"):
        calculate_nav(
            ledger=ledger,
            holdings=holdings({ETF: 10}, V2),
            specs=(etf_spec(),),
            prices={ETF: price("100", V1)},
            currency="USD",
            valuation_at=V2,
            information_cutoff=V2,
        )


def test_cash_event_after_information_cutoff_is_rejected_in_nav():
    """입력: 매수 이벤트 14:30, V1 평가, information_cutoff 14:00 (보유 0주라 가격 검사는 없음).
    출력: ValueError. 정보 기준 시각 뒤의 현금 이벤트로 평가하지 않는다."""
    ledger = ledger_with(funding(), consideration(), commission())

    with pytest.raises(ValueError, match="cash event"):
        nav(ledger, 0, None, V1, cutoff=datetime(2026, 10, 20, 14, 0, tzinfo=UTC))


def test_other_currency_cash_is_never_summed():
    """입력: (a) USD 이벤트와 KRW 입금 1,000,000이 든 장부, (b) 같은 KRW 금액이 입금 뒤 출금되어 KRW 순자산 0.
    출력: (a) NOT_COMPUTABLE(FX_MISSING: KRW), NAV None. 1,000,998 같은 합을 만들지 않고 환율을 1로 쓰지 않는다 (X8-3, X8-8).
    (b) KRW 순자산이 0이면 환율이 필요 없으므로 USD NAV 1,998 (ADR-0008 §6.2)."""
    krw_in = make_event("CE-K", K.EXTERNAL_FLOW, "1000000", FUND_AT, "transfer:T-K", currency="KRW")
    krw_out = make_event("CE-L", K.EXTERNAL_FLOW, "-1000000", BUY_AT, "transfer:T-L", currency="KRW")

    with_krw = nav(ledger_with(funding(), consideration(), commission(), krw_in), 10, "100", V1)
    netted = nav(ledger_with(funding(), consideration(), commission(), krw_in, krw_out), 10, "100", V1)

    assert with_krw.status is NavStatus.NOT_COMPUTABLE
    assert with_krw.reasons == ("FX_MISSING",)
    assert with_krw.fx_missing_currencies == ("KRW",)
    assert with_krw.nav is None
    assert netted.status is NavStatus.COMPUTED
    assert netted.nav == Decimal("1998")


def test_other_currency_holding_is_never_summed():
    """입력: USD 장부, KRW ETF(ETF.KR1) 5주 보유 (KRW 평가가격 30,000 있음).
    출력: NOT_COMPUTABLE(FX_MISSING: KRW), NAV None. KRW 평가액 150,000을 USD에 더하지 않는다 (X8-8)."""
    ledger = ledger_with(funding())

    result = calculate_nav(
        ledger=ledger,
        holdings=holdings({ETF_KRW: 5}, V1),
        specs=(etf_spec(unit_id=ETF_KRW, currency="KRW", lot_size=10),),
        prices={ETF_KRW: price("30000", V1, unit_id=ETF_KRW)},
        currency="USD",
        valuation_at=V1,
        information_cutoff=V1,
    )

    assert result.status is NavStatus.NOT_COMPUTABLE
    assert result.reasons == ("FX_MISSING",)
    assert result.fx_missing_currencies == ("KRW",)
    assert result.nav is None


def test_verified_holding_not_on_lot_is_valued_as_is():
    """입력: lot 10 ETF, 검증된 보유 15주, 평가가격 100, 현금 0.
    출력: 평가액 1,500, NAV 1,500. 10주(1,000)나 20주(2,000)로 반올림하지 않는다 (ADR-0013 R13-1)."""
    result = calculate_nav(
        ledger=ledger_with(),
        holdings=holdings({ETF: 15}, V1),
        specs=(etf_spec(lot_size=10),),
        prices={ETF: price("100", V1)},
        currency="USD",
        valuation_at=V1,
        information_cutoff=V1,
    )

    assert (result.market_value, result.nav) == (Decimal("1500"), Decimal("1500"))
    assert result.market_values[0].quantity == 15


def test_short_holding_and_negative_cash_need_no_new_rule():
    """입력: (a) 입금 1,000, 보유 −5주, 평가가격 110. (b) 입금 2,000, 30주 매수 @ 100 (대금 −3,000, 수수료 −2), 평가가격 100.
    출력: (a) 평가액 −550, NAV 450. (b) 현금 −1,002, NAV 1,998. 음수 보유·음수 현금을 금지하는 규칙을 만들지 않는다."""
    short = nav(ledger_with(make_event("CE-0", K.EXTERNAL_FLOW, "1000", FUND_AT, "transfer:T-0")), -5, "110", V1)
    leveraged = nav(
        ledger_with(
            funding(),
            make_event("CE-1", K.TRADE_CONSIDERATION, "-3000", BUY_AT, FILL_REF),
            make_event("CE-2", K.COMMISSION, "-2", BUY_AT, FILL_REF),
        ),
        30,
        "100",
        V1,
    )

    assert (short.market_value, short.nav) == (Decimal("-550"), Decimal("450"))
    assert (leveraged.cash.balance, leveraged.nav) == (Decimal("-1002"), Decimal("1998"))


def test_holdings_must_be_verified_for_this_valuation():
    """입력: (a) 보유 기준 시각 ≠ 평가 시각, (b) 다른 계좌의 보유, (c) 사양에 있는 종목을 보유에서 뺌, (d) 사양에 없는 종목의 가격,
    (e) 같은 종목 사양 두 개.
    출력: 모두 ValueError. 목표 포지션·미체결 주문이 아니라 평가 시각에 검증된 보유 기록만 받는다."""
    ledger = ledger_with(funding(), consideration(), commission())
    base = dict(ledger=ledger, currency="USD", valuation_at=V1, information_cutoff=V1)
    prices = {ETF: price("100", V1)}
    unknown_price = {**prices, "ETF.US9": price("1", V1, unit_id="ETF.US9")}
    cases = [
        (dict(holdings=holdings({ETF: 10}, V0), specs=(etf_spec(),), prices=prices), "verified at the valuation time"),
        (dict(holdings=holdings({ETF: 10}, V1, account_id="A2"), specs=(etf_spec(),), prices=prices), "another account"),
        (dict(holdings=holdings({}, V1), specs=(etf_spec(),), prices=prices), "exactly the ETF units"),
        (dict(holdings=holdings({ETF: 10}, V1), specs=(etf_spec(),), prices=unknown_price), "unknown unit"),
        (dict(holdings=holdings({ETF: 10}, V1), specs=(etf_spec(), etf_spec()), prices=prices), "repeat"),
    ]
    for case, message in cases:
        with pytest.raises(ValueError, match=message):
            calculate_nav(**base, **case)


def test_conflicting_cash_ledger_blocks_nav():
    """입력: 같은 ID·다른 금액의 수수료 재수신으로 CONFLICT가 기록된 장부.
    출력: CashIntegrityError. 충돌이 해결될 때까지 NAV를 계산하지 않는다."""
    ledger = ledger_with(funding(), consideration(), commission())
    ledger = apply_cash_event(ledger, make_event("CE-2", K.COMMISSION, "-3", BUY_AT, FILL_REF)).ledger

    with pytest.raises(CashIntegrityError):
        nav(ledger, 10, "100", V1)


def test_position_market_value():
    """입력: 검증된 10주, 평가가격 110 (출처·이용 가능 시각 포함), 평가 시각 V2.
    출력: 평가액 = 10 × 110 = 1,100 USD (ETF 승수 1, I6-6). 다른 종목의 가격이나 다른 시각의 보유 기록이면 ValueError."""
    result = position_market_value(
        holdings=holdings({ETF: 10}, V2), spec=etf_spec(), price=price("110", V2), valuation_at=V2, information_cutoff=V2
    )

    assert (result.unit_id, result.currency, result.quantity, result.amount) == (ETF, "USD", 10, Decimal("1100"))
    assert result.price.source_ref == "fixture:close"
    with pytest.raises(ValueError):
        position_market_value(
            holdings=holdings({ETF: 10}, V2),
            spec=etf_spec(),
            price=price("110", V2, unit_id="ETF.US9"),
            valuation_at=V2,
            information_cutoff=V2,
        )
    with pytest.raises(ValueError):
        position_market_value(
            holdings=holdings({ETF: 10}, V1), spec=etf_spec(), price=price("110", V2), valuation_at=V2, information_cutoff=V2
        )


@pytest.mark.parametrize("bad", [100.0, float("inf"), Decimal("NaN"), "NaN"])
def test_valuation_price_must_be_a_finite_decimal(bad):
    """입력: float, Infinity, NaN 평가가격.
    출력: ValueError."""
    with pytest.raises(ValueError):
        price(bad, V1)


def test_etf_spec_has_no_multiplier_and_no_default_lot():
    """입력: ETF 사양 (lot size 없음 = None), 0 이하 lot size, 문자열 lot size.
    출력: None은 그대로 None (1로 가정하지 않음, I6-11). 0·문자열은 ValueError. 승수 필드는 없다 (ETF 승수 1 고정, I6-6)."""
    assert etf_spec(lot_size=None).lot_size is None
    assert not hasattr(etf_spec(), "multiplier")
    with pytest.raises(ValueError):
        etf_spec(lot_size=0)
    with pytest.raises(ValueError):
        etf_spec(lot_size="10")


def test_nav_inputs_are_explicit_utc_times():
    """입력: (a) information_cutoff > 평가 시각, (b) 시간대 없는 평가 시각.
    출력: 모두 ValueError (사후 재평가 없음)."""
    ledger = ledger_with(funding())

    with pytest.raises(ValueError):
        nav(ledger, 0, None, V1, cutoff=V2)
    with pytest.raises(ValueError):
        calculate_nav(
            ledger=ledger,
            holdings=holdings({ETF: 0}, V1),
            specs=(etf_spec(),),
            prices={},
            currency="USD",
            valuation_at=datetime(2026, 10, 20, 21, 0),
            information_cutoff=V1,
        )
