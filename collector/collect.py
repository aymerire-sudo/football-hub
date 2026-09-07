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
# VOCABULAIRE
# ============================================================

DEFAULT_SUMMARY_KEYWORDS = {
    "highlights",
    "highlight",
    "match highlights",
    "extended highlights",
    "full highlights",
    "match recap",
    "recap",
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
    "hommage",
    "secrets de",
    "explique",
    "s'explique",
}


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


GENERIC = {
    "resume",
    "résumé",
    "highlights",
    "highlight",
    "extended",
    "full",
    "match",
    "recap",
    "buts",
    "but",
    "goals",
    "goal",
    "all",
    "the",
    "le",
    "la",
    "les",
    "un",
    "une",
    "des",
    "du",
    "de",
    "a",
    "au",
    "aux",
    "avec",
    "pour",
    "dans",
    "et",
    "qui",
    "se",
    "sur",
    "contre",
    "face",
    "live",
    "direct",
    "official",
    "officiel",
    "video",
    "vidéo",
    "season",
    "saison",
    "journee",
    "journée",
    "round",
    "week",
    "manita",
    "héroique",
    "heroique",
    "folle",
    "énorme",
    "enorme",
    "incroyable",
    "impressionnant",
    "impressionnante",
    "solide",
    "dominant",
    "domine",
    "humilie",
    "humilié",
    "écrase",
    "ecrase",
    "frappe",
    "tombe",
    "perd",
    "gagne",
    "bat",
    "révèle",
    "reveal",
    "reveals",
    "torres",
    "barcola",
    "champion",
    "champions",
    "league",
    "ligue",
}


COMPETITIONS = (
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


# ============================================================
# OUTILS GENERIQUES
# ============================================================


def load_json(
    path: Path,
    fallback: Path | None = None,
) -> dict[str, Any]:
    """
    Charge un fichier JSON et vérifie qu'il contient un objet.
    Utilise fallback si path n'existe pas.
    """
    target = path if path.exists() else fallback

    if target is None or not target.exists():
        raise FileNotFoundError(
            f"Configuration introuvable : {path}"
        )

    with target.open(
        "r",
        encoding="utf-8",
    ) as fh:
        data = json.load(fh)

    if not isinstance(data, dict):
        raise ValueError(
            f"Le fichier JSON {target} doit contenir un objet."
        )

    return data


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
            dt = datetime.strptime(
                value,
                "%Y%m%d",
            ).replace(
                tzinfo=timezone.utc
            )

            return dt.isoformat()

        if re.fullmatch(
            r"\d+(?:\.\d+)?",
            value,
        ):
            timestamp = float(
                value
            )

            if timestamp >= 1_000_000_000:
                return datetime.fromtimestamp(
                    timestamp,
                    timezone.utc,
                ).isoformat()

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


# ============================================================
# EQUIPES SUIVIES
# ============================================================


def aliases_for_team(
    team: dict[str, Any],
) -> list[str]:
    return [
        str(value)
        for value in [
            team.get("name"),
            *(
                team.get(
                    "aliases",
                    []
                )
                or []
            ),
        ]
        if value
    ]


def team_matches(
    text: str,
    team: dict[str, Any],
) -> bool:
    return any(
        contains(
            text,
            alias,
        )
        for alias in aliases_for_team(
            team
        )
    )


def followed_team_hits(
    text: str,
    teams: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    result = []

    for team in teams:
        if team_matches(
            text,
            team,
        ):
            result.append(
                {
                    "id": team["id"],
                    "name": team["name"],
                }
            )

    return result


# ============================================================
# BASE DE CLUBS / ADVERSAIRES
# ============================================================

KNOWN_CLUBS: dict[str, list[str]] = {
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
    "caen": [
        "Caen",
        "SM Caen",
    ],
    "guingamp": [
        "Guingamp",
        "EA Guingamp",
    ],
    "dijon": [
        "Dijon",
        "Dijon FCO",
    ],
    "le-mans": [
        "Le Mans",
    ],
    "red-star": [
        "Red Star",
    ],
    "paris-fc": [
        "Paris FC",
    ],

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
    "roma": [
        "Roma",
        "AS Roma",
    ],
    "inter": [
        "Inter Milan",
        "Internazionale",
        "Inter",
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
    "saint-gall": [
        "Saint-Gall",
        "St. Gallen",
        "St Gallen",
    ],
    "servette": [
        "Servette",
        "Servette FC",
    ],
    "macon": [
        "Macon",
        "Mâcon",
    ],
    "sparta-prague": [
        "Sparta Prague",
        "Sparta Praha",
        "Sparta",
    ],
    "wiesbaden": [
        "Wiesbaden",
    ],
    "rottach-egern": [
        "Rottach-Egern",
        "Rottach Egern",
    ],
    "jeju-united": [
        "Jeju Utd",
        "Jeju United",
        "Jeju",
    ],
    "heidenheim": [
        "Heidenheim",
        "1. FC Heidenheim",
    ],
    "leipzig": [
        "Leipzig",
        "RB Leipzig",
    ],
    "girona": [
        "Gérone",
        "Girona",
    ],
    "côme": [
        "Côme",
        "Como",
        "Como 1907",
    ],
    "coventry": [
        "Coventry",
        "Coventry City",
    ],
    "sunderland": [
        "Sunderland",
        "Sunderland AFC",
    ],
    "leeds-united": [
        "Leeds United",
        "Leeds",
    ],
    "nottingham-forest": [
        "Not. Forest",
        "Nottingham Forest",
        "Forest",
    ],
    "union-berlin": [
        "Union Berlin",
        "1. FC Union Berlin",
    ],
    "troyes": [
        "Troyes",
        "ESTAC",
    ],
    "elche": [
        "Elche",
    ],
    "villarreal": [
        "Villarreal",
        "Villareal",
    ],
    "sevilla": [
        "Séville",
        "Sevilla",
    ],
    "alcorcon": [
        "Alcorcón",
        "Alcorcon",
    ],
    "leganes": [
        "Leganes",
        "Leganés",
    ],
    "ferencvaros": [
        "Ferencvaros",
        "Ferencváros",
    ],
    "a-coruna": [
        "A Coruña",
        "Deportivo La Corogne",
        "Deportivo La Coruña",
    ],
    "mallorca": [
        "Majorque",
        "Mallorca",
        "RCD Mallorca",
    ],
}


CANONICAL_NAMES = {
    key: value
    for key, value in {
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
    }.items()
}


def find_known_clubs(
    text: str,
) -> list[dict[str, Any]]:
    normalized = normalize(
        text
    )

    found = {}

    aliases = []

    for club_id, values in KNOWN_CLUBS.items():
        for alias in values:
            aliases.append(
                (
                    club_id,
                    alias,
                )
            )

    aliases.sort(
        key=lambda item: len(
            normalize(
                item[1]
            )
        ),
        reverse=True,
    )

    for club_id, alias in aliases:
        needle = normalize(
            alias
        )

        if not needle:
            continue

        match = re.search(
            r"(?<![a-z0-9])"
            + re.escape(needle)
            + r"(?![a-z0-9])",
            normalized,
        )

        if not match:
            continue

        if club_id not in found:
            found[club_id] = {
                "id": club_id,
                "name": CANONICAL_NAMES.get(
                    club_id,
                    club_id.replace(
                        "-",
                        " ",
                    ).title(),
                ),
                "alias": alias,
                "start": match.start(),
                "end": match.end(),
            }

    return sorted(
        found.values(),
        key=lambda item: item["start"],
    )


def canonical_known_side(
    value: str,
) -> dict[str, Any] | None:
    clubs = find_known_clubs(value)

    if len(clubs) != 1:
        return None

    club = clubs[0]

    return {
        "id": club["id"],
        "name": club["name"],
    }


# ============================================================
# SCORES / COMPETITIONS
# ============================================================

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

HYPHEN_PAIR_RE = re.compile(
    r"\s+[-–—]\s+"
)


def extract_score(
    title: str,
) -> str | None:
    match = SCORE_RE.search(
        title
    )

    if not match:
        return None

    return (
        f"{match.group(1)}-"
        f"{match.group(2)}"
    )


def extract_date_from_title(
    title: str,
) -> str | None:
    match = DATE_RE.search(
        title
    )

    if not match:
        return None

    try:
        return datetime(
            int(match.group(1)),
            int(match.group(2)),
            int(match.group(3)),
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

    for competition in sorted(
        COMPETITIONS,
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


# ============================================================
# RECONNAISSANCE DES TITRES
# ============================================================


BASKETBALL_KEYWORDS = {
    "basket",
    "basketball",
    "betclic elite",
    "betclic",
    "lnb",
    "pro a",
    "jeep elite",
    "euroleague",
    "eurocup",
    "fiba",
    "nba",
    "wnba",
    "jl bourg",
    "bourg en bresse",
    "monaco lyon villeurbanne",
    "asvel",
    "cholet basket",
    "nantes basket",
    "gravelines dunkerque",
}

FOOTBALL_KEYWORDS = {
    "football",
    "soccer",
    "ligue 1",
    "ligue 2",
    "premier league",
    "la liga",
    "laliga",
    "bundesliga",
    "serie a",
    "champions league",
    "europa league",
    "conference league",
    "fa cup",
    "carabao cup",
    "trophee des champions",
    "trophée des champions",
    "coupe de france",
}


def is_basketball_title(title: str) -> bool:
    normalized = normalize(title)
    return any(
        normalize(keyword) in normalized
        for keyword in BASKETBALL_KEYWORDS
    )


def is_football_title_for_source(
    title: str,
    source_id: str | None,
) -> bool:
    """
    Le channel DAZN France mélange notamment du football et du basket.
    On exclut donc explicitement les titres basketball avant toute
    détection d'équipe.
    """
    if is_basketball_title(title):
        return False

    # Pour les autres sources, leur flux est déjà football-focused.
    if source_id != "dazn-france":
        return True

    normalized = normalize(title)

    # Pour DAZN, un titre football doit idéalement contenir une
    # compétition football ou au moins deux clubs de notre vocabulaire.
    if any(
        normalize(keyword) in normalized
        for keyword in FOOTBALL_KEYWORDS
    ):
        return True

    clubs = find_known_clubs(title)
    if len(clubs) >= 2:
        return True

    return False


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


def is_contextual_mention(
    title: str,
) -> bool:
    normalized = normalize(
        title
    )

    return any(
        normalize(
            phrase
        ) in normalized
        for phrase in CONTEXT_PATTERNS
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

    value = re.sub(
        r"\b(?:20\d{2})[-/]\d{2}\b",
        " ",
        value,
    )

    value = re.sub(
        r"\b(?:J\d+|"
        r"journ[eé]e\s*\d+|"
        r"week\s*\d+|"
        r"round\s*\d+)\b",
        " ",
        value,
        flags=re.I,
    )

    value = re.split(
        r"\s*[|•·]",
        value,
        maxsplit=1,
    )[0]

    value = re.split(
        r"\s+-\s+(?="
        r"(?:premier|ligue|bundesliga|"
        r"la\s+liga|laliga|champions|europa|"
        r"conference|trophee|trophée|"
        r"coupe|club|league|"
        r"highlights?|résumé|resume|"
        r"goals?|buts?)\b)",
        value,
        maxsplit=1,
        flags=re.I,
    )[0]

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

    words = normalized.split()

    if len(words) > 4:
        return True

    return all(
        word in GENERIC
        for word in words
    )


def infer_unknown_side(
    text: str,
) -> str:
    """
    Essaie d'identifier un adversaire non présent dans KNOWN_CLUBS.

    Très strict pour éviter :
      - les années comme "2026"
      - les scores
      - les phrases de joueur
      - les morceaux de titre sans nom de club
    """
    value = clean_side(text)

    value = re.sub(
        r"^\s*(?:un|une|le|la|les|l['’]|the)\s+",
        "",
        value,
        flags=re.I,
    )

    words = [
        word.strip(".,!?;:()[]{}")
        for word in value.split()
        if normalize(word)
    ]

    if not words or len(words) > 3:
        return ""

    useful_words = []

    for word in words:
        token = normalize(word)

        if not token:
            continue

        # Une année, un score ou un nombre seul ne peut pas être une équipe.
        if re.fullmatch(r"\d{1,4}", token):
            return ""

        if token in GENERIC:
            return ""

        useful_words.append(word)

    result = " ".join(useful_words).strip()

    if not result or side_is_generic(result):
        return ""

    normalized_result = normalize(result)

    # Refuse les morceaux trop ressemblants à des informations de match.
    if normalized_result in {
        "2026",
        "2027",
        "2026 27",
        "2027 28",
    }:
        return ""

    return result


def explicit_match_sides(
    title: str,
) -> tuple[
    str,
    str,
] | None:
    text = html.unescape(
        title or ""
    )

    # Score first.
    score = SCORE_RE.search(
        text
    )

    if score:
        left = text[
            :score.start()
        ]

        right = text[
            score.end():
        ]

        right = re.split(
            r"\s*[|•·]",
            right,
            maxsplit=1,
        )[0]

        if (
            left.strip()
            and right.strip()
        ):
            return (
                left,
                right,
            )

    # "Arsenal / Chelsea"
    # "PSG vs Monaco"
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

        if (
            left.strip()
            and right.strip()
        ):
            return (
                left,
                right,
            )

    # "Real Betis - Real Madrid"
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

        if (
            left.strip()
            and right.strip()
        ):
            return (
                left,
                right,
            )

    return None


def natural_match_sides(
    title: str,
) -> tuple[
    str,
    str,
] | None:
    clubs = find_known_clubs(
        title
    )

    if len(clubs) < 2:
        return None

    # For titles with explicit context phrases,
    # first two clubs generally identify the actual match.
    normalized = normalize(
        title
    )

    context_positions = []

    for phrase in CONTEXT_PATTERNS:
        needle = normalize(
            phrase
        )

        position = normalized.find(
            needle
        )

        if position >= 0:
            context_positions.append(
                position
            )

    if context_positions:
        context_position = min(
            context_positions
        )

        before_context = [
            club
            for club in clubs
            if club["start"]
            < context_position
        ]

        if len(
            before_context
        ) >= 2:
            return (
                before_context[0][
                    "name"
                ],
                before_context[1][
                    "name"
                ],
            )

    return (
        clubs[0]["name"],
        clubs[1]["name"],
    )



# ============================================================
# VALIDATION DES AFFICHES SUIVIES
# ============================================================

# Affiches tirées de la liste fournie pour les 5 équipes suivies.
# Sans API : une vidéo doit correspondre à une vraie affiche de cette
# liste pour être transformée en match.
REFERENCE_MATCH_PAIRS = {
    frozenset(pair)
    for pair in {
        # OL
        ("ol", "macon"), ("ol", "saint-gall"), ("ol", "servette"),
        ("ol", "sparta-prague"), ("ol", "fenerbahce"),
        ("ol", "toulouse"), ("ol", "le-havre"), ("ol", "auxerre"),
        ("ol", "paris-fc"), ("ol", "rennes"), ("ol", "lens"),
        ("ol", "nice"), ("ol", "psg"), ("ol", "angers"),
        ("ol", "brest"), ("ol", "lille"), ("ol", "monaco"),
        ("ol", "troyes"), ("ol", "marseille"), ("ol", "le-mans"),
        ("ol", "lorient"), ("ol", "strasbourg"),

        # Bayern
        ("bayern", "wiesbaden"), ("bayern", "rottach-egern"),
        ("bayern", "jeju-united"), ("bayern", "aston-villa"),
        ("bayern", "leipzig"), ("bayern", "heidenheim"),
        ("bayern", "dortmund"), ("bayern", "stuttgart"),
        ("bayern", "schalke"), ("bayern", "elversberg"),
        ("bayern", "union-berlin"), ("bayern", "augsburg"),
        ("bayern", "freiburg"),

        # Arsenal
        ("arsenal", "girona"), ("arsenal", "real-betis"),
        ("arsenal", "como"), ("arsenal", "dortmund"),
        ("arsenal", "man-city"), ("arsenal", "coventry"),
        ("arsenal", "aston-villa"), ("arsenal", "chelsea"),
        ("arsenal", "sunderland"), ("arsenal", "brighton"),
        ("arsenal", "leeds-united"), ("arsenal", "nottingham-forest"),
        ("arsenal", "everton"), ("arsenal", "liverpool"),
        ("arsenal", "hull-city"), ("arsenal", "newcastle"),

        # PSG
        ("psg", "mallorca"), ("psg", "man-united"),
        ("psg", "aston-villa"), ("psg", "lens"),
        ("psg", "rennes"), ("psg", "lille"), ("psg", "monaco"),
        ("psg", "brest"), ("psg", "marseille"), ("psg", "le-mans"),
        ("psg", "strasbourg"), ("psg", "ol"),

        # Real Madrid
        ("real-madrid", "alcorcon"), ("real-madrid", "leganes"),
        ("real-madrid", "fiorentina"), ("real-madrid", "ferencvaros"),
        ("real-madrid", "a-coruna"), ("real-madrid", "schalke"),
        ("real-madrid", "espanyol"), ("real-madrid", "real-sociedad"),
        ("real-madrid", "malaga"), ("real-madrid", "real-betis"),
        ("real-madrid", "rayo-vallecano"), ("real-madrid", "elche"),
        ("real-madrid", "atletico-madrid"), ("real-madrid", "villarreal"),
        ("real-madrid", "sevilla"), ("real-madrid", "barcelona"),
        ("real-madrid", "racing-santander"),
    }
}

FOLLOWED_REFERENCE_IDS = {
    "psg",
    "arsenal",
    "bayern",
    "real-madrid",
    "ol",
}

CONTEXTUAL_NEGATIVE_PATTERNS = (
    "apres",
    "après",
    "avant",
    "depuis",
    "mercato",
    "interview",
    "interviewe",
    "interviewé",
    "reaction",
    "réaction",
    "reactions",
    "réactions",
    "presse",
    "conférence",
    "conference",
    "best of",
    "top buts",
    "top skills",
    "stories",
    "inside",
)


def followed_mention_is_contextual(
    title: str,
    club: dict[str, Any],
) -> bool:
    """
    Vérifie si la mention du club suivi sert seulement de contexte
    ("après l'OL", "avant Lyon", "mercato du PSG", etc.).
    """
    normalized = normalize(title)
    club_name = normalize(club["name"])
    position = normalized.find(club_name)

    if position < 0:
        return False

    prefix = normalized[
        max(0, position - 45):position
    ]

    contextual_prefixes = (
        "apres ",
        "après ",
        "avant ",
        "mercato du ",
        "mercato de ",
        "depuis ",
        "retour de ",
        "apres l",
    )

    return any(
        prefix.rstrip().endswith(
            value
        )
        for value in contextual_prefixes
    )


def reference_match_from_title(
    title: str,
    teams: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """
    Détecte une affiche directement depuis le titre YouTube, sans API.

    Règle volontairement simple :
    - il faut au moins 2 clubs connus dans le titre ;
    - au moins un des deux doit être une équipe suivie ;
    - on privilégie les formats explicites "A / B", "A - B", "A vs B",
      "A contre B", etc. ;
    - une équipe suivie citée comme simple contexte ("après l'OL", "mercato
      du PSG", ...) est refusée.

    La liste des matchs fournie par l'utilisateur sert de référence :
    l'affiche détectée doit appartenir à cette liste pour être conservée.
    Cela évite qu'une simple mention d'une équipe dans un autre sujet soit
    interprétée comme un résumé de match.
    """
    clubs = find_known_clubs(title)

    if len(clubs) < 2:
        return None

    normalized_title = normalize(title)

    # Déduplication en conservant la première occurrence de chaque club.
    unique: dict[str, dict[str, Any]] = {}
    for club in clubs:
        unique.setdefault(club["id"], club)

    ordered = sorted(
        unique.values(),
        key=lambda club: club["start"],
    )

    followed_clubs = []
    for club in ordered:
        if club["id"] in FOLLOWED_REFERENCE_IDS:
            followed_clubs.append(club)

    if not followed_clubs:
        return None

    candidates = []

    for i, left in enumerate(ordered):
        for right in ordered[i + 1:]:
            left_followed = left["id"] in FOLLOWED_REFERENCE_IDS
            right_followed = right["id"] in FOLLOWED_REFERENCE_IDS

            if not (left_followed or right_followed):
                continue

            # Une équipe suivie citée comme contexte n'est pas l'affiche.
            contextual_followed = False
            if left_followed:
                contextual_followed = contextual_followed or followed_mention_is_contextual(
                    title,
                    left,
                )
            if right_followed:
                contextual_followed = contextual_followed or followed_mention_is_contextual(
                    title,
                    right,
                )
            if contextual_followed:
                continue

            # L'affiche doit faire partie des confrontations connues de la
            # saison fournie dans la configuration de ce collecteur.
            pair_ids = frozenset({left["id"], right["id"]})
            if pair_ids not in REFERENCE_MATCH_PAIRS:
                continue

            between = normalized_title[
                left["end"]:right["start"]
            ]

            explicit_separator = bool(
                re.search(
                    r"(?:^|\s)(?:/|vs|v|contre|face a|face à)(?:\s|$)",
                    between,
                    flags=re.I,
                )
                or re.search(r"[-–—:]", between)
            )

            # Distance textuelle entre les noms de clubs.
            distance = right["start"] - left["end"]

            score = 0
            if explicit_separator:
                score += 100
            if distance <= 12:
                score += 55
            elif distance <= 35:
                score += 40
            elif distance <= 70:
                score += 20

            if len(ordered) == 2:
                score += 60

            # Les titres avec plusieurs clubs doivent avoir un lien très
            # explicite entre les deux clubs sélectionnés, sinon on risque
            # d'interpréter un contexte comme une affiche.
            if len(ordered) >= 3 and not explicit_separator:
                continue

            # Renforce les titres football de type résumé / highlights,
            # sans en faire une condition d'identification globale.
            if any(
                token in normalized_title
                for token in (
                    "resume",
                    "highlights",
                    "highlight",
                    "match recap",
                    "recap",
                    "buts",
                    "goals",
                )
            ):
                score += 20

            # Avec exactement deux clubs connus, le titre peut être une
            # formulation éditoriale sans séparateur (« ... le PSG à Rennes »).
            # Dans ce cas, la présence des deux clubs suffit comme signal fort.
            minimum_score = 60 if len(ordered) == 2 else 80
            if score < minimum_score:
                continue

            candidates.append(
                (
                    score,
                    left,
                    right,
                )
            )

    if not candidates:
        return None

    candidates.sort(
        key=lambda item: item[0],
        reverse=True,
    )

    _, first, second = candidates[0]

    left_followed = None
    right_followed = None

    for team in teams:
        if team_matches(first["name"], team):
            left_followed = {
                "id": team["id"],
                "name": team["name"],
            }
        if team_matches(second["name"], team):
            right_followed = {
                "id": team["id"],
                "name": team["name"],
            }

    if not (left_followed or right_followed):
        return None

    return {
        "home": {
            "club_id": first["id"],
            "name": CANONICAL_NAMES.get(
                first["id"],
                first["name"],
            ),
            "followed": bool(left_followed),
            "followed_team_id": (
                left_followed["id"] if left_followed else None
            ),
        },
        "away": {
            "club_id": second["id"],
            "name": CANONICAL_NAMES.get(
                second["id"],
                second["name"],
            ),
            "followed": bool(right_followed),
            "followed_team_id": (
                right_followed["id"] if right_followed else None
            ),
        },
        "confidence": "title-pair",
    }

def identify_match(
    title: str,
    teams: list[dict[str, Any]],
) -> dict[str, Any] | None:
    return reference_match_from_title(
        title,
        teams,
    )


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

    if not is_football_title_for_source(
        title,
        video.get("source_id"),
    ):
        return None


    if not title:
        return None

    summary_like = looks_like_summary(
        title,
        app,
    )

    match = identify_match(
        title,
        teams,
    )

    if not match:
        return None

    # La chaîne officielle Ligue 1 publie aussi des résumés avec un titre
    # éditorial (« Nuamah régale... », « Openda sauve... ») sans le mot
    # « résumé ». Une affiche valide suffit donc pour cette source.
    if not summary_like and video.get("source_id") != "ligue-1":
        return None

    # Les mentions contextuelles de l'équipe suivie sont déjà filtrées
    # dans reference_match_from_title() (ex. « après l'OL »).

    home = match["home"]
    away = match["away"]

    followed_ids = sorted(
        {
            value
            for value in [
                home[
                    "followed_team_id"
                ],
                away[
                    "followed_team_id"
                ],
            ]
            if value
        }
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

    # IMPORTANT:
    # Score is not part of identity.
    home_key = home[
        "club_id"
    ]

    away_key = away[
        "club_id"
    ]

    round_key = ""

    round_match = re.search(
        r"\b(?:J(\d+)|"
        r"journ[eé]e\s*(\d+)|"
        r"week\s*(\d+)|"
        r"round\s*(\d+))\b",
        normalize(title),
        flags=re.I,
    )

    if round_match:
        values = [
            value
            for value in round_match.groups()
            if value
        ]

        if values:
            round_key = (
                "round:"
                + values[0]
            )

    if not round_key:
        round_key = (
            "date:"
            + normalize(
                match_date
            )[:10]
            if match_date
            else "date:unknown"
        )

    match_key = "|".join(
        [
            "match",
            str(home_key),
            str(away_key),
            slug(
                competition
                or "football"
            ),
            round_key,
        ]
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

    return {
        "is_summary": True,
        "match_key": match_key,
        "match_title": match_title,
        "home_team": {
            "id": home[
                "followed_team_id"
            ],
            "name": home[
                "name"
            ],
            "followed": home[
                "followed"
            ],
        },
        "away_team": {
            "id": away[
                "followed_team_id"
            ],
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
            "id": metadata[
                side
            ]["id"],
            "name": metadata[
                side
            ]["name"],
        }
        for side in (
            "home_team",
            "away_team",
        )
        if metadata[
            side
        ]["id"]
    ]

    return result


# ============================================================
# YOUTUBE
# ============================================================


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

    channel_match = re.search(
        r"/channel/(UC[0-9A-Za-z_-]{20,})",
        url,
    )

    if channel_match:
        return channel_match.group(
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
                        f"watch?v={video_id}"
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
    channel_id = resolve_channel_id(
        source
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

        alternate = entry.find(
            "atom:link[@rel='alternate']",
            NS,
        )

        url_value = (
            alternate.get(
                "href"
            )
            if alternate is not None
            else (
                "https://www.youtube.com/"
                f"watch?v={video_id}"
            )
        )

        result.append(
            {
                "id": video_id,
                "title": html.unescape(
                    title
                ),
                "url": url_value,
                "published_at": parse_date(
                    entry.findtext(
                        "atom:published",
                        "",
                        NS,
                    )
                ),
                "updated_at": parse_date(
                    entry.findtext(
                        "atom:updated",
                        "",
                        NS,
                    )
                ),
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


def fetch_video_details(
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
        process.returncode != 0
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


def source_limit(
    source: dict[str, Any],
    default_limit: int,
) -> int:
    overrides = {
        "bein-sports-france": 220,
        "canal-plus-sport": 160,
        "dazn-france": 160,
        "ligue-1": 180,
    }

    return max(
        default_limit,
        overrides.get(
            source.get(
                "id"
            ),
            default_limit,
        ),
    )


# ============================================================
# PERSISTANCE
# ============================================================


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

        source_map = {}

        for item in items:
            source_id = item.get(
                "source_id"
            )

            if (
                source_id
                and source_id
                not in source_map
            ):
                source_map[
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
                        team[
                            "id"
                        ]
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
                        team[
                            "name"
                        ]
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
                    source_map
                ),
                "sources": list(
                    source_map.values()
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


# ============================================================
# MAIN
# ============================================================


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

    default_limit = max(
        60,
        int(
            app.get(
                "max_videos_per_source",
                60,
            )
        ),
    )

    print(
        f"Scanning {len(sources)} sources..."
    )

    all_new_videos = []
    statuses = []

    for source in sources:
        limit = source_limit(
            source,
            default_limit,
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
                videos = run_ytdlp_playlist(
                    source,
                    limit,
                )
                method = "yt-dlp"

            except Exception as exc:
                print(
                    f"{source.get('name')} "
                    f"yt-dlp failed, falling back to Atom: "
                    f"{exc}"
                )

                videos = fetch_atom(
                    source,
                    min(
                        limit,
                        15,
                    ),
                )
                method = "atom"

            # Recover missing publication dates only for likely summaries.
            for video in [
                item
                for item in videos
                if (
                    not item.get(
                        "published_at"
                    )
                    and looks_like_summary(
                        item.get(
                            "title",
                            "",
                        ),
                        app,
                    )
                )
            ][:60]:
                details = fetch_video_details(
                    video[
                        "id"
                    ]
                )

                if details:
                    for key, value in details.items():
                        if value not in (
                            None,
                            "",
                        ):
                            video[
                                key
                            ] = value

                time.sleep(
                    0.10
                )

            all_new_videos.extend(
                videos
            )

            status["ok"] = True
            status["count"] = len(
                videos
            )
            status["method"] = method

        except (
            HTTPError,
            URLError,
            ET.ParseError,
            TimeoutError,
            RuntimeError,
            ValueError,
            json.JSONDecodeError,
        ) as exc:
            status["error"] = str(
                exc
            )[:1000]

        except Exception as exc:
            status["error"] = (
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

    # Reclassify the old dataset AND the new videos.
    # This removes previously stored false positives.
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
        value = (
            video.get(
                "published_at"
            )
            or video.get(
                "match_date"
            )
        )

        # Keep genuinely undated candidates temporarily.
        if not value:
            filtered.append(
                video
            )
            continue

        try:
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
        "Football Hub collection complete"
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
