"""ETF 체결 장부와 체결 반영 판정 (P0-03B Slice 4, ADR-0009 R9-9, §6.4a, ADR-0006 I6-4·I6-6).

선물 `FillLedger`와 같은 판정·증거·생성 제한을 ETF 종목 사양(`EtfSpec`)으로 둔 별도 장부다. 체결 기록은 기존 `FillRecord`를
그대로 쓰고(수량 = 주, 가격 = 통화/주), 상품 구분은 이 장부의 사양 타입이 한다. 선물 장부와 선물 손익 계산은 바꾸지 않는다.
장부는 `EtfFillLedger.empty()`와 `apply_etf_fill()`로만 만든다 (직접 생성·`replace`는 ValueError, 하위 클래스는 TypeError).
"""

from collections.abc import Iterable
from dataclasses import dataclass, field, replace

from carver_quant.lab.accounting.fill_ledger import FillConflict, FillIntegrityError, FillVerdict
from carver_quant.lab.domain.records import FILL_COMPARISON_FIELDS, EtfSpec, FillOrigin, FillRecord
from carver_quant.lab.domain.values import require_identifier

# 장부 생성 경로를 EtfFillLedger.empty()와 apply_etf_fill()로 제한하는 내부 표식. 생성 뒤에는 None으로 지운다.
_ETF_FILL_LEDGER_BUILD_TOKEN = object()


def _differing_fields(existing: FillRecord, incoming: FillRecord) -> tuple[str, ...]:
    return tuple(name for name in FILL_COMPARISON_FIELDS if getattr(existing, name) != getattr(incoming, name))


def _require_valid_for_unit(fill: FillRecord, spec: EtfSpec) -> None:
    if fill.price <= 0:
        raise ValueError("an ETF fill price must be positive (currency per share, Slice 4 decision).")
    if fill.fee_currency != spec.currency:
        raise ValueError("fee_currency must equal the ETF currency (ADR-0001 tentative assumption).")
    if fill.origin is FillOrigin.SIMULATED:
        if spec.lot_size is None:
            raise ValueError("a simulated fill cannot be checked against an unknown lot size.")
        if fill.quantity % spec.lot_size != 0:
            raise ValueError("a simulated fill must be a lot multiple until a simulation policy is approved.")


@dataclass(frozen=True)
class EtfFillLedger:
    """단일 계좌의 ETF 반영 체결 장부 (불변). `applied`는 도착 순서이며 키마다 한 건이다.

    내부 생성 때도 불변조건을 검사한다: 키당 한 건, 장부 계좌의 체결, 장부에 있는 종목, 수수료 통화 = ETF 통화,
    시뮬레이션 체결의 lot 배수, 중복 수신·충돌 기록은 반영된 키에 대한 것.
    """

    account_id: str
    units: tuple[EtfSpec, ...]
    applied: tuple[FillRecord, ...]
    duplicates: tuple[FillRecord, ...]
    conflicts: tuple[FillConflict, ...]
    _build_token: object = field(default=None, repr=False, compare=False)

    def __init_subclass__(cls, **kwargs: object) -> None:
        raise TypeError("EtfFillLedger cannot be subclassed; a subclass could skip the ledger checks.")

    def __post_init__(self) -> None:
        if self._build_token is not _ETF_FILL_LEDGER_BUILD_TOKEN:
            raise ValueError("EtfFillLedger can only be created with EtfFillLedger.empty() and apply_etf_fill().")
        object.__setattr__(self, "_build_token", None)
        object.__setattr__(self, "account_id", require_identifier(self.account_id, "account_id"))
        for name in ("units", "applied", "duplicates", "conflicts"):
            if not isinstance(getattr(self, name), tuple):
                raise ValueError(f"{name} must be a tuple.")
        if not self.units:
            raise ValueError("units must not be empty.")
        if not all(isinstance(spec, EtfSpec) for spec in self.units):
            raise ValueError("units must contain EtfSpec values.")
        unit_ids = [spec.unit_id for spec in self.units]
        if len(set(unit_ids)) != len(unit_ids):
            raise ValueError("units must not repeat a unit_id.")
        object.__setattr__(self, "units", tuple(sorted(self.units, key=lambda spec: spec.unit_id)))

        applied_by_key = {}
        for fill in self.applied:
            if not isinstance(fill, FillRecord):
                raise ValueError("applied must contain FillRecord values.")
            if fill.key.account_id != self.account_id:
                raise ValueError("an applied fill belongs to another account.")
            if fill.key in applied_by_key:
                raise ValueError("an applied fill key appears more than once.")
            _require_valid_for_unit(fill, self.unit(fill.contract_id))
            applied_by_key[fill.key] = fill

        for fill in self.duplicates:
            if not isinstance(fill, FillRecord):
                raise ValueError("duplicates must contain FillRecord values.")
            existing = applied_by_key.get(fill.key)
            if existing is None or _differing_fields(existing, fill):
                raise ValueError("a duplicate record must equal an applied fill with the same key.")

        for conflict in self.conflicts:
            if not isinstance(conflict, FillConflict):
                raise ValueError("conflicts must contain FillConflict values.")
            if applied_by_key.get(conflict.existing.key) != conflict.existing:
                raise ValueError("a conflict must refer to the applied fill with the same key.")

    @classmethod
    def empty(cls, *, account_id: str, units: Iterable[EtfSpec]) -> "EtfFillLedger":
        return cls(
            account_id=account_id,
            units=tuple(units),
            applied=(),
            duplicates=(),
            conflicts=(),
            _build_token=_ETF_FILL_LEDGER_BUILD_TOKEN,
        )

    def unit(self, unit_id: str) -> EtfSpec:
        for spec in self.units:
            if spec.unit_id == unit_id:
                return spec
        raise ValueError(f"unknown unit {unit_id!r} for this ledger.")

    def contract_ids(self) -> frozenset[str]:
        """거래 단위(ETF 종목) ID. `FillLedger`·`PositionBaseline`과 같은 이름이라 `actual_position`이 그대로 쓴다."""
        return frozenset(spec.unit_id for spec in self.units)

    def require_no_conflicts(self) -> None:
        if self.conflicts:
            raise FillIntegrityError(f"ledger has {len(self.conflicts)} conflicting fill record(s); calculation refused.")


@dataclass(frozen=True)
class EtfFillApplication:
    verdict: FillVerdict
    ledger: EtfFillLedger
    incoming: FillRecord
    existing: FillRecord | None
    differing_fields: tuple[str, ...]


def apply_etf_fill(ledger: EtfFillLedger, fill: FillRecord) -> EtfFillApplication:
    """ETF 체결 기록 하나를 장부에 반영하고 판정을 돌려준다 (선물 `apply_fill`과 같은 규칙).

    - 멱등 키 (계좌, 출처, 체결 ID)가 처음이면 검증 뒤 `APPLIED`.
    - 같은 키에 비교 필드(`FILL_COMPARISON_FIELDS`)가 모두 같으면 `DUPLICATE`. 반영 체결은 그대로이고 수신만 기록한다.
    - 하나라도 다르면 `CONFLICT`. 다시 반영하지 않고 두 기록을 `FillConflict`로 보관한다.
    예외조건 (ValueError): 다른 계좌의 체결, 장부에 없는 종목, 0 이하 체결 가격 (Slice 4 결정, 선물 가격 규칙은 그대로),
    수수료 통화 ≠ ETF 통화 (ADR-0001 잠정 가정),
    lot 배수가 아니거나 lot size를 모르는 시뮬레이션 체결 (ADR-0013 R13-1, Q13-5).
    """
    if not isinstance(ledger, EtfFillLedger):
        raise ValueError("ledger must be an EtfFillLedger.")
    if not isinstance(fill, FillRecord):
        raise ValueError("fill must be a FillRecord.")
    if fill.key.account_id != ledger.account_id:
        raise ValueError("fill account_id does not match the ledger account.")

    existing = next((record for record in ledger.applied if record.key == fill.key), None)
    if existing is not None:
        differing = _differing_fields(existing, fill)
        if not differing:
            return EtfFillApplication(
                verdict=FillVerdict.DUPLICATE,
                ledger=replace(ledger, duplicates=ledger.duplicates + (fill,), _build_token=_ETF_FILL_LEDGER_BUILD_TOKEN),
                incoming=fill,
                existing=existing,
                differing_fields=(),
            )
        conflict = FillConflict(existing=existing, incoming=fill, differing_fields=differing)
        return EtfFillApplication(
            verdict=FillVerdict.CONFLICT,
            ledger=replace(ledger, conflicts=ledger.conflicts + (conflict,), _build_token=_ETF_FILL_LEDGER_BUILD_TOKEN),
            incoming=fill,
            existing=existing,
            differing_fields=differing,
        )

    _require_valid_for_unit(fill, ledger.unit(fill.contract_id))

    return EtfFillApplication(
        verdict=FillVerdict.APPLIED,
        ledger=replace(ledger, applied=ledger.applied + (fill,), _build_token=_ETF_FILL_LEDGER_BUILD_TOKEN),
        incoming=fill,
        existing=None,
        differing_fields=(),
    )
