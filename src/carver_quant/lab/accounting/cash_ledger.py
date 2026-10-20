"""현금 이벤트 장부와 반영 판정 (P0-03B Slice 3, ADR-0008 §6.1·§6.3·§6.6, ADR-0009 R9-9·R9-11, F8-1 원칙).

체결 장부(fill_ledger)와 같은 방식이다: 순수 함수는 판정만 돌려주고 Trading State를 바꾸지 않는다. `CONFLICT`가 기록된
장부로는 잔액·NAV를 계산하지 않는다 (`CashIntegrityError`). 장부는 `CashLedger.empty()`와 `apply_cash_event()`로만 만든다.
직접 생성, `dataclasses.replace`, `copy.replace`는 ValueError, 하위 클래스 정의는 TypeError다.

한계: 영속 저장이 없으므로 호출자가 새 빈 장부에 받은 이벤트 일부만 다시 넣는 것은 알 수 없다 (ADR-0009 Q9-9, ADR-0012 Q12-7).
같은 경제적 사건이 다른 Cash Event ID로 두 번 오는 경우는 체결의 매매대금·수수료(체결 참조당 한 건)만 잡는다.
브로커 현금 보고와의 대조(ADR-0012 BF-6, ADR-0003 S-3)는 하지 않는다.
"""

from dataclasses import dataclass, field, replace
from datetime import datetime
from decimal import Decimal, DecimalException, localcontext
from enum import Enum

from carver_quant.lab.domain.cash import (
    CASH_EVENT_COMPARISON_FIELDS,
    FILL_CASH_EVENT_KINDS,
    CashEvent,
    CashEventConfirmation,
    CashEventKind,
)
from carver_quant.lab.domain.values import EXACT_DECIMAL_CONTEXT, require_identifier, require_utc_instant


class CashIntegrityError(ValueError):
    """같은 Cash Event ID의 내용이 다르거나 같은 체결의 대금·수수료가 두 번 온 장부를 계산에 쓰려 할 때."""


class CashVerdict(Enum):
    APPLIED = "APPLIED"
    DUPLICATE = "DUPLICATE"
    CONFLICT = "CONFLICT"


# 장부 생성 경로를 CashLedger.empty()와 apply_cash_event()로 제한하는 내부 표식. 생성 뒤에는 None으로 지운다.
_CASH_LEDGER_BUILD_TOKEN = object()


def _differing_fields(existing: CashEvent, incoming: CashEvent) -> tuple[str, ...]:
    names = ("cash_event_id",) + CASH_EVENT_COMPARISON_FIELDS
    return tuple(name for name in names if getattr(existing, name) != getattr(incoming, name))


def _same_fill_cause(first: CashEvent, second: CashEvent) -> bool:
    return first.kind in FILL_CASH_EVENT_KINDS and first.kind is second.kind and first.cause_ref == second.cause_ref


@dataclass(frozen=True)
class CashConflict:
    """무결성 오류의 증거 (불변). 기존 반영 기록, 반영하지 않은 수신 기록, 실제로 다른 필드를 모두 보관한다.

    두 경우다: (a) 같은 Cash Event ID인데 내용이 다름, (b) ID는 다르지만 같은 체결의 같은 종류(매매대금·수수료) 기록.
    """

    existing: CashEvent
    incoming: CashEvent
    differing_fields: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.existing, CashEvent) or not isinstance(self.incoming, CashEvent):
            raise ValueError("a conflict must hold two CashEvent values.")
        if self.existing.account_id != self.incoming.account_id:
            raise ValueError("a conflict must compare records of one account.")
        same_id = self.existing.cash_event_id == self.incoming.cash_event_id
        if not same_id and not _same_fill_cause(self.existing, self.incoming):
            raise ValueError("a conflict must share the cash event id, or the fill cause of a consideration or commission.")
        differing = _differing_fields(self.existing, self.incoming)
        if not differing or self.differing_fields != differing:
            raise ValueError("a conflict must list exactly the fields that differ.")


@dataclass(frozen=True)
class CashLedger:
    """단일 계좌의 현금 이벤트 장부 (불변). 이벤트마다 자기 통화를 가지며 잔액은 통화별로만 계산한다 (X8-8).

    `applied`는 도착 순서이며 Cash Event ID마다 한 건, 체결 참조마다 매매대금·수수료 각 한 건이다. 내부 생성 때도
    불변조건을 검사한다: ID당 한 건, 장부 계좌의 이벤트, 확인된 기록만, 체결 참조당 대금·수수료 한 건,
    중복 수신·충돌 기록은 반영된 이벤트에 대한 것.
    """

    account_id: str
    applied: tuple[CashEvent, ...]
    duplicates: tuple[CashEvent, ...]
    conflicts: tuple[CashConflict, ...]
    _build_token: object = field(default=None, repr=False, compare=False)

    def __init_subclass__(cls, **kwargs: object) -> None:
        raise TypeError("CashLedger cannot be subclassed; a subclass could skip the ledger checks.")

    def __post_init__(self) -> None:
        if self._build_token is not _CASH_LEDGER_BUILD_TOKEN:
            raise ValueError("CashLedger can only be created with CashLedger.empty() and apply_cash_event().")
        object.__setattr__(self, "_build_token", None)
        object.__setattr__(self, "account_id", require_identifier(self.account_id, "account_id"))
        for name in ("applied", "duplicates", "conflicts"):
            if not isinstance(getattr(self, name), tuple):
                raise ValueError(f"{name} must be a tuple.")

        applied_by_id = {}
        fill_causes = set()  # (종류, 체결 참조). 이벤트마다 이전 이벤트 전체를 다시 훑지 않는다 (장부 구성 비용)
        for event in self.applied:
            if not isinstance(event, CashEvent):
                raise ValueError("applied must contain CashEvent values.")
            if event.account_id != self.account_id:
                raise ValueError("an applied cash event belongs to another account.")
            if event.confirmation is not CashEventConfirmation.CONFIRMED:
                raise ValueError("an unconfirmed cash record cannot be an applied fact.")
            if event.cash_event_id in applied_by_id:
                raise ValueError("an applied cash event id appears more than once.")
            if event.kind in FILL_CASH_EVENT_KINDS:
                if (event.kind, event.cause_ref) in fill_causes:
                    raise ValueError("a fill's consideration or commission is applied twice for the same cause.")
                fill_causes.add((event.kind, event.cause_ref))
            applied_by_id[event.cash_event_id] = event

        for event in self.duplicates:
            if not isinstance(event, CashEvent):
                raise ValueError("duplicates must contain CashEvent values.")
            existing = applied_by_id.get(event.cash_event_id)
            if existing is None or _differing_fields(existing, event):
                raise ValueError("a duplicate record must equal an applied event with the same id.")

        for conflict in self.conflicts:
            if not isinstance(conflict, CashConflict):
                raise ValueError("conflicts must contain CashConflict values.")
            if applied_by_id.get(conflict.existing.cash_event_id) != conflict.existing:
                raise ValueError("a conflict must refer to an applied event.")

    @classmethod
    def empty(cls, *, account_id: str) -> "CashLedger":
        return cls(account_id=account_id, applied=(), duplicates=(), conflicts=(), _build_token=_CASH_LEDGER_BUILD_TOKEN)

    def require_no_conflicts(self) -> None:
        if self.conflicts:
            raise CashIntegrityError(f"cash ledger has {len(self.conflicts)} conflicting record(s); calculation refused.")


@dataclass(frozen=True)
class CashApplication:
    verdict: CashVerdict
    ledger: CashLedger
    incoming: CashEvent
    existing: CashEvent | None
    differing_fields: tuple[str, ...]


def apply_cash_event(ledger: CashLedger, event: CashEvent) -> CashApplication:
    """현금 이벤트 하나를 장부에 반영하고 판정을 돌려준다.

    입력: 불변 장부, 새 현금 이벤트. 출력: 새 장부와 판정 (`APPLIED` / `DUPLICATE` / `CONFLICT`).
    - Cash Event ID가 처음이고 같은 체결의 같은 종류(매매대금·수수료) 기록이 없으면 `APPLIED`.
    - 같은 ID에 비교 필드(`CASH_EVENT_COMPARISON_FIELDS`)가 모두 같으면 `DUPLICATE`. 잔액은 그대로이고 수신만 기록한다.
    - 같은 ID에 하나라도 다르면 `CONFLICT`. 반영하지 않고 두 기록을 `CashConflict`로 보관한다.
    - ID는 다르지만 같은 체결 참조의 같은 종류가 이미 있으면 `CONFLICT`. 더하지 않는다 (R9-9, R9-11, F8-1 원칙).
      체결 정정 형식이 정해지지 않았으므로(BR-11, D3A-30) 두 번째 기록을 정정으로 보지 않는다.
    예외조건 (ValueError): 다른 계좌의 이벤트, 확인되지 않은 기록 (`UNCONFIRMED`는 사실로 반영하지 않음).
    """
    if not isinstance(ledger, CashLedger):
        raise ValueError("ledger must be a CashLedger.")
    if not isinstance(event, CashEvent):
        raise ValueError("event must be a CashEvent.")
    if event.account_id != ledger.account_id:
        raise ValueError("cash event account_id does not match the ledger account.")
    if event.confirmation is not CashEventConfirmation.CONFIRMED:
        raise ValueError("an unconfirmed cash record is not applied as a fact; confirm or reconcile it first.")

    existing = next((record for record in ledger.applied if record.cash_event_id == event.cash_event_id), None)
    if existing is None:
        existing = next((record for record in ledger.applied if _same_fill_cause(record, event)), None)
    if existing is None:
        return CashApplication(
            verdict=CashVerdict.APPLIED,
            ledger=replace(ledger, applied=ledger.applied + (event,), _build_token=_CASH_LEDGER_BUILD_TOKEN),
            incoming=event,
            existing=None,
            differing_fields=(),
        )

    differing = _differing_fields(existing, event)
    if not differing:
        return CashApplication(
            verdict=CashVerdict.DUPLICATE,
            ledger=replace(ledger, duplicates=ledger.duplicates + (event,), _build_token=_CASH_LEDGER_BUILD_TOKEN),
            incoming=event,
            existing=existing,
            differing_fields=(),
        )
    conflict = CashConflict(existing=existing, incoming=event, differing_fields=differing)
    return CashApplication(
        verdict=CashVerdict.CONFLICT,
        ledger=replace(ledger, conflicts=ledger.conflicts + (conflict,), _build_token=_CASH_LEDGER_BUILD_TOKEN),
        incoming=event,
        existing=existing,
        differing_fields=differing,
    )


@dataclass(frozen=True)
class CashBalance:
    """통화 하나의 장부 현금 잔액 `Cash_κ(as_of)` (결제·미결제 포함, ADR-0008 §6.6). 사용 가능 현금이 아니다.

    `balance` = `trade_consideration` + `commission` + `external_flow` (종류별 이벤트 금액의 합, 단위 `currency`).
    모두 부호 있는 현금 금액이다. `commission`은 수수료 현금 유출의 합(≤ 0)이며, 거래 손익의 수수료 비용
    (`FillRecord.fee`, `PeriodTradingPnl.fees`, ≥ 0)과 부호가 반대다. NAV는 이 잔액을 쓰므로 수수료를 다시 빼지 않는다.
    """

    account_id: str
    currency: str
    as_of: datetime
    information_cutoff: datetime
    trade_consideration: Decimal
    commission: Decimal
    external_flow: Decimal
    balance: Decimal


def cash_balance(ledger: CashLedger, *, currency: str, as_of: datetime, information_cutoff: datetime) -> CashBalance:
    """통화 κ의 장부 현금 잔액을 계산한다.

    공식: Cash_κ(as_of) = Σ { amount[e] : currency[e] = κ, occurred_at[e] ≤ as_of } (장부의 처음부터, 종류별 합의 합).
    입력: 현금 장부, 통화 κ, 기준 시각, 정보 기준 시각 (UTC, information_cutoff ≤ as_of). 단위: 금액 κ.
    전제조건: 장부에는 계좌 시작 뒤의 확인된 현금 이벤트가 모두 있다 (시작 현금도 외부 입금 이벤트). 검증된 기초 잔액은
    다루지 않는다. 다른 통화의 금액은 더하지 않는다 (X8-8).
    예외조건: as_of 뒤에 발생한 이벤트는 넣지 않는다. information_cutoff < occurred_at ≤ as_of인 κ 이벤트는 ValueError
    (그 시각까지 알 수 없었던 이벤트로 계산하지 않음, V-1). 장부에 CONFLICT가 있으면 CashIntegrityError.
    정확한 Decimal 계산이 실패하면 ValueError.
    """
    if not isinstance(ledger, CashLedger):
        raise ValueError("ledger must be a CashLedger.")
    ledger.require_no_conflicts()
    currency = require_identifier(currency, "currency")
    require_utc_instant(as_of, "as_of")
    require_utc_instant(information_cutoff, "information_cutoff")
    if information_cutoff > as_of:
        raise ValueError("information_cutoff must not be later than as_of.")

    totals = {kind: Decimal(0) for kind in CashEventKind}
    try:
        with localcontext(EXACT_DECIMAL_CONTEXT):
            for event in ledger.applied:
                if event.currency != currency or event.occurred_at > as_of:
                    continue
                if event.occurred_at > information_cutoff:
                    raise ValueError(f"cash event {event.cash_event_id!r} happened after information_cutoff.")
                totals[event.kind] += event.amount
            balance = sum(totals.values(), Decimal(0))
    except DecimalException as error:
        raise ValueError(f"exact decimal calculation failed: {error!r}") from error

    return CashBalance(
        account_id=ledger.account_id,
        currency=currency,
        as_of=as_of,
        information_cutoff=information_cutoff,
        trade_consideration=totals[CashEventKind.TRADE_CONSIDERATION],
        commission=totals[CashEventKind.COMMISSION],
        external_flow=totals[CashEventKind.EXTERNAL_FLOW],
        balance=balance,
    )
