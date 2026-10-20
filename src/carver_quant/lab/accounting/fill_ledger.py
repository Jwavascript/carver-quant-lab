"""체결 장부와 체결 반영 판정 (ADR-0009 R9-9, §6.4a).

순수 함수는 판정만 돌려준다. `HALTED` 같은 Trading State 전이는 하지 않는다 (ADR-0003 §6.5, L3는 shell 책임).
`CONFLICT`가 기록된 장부로는 포지션·손익을 계산하지 않는다 (`FillIntegrityError`).

장부는 `FillLedger.empty()`와 `apply_fill()`로만 만든다 (추가 전용). 직접 생성, `dataclasses.replace`, `copy.replace`는
ValueError, 하위 클래스 정의는 TypeError이므로 기록된 충돌을 지운 장부를 만들 수 없다. 한계: 영속 저장이 없으므로, 호출자가 새 빈 장부에 받은 체결의
일부만 다시 넣는 것은 이 계층에서 알 수 없다. 받은 기록 전체의 보존은 영속 기록(ADR-0009 Q9-9, ADR-0012 Q12-7)의 일이다.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from enum import Enum

from carver_quant.lab.domain.records import (
    FILL_COMPARISON_FIELDS,
    FillOrigin,
    FillRecord,
    FuturesContractSpec,
)
from carver_quant.lab.domain.values import require_identifier


class FillIntegrityError(ValueError):
    """같은 체결 키에 내용이 다른 기록이 있는 장부를 계산에 쓰려 할 때."""


class FillVerdict(Enum):
    APPLIED = "APPLIED"
    DUPLICATE = "DUPLICATE"
    CONFLICT = "CONFLICT"


# 장부 생성 경로를 FillLedger.empty()와 apply_fill()로 제한하는 내부 표식. 생성 뒤에는 None으로 지운다.
_LEDGER_BUILD_TOKEN = object()


def _differing_fields(existing: FillRecord, incoming: FillRecord) -> tuple[str, ...]:
    return tuple(name for name in FILL_COMPARISON_FIELDS if getattr(existing, name) != getattr(incoming, name))


@dataclass(frozen=True)
class FillConflict:
    """무결성 오류의 증거 (불변). 기존 반영 기록과 거부된 재수신 기록, 실제로 다른 필드를 모두 보관한다."""

    existing: FillRecord
    incoming: FillRecord
    differing_fields: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.existing, FillRecord) or not isinstance(self.incoming, FillRecord):
            raise ValueError("a conflict must hold two FillRecord values.")
        if self.incoming.key != self.existing.key:
            raise ValueError("a conflict must compare records with the same key.")
        differing = _differing_fields(self.existing, self.incoming)
        if not differing or self.differing_fields != differing:
            raise ValueError("a conflict must list exactly the fields that differ.")


def _require_valid_for_contract(fill: FillRecord, spec: FuturesContractSpec) -> None:
    if fill.fee_currency != spec.currency:
        raise ValueError("fee_currency must equal the contract currency in Slice 1.")
    if fill.origin is FillOrigin.SIMULATED:
        if spec.lot_size is None:
            raise ValueError("a simulated fill cannot be checked against an unknown lot size.")
        if fill.quantity % spec.lot_size != 0:
            raise ValueError("a simulated fill must be a lot multiple until a simulation policy is approved.")


@dataclass(frozen=True)
class FillLedger:
    """단일 계좌의 반영 체결 장부 (불변). `applied`는 도착 순서이며 키마다 한 건이다.

    `FillLedger.empty()`와 `apply_fill()`로만 만든다. 내부 생성 때도 불변조건을 검사한다: 키당 한 건, 장부 계좌의 체결,
    장부에 있는 월물, 수수료 통화 = 월물 통화, 중복 수신·충돌 기록은 반영된 키에 대한 것.
    """

    account_id: str
    contracts: tuple[FuturesContractSpec, ...]
    applied: tuple[FillRecord, ...]
    duplicates: tuple[FillRecord, ...]
    conflicts: tuple[FillConflict, ...]
    _build_token: object = field(default=None, repr=False, compare=False)

    def __init_subclass__(cls, **kwargs: object) -> None:
        raise TypeError("FillLedger cannot be subclassed; a subclass could skip the ledger checks.")

    def __post_init__(self) -> None:
        if self._build_token is not _LEDGER_BUILD_TOKEN:
            raise ValueError("FillLedger can only be created with FillLedger.empty() and apply_fill().")
        object.__setattr__(self, "_build_token", None)
        object.__setattr__(self, "account_id", require_identifier(self.account_id, "account_id"))
        for name in ("contracts", "applied", "duplicates", "conflicts"):
            if not isinstance(getattr(self, name), tuple):
                raise ValueError(f"{name} must be a tuple.")
        if not self.contracts:
            raise ValueError("contracts must not be empty.")
        if not all(isinstance(spec, FuturesContractSpec) for spec in self.contracts):
            raise ValueError("contracts must contain FuturesContractSpec values.")
        contract_ids = [spec.contract_id for spec in self.contracts]
        if len(set(contract_ids)) != len(contract_ids):
            raise ValueError("contracts must not repeat a contract_id.")
        object.__setattr__(self, "contracts", tuple(sorted(self.contracts, key=lambda spec: spec.contract_id)))

        applied_by_key = {}
        for fill in self.applied:
            if not isinstance(fill, FillRecord):
                raise ValueError("applied must contain FillRecord values.")
            if fill.key.account_id != self.account_id:
                raise ValueError("an applied fill belongs to another account.")
            if fill.key in applied_by_key:
                raise ValueError("an applied fill key appears more than once.")
            _require_valid_for_contract(fill, self.contract(fill.contract_id))
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
    def empty(cls, *, account_id: str, contracts: Iterable[FuturesContractSpec]) -> "FillLedger":
        return cls(
            account_id=account_id,
            contracts=tuple(contracts),
            applied=(),
            duplicates=(),
            conflicts=(),
            _build_token=_LEDGER_BUILD_TOKEN,
        )

    def contract(self, contract_id: str) -> FuturesContractSpec:
        for spec in self.contracts:
            if spec.contract_id == contract_id:
                return spec
        raise ValueError(f"unknown contract_id {contract_id!r} for this ledger.")

    def contract_ids(self) -> frozenset[str]:
        return frozenset(spec.contract_id for spec in self.contracts)

    def require_no_conflicts(self) -> None:
        if self.conflicts:
            raise FillIntegrityError(
                f"ledger has {len(self.conflicts)} conflicting fill record(s); calculation refused."
            )


@dataclass(frozen=True)
class FillApplication:
    verdict: FillVerdict
    ledger: FillLedger
    incoming: FillRecord
    existing: FillRecord | None
    differing_fields: tuple[str, ...]


def apply_fill(ledger: FillLedger, fill: FillRecord) -> FillApplication:
    """체결 기록 하나를 장부에 반영하고 판정을 돌려준다.

    입력: 불변 장부, 새 체결 기록. 출력: 새 장부와 판정 (`APPLIED` / `DUPLICATE` / `CONFLICT`).
    - 멱등 키 (계좌, 출처, 체결 ID)가 처음이면 검증 뒤 `APPLIED`.
    - 같은 키에 비교 필드(`FILL_COMPARISON_FIELDS`)가 모두 같으면 `DUPLICATE`. 반영 체결은 그대로이고 수신만 기록한다.
    - 하나라도 다르면 `CONFLICT`. 다시 반영하지 않고 두 기록을 `FillConflict`로 보관한다.
    예외조건 (ValueError): 다른 계좌의 체결, 장부에 없는 월물, 수수료 통화 ≠ 월물 통화(Slice 1 단일 통화,
    ADR-0001 잠정 가정), lot 배수가 아닌 시뮬레이션 체결 (ADR-0013 R13-1, Q13-5).
    """
    if not isinstance(ledger, FillLedger):
        raise ValueError("ledger must be a FillLedger.")
    if not isinstance(fill, FillRecord):
        raise ValueError("fill must be a FillRecord.")
    if fill.key.account_id != ledger.account_id:
        raise ValueError("fill account_id does not match the ledger account.")

    existing = next((record for record in ledger.applied if record.key == fill.key), None)
    if existing is not None:
        differing = _differing_fields(existing, fill)
        if not differing:
            return FillApplication(
                verdict=FillVerdict.DUPLICATE,
                ledger=replace(ledger, duplicates=ledger.duplicates + (fill,), _build_token=_LEDGER_BUILD_TOKEN),
                incoming=fill,
                existing=existing,
                differing_fields=(),
            )
        conflict = FillConflict(existing=existing, incoming=fill, differing_fields=differing)
        return FillApplication(
            verdict=FillVerdict.CONFLICT,
            ledger=replace(ledger, conflicts=ledger.conflicts + (conflict,), _build_token=_LEDGER_BUILD_TOKEN),
            incoming=fill,
            existing=existing,
            differing_fields=differing,
        )

    _require_valid_for_contract(fill, ledger.contract(fill.contract_id))

    return FillApplication(
        verdict=FillVerdict.APPLIED,
        ledger=replace(ledger, applied=ledger.applied + (fill,), _build_token=_LEDGER_BUILD_TOKEN),
        incoming=fill,
        existing=None,
        differing_fields=(),
    )
