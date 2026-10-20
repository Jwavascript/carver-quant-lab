"""P0-03B Slice 2 주문 기록 (ADR-0009 §5.1, §6.2, §6.4).

주문 상태는 계산 코드가 만들지 않는다. 결과 상태(접수·거부·부분 체결·전량 체결·취소 확정·만료)는 브로커 응답·상태 조회·
체결 통보나 시뮬레이터 확인으로만 생긴다 (ADR-0009 §6.2). 시스템은 주문 의도와 요청 상태(제출·취소·정정 요청)를 기록하고,
결과를 알 수 없으면 UNKNOWN으로 분류한다 (ADR-0012 BR-2). 전체 주문 상태 기계(전이 규칙)는 구현하지 않는다.
"""

from dataclasses import dataclass
from enum import Enum

from carver_quant.lab.domain.values import require_identifier, require_int, require_optional_identifier


class OrderStatus(Enum):
    """ADR-0009 §6.2의 주문 상태 11종."""

    INTENT = "INTENT"
    PENDING_SUBMIT = "PENDING_SUBMIT"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    CANCELLED = "CANCELLED"
    REPLACE_REQUESTED = "REPLACE_REQUESTED"
    EXPIRED = "EXPIRED"
    UNKNOWN = "UNKNOWN"


class OrderStatusSource(Enum):
    """현재 상태를 정한 출처 (Slice 2 표현)."""

    SYSTEM = "SYSTEM"  # 시스템의 행동: 주문 의도 생성, 제출·취소·정정 요청 전송, 결과 불명확 분류
    BROKER = "BROKER"  # 브로커 응답, 상태 조회, 체결 통보
    SIMULATOR = "SIMULATOR"  # Paper 시뮬레이터 또는 백테스트 체결 시뮬레이션의 확인


_CONFIRMED_SOURCES = frozenset({OrderStatusSource.BROKER, OrderStatusSource.SIMULATOR})
_ALL_SOURCES = frozenset(OrderStatusSource)
_ALLOWED_SOURCES = {
    OrderStatus.INTENT: frozenset({OrderStatusSource.SYSTEM}),
    OrderStatus.PENDING_SUBMIT: _ALL_SOURCES,
    OrderStatus.ACCEPTED: _CONFIRMED_SOURCES,
    OrderStatus.REJECTED: _CONFIRMED_SOURCES,
    OrderStatus.PARTIALLY_FILLED: _CONFIRMED_SOURCES,
    OrderStatus.FILLED: _CONFIRMED_SOURCES,
    OrderStatus.CANCEL_REQUESTED: _ALL_SOURCES,
    OrderStatus.CANCELLED: _CONFIRMED_SOURCES,
    OrderStatus.REPLACE_REQUESTED: _ALL_SOURCES,
    OrderStatus.EXPIRED: _CONFIRMED_SOURCES,
    OrderStatus.UNKNOWN: _ALL_SOURCES,
}


def _same_direction_or_zero(value: int, quantity: int) -> bool:
    return value == 0 or (value > 0) == (quantity > 0)


@dataclass(frozen=True, kw_only=True)
class OrderRecord:
    """주문 하나의 현재 기록.

    `quantity`는 부호 있는 정수 주문 수량(매수 +, 매도 −)이다. `filled_quantity`는 확인된 체결 수량의 합,
    `cancelled_quantity`는 확인된 취소 수량이며 둘 다 주문과 같은 부호이거나 0이다. `replacement_quantity`는
    REPLACE_REQUESTED일 때 요청한 정정 수량이고 (RP-1: 새 남은 수량으로 본다), `replacement_client_order_id`는 그 정정
    주문(새 주문)의 Client Order ID다. 정정 응답 timeout으로 UNKNOWN이 된 주문은 두 값을 유지할 수 있다 (RP-5).
    선택 필드도 None을 명시해서 넘긴다.
    """

    account_id: str
    client_order_id: str
    broker_order_id: str | None
    contract_id: str
    quantity: int
    status: OrderStatus
    filled_quantity: int
    cancelled_quantity: int
    replacement_quantity: int | None
    replacement_client_order_id: str | None
    status_source: OrderStatusSource
    status_event_ref: str

    def __post_init__(self) -> None:
        for name in ("account_id", "client_order_id", "contract_id", "status_event_ref"):
            object.__setattr__(self, name, require_identifier(getattr(self, name), name))
        object.__setattr__(self, "broker_order_id", require_optional_identifier(self.broker_order_id, "broker_order_id"))
        quantity = require_int(self.quantity, "quantity")
        if quantity == 0:
            raise ValueError("order quantity must not be zero.")
        filled = require_int(self.filled_quantity, "filled_quantity")
        cancelled = require_int(self.cancelled_quantity, "cancelled_quantity")
        object.__setattr__(self, "quantity", quantity)
        object.__setattr__(self, "filled_quantity", filled)
        object.__setattr__(self, "cancelled_quantity", cancelled)
        if not isinstance(self.status, OrderStatus):
            raise ValueError("status must be an OrderStatus.")
        if not isinstance(self.status_source, OrderStatusSource):
            raise ValueError("status_source must be an OrderStatusSource.")

        if not _same_direction_or_zero(filled, quantity) or not _same_direction_or_zero(cancelled, quantity):
            raise ValueError("filled and cancelled quantities must follow the order direction.")
        if abs(filled) + abs(cancelled) > abs(quantity):
            raise ValueError("filled plus cancelled quantity must not exceed the order quantity.")
        if self.status_source not in _ALLOWED_SOURCES[self.status]:
            raise ValueError(f"status {self.status.name} cannot come from source {self.status_source.name}.")

        has_replacement = self.replacement_quantity is not None or self.replacement_client_order_id is not None
        if self.status is OrderStatus.REPLACE_REQUESTED or (self.status is OrderStatus.UNKNOWN and has_replacement):
            if self.replacement_quantity is None or self.replacement_client_order_id is None:
                raise ValueError("a replace request must carry the replacement quantity and the replacement client order id.")
            replacement = require_int(self.replacement_quantity, "replacement_quantity")
            if replacement == 0 or not _same_direction_or_zero(replacement, quantity):
                raise ValueError("the replacement quantity must be non-zero and follow the order direction.")
            replacement_id = require_identifier(self.replacement_client_order_id, "replacement_client_order_id")
            if replacement_id == self.client_order_id:
                raise ValueError("the replacement order needs its own client order id.")
            object.__setattr__(self, "replacement_quantity", replacement)
            object.__setattr__(self, "replacement_client_order_id", replacement_id)
        elif has_replacement:
            raise ValueError("only a REPLACE_REQUESTED order, or one that became UNKNOWN during the replace, carries a replacement.")

        # ADR-0009 §6.2의 상태 의미와 모순되는 수량은 받지 않는다.
        remaining = quantity - filled - cancelled
        status = self.status
        if status is OrderStatus.INTENT and (filled != 0 or cancelled != 0 or self.broker_order_id is not None):
            raise ValueError("an INTENT has no fills, cancels or broker order id.")
        if status in (OrderStatus.ACCEPTED, OrderStatus.REJECTED) and filled != 0:
            raise ValueError(f"an {status.name} order has no fills.")
        if status is OrderStatus.PARTIALLY_FILLED and (filled == 0 or remaining == 0):
            raise ValueError("a PARTIALLY_FILLED order has some fills and some remaining quantity.")
        if status is OrderStatus.FILLED and filled != quantity:
            raise ValueError("a FILLED order is fully filled.")
        if status is OrderStatus.CANCELLED and remaining != 0:
            raise ValueError("a CANCELLED order has no remaining quantity (fills plus confirmed cancels).")
