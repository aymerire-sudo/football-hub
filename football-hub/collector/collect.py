#!/usr/bin/env python3
"""Collect recent YouTube channel videos from Atom feeds and classify match summaries."""
from __future__ import annotations

import html
import json
import re
import sys
import time
import unicodedata
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config.json"
EXAMPLE = ROOT / "config.example.json"
OUTPUT = ROOT / "data" / "videos.json"

ATOM = "http://www.w3.org/2005/Atom"
YT = "http://www.youtube.com/xml/schemas/2015"
NS = {"atom": ATOM, "yt": YT, "media": "http://search.yahoo.com/mrss/"}

USER_AGENT = "FootballHub/1.0 (+https://github.com/)"


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
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/atom+xml,application/xml,text/xml,*/*"})
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
    if direct and not direct.startswith("REPLACE_"):
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


def parse_feed(xml_bytes: bytes, source: dict[str, Any], limit: int, resolved_channel_id: str = "") -> list[dict[str, Any]]:
    root = ET.fromstring(xml_bytes)
    videos: list[dict[str, Any]] = []
    for entry in root.findall("atom:entry", NS)[:limit]:
        video_id = get_text(entry, "yt:videoId")
        title = get_text(entry, "atom:title")
        published = parse_date(get_text(entry, "atom:published"))
        updated = parse_date(get_text(entry, "atom:updated"))
        url = get_attr(entry, "atom:link[@rel='alternate']", "href")
        author_name = get_text(entry, "atom:author/atom:name") or source.get("name", "YouTube")
        if not video_id:
            link_id = get_text(entry, "atom:id")
            if link_id.startswith("yt:video:"):
                video_id = link_id.rsplit(":", 1)[-1]
        if not url and video_id:
            url = f"https://www.youtube.com/watch?v={video_id}"
        thumbnail = f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg" if video_id else ""
        videos.append({
            "id": video_id,
            "title": html.unescape(title),
            "url": url,
            "published_at": published,
            "updated_at": updated,
            "thumbnail": thumbnail,
            "source_id": source["id"],
            "source_name": author_name,
            "source_channel_id": resolved_channel_id or source.get("youtube_channel_id", ""),
            "description": ""
        })
    return videos


def get_team_hits(title: str, description: str, teams: list[dict[str, Any]]) -> list[dict[str, Any]]:
    haystack = f"{title}\n{description}"
    hits = []
    for team in teams:
        aliases = [team.get("name", "")] + team.get("aliases", [])
        aliases = [x for x in aliases if x]
        if any(contains_term(haystack, alias) for alias in aliases):
            hits.append({"id": team["id"], "name": team["name"]})
    return hits


def looks_like_summary(video: dict[str, Any], app: dict[str, Any]) -> tuple[bool, list[str], list[str]]:
    text = f"{video.get('title', '')} {video.get('description', '')}"
    normalized = normalize(text)
    matched = [k for k in app.get("summary_keywords", []) if contains_term(text, k)]
    excluded = [k for k in app.get("exclude_keywords", []) if contains_term(text, k)]
    if excluded:
        return False, matched, excluded
    title_norm = normalize(video.get("title", ""))
    # Extra score/football signals make strict keyword lists less brittle.
    score_signal = bool(re.search(r"\b\d{1,2}\s*[-–—:]\s*\d{1,2}\b", title_norm))
    football_signal = any(x in normalized for x in ("match", "highlights", "highlight", "goals", "resume", "resumen"))
    decision = bool(matched) or (score_signal and football_signal)
    return decision, matched, excluded


def canonical_match_key(title: str, team_hits: list[dict[str, Any]], published_at: str | None) -> str:
    # This intentionally stays conservative: two different videos for the same match
    # are only merged when we have the same date + overlapping configured teams + score/title fingerprint.
    date = (published_at or "")[:10]
    teams = "+".join(sorted(t["id"] for t in team_hits)) or "unknown"
    score = re.search(r"\b(\d{1,2})\s*[-–—:]\s*(\d{1,2})\b", normalize(title))
    score_part = f"{score.group(1)}-{score.group(2)}" if score else "noscore"
    title_norm = normalize(title)
    title_norm = re.sub(r"\b\d{1,2}\s*[-–—:]\s*\d{1,2}\b", "", title_norm)
    # Avoid using generic summary words in the fingerprint.
    title_norm = re.sub(r"\b(highlights?|extended|full|match|recap|resume|resumen|goals?|all)\b", " ", title_norm)
    title_norm = re.sub(r"\s+", " ", title_norm).strip()
    fingerprint = re.sub(r"[^a-z0-9]", "", title_norm)[:80]
    return f"{date}|{teams}|{score_part}|{fingerprint}"


def load_existing() -> dict[str, Any]:
    if not OUTPUT.exists():
        return {"generated_at": None, "source_status": [], "videos": []}
    try:
        with OUTPUT.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {"generated_at": None, "source_status": [], "videos": []}


def main() -> int:
    cfg = load_json(CONFIG, EXAMPLE)
    app = cfg.get("app", {})
    teams = cfg.get("teams", [])
    sources = [s for s in cfg.get("sources", []) if s.get("enabled", True)]
    existing = load_existing()
    by_video_id = {v.get("id"): v for v in existing.get("videos", []) if v.get("id")}
    status: list[dict[str, Any]] = []
    all_new: list[dict[str, Any]] = []

    for source in sources:
        sid = source.get("id")
        channel_id = resolve_channel_id(source)
        result = {"source_id": sid, "source_name": source.get("name", sid), "ok": False, "count": 0, "error": None}
        if not channel_id:
            result["error"] = "Channel ID manquant"
            status.append(result)
            continue
        feed_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
        try:
            xml = fetch(feed_url)
            parsed = parse_feed(xml, source, int(app.get("max_videos_per_source", 15)), channel_id)
            for video in parsed:
                decision, keywords, excluded = looks_like_summary(video, app)
                hits = get_team_hits(video["title"], video.get("description", ""), teams)
                video["is_summary"] = decision
                video["summary_keywords"] = keywords
                video["excluded_keywords"] = excluded
                video["teams"] = hits
                video["match_key"] = canonical_match_key(video["title"], hits, video.get("published_at"))
                video["fetched_at"] = datetime.now(timezone.utc).isoformat()
                # Store only videos that have at least one configured team and look like summaries.
                if decision and hits:
                    all_new.append(video)
                    by_video_id[video["id"]] = video
            result["ok"] = True
            result["count"] = len(parsed)
        except (HTTPError, URLError, ET.ParseError, TimeoutError, ValueError) as exc:
            result["error"] = str(exc)[:300]
        except Exception as exc:  # defensive: one bad source must not break the whole update
            result["error"] = f"Unexpected error: {type(exc).__name__}: {exc}"[:300]
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
        if keep and video.get("is_summary") and video.get("teams"):
            retained.append(video)

    retained.sort(key=lambda v: v.get("published_at") or "", reverse=True)
    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_status": status,
        "videos": retained,
        "stats": {
            "videos": len(retained),
            "teams": len(teams),
            "sources": len(sources)
        }
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", encoding="utf-8") as fh:
        json.dump(output, fh, ensure_ascii=False, indent=2)
        fh.write("\n")

    print(f"Collected {len(all_new)} matching new items; stored {len(retained)} items.")
    failed = [s for s in status if not s["ok"]]
    if failed:
        print(f"{len(failed)} source(s) failed:")
        for item in failed:
            print(f"- {item['source_name']}: {item['error']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
