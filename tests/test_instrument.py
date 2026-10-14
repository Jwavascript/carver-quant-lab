import pytest

from carver_quant.instrument import InstrumentSpec


def test_create_instrument_spec():
    spec = InstrumentSpec(
        symbol="MES",
        currency="USD",
        multiplier=5.0,
        tick_size=0.25,
    )

    assert spec.symbol == "MES"
    assert spec.currency == "USD"
    assert spec.multiplier == 5.0
    assert spec.tick_size == 0.25


def test_instrument_spec_is_immutable():
    spec = InstrumentSpec(
        symbol="MES",
        currency="USD",
        multiplier=5.0,
        tick_size=0.25,
    )

    with pytest.raises(Exception):
        spec.multiplier = 10.0


@pytest.mark.parametrize(
    "multiplier",
    [
        0.0,
        -1.0,
        float("nan"),
        float("inf"),
    ],
)
def test_reject_invalid_multiplier(multiplier):
    with pytest.raises(ValueError):
        InstrumentSpec(
            symbol="MES",
            currency="USD",
            multiplier=multiplier,
            tick_size=0.25,
        )


@pytest.mark.parametrize(
    "tick_size",
    [
        0.0,
        -0.25,
        float("nan"),
        float("inf"),
    ],
)
def test_reject_invalid_tick_size(tick_size):
    with pytest.raises(ValueError):
        InstrumentSpec(
            symbol="MES",
            currency="USD",
            multiplier=5.0,
            tick_size=tick_size,
        )


def test_reject_empty_symbol():
    with pytest.raises(ValueError):
        InstrumentSpec(
            symbol=" ",
            currency="USD",
            multiplier=5.0,
            tick_size=0.25,
        )


def test_reject_empty_currency():
    with pytest.raises(ValueError):
        InstrumentSpec(
            symbol="MES",
            currency=" ",
            multiplier=5.0,
            tick_size=0.25,
        )