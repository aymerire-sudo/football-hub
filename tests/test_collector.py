import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from collector.collect import contains_term, get_team_hits, looks_like_summary, canonical_match_key


def test_normalized_team_match():
    teams = [{"id": "psg", "name": "Paris Saint-Germain", "aliases": ["PSG"]}]
    hits = get_team_hits("PSG 3-1 Marseille | Match Highlights", "", teams)
    assert hits and hits[0]["id"] == "psg"


def test_summary_detection():
    app = {"summary_keywords": ["highlights", "résumé"], "exclude_keywords": ["reaction"]}
    video = {"title": "Arsenal 2-1 Chelsea | Match Highlights", "description": ""}
    decision, matched, excluded = looks_like_summary(video, app)
    assert decision and "highlights" in matched and not excluded


def test_exclusion():
    app = {"summary_keywords": ["highlights"], "exclude_keywords": ["reaction"]}
    video = {"title": "Arsenal reaction to Chelsea highlights", "description": ""}
    decision, _, excluded = looks_like_summary(video, app)
    assert not decision and "reaction" in excluded


def test_contains_term_does_not_match_partial_word():
    assert contains_term("Arsenal FC", "arsenal")
    assert not contains_term("Marseille", "arse")


def test_match_key_is_stable():
    teams = [{"id": "arsenal", "name": "Arsenal"}]
    hits = get_team_hits("Arsenal 2-1 Chelsea | Highlights", "", teams)
    key1 = canonical_match_key("Arsenal 2-1 Chelsea | Highlights", hits, "2026-09-06T18:00:00+00:00")
    key2 = canonical_match_key("Arsenal 2–1 Chelsea | Full highlights", hits, "2026-09-06T18:30:00+00:00")
    assert key1 != ""
    assert key1.split("|")[:3] == key2.split("|")[:3]
