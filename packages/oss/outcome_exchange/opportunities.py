"""Local opportunity intake from a bounded, public employer posting feed."""

from __future__ import annotations

import http.client
import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import quote


SCHEMA = """
CREATE TABLE IF NOT EXISTS opportunities (
 id TEXT PRIMARY KEY, provider TEXT NOT NULL, site TEXT NOT NULL,
 external_id TEXT NOT NULL, title TEXT NOT NULL, organization TEXT NOT NULL,
 location TEXT NOT NULL, source_url TEXT NOT NULL, apply_url TEXT NOT NULL,
 first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL, last_refresh_id TEXT NOT NULL,
 missing_count INTEGER NOT NULL DEFAULT 0,
 status TEXT NOT NULL CHECK(status IN ('ACTIVE','CLOSED')),
 UNIQUE(provider,site,external_id)
);
CREATE INDEX IF NOT EXISTS idx_opportunities_status ON opportunities(status,site);
CREATE TABLE IF NOT EXISTS opportunity_refreshes (
 id TEXT PRIMARY KEY, provider TEXT NOT NULL, site TEXT NOT NULL,
 observed_at TEXT NOT NULL, count INTEGER NOT NULL, closed_count INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS local_application_tracks (
 opportunity_id TEXT PRIMARY KEY REFERENCES opportunities(id),
 status TEXT NOT NULL CHECK(status IN ('SAVED','APPLIED','INTERVIEW','OFFER','CLOSED')),
 note TEXT NOT NULL, follow_up_at TEXT, updated_at TEXT NOT NULL
);
"""
SITE = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9-]{0,79}\Z")
TRACK_STATUSES = {"SAVED", "APPLIED", "INTERVIEW", "OFFER", "CLOSED"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def freshness(last_seen_at: str, status: str, reference: datetime | None = None,
              missing_count: int = 0) -> str:
    if status == "CLOSED":
        return "CLOSED"
    if missing_count:
        return "MISSING_ONCE"
    reference = reference or datetime.now(timezone.utc)
    age_hours = (reference - datetime.fromisoformat(last_seen_at)).total_seconds() / 3600
    return "FRESH" if age_hours < 24 else "AGING" if age_hours < 72 else "STALE"


def validate_site(site: str) -> str:
    if not SITE.fullmatch(site):
        raise ValueError("site must be a Lever board slug")
    return site


def validate_timestamp(value: str) -> str:
    if not value:
        raise ValueError("follow_up_at must be an ISO 8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("follow_up_at must be an ISO 8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError("follow_up_at must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat()


def normalize_lever(posting: dict[str, Any], site: str, region: str) -> dict[str, str]:
    external_id = str(posting.get("id", "")).strip()
    title = str(posting.get("text", "")).strip()
    if not external_id or not title or len(external_id) > 200 or len(title) > 300:
        raise ValueError("Lever posting requires bounded id and title")
    categories = posting.get("categories") or {}
    if not isinstance(categories, dict):
        raise ValueError("Lever categories must be an object")
    location = str(categories.get("location") or "Not specified").strip()[:200]
    host = "jobs.eu.lever.co" if region == "eu" else "jobs.lever.co"
    canonical = f"https://{host}/{quote(site)}/{quote(external_id, safe='')}"
    return {"external_id": external_id, "title": title, "organization": site,
            "location": location, "source_url": canonical, "apply_url": canonical}


def fetch_lever_page(site: str, region: str, skip: int, limit: int) -> list[dict[str, Any]]:
    """Fetch from a fixed host without redirects or arbitrary URL input."""
    host = "api.eu.lever.co" if region == "eu" else "api.lever.co"
    connection = http.client.HTTPSConnection(host, timeout=10)
    try:
        connection.request("GET", f"/v0/postings/{quote(site)}?mode=json&skip={skip}&limit={limit}",
                           headers={"Accept": "application/json", "User-Agent": "A2Z-Agent-Hire/0.2"})
        response = connection.getresponse()
        if response.status != 200:
            raise RuntimeError(f"Lever API returned HTTP {response.status}")
        raw = response.read(3_000_001)
        if len(raw) > 3_000_000:
            raise ValueError("Lever response exceeds 3 MB limit")
        payload = json.loads(raw)
        if not isinstance(payload, list):
            raise ValueError("Lever response must be a list")
        return payload
    finally:
        connection.close()


class OpportunityStore:
    def __init__(self, db: sqlite3.Connection):
        self.db = db
        self.db.executescript(SCHEMA)
        self.db.commit()

    def list(self, status: str | None = "ACTIVE") -> list[dict[str, Any]]:
        if status not in {"ACTIVE", "CLOSED", None}:
            raise ValueError("invalid opportunity status")
        rows = (self.db.execute("SELECT * FROM opportunities WHERE status=? ORDER BY last_seen_at DESC, id", (status,))
                if status else self.db.execute("SELECT * FROM opportunities ORDER BY last_seen_at DESC, id"))
        return [{**dict(row), "freshness": freshness(row["last_seen_at"], row["status"],
                                                   missing_count=row["missing_count"])} for row in rows]

    def search(self, query: str = "", location: str = "") -> list[dict[str, Any]]:
        """Transparent local text retrieval; scores are not hiring predictions."""
        query, location = query.strip().casefold(), location.strip().casefold()
        if len(query) > 120 or len(location) > 120:
            raise ValueError("search terms are too long")
        tokens = list(dict.fromkeys(query.split()))
        if len(tokens) > 8:
            raise ValueError("search supports at most eight distinct terms")
        matches = []
        for item in self.list():
            title = item["title"].casefold()
            org = item["organization"].casefold()
            place = item["location"].casefold()
            if location and location not in place:
                continue
            if any(token not in f"{title} {org} {place}" for token in tokens):
                continue
            reasons = []
            score = 0
            for token in tokens:
                if token in title:
                    score += 3
                    reasons.append(f"title:{token}")
                if token in org:
                    score += 1
                    reasons.append(f"organization:{token}")
                if token in place:
                    score += 1
                    reasons.append(f"location:{token}")
            matches.append({**item, "retrieval_score": score, "match_reasons": reasons})
        return sorted(matches, key=lambda item: (-item["retrieval_score"], item["title"].casefold(),
                                                 item["organization"].casefold(), item["id"]))

    def refresh_lever(self, site: str, *, region: str = "global", max_pages: int = 20,
                      fetch_page: Callable[[str, str, int, int], list[dict[str, Any]]] = fetch_lever_page) -> dict[str, Any]:
        site = validate_site(site)
        if region not in {"global", "eu"} or not 1 <= max_pages <= 20:
            raise ValueError("invalid region or page limit")
        # Fetch and validate the entire source before changing any local state.
        batch: list[dict[str, str]] = []
        seen: set[str] = set()
        limit = 100
        for page in range(max_pages):
            payload = fetch_page(site, region, page * limit, limit)
            if not isinstance(payload, list) or len(payload) > limit:
                raise ValueError("Lever page must contain at most 100 postings")
            for item in payload:
                if not isinstance(item, dict):
                    raise ValueError("Lever posting must be an object")
                normalized = normalize_lever(item, site, region)
                if normalized["external_id"] in seen:
                    raise ValueError("duplicate external id in source refresh")
                seen.add(normalized["external_id"])
                batch.append(normalized)
            if len(payload) < limit:
                break
        else:
            raise ValueError("source pagination limit reached; no partial refresh committed")

        observed_at = now()
        refresh_id = f"REF-{uuid.uuid4().hex[:12].upper()}"
        with self.db:
            for item in batch:
                self.db.execute("""
                    INSERT INTO opportunities VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(provider,site,external_id) DO UPDATE SET
                      title=excluded.title, organization=excluded.organization,
                      location=excluded.location, source_url=excluded.source_url,
                      apply_url=excluded.apply_url, last_seen_at=excluded.last_seen_at,
                      last_refresh_id=excluded.last_refresh_id, missing_count=0, status='ACTIVE'
                """, (f"OPP-{uuid.uuid4().hex[:12].upper()}", "lever", site,
                      item["external_id"], item["title"], item["organization"],
                      item["location"], item["source_url"], item["apply_url"],
                      observed_at, observed_at, refresh_id, 0, "ACTIVE"))
            closed = self.db.execute(
                "SELECT COUNT(*) FROM opportunities WHERE provider='lever' AND site=? AND status='ACTIVE' AND missing_count=1 AND last_refresh_id<>?",
                (site, refresh_id)).fetchone()[0]
            self.db.execute("""
                UPDATE opportunities SET missing_count=missing_count+1,
                  status=CASE WHEN missing_count+1>=2 THEN 'CLOSED' ELSE status END
                WHERE provider='lever' AND site=? AND status='ACTIVE' AND last_refresh_id<>?
            """, (site, refresh_id))
            self.db.execute("INSERT INTO opportunity_refreshes VALUES(?,?,?,?,?,?)",
                            (refresh_id, "lever", site, observed_at, len(batch), closed))
        return {"refresh_id": refresh_id, "provider": "lever", "site": site, "region": region,
                "observed_at": observed_at, "count": len(batch), "closed_count": closed,
                "source_class": "PUBLIC_PROVIDER_API_OBSERVED"}

    def track(self, opportunity_id: str, status: str, note: str = "",
              follow_up_at: str | None = None) -> dict[str, Any]:
        if status not in TRACK_STATUSES or len(note) > 1000:
            raise ValueError("invalid status or note too long")
        if self.db.execute("SELECT 1 FROM opportunities WHERE id=?", (opportunity_id,)).fetchone() is None:
            raise KeyError("opportunity not found")
        follow_up = validate_timestamp(follow_up_at) if follow_up_at is not None else None
        with self.db:
            self.db.execute("""
                INSERT INTO local_application_tracks VALUES(?,?,?,?,?)
                ON CONFLICT(opportunity_id) DO UPDATE SET status=excluded.status,
                  note=excluded.note, follow_up_at=excluded.follow_up_at,
                  updated_at=excluded.updated_at
            """, (opportunity_id, status, note, follow_up, now()))
        row = self.db.execute("SELECT * FROM local_application_tracks WHERE opportunity_id=?", (opportunity_id,)).fetchone()
        return dict(row)

    def tracks(self) -> list[dict[str, Any]]:
        rows = self.db.execute("""
            SELECT t.*,o.title,o.organization,o.source_url,o.status AS opportunity_status
            FROM local_application_tracks t JOIN opportunities o ON o.id=t.opportunity_id
            ORDER BY t.updated_at DESC
        """)
        return [dict(row) for row in rows]
