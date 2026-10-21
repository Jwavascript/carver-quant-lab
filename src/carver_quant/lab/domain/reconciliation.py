"""P0-03C Slice 5 브로커 주문 Snapshot과 주문 대조 결과 (ADR-0012 BF-3·BF-4·BF-11·BR-4·BR-6·BR-7·BR-10·§6.3a, ADR-0009 R9-4·R9-8·
R9-13, ADR-0003 S-3·§6.5, ADR-0013 R13-1a).

브로커 Snapshot은 호출 경계가 명시적으로 넘기는 외부 보고다. 이 모듈은 그 진위와 브로커 시각의 의미(시점 기록 `as_of`인지)를 확인하지
않는다 (신뢰 경계 입력). 출처 표시(BROKER / SIMULATOR) 검사는 입력값 검사일 뿐 브로커 인증이 아니다. 완전성은 호출 경계가 근거 참조와
함께 하는 선언이며, 그 범위에서 보이지 않는 주문을 불일치로 보고하는 데만 쓴다 (일치·해소의 근거로 쓰지 않음). 실험용 입력을 운영상
검증된 증거로 올리지 않는다.
대조 결과는 비교한 항목의 일치(MATCH), 불일치(MISMATCH), 확인 불가(UNVERIFIED)만 말한다. MATCH는 주문 전송 가능, Trading State NORMAL,
UNKNOWN 해소, 대조 완료(HALTED 해제 조건)를 뜻하지 않는다 (`RECONCILIATION_NOT_ESTABLISHED`).
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from carver_quant.lab.domain.orders import OrderRecord, OrderStatus, OrderStatusSource
from carver_quant.lab.domain.values import require_identifier, require_int, require_optional_identifier, require_utc_instant


class BrokerSnapshotScope(Enum):
    """Snapshot이 무엇에 대한 보고인가. 범위 밖의 주문에 대해서는 아무것도 말하지 않는다. 체결 목록(BF-5)은 이 Slice에서 표현하지 않는다."""

    ORDER_QUERY = "ORDER_QUERY"  # 특정 주문 조회 결과 (BF-4, BF-11). 찾지 못함은 주문이 없다는 증거가 아니다 (BR-4)
    OPEN_ORDERS = "OPEN_ORDERS"  # 계좌의 미체결 주문 목록 (BF-3)
    ACCOUNT_ORDERS = "ACCOUNT_ORDERS"  # 계좌의 주문 기록 전체 (종료 주문 포함)


class BrokerSnapshotCompleteness(Enum):
    COMPLETE_FOR_SCOPE = "COMPLETE_FOR_SCOPE"  # 그 범위의 완전한 목록이라고 호출 경계가 근거 참조와 함께 선언. 브로커의 보장은 검증하지 않음 (§6.3a)
    UNVERIFIED = "UNVERIFIED"  # 완전성을 선언하지 않음. 목록에 없는 주문을 불일치로 보지 않는다


class ReconciliationStatus(Enum):
    MATCH = "MATCH"  # 실제로 비교한 값이 같다. 비교하지 않은 것에 대해서는 아무것도 말하지 않는다
    MISMATCH = "MISMATCH"  # 비교한 값이 다르거나 한쪽에만 있다. 설명된 차이로 보지 않는다 (ADR-0012 BR-10)
    UNVERIFIED = "UNVERIFIED"  # 판단할 근거가 없다


# 주문 대조가 확인하지 않는 것. 보고서가 MATCH여도 이 항목들은 따로 확인해야 한다.
RECONCILIATION_NOT_ESTABLISHED = (
    "ACTUAL_POSITION",  # 실제 보유. 주문별 누적 체결이 같아도 기준 포지션·Journal 밖 체결 때문에 포지션 일치를 뜻하지 않는다 (R9-8, S-3)
    "FILL_RECORDS",  # 체결 목록과 FillLedger의 체결 단위 대조 (R9-9)
    "CASH",  # 현금·결제 대조
    "ORDERS_OUTSIDE_SNAPSHOT_SCOPE",  # 범위 밖이거나, 완전성이 선언되지 않은 목록에서 보이지 않는 주문
    "SNAPSHOT_TIME_MEANING",  # 브로커 시각이 시점 기록 as_of인지 (BR-7, §6.3a). 확인 전의 일치는 약한 일치다 (Q12-15)
    "BROKER_AUTHENTICITY",  # 보고가 실제 브로커에서 왔는지. 출처 표시만 검사한다
    "UNKNOWN_RESOLUTION",  # 대조는 UNKNOWN을 해소하지 않는다 (R9-4, Q12-14)
    "TRADING_STATE_RELEASE",  # 대조 완료와 HALTED 해제(원인 해소 + 대조 완료 + 사용자 승인)를 판단하지 않는다 (ADR-0003 §6.5)
)

_OPEN_STATUSES = frozenset({
    OrderStatus.PENDING_SUBMIT,
    OrderStatus.ACCEPTED,
    OrderStatus.PARTIALLY_FILLED,
    OrderStatus.CANCEL_REQUESTED,
    OrderStatus.REPLACE_REQUESTED,
    OrderStatus.UNKNOWN,
})


def _same_direction_or_zero(value: int, quantity: int) -> bool:
    return value == 0 or (value > 0) == (quantity > 0)


@dataclass(frozen=True, kw_only=True)
class BrokerOrderReport:
    """브로커가 보고한 주문 하나 (BF-3·BF-4 응답의 한 줄을 Adapter가 ADR-0009 §6.2 상태로 번역한 값. 번역할 수 없으면 UNKNOWN, BR-6).

    수량은 부호 있는 정수다 (매수 +, 매도 −). `filled_quantity`는 브로커가 보고한 누적 체결, `remaining_quantity`는 현재 미체결 잔량이며
    둘 다 주문과 같은 부호이거나 0이다. 둘의 합이 주문 수량보다 작으면 나머지는 보고된 그대로 둔다 (취소나 체결로 추정하지 않음).
    lot 배수는 요구하지 않는다 (ADR-0013 R13-1a). 정수가 아닌 보고는 이 타입으로 표현하지 않는다. Client Order ID는 브로커가 돌려줄
    때만 있다 (BF-3). 선택 필드도 None을 명시해서 넘긴다.
    """

    client_order_id: str | None
    broker_order_id: str
    contract_id: str
    quantity: int
    filled_quantity: int
    remaining_quantity: int
    status: OrderStatus

    def __post_init__(self) -> None:
        object.__setattr__(self, "client_order_id", require_optional_identifier(self.client_order_id, "client_order_id"))
        for name in ("broker_order_id", "contract_id"):
            object.__setattr__(self, name, require_identifier(getattr(self, name), name))
        quantity = require_int(self.quantity, "quantity")
        filled = require_int(self.filled_quantity, "filled_quantity")
        remaining = require_int(self.remaining_quantity, "remaining_quantity")
        if quantity == 0:
            raise ValueError("order quantity must not be zero.")
        if not _same_direction_or_zero(filled, quantity) or not _same_direction_or_zero(remaining, quantity):
            raise ValueError("filled and remaining quantities must follow the order direction.")
        if abs(filled) + abs(remaining) > abs(quantity):
            raise ValueError("filled plus remaining quantity must not exceed the order quantity.")
        object.__setattr__(self, "quantity", quantity)
        object.__setattr__(self, "filled_quantity", filled)
        object.__setattr__(self, "remaining_quantity", remaining)
        if not isinstance(self.status, OrderStatus):
            raise ValueError("status must be an OrderStatus.")

        # ADR-0009 §6.2의 상태 의미와 모순되는 보고는 받지 않는다 (OrderRecord와 같은 규칙을 보고된 잔량에 적용).
        status = self.status
        if status is OrderStatus.INTENT:
            raise ValueError("a broker report cannot carry INTENT, which is a system-only state.")
        if status in (OrderStatus.ACCEPTED, OrderStatus.PENDING_SUBMIT) and (filled != 0 or remaining == 0):
            raise ValueError(f"an {status.name} order has no fills and some remaining quantity.")
        if status is OrderStatus.PARTIALLY_FILLED and (filled == 0 or remaining == 0):
            raise ValueError("a PARTIALLY_FILLED order has some fills and some remaining quantity.")
        if status is OrderStatus.FILLED and (filled != quantity or remaining != 0):
            raise ValueError("a FILLED order is fully filled with nothing remaining.")
        if status in (OrderStatus.CANCELLED, OrderStatus.EXPIRED) and remaining != 0:
            raise ValueError(f"a {status.name} order has no remaining quantity.")
        if status is OrderStatus.REJECTED and (filled != 0 or remaining != 0):
            raise ValueError("a REJECTED order has no fills and no remaining quantity.")


@dataclass(frozen=True, kw_only=True)
class BrokerOrderSnapshot:
    """한 계좌에 대한 브로커 주문 보고 묶음 (한 출처, 한 범위).

    `observed_at`은 보고가 관측된 브로커 쪽 시각, `available_at`은 시스템이 그 보고를 이용할 수 있게 된 시각이다 (BR-7, ADR-0001 I-1:
    관측 ≤ 이용 가능). 관측 시각이 시점 기록 `as_of`라는 보장은 확인하지 않는다 (§6.3a). 주문 조회(ORDER_QUERY)는 조회한 Client Order
    ID를 함께 담고, 찾지 못함이 부재의 증거가 아니므로 완전하다고 선언할 수 없다 (BR-4). 미체결 목록은 미체결 주문만 담는다.
    같은 Client Order ID나 Broker Order ID가 두 줄에 나오면 어느 쪽이 맞는지 고르지 않고 거부한다. 선택 필드도 None을 명시해서 넘긴다.
    """

    snapshot_id: str
    account_id: str
    source: OrderStatusSource
    scope: BrokerSnapshotScope
    queried_client_order_ids: tuple[str, ...]
    completeness: BrokerSnapshotCompleteness
    completeness_ref: str | None
    observed_at: datetime
    available_at: datetime
    orders: tuple[BrokerOrderReport, ...]

    def __post_init__(self) -> None:
        for name in ("snapshot_id", "account_id"):
            object.__setattr__(self, name, require_identifier(getattr(self, name), name))
        if self.source not in (OrderStatusSource.BROKER, OrderStatusSource.SIMULATOR):
            raise ValueError("a broker snapshot comes from a BROKER or a SIMULATOR.")
        if not isinstance(self.scope, BrokerSnapshotScope):
            raise ValueError("scope must be a BrokerSnapshotScope.")
        if not isinstance(self.completeness, BrokerSnapshotCompleteness):
            raise ValueError("completeness must be a BrokerSnapshotCompleteness.")
        if self.completeness is BrokerSnapshotCompleteness.COMPLETE_FOR_SCOPE:
            object.__setattr__(self, "completeness_ref", require_identifier(self.completeness_ref, "completeness_ref"))
        else:
            object.__setattr__(self, "completeness_ref", require_optional_identifier(self.completeness_ref, "completeness_ref"))
        require_utc_instant(self.observed_at, "observed_at")
        require_utc_instant(self.available_at, "available_at")
        if self.observed_at > self.available_at:
            raise ValueError("a broker snapshot cannot be available before it was observed (ADR-0001 I-1).")
        if not isinstance(self.queried_client_order_ids, tuple) or not isinstance(self.orders, tuple):
            raise ValueError("queried_client_order_ids and orders must be tuples.")
        queried = tuple(require_identifier(value, "queried_client_order_ids") for value in self.queried_client_order_ids)
        object.__setattr__(self, "queried_client_order_ids", queried)
        if len(set(queried)) != len(queried):
            raise ValueError("an order query names each queried order once.")
        for order in self.orders:
            if not isinstance(order, BrokerOrderReport):
                raise ValueError("orders must contain BrokerOrderReport values.")
        client_ids = [order.client_order_id for order in self.orders if order.client_order_id is not None]
        broker_ids = [order.broker_order_id for order in self.orders]
        if len(set(client_ids)) != len(client_ids) or len(set(broker_ids)) != len(broker_ids):
            raise ValueError("each client order id and broker order id appears at most once in a snapshot.")

        if self.scope is BrokerSnapshotScope.ORDER_QUERY:
            if not queried:
                raise ValueError("an order query names the orders it asked about.")
            if self.completeness is BrokerSnapshotCompleteness.COMPLETE_FOR_SCOPE:
                raise ValueError("an order query cannot be complete: not found is not proof of absence (ADR-0012 BR-4).")
            if any(order.client_order_id not in queried for order in self.orders):
                raise ValueError("an order query result names one of the queried client order ids.")
        elif queried:
            raise ValueError("only an order query names queried orders.")
        if self.scope is BrokerSnapshotScope.OPEN_ORDERS and any(order.status not in _OPEN_STATUSES for order in self.orders):
            raise ValueError("an open-orders listing holds only open orders.")


@dataclass(frozen=True, kw_only=True)
class FieldComparison:
    """필드 하나의 비교. 수량 필드의 `difference`는 브로커 값 − 로컬 값이고, 다른 필드에서는 None이다."""

    name: str
    local_value: str | int | None
    broker_value: str | int | None
    status: ReconciliationStatus
    reason: str | None
    difference: int | None


@dataclass(frozen=True, kw_only=True)
class OrderReconciliation:
    """주문 하나의 대조. `local`은 결정 시점 로컬 Snapshot의 기록, `broker`는 브로커 보고 그대로다 (어느 쪽도 고치거나 만들지 않음).
    한쪽에만 있는 주문은 다른 쪽이 None이고 비교한 필드가 없다."""

    client_order_id: str | None
    broker_order_id: str | None
    local: OrderRecord | None
    broker: BrokerOrderReport | None
    status: ReconciliationStatus
    reasons: tuple[str, ...]
    fields: tuple[FieldComparison, ...]

    def field(self, name: str) -> FieldComparison:
        for compared in self.fields:
            if compared.name == name:
                return compared
        raise KeyError(name)


@dataclass(frozen=True, kw_only=True)
class OrderReconciliationReport:
    """결정 시점의 주문 대조. `status`는 대조한 주문 전체의 요약이다: 불일치가 하나라도 있으면 MISMATCH, 그렇지 않고 확인 불가인 주문이
    있거나 Snapshot을 쓸 수 없거나 목록·로컬 기록의 완전성이 확인되지 않았으면 UNVERIFIED (`reasons`), 그 밖에는 MATCH.
    MATCH도 Snapshot 관측 시각에 비교한 범위의 주문에 대한 약한 일치일 뿐이다 (`not_established`). 관측 시각이 얼마나 오래되어도 되는지는
    정하지 않는다."""

    account_id: str
    decision_at: datetime
    snapshot_id: str
    snapshot_observed_at: datetime
    snapshot_available_at: datetime
    scope: BrokerSnapshotScope
    status: ReconciliationStatus
    reasons: tuple[str, ...]
    orders: tuple[OrderReconciliation, ...]
    not_established: tuple[str, ...]

    def order(self, client_order_id: str) -> OrderReconciliation:
        for order in self.orders:
            if order.client_order_id == client_order_id:
                return order
        raise KeyError(client_order_id)
