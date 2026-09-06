#!/usr/bin/env python3
from __future__ import annotations

import html
import json
import re
import subprocess
import time
import unicodedata
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config.json"
EXAMPLE = ROOT / "config.example.json"
OUTPUT = ROOT / "data" / "videos.json"

USER_AGENT = (
    "FootballHub/5.0 "
    "(+https://github.com/aymerire-sudo/football-hub)"
)

ATOM_NS = "http://www.w3.org/2005/Atom"
YT_NS = "http://www.youtube.com/xml/schemas/2015"

NS = {
    "atom": ATOM_NS,
    "yt": YT_NS,
}


# ============================================================
# FALLBACK VOCABULARY
# ============================================================

DEFAULT_SUMMARY_KEYWORDS = {
    "highlights",
    "highlight",
    "match highlights",
    "extended highlights",
    "full highlights",
    "daZn highlights",
    "recap",
    "match recap",
    "résumé",
    "resume",
    "résumé du match",
    "résumé et buts",
    "buts",
    "goals",
    "all goals",
    "goals & highlights",
    "match goals",
    "all goals & highlights",
    "best moments",
    "meilleurs moments",
}


DEFAULT_EXCLUDE_KEYWORDS = {
    "reaction",
    "reactions",
    "réaction",
    "réactions",
    "preview",
    "predictions",
    "prediction",
    "avant-match",
    "avant match",
    "press conference",
    "press-conference",
    "conférence de presse",
    "interview",
    "interviews",
    "training",
    "behind the scenes",
    "transfer",
    "transfers",
    "mercato",
    "news",
    "news roundup",
    "analysis",
    "tactical analysis",
    "analyse",
    "débrief",
    "debrief",
    "podcast",
    "émission",
    "emission",
    "inside",
    "inside the",
    "reveals",
    "reveal",
    "exclusive",
    "best of",
    "top goals",
    "top buts",
    "stories",
    "ref cam",
    "challenge",
    "documentaire",
    "documentary",
    "coulisses",
    "homage",
    "hommage",
    "secrets de",
    "explique",
    "s'explique",
}


# ============================================================
# CLUB DATABASE
#
# The five followed teams come from config.json.
# This additional club dictionary lets us identify opponents
# and therefore distinguish:
#
#   "Bayern - Schalke"                         -> MATCH
#   "Mayence - Hambourg ... double le Bayern"  -> Mainz/Hamburg
#
# from a contextual mention.
# ============================================================

KNOWN_CLUBS: dict[str, list[str]] = {
    # France
    "psg": [
        "PSG",
        "Paris Saint-Germain",
        "Paris Saint Germain",
        "Paris SG",
    ],
    "ol": [
        "OL",
        "Olympique Lyonnais",
        "Olympique Lyon",
        "Lyon",
    ],
    "marseille": [
        "OM",
        "Olympique de Marseille",
        "Olympique Marseille",
        "Marseille",
    ],
    "monaco": [
        "AS Monaco",
        "Monaco",
        "ASM",
    ],
    "lille": [
        "LOSC",
        "Lille",
        "Lille OSC",
    ],
    "lens": [
        "RC Lens",
        "Lens",
        "RC LENS",
    ],
    "le-havre": [
        "Le Havre",
        "HAC",
        "Havre AC",
    ],
    "auxerre": [
        "Auxerre",
        "AJ Auxerre",
    ],
    "toulouse": [
        "Toulouse",
        "TFC",
    ],
    "rennes": [
        "Rennes",
        "Stade Rennais",
    ],
    "nice": [
        "Nice",
        "OGC Nice",
    ],
    "nantes": [
        "Nantes",
        "FC Nantes",
    ],
    "strasbourg": [
        "Strasbourg",
        "RC Strasbourg",
    ],
    "montpellier": [
        "Montpellier",
        "Montpellier HSC",
        "MHSC",
    ],
    "saint-etienne": [
        "Saint-Etienne",
        "Saint-Étienne",
        "ASSE",
    ],
    "bordeaux": [
        "Bordeaux",
        "Girondins de Bordeaux",
    ],
    "reims": [
        "Reims",
        "Stade de Reims",
    ],
    "metz": [
        "Metz",
        "FC Metz",
    ],
    "lorient": [
        "Lorient",
        "FC Lorient",
    ],
    "angers": [
        "Angers",
        "Angers SCO",
    ],
    "brest": [
        "Brest",
        "Stade Brestois",
    ],
    "auxerre": [
        "Auxerre",
        "AJ Auxerre",
    ],
    "le-mans": [
        "Le Mans",
    ],
    "dijon": [
        "Dijon",
        "Dijon FCO",
    ],
    "grenoble": [
        "Grenoble",
        "Grenoble Foot",
    ],
    "laval": [
        "Laval",
        "Stade Lavallois",
    ],
    "clermont": [
        "Clermont",
        "Clermont Foot",
    ],
    "dunkerque": [
        "Dunkerque",
        "USL Dunkerque",
    ],
    "caen": [
        "Caen",
        "SM Caen",
    ],
    "sochaux": [
        "Sochaux",
        "FC Sochaux",
    ],
    "pau": [
        "Pau",
        "Pau FC",
    ],
    "annecy": [
        "Annecy",
        "FC Annecy",
    ],
    "guingamp": [
        "Guingamp",
        "EA Guingamp",
    ],
    "boulogne": [
        "Boulogne-sur-Mer",
        "US Boulogne",
    ],
    "red-star": [
        "Red Star",
    ],
    "paris-fc": [
        "Paris FC",
    ],

    # England
    "arsenal": [
        "Arsenal",
        "Arsenal FC",
        "Arsenal Football Club",
    ],
    "chelsea": [
        "Chelsea",
        "Chelsea FC",
    ],
    "man-united": [
        "Manchester United",
        "Man United",
        "Man Utd",
        "Man U",
    ],
    "man-city": [
        "Manchester City",
        "Man City",
    ],
    "liverpool": [
        "Liverpool",
        "Liverpool FC",
    ],
    "tottenham": [
        "Tottenham",
        "Tottenham Hotspur",
        "Spurs",
    ],
    "newcastle": [
        "Newcastle",
        "Newcastle United",
    ],
    "aston-villa": [
        "Aston Villa",
    ],
    "crystal-palace": [
        "Crystal Palace",
    ],
    "brighton": [
        "Brighton",
        "Brighton & Hove Albion",
    ],
    "fulham": [
        "Fulham",
    ],
    "everton": [
        "Everton",
    ],
    "ipswich": [
        "Ipswich",
        "Ipswich Town",
    ],
    "hull-city": [
        "Hull City",
    ],

    # Germany
    "bayern": [
        "Bayern Munich",
        "Bayern München",
        "FC Bayern München",
        "FC Bayern Munich",
        "Bayern",
    ],
    "schalke": [
        "Schalke",
        "Schalke 04",
    ],
    "mainz": [
        "Mainz",
        "Mayence",
        "Mainz 05",
        "FSV Mainz",
    ],
    "hamburg": [
        "Hambourg",
        "Hamburg",
        "Hamburger SV",
        "HSV",
    ],
    "dortmund": [
        "Dortmund",
        "Borussia Dortmund",
        "BVB",
    ],
    "leverkusen": [
        "Leverkusen",
        "Bayer Leverkusen",
    ],
    "frankfurt": [
        "Francfort",
        "Frankfurt",
        "Eintracht Frankfurt",
    ],
    "augsburg": [
        "Augsbourg",
        "Augsburg",
        "FC Augsburg",
    ],
    "freiburg": [
        "Fribourg",
        "Freiburg",
        "SC Freiburg",
    ],
    "stuttgart": [
        "Stuttgart",
        "VfB Stuttgart",
    ],
    "cologne": [
        "Cologne",
        "Köln",
        "FC Köln",
    ],
    "monchengladbach": [
        "Mönchengladbach",
        "Monchengladbach",
        "Gladbach",
        "Borussia Mönchengladbach",
    ],
    "werder-bremen": [
        "Werder Brême",
        "Werder Bremen",
        "Bremen",
    ],
    "paderborn": [
        "Paderborn",
        "SC Paderborn",
    ],
    "elversberg": [
        "Elversberg",
        "SV Elversberg",
    ],

    # Spain
    "real-madrid": [
        "Real Madrid",
        "Real Madrid CF",
        "Real Madrid C.F.",
    ],
    "real-betis": [
        "Real Betis",
        "Betis",
        "Real Betis Balompié",
    ],
    "barcelona": [
        "FC Barcelona",
        "Barcelona",
        "Barça",
        "Barca",
    ],
    "real-sociedad": [
        "Real Sociedad",
    ],
    "athletic-bilbao": [
        "Athletic Bilbao",
        "Athletic Club",
        "Bilbao",
    ],
    "atletico-madrid": [
        "Atlético Madrid",
        "Atletico Madrid",
        "Atlético de Madrid",
        "Atletico de Madrid",
    ],
    "rayo-vallecano": [
        "Rayo Vallecano",
        "Rayo",
    ],
    "racing-santander": [
        "Racing Santander",
        "Racing",
    ],
    "alaves": [
        "Alavés",
        "Alaves",
        "Deportivo Alavés",
    ],
    "osasuna": [
        "Osasuna",
        "CA Osasuna",
    ],
    "celta-vigo": [
        "Celta Vigo",
        "Celta",
    ],
    "malaga": [
        "Málaga",
        "Malaga",
        "Málaga CF",
    ],
    "levante": [
        "Levante",
        "Levante UD",
    ],
    "valencia": [
        "Valence",
        "Valencia",
        "Valencia CF",
    ],

    # Turkey / Portugal / Italy / etc.
    "fenerbahce": [
        "Fenerbahçe",
        "Fenerbahce",
        "Fener",
    ],
    "besiktas": [
        "Besiktas",
        "Beşiktaş",
    ],
    "benfica": [
        "Benfica",
        "SL Benfica",
    ],
    "maritimo": [
        "Marítimo",
        "Maritimo",
    ],
    "porto": [
        "Porto",
        "FC Porto",
    ],
    "moreirense": [
        "Moreirense",
    ],
    "sporting": [
        "Sporting",
        "Sporting CP",
        "Sporting Portugal",
    ],
    "nacional": [
        "Nacional",
        "Nacional Madeira",
    ],
    "galatasaray": [
        "Galatasaray",
    ],
    "trabzonspor": [
        "Trabzonspor",
    ],
    "besiktas": [
        "Besiktas",
        "Beşiktaş",
    ],
    "roma": [
        "Roma",
        "AS Roma",
    ],
    "inter": [
        "Inter",
        "Inter Milan",
        "Internazionale",
    ],
    "napoli": [
        "Napoli",
        "SSC Napoli",
    ],
    "atalanta": [
        "Atalanta",
        "Atalanta BC",
    ],
    "fiorentina": [
        "Fiorentina",
    ],
    "torino": [
        "Torino",
    ],
    "genoa": [
        "Genoa",
    ],
    "como": [
        "Como",
        "Côme",
        "Como 1907",
    ],
    "monza": [
        "Monza",
        "AC Monza",
    ],
    "udinese": [
        "Udinese",
    ],
    "parma": [
        "Parma",
    ],
    "bologna": [
        "Bologne",
        "Bologna",
    ],
    "sassuolo": [
        "Sassuolo",
    ],
    "lazio": [
        "Lazio",
        "SS Lazio",
    ],
    "frosinone": [
        "Frosinone",
    ],
    "venezia": [
        "Venise",
        "Venezia",
    ],
    "cagliari": [
        "Cagliari",
    ],
    "lecce": [
        "Lecce",
    ],
}


# ---------------------------------------------------------------------------
# Team aliases / config
# ---------------------------------------------------------------------------


def aliases_for_config_team(
    team: dict[str, Any],
) -> list[str]:
    return [
        str(value)
        for value in [
            team.get("name"),
            *(team.get("aliases") or []),
        ]
        if value
    ]


def normalize(
    value: str | None,
) -> str:
    value = html.unescape(
        value or ""
    )

    value = unicodedata.normalize(
        "NFKD",
        value,
    )

    value = "".join(
        char
        for char in value
        if not unicodedata.combining(char)
    )

    value = value.lower()
    value = value.replace(
        "&",
        " and ",
    )

    value = re.sub(
        r"[^a-z0-9]+",
        " ",
        value,
    )

    return re.sub(
        r"\s+",
        " ",
        value,
    ).strip()


def slug(
    value: str | None,
) -> str:
    return re.sub(
        r"[^a-z0-9]+",
        "-",
        normalize(value),
    ).strip("-")


def contains(
    text: str | None,
    term: str | None,
) -> bool:
    haystack = normalize(text)
    needle = normalize(term)

    if not needle:
        return False

    return bool(
        re.search(
            r"(?<![a-z0-9])"
            + re.escape(needle)
            + r"(?![a-z0-9])",
            haystack,
        )
    )


def team_match(
    text: str,
    team: dict[str, Any],
) -> bool:
    return any(
        contains(
            text,
            alias,
        )
        for alias in aliases_for_config_team(
            team
        )
    )


def followed_team_hits(
    text: str,
    teams: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    found = []

    for team in teams:
        if team_match(
            text,
            team,
        ):
            found.append(
                {
                    "id": team["id"],
                    "name": team["name"],
                }
            )

    return found


# ---------------------------------------------------------------------------
# Known club detection
# ---------------------------------------------------------------------------


def known_aliases() -> list[
    tuple[str, str]
]:
    pairs = []

    for club_id, aliases in KNOWN_CLUBS.items():
        for alias in aliases:
            pairs.append(
                (
                    club_id,
                    alias,
                )
            )

    # Longest aliases first prevents
    # "Real Madrid" from being matched as just "Madrid".
    pairs.sort(
        key=lambda item: len(
            normalize(item[1])
        ),
        reverse=True,
    )

    return pairs


KNOWN_ALIASES = known_aliases()


def find_known_clubs(
    text: str,
) -> list[dict[str, Any]]:
    normalized = normalize(
        text
    )

    found = {}

    for club_id, alias in KNOWN_ALIASES:
        term = normalize(
            alias
        )

        if not term:
            continue

        match = re.search(
            r"(?<![a-z0-9])"
            + re.escape(term)
            + r"(?![a-z0-9])",
            normalized,
        )

        if not match:
            continue

        if club_id not in found:
            found[club_id] = {
                "id": club_id,
                "name": canonical_club_name(
                    club_id
                ),
                "alias": alias,
                "start": match.start(),
                "end": match.end(),
            }

    return sorted(
        found.values(),
        key=lambda item: item["start"],
    )


def canonical_club_name(
    club_id: str,
) -> str:
    mapping = {
        "psg": "PSG",
        "ol": "OL",
        "arsenal": "Arsenal",
        "bayern": "Bayern Munich",
        "real-madrid": "Real Madrid",
        "marseille": "Marseille",
        "monaco": "Monaco",
        "lille": "Lille",
        "lens": "RC Lens",
        "le-havre": "Le Havre",
        "auxerre": "Auxerre",
        "toulouse": "Toulouse",
        "rennes": "Rennes",
        "nice": "Nice",
        "nantes": "Nantes",
        "strasbourg": "Strasbourg",
        "montpellier": "Montpellier",
        "saint-etienne": "Saint-Étienne",
        "bordeaux": "Bordeaux",
        "reims": "Reims",
        "metz": "Metz",
        "lorient": "Lorient",
        "angers": "Angers",
        "brest": "Brest",
        "caen": "Caen",
        "guingamp": "Guingamp",
        "dijon": "Dijon",
        "le-mans": "Le Mans",
        "red-star": "Red Star",
        "paris-fc": "Paris FC",
        "chelsea": "Chelsea",
        "man-united": "Manchester United",
        "man-city": "Manchester City",
        "liverpool": "Liverpool",
        "tottenham": "Tottenham",
        "newcastle": "Newcastle",
        "aston-villa": "Aston Villa",
        "crystal-palace": "Crystal Palace",
        "brighton": "Brighton",
        "fulham": "Fulham",
        "everton": "Everton",
        "ipswich": "Ipswich",
        "hull-city": "Hull City",
        "schalke": "Schalke",
        "mainz": "Mayence",
        "hamburg": "Hambourg",
        "dortmund": "Dortmund",
        "leverkusen": "Leverkusen",
        "frankfurt": "Eintracht Frankfurt",
        "augsburg": "Augsbourg",
        "freiburg": "Fribourg",
        "stuttgart": "Stuttgart",
        "cologne": "Cologne",
        "monchengladbach": "Mönchengladbach",
        "werder-bremen": "Werder Bremen",
        "paderborn": "Paderborn",
        "elversberg": "Elversberg",
        "real-betis": "Real Betis",
        "barcelona": "Barcelona",
        "real-sociedad": "Real Sociedad",
        "athletic-bilbao": "Athletic Bilbao",
        "atletico-madrid": "Atlético Madrid",
        "rayo-vallecano": "Rayo Vallecano",
        "racing-santander": "Racing Santander",
        "alaves": "Alavés",
        "osasuna": "Osasuna",
        "celta-vigo": "Celta Vigo",
        "malaga": "Málaga",
        "levante": "Levante",
        "valencia": "Valence",
        "fenerbahce": "Fenerbahçe",
        "besiktas": "Beşiktaş",
        "benfica": "Benfica",
        "maritimo": "Marítimo",
        "porto": "Porto",
        "moreirense": "Moreirense",
        "sporting": "Sporting",
        "nacional": "Nacional",
        "galatasaray": "Galatasaray",
        "trabzonspor": "Trabzonspor",
        "roma": "Roma",
        "inter": "Inter",
        "napoli": "Napoli",
        "atalanta": "Atalanta",
        "fiorentina": "Fiorentina",
        "torino": "Torino",
        "genoa": "Genoa",
        "como": "Como",
        "monza": "Monza",
        "udinese": "Udinese",
        "parma": "Parma",
        "bologna": "Bologne",
        "sassuolo": "Sassuolo",
        "lazio": "Lazio",
        "frosinone": "Frosinone",
        "venezia": "Venise",
        "cagliari": "Cagliari",
        "lecce": "Lecce",
    }

    return mapping.get(
        club_id,
        club_id.replace(
            "-",
            " ",
        ).title(),
    )


def followed_club_ids(
    teams: list[dict[str, Any]],
) -> dict[str, str]:
    mapping = {}

    for team in teams:
        config_id = team["id"]

        for club_id, aliases in KNOWN_CLUBS.items():
            if any(
                normalize(alias)
                == normalize(config_alias)
                or contains(
                    alias,
                    config_alias,
                )
                or contains(
                    config_alias,
                    alias,
                )
                for alias in aliases
                for config_alias in aliases_for_config_team(
                    team
                )
            ):
                mapping[
                    club_id
                ] = config_id

    return mapping


# ---------------------------------------------------------------------------
# Score / competition / text helpers
# ---------------------------------------------------------------------------


SCORE_RE = re.compile(
    r"(?<!\d)(\d{1,2})\s*[-–—:]\s*(\d{1,2})(?!\d)"
)

DATE_RE = re.compile(
    r"\b(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})\b"
)

EXPLICIT_SEPARATOR_RE = re.compile(
    r"\s+(?:vs\.?|v\.?|contre|@)\s+|"
    r"\s*/\s*"
)

# Used for "Arsenal - Chelsea".
HYPHEN_PAIR_RE = re.compile(
    r"(?<![A-Za-z0-9])\s+[-–—]\s+(?![A-Za-z0-9])"
)

RELATION_RE = re.compile(
    r"\b(?:face\s+à|face\s+a|contre|sur)\b",
    re.IGNORECASE,
)

CONTEXT_PATTERNS = {
    "classement",
    "points",
    "leader",
    "leaders",
    "devance",
    "devant",
    "dépasse",
    "double le",
    "double la",
    "double les",
    "prend la tête",
    "en tête",
    "au classement",
    "course au titre",
}


def extract_score(
    text: str,
) -> str | None:
    found = SCORE_RE.search(
        text
    )

    if not found:
        return None

    return (
        f"{found.group(1)}-"
        f"{found.group(2)}"
    )


def extract_date_from_title(
    title: str,
) -> str | None:
    found = DATE_RE.search(
        title
    )

    if not found:
        return None

    try:
        return datetime(
            int(found.group(1)),
            int(found.group(2)),
            int(found.group(3)),
            tzinfo=timezone.utc,
        ).isoformat()

    except ValueError:
        return None


def competition_from_title(
    title: str,
) -> str | None:
    normalized = normalize(
        title
    )

    competitions = (
        "uefa champions league",
        "champions league",
        "europa league",
        "conference league",
        "premier league",
        "la liga",
        "bundesliga",
        "ligue 1",
        "ligue 2",
        "coupe de france",
        "coupe de la ligue",
        "trophee des champions",
        "trophée des champions",
        "fa cup",
        "carabao cup",
        "community shield",
        "dfb pokal",
        "copa del rey",
        "supercopa",
        "club world cup",
        "mondial des clubs",
        "world cup",
        "coupe du monde",
        "euro",
        "euros",
    )

    for competition in sorted(
        competitions,
        key=len,
        reverse=True,
    ):
        if normalize(
            competition
        ) in normalized:
            return (
                competition.title()
                .replace(
                    "Trophee",
                    "Trophée",
                )
            )

    return None


def looks_like_summary(
    title: str,
    app: dict[str, Any],
) -> bool:
    includes = (
        app.get(
            "summary_keywords"
        )
        or list(
            DEFAULT_SUMMARY_KEYWORDS
        )
    )

    excludes = (
        app.get(
            "exclude_keywords"
        )
        or list(
            DEFAULT_EXCLUDE_KEYWORDS
        )
    )

    normalized = normalize(
        title
    )

    if any(
        contains(
            title,
            keyword,
        )
        for keyword in excludes
    ):
        return False

    return any(
        contains(
            title,
            keyword,
        )
        for keyword in includes
    )


def looks_contextual(
    title: str,
) -> bool:
    normalized = normalize(
        title
    )

    return any(
        normalize(pattern)
        in normalized
        for pattern in CONTEXT_PATTERNS
    )


def clean_side(
    text: str,
) -> str:
    value = html.unescape(
        text or ""
    )

    value = re.sub(
        r"^\s*(?:le|la|les|l['’])?\s*"
        r"(?:résumé|resume|highlights?|recap)"
        r"\s*(?:de|du|des|of)?"
        r"\s*[:\-–—|]?\s*",
        "",
        value,
        flags=re.I,
    )

    value = re.sub(
        r"\([^)]*\)",
        " ",
        value,
    )

    value = SCORE_RE.sub(
        " ",
        value,
    )

    value = re.split(
        r"\s*[|•·]\s*",
        value,
        maxsplit=1,
    )[0]

    # Season labels are NEVER clubs.
    value = re.sub(
        r"\b(?:20\d{2})[-/]\d{2}\b",
        " ",
        value,
    )

    value = re.sub(
        r"\b(?:J\d+|J\d+(?:re|e)|"
        r"week\s*\d+|"
        r"journ[eé]e\s*\d+|"
        r"round\s*\d+)\b",
        " ",
        value,
        flags=re.I,
    )

    value = re.sub(
        r"\s+-\s+(?="
        r"(?:premier|ligue|bundesliga|"
        r"la\s+liga|champions|europa|"
        r"conference|trophee|trophée|"
        r"coupe|club|league|"
        r"highlights?|résumé|resume|"
        r"goals?|buts?)\b)",
        "",
        value,
        flags=re.I,
    )

    return re.sub(
        r"\s+",
        " ",
        value,
    ).strip(
        " -–—:|"
    )


def side_is_generic(
    value: str,
) -> bool:
    normalized = normalize(
        value
    )

    if not normalized:
        return True

    generic = {
        "ligue",
        "league",
        "football",
        "match",
        "matches",
        "game",
        "games",
        "highlights",
        "highlight",
        "resume",
        "résumé",
        "recap",
        "buts",
        "but",
        "goals",
        "goal",
        "all",
        "the",
        "week",
        "saison",
        "season",
        "26 27",
        "27",
        "2026",
        "2027",
    }

    words = normalized.split()

    if len(words) > 4:
        return True

    return all(
        word in generic
        for word in words
    )


def canonical_known_side(
    side_text: str,
) -> dict[str, Any] | None:
    hits = find_known_clubs(
        side_text
    )

    if not hits:
        return None

    hit = hits[0]

    return {
        "club_id": hit["id"],
        "name": hit["name"],
    }


def infer_unknown_side(
    side_text: str,
) -> str:
    value = clean_side(
        side_text
    )

    value = re.sub(
        r"^\s*(?:un|une|le|la|les|l['’]|the)\s+",
        "",
        value,
        flags=re.I,
    )

    words = []

    for word in value.split():
        normalized_word = normalize(
            word
        )

        if not normalized_word:
            continue

        if normalized_word in {
            "qui",
            "et",
            "avec",
            "pour",
            "dans",
            "sur",
            "face",
            "contre",
            "héroïque",
            "heroique",
            "héroiques",
            "heroique",
            "brillant",
            "brillante",
            "incroyable",
            "impressionnant",
            "impressionnante",
            "fou",
            "folle",
            "grâce",
            "grace",
            "grace a",
            "a",
        }:
            break

        if len(words) >= 3:
            break

        words.append(
            word.strip(
                ".,!?;:()[]{}"
            )
        )

    result = " ".join(
        words
    ).strip()

    if side_is_generic(
        result
    ):
        return ""

    # A long natural-language sentence is not a club.
    if len(
        normalize(result).split()
    ) > 3:
        return ""

    return result


# ---------------------------------------------------------------------------
# Match side extraction
# ---------------------------------------------------------------------------


def explicit_sides(
    title: str,
) -> tuple[
    str,
    str,
] | None:
    text = html.unescape(
        title or ""
    )

    # --------------------------------------------------------
    # 1. Score-based titles
    #
    # Examples:
    # Arsenal 2-1 Chelsea
    # Chelsea 1 - 2 Arsenal
    # --------------------------------------------------------

    score_match = SCORE_RE.search(
        text
    )

    if score_match:
        left = text[
            :score_match.start()
        ]

        right = text[
            score_match.end():
        ]

        right = re.split(
            r"\s*[|•·]",
            right,
            maxsplit=1,
        )[0]

        right = re.split(
            r"\s+-\s+(?="
            r"(?:premier|ligue|bundesliga|"
            r"la\s+liga|champions|europa|"
            r"conference|troph|coupe|club|"
            r"league|highlights?|résumé|"
            r"resume|goals?|buts?)\b)",
            right,
            maxsplit=1,
            flags=re.I,
        )[0]

        if (
            left.strip()
            and right.strip()
        ):
            return (
                left,
                right,
            )

    # --------------------------------------------------------
    # 2. Explicit separators
    # --------------------------------------------------------

    matches = list(
        EXPLICIT_SEPARATOR_RE.finditer(
            text
        )
    )

    for separator in reversed(
        matches
    ):
        left = text[
            :separator.start()
        ]

        right = text[
            separator.end():
        ]

        right = re.split(
            r"\s*[|•·]",
            right,
            maxsplit=1,
        )[0]

        right = re.split(
            r"\s+-\s+(?="
            r"(?:premier|ligue|bundesliga|"
            r"la\s+liga|champions|europa|"
            r"conference|troph|coupe|club|"
            r"league|highlights?|résumé|"
            r"resume|goals?|buts?)\b)",
            right,
            maxsplit=1,
            flags=re.I,
        )[0]

        if (
            left.strip()
            and right.strip()
        ):
            return (
                left,
                right,
            )

    # --------------------------------------------------------
    # 3. Hyphen pair
    #
    # DAZN:
    # Real Betis - Real Madrid | LALIGA...
    # --------------------------------------------------------

    matches = list(
        HYPHEN_PAIR_RE.finditer(
            text
        )
    )

    for separator in reversed(
        matches
    ):
        left = text[
            :separator.start()
        ]

        right = text[
            separator.end():
        ]

        right = re.split(
            r"\s*[|•·]",
            right,
            maxsplit=1,
        )[0]

        # Do not treat "Real Madrid - LALIGA" as a match.
        right = re.split(
            r"\s*-\s*(?="
            r"(?:premier|ligue|bundesliga|"
            r"laliga|la\s+liga|champions|"
            r"europa|conference|trophee|"
            r"trophée|coupe|club)\b)",
            right,
            maxsplit=1,
            flags=re.I,
        )[0]

        if (
            left.strip()
            and right.strip()
        ):
            return (
                left,
                right,
            )

    return None


def natural_language_sides(
    title: str,
) -> tuple[
    str,
    str,
] | None:
    text = html.unescape(
        title or ""
    )

    clubs = find_known_clubs(
        text
    )

    if len(clubs) < 2:
        return None

    # For natural-language headlines, first examine where
    # the known clubs occur.
    #
    # Example:
    # MAYENCE ... HAMBOURG ... double le BAYERN
    #
    # We intentionally take the first two club mentions when
    # a context-only phrase occurs before the third one.
    normalized = normalize(
        text
    )

    context_positions = [
        normalized.find(
            normalize(
                pattern
            )
        )
        for pattern in CONTEXT_PATTERNS
        if normalize(pattern)
        in normalized
    ]

    first_context = (
        min(
            pos
            for pos in context_positions
            if pos >= 0
        )
        if context_positions
        else None
    )

    if first_context is not None:
        before_context = [
            club
            for club in clubs
            if club["start"]
            < first_context
        ]

        if len(
            before_context
        ) >= 2:
            return (
                before_context[0]["name"],
                before_context[1]["name"],
            )

    # Otherwise take first two known clubs.
    return (
        clubs[0]["name"],
        clubs[1]["name"],
    )


def identify_match(
    title: str,
    teams: list[dict[str, Any]],
) -> dict[str, Any] | None:
    explicit = explicit_sides(
        title
    )

    candidate_pairs = []

    if explicit:
        candidate_pairs.append(
            (
                explicit[0],
                explicit[1],
                "high",
            )
        )

    natural = natural_language_sides(
        title
    )

    if natural:
        candidate_pairs.append(
            (
                natural[0],
                natural[1],
                "medium",
            )
        )

    for left_raw, right_raw, confidence in candidate_pairs:
        left = clean_side(
            left_raw
        )

        right = clean_side(
            right_raw
        )

        if not left or not right:
            continue

        # IMPORTANT:
        # Determine known clubs from each side separately.
        # This prevents a third contextual team from
        # contaminating the match.
        left_known = canonical_known_side(
            left
        )

        right_known = canonical_known_side(
            right
        )

        # At least one side must correspond to a followed team.
        followed_left = None
        followed_right = None

        for team in teams:
            if team_match(
                left,
                team,
            ):
                followed_left = {
                    "id": team["id"],
                    "name": team["name"],
                }

            if team_match(
                right,
                team,
            ):
                followed_right = {
                    "id": team["id"],
                    "name": team["name"],
                }

        if (
            not followed_left
            and not followed_right
        ):
            continue

        # Replace known aliases with canonical names.
        if left_known:
            left_name = left_known["name"]
            left_club_id = left_known[
                "club_id"
            ]
        else:
            left_name = infer_unknown_side(
                left
            )
            left_club_id = (
                "opp:" + slug(left_name)
                if left_name
                else None
            )

        if right_known:
            right_name = right_known["name"]
            right_club_id = right_known[
                "club_id"
            ]
        else:
            right_name = infer_unknown_side(
                right
            )
            right_club_id = (
                "opp:" + slug(right_name)
                if right_name
                else None
            )

        if not left_name or not right_name:
            continue

        if side_is_generic(
            left_name
        ) or side_is_generic(
            right_name
        ):
            continue

        if (
            normalize(left_name)
            == normalize(right_name)
        ):
            continue

        return {
            "home": {
                "club_id": left_club_id,
                "name": left_name,
                "followed": bool(
                    followed_left
                ),
                "followed_team_id": (
                    followed_left["id"]
                    if followed_left
                    else None
                ),
            },
            "away": {
                "club_id": right_club_id,
                "name": right_name,
                "followed": bool(
                    followed_right
                ),
                "followed_team_id": (
                    followed_right["id"]
                    if followed_right
                    else None
                ),
            },
            "confidence": confidence,
        }

    return None


# ---------------------------------------------------------------------------
# Video classification
# ---------------------------------------------------------------------------


def classify_video(
    video: dict[str, Any],
    app: dict[str, Any],
    teams: list[dict[str, Any]],
) -> dict[str, Any] | None:
    title = html.unescape(
        video.get(
            "title",
            "",
        )
        or ""
    )

    if not title:
        return None

    if not looks_like_summary(
        title,
        app,
    ):
        return None

    followed_hits = followed_team_hits(
        title,
        teams,
    )

    if not followed_hits:
        return None

    # --------------------------------------------------------
    # Strong exclusion:
    # a single followed team + contextual language
    # is not a match.
    # --------------------------------------------------------

    if (
        len(followed_hits) == 1
        and looks_contextual(
            title
        )
    ):
        explicit = explicit_sides(
            title
        )

        if not explicit:
            return None

    match = identify_match(
        title,
        teams,
    )

    if not match:
        return None

    home = match["home"]
    away = match["away"]

    followed_ids = []

    if home[
        "followed_team_id"
    ]:
        followed_ids.append(
            home[
                "followed_team_id"
            ]
        )

    if away[
        "followed_team_id"
    ]:
        followed_ids.append(
            away[
                "followed_team_id"
            ]
        )

    followed_ids = sorted(
        set(
            followed_ids
        )
    )

    if not followed_ids:
        return None

    score = extract_score(
        title
    )

    competition = competition_from_title(
        title
    )

    date_in_title = (
        extract_date_from_title(
            title
        )
    )

    published_at = (
        parse_date(
            video.get(
                "published_at"
            )
        )
        or parse_date(
            video.get(
                "updated_at"
            )
        )
    )

    match_date = (
        date_in_title
        or published_at
    )

    if score:
        match_title = (
            f"{home['name']} "
            f"{score} "
            f"{away['name']}"
        )
    else:
        match_title = (
            f"{home['name']} vs "
            f"{away['name']}"
        )

    # --------------------------------------------------------
    # IMPORTANT:
    # Do NOT include the score in match identity.
    #
    # CANAL+:
    # Arsenal / Chelsea
    #
    # DAZN:
    # Arsenal 2-1 Chelsea
    #
    # -> same match.
    # --------------------------------------------------------

    home_key = (
        home["club_id"]
        or "opp:" + slug(
            home["name"]
        )
    )

    away_key = (
        away["club_id"]
        or "opp:" + slug(
            away["name"]
        )
    )

    round_token = ""

    round_match = re.search(
        r"\b(?:J(\d+)|"
        r"journ[eé]e\s*(\d+)|"
        r"week\s*(\d+)|"
        r"round\s*(\d+))\b",
        normalize(title),
        flags=re.I,
    )

    if round_match:
        numbers = [
            value
            for value in round_match.groups()
            if value
        ]

        if numbers:
            round_token = (
                "r"
                + numbers[0]
            )

    # Home/away is preserved, which avoids merging
    # two league meetings when both happen in the same season.
    match_key = "|".join(
        [
            "match",
            home_key,
            away_key,
            slug(
                competition
                or "football"
            ),
            round_token
            or (
                "date:"
                + normalize(
                    match_date
                )[:10]
                if match_date
                else "date:unknown"
            ),
        ]
    )

    return {
        "is_summary": True,

        "match_key": match_key,

        "match_title": match_title,

        "home_team": {
            "id": (
                home[
                    "followed_team_id"
                ]
            ),
            "name": home[
                "name"
            ],
            "followed": home[
                "followed"
            ],
        },

        "away_team": {
            "id": (
                away[
                    "followed_team_id"
                ]
            ),
            "name": away[
                "name"
            ],
            "followed": away[
                "followed"
            ],
        },

        "score": score,

        "competition": competition,

        "match_date": match_date,

        "team_ids": followed_ids,

        "match_confidence": match[
            "confidence"
        ],

        "summary_keywords": [
            keyword
            for keyword in (
                app.get(
                    "summary_keywords"
                )
                or DEFAULT_SUMMARY_KEYWORDS
            )
            if contains(
                title,
                keyword,
            )
        ],
    }


def enrich_video(
    video: dict[str, Any],
    app: dict[str, Any],
    teams: list[dict[str, Any]],
) -> dict[str, Any] | None:
    metadata = classify_video(
        video,
        app,
        teams,
    )

    if not metadata:
        return None

    result = {
        **video,
        **metadata,
    }

    result["teams"] = [
        {
            "id": metadata[side]["id"],
            "name": metadata[side]["name"],
        }
        for side in (
            "home_team",
            "away_team",
        )
        if metadata[side]["id"]
    ]

    return result


# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------


def parse_date(
    value: Any,
) -> str | None:
    if value is None:
        return None

    value = str(value).strip()

    if not value:
        return None

    try:
        if re.fullmatch(
            r"\d{8}",
            value,
        ):
            return (
                datetime.strptime(
                    value,
                    "%Y%m%d",
                )
                .replace(
                    tzinfo=timezone.utc
                )
                .isoformat()
            )

        if re.fullmatch(
            r"\d+(?:\.\d+)?",
            value,
        ):
            timestamp = float(
                value
            )

            if (
                timestamp
                >= 1_000_000_000
            ):
                return (
                    datetime.fromtimestamp(
                        timestamp,
                        timezone.utc,
                    ).isoformat()
                )

        dt = datetime.fromisoformat(
            value.replace(
                "Z",
                "+00:00",
            )
        )

        if dt.tzinfo is None:
            dt = dt.replace(
                tzinfo=timezone.utc
            )

        return dt.astimezone(
            timezone.utc
        ).isoformat()

    except ValueError:
        return None


# ---------------------------------------------------------------------------
# YouTube
# ---------------------------------------------------------------------------


def resolve_channel_id(
    source: dict[str, Any],
) -> str:
    direct = str(
        source.get(
            "youtube_channel_id",
            "",
        )
        or ""
    ).strip()

    if direct.startswith(
        "UC"
    ):
        return direct

    url = str(
        source.get(
            "youtube_url",
            "",
        )
        or ""
    ).strip()

    if not url:
        return ""

    match = re.search(
        r"/channel/(UC[0-9A-Za-z_-]{20,})",
        url,
    )

    if match:
        return match.group(
            1
        )

    try:
        request = Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
            },
        )

        with urlopen(
            request,
            timeout=20,
        ) as response:
            body = response.read().decode(
                "utf-8",
                errors="ignore",
            )

        patterns = [
            r'"channelId":"(UC[0-9A-Za-z_-]{20,})"',
            r'"externalId":"(UC[0-9A-Za-z_-]{20,})"',
            (
                r'<meta[^>]+itemprop=["\']channelId'
                r'["\'][^>]+content=["\']'
                r'(UC[0-9A-Za-z_-]{20,})'
            ),
        ]

        for pattern in patterns:
            found = re.search(
                pattern,
                body,
                flags=re.I,
            )

            if found:
                return found.group(
                    1
                )

    except Exception:
        pass

    return ""


def run_ytdlp_playlist(
    source: dict[str, Any],
    limit: int,
) -> list[
    dict[str, Any]
]:
    url = str(
        source.get(
            "youtube_url",
            "",
        )
        or ""
    ).strip().rstrip("/")

    if not url:
        return []

    if not url.endswith(
        "/videos"
    ):
        url += "/videos"

    command = [
        "yt-dlp",
        "--dump-single-json",
        "--flat-playlist",
        "--ignore-errors",
        "--no-warnings",
        "--playlist-items",
        f"1:{limit}",
        url,
    ]

    process = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=240,
    )

    if process.returncode not in (
        0,
        1,
    ):
        raise RuntimeError(
            process.stderr[
                -1500:
            ]
            or "yt-dlp failed"
        )

    if not process.stdout.strip():
        return []

    try:
        payload = json.loads(
            process.stdout
        )
    except json.JSONDecodeError:
        return []

    result = []

    for item in (
        payload.get(
            "entries"
        )
        or []
    ):
        if not item:
            continue

        video_id = item.get(
            "id"
        )

        if not video_id:
            continue

        result.append(
            {
                "id": video_id,

                "title": html.unescape(
                    item.get(
                        "title",
                        "",
                    )
                    or ""
                ),

                "url": (
                    item.get(
                        "webpage_url"
                    )
                    or (
                        "https://www.youtube.com/"
                        "watch?v="
                        f"{video_id}"
                    )
                ),

                "published_at": (
                    parse_date(
                        item.get(
                            "release_timestamp"
                        )
                    )
                    or parse_date(
                        item.get(
                            "timestamp"
                        )
                    )
                    or parse_date(
                        item.get(
                            "upload_date"
                        )
                    )
                ),

                "updated_at": None,

                "thumbnail": (
                    item.get(
                        "thumbnail"
                    )
                    or (
                        "https://i.ytimg.com/vi/"
                        f"{video_id}/hqdefault.jpg"
                    )
                ),

                "source_id": source[
                    "id"
                ],

                "source_name": source.get(
                    "name",
                    source[
                        "id"
                    ],
                ),

                "source_channel_id": (
                    item.get(
                        "channel_id"
                    )
                    or ""
                ),

                "description": (
                    item.get(
                        "description"
                    )
                    or ""
                ),
            }
        )

    return result


def fetch_atom(
    source: dict[str, Any],
    limit: int,
) -> list[
    dict[str, Any]
]:
    channel_id = (
        resolve_channel_id(
            source
        )
    )

    if not channel_id:
        return []

    url = (
        "https://www.youtube.com/"
        "feeds/videos.xml"
        "?channel_id="
        f"{channel_id}"
    )

    request = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
        },
    )

    with urlopen(
        request,
        timeout=30,
    ) as response:
        data = response.read()

    root = ET.fromstring(
        data
    )

    result = []

    for entry in root.findall(
        "atom:entry",
        NS,
    )[:limit]:
        video_id = (
            entry.findtext(
                "yt:videoId",
                "",
                NS,
            )
            or ""
        ).strip()

        if not video_id:
            continue

        title = (
            entry.findtext(
                "atom:title",
                "",
                NS,
            )
            or ""
        ).strip()

        alt_link = entry.find(
            "atom:link[@rel='alternate']",
            NS,
        )

        url_value = (
            alt_link.get(
                "href"
            )
            if alt_link is not None
            else (
                "https://www.youtube.com/"
                f"watch?v={video_id}"
            )
        )

        published_at = parse_date(
            entry.findtext(
                "atom:published",
                "",
                NS,
            )
        )

        updated_at = parse_date(
            entry.findtext(
                "atom:updated",
                "",
                NS,
            )
        )

        result.append(
            {
                "id": video_id,
                "title": html.unescape(
                    title
                ),
                "url": url_value,
                "published_at": published_at,
                "updated_at": updated_at,
                "thumbnail": (
                    "https://i.ytimg.com/vi/"
                    f"{video_id}/hqdefault.jpg"
                ),
                "source_id": source[
                    "id"
                ],
                "source_name": source.get(
                    "name",
                    source[
                        "id"
                    ],
                ),
                "source_channel_id": channel_id,
                "description": "",
            }
        )

    return result


def fetch_details(
    video_id: str,
) -> dict[str, Any]:
    url = (
        "https://www.youtube.com/"
        "watch?v="
        f"{video_id}"
    )

    command = [
        "yt-dlp",
        "--dump-single-json",
        "--no-playlist",
        "--no-warnings",
        "--ignore-errors",
        url,
    ]

    process = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=45,
    )

    if (
        process.returncode
        != 0
        or not process.stdout.strip()
    ):
        return {}

    try:
        payload = json.loads(
            process.stdout
        )
    except json.JSONDecodeError:
        return {}

    return {
        "published_at": (
            parse_date(
                payload.get(
                    "release_timestamp"
                )
            )
            or parse_date(
                payload.get(
                    "timestamp"
                )
            )
            or parse_date(
                payload.get(
                    "upload_date"
                )
            )
        ),

        "updated_at": None,

        "description": (
            payload.get(
                "description"
            )
            or ""
        ),

        "thumbnail": (
            payload.get(
                "thumbnail"
            )
            or ""
        ),

        "url": (
            payload.get(
                "webpage_url"
            )
            or url
        ),

        "source_channel_id": (
            payload.get(
                "channel_id"
            )
            or ""
        ),
    }


# ---------------------------------------------------------------------------
# Source limits
# ---------------------------------------------------------------------------


def source_limit(
    source: dict[str, Any],
    configured_default: int,
) -> int:
    source_id = source.get(
        "id",
        "",
    )

    # These sources publish large quantities of material.
    # We need enough depth to recover older football summaries.
    overrides = {
        "bein-sports-france": 220,
        "canal-plus-sport": 160,
        "dazn-france": 160,
        "ligue-1": 180,
    }

    return max(
        configured_default,
        overrides.get(
            source_id,
            configured_default,
        ),
    )


# ---------------------------------------------------------------------------
# Data merging / grouping
# ---------------------------------------------------------------------------


def load_existing() -> dict[str, Any]:
    if not OUTPUT.exists():
        return {
            "videos": []
        }

    try:
        data = json.loads(
            OUTPUT.read_text(
                encoding="utf-8"
            )
        )

        if not isinstance(
            data,
            dict,
        ):
            return {
                "videos": []
            }

        data.setdefault(
            "videos",
            []
        )

        return data

    except (
        OSError,
        json.JSONDecodeError,
    ):
        return {
            "videos": []
        }


def reclassify_records(
    old_videos: list[
        dict[str, Any]
    ],
    new_videos: list[
        dict[str, Any]
    ],
    app: dict[str, Any],
    teams: list[dict[str, Any]],
) -> list[
    dict[str, Any]
]:
    by_id: dict[
        str,
        dict[str, Any],
    ] = {}

    for video in (
        old_videos
        + new_videos
    ):
        video_id = video.get(
            "id"
        )

        if not video_id:
            continue

        by_id[
            video_id
        ] = {
            **by_id.get(
                video_id,
                {}
            ),
            **video,
        }

    result = []

    for video in by_id.values():
        enriched = enrich_video(
            video,
            app,
            teams,
        )

        if enriched:
            result.append(
                enriched
            )

    return result


def build_matches(
    videos: list[
        dict[str, Any]
    ],
) -> list[
    dict[str, Any]
]:
    groups: dict[
        str,
        list[
            dict[str, Any]
        ],
    ] = {}

    for video in videos:
        key = (
            video.get(
                "match_key"
            )
            or video.get(
                "id"
            )
        )

        groups.setdefault(
            key,
            [],
        ).append(
            video
        )

    matches = []

    for key, items in groups.items():
        items.sort(
            key=lambda item: (
                item.get(
                    "published_at"
                )
                or ""
            ),
            reverse=True,
        )

        first = items[0]

        sources_seen = {}

        for item in items:
            source_id = item.get(
                "source_id"
            )

            if (
                source_id
                and source_id
                not in sources_seen
            ):
                sources_seen[
                    source_id
                ] = {
                    "id": source_id,
                    "name": item.get(
                        "source_name",
                        source_id,
                    ),
                }

        match_dates = [
            item.get(
                "match_date"
            )
            for item in items
            if item.get(
                "match_date"
            )
        ]

        published_dates = [
            item.get(
                "published_at"
            )
            for item in items
            if item.get(
                "published_at"
            )
        ]

        matches.append(
            {
                "match_key": key,

                "title": (
                    first.get(
                        "match_title"
                    )
                    or first.get(
                        "title"
                    )
                    or "Résumé"
                ),

                "home_team": first.get(
                    "home_team"
                ),

                "away_team": first.get(
                    "away_team"
                ),

                "score": next(
                    (
                        item.get(
                            "score"
                        )
                        for item in items
                        if item.get(
                            "score"
                        )
                    ),
                    None,
                ),

                "competition": first.get(
                    "competition"
                ),

                "match_date": (
                    min(
                        match_dates
                    )
                    if match_dates
                    else (
                        min(
                            published_dates
                        )
                        if published_dates
                        else None
                    )
                ),

                "published_at": (
                    max(
                        published_dates
                    )
                    if published_dates
                    else None
                ),

                "team_ids": sorted(
                    {
                        team["id"]
                        for item in items
                        for team in (
                            item.get(
                                "teams"
                            )
                            or []
                        )
                        if team.get(
                            "id"
                        )
                    }
                ),

                "team_names": sorted(
                    {
                        team["name"]
                        for item in items
                        for team in (
                            item.get(
                                "teams"
                            )
                            or []
                        )
                        if team.get(
                            "name"
                        )
                    }
                ),

                "sources_count": len(
                    sources_seen
                ),

                "sources": list(
                    sources_seen.values()
                ),

                "videos": items,
            }
        )

    matches.sort(
        key=lambda match: (
            match.get(
                "match_date"
            )
            or match.get(
                "published_at"
            )
            or ""
        ),
        reverse=True,
    )

    return matches


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    config = load_json(
        CONFIG,
        EXAMPLE,
    )

    app = config.get(
        "app",
        {},
    )

    teams = [
        team
        for team in config.get(
            "teams",
            [],
        )
        if team.get(
            "id"
        )
        and team.get(
            "name"
        )
    ]

    sources = [
        source
        for source in config.get(
            "sources",
            [],
        )
        if source.get(
            "enabled",
            True,
        )
    ]

    existing = load_existing()

    configured_default = int(
        app.get(
            "max_videos_per_source",
            60,
        )
    )

    print(
        f"Scanning {len(sources)} sources..."
    )

    all_new_videos = []
    statuses = []

    for source in sources:
        limit = source_limit(
            source,
            configured_default,
        )

        status = {
            "source_id": source[
                "id"
            ],
            "source_name": source.get(
                "name",
                source[
                    "id"
                ],
            ),
            "ok": False,
            "count": 0,
            "method": None,
            "error": None,
        }

        try:
            try:
                videos = (
                    run_ytdlp_playlist(
                        source,
                        limit,
                    )
                )

                method = "yt-dlp"

            except Exception:
                videos = fetch_atom(
                    source,
                    min(
                        limit,
                        15,
                    ),
                )

                method = "atom"

            # Recover exact publication metadata only for
            # likely football-summary candidates.
            candidates = [
                video
                for video in videos
                if (
                    not video.get(
                        "published_at"
                    )
                    and looks_like_summary(
                        video.get(
                            "title",
                            "",
                        ),
                        app,
                    )
                )
            ]

            # Avoid excessive YouTube requests.
            for candidate in candidates[:60]:
                details = fetch_details(
                    candidate[
                        "id"
                    ]
                )

                if details:
                    for key, value in details.items():
                        if value not in (
                            None,
                            "",
                        ):
                            candidate[
                                key
                            ] = value

                time.sleep(
                    0.10
                )

            all_new_videos.extend(
                videos
            )

            status[
                "ok"
            ] = True

            status[
                "count"
            ] = len(
                videos
            )

            status[
                "method"
            ] = method

        except (
            HTTPError,
            URLError,
            ET.ParseError,
            TimeoutError,
            RuntimeError,
            ValueError,
            json.JSONDecodeError,
        ) as exc:
            status[
                "error"
            ] = str(
                exc
            )[:1000]

        except Exception as exc:
            status[
                "error"
            ] = (
                f"{type(exc).__name__}: "
                f"{exc}"
            )[:1000]

        statuses.append(
            status
        )

        print(
            f"[{status['source_name']}] "
            f"{'OK' if status['ok'] else 'ERROR'} "
            f"({status['count']} videos)"
        )

        time.sleep(
            0.4
        )

    # Reclassify old records with the new engine.
    # This is what removes previous false positives.
    retained = reclassify_records(
        existing.get(
            "videos",
            [],
        ),
        all_new_videos,
        app,
        teams,
    )

    cutoff = (
        datetime.now(
            timezone.utc
        )
        - timedelta(
            days=int(
                app.get(
                    "keep_days",
                    45,
                )
            )
        )
    )

    filtered = []

    for video in retained:
        date_value = (
            video.get(
                "published_at"
            )
            or video.get(
                "match_date"
            )
        )

        if not date_value:
            # Keep undated videos temporarily.
            filtered.append(
                video
            )
            continue

        try:
            dt = datetime.fromisoformat(
                date_value.replace(
                    "Z",
                    "+00:00",
                )
            )

            if dt.tzinfo is None:
                dt = dt.replace(
                    tzinfo=timezone.utc
                )

            if dt >= cutoff:
                filtered.append(
                    video
                )

        except ValueError:
            filtered.append(
                video
            )

    filtered.sort(
        key=lambda video: (
            video.get(
                "published_at"
            )
            or video.get(
                "match_date"
            )
            or ""
        ),
        reverse=True,
    )

    matches = build_matches(
        filtered
    )

    output = {
        "generated_at": datetime.now(
            timezone.utc
        ).isoformat(),

        "teams": [
            {
                "id": team[
                    "id"
                ],
                "name": team[
                    "name"
                ],
            }
            for team in teams
        ],

        "source_status": statuses,

        "videos": filtered,

        "matches": matches,

        "stats": {
            "videos": len(
                filtered
            ),
            "matches": len(
                matches
            ),
            "teams": len(
                teams
            ),
            "sources": len(
                sources
            ),
        },
    }

    OUTPUT.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    OUTPUT.write_text(
        json.dumps(
            output,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print()
    print(
        "=========================================="
    )
    print(
        "Football Hub V5 collection complete"
    )
    print(
        "=========================================="
    )

    print(
        f"Videos retained : {len(filtered)}"
    )

    print(
        f"Matches grouped : {len(matches)}"
    )

    print()

    for match in matches[:30]:
        print(
            f"- {match.get('title', 'Résumé')} "
            f"| sources={match.get('sources_count', 0)} "
            f"| date={match.get('match_date')}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
