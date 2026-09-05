from src.features.market_movement import spread_move, team_spread_from_home


def test_favorite_lengthens() -> None:
    assert spread_move(-3, -5) == 2


def test_dog_shortens() -> None:
    assert spread_move(7, 4) == 3


def test_favorite_shortens() -> None:
    assert spread_move(-7, -4) == -3


def test_away_row_flips_home_spread() -> None:
    assert team_spread_from_home(-3, is_home=True) == -3
    assert team_spread_from_home(-3, is_home=False) == 3
