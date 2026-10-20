"""P0-03B Slice 1 도메인 기록: 선물 월물 사양, 체결 기록, 검증된 기준 포지션, raw 평가가격.

이름은 V1 타입(`InstrumentSpec`, `execution.Fill` 등)과 겹치지 않게 정했다 (D3A-01, ADR-0010 PK-12).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum

from carver_quant.lab.domain.values import (
    require_decimal,
    require_identifier,
    require_int,
    require_optional_identifier,
    require_utc_instant,
)


@dataclass(frozen=True, kw_only=True)
class FuturesContractSpec:
    """선물 월물 하나의 사양. 승수 `M[c]`는 그 월물의 값만 쓴다 (ADR-0001 §6.2, I6-6).

    `lot_size`는 참조 데이터다. 값이 없으면 None을 명시하며, 1로 가정하지 않는다 (I6-11).
    """

    contract_id: str
    instrument_id: str
    currency: str
    multiplier: Decimal
    lot_size: int | None

    def __post_init__(self) -> None:
        for name in ("contract_id", "instrument_id", "currency"):
            object.__setattr__(self, name, require_identifier(getattr(self, name), name))
        multiplier = require_decimal(self.multiplier, "multiplier")
        if multiplier <= 0:
            raise ValueError("multiplier must be greater than 0.")
        object.__setattr__(self, "multiplier", multiplier)
        if self.lot_size is not None:
            lot_size = require_int(self.lot_size, "lot_size")
            if lot_size < 1:
                raise ValueError("lot_size must be at least 1.")
            object.__setattr__(self, "lot_size", lot_size)


class FillOrigin(Enum):
    BROKER_REPORTED = "BROKER_REPORTED"
    SIMULATED = "SIMULATED"


@dataclass(frozen=True)
class FillKey:
    """체결 멱등 키 (계좌, 체결 정보 출처, 체결 ID) (ADR-0009 §6.4a)."""

    account_id: str
    fill_source: str
    fill_id: str

    def __post_init__(self) -> None:
        for name in ("account_id", "fill_source", "fill_id"):
            object.__setattr__(self, name, require_identifier(getattr(self, name), name))


@dataclass(frozen=True, kw_only=True)
class FillRecord:
    """실제 또는 시뮬레이션 체결 한 건 (ADR-0009 R9-3, §6.4a).

    `quantity`는 부호 있는 정수 계약 수(매수 +, 매도 −), `price`는 raw 체결가 `F[k]`(pt),
    `fee`는 `fee_currency` 단위 수수료다. 선택 필드(`broker_order_id`, `venue`, `liquidity_flag`)도
    값이 없으면 None을 명시해서 넘긴다.
    """

    key: FillKey
    client_order_id: str
    broker_order_id: str | None
    contract_id: str
    quantity: int
    price: Decimal
    fill_at: datetime
    fee: Decimal
    fee_currency: str
    origin: FillOrigin
    execution_assumption_ref: str | None
    venue: str | None
    liquidity_flag: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.key, FillKey):
            raise ValueError("key must be a FillKey.")
        # 하위 클래스 키가 같은 값의 키와 다르게 비교되어 멱등성을 우회하지 않도록 정확한 FillKey로 다시 만든다.
        object.__setattr__(
            self,
            "key",
            FillKey(account_id=self.key.account_id, fill_source=self.key.fill_source, fill_id=self.key.fill_id),
        )
        for name in ("client_order_id", "contract_id", "fee_currency"):
            object.__setattr__(self, name, require_identifier(getattr(self, name), name))
        for name in ("broker_order_id", "execution_assumption_ref", "venue", "liquidity_flag"):
            object.__setattr__(self, name, require_optional_identifier(getattr(self, name), name))
        quantity = require_int(self.quantity, "quantity")
        if quantity == 0:
            raise ValueError("quantity must not be zero.")
        object.__setattr__(self, "quantity", quantity)
        object.__setattr__(self, "price", require_decimal(self.price, "price"))
        require_utc_instant(self.fill_at, "fill_at")
        fee = require_decimal(self.fee, "fee")
        if fee < 0:
            raise ValueError("fee must not be negative.")
        object.__setattr__(self, "fee", fee)
        if not isinstance(self.origin, FillOrigin):
            raise ValueError("origin must be a FillOrigin.")
        if self.origin is FillOrigin.SIMULATED and self.execution_assumption_ref is None:
            raise ValueError("a simulated fill must reference its execution assumption.")
        if self.origin is FillOrigin.BROKER_REPORTED and self.execution_assumption_ref is not None:
            raise ValueError("a broker-reported fill must not reference an execution assumption.")


# 같은 멱등 키의 재수신을 비교할 필드. ADR-0009 §6.4a의 비교 대상 전부와 체결 출처 구분을 포함한다.
FILL_COMPARISON_FIELDS = (
    "client_order_id",
    "broker_order_id",
    "contract_id",
    "quantity",
    "price",
    "fill_at",
    "fee",
    "fee_currency",
    "venue",
    "liquidity_flag",
    "origin",
    "execution_assumption_ref",
)


@dataclass(frozen=True, kw_only=True)
class PositionBaseline:
    """검증된 기준 포지션 (ADR-0009 R9-2, ADR-0013 R13-3).

    검증 절차는 구현하지 않는다 (Q13-2). 호출자가 검증 근거를 `verification_ref`로 명시한다.
    `quantities`는 월물 ID별 정수 계약 수이며 0도 명시한다. 생성 시 Mapping 또는 (월물, 수량) 쌍을 받아
    월물 ID 순으로 정렬한 tuple로 저장한다.
    """

    account_id: str
    as_of: datetime
    quantities: tuple[tuple[str, int], ...]
    verification_ref: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "account_id", require_identifier(self.account_id, "account_id"))
        require_utc_instant(self.as_of, "as_of")
        object.__setattr__(self, "verification_ref", require_identifier(self.verification_ref, "verification_ref"))
        if isinstance(self.quantities, Mapping):
            pairs = tuple(self.quantities.items())
        elif isinstance(self.quantities, tuple) and all(isinstance(pair, tuple) and len(pair) == 2 for pair in self.quantities):
            pairs = self.quantities
        else:
            raise ValueError("quantities must be a mapping or a tuple of (contract_id, int) pairs.")
        items = []
        for contract_id, quantity in pairs:
            items.append((require_identifier(contract_id, "contract_id"), require_int(quantity, "baseline quantity")))
        if len({contract_id for contract_id, _ in items}) != len(items):
            raise ValueError("quantities must not repeat a contract_id.")
        object.__setattr__(self, "quantities", tuple(sorted(items)))

    def contract_ids(self) -> frozenset[str]:
        return frozenset(contract_id for contract_id, _ in self.quantities)

    def quantity(self, contract_id: str) -> int:
        for known_id, quantity in self.quantities:
            if known_id == contract_id:
                return quantity
        raise ValueError(f"baseline has no quantity for contract {contract_id!r}.")


@dataclass(frozen=True, kw_only=True)
class ValuationPrice:
    """사용자가 지정한 월물별 raw 평가가격 `V[c,t]` (pt).

    평가가격 선택 정책은 구현하지 않는다 (Q1-2, Q7-3, Q7-4). `valuation_at`은 이 가격이 나타내는 평가 시각,
    `data_available_at`은 이 값을 실제로 쓸 수 있게 된 시각이다.
    """

    contract_id: str
    price: Decimal
    valuation_at: datetime
    data_available_at: datetime
    source_ref: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "contract_id", require_identifier(self.contract_id, "contract_id"))
        object.__setattr__(self, "price", require_decimal(self.price, "price"))
        require_utc_instant(self.valuation_at, "valuation_at")
        require_utc_instant(self.data_available_at, "data_available_at")
        object.__setattr__(self, "source_ref", require_identifier(self.source_ref, "source_ref"))
