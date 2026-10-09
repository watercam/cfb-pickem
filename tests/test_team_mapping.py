from src.data.team_mapping import (
    TeamNameIndex,
    canonicalize,
    load_aliases,
    normalize_team_key,
    pair_odds_sides_for_espn,
    resolve_pair,
)


def test_alias_resolution() -> None:
    aliases = load_aliases()
    assert canonicalize("Ole Miss", "cfbd", aliases=aliases) == "Ole Miss"
    assert canonicalize("Mississippi Rebels", "odds", aliases=aliases) == "Ole Miss"


def test_unmapped_without_alias() -> None:
    aliases = load_aliases()
    assert canonicalize("Not A Real Team", "cfbd", aliases=aliases) is None


def test_exact_string_pair_resolves() -> None:
    assert resolve_pair("Alpha State", "Alpha State", aliases=[]) == "Alpha State"


def test_fuzzy_disabled_by_default() -> None:
    aliases = load_aliases()
    assert canonicalize("ole miss", "cfbd", aliases=aliases, enable_fuzzy=False) is None


def test_espn_alias_resolution() -> None:
    aliases = load_aliases()
    assert canonicalize("Miami", "espn", aliases=aliases) == "Miami"
    assert canonicalize("Ole Miss", "espn", aliases=aliases) == "Ole Miss"
    assert canonicalize("Miam", "espn", aliases=aliases) is None


def test_normalize_st_vs_state_and_mascots() -> None:
    assert normalize_team_key("Arizona St.") == "arizona state"
    assert normalize_team_key("Arizona St") == "arizona state"
    assert normalize_team_key("St. Francis") == "saint francis"
    index = TeamNameIndex()
    assert index.resolve("Arizona St.") == "Arizona State"
    assert index.resolve("Arizona State Sun Devils") == "Arizona State"
    assert index.resolve("ASU") == "Arizona State"
    assert index.resolve("Texas Longhorns") == "Texas"
    assert index.resolve("Oklahoma Sooners") == "Oklahoma"
    assert index.same_team("Kansas", "Kansas State") is False
    assert index.same_team("Miami", "Miami (OH)") is False
    assert index.same_team("Texas", "Texas A&M") is False


def test_pair_odds_sides_swapped_neutral_site() -> None:
    paired = pair_odds_sides_for_espn(
        "Kansas",
        "ASU",
        "Arizona State Sun Devils",
        "Kansas Jayhawks",
    )
    assert paired == ("Kansas Jayhawks", "Arizona State Sun Devils")


def test_pair_odds_sides_does_not_guess_kansas_state() -> None:
    assert (
        pair_odds_sides_for_espn(
            "Kansas",
            "Arizona State",
            "Kansas State Wildcats",
            "Arizona State Sun Devils",
        )
        is None
    )
