#!/usr/bin/env python3
from __future__ import annotations

import html
import json
import re
import subprocess
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config.json"
EXAMPLE = ROOT / "config.example.json"
OUTPUT = ROOT / "data" / "videos.json"

SCORE_RE = re.compile(
    r"(?<!\d)(\d{1,2})\s*[-–—:]\s*(\d{1,2})(?!\d)"
)

DATE_RE = re.compile(
    r"\b(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})\b"
)

# Important :
# the "/" separator deliberately ignores things like 26/27.
EXPLICIT_RE = re.compile(
    r"\s+(?:vs\.?|v\.?|contre|@)\s+|(?<!\d)\s*/\s*(?!\d)",
    re.I,
)

HYPHEN_RE = re.compile(
    r"\s+[-–—]\s+"
)

RELATION_RE = re.compile(
    r"\b(?:face\s+à|face\s+a|contre|sur)\b",
    re.I,
)


DEFAULT_SUMMARY = {
    "highlights",
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


DEFAULT_EXCLUDE = {
    "reaction",
    "reactions",
    "preview",
    "prediction",
    "predictions",
    "press conference",
    "press-conference",
    "interview",
    "interviews",
    "training",
    "behind the scenes",
    "transfer",
    "transfers",
    "news",
    "news roundup",
    "analysis",
    "tactical analysis",
    "débrief",
    "debrief",
    "avant-match",
    "avant match",
    "conférence de presse",
    "conférence",
    "podcast",
    "émission",
    "emission",
    "mercato",
    "inside",
    "reveals",
    "reveal",
    "exclusive",
    "best of",
    "top goals",
    "top buts",
}


CONTEXT_ONLY = {
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


def load_json(
    path: Path,
    fallback: Path | None = None,
) -> dict[str, Any]:
    target = path if path.exists() else fallback

    if target is None or not target.exists():
        raise FileNotFoundError(
            f"Configuration introuvable: {path}"
        )

    with target.open(
        "r",
        encoding="utf-8",
    ) as fh:
        return json.load(fh)


def normalize(value: str | None) -> str:
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
    n = normalize(text)
    t = normalize(term)

    if not t:
        return False

    return bool(
        re.search(
            r"(?<![a-z0-9])"
            + re.escape(t)
            + r"(?![a-z0-9])",
            n,
        )
    )


def parse_date(
    value: Any,
) -> str | None:
    if value is None or value == "":
        return None

    value = str(value).strip()

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

        if (
            re.fullmatch(
                r"\d+(?:\.\d+)?",
                value,
            )
            and float(value)
            > 1_000_000_000
        ):
            return datetime.fromtimestamp(
                float(value),
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


def team_aliases(
    team: dict[str, Any],
) -> list[str]:
    values = [
        team.get(
            "name",
            "",
        ),
        *(
            team.get(
                "aliases",
                []
            )
            or []
        ),
    ]

    return [
        str(value)
        for value in values
        if value
    ]


def team_in(
    text: str,
    team: dict[str, Any],
) -> bool:
    return any(
        contains(
            text,
            alias,
        )
        for alias in team_aliases(
            team
        )
    )


def team_hit(
    text: str,
    teams: list[dict[str, Any]],
) -> dict[str, Any] | None:
    for team in teams:
        if team_in(
            text,
            team,
        ):
            return {
                "id": team["id"],
                "name": team["name"],
            }

    return None


def team_hits(
    text: str,
    teams: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {
            "id": team["id"],
            "name": team["name"],
        }
        for team in teams
        if team_in(
            text,
            team,
        )
    ]


def get_competition(
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
                competition
                .title()
                .replace(
                    "Trophee",
                    "Trophée",
                )
            )

    return None


def strip_prefix(
    text: str,
) -> str:
    return re.sub(
        r"^\s*"
        r"(?:le|la|les|l['’])?\s*"
        r"(?:résumé|resume|highlights?|recap)"
        r"\s*"
        r"(?:de|du|des|of)?\s*"
        r"[:\-–—|]?\s*",
        "",
        text,
        flags=re.I,
    ).strip()


def clean_side(
    text: str,
    teams: list[dict[str, Any]],
) -> str:
    value = strip_prefix(
        html.unescape(
            text or ""
        )
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

    # Remove competition / highlight suffixes.
    value = re.split(
        r"\s+-\s+(?="
        r"(?:premier|ligue|bundesliga|"
        r"la\s+liga|champions|europa|"
        r"conference|troph|coupe|club|"
        r"league|highlights?|resume|"
        r"résumé|goals?|buts?)\b)",
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


def generic_side(
    text: str,
) -> bool:
    words = normalize(
        text
    ).split()

    if not words:
        return True

    if len(words) > 4:
        return True

    return all(
        word in GENERIC
        for word in words
    )


def extract_sides(
    title: str,
    teams: list[dict[str, Any]],
) -> tuple[
    str,
    str,
    str,
] | None:
    text = html.unescape(
        title or ""
    )

    def valid_pair(
        left: str,
        right: str,
        confidence: str,
    ) -> tuple[
        str,
        str,
        str,
    ] | None:
        left = clean_side(
            left,
            teams,
        )

        right = clean_side(
            right,
            teams,
        )

        if not left or not right:
            return None

        left_team = team_hit(
            left,
            teams,
        )

        right_team = team_hit(
            right,
            teams,
        )

        # A non-team side may be a short opponent name,
        # but not a long editorial/player sentence.
        if (
            left_team is None
            and generic_side(left)
        ):
            return None

        if (
            right_team is None
            and generic_side(right)
        ):
            return None

        if (
            left_team is None
            and right_team is None
        ):
            return None

        # Reject player/stat titles:
        # "Bradley Barcola en solitaire 2-0 PSG".
        if (
            left_team is None
            and len(
                normalize(left).split()
            )
            > 2
        ):
            return None

        if (
            right_team is None
            and len(
                normalize(right).split()
            )
            > 2
        ):
            return None

        return (
            left,
            right,
            confidence,
        )

    # Strongest signal: a real score.
    score_match = SCORE_RE.search(
        text
    )

    if score_match:
        left = text[
            :score_match.start()
        ]

        right = text[
            score_match.end():]

        right = re.split(
            r"\s*[|•·]\s*",
            right,
            maxsplit=1,
        )[0]

        right = re.split(
            r"\s+-\s+(?="
            r"(?:premier|ligue|bundesliga|"
            r"la\s+liga|champions|europa|"
            r"conference|troph|coupe|club|"
            r"league|highlights?|resume|"
            r"résumé|goals?|buts?)\b)",
            right,
            maxsplit=1,
            flags=re.I,
        )[0]

        candidate = valid_pair(
            left,
            right,
            "high",
        )

        if candidate:
            return candidate

    # Explicit "vs", "/", "contre", "@".
    for separator in reversed(
        list(
            EXPLICIT_RE.finditer(
                text
            )
        )
    ):
        candidate = valid_pair(
            text[
                :separator.start()
            ],
            text[
                separator.end():
            ],
            "high",
        )

        if candidate:
            return candidate

    # Common YouTube format:
    # "RC LENS - PSG Highlights".
    for separator in reversed(
        list(
            HYPHEN_RE.finditer(
                text
            )
        )
    ):
        candidate = valid_pair(
            text[
                :separator.start()
            ],
            text[
                separator.end():
            ],
            "high",
        )

        if candidate:
            return candidate

    # Natural language:
    # "Le Bayern se casse les dents sur Schalke".
    for relation in RELATION_RE.finditer(
        text
    ):
        before = clean_side(
            text[
                :relation.start()
            ],
            teams,
        )

        after = clean_side(
            text[
                relation.end():
            ],
            teams,
        )

        if not team_hits(
            before,
            teams,
        ):
            continue

        after = re.split(
            r"[!?.,]",
            after,
            maxsplit=1,
        )[0].strip()

        words = []

        for word in after.split():
            normalized_word = normalize(
                word
            )

            if (
                normalized_word
                in GENERIC
                or len(words) >= 4
            ):
                break

            words.append(
                word.strip(
                    ".,!?;:()[]{}"
                )
            )

        opponent = " ".join(
            words
        ).strip()

        if not opponent:
            continue

        candidate = valid_pair(
            before,
            opponent,
            "medium",
        )

        if candidate:
            return candidate

    return None


def looks_summary(
    title: str,
    app: dict[str, Any],
) -> bool:
    includes = (
        app.get(
            "summary_keywords"
        )
        or list(
            DEFAULT_SUMMARY
        )
    )

    excludes = (
        app.get(
            "exclude_keywords"
        )
        or list(
            DEFAULT_EXCLUDE
        )
    )

    return (
        any(
            contains(
                title,
                keyword,
            )
            for keyword in includes
        )
        and not any(
            contains(
                title,
                keyword,
            )
            for keyword in excludes
        )
    )


def classify(
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

    if not looks_summary(
        title,
        app,
    ):
        return None

    hits = team_hits(
        title,
        teams,
    )

    if not hits:
        return None

    # Context-only mentions such as:
    # "double le Bayern au classement"
    # are rejected unless the title also has explicit match syntax.
    if (
        any(
            contains(
                title,
                phrase,
            )
            for phrase in CONTEXT_ONLY
        )
        and len(hits) == 1
    ):
        if not (
            EXPLICIT_RE.search(
                title
            )
            or HYPHEN_RE.search(
                title
            )
            or SCORE_RE.search(
                title
            )
        ):
            return None

    sides = extract_sides(
        title,
        teams,
    )

    if not sides:
        return None

    left, right, confidence = sides

    left_team = team_hit(
        left,
        teams,
    )

    right_team = team_hit(
        right,
        teams,
    )

    if not left_team and not right_team:
        return None

    # Reject only an editorial side that isn't the configured team.
    if (
        left_team is None
        and generic_side(left)
    ):
        return None

    if (
        right_team is None
        and generic_side(right)
    ):
        return None

    score = None

    score_match = SCORE_RE.search(
        title
    )

    if score_match:
        score = (
            f"{score_match.group(1)}-"
            f"{score_match.group(2)}"
        )

    published = (
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

    date_in_title = None

    date_match = DATE_RE.search(
        title
    )

    if date_match:
        try:
            date_in_title = datetime(
                int(
                    date_match.group(
                        1
                    )
                ),
                int(
                    date_match.group(
                        2
                    )
                ),
                int(
                    date_match.group(
                        3
                    )
                ),
                tzinfo=timezone.utc,
            ).isoformat()

        except ValueError:
            date_in_title = None

    home = (
        left_team
        or {
            "id": None,
            "name": clean_side(
                left,
                teams,
            ),
        }
    )

    away = (
        right_team
        or {
            "id": None,
            "name": clean_side(
                right,
                teams,
            ),
        }
    )

    if (
        not home["name"]
        or not away["name"]
        or normalize(
            home["name"]
        )
        == normalize(
            away["name"]
        )
    ):
        return None

    followed_ids = [
        team["id"]
        for team in (
            left_team,
            right_team,
        )
        if team
    ]

    if not followed_ids:
        return None

    pair_tokens = []

    for side, team in (
        (home, left_team),
        (away, right_team),
    ):
        if team:
            pair_tokens.append(
                team["id"]
            )
        else:
            pair_tokens.append(
                "opp:"
                + slug(
                    side["name"]
                )
            )

    match_key = "|".join(
        [
            "match",
            "+".join(
                sorted(
                    pair_tokens
                )
            ),
            slug(
                get_competition(
                    title
                )
                or "football"
            ),
            score or "noscore",
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
            f"{home['name']} "
            f"vs "
            f"{away['name']}"
        )

    return {
        "is_summary": True,
        "match_key": match_key,
        "match_title": match_title,
        "home_team": {
            "id": home["id"],
            "name": home["name"],
            "followed": bool(
                left_team
            ),
        },
        "away_team": {
            "id": away["id"],
            "name": away["name"],
            "followed": bool(
                right_team
            ),
        },
        "score": score,
        "competition": get_competition(
            title
        ),
        "match_date": (
            date_in_title
            or published
        ),
        "team_ids": sorted(
            set(
                followed_ids
            )
        ),
        "match_confidence": confidence,
        "summary_keywords": [
            keyword
            for keyword in (
                app.get(
                    "summary_keywords"
                )
                or DEFAULT_SUMMARY
            )
            if contains(
                title,
                keyword,
            )
        ],
    }


def enrich(
    video: dict[str, Any],
    app: dict[str, Any],
    teams: list[dict[str, Any]],
) -> dict[str, Any] | None:
    metadata = classify(
        video,
        app,
        teams,
    )

    if not metadata:
        return None

    result = dict(
        video
    )

    result.update(
        metadata
    )

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


def run_ytdlp(
    source: dict[str, Any],
    limit: int,
) -> list[dict[str, Any]]:
    url = (
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
        timeout=180,
    )

    if process.returncode not in (
        0,
        1,
    ):
        raise RuntimeError(
            process.stderr[
                -1200:
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

    videos = []

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

        published_at = (
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
        )

        videos.append(
            {
                "id": video_id,
                "title": html.unescape(
                    item.get(
                        "title"
                    )
                    or ""
                ),
                "url": (
                    item.get(
                        "webpage_url"
                    )
                    or (
                        f"https://www.youtube.com/"
                        f"watch?v={video_id}"
                    )
                ),
                "published_at": published_at,
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
                    source["id"],
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

    return videos


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
        timeout=40,
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
        "thumbnail": payload.get(
            "thumbnail"
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


def merge_records(
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
        enriched = enrich(
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
        list[dict[str, Any]],
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
            key=lambda video: (
                video.get(
                    "published_at"
                )
                or ""
            ),
            reverse=True,
        )

        first = items[0]

        source_ids = {
            video.get(
                "source_id"
            )
            for video in items
            if video.get(
                "source_id"
            )
        }

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
                "score": first.get(
                    "score"
                ),
                "competition": first.get(
                    "competition"
                ),
                "match_date": min(
                    (
                        video.get(
                            "match_date"
                        )
                        or video.get(
                            "published_at"
                        )
                        for video in items
                        if (
                            video.get(
                                "match_date"
                            )
                            or video.get(
                                "published_at"
                            )
                        )
                    ),
                    default=None,
                ),
                "published_at": max(
                    (
                        video.get(
                            "published_at"
                        )
                        for video in items
                        if video.get(
                            "published_at"
                        )
                    ),
                    default=None,
                ),
                "team_ids": sorted(
                    {
                        team["id"]
                        for video in items
                        for team in (
                            video.get(
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
                        for video in items
                        for team in (
                            video.get(
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
                    source_ids
                ),
                "sources": [
                    {
                        "id": video.get(
                            "source_id"
                        ),
                        "name": video.get(
                            "source_name"
                        ),
                    }
                    for video in items
                    if video.get(
                        "source_id"
                    )
                ],
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

    existing = {
        "videos": []
    }

    if OUTPUT.exists():
        try:
            existing = json.loads(
                OUTPUT.read_text(
                    encoding="utf-8"
                )
            )
        except (
            OSError,
            json.JSONDecodeError,
        ):
            existing = {
                "videos": []
            }

    limit = max(
        60,
        int(
            app.get(
                "max_videos_per_source",
                60,
            )
        ),
    )

    collected: list[
        dict[str, Any]
    ] = []

    statuses = []

    print(
        f"Scanning {len(sources)} sources "
        f"with up to {limit} recent videos/source..."
    )

    for source in sources:
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
            items = run_ytdlp(
                source,
                limit,
            )

            status[
                "method"
            ] = "yt-dlp"

            status[
                "count"
            ] = len(
                items
            )

            status[
                "ok"
            ] = True

            # Recover a real publication date only for likely summary videos.
            for item in items:
                if (
                    looks_summary(
                        item.get(
                            "title",
                            "",
                        ),
                        app,
                    )
                    and not item.get(
                        "published_at"
                    )
                ):
                    details = fetch_details(
                        item["id"]
                    )

                    if details:
                        item.update(
                            {
                                key: value
                                for key, value in details.items()
                                if value
                                not in (
                                    None,
                                    "",
                                )
                            }
                        )

                    time.sleep(
                        0.15
                    )

            collected.extend(
                items
            )

        except Exception as exc:
            status[
                "error"
            ] = (
                f"{type(exc).__name__}: "
                f"{exc}"
            )[:800]

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

    # Reclassify existing and new videos using the same
    # new engine. Old false positives therefore disappear.
    videos = merge_records(
        existing.get(
            "videos",
            [],
        ),
        collected,
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

    retained = []

    for video in videos:
        date_value = (
            video.get(
                "published_at"
            )
            or video.get(
                "match_date"
            )
        )

        # Keep undated candidates rather than deleting
        # them immediately; the website can still display them.
        if not date_value:
            retained.append(
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
                retained.append(
                    video
                )

        except ValueError:
            retained.append(
                video
            )

    retained.sort(
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
        retained
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

        "videos": retained,

        "matches": matches,

        "stats": {
            "videos": len(
                retained
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

    print(
        "Football Hub collection complete"
    )

    print(
        f"Videos retained : "
        f"{len(retained)}"
    )

    print(
        f"Matches grouped : "
        f"{len(matches)}"
    )

    for match in matches[:20]:
        print(
            f"- {match['title']} "
            f"| sources="
            f"{match['sources_count']}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
