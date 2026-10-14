import math
import pytest

from carver_quant.account_ledger import update_account_value



def test_update_account_value_after_loss():
    result = update_account_value(
        previous_account_value=50340.0,
        net_pnl=-420.0,
    )

    assert result == 49920.0

def test_update_account_value_after_profit():
    result = update_account_value(
        previous_account_value=50000.0,
        net_pnl=750.0,
    )

    assert result == 50750.0


def test_update_account_value_when_pnl_is_zero():
    result = update_account_value(
        previous_account_value=50000.0,
        net_pnl=0.0,
    )

    assert result == 50000.0


def test_update_account_value_can_be_negative():
    result = update_account_value(
        previous_account_value=1000.0,
        net_pnl=-1500.0,
    )

    assert result == -500.0

def test_nan_previous_account_value_raises_value_error():
    with pytest.raises(ValueError):
        update_account_value(
            previous_account_value=math.nan,
            net_pnl=100.0,
        )


def test_infinite_net_pnl_raises_value_error():
    with pytest.raises(ValueError):
        update_account_value(
            previous_account_value=50000.0,
            net_pnl=math.inf,
        )