"""실제 포지션 계산 (ADR-0009 R9-2, R9-13). 선물 월물 장부와 Slice 4의 ETF 체결 장부에 같은 식을 쓴다."""

from datetime import datetime

from carver_quant.lab.accounting.etf_fill_ledger import EtfFillLedger
from carver_quant.lab.accounting.fill_ledger import FillLedger
from carver_quant.lab.domain.records import PositionBaseline
from carver_quant.lab.domain.values import require_utc_instant


def actual_position(baseline: PositionBaseline, ledger: FillLedger | EtfFillLedger, as_of: datetime) -> dict[str, int]:
    """거래 단위별 실제 수량을 계산한다 (선물: 월물별 계약 수, Slice 4의 ETF: 종목별 주 수).

    공식: A[c](as_of) = 기준[c] + Σ { Δq[k] : c(k) = c, T0 < fill_at[k] ≤ as_of } (R9-2). T0 = baseline.as_of.
    입력: 검증된 기준 포지션(장부의 모든 거래 단위를 0 포함해 명시), 반영 체결 장부(선물 FillLedger 또는 EtfFillLedger),
    계산 기준 시각 (UTC). 출력: 거래 단위 ID → 정수 수량. 거래 단위끼리 합치지 않는다 (I6-3).
    전제조건: 장부의 각 키는 한 번만 반영되어 있다 (apply_fill). fill_at < T0인 체결은 기준에 이미 들어 있다 (AT-0013-11).
    예외조건: fill_at = T0인 체결 (Q13-2 미결정이므로 거부), as_of < T0, 계좌 불일치, 기준과 장부의 월물 불일치는
    ValueError. 장부에 CONFLICT가 있으면 FillIntegrityError.
    """
    if not isinstance(baseline, PositionBaseline):
        raise ValueError("baseline must be a PositionBaseline.")
    if not isinstance(ledger, (FillLedger, EtfFillLedger)):
        raise ValueError("ledger must be a FillLedger or an EtfFillLedger.")
    require_utc_instant(as_of, "as_of")
    if baseline.account_id != ledger.account_id:
        raise ValueError("baseline account_id does not match the ledger account.")
    ledger.require_no_conflicts()
    if baseline.contract_ids() != ledger.contract_ids():
        raise ValueError("baseline must list exactly the ledger contracts (use 0 for no position).")
    if as_of < baseline.as_of:
        raise ValueError("as_of must not be earlier than the baseline time.")

    positions = {contract_id: quantity for contract_id, quantity in baseline.quantities}
    for fill in ledger.applied:
        if fill.fill_at == baseline.as_of:
            raise ValueError("a fill at exactly the baseline time is not supported until Q13-2 is decided.")
        if baseline.as_of < fill.fill_at <= as_of:
            positions[fill.contract_id] += fill.quantity
    return positions
