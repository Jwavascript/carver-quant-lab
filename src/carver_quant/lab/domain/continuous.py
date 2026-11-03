"""P1-02 연속 선물 도메인 계약: 명시적 롤 계획, 선물 롤 이벤트(TC-C7), 연구용 조정 가격 시계열(TC-C6), 연속 시계열 품질 보고서
(ADR-0004 §6.4·§6.5, ADR-0006 I6-1·I6-3, P0-03A TC-C6·TC-C7·INV-28. 타입 이름은 가칭, D3A-01).

조정 가격은 Research 계층(`lab.research`)만 만든다. 이 모듈은 계약만 둔다. 가격과 조정값은 index point 단위의 정확한 Decimal이다.
롤 기준일은 가격을 잇는 회계적 기준일이며 주문·체결 시각이나 가격이 아니다. 조정 가격은 신호 계산 전용이다: 체결·평가·명목가치·증거금·
현금에 쓰지 않고, 서로 다른 `as_of` 시계열끼리 차분하지 않는다 (INV-28). raw로 되돌리는 암묵적 변환을 두지 않는다.
"""

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum

from carver_quant.lab.domain.market_data import (
    AvailabilityEvidence,
    QualityFinding,
    QualityStatus,
    evidence_at_least,
    require_date,
    worst_quality_status,
)
from carver_quant.lab.domain.values import EXACT_DECIMAL_CONTEXT, require_decimal, require_identifier, require_utc_instant


def _require_member(value: object, kind: type[Enum], name: str) -> Enum:
    if not isinstance(value, kind):
        raise ValueError(f"{name} must be a {kind.__name__}.")

    return value


def _require_tuple_of(values: object, kind: type, name: str) -> tuple:
    if not isinstance(values, tuple) or any(type(item) is not kind for item in values):
        raise ValueError(f"{name} must be a tuple of {kind.__name__} values.")

    return values


def _require_codes(values: object, name: str) -> tuple[str, ...]:
    if not isinstance(values, tuple) or not values:
        raise ValueError(f"{name} must be a non-empty tuple.")

    return tuple(require_identifier(item, name) for item in values)


@dataclass(frozen=True, kw_only=True)
class RollPlanEntry:
    """연구용 롤 계획의 롤 하나 (명시적 입력이며 롤 날짜를 자동으로 정하지 않는다. 실거래 롤 정책이 아니다).

    `roll_reference_date`는 두 월물 가격을 비교하는 기준 거래일, `new_contract_first_date`는 신월물을 처음 선택하는 거래일(TC-C7 효력일)이다.
    `evidence_cutoff_at`(TC-C7 known_at)은 기준 가격을 정하는 시각이다: 그 시각에 받아들인 근거로 보인 두 최종 정산가로 gap을 정하고,
    그 뒤의 정정은 반영하지 않는다. 기준일 UTC 자정보다 이를 수 없다 (그 전에는 기준일 정산가가 없다).
    """

    from_contract_id: str
    to_contract_id: str
    roll_reference_date: date
    new_contract_first_date: date
    selection_policy_id: str
    evidence_cutoff_at: datetime

    def __post_init__(self) -> None:
        for name in ("from_contract_id", "to_contract_id", "selection_policy_id"):
            object.__setattr__(self, name, require_identifier(getattr(self, name), name))
        if self.from_contract_id == self.to_contract_id:
            raise ValueError("a roll needs two different contracts.")
        reference = require_date(self.roll_reference_date, "roll_reference_date")
        first = require_date(self.new_contract_first_date, "new_contract_first_date")
        if not reference < first:
            raise ValueError("new_contract_first_date must be after roll_reference_date.")
        object.__setattr__(self, "roll_reference_date", reference)
        object.__setattr__(self, "new_contract_first_date", first)
        cutoff = require_utc_instant(self.evidence_cutoff_at, "evidence_cutoff_at")
        if cutoff < datetime(reference.year, reference.month, reference.day, tzinfo=timezone.utc):
            raise ValueError("evidence_cutoff_at must not precede the roll reference date.")


@dataclass(frozen=True, kw_only=True)
class RollPlan:
    """연구용 연속 선물 하나의 명시적 롤 계획 (P1-02 명세 §3).

    `research_instrument_id`(예: `CME.MES.CONTINUOUS`)는 연구용 시계열의 식별자이며 주문할 수 있는 계약이 아니다. 월물 ID와 같을 수 없다.
    월물은 `initial_contract_id`에서 시작해 롤마다 하나씩 이어지는 사슬이며 같은 월물이 두 번 나오지 않는다. 롤은 날짜 순서이고 앞 롤의
    신월물 첫 거래일 전에 다음 롤의 기준일이 올 수 없으며, known_at(`evidence_cutoff_at`)도 줄어들지 않는다. 그래서 같은 롤이 두 번 있거나 같은
    날 상충하는 롤은 계획으로 만들 수 없다. `accepted_evidence`는 기준 가격과 시계열 입력에 받아들이는 가장 약한 근거다 (기본값 없음).
    """

    plan_id: str
    research_instrument_id: str
    initial_contract_id: str
    accepted_evidence: AvailabilityEvidence
    entries: tuple[RollPlanEntry, ...]

    def __post_init__(self) -> None:
        for name in ("plan_id", "research_instrument_id", "initial_contract_id"):
            object.__setattr__(self, name, require_identifier(getattr(self, name), name))
        _require_member(self.accepted_evidence, AvailabilityEvidence, "accepted_evidence")
        entries = _require_tuple_of(self.entries, RollPlanEntry, "entries")
        chain = [self.initial_contract_id]
        for entry in entries:
            if entry.from_contract_id != chain[-1]:
                raise ValueError("roll entries must form one contract chain (each roll starts from the previous new contract).")
            chain.append(entry.to_contract_id)
        if len(set(chain)) != len(chain):
            raise ValueError("a contract cannot appear twice in the roll chain.")
        if self.research_instrument_id in chain:
            raise ValueError("research_instrument_id must differ from every contract ID.")
        for previous, following in zip(entries, entries[1:]):
            if following.roll_reference_date < previous.new_contract_first_date:
                raise ValueError("a roll cannot reference a date before the previous roll's new contract first date.")
            if following.evidence_cutoff_at < previous.evidence_cutoff_at:
                raise ValueError("roll evidence cutoffs must not decrease.")

    @property
    def contracts(self) -> tuple[str, ...]:
        return (self.initial_contract_id, *(entry.to_contract_id for entry in self.entries))


@dataclass(frozen=True, kw_only=True)
class FuturesRollEvent:
    """기준 가격이 정해진 선물 롤 (TC-C7 `FuturesRollEvent`). 효력일 = `new_contract_first_date`, known_at = `evidence_cutoff_at`.

    단위: 가격과 gap은 index point. `roll_gap_points` = 구월물 기준가 − 신월물 기준가 (정확한 Decimal). 두 기준가는 같은 기준 거래일의 최종
    정산가이며, `reference_prices_available_at`(둘 중 늦게 보인 시각)은 known_at 이하다. 원본 레코드·Snapshot ID로 추적한다. 롤 gap은
    실현 손익이나 거래비용이 아니다.
    """

    research_instrument_id: str
    from_contract_id: str
    to_contract_id: str
    roll_reference_date: date
    new_contract_first_date: date
    selection_policy_id: str
    evidence_cutoff_at: datetime
    accepted_evidence: AvailabilityEvidence
    old_reference_price: Decimal
    new_reference_price: Decimal
    roll_gap_points: Decimal
    reference_prices_available_at: datetime
    old_source_record_id: str
    old_source_snapshot_id: str
    new_source_record_id: str
    new_source_snapshot_id: str

    def __post_init__(self) -> None:
        for name in ("research_instrument_id", "from_contract_id", "to_contract_id", "selection_policy_id", "old_source_record_id",
                     "old_source_snapshot_id", "new_source_record_id", "new_source_snapshot_id"):
            object.__setattr__(self, name, require_identifier(getattr(self, name), name))
        if self.from_contract_id == self.to_contract_id:
            raise ValueError("a roll needs two different contracts.")
        reference = require_date(self.roll_reference_date, "roll_reference_date")
        first = require_date(self.new_contract_first_date, "new_contract_first_date")
        if not reference < first:
            raise ValueError("new_contract_first_date must be after roll_reference_date.")
        object.__setattr__(self, "roll_reference_date", reference)
        object.__setattr__(self, "new_contract_first_date", first)
        _require_member(self.accepted_evidence, AvailabilityEvidence, "accepted_evidence")
        for name in ("old_reference_price", "new_reference_price", "roll_gap_points"):
            object.__setattr__(self, name, require_decimal(getattr(self, name), name))
        if EXACT_DECIMAL_CONTEXT.subtract(self.old_reference_price, self.new_reference_price) != self.roll_gap_points:
            raise ValueError("roll_gap_points must equal old_reference_price − new_reference_price exactly.")
        known_at = require_utc_instant(self.evidence_cutoff_at, "evidence_cutoff_at")
        if known_at < datetime(reference.year, reference.month, reference.day, tzinfo=timezone.utc):
            raise ValueError("evidence_cutoff_at must not precede the roll reference date.")
        if require_utc_instant(self.reference_prices_available_at, "reference_prices_available_at") > known_at:
            raise ValueError("reference prices must have been available by evidence_cutoff_at.")

    @property
    def effective_date(self) -> date:
        return self.new_contract_first_date

    @property
    def known_at(self) -> datetime:
        return self.evidence_cutoff_at


@dataclass(frozen=True, kw_only=True)
class UnresolvedRoll:
    """기준 가격을 정할 수 없는 롤 (known_at에 두 최종 정산가가 모두 보이지 않음). gap을 추정하지 않는다."""

    entry: RollPlanEntry
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self.entry) is not RollPlanEntry:
            raise ValueError("entry must be a RollPlanEntry.")
        object.__setattr__(self, "reasons", _require_codes(self.reasons, "reasons"))


class AdjustmentMethod(Enum):
    FUTURES_ADDITIVE_BACK_ADJUSTED = "FUTURES_ADDITIVE_BACK_ADJUSTED"  # 가산(Panama): 최신 월물 기준으로 과거 가격을 롤 gap만큼 옮김


class ContinuousSeriesBasis(Enum):
    FULL_SAMPLE = "FULL_SAMPLE"  # 자료 끝 시각을 as_of로 둔 시계열. 계획의 모든 롤을 적용. 사후 연구·시각화용이며 as_of 전 판단에 쓰지 않음
    AS_OF_CUTOFF = "AS_OF_CUTOFF"  # 과거 cutoff에 알려진 정산가와 롤만 쓴 PIT 시계열


@dataclass(frozen=True, kw_only=True)
class AdjustedPricePoint:
    """연구용 조정 가격 시계열의 한 점 (거래일 하나, 선택한 월물 하나).

    단위: index point. `raw_price`는 선택한 월물의 최종 정산가(raw), `cumulative_adjustment_points`는 이 날 뒤에 효력이 생기는 롤 gap의 합,
    `adjusted_price` = `raw_price` − `cumulative_adjustment_points` (정확한 Decimal, 부호 제약 없음). `daily_price_change_points`는 같은
    시계열 안의 앞 점(`change_from_trading_date`)과의 조정 가격 차이이며 첫 점은 None이다. `available_at`·`availability_evidence`는 raw 정산가가
    보인 시각과 근거다 (조정 가격 자체는 시계열의 `as_of`에 알려진 롤로 정해진다).
    """

    trading_date: date
    selected_contract_id: str
    raw_price: Decimal
    cumulative_adjustment_points: Decimal
    adjusted_price: Decimal
    daily_price_change_points: Decimal | None
    change_from_trading_date: date | None
    source_record_id: str
    source_snapshot_id: str
    available_at: datetime
    availability_evidence: AvailabilityEvidence

    def __post_init__(self) -> None:
        object.__setattr__(self, "trading_date", require_date(self.trading_date, "trading_date"))
        for name in ("selected_contract_id", "source_record_id", "source_snapshot_id"):
            object.__setattr__(self, name, require_identifier(getattr(self, name), name))
        for name in ("raw_price", "cumulative_adjustment_points", "adjusted_price"):
            object.__setattr__(self, name, require_decimal(getattr(self, name), name))
        if EXACT_DECIMAL_CONTEXT.subtract(self.raw_price, self.cumulative_adjustment_points) != self.adjusted_price:
            raise ValueError("adjusted_price must equal raw_price − cumulative_adjustment_points exactly.")
        if (self.daily_price_change_points is None) != (self.change_from_trading_date is None):
            raise ValueError("daily_price_change_points and change_from_trading_date are both present or both absent.")
        if self.daily_price_change_points is not None:
            object.__setattr__(self, "daily_price_change_points", require_decimal(self.daily_price_change_points, "daily_price_change_points"))
            previous = require_date(self.change_from_trading_date, "change_from_trading_date")
            if not previous < self.trading_date:
                raise ValueError("change_from_trading_date must be before trading_date.")
            object.__setattr__(self, "change_from_trading_date", previous)
        require_utc_instant(self.available_at, "available_at")
        _require_member(self.availability_evidence, AvailabilityEvidence, "availability_evidence")


@dataclass(frozen=True, kw_only=True)
class ContinuousExclusion:
    """선택한 월물에 쓸 수 있는 최종 정산가가 없어 시계열에 점이 없는 거래일과 그 이유. 다른 월물로 대신하거나 채우지 않는다."""

    trading_date: date
    selected_contract_id: str
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "trading_date", require_date(self.trading_date, "trading_date"))
        object.__setattr__(self, "selected_contract_id", require_identifier(self.selected_contract_id, "selected_contract_id"))
        object.__setattr__(self, "reasons", _require_codes(self.reasons, "reasons"))


def cumulative_adjustment(rolls, trading_date: date) -> Decimal:
    """거래일 하나의 누적 조정 (index point): 신월물 첫 거래일이 그 날보다 뒤인 롤 gap의 정확한 합. 해당 롤이 없으면 0."""
    total = Decimal(0)
    for roll in rolls:
        if roll.new_contract_first_date > trading_date:
            total = EXACT_DECIMAL_CONTEXT.add(total, roll.roll_gap_points)
    return total


def _sorted_dates(items, name: str) -> list[date]:
    dates = [item.trading_date for item in items]
    if any(left >= right for left, right in zip(dates, dates[1:])):
        raise ValueError(f"{name} must be in strictly increasing trading-date order.")
    return dates


@dataclass(frozen=True, kw_only=True)
class AdjustedPriceSeries:
    """연구용 연속 선물 조정 가격 시계열 snapshot (TC-C6 `AdjustedPriceSeries`, 상품 하나, `as_of` 하나, PIT 구성).

    `applied_rolls`는 이 `as_of`에 알려진(known_at ≤ `as_of`) 롤이며 `initial_contract_id`에서 이어지는 사슬이다. 점의 선택 월물, 누적 조정,
    일별 변화는 이 롤들과 맞아야 하고, 모든 점의 raw 정산가는 `as_of`까지 받아들인 근거 이상으로 보인 것이다. 일별 변화는 이 시계열 안에서만
    계산한다 (다른 `as_of` 시계열과 차분하지 않음).
    """

    research_instrument_id: str
    method: AdjustmentMethod
    algorithm_version: str
    basis: ContinuousSeriesBasis
    as_of: datetime
    accepted_evidence: AvailabilityEvidence
    roll_plan_id: str
    initial_contract_id: str
    applied_rolls: tuple[FuturesRollEvent, ...]
    points: tuple[AdjustedPricePoint, ...]
    excluded: tuple[ContinuousExclusion, ...]

    def __post_init__(self) -> None:
        for name in ("research_instrument_id", "algorithm_version", "roll_plan_id", "initial_contract_id"):
            object.__setattr__(self, name, require_identifier(getattr(self, name), name))
        _require_member(self.method, AdjustmentMethod, "method")
        _require_member(self.basis, ContinuousSeriesBasis, "basis")
        as_of = require_utc_instant(self.as_of, "as_of")
        accepted = _require_member(self.accepted_evidence, AvailabilityEvidence, "accepted_evidence")
        rolls = _require_tuple_of(self.applied_rolls, FuturesRollEvent, "applied_rolls")
        points = _require_tuple_of(self.points, AdjustedPricePoint, "points")
        excluded = _require_tuple_of(self.excluded, ContinuousExclusion, "excluded")
        chain = [self.initial_contract_id]
        for index, roll in enumerate(rolls):
            if roll.from_contract_id != chain[-1] or roll.research_instrument_id != self.research_instrument_id:
                raise ValueError("applied rolls must form the chain of this series' contracts.")
            if roll.known_at > as_of or roll.accepted_evidence is not accepted:
                raise ValueError("applied rolls must have been known by as_of on the series' accepted evidence.")
            if index and (roll.roll_reference_date < rolls[index - 1].new_contract_first_date or roll.known_at < rolls[index - 1].known_at):
                raise ValueError("applied rolls must be in date and known_at order.")
            if roll.to_contract_id in chain:
                raise ValueError("a contract cannot appear twice in the applied roll chain.")
            chain.append(roll.to_contract_id)
        if set(_sorted_dates(points, "points")) & set(_sorted_dates(excluded, "excluded")):
            raise ValueError("a trading date cannot be both a point and an exclusion.")

        def segment_contract(day: date) -> str:
            current = self.initial_contract_id
            for roll in rolls:
                if day >= roll.new_contract_first_date:
                    current = roll.to_contract_id
            return current

        previous = None
        for point in points:
            if point.selected_contract_id != segment_contract(point.trading_date):
                raise ValueError("a point's selected contract must follow the applied rolls.")
            if any(roll.roll_reference_date < point.trading_date < roll.new_contract_first_date for roll in rolls):
                raise ValueError("no point may lie between a roll's reference date and its new contract first date (continuity).")
            if point.cumulative_adjustment_points != cumulative_adjustment(rolls, point.trading_date):
                raise ValueError("cumulative_adjustment_points must be the sum of the gaps of rolls effective after the point.")
            if point.available_at > as_of or not evidence_at_least(point.availability_evidence, accepted):
                raise ValueError("every point must have been available by as_of on accepted or stronger evidence.")
            if previous is None:
                if point.daily_price_change_points is not None:
                    raise ValueError("the first point has no daily price change.")
            elif (point.change_from_trading_date != previous.trading_date
                  or point.daily_price_change_points != EXACT_DECIMAL_CONTEXT.subtract(point.adjusted_price, previous.adjusted_price)):
                raise ValueError("daily_price_change_points must be the adjusted change from the previous point in this series.")
            previous = point
        if any(item.selected_contract_id != segment_contract(item.trading_date) for item in excluded):
            raise ValueError("an exclusion's contract must follow the applied rolls.")


class ContinuousCheckName(Enum):
    CONTRACT_IDENTITY = "CONTRACT_IDENTITY"
    ROLL_ORDER = "ROLL_ORDER"
    EXPIRY = "EXPIRY"
    REFERENCE_PRICES = "REFERENCE_PRICES"
    OVERLAP = "OVERLAP"
    SELECTION_COVERAGE = "SELECTION_COVERAGE"
    MISSING_SESSIONS = "MISSING_SESSIONS"
    PIT = "PIT"
    DECIMAL_PRECISION = "DECIMAL_PRECISION"
    ADJUSTMENT_ARITHMETIC = "ADJUSTMENT_ARITHMETIC"
    SOURCE_INTEGRITY = "SOURCE_INTEGRITY"
    CONTRACT_DATA_QUALITY = "CONTRACT_DATA_QUALITY"


@dataclass(frozen=True, kw_only=True)
class ContinuousQualityCheck:
    """연속 시계열 품질 검사 하나. 상태는 발견 가운데 가장 심한 것이고 발견이 없으면 PASSED다 (P1-01 `QualityFinding` 재사용)."""

    name: ContinuousCheckName
    status: QualityStatus
    findings: tuple[QualityFinding, ...]

    def __post_init__(self) -> None:
        _require_member(self.name, ContinuousCheckName, "name")
        findings = _require_tuple_of(self.findings, QualityFinding, "findings")
        if any(left.code >= right.code for left, right in zip(findings, findings[1:])):
            raise ValueError("findings must be sorted by code without duplicates.")
        if self.status is not worst_quality_status(item.status for item in findings):
            raise ValueError("status must be the most severe finding status (PASSED without findings).")

    @property
    def reasons(self) -> tuple[str, ...]:
        return tuple(item.code for item in self.findings)


@dataclass(frozen=True, kw_only=True)
class RollBoundary:
    """롤 경계 하나의 가격 변화 비교 (단위 index point). `naive_raw_change_points`는 구월물 마지막 점에서 신월물 첫 점으로 raw 가격을 그대로
    이었을 때의 변화, `new_contract_change_points`는 신월물 자신의 기준일 → 첫 점 변화, `adjusted_change_points`는 조정 시계열의 변화다.
    `spurious_jump_points` = 단순 연결 변화 − 신월물 자신의 변화 (월물 교체로 생긴 가짜 점프)."""

    from_contract_id: str
    to_contract_id: str
    last_old_trading_date: date
    first_new_trading_date: date
    naive_raw_change_points: Decimal
    new_contract_change_points: Decimal
    adjusted_change_points: Decimal
    spurious_jump_points: Decimal

    def __post_init__(self) -> None:
        for name in ("from_contract_id", "to_contract_id"):
            object.__setattr__(self, name, require_identifier(getattr(self, name), name))
        last = require_date(self.last_old_trading_date, "last_old_trading_date")
        first = require_date(self.first_new_trading_date, "first_new_trading_date")
        if not last < first:
            raise ValueError("first_new_trading_date must be after last_old_trading_date.")
        for name in ("naive_raw_change_points", "new_contract_change_points", "adjusted_change_points", "spurious_jump_points"):
            object.__setattr__(self, name, require_decimal(getattr(self, name), name))
        if EXACT_DECIMAL_CONTEXT.subtract(self.naive_raw_change_points, self.new_contract_change_points) != self.spurious_jump_points:
            raise ValueError("spurious_jump_points must equal naive_raw_change_points − new_contract_change_points.")


@dataclass(frozen=True, kw_only=True)
class RollOverlap:
    """두 월물에 모두 최종 정산가가 있는 거래일 (롤 하나)."""

    from_contract_id: str
    to_contract_id: str
    trading_dates: tuple[date, ...]

    def __post_init__(self) -> None:
        for name in ("from_contract_id", "to_contract_id"):
            object.__setattr__(self, name, require_identifier(getattr(self, name), name))
        if not isinstance(self.trading_dates, tuple):
            raise ValueError("trading_dates must be a tuple.")
        dates = tuple(require_date(item, "trading_dates") for item in self.trading_dates)
        if any(left >= right for left, right in zip(dates, dates[1:])):
            raise ValueError("trading_dates must be strictly increasing.")
        object.__setattr__(self, "trading_dates", dates)


@dataclass(frozen=True, kw_only=True)
class ContinuousQualityReport:
    """연속 선물 시계열 하나의 품질 보고서. 검사는 `ContinuousCheckName` 순서로 하나씩 있고 전체 상태는 가장 심한 검사 상태다.
    시계열을 만들 수 없었으면 `series_basis`·`series_as_of`가 None이다. `calendar_holidays`는 달력 범위 안에서 달력에 없는 평일
    (휴장일로 본 날), `missing_trading_dates`는 달력에 있는데 점이 없는 날, `unverified_gaps`는 달력이 없을 때 점이 없는 평일이다."""

    research_instrument_id: str
    roll_plan_id: str
    rule_version: str
    series_basis: ContinuousSeriesBasis | None
    series_as_of: datetime | None
    status: QualityStatus
    checks: tuple[ContinuousQualityCheck, ...]
    overlaps: tuple[RollOverlap, ...]
    roll_boundaries: tuple[RollBoundary, ...]
    missing_trading_dates: tuple[date, ...]
    calendar_holidays: tuple[date, ...]
    unverified_gaps: tuple[date, ...]
    not_established: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in ("research_instrument_id", "roll_plan_id", "rule_version"):
            object.__setattr__(self, name, require_identifier(getattr(self, name), name))
        if (self.series_basis is None) != (self.series_as_of is None):
            raise ValueError("series_basis and series_as_of are both present or both absent.")
        if self.series_basis is not None:
            _require_member(self.series_basis, ContinuousSeriesBasis, "series_basis")
            require_utc_instant(self.series_as_of, "series_as_of")
        checks = _require_tuple_of(self.checks, ContinuousQualityCheck, "checks")
        if tuple(item.name for item in checks) != tuple(ContinuousCheckName):
            raise ValueError("checks must contain one check per ContinuousCheckName, in order.")
        if self.status is not worst_quality_status(item.status for item in checks):
            raise ValueError("status must be the most severe check status.")
        _require_tuple_of(self.overlaps, RollOverlap, "overlaps")
        _require_tuple_of(self.roll_boundaries, RollBoundary, "roll_boundaries")
        for name in ("missing_trading_dates", "calendar_holidays", "unverified_gaps"):
            if not isinstance(getattr(self, name), tuple):
                raise ValueError(f"{name} must be a tuple.")
            values = tuple(require_date(item, name) for item in getattr(self, name))
            if any(left >= right for left, right in zip(values, values[1:])):
                raise ValueError(f"{name} must be strictly increasing.")
            object.__setattr__(self, name, values)
        object.__setattr__(self, "not_established", _require_codes(self.not_established, "not_established"))
