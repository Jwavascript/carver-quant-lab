"""ETF 평가액과 단일 통화 NAV (P0-03B Slice 3, ADR-0008 §6.2·§6.4·§6.5, ADR-0006 I6-6, ADR-0013 R13-1).

평가가격 선택 정책, 기준통화 NAV와 FX 환산, 선물 평가·정산, 브로커 현금 대조, 운영용 NAV 확정 규칙은 구현하지 않는다.
`COMPUTED`는 이 Slice가 받은 명시 입력(평가가격, 검증된 보유, 확인된 현금 이벤트)으로 계산했다는 뜻이며 운영용 확정이
아니다. 운영용 확정에 남은 조건은 `NAV_OPEN_POLICIES`로 결과에 함께 싣는다.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, DecimalException, localcontext
from enum import Enum

from carver_quant.lab.accounting.cash_ledger import CashBalance, CashLedger, cash_balance
from carver_quant.lab.domain.records import EtfSpec, PositionBaseline, ValuationPrice
from carver_quant.lab.domain.values import EXACT_DECIMAL_CONTEXT, require_identifier, require_utc_instant


class NavStatus(Enum):
    COMPUTED = "COMPUTED"  # 명시 입력으로 계산함. 운영용 NAV 확정이 아니다 (NAV_OPEN_POLICIES)
    NOT_COMPUTABLE = "NOT_COMPUTABLE"  # 필요한 입력이 없어 NAV를 정하지 않음 (미확정). nav는 None이며 0이 아니다


# COMPUTED NAV에도 남아 있는 운영용 확정 조건. 모두 OPEN이며 이 Slice는 정하지 않는다.
NAV_OPEN_POLICIES = (
    "VALUATION_PRICE_POLICY",  # 평가가격 선택: 종가·정산가·ETF NAV, 결측 처리 (ADR-0001 Q1-2, ADR-0007 Q7-3·Q7-4)
    "BASE_CURRENCY",  # 계좌 기준통화와 FX 환산 (ADR-0008 Q8-9, Q8-1)
    "CASH_RECONCILIATION",  # 브로커 현금·포지션 대조 (ADR-0012 BF-6, ADR-0003 S-3)
    "NAV_CONFIRMATION_RULE",  # 운영용 NAV 확정과 미확정 시 처리 (ADR-0012 Q12-10)
)


@dataclass(frozen=True)
class MarketValue:
    """ETF 한 종목의 평가액 `q × V` (단위 `currency`, ETF 승수 1)."""

    account_id: str
    unit_id: str
    currency: str
    quantity: int
    price: ValuationPrice
    valuation_at: datetime
    amount: Decimal


@dataclass(frozen=True)
class NavResult:
    """평가 시각의 단일 통화 NAV (ADR-0008 §6.2의 `E_κ = Cash_κ + MV_κ`, κ = `currency`. FX 환산 없음).

    `nav`와 `market_value`(평가액 합계)는 COMPUTED일 때만 값이 있다. NOT_COMPUTABLE이면 None이고 `reasons`에 사유가 있다.
    """

    account_id: str
    currency: str
    valuation_at: datetime
    information_cutoff: datetime
    status: NavStatus
    reasons: tuple[str, ...]
    nav: Decimal | None
    cash: CashBalance
    market_value: Decimal | None
    market_values: tuple[MarketValue, ...]
    unpriced_unit_ids: tuple[str, ...]
    fx_missing_currencies: tuple[str, ...]
    open_policies: tuple[str, ...]


def _check_times(valuation_at: datetime, information_cutoff: datetime) -> None:
    require_utc_instant(valuation_at, "valuation_at")
    require_utc_instant(information_cutoff, "information_cutoff")
    if information_cutoff > valuation_at:
        raise ValueError("information_cutoff must not be later than the valuation time (no after-the-fact revaluation).")


def _check_holdings(holdings: object, valuation_at: datetime) -> PositionBaseline:
    if not isinstance(holdings, PositionBaseline):
        raise ValueError("holdings must be a PositionBaseline with the verified actual holdings.")
    if holdings.as_of != valuation_at:
        raise ValueError("holdings must be verified at the valuation time (holdings.as_of = valuation_at).")
    return holdings


def _check_price(price: object, unit_id: str, valuation_at: datetime, information_cutoff: datetime) -> ValuationPrice:
    if not isinstance(price, ValuationPrice):
        raise ValueError(f"the price for {unit_id!r} must be a ValuationPrice.")
    if price.contract_id != unit_id:
        raise ValueError(f"the price for {unit_id!r} is a price for {price.contract_id!r}.")
    if price.valuation_at != valuation_at:
        raise ValueError(f"the price for {unit_id!r} is not a price for valuation time {valuation_at.isoformat()}.")
    if price.data_available_at > information_cutoff:
        raise ValueError(f"the price for {unit_id!r} became available after information_cutoff.")
    if price.data_available_at > valuation_at:
        raise ValueError(f"the price for {unit_id!r} became available after its own valuation time.")
    return price


def position_market_value(
    *,
    holdings: PositionBaseline,
    spec: EtfSpec,
    price: ValuationPrice,
    valuation_at: datetime,
    information_cutoff: datetime,
) -> MarketValue:
    """ETF 한 종목의 평가액을 계산한다.

    공식: MV[c,t] = q[c,t] × V[c,t] (ETF 승수 1, ADR-0008 §6.2, I6-6).
    단위: 수량 주, 평가가격 `spec.currency`/주, 평가액 `spec.currency`.
    입력: 평가 시각에 검증된 실제 보유(`PositionBaseline`, as_of = valuation_at), ETF 사양, 명시적 raw 평가가격
    (출처·이용 가능 시각 포함), 평가 시각, 정보 기준 시각 (UTC).
    전제조건: 보유 수량이 실제로 검증되었는지는 호출 경계의 책임이다. 목표 포지션·미체결 주문은 보유가 아니다.
    lot에 맞지 않는 보유도 그대로 평가한다 (반올림 없음, ADR-0013 R13-1).
    예외조건 (ValueError): 보유 기준 시각 ≠ 평가 시각, 보유에 그 종목이 없음, 다른 종목·다른 평가 시각의 가격,
    information_cutoff나 평가 시각 뒤에 이용 가능해진 가격, information_cutoff > 평가 시각, 정확한 Decimal 계산 실패.
    """
    _check_times(valuation_at, information_cutoff)
    _check_holdings(holdings, valuation_at)
    if not isinstance(spec, EtfSpec):
        raise ValueError("spec must be an EtfSpec.")
    _check_price(price, spec.unit_id, valuation_at, information_cutoff)
    quantity = holdings.quantity(spec.unit_id)
    try:
        with localcontext(EXACT_DECIMAL_CONTEXT):
            amount = quantity * price.price
    except DecimalException as error:
        raise ValueError(f"exact decimal calculation failed: {error!r}") from error
    return MarketValue(
        account_id=holdings.account_id,
        unit_id=spec.unit_id,
        currency=spec.currency,
        quantity=quantity,
        price=price,
        valuation_at=valuation_at,
        amount=amount,
    )


def calculate_nav(
    *,
    ledger: CashLedger,
    holdings: PositionBaseline,
    specs: Iterable[EtfSpec],
    prices: Mapping[str, ValuationPrice],
    currency: str,
    valuation_at: datetime,
    information_cutoff: datetime,
) -> NavResult:
    """평가 시각의 단일 통화 NAV를 계산한다.

    공식 (κ = `currency`): NAV_κ(t) = Cash_κ(t) + Σ_{ETF c : κ(c) = κ} q[c,t] × V[c,t]
    (ADR-0008 §6.2의 통화별 순자산 E_κ. 단일 통화이므로 FX 환산이 없다).
    입력: 현금 장부, 평가 시각에 검증된 보유(사양의 모든 종목을 0 포함해 명시), ETF 사양, 종목별 명시 평가가격, 통화,
    평가 시각, 정보 기준 시각 (UTC). 현금 잔액은 같은 평가 시각·정보 기준 시각으로 계산한다.
    결과: COMPUTED(nav, 남은 운영 정책 `NAV_OPEN_POLICIES`) 또는 NOT_COMPUTABLE(사유, nav = None):
      - VALUATION_PRICE_MISSING: 0이 아닌 보유의 평가가격이 없다. 이전 가격·체결가로 채우지 않는다.
      - FX_MISSING: 다른 통화의 현금 잔액이나 보유가 0이 아니다. 환율을 1로 쓰지도, 더하지도 않는다
        (X8-3, X8-8, ADR-0008 §6.2: 순자산이 0이 아닌 통화의 환율이 없으면 NAV를 확정하지 않음).
    투자 손익은 ΔNAV − 외부 흐름이다 (ADR-0008 §6.4, X8-7). 외부 흐름은 `cash.external_flow`의 차이로 얻는다.
    예외조건 (ValueError): 계좌 불일치, 보유 기준 시각 ≠ 평가 시각, 보유와 사양의 종목 불일치, 사양 중복, 사양에 없는
    종목의 가격, 잘못된 평가 시각의 가격, 정보 기준 시각 뒤의 가격·현금 이벤트. 장부에 CONFLICT가 있으면 CashIntegrityError.
    """
    if not isinstance(ledger, CashLedger):
        raise ValueError("ledger must be a CashLedger.")
    currency = require_identifier(currency, "currency")
    _check_times(valuation_at, information_cutoff)
    _check_holdings(holdings, valuation_at)
    if holdings.account_id != ledger.account_id:
        raise ValueError("holdings belong to another account than the cash ledger.")
    checked_specs = tuple(specs)
    if not all(isinstance(spec, EtfSpec) for spec in checked_specs):
        raise ValueError("specs must contain EtfSpec values.")
    unit_ids = [spec.unit_id for spec in checked_specs]
    if len(set(unit_ids)) != len(unit_ids):
        raise ValueError("specs must not repeat a unit_id.")
    if holdings.contract_ids() != set(unit_ids):
        raise ValueError("holdings must list exactly the ETF units of the specs (use 0 for no holding).")
    if not isinstance(prices, Mapping):
        raise ValueError("prices must be a mapping of unit_id to ValuationPrice.")
    for unit_id, price in prices.items():
        if unit_id not in unit_ids:
            raise ValueError(f"prices has unknown unit {unit_id!r}.")
        _check_price(price, unit_id, valuation_at, information_cutoff)

    cash = cash_balance(ledger, currency=currency, as_of=valuation_at, information_cutoff=information_cutoff)
    fx_missing = set()
    for other in sorted({event.currency for event in ledger.applied} - {currency}):
        other_cash = cash_balance(ledger, currency=other, as_of=valuation_at, information_cutoff=information_cutoff)
        if other_cash.balance != 0:
            fx_missing.add(other)

    market_values = []
    unpriced = []
    for spec in sorted(checked_specs, key=lambda spec: spec.unit_id):
        quantity = holdings.quantity(spec.unit_id)
        if quantity == 0:
            continue
        if spec.currency != currency:
            fx_missing.add(spec.currency)
        elif spec.unit_id not in prices:
            unpriced.append(spec.unit_id)
        else:
            market_values.append(
                position_market_value(
                    holdings=holdings,
                    spec=spec,
                    price=prices[spec.unit_id],
                    valuation_at=valuation_at,
                    information_cutoff=information_cutoff,
                )
            )

    reasons = ("VALUATION_PRICE_MISSING",) if unpriced else ()
    reasons += ("FX_MISSING",) if fx_missing else ()
    if reasons:
        return _nav_result(
            ledger, currency, valuation_at, information_cutoff, NavStatus.NOT_COMPUTABLE, reasons, None, cash, None,
            market_values, unpriced, fx_missing,
        )
    try:
        with localcontext(EXACT_DECIMAL_CONTEXT):
            market_value = sum((row.amount for row in market_values), Decimal(0))
            nav = cash.balance + market_value
    except DecimalException as error:
        raise ValueError(f"exact decimal calculation failed: {error!r}") from error
    return _nav_result(
        ledger, currency, valuation_at, information_cutoff, NavStatus.COMPUTED, (), nav, cash, market_value,
        market_values, unpriced, fx_missing,
    )


def _nav_result(
    ledger: CashLedger,
    currency: str,
    valuation_at: datetime,
    information_cutoff: datetime,
    status: NavStatus,
    reasons: tuple[str, ...],
    nav: Decimal | None,
    cash: CashBalance,
    market_value: Decimal | None,
    market_values: list[MarketValue],
    unpriced: list[str],
    fx_missing: set[str],
) -> NavResult:
    return NavResult(
        account_id=ledger.account_id,
        currency=currency,
        valuation_at=valuation_at,
        information_cutoff=information_cutoff,
        status=status,
        reasons=reasons,
        nav=nav,
        cash=cash,
        market_value=market_value,
        market_values=tuple(market_values),
        unpriced_unit_ids=tuple(unpriced),
        fx_missing_currencies=tuple(sorted(fx_missing)),
        open_policies=NAV_OPEN_POLICIES if status is NavStatus.COMPUTED else (),
    )
