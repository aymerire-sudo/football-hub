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

ATOM = "http://www.w3.org/2005/Atom"
YT = "http://www.youtube.com/xml/schemas/2015"
NS = {"atom": ATOM, "yt": YT}

USER_AGENT = "FootballHub/3.0 (+https://github.com/)"

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
}

COMPETITIONS = (
    "champions league",
    "uefa champions league",
    "europa league",
    "conference league",
    "premier league",
    "la liga",
    "liga",
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
    "coupe du monde",
    "world cup",
    "euro",
    "euros",
    "club world cup",
    "mondial des clubs",
)

NOISE_WORDS = {
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
    "héroique",
    "heroique",
    "héroïque",
    "brillant",
    "brillante",
    "énorme",
    "enorme",
    "solide",
    "incroyable",
    "impressionnant",
    "impressionnante",
    "dominant",
    "domine",
    "humilie",
    "écrase",
    "ecrase",
    "frappe",
    "tombe",
    "perd",
    "gagne",
    "bat",
    "s",
    "impose",
    "incline",
    "s'impose",
    "s'incline",
    "manita",
    "folle",
    "chaud",
    "heroique",
}

SCORE_RE = re.compile(r"(?<!\d)(\d{1,2})\s*[-–—:]\s*(\d{1,2})(?!\d)")
DATE_RE = re.compile(r"\b(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})\b")

PAIR_RE = re.compile(
    r"\s+(?:vs\.?|v\.?|contre|/|@)\s+",
    re.IGNORECASE,
)

HYPHEN_PAIR_RE = re.compile(r"\s+[-–—]\s+")

NATURAL_RELATION_RE = re.compile(
    r"\b(?:sur|contre|face\s+a|face\s+à)\b",
    re.IGNORECASE,
)


def load_json(path: Path, fallback: Path | None = None) -> dict[str, Any]:
    target = path if path.exists() else fallback

    if target is None or not target.exists():
        raise FileNotFoundError(f"Config not found: {path}")

    with target.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def normalize(value: str) -> str:
    value = html.unescape(value or "")
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.lower().replace("&", " and ")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", normalize(value)).strip("-")


def contains_term(text: str, term: str) -> bool:
    t = normalize(term)
    n = normalize(text)

    if not t:
        return False

    return (
        re.search(
            r"(?<![a-z0-9])" + re.escape(t) + r"(?![a-z0-9])",
            n,
        )
        is not None
    )


def parse_date(value: str | int | float | None) -> str | None:
    if value is None or value == "":
        return None

    value = str(value).strip()

    try:
        if re.fullmatch(r"\d{8}", value):
            dt = datetime.strptime(value, "%Y%m%d").replace(
                tzinfo=timezone.utc
            )
            return dt.isoformat()

        if re.fullmatch(r"\d+(?:\.\d+)?", value):
            timestamp = float(value)

            if timestamp > 1_000_000_000:
                return datetime.fromtimestamp(
                    timestamp,
                    timezone.utc,
                ).isoformat()

        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        return dt.astimezone(timezone.utc).isoformat()

    except ValueError:
        return None


def fetch(url: str, timeout: int = 30) -> bytes:
    req = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/atom+xml,application/xml,text/xml,*/*",
        },
    )

    with urlopen(req, timeout=timeout) as response:
        return response.read()


def get_text(parent: ET.Element, path: str) -> str:
    node = parent.find(path, NS)

    if node is not None and node.text:
        return node.text.strip()

    return ""


def get_attr(
    parent: ET.Element,
    path: str,
    attr: str,
) -> str:
    node = parent.find(path, NS)

    if node is not None:
        return (node.attrib.get(attr) or "").strip()

    return ""


def resolve_channel_id(source: dict[str, Any]) -> str:
    direct = (source.get("youtube_channel_id") or "").strip()

    if direct.startswith("UC"):
        return direct

    url = (source.get("youtube_url") or "").strip()

    if not url:
        return ""

    match = re.search(
        r"/channel/(UC[0-9A-Za-z_-]{20,})",
        url,
    )

    if match:
        return match.group(1)

    try:
        body = fetch(url, timeout=20).decode(
            "utf-8",
            errors="ignore",
        )

        patterns = [
            r'"channelId":"(UC[0-9A-Za-z_-]{20,})"',
            r'"externalId":"(UC[0-9A-Za-z_-]{20,})"',
            r'<meta[^>]+itemprop=["\']channelId["\'][^>]+content=["\'](UC[0-9A-Za-z_-]{20,})',
        ]

        for pattern in patterns:
            found = re.search(pattern, body, re.I)

            if found:
                return found.group(1)

    except Exception:
        pass

    return ""


def parse_feed(
    xml_bytes: bytes,
    source: dict[str, Any],
    limit: int,
    channel_id: str = "",
) -> list[dict[str, Any]]:
    root = ET.fromstring(xml_bytes)

    videos: list[dict[str, Any]] = []

    for entry in root.findall("atom:entry", NS)[:limit]:
        video_id = get_text(entry, "yt:videoId")
        link_id = get_text(entry, "atom:id")

        if not video_id and link_id.startswith("yt:video:"):
            video_id = link_id.rsplit(":", 1)[-1]

        if not video_id:
            continue

        title = html.unescape(
            get_text(entry, "atom:title")
        )

        published = parse_date(
            get_text(entry, "atom:published")
        )

        updated = parse_date(
            get_text(entry, "atom:updated")
        )

        url = (
            get_attr(
                entry,
                "atom:link[@rel='alternate']",
                "href",
            )
            or f"https://www.youtube.com/watch?v={video_id}"
        )

        author = (
            get_text(entry, "atom:author/atom:name")
            or source.get("name", "YouTube")
        )

        videos.append(
            {
                "id": video_id,
                "title": title,
                "url": url,
                "published_at": published,
                "updated_at": updated,
                "thumbnail": (
                    f"https://i.ytimg.com/vi/"
                    f"{video_id}/hqdefault.jpg"
                ),
                "source_id": source["id"],
                "source_name": source.get(
                    "name",
                    author,
                ),
                "source_channel_id": channel_id,
                "description": "",
            }
        )

    return videos


def source_videos_url(source: dict[str, Any]) -> str:
    url = (source.get("youtube_url") or "").strip()

    if not url:
        return ""

    clean = url.rstrip("/")

    if not clean.endswith("/videos"):
        clean += "/videos"

    return clean


def parse_ytdlp_json_lines(
    stdout: str,
    source: dict[str, Any],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    for line in stdout.splitlines():
        line = line.strip()

        if not line or not line.startswith("{"):
            continue

        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue

        vid = item.get("id")

        if not vid:
            continue

        timestamp = (
            item.get("release_timestamp")
            or item.get("timestamp")
        )

        published = parse_date(
            timestamp
            if timestamp is not None
            else item.get("upload_date")
        )

        out.append(
            {
                "id": vid,
                "title": html.unescape(
                    item.get("title") or ""
                ),
                "url": (
                    item.get("webpage_url")
                    or item.get("original_url")
                    or f"https://www.youtube.com/watch?v={vid}"
                ),
                "published_at": published,
                "updated_at": None,
                "thumbnail": (
                    item.get("thumbnail")
                    or f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"
                ),
                "source_id": source["id"],
                "source_name": source.get(
                    "name",
                    "YouTube",
                ),
                "source_channel_id": (
                    item.get("channel_id") or ""
                ),
                "description": item.get(
                    "description"
                )
                or "",
                "duration": item.get("duration"),
            }
        )

    return out


def fetch_with_ytdlp(
    source: dict[str, Any],
    limit: int,
) -> list[dict[str, Any]]:
    url = source_videos_url(source)

    if not url:
        return []

    cmd = [
        "yt-dlp",
        "--dump-json",
        "--skip-download",
        "--ignore-errors",
        "--no-warnings",
        "--flat-playlist",
        "--playlist-items",
        f"1:{limit}",
        url,
    ]

    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=120,
    )

    flat = parse_ytdlp_json_lines(
        proc.stdout,
        source,
    )

    # Fast first pass: only fetch full metadata for videos
    # which have a realistic chance of being a match.
    candidates = [
        item
        for item in flat
        if looks_like_possible_match_title(
            item.get("title", "")
        )
    ]

    details_by_id: dict[str, dict[str, Any]] = {}

    for item in candidates[:40]:
        vid = item["id"]

        detail_cmd = [
            "yt-dlp",
            "--dump-single-json",
            "--skip-download",
            "--no-warnings",
            "--no-playlist",
            f"https://www.youtube.com/watch?v={vid}",
        ]

        try:
            detail = subprocess.run(
                detail_cmd,
                capture_output=True,
                text=True,
                timeout=35,
            )

            if (
                detail.returncode == 0
                and detail.stdout.strip()
            ):
                payload = json.loads(
                    detail.stdout
                )

                timestamp = (
                    payload.get("release_timestamp")
                    or payload.get("timestamp")
                )

                published = parse_date(
                    timestamp
                    if timestamp is not None
                    else payload.get("upload_date")
                )

                details_by_id[vid] = {
                    "published_at": published,
                    "updated_at": None,
                    "description": payload.get(
                        "description"
                    )
                    or "",
                    "thumbnail": (
                        payload.get("thumbnail")
                        or item.get("thumbnail")
                    ),
                    "url": (
                        payload.get("webpage_url")
                        or item.get("url")
                    ),
                    "channel_id": (
                        payload.get("channel_id")
                        or item.get(
                            "source_channel_id",
                            "",
                        )
                    ),
                    "duration": payload.get(
                        "duration"
                    ),
                }

        except (
            subprocess.TimeoutExpired,
            json.JSONDecodeError,
        ):
            continue

    out: list[dict[str, Any]] = []

    for item in flat:
        detail = details_by_id.get(
            item["id"],
            {},
        )

        merged = {
            **item,
            **detail,
        }

        merged["source_id"] = source["id"]
        merged["source_name"] = source.get(
            "name",
            "YouTube",
        )
        merged["source_channel_id"] = (
            merged.get("channel_id")
            or merged.get(
                "source_channel_id",
                "",
            )
        )

        merged.pop("channel_id", None)

        out.append(merged)

    if out:
        return out

    # Full fallback if flat playlist extraction failed.
    full_cmd = [
        "yt-dlp",
        "--dump-json",
        "--skip-download",
        "--ignore-errors",
        "--no-warnings",
        "--playlist-items",
        f"1:{limit}",
        url,
    ]

    proc = subprocess.run(
        full_cmd,
        capture_output=True,
        text=True,
        timeout=240,
    )

    return parse_ytdlp_json_lines(
        proc.stdout,
        source,
    )


def team_patterns(
    team: dict[str, Any],
) -> list[str]:
    return [
        x
        for x in [
            team.get("name", ""),
            *(team.get("aliases") or []),
        ]
        if x
    ]


def find_team_mentions(
    text: str,
    team: dict[str, Any],
) -> list[tuple[int, int, str]]:
    normalized = normalize(text)
    result: list[tuple[int, int, str]] = []

    for alias in team_patterns(team):
        term = normalize(alias)

        if not term:
            continue

        for match in re.finditer(
            r"(?<![a-z0-9])"
            + re.escape(term)
            + r"(?![a-z0-9])",
            normalized,
        ):
            result.append(
                (
                    match.start(),
                    match.end(),
                    alias,
                )
            )

    return result


def get_configured_hits(
    text: str,
    teams: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []

    for team in teams:
        if find_team_mentions(text, team):
            hits.append(
                {
                    "id": team["id"],
                    "name": team["name"],
                }
            )

    return hits


def score_from_title(
    title: str,
) -> tuple[int, int, str] | None:
    match = SCORE_RE.search(
        html.unescape(title or "")
    )

    if not match:
        return None

    home = int(match.group(1))
    away = int(match.group(2))

    return home, away, f"{home}-{away}"


def clean_side(
    text: str,
    teams: list[dict[str, Any]],
) -> str:
    value = html.unescape(text or "")

    value = re.sub(
        r"^\s*(?:(?:le|la|les)\s+)?"
        r"résumé(?:\s+de)?\s*[:|-]?\s*",
        "",
        value,
        flags=re.I,
    )

    value = re.sub(
        r"^\s*(?:match\s+)?highlights?"
        r"\s*[-:–—|]+\s*",
        "",
        value,
        flags=re.I,
    )

    value = re.sub(
        r"^\s*(?:summary|recap)"
        r"\s*[-:–—|]+\s*",
        "",
        value,
        flags=re.I,
    )

    value = SCORE_RE.sub(" ", value)

    value = re.sub(
        r"\([^)]*\)",
        " ",
        value,
    )

    value = re.sub(
        r"\[.*?\]",
        " ",
        value,
    )

    value = re.split(
        r"\s*[|•·]\s*",
        value,
        maxsplit=1,
    )[0]

    value = re.split(
        r"\s+[-–—:]\s+"
        r"(?=(?:premier|ligue|bundesliga|la\s+liga|"
        r"champions|europa|conference|troph|coupe|club|"
        r"highlights?|résumé|resume)\b)",
        value,
        maxsplit=1,
        flags=re.I,
    )[0]

    normalized = normalize(value)

    normalized = re.sub(
        r"^(?:le|la|les|l|un|une|the|fc)\s+",
        "",
        normalized,
    )

    return re.sub(
        r"\s+",
        " ",
        normalized,
    ).strip()


def split_explicit_match(
    title: str,
) -> tuple[str, str] | None:
    text = html.unescape(title or "")

    # Score is our strongest evidence:
    # "Arsenal 2-1 Chelsea".
    score_match = SCORE_RE.search(text)

    if score_match:
        left = text[:score_match.start()]
        right = text[score_match.end():]

        right = re.split(
            r"\s*[|•·]\s*",
            right,
            maxsplit=1,
        )[0]

        right = re.split(
            r"\s+-\s+"
            r"(?=(?:Premier|Ligue|Bundesliga|La Liga|"
            r"Champions|Europa|Troph|Coupe|Club)\b)",
            right,
            maxsplit=1,
            flags=re.I,
        )[0]

        left = re.split(
            r"\s*[|•·]\s*",
            left,
            maxsplit=1,
        )[-1]

        if left.strip() and right.strip():
            return left.strip(), right.strip()

    # Explicit "vs", "/", "contre", etc.
    for pattern in (PAIR_RE, HYPHEN_PAIR_RE):
        matches = list(pattern.finditer(text))

        for match in reversed(matches):
            left = text[:match.start()]
            right = text[match.end():]

            if (
                len(normalize(left)) < 2
                or len(normalize(right)) < 2
            ):
                continue

            right = re.split(
                r"\s*[|•·]\s*",
                right,
                maxsplit=1,
            )[0]

            right = re.split(
                r"\s+-\s+"
                r"(?=(?:Premier|Ligue|Bundesliga|La Liga|"
                r"Champions|Europa|Troph|Coupe|Club)\b)",
                right,
                maxsplit=1,
                flags=re.I,
            )[0]

            return left.strip(), right.strip()

    return None


def extract_opponent_after_relation(
    text: str,
    relation_match: re.Match[str],
) -> str:
    right = text[relation_match.end():]

    right = re.split(
        r"\s*[|•·]\s*",
        right,
        maxsplit=1,
    )[0]

    right = re.split(
        r"[!?.,]",
        right,
        maxsplit=1,
    )[0]

    right = re.sub(
        r"^\s*(?:un|une|le|la|les|l['’])\s+",
        "",
        right,
        flags=re.I,
    )

    words = re.split(
        r"\s+",
        right.strip(),
    )

    kept: list[str] = []

    for word in words:
        n = normalize(word)

        if not n:
            continue

        if n in NOISE_WORDS:
            break

        if len(kept) >= 4:
            break

        kept.append(word)

    return " ".join(kept).strip()


def extract_match_sides(
    title: str,
    teams: list[dict[str, Any]],
) -> tuple[str, str, dict[str, Any]] | None:
    explicit = split_explicit_match(title)

    score = score_from_title(title)

    if explicit:
        left, right = explicit

        left_hits = get_configured_hits(
            left,
            teams,
        )

        right_hits = get_configured_hits(
            right,
            teams,
        )

        if left_hits or right_hits:
            return (
                left,
                right,
                {
                    "score": (
                        score[2]
                        if score
                        else None
                    ),
                    "confidence": "high",
                },
            )

    text = html.unescape(title or "")

    for relation in NATURAL_RELATION_RE.finditer(text):
        before = text[:relation.start()]
        after = extract_opponent_after_relation(
            text,
            relation,
        )

        before_hits = get_configured_hits(
            before,
            teams,
        )

        after_hits = get_configured_hits(
            after,
            teams,
        )

        # "Le Bayern ... sur Schalke".
        if before_hits and after and not after_hits:
            return (
                before,
                after,
                {
                    "score": (
                        score[2]
                        if score
                        else None
                    ),
                    "confidence": "high",
                },
            )

        # Reverse or less common phrasing.
        if after_hits and before:
            return (
                before,
                after,
                {
                    "score": (
                        score[2]
                        if score
                        else None
                    ),
                    "confidence": "medium",
                },
            )

    return None


def team_from_side(
    side: str,
    teams: list[dict[str, Any]],
) -> dict[str, Any] | None:
    hits = get_configured_hits(
        side,
        teams,
    )

    if hits:
        return hits[0]

    return None


def opponent_label(
    side: str,
    teams: list[dict[str, Any]],
) -> str:
    value = html.unescape(side or "")

    value = re.sub(
        r"^\s*(?:(?:le|la|les)\s+)?"
        r"résumé(?:\s+de)?\s*[:|-]?\s*",
        "",
        value,
        flags=re.I,
    )

    value = re.sub(
        r"^\s*(?:match\s+)?highlights?"
        r"\s*[-:–—|]+\s*",
        "",
        value,
        flags=re.I,
    )

    value = re.split(
        r"\s*[|•·]\s*",
        value,
        maxsplit=1,
    )[0]

    value = re.split(
        r"\s+[-–—:]\s+"
        r"(?=(?:premier|ligue|bundesliga|la\s+liga|"
        r"champions|europa|conference|troph|coupe|club)\b)",
        value,
        maxsplit=1,
        flags=re.I,
    )[0]

    for team in teams:
        for alias in team_patterns(team):
            value = re.sub(
                r"(?<![A-Za-z0-9])"
                + re.escape(alias)
                + r"(?![A-Za-z0-9])",
                " ",
                value,
                flags=re.I,
            )

    words = re.split(
        r"\s+",
        value.strip(),
    )

    kept: list[str] = []

    for word in words:
        if normalize(word) in NOISE_WORDS:
            break

        if len(kept) >= 4:
            break

        if word:
            kept.append(
                word.strip(
                    ".,!?;:()[]{}"
                )
            )

    value = re.sub(
        r"\s+",
        " ",
        " ".join(kept),
    ).strip(" -–—:|")

    if value.isupper():
        value = value.title()

    return value[:80]


def competition_from_title(
    title: str,
) -> str | None:
    for competition in COMPETITIONS:
        if contains_term(
            title,
            competition,
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


def title_has_excluded_keyword(
    title: str,
    exclude_keywords: list[str],
) -> list[str]:
    return [
        keyword
        for keyword in exclude_keywords
        if contains_term(
            title,
            keyword,
        )
    ]


def looks_like_possible_match_title(
    title: str,
) -> bool:
    norm = normalize(title)

    return bool(
        SCORE_RE.search(title)
        or PAIR_RE.search(title)
        or HYPHEN_PAIR_RE.search(title)
        or NATURAL_RELATION_RE.search(title)
        or any(
            word in norm
            for word in (
                "highlights",
                "resume",
                "resumé",
                "recap",
                "goals",
                "buts",
            )
        )
    )


def analyze_video(
    video: dict[str, Any],
    app: dict[str, Any],
    teams: list[dict[str, Any]],
) -> tuple[bool, dict[str, Any]]:
    title = html.unescape(
        video.get("title") or ""
    )

    summary_keywords = (
        app.get("summary_keywords")
        or sorted(SUMMARY_FALLBACK)
    )

    exclude_keywords = (
        app.get("exclude_keywords")
        or sorted(EXCLUDE_FALLBACK)
    )

    excluded = title_has_excluded_keyword(
        title,
        exclude_keywords,
    )

    if excluded:
        return False, {
            "reason": "excluded keyword",
            "excluded_keywords": excluded,
        }

    configured_hits = get_configured_hits(
        title,
        teams,
    )

    sides = extract_match_sides(
        title,
        teams,
    )

    if not sides or not configured_hits:
        return False, {
            "reason": "no two-sided match evidence",
            "excluded_keywords": [],
        }

    left, right, side_meta = sides

    left_team = team_from_side(
        left,
        teams,
    )

    right_team = team_from_side(
        right,
        teams,
    )

    if not left_team and not right_team:
        return False, {
            "reason": "configured team not in match side",
            "excluded_keywords": [],
        }

    title_summary = any(
        contains_term(
            title,
            keyword,
        )
        for keyword in summary_keywords
    )

    score = score_from_title(title)

    relation_evidence = (
        side_meta.get("confidence")
        in {"high", "medium"}
    )

    if not (
        title_summary
        or score
        or relation_evidence
    ):
        return False, {
            "reason": "not enough summary evidence",
            "excluded_keywords": [],
        }

    home = {
        "id": (
            left_team["id"]
            if left_team
            else None
        ),
        "name": (
            left_team["name"]
            if left_team
            else opponent_label(
                left,
                teams,
            )
        ),
        "followed": bool(left_team),
    }

    away = {
        "id": (
            right_team["id"]
            if right_team
            else None
        ),
        "name": (
            right_team["name"]
            if right_team
            else opponent_label(
                right,
                teams,
            )
        ),
        "followed": bool(right_team),
    }

    if not home["name"] or not away["name"]:
        return False, {
            "reason": "could not identify both sides",
            "excluded_keywords": [],
        }

    match_date = None

    date_match = DATE_RE.search(title)

    if date_match:
        try:
            match_date = datetime(
                int(date_match.group(1)),
                int(date_match.group(2)),
                int(date_match.group(3)),
                tzinfo=timezone.utc,
            ).isoformat()
        except ValueError:
            match_date = None

    score_text = (
        score[2]
        if score
        else None
    )

    competition = competition_from_title(
        title
    )

    title_for_display = (
        f"{home['name']} vs {away['name']}"
    )

    if score_text:
        title_for_display = (
            f"{home['name']} "
            f"{score_text} "
            f"{away['name']}"
        )

    followed_ids = [
        team["id"]
        for team in (
            left_team,
            right_team,
        )
        if team
    ]

    if not followed_ids:
        return False, {
            "reason": "no followed team",
            "excluded_keywords": [],
        }

    opponent = ""

    if left_team and not right_team:
        opponent = away["name"]

    elif right_team and not left_team:
        opponent = home["name"]

    canonical_pair = "|".join(
        sorted(
            followed_ids
            + (
                [slug(opponent)]
                if opponent
                else []
            )
        )
    )

    key_parts = [
        canonical_pair or "unknown",
        slug(competition or "football"),
        score_text or "noscore",
    ]

    match_key = "|".join(key_parts)

    if left_team and right_team:
        match_key = "|".join(
            [
                "teams",
                "+".join(
                    sorted(
                        [
                            left_team["id"],
                            right_team["id"],
                        ]
                    )
                ),
                slug(
                    competition
                    or "football"
                ),
                score_text
                or "noscore",
            ]
        )

    meta = {
        "match_key": match_key,
        "match_title": title_for_display,
        "home_team": home,
        "away_team": away,
        "score": score_text,
        "competition": competition,
        "match_date": match_date,
        "team_ids": followed_ids,
        "confidence": side_meta.get(
            "confidence",
            "medium",
        ),
        "reason": "two-sided match detected",
        "summary_keywords": [
            keyword
            for keyword in summary_keywords
            if contains_term(
                title,
                keyword,
            )
        ],
        "excluded_keywords": [],
    }

    return True, meta


def enrich_video(
    video: dict[str, Any],
    app: dict[str, Any],
    teams: list[dict[str, Any]],
) -> dict[str, Any] | None:
    ok, meta = analyze_video(
        video,
        app,
        teams,
    )

    if not ok:
        return None

    result = dict(video)

    result["is_summary"] = True
    result["match_key"] = meta[
        "match_key"
    ]
    result["match_title"] = meta[
        "match_title"
    ]
    result["home_team"] = meta[
        "home_team"
    ]
    result["away_team"] = meta[
        "away_team"
    ]
    result["score"] = meta[
        "score"
    ]
    result["competition"] = meta[
        "competition"
    ]
    result["match_date"] = meta[
        "match_date"
    ]

    result["teams"] = [
        {
            "id": meta[side]["id"],
            "name": meta[side]["name"],
        }
        for side in (
            "home_team",
            "away_team",
        )
        if meta[side]["id"] is not None
    ]

    result["match_confidence"] = meta[
        "confidence"
    ]

    result["match_reason"] = meta[
        "reason"
    ]

    result["summary_keywords"] = meta[
        "summary_keywords"
    ]

    result["excluded_keywords"] = []

    if not result.get("published_at"):
        result["published_at"] = (
            result.get("updated_at")
        )

    return result


def extract_source_videos(
    source: dict[str, Any],
    limit: int,
) -> tuple[list[dict[str, Any]], str]:
    ytdlp_error = ""

    try:
        videos = fetch_with_ytdlp(
            source,
            limit,
        )

        if videos:
            return videos, "yt-dlp"

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
        f"?channel_id={channel_id}"
    )

    xml = fetch(feed_url)

    return (
        parse_feed(
            xml,
            source,
            min(limit, 15),
            channel_id,
        ),
        "atom",
    )


def empty_output() -> dict[str, Any]:
    return {
        "generated_at": None,
        "source_status": [],
        "videos": [],
        "matches": [],
    }


def load_existing() -> dict[str, Any]:
    if not OUTPUT.exists():
        return empty_output()

    try:
        with OUTPUT.open(
            "r",
            encoding="utf-8",
        ) as fh:
            value = json.load(fh)

        value.setdefault(
            "videos",
            [],
        )

        value.setdefault(
            "matches",
            [],
        )

        return value

    except (
        OSError,
        json.JSONDecodeError,
    ):
        return empty_output()


def build_matches(
    videos: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    groups: dict[
        str,
        list[dict[str, Any]],
    ] = {}

    for video in videos:
        key = (
            video.get("match_key")
            or video.get("id")
        )

        groups.setdefault(
            key,
            [],
        ).append(video)

    matches: list[dict[str, Any]] = []

    for key, items in groups.items():
        items.sort(
            key=lambda video: (
                video.get("published_at")
                or ""
            ),
            reverse=True,
        )

        first = items[0]

        team_ids = sorted(
            {
                team["id"]
                for video in items
                for team in (
                    video.get("teams")
                    or []
                )
                if team.get("id")
            }
        )

        team_names = []

        seen_names = set()

        for video in items:
            for team in (
                video.get("teams")
                or []
            ):
                team_id = team.get(
                    "id"
                )

                team_name = team.get(
                    "name"
                )

                if (
                    team_name
                    and team_id not in seen_names
                ):
                    team_names.append(
                        team_name
                    )
                    seen_names.add(
                        team_id
                    )

        matches.append(
            {
                "match_key": key,
                "title": (
                    first.get(
                        "match_title"
                    )
                    or first.get("title")
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
                    first.get(
                        "match_date"
                    )
                    or first.get(
                        "published_at"
                    )
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
                "team_ids": team_ids,
                "team_names": team_names,
                "sources_count": len(
                    {
                        video.get(
                            "source_id"
                        )
                        for video in items
                    }
                ),
                "videos": items,
            }
        )

    matches.sort(
        key=lambda match: (
            match.get("match_date")
            or match.get("published_at")
            or ""
        ),
        reverse=True,
    )

    return matches


def main() -> int:
    cfg = load_json(
        CONFIG,
        EXAMPLE,
    )

    app = cfg.get(
        "app",
        {},
    )

    teams = cfg.get(
        "teams",
        [],
    )

    sources = [
        source
        for source in cfg.get(
            "sources",
            [],
        )
        if source.get(
            "enabled",
            True,
        )
    ]

    existing = load_existing()

    # Reclassify old records with the new engine.
    # This automatically removes old false positives.
    by_video_id: dict[
        str,
        dict[str, Any],
    ] = {}

    for old in existing.get(
        "videos",
        [],
    ):
        enriched = enrich_video(
            old,
            app,
            teams,
        )

        if enriched and enriched.get(
            "id"
        ):
            by_video_id[
                enriched["id"]
            ] = enriched

    statuses: list[
        dict[str, Any]
    ] = []

    # Always scan a decent history even if config.json
    # still contains the old value of 15.
    limit = max(
        60,
        int(
            app.get(
                "max_videos_per_source",
                60,
            )
        ),
    )

    for source in sources:
        source_id = source.get(
            "id"
        )

        result = {
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
            parsed, method = (
                extract_source_videos(
                    source,
                    limit,
                )
            )

            result["method"] = method
            result["count"] = len(parsed)

            for video in parsed:
                enriched = enrich_video(
                    video,
                    app,
                    teams,
                )

                if enriched and enriched.get(
                    "id"
                ):
                    enriched["fetched_at"] = (
                        datetime.now(
                            timezone.utc
                        ).isoformat()
                    )

                    by_video_id[
                        enriched["id"]
                    ] = enriched

            result["ok"] = True

        except (
            HTTPError,
            URLError,
            ET.ParseError,
            TimeoutError,
            ValueError,
            RuntimeError,
            json.JSONDecodeError,
        ) as exc:
            result["error"] = str(exc)[
                :500
            ]

        except Exception as exc:
            result["error"] = (
                "Unexpected error: "
                f"{type(exc).__name__}: "
                f"{exc}"
            )[:500]

        statuses.append(result)

        time.sleep(0.5)

    cutoff = (
        datetime.now(timezone.utc)
        - timedelta(
            days=int(
                app.get(
                    "keep_days",
                    45,
                )
            )
        )
    )

    retained: list[
        dict[str, Any]
    ] = []

    for video in by_video_id.values():
        pub = video.get(
            "published_at"
        )

        keep = True

        if pub:
            try:
                keep = (
                    datetime.fromisoformat(
                        pub.replace(
                            "Z",
                            "+00:00",
                        )
                    )
                    >= cutoff
                )
            except ValueError:
                keep = True

        if keep:
            retained.append(video)

    retained.sort(
        key=lambda video: (
            video.get(
                "published_at"
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
                "id": team.get(
                    "id"
                ),
                "name": team.get(
                    "name"
                ),
            }
            for team in teams
            if team.get("id")
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
        fh.write("\n")

    print(
        f"Stored {len(retained)} videos "
        f"grouped into {len(matches)} matches."
    )

    for item in statuses:
        method = (
            f" [{item['method']}]"
            if item.get("method")
            else ""
        )

        if item["ok"]:
            print(
                f"- {item['source_name']}"
                f"{method}: "
                f"{item['count']} videos scanned"
            )
        else:
            print(
                f"- {item['source_name']}: "
                f"ERROR: {item['error']}"
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
