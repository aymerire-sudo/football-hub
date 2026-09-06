#!/usr/bin/env python3
from __future__ import annotations

import html
import json
import re
import subprocess
import sys
import time
import unicodedata
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config.json"
EXAMPLE = ROOT / "config.example.json"
OUTPUT = ROOT / "data" / "videos.json"
ATOM = "http://www.w3.org/2005/Atom"
YT = "http://www.youtube.com/xml/schemas/2015"
NS = {"atom": ATOM, "yt": YT}
USER_AGENT = "FootballHub/2.0 (+https://github.com/)"

SUMMARY_FALLBACK = {
    "highlights", "match highlights", "extended highlights", "full highlights",
    "match recap", "recap", "résumé", "resume", "résumé du match", "buts",
    "but", "goals", "all goals", "goals & highlights", "match goals",
    "all goals & highlights", "meilleurs moments", "résumé et buts"
}
EXCLUDE_FALLBACK = {
    "reaction", "reactions", "preview", "predictions", "prediction",
    "press conference", "press-conference", "interview", "interviews",
    "training", "behind the scenes", "transfer", "transfers", "news",
    "analysis", "tactical analysis", "débrief", "debrief", "avant-match",
    "avant match", "conférence de presse", "podcast", "émission", "emission",
    "mercato", "inside"
}

SCORE_RE = re.compile(r"(?<!\d)(\d{1,2})\s*[-–—:]\s*(\d{1,2})(?!\d)")
PAIR_SEP_RE = re.compile(r"\s+(?:vs\.?|v\.?|contre|/|@)\s+", re.I)
MENTION_PATTERNS = [
    r"\bdouble\s+(?:le|la|l['’])\b",
    r"\bdevance(?:nt)?\s+(?:le|la|l['’])\b",
    r"\bdépasse(?:nt)?\s+(?:le|la|l['’])\b",
    r"\bdevant\s+(?:le|la|l['’])\b",
    r"\bprend(?:re)?\s+la\s+tête\b",
    r"\ben\s+tête\b",
    r"\bclassement\b",
    r"\bpoints\b",
    r"\bcourse\s+au\s+titre\b",
    r"\bcourse\s+à\s+la\s+ligue\b",
]


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


def contains_term(text: str, term: str) -> bool:
    t = normalize(term)
    if not t:
        return False
    return re.search(r"(?<![a-z0-9])" + re.escape(t) + r"(?![a-z0-9])", normalize(text)) is not None


def parse_date(value: str | None) -> str | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc).isoformat()
    except ValueError:
        return None


def fetch(url: str, timeout: int = 20) -> bytes:
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
    return (node.text or "").strip() if node is not None and node.text else ""


def get_attr(parent: ET.Element, path: str, attr: str) -> str:
    node = parent.find(path, NS)
    return (node.attrib.get(attr) or "").strip() if node is not None else ""


def resolve_channel_id(source: dict[str, Any]) -> str:
    direct = (source.get("youtube_channel_id") or "").strip()
    if direct and direct.startswith("UC"):
        return direct

    url = (source.get("youtube_url") or "").strip()
    if not url:
        return ""

    match = re.search(r"/channel/(UC[0-9A-Za-z_-]{20,})", url)
    if match:
        return match.group(1)

    try:
        body = fetch(url, timeout=20).decode("utf-8", errors="ignore")
        patterns = [
            r'"channelId":"(UC[0-9A-Za-z_-]{20,})"',
            r'"externalId":"(UC[0-9A-Za-z_-]{20,})"',
            r'<meta[^>]+itemprop=["\']channelId["\'][^>]+content=["\'](UC[0-9A-Za-z_-]{20,})',
            r'<link[^>]+itemprop=["\']url["\'][^>]+href=["\']https?://www\.youtube\.com/channel/(UC[0-9A-Za-z_-]{20,})',
        ]
        for pattern in patterns:
            found = re.search(pattern, body, re.I)
            if found:
                return found.group(1)
    except Exception:
        pass
    return ""


def parse_feed(xml_bytes: bytes, source: dict[str, Any], limit: int, channel_id: str = "") -> list[dict[str, Any]]:
    root = ET.fromstring(xml_bytes)
    videos: list[dict[str, Any]] = []
    for entry in root.findall("atom:entry", NS)[:limit]:
        video_id = get_text(entry, "yt:videoId")
        link_id = get_text(entry, "atom:id")
        if not video_id and link_id.startswith("yt:video:"):
            video_id = link_id.rsplit(":", 1)[-1]
        if not video_id:
            continue

        title = html.unescape(get_text(entry, "atom:title"))
        published = parse_date(get_text(entry, "atom:published"))
        updated = parse_date(get_text(entry, "atom:updated"))
        url = get_attr(entry, "atom:link[@rel='alternate']", "href") or f"https://www.youtube.com/watch?v={video_id}"
        author = get_text(entry, "atom:author/atom:name") or source.get("name", "YouTube")

        videos.append(
            {
                "id": video_id,
                "title": title,
                "url": url,
                "published_at": published,
                "updated_at": updated,
                "thumbnail": f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
                "source_id": source["id"],
                "source_name": source.get("name", author),
                "source_channel_id": channel_id,
                "description": "",
            }
        )
    return videos


def fetch_with_ytdlp(source: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    url = (source.get("youtube_url") or "").strip()
    if not url:
        return []
    if "/videos" not in url.rstrip("/") and "/channel/" not in url and "/@" in url:
        url = url.rstrip("/") + "/videos"
    elif "/channel/" in url and not url.endswith("/videos"):
        url = url.rstrip("/") + "/videos"

    cmd = [
        "yt-dlp",
        "--flat-playlist",
        "--dump-single-json",
        "--no-warnings",
        "--ignore-errors",
        "--playlist-items", f"1:{max(10, limit)}",
        url,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
    if proc.returncode not in (0, 1):
        raise RuntimeError(proc.stderr.strip()[-500:] or "yt-dlp failed")
    if not proc.stdout.strip():
        return []

    payload = json.loads(proc.stdout)
    entries = payload.get("entries") or []
    out: list[dict[str, Any]] = []
    for item in entries:
        if not item:
            continue
        vid = item.get("id")
        if not vid:
            continue
        upload_date = item.get("upload_date")
        published = None
        if upload_date and re.fullmatch(r"\d{8}", str(upload_date)):
            published = datetime.strptime(str(upload_date), "%Y%m%d").replace(tzinfo=timezone.utc).isoformat()
        page_url = item.get("webpage_url") or item.get("original_url") or f"https://www.youtube.com/watch?v={vid}"
        out.append(
            {
                "id": vid,
                "title": html.unescape(item.get("title") or ""),
                "url": page_url,
                "published_at": published,
                "updated_at": None,
                "thumbnail": item.get("thumbnail") or f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",
                "source_id": source["id"],
                "source_name": source.get("name", "YouTube"),
                "source_channel_id": item.get("channel_id") or "",
                "description": item.get("description") or "",
            }
        )
    return out


def team_patterns(team: dict[str, Any]) -> list[str]:
    values = [team.get("name", "")] + list(team.get("aliases", []) or [])
    return [v for v in values if v]


def team_occurrences(text: str, team: dict[str, Any]) -> list[tuple[int, int, str]]:
    raw = html.unescape(text or "")
    occurrences: list[tuple[int, int, str]] = []
    for alias in team_patterns(team):
        m = normalize(alias)
        if not m:
            continue
        # Compare on normalized text; this is sufficient for title matching and avoids partial hits.
        norm = normalize(raw)
        for match in re.finditer(r"(?<![a-z0-9])" + re.escape(m) + r"(?![a-z0-9])", norm):
            occurrences.append((match.start(), match.end(), alias))
    return occurrences


def get_team_hits(title: str, description: str, teams: list[dict[str, Any]]) -> list[dict[str, Any]]:
    text = f"{title}\n{description}"
    hits: list[dict[str, Any]] = []
    for team in teams:
        aliases = team_patterns(team)
        if any(contains_term(text, alias) for alias in aliases):
            hits.append({"id": team["id"], "name": team["name"]})
    return hits


def score_from_title(title: str) -> str | None:
    m = SCORE_RE.search(normalize(title))
    return f"{m.group(1)}-{m.group(2)}" if m else None


def title_is_about_match(title: str, team_hits: list[dict[str, Any]], teams: list[dict[str, Any]], summary_keywords: list[str]) -> tuple[bool, dict[str, Any]]:
    text = html.unescape(title or "")
    norm = normalize(text)
    score = score_from_title(text)
    hit_ids = {t["id"] for t in team_hits}

    # Strongest evidence: score + configured team.
    if score and team_hits:
        return True, {"score": score, "confidence": "high"}

    # If the title explicitly presents two sides around /, vs, v, contre or @, it is a match title.
    parts = PAIR_SEP_RE.split(text, maxsplit=1)
    if len(parts) == 2 and team_hits:
        left, right = parts
        left_hits = get_team_hits(left, "", teams)
        right_hits = get_team_hits(right, "", teams)
        if left_hits or right_hits:
            return True, {"score": score, "confidence": "high"}

    # Common editorial phrasing: "Le BAYERN ... sur SCHALKE", "PSG s'impose...".
    if team_hits:
        leading_team = False
        for team in teams:
            if team["id"] in hit_ids:
                pos = min((o[0] for o in team_occurrences(text, team)), default=9999)
                if pos < max(45, len(normalize(text)) * 0.55):
                    leading_team = True
                    break
        if leading_team:
            for phrase in (" sur ", " face a ", " face à ", " contre ", " batt", " bat ", " s impose", " s'impose", " s incline", " s'incline", " domine", " perd ", " gagne ", " nul"):
                if phrase in f" {norm} ":
                    return True, {"score": score, "confidence": "medium"}

    # A simple team mention at the end of an article-style title is commonly a contextual mention.
    if len(team_hits) == 1:
        for pattern in MENTION_PATTERNS:
            if re.search(pattern, norm, re.I):
                return False, {"score": score, "confidence": "low", "reason": "contextual team mention"}

    # Explicit summary keywords can rescue concise titles such as "Bayern - Schalke : 0-0".
    if team_hits and any(contains_term(text, k) for k in summary_keywords):
        return True, {"score": score, "confidence": "medium"}

    return False, {"score": score, "confidence": "low", "reason": "no match evidence"}


def looks_like_summary(video: dict[str, Any], app: dict[str, Any], teams: list[dict[str, Any]]) -> tuple[bool, list[str], list[str], dict[str, Any]]:
    text = f"{video.get('title', '')} {video.get('description', '')}"
    summary_keywords = app.get("summary_keywords") or sorted(SUMMARY_FALLBACK)
    exclude_keywords = app.get("exclude_keywords") or sorted(EXCLUDE_FALLBACK)
    matched = [k for k in summary_keywords if contains_term(text, k)]
    excluded = [k for k in exclude_keywords if contains_term(text, k)]
    if excluded:
        return False, matched, excluded, {"confidence": "low", "reason": "excluded keyword"}

    title_norm = normalize(video.get("title", ""))
    score_signal = bool(SCORE_RE.search(title_norm))
    football_signal = any(x in title_norm for x in ("match", "highlights", "highlight", "goals", "resume", "resumen", "buts", "goal", "contre", " vs ", " v "))
    team_hits = get_team_hits(video.get("title", ""), video.get("description", ""), teams)

    match_ok, match_meta = title_is_about_match(video.get("title", ""), team_hits, teams, summary_keywords)
    decision = bool(team_hits) and (bool(matched) or score_signal or football_signal) and match_ok
    return decision, matched, excluded, match_meta


def infer_match_parts(title: str, teams: list[dict[str, Any]]) -> tuple[list[str], list[str], str | None]:
    """Return configured team ids involved, a stable opponent fingerprint, and score."""
    score = score_from_title(title)
    text = html.unescape(title or "")
    norm = normalize(text)
    configured_hits = get_team_hits(text, "", teams)
    configured_ids = [t["id"] for t in configured_hits]

    # Prefer explicit separators around the two teams.
    parts = PAIR_SEP_RE.split(text, maxsplit=1)
    candidates: list[str] = []
    if len(parts) == 2:
        candidates = [parts[0], parts[1]]
    else:
        # Common natural-language title patterns.
        m = re.search(r"\b(?:sur|contre|face a|face à)\s+(?:un|une|le|la|l['’])?\s*([A-Z][A-Za-zÀ-ÿ'’.-]+(?:\s+[A-Z][A-Za-zÀ-ÿ'’.-]+)*)", text)
        if m:
            candidates = [text[:m.start()], m.group(1)]

    opponent_tokens: list[str] = []
    if candidates:
        for part in candidates:
            cleaned = normalize(part)
            cleaned = SCORE_RE.sub(" ", cleaned)
            cleaned = re.sub(r"\b(resume|résumé|highlights?|extended|full|match|recap|buts?|goals?|du|de|des|le|la|les|un|une|a|sur|contre|face|avec|dans|pour|et|vs|v)\b", " ", cleaned)
            for team in teams:
                for alias in team_patterns(team):
                    cleaned = re.sub(r"(?<![a-z0-9])" + re.escape(normalize(alias)) + r"(?![a-z0-9])", " ", cleaned)
            cleaned = re.sub(r"[^a-z0-9]+", " ", cleaned).strip()
            if cleaned:
                opponent_tokens.append(cleaned)

    opponent = " ".join(sorted(set(opponent_tokens)))
    # For explicit two configured teams, opponent is represented by the pair ids and needs no free-text.
    if len(configured_ids) >= 2:
        opponent = ""

    return sorted(configured_ids), opponent[:80], score


def canonical_match_key(video: dict[str, Any], teams: list[dict[str, Any]]) -> str:
    configured_ids, opponent, score = infer_match_parts(video.get("title", ""), teams)
    source_title = normalize(video.get("title", ""))
    source_title = SCORE_RE.sub(" ", source_title)
    source_title = re.sub(r"\b(highlights?|extended|full|match|recap|resume|resumen|goals?|buts?|all|du|de|the|le|la|les|a)\b", " ", source_title)
    source_title = re.sub(r"\s+", " ", source_title).strip()
    pair = "+".join(configured_ids) if configured_ids else "unknown"
    fingerprint = re.sub(r"[^a-z0-9]", "", source_title)

    # For one configured team, include an opponent fingerprint when possible. For two, ids are enough.
    if opponent:
        return f"{pair}|{score or 'noscore'}|{normalize(opponent)}"
    if len(configured_ids) >= 2:
        return f"{pair}|{score or 'noscore'}"
    return f"{pair}|{score or 'noscore'}|{fingerprint[:50]}"


def clean_match_title(video: dict[str, Any], teams: list[dict[str, Any]]) -> str:
    title = video.get("title") or "Résumé"
    configured = get_team_hits(title, "", teams)
    names = [x["name"] for x in configured]
    score = score_from_title(title)
    parts = PAIR_SEP_RE.split(title, maxsplit=1)
    if len(parts) == 2:
        left = normalize(parts[0])
        right = normalize(parts[1])
        if score:
            return f"{parts[0].strip()} — {parts[1].strip()}".replace("  ", " ")
    if names and score:
        return title
    return title


def extract_source_videos(source: dict[str, Any], limit: int) -> tuple[list[dict[str, Any]], str]:
    try:
        videos = fetch_with_ytdlp(source, limit)
        if videos:
            return videos, "yt-dlp"
    except Exception as exc:
        ytdlp_error = str(exc)
    else:
        ytdlp_error = ""

    channel_id = resolve_channel_id(source)
    if not channel_id:
        if ytdlp_error:
            raise RuntimeError(ytdlp_error)
        return [], "atom"
    feed_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    xml = fetch(feed_url)
    return parse_feed(xml, source, min(limit, 15), channel_id), "atom"


def load_existing() -> dict[str, Any]:
    if not OUTPUT.exists():
        return {"generated_at": None, "source_status": [], "videos": [], "matches": []}
    try:
        with OUTPUT.open("r", encoding="utf-8") as fh:
            value = json.load(fh)
            value.setdefault("videos", [])
            value.setdefault("matches", [])
            return value
    except (OSError, json.JSONDecodeError):
        return {"generated_at": None, "source_status": [], "videos": [], "matches": []}


def build_matches(videos: list[dict[str, Any]], teams: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for video in videos:
        groups.setdefault(video.get("match_key") or video.get("id"), []).append(video)

    matches: list[dict[str, Any]] = []
    for key, items in groups.items():
        items.sort(key=lambda v: v.get("published_at") or "", reverse=True)
        team_map = {t["id"]: t["name"] for v in items for t in (v.get("teams") or [])}
        score = next((v.get("score") for v in items if v.get("score")), None)
        title = next((v.get("title") for v in items if v.get("title")), "Résumé")
        match_date = min((v.get("published_at") for v in items if v.get("published_at")), default=None)
        matches.append(
            {
                "match_key": key,
                "team_ids": sorted(team_map),
                "team_names": [team_map[i] for i in sorted(team_map)],
                "score": score,
                "title": title,
                "published_at": match_date,
                "sources_count": len(items),
                "videos": items,
            }
        )
    matches.sort(key=lambda m: m.get("published_at") or "", reverse=True)
    return matches


def main() -> int:
    cfg = load_json(CONFIG, EXAMPLE)
    app = cfg.get("app", {})
    teams = cfg.get("teams", [])
    sources = [s for s in cfg.get("sources", []) if s.get("enabled", True)]
    existing = load_existing()

    # Keep old valid records so we do not lose older summaries when a channel temporarily fails.
    by_video_id = {v.get("id"): v for v in existing.get("videos", []) if v.get("id")}
    status: list[dict[str, Any]] = []
    limit = max(60, int(app.get("max_videos_per_source", 60)))

    for source in sources:
        sid = source.get("id")
        result = {"source_id": sid, "source_name": source.get("name", sid), "ok": False, "count": 0, "method": None, "error": None}
        try:
            parsed, method = extract_source_videos(source, limit)
            result["method"] = method
            result["count"] = len(parsed)
            for video in parsed:
                decision, keywords, excluded, meta = looks_like_summary(video, app, teams)
                hits = get_team_hits(video.get("title", ""), video.get("description", ""), teams)
                video["is_summary"] = decision
                video["summary_keywords"] = keywords
                video["excluded_keywords"] = excluded
                video["match_confidence"] = meta.get("confidence")
                video["match_reason"] = meta.get("reason")
                video["score"] = meta.get("score")
                video["teams"] = hits
                if decision and hits:
                    video["match_key"] = canonical_match_key(video, teams)
                    video["match_title"] = clean_match_title(video, teams)
                    video["fetched_at"] = datetime.now(timezone.utc).isoformat()
                    by_video_id[video["id"]] = video
            result["ok"] = True
        except (HTTPError, URLError, ET.ParseError, TimeoutError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
            result["error"] = str(exc)[:400]
        except Exception as exc:
            result["error"] = f"Unexpected error: {type(exc).__name__}: {exc}"[:400]
        status.append(result)
        time.sleep(0.4)

    cutoff = datetime.now(timezone.utc) - timedelta(days=int(app.get("keep_days", 45)))
    retained: list[dict[str, Any]] = []
    for video in by_video_id.values():
        pub = video.get("published_at")
        keep = True
        if pub:
            try:
                keep = datetime.fromisoformat(pub.replace("Z", "+00:00")) >= cutoff
            except ValueError:
                keep = True
        if keep and video.get("is_summary") and video.get("teams") and video.get("match_key"):
            retained.append(video)

    retained.sort(key=lambda v: v.get("published_at") or "", reverse=True)
    matches = build_matches(retained, teams)

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "teams": [{"id": t.get("id"), "name": t.get("name")} for t in teams if t.get("id")],
        "source_status": status,
        "videos": retained,
        "matches": matches,
        "stats": {
            "videos": len(retained),
            "matches": len(matches),
            "teams": len(teams),
            "sources": len(sources),
        },
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", encoding="utf-8") as fh:
        json.dump(output, fh, ensure_ascii=False, indent=2)
        fh.write("\n")

    print(f"Stored {len(retained)} videos grouped into {len(matches)} matches.")
    for item in status:
        method = f" [{item['method']}]" if item.get("method") else ""
        if item["ok"]:
            print(f"- {item['source_name']}{method}: {item['count']} videos scanned")
        else:
            print(f"- {item['source_name']}: ERROR: {item['error']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
