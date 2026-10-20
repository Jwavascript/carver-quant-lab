"""거래 전 최악 경우 노출과 명시 한도 비교 (P0-03C Slice 1, ADR-0003 §6.2.2·§6.3·§6.4·§6.5).

ADR-0003 L1의 일부(월물별 최악 경우 수량과 예상 노출)와 그 값의 한도 비교만 한다. 최악 경우 수량은 P0-03B Slice 2의
`prepare_order_candidates`(내부에서 `project_positions`) 결과를 그대로 쓴다. L2 정책 결정(ALLOW / REDUCE_TO_LIMIT /
BLOCK_INCREASE), 검증된 위험 축소(S-1~S-7), 다른 L1 지표(leverage·margin·상품 노출 비율·현금·drawdown·신선도), L3 상태 결정은
하지 않는다. `WITHIN_LIMIT`는 이 검사 항목의 결과이며 주문 제출 승인이 아니다.

검사는 월물 단위다. 같은 상품의 다른 월물이나 상품·계좌 전체의 위험을 판정하지 않으며, 한 월물의 결과로 다른 월물이 안전하다고
보지 않는다. 주문 기록에는 정보 이용 가능 시각이 없으므로 과거 시점의 주문 상태를 PIT로 재현한다고 보장하지 않는다.

배치: Slice 1 한정 계산 보조 모듈로 `lab.accounting`에 둔다. 거래 전 위험 L1·L2의 소유 계층은 ADR-0004 §6.2 표의 Portfolio & Risk
(ADR-0010 §6.2 초안의 `lab.risk`)이고, 그곳에서 이 계산을 쓰려면 미승인 `risk → accounting` 의존(PK-2, Q10-4)이 필요하다.
이 배치는 최종 소유 위치를 정한 것이 아니다 (Q10-4 결정 전까지 OPEN).
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, DecimalException, localcontext
from enum import Enum

from carver_quant.lab.accounting.fill_ledger import FillLedger
from carver_quant.lab.accounting.order_projection import (
    CandidateStatus,
    PreSubmissionReport,
    prepare_order_candidates,
)
from carver_quant.lab.domain.orders import OrderRecord
from carver_quant.lab.domain.records import PositionBaseline, ValuationPrice
from carver_quant.lab.domain.risk import ContractMultiplier, ExposureLimit, TradingState
from carver_quant.lab.domain.values import EXACT_DECIMAL_CONTEXT, require_decimal, require_int, require_utc_instant


class RiskCheckStatus(Enum):
    WITHIN_LIMIT = "WITHIN_LIMIT"  # 이 검사 항목의 한도 안. 주문 제출 승인이 아니다
    LIMIT_EXCEEDED = "LIMIT_EXCEEDED"  # 이 검사 항목의 한도를 넘음
    NOT_ASSESSABLE = "NOT_ASSESSABLE"  # 필요한 정보가 없거나 믿을 수 없어 판정하지 않음


# 이 검사 결과와 관계없이 제출 전에 남는 단계. 이 Slice는 아무것도 승인하지 않는다.
REMAINING_PRE_SUBMISSION_STEPS = (
    "L1_OTHER_RISK_METRICS",  # leverage·margin·상품 노출 비율·현금·drawdown·데이터 신선도 (ADR-0003 §5.4, §6.2.2)
    "L2_POLICY_DECISION",  # ALLOW / REDUCE_TO_LIMIT / BLOCK_INCREASE와 위험 증가·축소 분류 (§6.1, §6.2, Q3-2, Q3-10)
    "VERIFIED_RISK_REDUCTION",  # S-1~S-7 (§6.2.1)
    "L3_TRADING_STATE_GATE",  # 브로커 대조·주문 상태·연결로 정하는 계좌 상태 게이트 (§6.5, Paper/Live)
    "BROKER_SUBMISSION_STEPS",  # 제출 전 기록(BR-3)과 브로커·거래소 주문 제약 (ADR-0012)
)


@dataclass(frozen=True)
class WorstCasePosition:
    """월물 하나의 최악 경우 수량 (계약). `open_*`은 진행 중 주문의 최악 경우 기여분(매수 ≥ 0, 매도 ≤ 0)이다.

    `*_before`는 기존 주문만, `*_after`는 새 주문 후보까지 넣은 값이다 (ADR-0003 §6.3). 후보가 0이면 같고, 후보를 만들지
    않았으면(BLOCKED) None이다.
    """

    contract_id: str
    actual_quantity: int
    open_buy_quantity: int
    open_sell_quantity: int
    candidate_quantity: int | None
    worst_long_before: int
    worst_short_before: int
    worst_long_after: int | None
    worst_short_after: int | None


def worst_case_positions(report: PreSubmissionReport) -> tuple[WorstCasePosition, ...]:
    """Slice 2 결과에서 월물별 최악 경우 수량을 꺼낸다 (계산식을 다시 구현하지 않음).

    기존 주문만의 값은 `project_positions`의 최악 경우(R9-7, RP-1, BR-12), 후보 포함 값은 `prepare_order_candidates`가
    q_long_worst = 기존 롱 + max(후보, 0), q_short_worst = 기존 숏 + min(후보, 0)으로 낸 값이다.
    """
    if not isinstance(report, PreSubmissionReport):
        raise ValueError("report must be a PreSubmissionReport.")
    results = {result.contract_id: result for result in report.results}
    positions = []
    for unit in report.projection.units:
        result = results[unit.contract_id]
        candidate = result.candidate_quantity
        if candidate is None:
            long_after = short_after = None
        elif candidate == 0:
            long_after, short_after = unit.worst_long_quantity, unit.worst_short_quantity
        else:
            long_after, short_after = result.worst_long_after, result.worst_short_after
        positions.append(
            WorstCasePosition(
                contract_id=unit.contract_id,
                actual_quantity=unit.actual_quantity,
                open_buy_quantity=unit.worst_long_quantity - unit.actual_quantity,
                open_sell_quantity=unit.worst_short_quantity - unit.actual_quantity,
                candidate_quantity=candidate,
                worst_long_before=unit.worst_long_quantity,
                worst_short_before=unit.worst_short_quantity,
                worst_long_after=long_after,
                worst_short_after=short_after,
            )
        )
    return tuple(positions)


def projected_exposure(*, worst_long: int, worst_short: int, reference_price: Decimal, multiplier: Decimal) -> Decimal:
    """월물 하나의 예상 노출 (ADR-0003 §6.3).

    공식: max(|q_long_worst|, |q_short_worst|) × |P_ref| × M. 단위: 수량 계약, 가격 pt, 승수 통화/pt/계약, 노출 월물 통화.
    단일 통화 범위라 fx를 곱하지 않는다 (환율을 1로 가정하는 것이 아니라 월물 통화 금액으로 둔다). 음수 선물 가격도 받는다.
    예외조건 (ValueError): 정수가 아닌 수량(bool 포함), Decimal이 아니거나 비유한 가격·승수, 0 이하 승수, 정확한 계산 실패.
    """
    long_quantity = require_int(worst_long, "worst_long")
    short_quantity = require_int(worst_short, "worst_short")
    price = require_decimal(reference_price, "reference_price")
    contract_multiplier = require_decimal(multiplier, "multiplier")
    if contract_multiplier <= 0:
        raise ValueError("multiplier must be greater than 0.")
    try:
        with localcontext(EXACT_DECIMAL_CONTEXT):
            return max(abs(long_quantity), abs(short_quantity)) * abs(price) * contract_multiplier
    except DecimalException as error:
        raise ValueError(f"exact decimal calculation failed: {error!r}") from error


def compare_exposure_to_limit(*, exposure: Decimal, max_exposure: Decimal) -> tuple[RiskCheckStatus, tuple[str, ...]]:
    """예상 노출을 같은 통화의 명시 한도와 비교한다.

    노출 < 한도 → WITHIN_LIMIT, 노출 > 한도 → LIMIT_EXCEEDED. 노출 = 한도이면 NOT_ASSESSABLE(LIMIT_BOUNDARY_RULE_OPEN):
    한도와 같을 때 ≤ / < 중 어느 것을 쓸지는 정해지지 않았다 (ADR-0003 AT-0003-3·AT-0003-4).
    예외조건 (ValueError): Decimal이 아니거나 비유한 값, 음수.
    """
    amount = require_decimal(exposure, "exposure")
    ceiling = require_decimal(max_exposure, "max_exposure")
    if amount < 0 or ceiling < 0:
        raise ValueError("exposure and max_exposure must not be negative.")
    if amount < ceiling:
        return RiskCheckStatus.WITHIN_LIMIT, ()
    if amount > ceiling:
        return RiskCheckStatus.LIMIT_EXCEEDED, ()
    return RiskCheckStatus.NOT_ASSESSABLE, ("LIMIT_BOUNDARY_RULE_OPEN",)


@dataclass(frozen=True)
class PreTradeRiskView:
    """월물 하나의 거래 전 결과 묶음. 로컬 주문 검사, 노출 한도 검사, 상태 차단 사유를 따로 보여 준다.

    전체 주문 승인 상태는 없다. `remaining_steps`는 결과와 관계없이 남은 제출 전 단계다.
    """

    contract_id: str
    worst_case: WorstCasePosition
    currency: str
    reference_price: ValuationPrice | None
    multiplier: Decimal | None
    exposure_before: Decimal | None
    exposure_after: Decimal | None
    max_exposure: Decimal | None
    risk_status: RiskCheckStatus
    risk_reasons: tuple[str, ...]
    local_status: CandidateStatus
    local_reasons: tuple[str, ...]
    state_blocks: tuple[str, ...]
    remaining_steps: tuple[str, ...]


@dataclass(frozen=True)
class PreTradeRiskReport:
    account_id: str
    decision_at: datetime
    trading_state: TradingState
    views: tuple[PreTradeRiskView, ...]

    def view(self, contract_id: str) -> PreTradeRiskView:
        for view in self.views:
            if view.contract_id == contract_id:
                return view
        raise ValueError(f"no risk view for contract {contract_id!r}.")


def _checked_inputs(values: object, kind: type, ledger: FillLedger, name: str) -> dict:
    if not isinstance(values, Mapping):
        raise ValueError(f"{name} must be a mapping of contract_id to {kind.__name__}.")
    known = ledger.contract_ids()
    checked = {}
    for contract_id, value in values.items():
        if contract_id not in known:
            raise ValueError(f"{name} has unknown contract_id {contract_id!r}.")
        if not isinstance(value, kind):
            raise ValueError(f"{name}[{contract_id!r}] must be a {kind.__name__}.")
        if value.contract_id != contract_id:
            raise ValueError(f"{name}[{contract_id!r}] is a record for {value.contract_id!r}.")
        checked[contract_id] = value
    return checked


def assess_pretrade_risk(
    *,
    baseline: PositionBaseline,
    ledger: FillLedger,
    orders: Iterable[OrderRecord],
    targets: Mapping[str, int],
    decision_at: datetime,
    trading_state: TradingState,
    reference_prices: Mapping[str, ValuationPrice],
    multipliers: Mapping[str, ContractMultiplier],
    limits: Mapping[str, ExposureLimit],
) -> PreTradeRiskReport:
    """월물별로 새 주문 후보를 포함한 최악 경우 노출을 계산하고 명시 한도와 비교한다.

    순서: (1) `prepare_order_candidates`(as_of = decision_at)로 실제·진행 중 주문·후보와 로컬 검사를 얻고,
    (2) `worst_case_positions`로 최악 경우 수량을, (3) `projected_exposure`로 기존·후보 포함 노출을,
    (4) `compare_exposure_to_limit`로 한도 결과를 낸다.
    NOT_ASSESSABLE 사유: REFERENCE_PRICE_MISSING, REFERENCE_PRICE_NOT_AVAILABLE_AT_DECISION (`data_available_at` 또는
    가격 시각이 decision_at 뒤, I-1), MULTIPLIER_MISSING, MULTIPLIER_NOT_AVAILABLE_AT_DECISION, CONTRACT_SPEC_MISMATCH (승수·통화가
    월물 사양과 다름), LIMIT_MISSING (§6.2.2: 한도 없는 지표는 판단 불가), FX_MISSING (한도 통화 ≠ 월물 통화), 후보를 만들지 않은
    Slice 2 사유(UNKNOWN_ORDER_PRESENT, REPLACE_PENDING, CANCEL_PENDING), LIMIT_BOUNDARY_RULE_OPEN. 기본값으로 대신하지 않는다.
    상태 차단 (새 주문이 있을 수 있는 월물): HALTED → TRADING_STATE_HALTED (자동 주문 금지), RESTRICTED → TRADING_STATE_RESTRICTED
    (위험 증가 금지. 검증된 위험 축소를 이 Slice가 확인하지 않으므로 축소 후보도 막음). UNKNOWN 주문이 있으면 HALTED 조건이므로
    입력 상태와 관계없이 모든 월물에 UNKNOWN_ORDER_PRESENT (§6.3, §6.5). 상태를 바꾸거나 NORMAL로 되돌리지 않는다.
    예외조건 (ValueError): 시간대 없는 decision_at, TradingState가 아닌 상태, 장부에 없는 월물의 입력, 키와 다른 월물의 기록,
    Slice 2의 예외조건 (decision_at 뒤의 체결, 계좌·월물 불일치 등). 장부 충돌은 FillIntegrityError.
    """
    require_utc_instant(decision_at, "decision_at")
    if not isinstance(trading_state, TradingState):
        raise ValueError("trading_state must be a TradingState.")
    report = prepare_order_candidates(baseline=baseline, ledger=ledger, orders=orders, targets=targets, as_of=decision_at)
    prices = _checked_inputs(reference_prices, ValuationPrice, ledger, "reference_prices")
    contract_multipliers = _checked_inputs(multipliers, ContractMultiplier, ledger, "multipliers")
    contract_limits = _checked_inputs(limits, ExposureLimit, ledger, "limits")
    results = {result.contract_id: result for result in report.results}
    unknown_present = bool(report.projection.unknown_client_order_ids)

    views = []
    for worst in worst_case_positions(report):
        contract_id = worst.contract_id
        spec = ledger.contract(contract_id)
        result = results[contract_id]
        reasons = []

        price = prices.get(contract_id)
        if price is None:
            reasons.append("REFERENCE_PRICE_MISSING")
        elif price.data_available_at > decision_at or price.valuation_at > decision_at:
            reasons.append("REFERENCE_PRICE_NOT_AVAILABLE_AT_DECISION")
        multiplier = contract_multipliers.get(contract_id)
        if multiplier is None:
            reasons.append("MULTIPLIER_MISSING")
        elif multiplier.data_available_at > decision_at:
            reasons.append("MULTIPLIER_NOT_AVAILABLE_AT_DECISION")
        elif multiplier.multiplier != spec.multiplier or multiplier.currency != spec.currency:
            reasons.append("CONTRACT_SPEC_MISMATCH")
        exposure_inputs_usable = not reasons

        limit = contract_limits.get(contract_id)
        if limit is None:
            reasons.append("LIMIT_MISSING")
        elif limit.currency != spec.currency:
            reasons.append("FX_MISSING")
        if worst.candidate_quantity is None:
            reasons.extend(result.reasons)

        exposure_before = exposure_after = None
        if exposure_inputs_usable:
            exposure_before = projected_exposure(
                worst_long=worst.worst_long_before,
                worst_short=worst.worst_short_before,
                reference_price=price.price,
                multiplier=multiplier.multiplier,
            )
            if worst.worst_long_after is not None:
                exposure_after = projected_exposure(
                    worst_long=worst.worst_long_after,
                    worst_short=worst.worst_short_after,
                    reference_price=price.price,
                    multiplier=multiplier.multiplier,
                )

        if reasons:
            status, risk_reasons = RiskCheckStatus.NOT_ASSESSABLE, tuple(reasons)
        else:
            status, risk_reasons = compare_exposure_to_limit(exposure=exposure_after, max_exposure=limit.max_exposure)

        state_blocks = []
        if worst.candidate_quantity != 0:
            if trading_state is TradingState.HALTED:
                state_blocks.append("TRADING_STATE_HALTED")
            elif trading_state is TradingState.RESTRICTED:
                state_blocks.append("TRADING_STATE_RESTRICTED")
        if unknown_present:
            state_blocks.append("UNKNOWN_ORDER_PRESENT")

        views.append(
            PreTradeRiskView(
                contract_id=contract_id,
                worst_case=worst,
                currency=spec.currency,
                reference_price=price,
                multiplier=multiplier.multiplier if multiplier is not None else None,
                exposure_before=exposure_before,
                exposure_after=exposure_after,
                max_exposure=limit.max_exposure if limit is not None else None,
                risk_status=status,
                risk_reasons=risk_reasons,
                local_status=result.status,
                local_reasons=result.reasons,
                state_blocks=tuple(state_blocks),
                remaining_steps=REMAINING_PRE_SUBMISSION_STEPS,
            )
        )

    return PreTradeRiskReport(
        account_id=ledger.account_id, decision_at=decision_at, trading_state=trading_state, views=tuple(views)
    )
