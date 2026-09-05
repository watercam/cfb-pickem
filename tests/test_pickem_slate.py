import json
from src.pickem.slate import parse_espn_payload, parse_gambit_payload
from src.settings import project_root


def test_gambit_fixture_parses_week_kickoff_and_public_pct() -> None:
    path = project_root() / "tests" / "fixtures" / "espn_gambit_week.json"
    payload = json.loads(path.read_text())
    games = parse_gambit_payload(payload)
    assert len(games) == 10
    assert all(game.week == 1 for game in games)
    names = {(game.away_espn, game.home_espn) for game in games}
    assert ("Clemson", "LSU") in names
    assert ("Tulane", "Duke") in names
    lsu = next(game for game in games if game.home_espn == "LSU")
    assert lsu.game_id == "CLEM @ LSU"
    assert lsu.kickoff.year == 2026
    assert lsu.public_home_pct is not None
    assert 0 < lsu.public_home_pct <= 100
    # Format-3-only games (e.g. Ohio @ Nebraska) stay off the confidence slate.
    assert all("Ohio" not in (game.away_espn, game.home_espn) for game in games)


def test_parse_espn_payload_uses_gambit_when_propositions_present() -> None:
    payload = json.loads(
        (project_root() / "tests" / "fixtures" / "espn_gambit_week.json").read_text()
    )
    games = parse_espn_payload(payload)
    assert len(games) == 10
    assert games[0].week == 1
