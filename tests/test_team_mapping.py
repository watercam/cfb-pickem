from src.data.team_mapping import canonicalize, load_aliases, resolve_pair


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
