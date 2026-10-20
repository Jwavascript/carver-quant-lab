"""P0-03B Gate A: 충돌 기록 무결성 (ADR-0009 R9-9, §6.4a).

충돌 증거를 지운 장부를 정상 장부로 쓰지 못하게 한다. 장부는 FillLedger.empty()와 apply_fill()로만 만들 수 있다.
영속 저장이 없으므로, 호출자가 새 빈 장부에 일부 체결만 다시 넣는 것(받은 기록을 넣지 않는 것)은 이 계층에서 막을 수 없다.
"""

import copy
import dataclasses
from datetime import datetime, timezone

import pytest

from carver_quant.lab.accounting import fill_ledger as fill_ledger_module
from carver_quant.lab.accounting.fill_ledger import (
    FillConflict,
    FillIntegrityError,
    FillLedger,
    FillVerdict,
    apply_fill,
)
from carver_quant.lab.accounting.positions import actual_position
from carver_quant.lab.accounting.trading_pnl import period_trading_pnl
from carver_quant.lab.domain.records import (
    FillKey,
    FillOrigin,
    FillRecord,
    FuturesContractSpec,
    PositionBaseline,
    ValuationPrice,
)

UTC = timezone.utc
C1 = "FUT.ALPHA.C1"
T0 = datetime(2026, 10, 19, 0, 0, tzinfo=UTC)
AS_OF = datetime(2026, 10, 20, 20, 0, tzinfo=UTC)


def contract():
    return FuturesContractSpec(contract_id=C1, instrument_id="FUT.ALPHA", currency="USD", multiplier="10", lot_size=1)


def make_fill(fill_id="X-1", quantity=2, fill_at=datetime(2026, 10, 20, 14, 0, tzinfo=UTC)):
    return FillRecord(
        key=FillKey(account_id="A1", fill_source="BRK", fill_id=fill_id),
        client_order_id="C-1",
        broker_order_id="B-1",
        contract_id=C1,
        quantity=quantity,
        price="101",
        fill_at=fill_at,
        fee="2",
        fee_currency="USD",
        origin=FillOrigin.BROKER_REPORTED,
        execution_assumption_ref=None,
        venue=None,
        liquidity_flag=None,
    )


def conflicting_ledger():
    ledger = apply_fill(FillLedger.empty(account_id="A1", contracts=(contract(),)), make_fill()).ledger
    result = apply_fill(ledger, make_fill(quantity=3))
    assert result.verdict is FillVerdict.CONFLICT
    return result.ledger


def baseline():
    return PositionBaseline(account_id="A1", as_of=T0, quantities={C1: 0}, verification_ref="fixture:verified")


def test_conflict_cannot_be_removed_with_dataclasses_replace():
    """입력: CONFLICT가 기록된 장부에 dataclasses.replace(ledger, conflicts=()).
    출력: ValueError. 충돌 증거를 지운 장부가 만들어지지 않는다 (재현: 수정 전에는 장부가 만들어지고 포지션 +2가 계산됐다)."""
    ledger = conflicting_ledger()
    with pytest.raises(ValueError, match="can only be created"):
        dataclasses.replace(ledger, conflicts=())


def test_conflict_cannot_be_removed_with_copy_replace():
    """입력: copy.replace(ledger, conflicts=()) (Python 3.13+의 표준 복사·수정 경로).
    출력: ValueError."""
    ledger = conflicting_ledger()
    with pytest.raises(ValueError, match="can only be created"):
        copy.replace(ledger, conflicts=())


def test_ledger_cannot_be_constructed_directly_without_conflict_history():
    """입력: 충돌 장부의 applied·duplicates만 옮기고 conflicts=()로 직접 생성.
    출력: ValueError. 장부는 FillLedger.empty()와 apply_fill()로만 만들어진다."""
    ledger = conflicting_ledger()
    with pytest.raises(ValueError, match="can only be created"):
        FillLedger(
            account_id="A1",
            contracts=ledger.contracts,
            applied=ledger.applied,
            duplicates=ledger.duplicates,
            conflicts=(),
        )


def test_conflict_is_carried_by_every_later_ledger_and_keeps_blocking_calculations():
    """입력: CONFLICT 뒤 새 체결 X-2 반영, 원래 X-1 재수신(DUPLICATE), 다시 다른 내용의 X-1 재수신.
    출력: 모든 다음 장부에 첫 충돌이 그대로 남고(두 번째 충돌도 추가), 포지션·손익 계산은 계속 FillIntegrityError."""
    ledger = conflicting_ledger()
    first_conflict = ledger.conflicts[0]
    ledger = apply_fill(ledger, make_fill(fill_id="X-2", quantity=1)).ledger
    ledger = apply_fill(ledger, make_fill()).ledger
    ledger = apply_fill(ledger, make_fill(quantity=4)).ledger

    assert ledger.conflicts[0] == first_conflict
    assert len(ledger.conflicts) == 2
    with pytest.raises(FillIntegrityError):
        actual_position(baseline(), ledger, AS_OF)
    with pytest.raises(FillIntegrityError):
        period_trading_pnl(
            ledger=ledger,
            currency="USD",
            period_start=datetime(2026, 10, 19, 21, 0, tzinfo=UTC),
            period_end=datetime(2026, 10, 20, 21, 0, tzinfo=UTC),
            start_positions={C1: 0},
            start_prices={},
            end_prices={
                C1: ValuationPrice(
                    contract_id=C1,
                    price="103",
                    valuation_at=datetime(2026, 10, 20, 21, 0, tzinfo=UTC),
                    data_available_at=datetime(2026, 10, 20, 20, 30, tzinfo=UTC),
                    source_ref="fixture",
                )
            },
            information_cutoff=datetime(2026, 10, 20, 21, 0, tzinfo=UTC),
        )


def test_copies_keep_conflict_evidence():
    """입력: copy.copy, copy.deepcopy로 복사한 충돌 장부.
    출력: 복사본도 같은 충돌 증거를 가지며 계산이 막힌다 (복사로 증거가 사라지지 않음)."""
    ledger = conflicting_ledger()
    for duplicate in (copy.copy(ledger), copy.deepcopy(ledger)):
        assert duplicate.conflicts == ledger.conflicts
        with pytest.raises(FillIntegrityError):
            actual_position(baseline(), duplicate, AS_OF)


def test_conflict_evidence_is_an_immutable_record():
    """입력: FillConflict의 필드를 바꾸려는 시도, 잘못된 타입으로 직접 만든 FillConflict.
    출력: 필드 변경은 FrozenInstanceError. 잘못된 증거 기록(체결 기록이 아님, 키가 다름, 다른 필드가 실제와 다름)은 ValueError."""
    conflict = conflicting_ledger().conflicts[0]
    with pytest.raises(dataclasses.FrozenInstanceError):
        conflict.incoming = conflict.existing

    with pytest.raises(ValueError):
        FillConflict(existing=None, incoming=conflict.incoming, differing_fields=("quantity",))
    with pytest.raises(ValueError):
        FillConflict(existing=conflict.existing, incoming=make_fill(fill_id="X-9", quantity=3), differing_fields=("quantity",))
    with pytest.raises(ValueError):
        FillConflict(existing=conflict.existing, incoming=conflict.incoming, differing_fields=("price",))


def internal_ledger(applied=(), duplicates=(), conflicts=(), contracts=None):
    """내부 생성 경로(apply_fill이 쓰는 표식)로 장부를 만든다. 불변조건 검사 자체를 시험하기 위한 것이다."""
    return FillLedger(
        account_id="A1",
        contracts=contracts or (contract(),),
        applied=applied,
        duplicates=duplicates,
        conflicts=conflicts,
        _build_token=fill_ledger_module._LEDGER_BUILD_TOKEN,
    )


def test_internal_construction_still_validates_ledger_invariants():
    """입력: 내부 생성 경로로 만든 잘못된 장부: (a) 같은 키 두 건 (FillKey 하위 클래스 키 포함), (b) 다른 계좌의 체결,
    (c) 장부에 없는 월물, (d) 수수료 통화 ≠ 월물 통화, (e) lot 배수가 아닌 시뮬레이션 체결, (f) 반영되지 않은 키의 중복 수신,
    (g) 반영 기록을 가리키지 않는 충돌 기록.
    출력: 각각 해당 사유의 ValueError. 생성 제한과 별개로 Slice 1 불변조건 검사가 그대로 동작한다 (방어적 이중 검사)."""

    class OtherKey(FillKey):
        pass

    lot10 = FuturesContractSpec(contract_id=C1, instrument_id="FUT.ALPHA", currency="USD", multiplier="10", lot_size=10)
    subclass_key_fill = dataclasses.replace(make_fill(), key=OtherKey(account_id="A1", fill_source="BRK", fill_id="X-1"))
    other_account = dataclasses.replace(make_fill(), key=FillKey(account_id="A2", fill_source="BRK", fill_id="X-1"))
    unknown_contract = dataclasses.replace(make_fill(), contract_id="FUT.ALPHA.C9")
    krw_fee = dataclasses.replace(make_fill(), fee_currency="KRW")
    simulated_sub_lot = dataclasses.replace(
        make_fill(), origin=FillOrigin.SIMULATED, execution_assumption_ref="assumption:test-1", broker_order_id=None
    )
    applied = make_fill()
    other = make_fill(fill_id="X-2")
    cases = [
        (dict(applied=(applied, make_fill(quantity=3))), "appears more than once"),
        (dict(applied=(applied, subclass_key_fill)), "appears more than once"),
        (dict(applied=(other_account,)), "another account"),
        (dict(applied=(unknown_contract,)), "unknown contract_id"),
        (dict(applied=(krw_fee,)), "fee_currency"),
        (dict(applied=(simulated_sub_lot,), contracts=(lot10,)), "lot multiple"),
        (dict(applied=(applied,), duplicates=(other,)), "duplicate record must equal"),
        (
            dict(applied=(applied,), conflicts=(FillConflict(existing=other, incoming=dataclasses.replace(other, quantity=3), differing_fields=("quantity",)),)),
            "must refer to the applied fill",
        ),
    ]
    for kwargs, message in cases:
        with pytest.raises(ValueError, match=message):
            internal_ledger(**kwargs)


def test_fill_ledger_cannot_be_subclassed():
    """입력: FillLedger를 상속한 클래스 정의.
    출력: TypeError. 하위 클래스가 생성 검사를 다시 정의해 충돌 기록을 지우는 경로를 막는다."""
    with pytest.raises(TypeError):

        class LenientLedger(FillLedger):  # noqa: F841
            pass
