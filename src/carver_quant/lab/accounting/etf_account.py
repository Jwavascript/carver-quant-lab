"""ETF 체결 → 실제 포지션 → 현금 이벤트 → NAV 통합 (P0-03B Slice 4).

ADR-0009 R9-2·R9-9·R9-11, ADR-0008 §6.2·§6.3·§6.4, F8-1·F8-2 원칙, ADR-0001 §5.1.3. 계좌 하나·가상 ETF 범위의 최소 통합이다.
체결이 APPLIED일 때만 그 체결의 매매대금·수수료 현금 이벤트를 만들고(C-3), 포지션·현금·NAV를 낼 때마다 체결 장부와 현금 장부를
이벤트 단위로 대조한다. 충돌·누락·불일치가 있으면 계산을 확정하지 않는다.

구현하지 않는 것: ETF 결제 예정일·결제 상태(R9-11의 결제 부분, Q8-5), 분배금·세금·기업 행사, 선물 정산·증거금, FX,
브로커 대조, 여러 건으로 나뉜 수수료 보고, 늦게 받은 브로커 체결의 이용 가능 시각, 기준 시각 이전 체결과 검증된 기초 현금(Q13-2),
영속 저장. 이 통합은 실전 거래 준비가 아니다.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal, DecimalException, localcontext
from enum import Enum

from carver_quant.lab.accounting.cash_ledger import (
    CashApplication,
    CashBalance,
    CashLedger,
    CashVerdict,
    apply_cash_event,
    cash_balance,
)
from carver_quant.lab.accounting.etf_fill_ledger import EtfFillLedger, apply_etf_fill
from carver_quant.lab.accounting.fill_ledger import FillVerdict
from carver_quant.lab.accounting.positions import actual_position
from carver_quant.lab.accounting.valuation import NavResult, calculate_nav
from carver_quant.lab.domain.cash import (
    CASH_EVENT_COMPARISON_FIELDS,
    FILL_CASH_EVENT_KINDS,
    CashEvent,
    CashEventConfirmation,
    CashEventKind,
)
from carver_quant.lab.domain.records import EtfSpec, FillKey, FillRecord, PositionBaseline, ValuationPrice
from carver_quant.lab.domain.values import EXACT_DECIMAL_CONTEXT, require_utc_instant


# 체결에서 나온 매매대금·수수료의 원인 참조 접두어. 다른 종류의 이벤트가 이 접두어를 쓰면 대조에서 UNEXPECTED다.
FILL_CAUSE_PREFIX = "fill:"


def fill_cause_ref(key: FillKey) -> str:
    """체결 키의 결정적 원인 참조 (Slice 4 내부 형식이며 브로커 수수료 기록 형식(D3A-30)을 정하지 않는다).

    각 부분 앞에 길이를 붙여 이어 쓴다: (A1, SIM, E-1) → "fill:2:A1:3:SIM:3:E-1". 그래서 구분자가 든 ID라도 다른 키와 겹치지 않는다.
    """
    if not isinstance(key, FillKey):
        raise ValueError("key must be a FillKey.")
    return FILL_CAUSE_PREFIX + ":".join(f"{len(part)}:{part}" for part in (key.account_id, key.fill_source, key.fill_id))


def fill_cash_events(fill: FillRecord, spec: EtfSpec) -> tuple[CashEvent, CashEvent]:
    """ETF 체결 하나에서 생기는 현금 이벤트 두 건을 만든다 (R9-11, ADR-0008 §6.3, F8-1 원칙).

    공식: 매매대금 = −q × F (ETF 승수 1: 매수 −, 매도 +), 수수료 = −fee (≤ 0). 단위: ETF 통화 (= 수수료 통화).
    발생 시각 = fill_at. 원인 참조 = fill_cause_ref(체결 키), ID = 원인 참조 + ":" + 종류이므로 같은 체결이면 언제 만들어도
    같은 이벤트다. 결제 예정일·결제 상태는 만들지 않는다. CONFIRMED는 반영된 체결에서 나온 기록이라는 뜻이며, 브로커가
    확인한 현금이라는 뜻이 아니다 (출처 구분은 OPEN).
    예외조건 (ValueError): 사양과 다른 종목, 0 이하 체결 가격 (Slice 4 결정), 수수료 통화 ≠ ETF 통화, 정확한 Decimal 계산 실패.
    """
    if not isinstance(fill, FillRecord):
        raise ValueError("fill must be a FillRecord.")
    if not isinstance(spec, EtfSpec):
        raise ValueError("spec must be an EtfSpec.")
    if fill.contract_id != spec.unit_id:
        raise ValueError(f"fill {fill.key.fill_id!r} is for {fill.contract_id!r}, not for {spec.unit_id!r}.")
    if fill.price <= 0:
        raise ValueError("an ETF fill price must be positive (currency per share, Slice 4 decision).")
    if fill.fee_currency != spec.currency:
        raise ValueError("fee_currency must equal the ETF currency (ADR-0001 tentative assumption).")
    try:
        with localcontext(EXACT_DECIMAL_CONTEXT):
            consideration = Decimal(0) - fill.quantity * fill.price
            commission = Decimal(0) - fill.fee
    except DecimalException as error:
        raise ValueError(f"exact decimal calculation failed: {error!r}") from error
    cause = fill_cause_ref(fill.key)
    return tuple(
        CashEvent(
            account_id=fill.key.account_id,
            cash_event_id=f"{cause}:{kind.value}",
            kind=kind,
            cause_ref=cause,
            currency=spec.currency,
            amount=amount,
            occurred_at=fill.fill_at,
            confirmation=CashEventConfirmation.CONFIRMED,
        )
        for kind, amount in ((CashEventKind.TRADE_CONSIDERATION, consideration), (CashEventKind.COMMISSION, commission))
    )


@dataclass(frozen=True)
class EtfAccount:
    """계좌 하나의 ETF 통합 기록: 검증된 기준 포지션, ETF 체결 장부, 현금 장부.

    직접 만들 수도 있다 (예: 따로 받은 현금 장부). 대신 포지션·현금·NAV를 낼 때마다 두 장부를 이벤트 단위로 대조한다.
    """

    baseline: PositionBaseline
    fills: EtfFillLedger
    cash: CashLedger

    def __post_init__(self) -> None:
        if not isinstance(self.baseline, PositionBaseline):
            raise ValueError("baseline must be a PositionBaseline.")
        if not isinstance(self.fills, EtfFillLedger):
            raise ValueError("fills must be an EtfFillLedger.")
        if not isinstance(self.cash, CashLedger):
            raise ValueError("cash must be a CashLedger.")
        if not self.baseline.account_id == self.fills.account_id == self.cash.account_id:
            raise ValueError("baseline, fills and cash must belong to one account.")
        if self.baseline.contract_ids() != self.fills.contract_ids():
            raise ValueError("the baseline must list exactly the ETF units of the fill ledger (use 0 for no holding).")


def open_etf_account(*, baseline: PositionBaseline, units: Iterable[EtfSpec]) -> EtfAccount:
    """검증된 기준 포지션과 ETF 사양으로 빈 체결 장부·빈 현금 장부를 가진 계좌를 만든다."""
    if not isinstance(baseline, PositionBaseline):
        raise ValueError("baseline must be a PositionBaseline.")
    return EtfAccount(
        baseline=baseline,
        fills=EtfFillLedger.empty(account_id=baseline.account_id, units=units),
        cash=CashLedger.empty(account_id=baseline.account_id),
    )


class PostingOutcome(Enum):
    """체결 하나를 반영한 뒤의 계좌 전체 결과. 체결 장부의 판정(`FillVerdict`)과 따로 본다."""

    POSTED = "POSTED"  # 새 체결과 그 현금 이벤트가 반영되었고 계좌가 일관됨
    NO_CHANGE = "NO_CHANGE"  # 같은 체결의 재수신(DUPLICATE). 포지션·현금 그대로이고 계좌가 일관됨
    BLOCKED = "BLOCKED"  # 체결·현금 충돌이 있거나 체결과 현금이 맞지 않음. 해결 전까지 포지션·현금·NAV를 계산하지 않음


@dataclass(frozen=True)
class EtfFillPosting:
    """체결 하나의 반영 결과. `fill_verdict`는 체결 장부의 판정일 뿐이며, 계좌 전체 결과는 `outcome`과 `reasons`다
    (FILL_CONFLICT, CASH_CONFLICT, FILL_CASH_NOT_RECONCILED). `cash_events`는 APPLIED 체결일 때만 있고, `cash_verdicts`는
    각 이벤트의 현금 장부 판정이다."""

    fill_verdict: FillVerdict
    outcome: PostingOutcome
    reasons: tuple[str, ...]
    account: EtfAccount
    cash_events: tuple[CashEvent, ...]
    cash_verdicts: tuple[CashVerdict, ...]


def _posting(
    fill_verdict: FillVerdict,
    account: EtfAccount,
    cash_events: tuple[CashEvent, ...],
    cash_verdicts: tuple[CashVerdict, ...],
) -> EtfFillPosting:
    reasons = ("FILL_CONFLICT",) if account.fills.conflicts else ()
    reasons += ("CASH_CONFLICT",) if account.cash.conflicts else ()
    if not reasons and not reconcile_fill_cash(account.fills, account.cash).complete:
        reasons = ("FILL_CASH_NOT_RECONCILED",)
    if reasons:
        outcome = PostingOutcome.BLOCKED
    elif fill_verdict is FillVerdict.DUPLICATE:
        outcome = PostingOutcome.NO_CHANGE
    else:
        outcome = PostingOutcome.POSTED
    return EtfFillPosting(
        fill_verdict=fill_verdict,
        outcome=outcome,
        reasons=reasons,
        account=account,
        cash_events=cash_events,
        cash_verdicts=cash_verdicts,
    )


def record_etf_fill(account: EtfAccount, fill: FillRecord) -> EtfFillPosting:
    """ETF 체결 하나를 체결 장부에 반영하고, APPLIED일 때만 그 체결의 현금 이벤트를 현금 장부에 반영한다.

    DUPLICATE·CONFLICT는 현금 장부를 바꾸지 않는다 (C-3, R9-9). 이미 있는 키의 재수신은 체결 시각과 관계없이 먼저
    DUPLICATE·CONFLICT로 판정해 충돌 증거를 남긴다. 현금 장부의 판정(같은 체결의 다른 ID 기록이면 CONFLICT)은
    `cash_verdicts`로 돌려준다. 체결이 APPLIED여도 계좌에 충돌이 있거나 체결과 현금이 맞지 않으면 `outcome`은 BLOCKED이며,
    그 계좌로는 이후 계산이 막힌다.
    예외조건 (ValueError): 새 체결의 시각이 기준 시각과 같거나 이름 (기준에 이미 든 체결과 시작 현금의 관계는 OPEN, Q13-2),
    `apply_etf_fill`의 예외조건.
    """
    if not isinstance(account, EtfAccount):
        raise ValueError("account must be an EtfAccount.")
    if not isinstance(fill, FillRecord):
        raise ValueError("fill must be a FillRecord.")
    application = apply_etf_fill(account.fills, fill)
    if application.verdict is not FillVerdict.APPLIED:
        return _posting(application.verdict, replace(account, fills=application.ledger), (), ())
    if fill.fill_at <= account.baseline.as_of:
        raise ValueError(
            "an integrated account only takes new fills after the baseline time; "
            "earlier fills and the opening cash are not reconciled here (Q13-2)."
        )

    events = fill_cash_events(fill, application.ledger.unit(fill.contract_id))
    cash = account.cash
    verdicts = []
    for event in events:
        result = apply_cash_event(cash, event)
        cash = result.ledger
        verdicts.append(result.verdict)
    return _posting(
        FillVerdict.APPLIED,
        EtfAccount(baseline=account.baseline, fills=application.ledger, cash=cash),
        events,
        tuple(verdicts),
    )


@dataclass(frozen=True)
class EtfCashPosting:
    account: EtfAccount
    application: CashApplication


def record_cash_event(account: EtfAccount, event: CashEvent) -> EtfCashPosting:
    """현금 이벤트 하나(예: 외부 입출금)를 현금 장부에 반영한다. 판정은 `apply_cash_event` 그대로다.

    매매대금·수수료를 따로 받으면, 포지션·현금·NAV를 낼 때 반영된 체결의 기대 이벤트와 대조한다.
    """
    if not isinstance(account, EtfAccount):
        raise ValueError("account must be an EtfAccount.")
    application = apply_cash_event(account.cash, event)
    return EtfCashPosting(account=replace(account, cash=application.ledger), application=application)


class FillCashIssueKind(Enum):
    MISSING = "MISSING"  # 반영된 체결의 기대 이벤트가 현금 장부에 없음
    MISMATCHED = "MISMATCHED"  # 같은 체결·종류의 이벤트가 있지만 ID·통화·금액·시각·확인 여부가 기대와 다름
    UNEXPECTED = "UNEXPECTED"  # 반영된 ETF 체결에 대응하지 않는 매매대금·수수료 이벤트


@dataclass(frozen=True)
class FillCashIssue:
    kind: FillCashIssueKind
    cause_ref: str
    event_kind: CashEventKind
    expected: CashEvent | None
    actual: CashEvent | None
    differing_fields: tuple[str, ...]


@dataclass(frozen=True)
class FillCashReconciliation:
    """체결 장부와 현금 장부의 이벤트 단위 대조 결과. `issues`가 비어 있을 때만 완전하다."""

    account_id: str
    expected_events: int
    matched_events: int
    issues: tuple[FillCashIssue, ...]

    @property
    def complete(self) -> bool:
        return not self.issues


class FillCashReconciliationError(ValueError):
    """체결과 현금 이벤트가 맞지 않아(누락·불일치·대응 없음) 포지션·현금·NAV를 확정하지 않을 때."""

    def __init__(self, reconciliation: FillCashReconciliation) -> None:
        self.reconciliation = reconciliation
        super().__init__(
            f"fill and cash records do not reconcile ({len(reconciliation.issues)} issue(s)); calculation refused."
        )


_EVENT_FIELDS = ("cash_event_id",) + CASH_EVENT_COMPARISON_FIELDS


def reconcile_fill_cash(fills: EtfFillLedger, cash: CashLedger) -> FillCashReconciliation:
    """반영된 ETF 체결에서 나와야 하는 매매대금·수수료 이벤트와 현금 장부의 실제 이벤트를 하나씩 대조한다.

    기대 이벤트는 `fill_cash_events`로 만들고, (원인 참조, 종류)로 실제 이벤트를 찾아 ID·통화·금액·발생 시각·확인 여부를
    비교한다. 결과: MISSING, MISMATCHED(다른 필드 목록), UNEXPECTED. 합계가 같아도 이벤트가 하나라도 다르면 완전하지 않다.
    외부 입출금(EXTERNAL_FLOW)은 대조 대상이 아니다. 단 체결 원인 참조(`FILL_CAUSE_PREFIX`)를 쓰는 다른 종류의 이벤트는
    체결 현금을 외부 흐름으로 다시 넣는 것일 수 있으므로 UNEXPECTED다.
    예외조건: 계좌 불일치는 ValueError. 체결 장부 CONFLICT는 FillIntegrityError, 현금 장부 CONFLICT는 CashIntegrityError.
    """
    if not isinstance(fills, EtfFillLedger):
        raise ValueError("fills must be an EtfFillLedger.")
    if not isinstance(cash, CashLedger):
        raise ValueError("cash must be a CashLedger.")
    if fills.account_id != cash.account_id:
        raise ValueError("fills and cash must belong to one account.")
    fills.require_no_conflicts()
    cash.require_no_conflicts()

    expected = {}
    for fill in fills.applied:
        for event in fill_cash_events(fill, fills.unit(fill.contract_id)):
            expected[(event.cause_ref, event.kind)] = event
    actual = {(event.cause_ref, event.kind): event for event in cash.applied if event.kind in FILL_CASH_EVENT_KINDS}

    issues = []
    matched = 0
    for key, wanted in expected.items():
        found = actual.get(key)
        if found is None:
            issues.append(FillCashIssue(FillCashIssueKind.MISSING, key[0], key[1], wanted, None, ()))
            continue
        differing = tuple(name for name in _EVENT_FIELDS if getattr(wanted, name) != getattr(found, name))
        if differing:
            issues.append(FillCashIssue(FillCashIssueKind.MISMATCHED, key[0], key[1], wanted, found, differing))
        else:
            matched += 1
    for key, found in actual.items():
        if key not in expected:
            issues.append(FillCashIssue(FillCashIssueKind.UNEXPECTED, key[0], key[1], None, found, ()))
    for event in cash.applied:
        if event.kind not in FILL_CASH_EVENT_KINDS and event.cause_ref.startswith(FILL_CAUSE_PREFIX):
            issues.append(FillCashIssue(FillCashIssueKind.UNEXPECTED, event.cause_ref, event.kind, None, event, ()))

    issues.sort(key=lambda issue: (issue.cause_ref, issue.event_kind.value, issue.kind.value))
    return FillCashReconciliation(
        account_id=fills.account_id, expected_events=len(expected), matched_events=matched, issues=tuple(issues)
    )


def _require_consistent(account: EtfAccount, as_of: datetime, information_cutoff: datetime) -> None:
    if not isinstance(account, EtfAccount):
        raise ValueError("account must be an EtfAccount.")
    require_utc_instant(as_of, "as_of")
    require_utc_instant(information_cutoff, "information_cutoff")
    if information_cutoff > as_of:
        raise ValueError("information_cutoff must not be later than as_of.")
    reconciliation = reconcile_fill_cash(account.fills, account.cash)
    if not reconciliation.complete:
        raise FillCashReconciliationError(reconciliation)
    for fill in account.fills.applied:
        if fill.fill_at <= account.baseline.as_of:
            raise ValueError("an applied fill at or before the baseline time is not supported in the integrated account (Q13-2).")
        if information_cutoff < fill.fill_at <= as_of:
            raise ValueError(f"ETF fill {fill.key.fill_id!r} happened after information_cutoff.")


def account_position(account: EtfAccount, *, as_of: datetime, information_cutoff: datetime) -> dict[str, int]:
    """통합 계좌의 종목별 실제 수량(주)을 계산한다.

    공식: A[c](as_of) = 기준[c] + Σ { Δq[k] : c(k) = c, T0 < fill_at[k] ≤ as_of } (R9-2, 기존 `actual_position`).
    먼저 체결·현금 대조를 확인한다. 예외조건: 장부 충돌(FillIntegrityError·CashIntegrityError), 대조 실패
    (FillCashReconciliationError), information_cutoff < fill_at ≤ as_of인 체결, information_cutoff > as_of → ValueError.
    """
    _require_consistent(account, as_of, information_cutoff)
    return actual_position(account.baseline, account.fills, as_of)


def account_cash(account: EtfAccount, *, currency: str, as_of: datetime, information_cutoff: datetime) -> CashBalance:
    """통합 계좌의 통화별 현금 잔액 (기존 `cash_balance`). 먼저 `account_position`과 같은 일관성 검사를 한다."""
    _require_consistent(account, as_of, information_cutoff)
    return cash_balance(account.cash, currency=currency, as_of=as_of, information_cutoff=information_cutoff)


def account_nav(
    account: EtfAccount,
    *,
    prices: Mapping[str, ValuationPrice],
    currency: str,
    valuation_at: datetime,
    information_cutoff: datetime,
) -> NavResult:
    """통합 계좌의 단일 통화 NAV (기존 `calculate_nav`: NAV = 현금 + Σ q × V).

    보유는 R9-2 실제 포지션(검증된 기준 + 반영된 체결)이며 목표 포지션·미체결 주문이 아니다. 평가 시각 기준으로 만든
    보유 기록의 `verification_ref`는 "derived:" + 기준의 검증 참조다. COMPUTED는 운영용 NAV 확정이 아니다 (`NAV_OPEN_POLICIES`).
    예외조건: `account_position`과 같은 일관성 검사, `calculate_nav`의 예외조건.
    """
    holdings = account_position(account, as_of=valuation_at, information_cutoff=information_cutoff)
    derived = PositionBaseline(
        account_id=account.baseline.account_id,
        as_of=valuation_at,
        quantities=holdings,
        verification_ref="derived:" + account.baseline.verification_ref,
    )
    return calculate_nav(
        ledger=account.cash,
        holdings=derived,
        specs=account.fills.units,
        prices=prices,
        currency=currency,
        valuation_at=valuation_at,
        information_cutoff=information_cutoff,
    )
