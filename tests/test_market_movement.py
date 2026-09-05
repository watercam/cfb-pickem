from src.features.market_movement import american_to_implied, no_vig_probability


def test_favorite_implied_probability() -> None:
    assert abs(american_to_implied(-300) - 0.75) < 1e-9


def test_underdog_implied_probability() -> None:
    assert abs(american_to_implied(150) - 0.4) < 1e-9


def test_no_vig_sums_to_one() -> None:
    p = no_vig_probability(-150, 130)
    q = no_vig_probability(130, -150)
    assert abs(p + q - 1.0) < 1e-9
    assert p > 0.5
