from datetime import date

import pytest

from carver_quant.futures_data import (
    BackAdjustedPrice,
    ContractPrice,
    RollEvent,
    build_back_adjusted_prices,
    build_back_adjusted_prices_as_of,
)


def test_build_back_adjusted_prices_matches_carver_example():
    prices = [
        # Contract A
        ContractPrice(
            date(2019, 1, 2),
            "A",
            100.0,
        ),
        ContractPrice(
            date(2019, 1, 3),
            "A",
            100.2,
        ),
        ContractPrice(
            date(2019, 1, 6),
            "A",
            100.3,
        ),
        ContractPrice(
            date(2019, 1, 7),
            "A",
            99.9,
        ),

        # Contract B
        ContractPrice(
            date(2019, 1, 7),
            "B",
            100.2,
        ),
        ContractPrice(
            date(2019, 1, 8),
            "B",
            99.9,
        ),
        ContractPrice(
            date(2019, 1, 9),
            "B",
            98.7,
        ),
        ContractPrice(
            date(2019, 1, 10),
            "B",
            99.0,
        ),

        # Contract C
        ContractPrice(
            date(2019, 1, 9),
            "C",
            99.1,
        ),
        ContractPrice(
            date(2019, 1, 10),
            "C",
            99.5,
        ),
        ContractPrice(
            date(2019, 1, 13),
            "C",
            99.9,
        ),
        ContractPrice(
            date(2019, 1, 14),
            "C",
            100.1,
        ),
    ]

    rolls = [
        RollEvent(
            date=date(2019, 1, 7),
            old_contract="A",
            new_contract="B",
        ),
        RollEvent(
            date=date(2019, 1, 10),
            old_contract="B",
            new_contract="C",
        ),
    ]

    result = build_back_adjusted_prices(
        prices=prices,
        initial_contract="A",
        roll_events=rolls,
    )

    assert [
        x.adjusted_price
        for x in result
    ] == pytest.approx([
        100.8,
        101.0,
        101.1,
        100.7,
        100.4,
        99.2,
        99.5,
        99.9,
        100.1,
    ])


def test_latest_adjusted_price_equals_current_raw_price():
    prices = [
        ContractPrice(
            date(2026, 1, 1),
            "A",
            100.0,
        ),
        ContractPrice(
            date(2026, 1, 2),
            "A",
            101.0,
        ),
        ContractPrice(
            date(2026, 1, 2),
            "B",
            105.0,
        ),
        ContractPrice(
            date(2026, 1, 3),
            "B",
            106.0,
        ),
    ]

    result = build_back_adjusted_prices(
        prices=prices,
        initial_contract="A",
        roll_events=[
            RollEvent(
                date=date(2026, 1, 2),
                old_contract="A",
                new_contract="B",
            )
        ],
    )

    assert result[-1].raw_price == pytest.approx(
        106.0
    )

    assert result[-1].adjusted_price == pytest.approx(
        106.0
    )


def test_roll_gap_does_not_create_artificial_return():
    prices = [
        ContractPrice(
            date(2026, 1, 1),
            "A",
            100.0,
        ),
        ContractPrice(
            date(2026, 1, 2),
            "A",
            101.0,
        ),
        ContractPrice(
            date(2026, 1, 2),
            "B",
            111.0,
        ),
        ContractPrice(
            date(2026, 1, 3),
            "B",
            111.0,
        ),
    ]

    result = build_back_adjusted_prices(
        prices=prices,
        initial_contract="A",
        roll_events=[
            RollEvent(
                date=date(2026, 1, 2),
                old_contract="A",
                new_contract="B",
            )
        ],
    )

    # Roll date:
    # A = 101
    # B = 111
    # gap = +10
    #
    # A adjusted = 111
    # 다음 날 B raw = 111
    #
    # 따라서 roll 자체로 수익이 생기지 않는다.
    assert result[1].adjusted_price == pytest.approx(
        111.0
    )

    assert result[2].adjusted_price == pytest.approx(
        111.0
    )


def test_negative_futures_price_is_allowed():
    price = ContractPrice(
        date=date(2020, 4, 20),
        contract="CL",
        close=-10.0,
    )

    assert price.close == -10.0


def test_missing_new_contract_price_on_roll_date_is_rejected():
    prices = [
        ContractPrice(
            date(2026, 1, 1),
            "A",
            100.0,
        )
    ]

    with pytest.raises(
        ValueError,
        match="New contract price is missing",
    ):
        build_back_adjusted_prices(
            prices=prices,
            initial_contract="A",
            roll_events=[
                RollEvent(
                    date=date(2026, 1, 1),
                    old_contract="A",
                    new_contract="B",
                )
            ],
        )


def test_inconsistent_roll_chain_is_rejected():
    prices = [
        ContractPrice(
            date(2026, 1, 1),
            "A",
            100.0,
        ),
        ContractPrice(
            date(2026, 1, 1),
            "B",
            101.0,
        ),
    ]

    with pytest.raises(
        ValueError,
        match="Roll event chain is inconsistent",
    ):
        build_back_adjusted_prices(
            prices=prices,
            initial_contract="A",
            roll_events=[
                RollEvent(
                    date=date(2026, 1, 1),
                    old_contract="X",
                    new_contract="B",
                )
            ],
        )

def test_as_of_back_adjustment_does_not_use_future_roll():
    prices = [
        ContractPrice(
            date=date(2026, 1, 1),
            contract="A",
            close=100.0,
        ),
        ContractPrice(
            date=date(2026, 1, 2),
            contract="A",
            close=101.0,
        ),
        ContractPrice(
            date=date(2026, 1, 3),
            contract="A",
            close=102.0,
        ),
        ContractPrice(
            date=date(2026, 1, 3),
            contract="B",
            close=111.0,
        ),
        ContractPrice(
            date=date(2026, 1, 4),
            contract="B",
            close=112.0,
        ),
    ]

    roll_events = [
        RollEvent(
            date=date(2026, 1, 3),
            old_contract="A",
            new_contract="B",
        )
    ]

    result = build_back_adjusted_prices_as_of(
        prices=prices,
        initial_contract="A",
        roll_events=roll_events,
        as_of_date=date(2026, 1, 2),
    )

    assert len(result) == 2

    assert result[0].adjusted_price == pytest.approx(
        100.0
    )

    assert result[1].adjusted_price == pytest.approx(
        101.0
    )

def test_offline_back_adjustment_can_revise_historical_levels():
    prices = [
        ContractPrice(
            date=date(2026, 1, 1),
            contract="A",
            close=100.0,
        ),
        ContractPrice(
            date=date(2026, 1, 2),
            contract="A",
            close=101.0,
        ),
        ContractPrice(
            date=date(2026, 1, 3),
            contract="A",
            close=102.0,
        ),
        ContractPrice(
            date=date(2026, 1, 3),
            contract="B",
            close=111.0,
        ),
        ContractPrice(
            date=date(2026, 1, 4),
            contract="B",
            close=112.0,
        ),
    ]

    roll_events = [
        RollEvent(
            date=date(2026, 1, 3),
            old_contract="A",
            new_contract="B",
        )
    ]

    result = build_back_adjusted_prices(
        prices=prices,
        initial_contract="A",
        roll_events=roll_events,
    )

    # roll gap = 111 - 102 = 9

    assert result[0].adjusted_price == pytest.approx(
        109.0
    )

    assert result[1].adjusted_price == pytest.approx(
        110.0
    )

    assert result[2].adjusted_price == pytest.approx(
        111.0
    )

    assert result[3].adjusted_price == pytest.approx(
        112.0
    )

def test_as_of_back_adjustment_includes_known_roll():
    prices = [
        ContractPrice(
            date=date(2026, 1, 1),
            contract="A",
            close=100.0,
        ),
        ContractPrice(
            date=date(2026, 1, 2),
            contract="A",
            close=101.0,
        ),
        ContractPrice(
            date=date(2026, 1, 3),
            contract="A",
            close=102.0,
        ),
        ContractPrice(
            date=date(2026, 1, 3),
            contract="B",
            close=111.0,
        ),
        ContractPrice(
            date=date(2026, 1, 4),
            contract="B",
            close=112.0,
        ),
    ]

    roll_events = [
        RollEvent(
            date=date(2026, 1, 3),
            old_contract="A",
            new_contract="B",
        )
    ]

    result = build_back_adjusted_prices_as_of(
        prices=prices,
        initial_contract="A",
        roll_events=roll_events,
        as_of_date=date(2026, 1, 4),
    )

    assert [
        point.adjusted_price
        for point in result
    ] == pytest.approx([
        109.0,
        110.0,
        111.0,
        112.0,
    ])