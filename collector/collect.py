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

ATOM_NS = "http://www.w3.org/2005/Atom"
YT_NS = "http://www.youtube.com/xml/schemas/2015"

NS = {
    "atom": ATOM_NS,
    "yt": YT_NS,
}

USER_AGENT = (
    "FootballHub/4.0 "
    "(+https://github.com/aymerire-sudo/football-hub)"
)

# ---------------------------------------------------------------------------
# Detection vocabulary
# ---------------------------------------------------------------------------

SUMMARY_FALLBACK = {
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

EXCLUDE_FALLBACK = {
    "reaction",
    "reactions",
    "preview",
    "predictions",
    "prediction",
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
    "inside the",
    "reveals",
    "reveal",
    "talks about",
    "speaks about",
    "exclusive",
    "best of",
    "top goals",
    "top buts",
}

# Titres dans lesquels le nom d'une équipe est généralement contextuel.
CONTEXT_PATTERNS = {
    "classement",
    "points",
    "course au titre",
    "course à la ligue",
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
}

# Mots qui ne doivent jamais être considérés comme le nom
# d'un adversaire extrait automatiquement.
GENERIC_NON_TEAM_WORDS = {
    "ligue",
    "league",
    "football",
    "match",
    "matches",
    "game",
    "games",
    "highlights",
    "highlight",
    "résumé",
    "resume",
    "recap",
    "buts",
    "but",
    "goals",
    "goal",
    "all",
    "the",
    "and",
    "avec",
    "pour",
    "sur",
    "face",
    "contre",
    "vs",
    "v",
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
    "heroique",
    "héroïque",
    "héroïques",
    "folle",
    "folles",
    "énorme",
    "enorme",
    "incroyable",
    "impressionnant",
    "impressionnante",
    "solide",
    "dominant",
    "dominant",
    "humilie",
    "humilier",
    "écrase",
    "ecrase",
    "frappe",
    "tombe",
    "gagne",
    "bat",
    "perd",
    "perdu",
    "s'impose",
    "s impose",
    "s'incline",
    "s incline",
    "révèle",
    "reveals",
    "reveal",
    "goals",
    "torres",
    "barcola",
    "mbappe",
    "mbappé",
    "champion",
    "champions",
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

SCORE_RE = re.compile(
    r"(?<!\d)(\d{1,2})\s*[-–—:]\s*(\d{1,2})(?!\d)"
)

DATE_RE = re.compile(
    r"\b(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})\b"
)

# Exemples :
# Arsenal vs Chelsea
# Arsenal v Chelsea
# Arsenal / Chelsea
# Arsenal contre Chelsea
# Arsenal @ Chelsea
EXPLICIT_SEPARATOR_RE = re.compile(
    r"\s+(?:vs\.?|v\.?|contre|@)\s+|\s*/\s*",
    re.IGNORECASE,
)

# Exemple de formulation journalistique :
# Le Bayern se casse les dents sur Schalke héroïque
# Arsenal s'impose face à Chelsea
# Le PSG perd contre Monaco
RELATION_RE = re.compile(
    r"\b(?:sur|contre|face\s+a|face\s+à)\b",
    re.IGNORECASE,
)

# Verbes qui montrent qu'il s'agit probablement d'un vrai match.
MATCH_VERBS = (
    "bat",
    "battu",
    "batte",
    "domine",
    "dominé",
    "gagne",
    "gagné",
    "perd",
    "perdu",
    "tombe",
    "tombé",
    "s'impose",
    "s impose",
    "s'incline",
    "s incline",
    "frappe",
    "frappé",
    "écrase",
    "ecrase",
    "humilie",
    "humilié",
    "neutralise",
    "accroche",
    "accroché",
    "tenu en échec",
)

# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------


def empty_output() -> dict[str, Any]:
    return {
        "generated_at": None,
        "teams": [],
        "source_status": [],
        "videos": [],
        "matches": [],
        "stats": {
            "videos": 0,
            "matches": 0,
            "teams": 0,
            "sources": 0,
        },
    }


def load_json(
    path: Path,
    fallback: Path | None = None,
) -> dict[str, Any]:
    target = path if path.exists() else fallback

    if target is None or not target.exists():
        raise FileNotFoundError(
            f"Impossible de trouver : {path}"
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
    value = value.replace("&", " and ")
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


def slug(value: str | None) -> str:
    return re.sub(
        r"[^a-z0-9]+",
        "-",
        normalize(value),
    ).strip("-")


def compact(value: str | None) -> str:
    return re.sub(
        r"[^a-z0-9]",
        "",
        normalize(value),
    )


def contains_term(
    text: str | None,
    term: str | None,
) -> bool:
    haystack = normalize(text)
    needle = normalize(term)

    if not needle:
        return False

    return (
        re.search(
            r"(?<![a-z0-9])"
            + re.escape(needle)
            + r"(?![a-z0-9])",
            haystack,
        )
        is not None
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
        # yt-dlp upload_date
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

        # Unix timestamp
        if re.fullmatch(
            r"\d+(?:\.\d+)?",
            value,
        ):
            timestamp = float(value)

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


def fetch(
    url: str,
    timeout: int = 30,
) -> bytes:
    request = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": (
                "application/atom+xml,"
                "application/xml,text/xml,*/*"
            ),
        },
    )

    with urlopen(
        request,
        timeout=timeout,
    ) as response:
        return response.read()


def get_text(
    parent: ET.Element,
    path: str,
) -> str:
    node = parent.find(
        path,
        NS,
    )

    if node is None:
        return ""

    return (
        (node.text or "").strip()
    )


def get_attr(
    parent: ET.Element,
    path: str,
    attribute: str,
) -> str:
    node = parent.find(
        path,
        NS,
    )

    if node is None:
        return ""

    return (
        node.attrib
        .get(attribute, "")
        .strip()
    )


# ---------------------------------------------------------------------------
# YouTube channel / feed handling
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

    if direct.startswith("UC"):
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
        return match.group(1)

    try:
        body = fetch(
            url,
            timeout=20,
        ).decode(
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
            (
                r'<link[^>]+itemprop=["\']url["\']'
                r'[^>]+href=["\']https?://www\.youtube\.com/'
                r'channel/(UC[0-9A-Za-z_-]{20,})'
            ),
        ]

        for pattern in patterns:
            found = re.search(
                pattern,
                body,
                flags=re.IGNORECASE,
            )

            if found:
                return found.group(1)

    except Exception:
        pass

    return ""


def parse_atom_feed(
    xml_bytes: bytes,
    source: dict[str, Any],
    channel_id: str,
    limit: int,
) -> list[dict[str, Any]]:
    root = ET.fromstring(
        xml_bytes
    )

    videos: list[
        dict[str, Any]
    ] = []

    entries = root.findall(
        "atom:entry",
        NS,
    )

    for entry in entries[:limit]:
        video_id = get_text(
            entry,
            "yt:videoId",
        )

        if not video_id:
            atom_id = get_text(
                entry,
                "atom:id",
            )

            if atom_id.startswith(
                "yt:video:"
            ):
                video_id = atom_id.rsplit(
                    ":",
                    1,
                )[-1]

        if not video_id:
            continue

        title = html.unescape(
            get_text(
                entry,
                "atom:title",
            )
        )

        published_at = parse_date(
            get_text(
                entry,
                "atom:published",
            )
        )

        updated_at = parse_date(
            get_text(
                entry,
                "atom:updated",
            )
        )

        url = (
            get_attr(
                entry,
                "atom:link[@rel='alternate']",
                "href",
            )
            or (
                "https://www.youtube.com/"
                "watch?v="
                f"{video_id}"
            )
        )

        videos.append(
            {
                "id": video_id,
                "title": title,
                "url": url,
                "published_at": published_at,
                "updated_at": updated_at,
                "thumbnail": (
                    "https://i.ytimg.com/vi/"
                    f"{video_id}/hqdefault.jpg"
                ),
                "source_id": source["id"],
                "source_name": source.get(
                    "name",
                    source["id"],
                ),
                "source_channel_id": channel_id,
                "description": "",
            }
        )

    return videos


def channel_videos_url(
    source: dict[str, Any],
) -> str:
    url = str(
        source.get(
            "youtube_url",
            "",
        )
        or ""
    ).strip()

    if not url:
        return ""

    url = url.rstrip("/")

    if not url.endswith("/videos"):
        url += "/videos"

    return url


def parse_ytdlp_playlist(
    stdout: str,
    source: dict[str, Any],
) -> list[dict[str, Any]]:
    if not stdout.strip():
        return []

    try:
        payload = json.loads(
            stdout
        )
    except json.JSONDecodeError:
        return []

    entries = (
        payload.get("entries")
        or []
    )

    videos: list[
        dict[str, Any]
    ] = []

    for item in entries:
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
                        "title",
                        "",
                    )
                    or ""
                ),
                "url": (
                    item.get(
                        "webpage_url"
                    )
                    or item.get(
                        "original_url"
                    )
                    or (
                        "https://www.youtube.com/"
                        "watch?v="
                        f"{video_id}"
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
                "source_id": source["id"],
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
                "duration": item.get(
                    "duration"
                ),
            }
        )

    return videos


def fetch_playlist_with_ytdlp(
    source: dict[str, Any],
    limit: int,
) -> list[dict[str, Any]]:
    url = channel_videos_url(
        source
    )

    if not url:
        return []

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
        timeout=150,
    )

    if (
        process.returncode
        not in (0, 1)
    ):
        raise RuntimeError(
            process.stderr.strip()[
                -1000:
            ]
            or "yt-dlp failed"
        )

    return parse_ytdlp_playlist(
        process.stdout,
        source,
    )


def title_candidate_for_metadata(
    title: str,
) -> bool:
    norm = normalize(
        title
    )

    if not norm:
        return False

    has_summary_word = any(
        token in norm
        for token in (
            "highlight",
            "resume",
            "recap",
            "goal",
            "goals",
            "buts",
            "match",
        )
    )

    has_match_separator = bool(
        EXPLICIT_SEPARATOR_RE.search(
            title
        )
    )

    has_score = bool(
        SCORE_RE.search(title)
    )

    has_relation = bool(
        RELATION_RE.search(title)
    )

    return (
        has_summary_word
        or has_match_separator
        or has_score
        or has_relation
    )


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
        timeout=35,
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


def enrich_missing_metadata(
    videos: list[dict[str, Any]],
    maximum: int = 45,
) -> list[dict[str, Any]]:
    candidates = [
        video
        for video in videos
        if title_candidate_for_metadata(
            video.get(
                "title",
                "",
            )
        )
    ]

    # Prioritize videos which could actually be displayed.
    candidates = candidates[:maximum]

    for index, video in enumerate(
        candidates,
        start=1,
    ):
        needs_date = not video.get(
            "published_at"
        )

        if not needs_date:
            continue

        details = fetch_video_details(
            video["id"]
        )

        if not details:
            continue

        for key, value in details.items():
            if value not in (
                None,
                "",
            ):
                video[key] = value

        # Keep GitHub Actions from hammering YouTube.
        if index < len(candidates):
            time.sleep(0.25)

    return videos


def extract_source_videos(
    source: dict[str, Any],
    limit: int,
) -> tuple[
    list[dict[str, Any]],
    str,
]:
    ytdlp_error = ""

    try:
        videos = fetch_playlist_with_ytdlp(
            source,
            limit,
        )

        if videos:
            return (
                videos,
                "yt-dlp",
            )

    except Exception as exc:
        ytdlp_error = str(exc)

    channel_id = resolve_channel_id(
        source
    )

    if not channel_id:
        if ytdlp_error:
            raise RuntimeError(
                ytdlp_error
            )

        return [], "atom"

    feed_url = (
        "https://www.youtube.com/"
        "feeds/videos.xml"
        "?channel_id="
        f"{channel_id}"
    )

    xml = fetch(
        feed_url,
        timeout=30,
    )

    return (
        parse_atom_feed(
            xml,
            source,
            channel_id,
            min(
                limit,
                15,
            ),
        ),
        "atom",
    )


# ---------------------------------------------------------------------------
# Team detection
# ---------------------------------------------------------------------------


def team_aliases(
    team: dict[str, Any],
) -> list[str]:
    values = [
        team.get(
            "name",
            "",
        )
    ]

    values.extend(
        team.get(
            "aliases",
            []
        )
        or []
    )

    result = []

    for value in values:
        if value:
            result.append(
                str(value)
            )

    return result


def team_hits_in_text(
    text: str,
    teams: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    hits = []

    for team in teams:
        for alias in team_aliases(
            team
        ):
            if contains_term(
                text,
                alias,
            ):
                hits.append(
                    {
                        "id": team["id"],
                        "name": team["name"],
                        "alias": alias,
                    }
                )
                break

    return hits


def strip_team_names(
    text: str,
    teams: list[dict[str, Any]],
) -> str:
    value = text or ""

    for team in teams:
        for alias in team_aliases(
            team
        ):
            value = re.sub(
                r"(?<![A-Za-z0-9])"
                + re.escape(alias)
                + r"(?![A-Za-z0-9])",
                " ",
                value,
                flags=re.IGNORECASE,
            )

    return value


def clean_side_text(
    text: str,
    teams: list[dict[str, Any]],
) -> str:
    value = html.unescape(
        text or ""
    )

    value = re.sub(
        r"^\s*(?:le|la|les|l['’])?\s*"
        r"(?:résumé|resume|highlights?|recap)"
        r"\s*(?:de|du|des|of)?\s*"
        r"[:\-–—|]?\s*",
        "",
        value,
        flags=re.IGNORECASE,
    )

    value = re.sub(
        r"\([^)]*\)",
        " ",
        value,
    )

    value = re.split(
        r"\s*[|•·]\s*",
        value,
        maxsplit=1,
    )[0]

    value = SCORE_RE.sub(
        " ",
        value,
    )

    # Remove obvious competition suffixes.
    value = re.split(
        r"\s+-\s+(?="
        r"(?:premier|ligue|bundesliga|la\s+liga|"
        r"champions|europa|conference|trophee|"
        r"trophée|coupe|club|league)\b)",
        value,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]

    return re.sub(
        r"\s+",
        " ",
        value,
    ).strip(
        " -–—:|"
    )


def looks_like_generic_non_team(
    text: str,
) -> bool:
    words = normalize(
        text
    ).split()

    if not words:
        return True

    if len(words) > 5:
        return True

    if all(
        word in GENERIC_NON_TEAM_WORDS
        for word in words
    ):
        return True

    if len(words) == 1:
        return (
            words[0]
            in GENERIC_NON_TEAM_WORDS
        )

    return False


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


def extract_explicit_sides(
    title: str,
) -> tuple[str, str] | None:
    text = html.unescape(
        title or ""
    )

    # Scores should be removed only after finding
    # the sides around the score.
    score_match = SCORE_RE.search(
        text
    )

    if score_match:
        left = text[
            :score_match.start()
        ]

        right = text[
            score_match.end():]
        
        # Don't let the competition become the opponent.
        right = re.split(
            r"\s*[|•·]\s*",
            right,
            maxsplit=1,
        )[0]

        right = re.split(
            r"\s+-\s+(?="
            r"(?:premier|ligue|bundesliga|la\s+liga|"
            r"champions|europa|conference|trophee|"
            r"trophée|coupe|club|league)\b)",
            right,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0]

        # For score titles, this is a high-value signal.
        if left.strip() and right.strip():
            return (
                left.strip(),
                right.strip(),
            )

    separators = list(
        EXPLICIT_SEPARATOR_RE.finditer(
            text
        )
    )

    if not separators:
        return None

    # Prefer the last explicit separator:
    # "Résumé de Arsenal / Chelsea - Premier League"
    separator = separators[-1]

    left = text[
        :separator.start()
    ]

    right = text[
        separator.end():]

    right = re.split(
        r"\s*[|•·]\s*",
        right,
        maxsplit=1,
    )[0]

    right = re.split(
        r"\s+-\s+(?="
        r"(?:premier|ligue|bundesliga|la\s+liga|"
        r"champions|europa|conference|trophee|"
        r"trophée|coupe|club|league)\b)",
        right,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]

    if not left.strip() or not right.strip():
        return None

    return (
        left.strip(),
        right.strip(),
    )


def extract_natural_sides(
    title: str,
    teams: list[dict[str, Any]],
) -> tuple[str, str] | None:
    text = html.unescape(
        title or ""
    )

    configured_hits = (
        team_hits_in_text(
            text,
            teams,
        )
    )

    if not configured_hits:
        return None

    # We explicitly ignore "sur" in contexts like
    # "double le Bayern sur le classement".
    for relation in RELATION_RE.finditer(
        text
    ):
        before = text[
            :relation.start()
        ]

        after = text[
            relation.end():]

        before_hits = (
            team_hits_in_text(
                before,
                teams,
            )
        )

        # At least one configured team must be before
        # the relation. This avoids a random context mention.
        if not before_hits:
            continue

        after = re.split(
            r"\s*[|•·]",
            after,
            maxsplit=1,
        )[0]

        after = re.split(
            r"[!?.,]",
            after,
            maxsplit=1,
        )[0]

        after = re.sub(
            r"^\s*(?:un|une|le|la|les|l['’])\s+",
            "",
            after,
            flags=re.IGNORECASE,
        )

        words = after.split()

        kept = []

        for word in words:
            clean_word = word.strip(
                ".,!?;:()[]{}"
            )

            norm_word = normalize(
                clean_word
            )

            if not norm_word:
                continue

            if (
                norm_word
                in GENERIC_NON_TEAM_WORDS
            ):
                break

            if len(kept) >= 4:
                break

            kept.append(
                clean_word
            )

        opponent = " ".join(
            kept
        ).strip()

        if not opponent:
            continue

        if looks_like_generic_non_team(
            opponent
        ):
            continue

        if any(
            contains_term(
                opponent,
                team_alias,
            )
            for configured in teams
            for team_alias in team_aliases(
                configured
            )
        ):
            # If it literally contains a configured team,
            # it's a stronger case.
            return (
                before.strip(),
                opponent,
            )

        # Natural-language article title:
        # "Le Bayern s'impose sur Schalke"
        if (
            any(
                verb in normalize(
                    before
                )
                for verb in MATCH_VERBS
            )
            or len(kept) >= 1
        ):
            return (
                before.strip(),
                opponent,
            )

    return None


def identify_match_sides(
    title: str,
    teams: list[dict[str, Any]],
) -> tuple[
    str,
    str,
    str | None,
] | None:
    explicit = extract_explicit_sides(
        title
    )

    if explicit:
        left, right = explicit

        left_clean = clean_side_text(
            left,
            teams,
        )

        right_clean = clean_side_text(
            right,
            teams,
        )

        left_hits = team_hits_in_text(
            left,
            teams,
        )

        right_hits = team_hits_in_text(
            right,
            teams,
        )

        if not left_hits and not right_hits:
            return None

        # Reject obvious garbage such as:
        # "PSG vs Ligue"
        if (
            looks_like_generic_non_team(
                left_clean
            )
            or looks_like_generic_non_team(
                right_clean
            )
        ):
            return None

        return (
            left_clean,
            right_clean,
            "high",
        )

    natural = extract_natural_sides(
        title,
        teams,
    )

    if natural:
        left, right = natural

        left_clean = clean_side_text(
            left,
            teams,
        )

        right_clean = clean_side_text(
            right,
            teams,
        )

        if (
            looks_like_generic_non_team(
                right_clean
            )
        ):
            return None

        return (
            left_clean,
            right_clean,
            "medium",
        )

    return None


def team_from_side(
    side: str,
    teams: list[dict[str, Any]],
) -> dict[str, Any] | None:
    hits = team_hits_in_text(
        side,
        teams,
    )

    if not hits:
        return None

    return {
        "id": hits[0]["id"],
        "name": hits[0]["name"],
    }


def clean_opponent_name(
    side: str,
    teams: list[dict[str, Any]],
) -> str:
    value = strip_team_names(
        side,
        teams,
    )

    value = re.sub(
        r"\b(?:le|la|les|l['’]|un|une|the)\b",
        " ",
        value,
        flags=re.IGNORECASE,
    )

    value = re.sub(
        r"\b(?:qui|se|s|de|du|des|avec|pour|dans|sur|face|contre)\b",
        " ",
        value,
        flags=re.IGNORECASE,
    )

    words = []

    for word in value.split():
        normalized_word = normalize(
            word
        )

        if (
            normalized_word
            in GENERIC_NON_TEAM_WORDS
        ):
            break

        if len(words) >= 4:
            break

        words.append(
            word.strip(
                ".,!?;:()[]{}"
            )
        )

    value = re.sub(
        r"\s+",
        " ",
        " ".join(words),
    ).strip()

    if not value:
        return ""

    # Preserve common capitalization from source,
    # but avoid shouting.
    if value.isupper():
        value = value.title()

    return value[:80]


# ---------------------------------------------------------------------------
# Match / summary classification
# ---------------------------------------------------------------------------


def find_competition(
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
        if (
            normalize(
                competition
            )
            in normalized
        ):
            return (
                competition
                .replace(
                    "trophee",
                    "trophée",
                )
                .title()
            )

    return None


def summary_keywords_found(
    text: str,
    keywords: list[str],
) -> list[str]:
    return [
        keyword
        for keyword in keywords
        if contains_term(
            text,
            keyword,
        )
    ]


def excluded_keywords_found(
    text: str,
    keywords: list[str],
) -> list[str]:
    return [
        keyword
        for keyword in keywords
        if contains_term(
            text,
            keyword,
        )
    ]


def title_contains_context_pattern(
    title: str,
) -> bool:
    normalized = normalize(
        title
    )

    return any(
        phrase in normalized
        for phrase in (
            normalize(pattern)
            for pattern in CONTEXT_PATTERNS
        )
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

    description = html.unescape(
        video.get(
            "description",
            "",
        )
        or ""
    )

    text = (
        f"{title}\n{description}"
    )

    summary_keywords = (
        app.get(
            "summary_keywords"
        )
        or sorted(
            SUMMARY_FALLBACK
        )
    )

    exclude_keywords = (
        app.get(
            "exclude_keywords"
        )
        or sorted(
            EXCLUDE_FALLBACK
        )
    )

    excluded = (
        excluded_keywords_found(
            title,
            exclude_keywords,
        )
    )

    # We intentionally inspect the title first.
    # A description may contain unrelated channel metadata.
    if excluded:
        return None

    title_team_hits = (
        team_hits_in_text(
            title,
            teams,
        )
    )

    if not title_team_hits:
        return None

    summary_matches = (
        summary_keywords_found(
            title,
            summary_keywords,
        )
    )

    score = extract_score(
        title
    )

    sides = identify_match_sides(
        title,
        teams,
    )

    if not sides:
        return None

    left,
    right,
    confidence = sides

    left_team = team_from_side(
        left,
        teams,
    )

    right_team = team_from_side(
        right,
        teams,
    )

    # One of the two sides MUST be a followed team.
    if not left_team and not right_team:
        return None

    # This rejects "FERRAN TORRES reveals his GOALS with PSG"
    # because there isn't a real two-sided match.
    if (
        not summary_matches
        and not score
        and confidence != "high"
    ):
        return None

    # Additional guard against contextual team mentions.
    if (
        len(title_team_hits) == 1
        and title_contains_context_pattern(
            title
        )
    ):
        # Explicit two-sided match wins.
        if confidence != "high":
            return None

    home_name = (
        left_team["name"]
        if left_team
        else clean_opponent_name(
            left,
            teams,
        )
    )

    away_name = (
        right_team["name"]
        if right_team
        else clean_opponent_name(
            right,
            teams,
        )
    )

    if not home_name or not away_name:
        return None

    if (
        normalize(
            home_name
        )
        == normalize(
            away_name
        )
    ):
        return None

    team_ids = []

    if left_team:
        team_ids.append(
            left_team["id"]
        )

    if right_team:
        team_ids.append(
            right_team["id"]
        )

    team_ids = sorted(
        set(team_ids)
    )

    # There must be at least one followed team.
    if not team_ids:
        return None

    competition = find_competition(
        title
    )

    match_date = None

    date_match = DATE_RE.search(
        title
    )

    if date_match:
        try:
            match_date = datetime(
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
            match_date = None

    # If the title doesn't contain a date,
    # use the YouTube publication timestamp as
    # a fallback for display and retention.
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

    score_text = score

    # Stable opponent fingerprint.
    if left_team:
        opponent = away_name
    else:
        opponent = home_name

    followed_pair = "+".join(
        sorted(team_ids)
    )

    opponent_fingerprint = slug(
        opponent
    )

    pair_ids = sorted(
        [
            left_team["id"]
            if left_team
            else f"opponent:{opponent_fingerprint}",
            right_team["id"]
            if right_team
            else f"opponent:{opponent_fingerprint}",
        ]
    )

    # We use both teams whenever both are followed.
    # Otherwise we use followed team + opponent.
    match_key = "|".join(
        [
            "match",
            "+".join(
                pair_ids
            ),
            slug(
                competition
                or "football"
            ),
            score_text
            or "noscore",
        ]
    )

    # Human friendly title.
    if score_text:
        match_title = (
            f"{home_name} "
            f"{score_text} "
            f"{away_name}"
        )
    else:
        match_title = (
            f"{home_name} vs "
            f"{away_name}"
        )

    return {
        "match_key": match_key,
        "match_title": match_title,
        "home_team": {
            "id": (
                left_team["id"]
                if left_team
                else None
            ),
            "name": home_name,
            "followed": bool(
                left_team
            ),
        },
        "away_team": {
            "id": (
                right_team["id"]
                if right_team
                else None
            ),
            "name": away_name,
            "followed": bool(
                right_team
            ),
        },
        "score": score_text,
        "competition": competition,
        "match_date": (
            match_date
            or published_at
        ),
        "team_ids": team_ids,
        "confidence": confidence,
        "summary_keywords": summary_matches,
        "excluded_keywords": [],
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

    if metadata is None:
        return None

    result = dict(
        video
    )

    result["is_summary"] = True
    result["match_key"] = (
        metadata["match_key"]
    )
    result["match_title"] = (
        metadata["match_title"]
    )
    result["home_team"] = (
        metadata["home_team"]
    )
    result["away_team"] = (
        metadata["away_team"]
    )
    result["score"] = (
        metadata["score"]
    )
    result["competition"] = (
        metadata["competition"]
    )
    result["match_date"] = (
        metadata["match_date"]
    )
    result["teams"] = []

    for side in (
        metadata["home_team"],
        metadata["away_team"],
    ):
        if side.get("id"):
            result["teams"].append(
                {
                    "id": side["id"],
                    "name": side["name"],
                }
            )

    result["match_confidence"] = (
        metadata["confidence"]
    )
    result["summary_keywords"] = (
        metadata["summary_keywords"]
    )
    result["excluded_keywords"] = []

    return result


# ---------------------------------------------------------------------------
# Persistence / grouping
# ---------------------------------------------------------------------------


def load_existing() -> dict[str, Any]:
    if not OUTPUT.exists():
        return empty_output()

    try:
        with OUTPUT.open(
            "r",
            encoding="utf-8",
        ) as fh:
            value = json.load(
                fh
            )

        if not isinstance(
            value,
            dict,
        ):
            return empty_output()

        value.setdefault(
            "videos",
            [],
        )
        value.setdefault(
            "matches",
            [],
        )
        value.setdefault(
            "source_status",
            [],
        )
        value.setdefault(
            "teams",
            [],
        )

        return value

    except (
        OSError,
        json.JSONDecodeError,
    ):
        return empty_output()


def is_recent_enough(
    published_at: str | None,
    cutoff: datetime,
) -> bool:
    if not published_at:
        # Keep undated items for the current run.
        return True

    try:
        dt = datetime.fromisoformat(
            published_at.replace(
                "Z",
                "+00:00",
            )
        )

        if dt.tzinfo is None:
            dt = dt.replace(
                tzinfo=timezone.utc
            )

        return (
            dt.astimezone(
                timezone.utc
            )
            >= cutoff
        )

    except ValueError:
        return True


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

    for match_key, items in groups.items():
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

        team_map: dict[
            str,
            str,
        ] = {}

        for item in items:
            for team in (
                item.get(
                    "teams"
                )
                or []
            ):
                if team.get("id"):
                    team_map[
                        team["id"]
                    ] = team.get(
                        "name",
                        team["id"],
                    )

        sources = {}
        for item in items:
            source_id = item.get(
                "source_id"
            )

            if source_id:
                sources[
                    source_id
                ] = {
                    "id": source_id,
                    "name": item.get(
                        "source_name",
                        source_id,
                    ),
                }

        match_date_values = [
            item.get(
                "match_date"
            )
            or item.get(
                "published_at"
            )
            for item in items
            if (
                item.get(
                    "match_date"
                )
                or item.get(
                    "published_at"
                )
            )
        ]

        published_values = [
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
                "match_key": match_key,
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
                "match_date": (
                    min(
                        match_date_values
                    )
                    if match_date_values
                    else None
                ),
                "published_at": (
                    max(
                        published_values
                    )
                    if published_values
                    else None
                ),
                "team_ids": sorted(
                    team_map.keys()
                ),
                "team_names": [
                    team_map[key]
                    for key in sorted(
                        team_map
                    )
                ],
                "sources_count": len(
                    sources
                ),
                "sources": list(
                    sources.values()
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


def merge_video_records(
    existing_videos: list[
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
    # Important:
    # every time we run the collector, we reclassify old
    # records too. This automatically removes previous false positives.
    by_id: dict[
        str,
        dict[str, Any],
    ] = {}

    for video in existing_videos:
        video_id = video.get(
            "id"
        )

        if not video_id:
            continue

        by_id[
            video_id
        ] = video

    for video in new_videos:
        video_id = video.get(
            "id"
        )

        if not video_id:
            continue

        old = by_id.get(
            video_id,
            {},
        )

        merged = {
            **old,
            **video,
        }

        by_id[
            video_id
        ] = merged

    retained = []

    for video in by_id.values():
        enriched = enrich_video(
            video,
            app,
            teams,
        )

        if enriched:
            retained.append(
                enriched
            )

    return retained


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
        if team.get("id")
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

    all_new_videos = []

    statuses = []

    # We intentionally inspect more than the old 15 videos.
    limit = max(
        60,
        int(
            app.get(
                "max_videos_per_source",
                60,
            )
        ),
    )

    print(
        f"Scanning {len(sources)} sources "
        f"with up to {limit} recent videos/source..."
    )

    for source in sources:
        source_id = source.get(
            "id"
        )

        status = {
            "source_id": source_id,
            "source_name": source.get(
                "name",
                source_id,
            ),
            "ok": False,
            "count": 0,
            "method": None,
            "error": None,
        }

        try:
            videos, method = (
                extract_source_videos(
                    source,
                    limit,
                )
            )

            # Get true publication dates for likely candidates.
            videos = enrich_missing_metadata(
                videos,
                maximum=45,
            )

            status["ok"] = True
            status["count"] = len(
                videos
            )
            status["method"] = method

            all_new_videos.extend(
                videos
            )

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
            )[:800]

        except Exception as exc:
            status["error"] = (
                f"{type(exc).__name__}: "
                f"{exc}"
            )[:800]

        statuses.append(
            status
        )

        print(
            f"[{source.get('name', source_id)}] "
            f"{'OK' if status['ok'] else 'ERROR'} "
            f"({status['count']} videos)"
        )

        time.sleep(0.4)

    # Reclassify both old and newly downloaded records.
    retained = merge_video_records(
        existing.get(
            "videos",
            [],
        ),
        all_new_videos,
        app,
        teams,
    )

    # Keep only the configured retention period.
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

    filtered = [
        video
        for video in retained
        if is_recent_enough(
            video.get(
                "published_at"
            )
            or video.get(
                "match_date"
            ),
            cutoff,
        )
    ]

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
                "id": team["id"],
                "name": team["name"],
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

    with OUTPUT.open(
        "w",
        encoding="utf-8",
    ) as fh:
        json.dump(
            output,
            fh,
            ensure_ascii=False,
            indent=2,
        )

        fh.write(
            "\n"
        )

    print()
    print(
        "========================================"
    )
    print(
        "Football Hub collection complete"
    )
    print(
        "========================================"
    )
    print(
        f"Videos retained : {len(filtered)}"
    )
    print(
        f"Matches grouped : {len(matches)}"
    )

    for match in matches[:15]:
        print(
            "- "
            f"{match.get('title', 'Résumé')}"
            f" | sources={match.get('sources_count', 0)}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
