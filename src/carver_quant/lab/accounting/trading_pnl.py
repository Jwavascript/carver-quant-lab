"""주기별 거래 손익 (ADR-0001 §6.2 식 (1), 단일 통화).

가격 선택 정책, 선물 정산의 현금 반영, NAV는 구현하지 않는다. 입력 가격은 이미 지정된 raw 평가가격이다.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import (
    MAX_EMAX,
    MAX_PREC,
    MIN_EMIN,
    Context,
    Decimal,
    DecimalException,
    DivisionByZero,
    Inexact,
    InvalidOperation,
    Overflow,
    localcontext,
)

from carver_quant.lab.accounting.fill_ledger import FillLedger
from carver_quant.lab.domain.records import FillRecord, ValuationPrice
from carver_quant.lab.domain.values import require_identifier, require_int, require_utc_instant

# 덧셈·뺄셈·곱셈만 쓰므로 정밀도 한계 없이 정확히 계산한다. 반올림이 생기면 Inexact로 즉시 실패한다.
_EXACT_CONTEXT = Context(
    prec=MAX_PREC,
    Emax=MAX_EMAX,
    Emin=MIN_EMIN,
    traps=[InvalidOperation, DivisionByZero, Overflow, Inexact],
)


@dataclass(frozen=True)
class ContractPnl:
    """월물 하나의 기여분 (보고용). 합계 손익은 이 값들을 한 번만 더해 만든다."""

    contract_id: str
    holding_pnl: Decimal
    fill_pnl: Decimal
    fees: Decimal


@dataclass(frozen=True)
class PeriodTradingPnl:
    currency: str
    period_start: datetime
    period_end: datetime
    information_cutoff: datetime
    gross_pnl: Decimal
    fees: Decimal
    net_pnl: Decimal
    contributions: tuple[ContractPnl, ...]


def _validated_prices(
    prices: object,
    name: str,
    ledger: FillLedger,
    valuation_at: datetime,
    information_cutoff: datetime,
) -> dict[str, ValuationPrice]:
    if not isinstance(prices, Mapping):
        raise ValueError(f"{name} must be a mapping of contract_id to ValuationPrice.")
    known = ledger.contract_ids()
    result = {}
    for contract_id, price in prices.items():
        if contract_id not in known:
            raise ValueError(f"{name} has unknown contract_id {contract_id!r}.")
        if not isinstance(price, ValuationPrice):
            raise ValueError(f"{name}[{contract_id!r}] must be a ValuationPrice.")
        if price.contract_id != contract_id:
            raise ValueError(f"{name}[{contract_id!r}] is a price for {price.contract_id!r}.")
        if price.valuation_at != valuation_at:
            raise ValueError(f"{name}[{contract_id!r}] is not a price for valuation time {valuation_at.isoformat()}.")
        if price.data_available_at > information_cutoff:
            raise ValueError(f"{name}[{contract_id!r}] became available after information_cutoff.")
        if price.data_available_at > valuation_at:
            raise ValueError(f"{name}[{contract_id!r}] became available after its own valuation time.")
        result[contract_id] = price
    return result


def period_trading_pnl(
    *,
    ledger: FillLedger,
    currency: str,
    period_start: datetime,
    period_end: datetime,
    start_positions: Mapping[str, int],
    start_prices: Mapping[str, ValuationPrice],
    end_prices: Mapping[str, ValuationPrice],
    information_cutoff: datetime,
) -> PeriodTradingPnl:
    """평가 주기 t의 단일 통화 거래 손익을 계산한다 (ADR-0001 §6.2 식 (1), 환산 없음).

    공식 (통화 κ = `currency`, 선물이므로 분배금 항 D = 0):
        Gross = Σ_c q[c,t−1] × (V[c,t] − V[c,t−1]) × M[c]  +  Σ_k Δq[k] × (V[c(k),t] − F[k]) × M[c(k)]
        Fee   = Σ_k fee[k]
        Net   = Gross − Fee
    체결 k는 period_start < fill_at[k] ≤ period_end일 때만 이 주기에 귀속된다 (ADR-0001 §5.1.3, I-3).
    단위: 수량 계약, 가격 pt, 승수 `currency`/pt/계약, 금액 `currency`.
    입력: 반영 체결 장부, 주기 시작·끝(valuation_at(t−1), valuation_at(t)), 장부의 모든 월물의 시작 포지션 q[c,t−1],
    월물별 raw 평가가격 V[c,t−1]·V[c,t] (출처·이용 가능 시각 포함), 명시적 information_cutoff.
    전제조건: 승수는 각 월물 사양의 M[c]. 수수료 통화 = 월물 통화 (ADR-0001 잠정 가정). 체결가에 이미 들어 있는
    스프레드·슬리피지는 따로 빼지 않는다 (이중 차감 금지).
    예외조건 (ValueError): period_start ≥ period_end, information_cutoff > period_end, information_cutoff 뒤에 이용 가능해진
    가격, 자기 평가 시각 뒤에 이용 가능해진 가격, information_cutoff 뒤의 귀속 체결, 평가 시각이 맞지 않는 가격,
    필요한 가격·시작 포지션 없음, 월물·통화 불일치, 정확한 Decimal 계산 실패.
    장부에 CONFLICT가 있으면 FillIntegrityError. 0·이전 값·기본 가격·기본 승수로 대체하지 않는다.
    """
    if not isinstance(ledger, FillLedger):
        raise ValueError("ledger must be a FillLedger.")
    ledger.require_no_conflicts()
    require_identifier(currency, "currency")
    require_utc_instant(period_start, "period_start")
    require_utc_instant(period_end, "period_end")
    require_utc_instant(information_cutoff, "information_cutoff")
    if period_start >= period_end:
        raise ValueError("period_start must be earlier than period_end.")
    if information_cutoff > period_end:
        raise ValueError("information_cutoff must not be later than the valuation time (no after-the-fact revaluation).")

    for spec in ledger.contracts:
        if spec.currency != currency:
            raise ValueError(f"contract {spec.contract_id!r} is not in currency {currency!r}.")

    if not isinstance(start_positions, Mapping):
        raise ValueError("start_positions must be a mapping of contract_id to int.")
    if set(start_positions) != ledger.contract_ids():
        raise ValueError("start_positions must list exactly the ledger contracts (use 0 for no position).")
    positions = {contract_id: require_int(quantity, "start position") for contract_id, quantity in start_positions.items()}

    starts = _validated_prices(start_prices, "start_prices", ledger, period_start, information_cutoff)
    ends = _validated_prices(end_prices, "end_prices", ledger, period_end, information_cutoff)

    period_fills = [fill for fill in ledger.applied if period_start < fill.fill_at <= period_end]
    for fill in period_fills:
        if fill.fill_at > information_cutoff:
            raise ValueError(f"fill {fill.key.fill_id!r} happened after information_cutoff.")
        if fill.fee_currency != currency:
            raise ValueError(f"fill {fill.key.fill_id!r} fee currency is not {currency!r}.")

    try:
        contributions = _contract_contributions(ledger, positions, starts, ends, period_fills)
        with localcontext(_EXACT_CONTEXT):
            gross_pnl = sum((row.holding_pnl + row.fill_pnl for row in contributions), Decimal(0))
            total_fees = sum((row.fees for row in contributions), Decimal(0))
            net_pnl = gross_pnl - total_fees
    except DecimalException as error:
        raise ValueError(f"exact decimal calculation failed: {error!r}") from error

    return PeriodTradingPnl(
        currency=currency,
        period_start=period_start,
        period_end=period_end,
        information_cutoff=information_cutoff,
        gross_pnl=gross_pnl,
        fees=total_fees,
        net_pnl=net_pnl,
        contributions=contributions,
    )


def _contract_contributions(
    ledger: FillLedger,
    positions: dict[str, int],
    starts: dict[str, ValuationPrice],
    ends: dict[str, ValuationPrice],
    period_fills: list[FillRecord],
) -> tuple[ContractPnl, ...]:
    contributions = []
    with localcontext(_EXACT_CONTEXT):
        for spec in ledger.contracts:
            contract_id = spec.contract_id
            multiplier = spec.multiplier
            start_quantity = positions[contract_id]
            fills = [fill for fill in period_fills if fill.contract_id == contract_id]

            holding_pnl = Decimal(0)
            if start_quantity != 0:
                if contract_id not in starts or contract_id not in ends:
                    raise ValueError(f"start and end valuation prices are required for held contract {contract_id!r}.")
                holding_pnl = start_quantity * (ends[contract_id].price - starts[contract_id].price) * multiplier

            fill_pnl = Decimal(0)
            fees = Decimal(0)
            if fills:
                if contract_id not in ends:
                    raise ValueError(f"an end valuation price is required for traded contract {contract_id!r}.")
                end_price = ends[contract_id].price
                for fill in fills:
                    fill_pnl += fill.quantity * (end_price - fill.price) * multiplier
                    fees += fill.fee

            contributions.append(
                ContractPnl(contract_id=contract_id, holding_pnl=holding_pnl, fill_pnl=fill_pnl, fees=fees)
            )
    return tuple(contributions)
