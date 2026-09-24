"""Atomic import of source-verified Entity Continuity synthetic review drafts."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from typing import Any

from .core import ECONOMIC_COSTS, ExchangeDB, utc_now


def _digest(value: Any) -> str:
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode()
    except (TypeError, ValueError) as exc:
        raise ValueError("handoff must contain finite JSON values") from exc
    return hashlib.sha256(raw).hexdigest()


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _zero_money(value: Any) -> bool:
    return type(value) in {int, float} and value == 0


def _validate(bundle: dict[str, Any], verified_bundle_digest: str) -> list[dict[str, Any]]:
    """Validate the portable contract after exact-source verification by the caller."""
    if not isinstance(bundle, dict) or set(bundle) != {
        "schema_version", "scope", "as_of", "source_receipt_digest", "jobs", "bundle_digest"
    }:
        raise ValueError("invalid Entity Continuity handoff shape")
    if bundle["schema_version"] != "entity-continuity.a2z-agent-hire.v2":
        raise ValueError("unsupported Entity Continuity handoff schema")
    if bundle["scope"] != "SYNTHETIC_REVIEW_DRAFTS_ONLY_NO_EXTERNAL_ACTION":
        raise ValueError("only synthetic review drafts are accepted")
    if not _nonempty(bundle["as_of"]) or len(bundle["as_of"]) != 10:
        raise ValueError("handoff as_of must be an ISO date")
    try:
        date.fromisoformat(bundle["as_of"])
    except ValueError as exc:
        raise ValueError("handoff as_of must be an ISO date") from exc
    if not isinstance(bundle["source_receipt_digest"], str) or not re.fullmatch(
            r"[0-9a-f]{64}", bundle["source_receipt_digest"]):
        raise ValueError("source receipt digest is invalid")
    body = {key: value for key, value in bundle.items() if key != "bundle_digest"}
    if bundle["bundle_digest"] != _digest(body) or verified_bundle_digest != bundle["bundle_digest"]:
        raise ValueError("handoff digest or source verification does not match bundle")
    jobs = bundle["jobs"]
    if not isinstance(jobs, list) or not jobs:
        raise ValueError("handoff jobs must be a nonempty list")
    seen: set[str] = set()
    for item in jobs:
        if not isinstance(item, dict) or set(item) != {"source", "a2z_job"}:
            raise ValueError("handoff job has invalid shape")
        source, job = item["source"], item["a2z_job"]
        if not isinstance(source, dict) or not isinstance(job, dict):
            raise ValueError("handoff source and job must be objects")
        required_source = {"entity_id", "obligation_id", "receipt_digest", "jurisdiction",
                           "rule_id", "event_id", "due_at", "status", "evidence_status"}
        if set(source) != required_source or any(not _nonempty(source[key]) for key in required_source):
            raise ValueError("handoff source fields are incomplete")
        if source["receipt_digest"] != bundle["source_receipt_digest"]:
            raise ValueError("handoff source receipt differs from bundle")
        if source["status"] not in {"open", "overdue"} or source["evidence_status"] not in {
                "missing", "reported", "verification_claimed"}:
            raise ValueError("handoff source status is unsupported")
        try:
            if len(source["due_at"]) != 10:
                raise ValueError("invalid length")
            date.fromisoformat(source["due_at"])
        except ValueError as exc:
            raise ValueError("handoff source due_at must be an ISO date") from exc
        source_key = {"entity_id": source["entity_id"], "obligation_id": source["obligation_id"],
                      "receipt_digest": source["receipt_digest"]}
        expected_id = "JOB-EC-" + _digest(source_key)[:16].upper()
        if job.get("id") != expected_id or expected_id in seen:
            raise ValueError("handoff job id is invalid or duplicated")
        required_job = {"id", "title", "objective", "budget_usd", "customer_price_usd",
                        "economics", "acceptance_criteria", "worker_policy", "evidence_class"}
        if set(job) != required_job or not _nonempty(job["title"]) or not _nonempty(job["objective"]):
            raise ValueError("handoff job fields are incomplete")
        if not _zero_money(job["budget_usd"]) or not _zero_money(job["customer_price_usd"]):
            raise ValueError("handoff review draft must be zero-dollar")
        costs = job["economics"]
        if not isinstance(costs, dict) or set(costs) != set(ECONOMIC_COSTS) or any(
                not _zero_money(costs[key]) for key in ECONOMIC_COSTS):
            raise ValueError("handoff review draft cannot inherit demo costs")
        if (job["evidence_class"] != "SYNTHETIC" or
                job["worker_policy"] != {"allowed_worker_types": ["human"],
                                         "requires_independent_verifier": True}):
            raise ValueError("handoff job is not a synthetic human-review draft")
        criteria = job["acceptance_criteria"]
        if (not isinstance(criteria, list) or len(criteria) != 3 or
                any(not isinstance(item, dict) or not _nonempty(item.get("id")) or
                    item.get("required") is not True or
                    not _nonempty(item.get("description")) for item in criteria)):
            raise ValueError("handoff acceptance criteria are invalid")
        if {item["id"] for item in criteria} != {
                "SOURCE_RECONCILED", "EVIDENCE_GAPS", "HUMAN_ACCEPTANCE"}:
            raise ValueError("handoff acceptance criteria are invalid")
        seen.add(expected_id)
    return jobs


def preview_handoff(bundle: dict[str, Any], *, verified_bundle_digest: str) -> dict[str, Any]:
    """Show the exact import scope without opening or changing a database."""
    jobs = _validate(bundle, verified_bundle_digest)
    return {"dry_run": True, "job_count": len(jobs),
            "job_ids": [item["a2z_job"]["id"] for item in jobs],
            "bundle_digest": bundle["bundle_digest"],
            "source_receipt_digest": bundle["source_receipt_digest"]}


def import_handoff(db: ExchangeDB, bundle: dict[str, Any], *,
                   verified_bundle_digest: str) -> dict[str, Any]:
    """Persist a verified bundle and all jobs in one SQLite transaction."""
    jobs = _validate(bundle, verified_bundle_digest)
    digest = bundle["bundle_digest"]
    recorded = db.db.execute("SELECT * FROM entity_handoffs WHERE bundle_digest=?", (digest,)).fetchone()
    if recorded is not None:
        mappings = {row["job_id"]: row for row in db.db.execute(
            "SELECT * FROM entity_handoff_jobs WHERE bundle_digest=?", (digest,))}
        expected = {item["a2z_job"]["id"]: item for item in jobs}
        if (recorded["source_receipt_digest"] != bundle["source_receipt_digest"] or
                recorded["as_of"] != bundle["as_of"] or
                recorded["job_count"] != len(jobs) or set(mappings) != set(expected)):
            raise ValueError("recorded handoff is incomplete or conflicts with source")
        fields = ("title", "objective", "budget_usd", "customer_price_usd",
                  "acceptance_criteria", "worker_policy", "evidence_class")
        for job_id, item in expected.items():
            source, job = item["source"], item["a2z_job"]
            mapping = mappings[job_id]
            if (mapping["source_entity_id"] != source["entity_id"] or
                    mapping["source_obligation_id"] != source["obligation_id"]):
                raise ValueError("recorded handoff source mapping differs")
            try:
                stored = db.job(job_id)
            except KeyError as exc:
                raise ValueError("recorded handoff job is missing") from exc
            if (any(stored[key] != job[key] for key in fields) or
                    stored["economics"]["costs"] != job["economics"]):
                raise ValueError("recorded handoff job contract differs")
        return {"created": [], "unchanged": sorted(expected), "bundle_digest": digest,
                "source_receipt_digest": bundle["source_receipt_digest"], "scope": bundle["scope"]}
    # A deterministic ID already owned by another import or job is a conflict.
    for item in jobs:
        job_id = item["a2z_job"]["id"]
        if db.db.execute("SELECT 1 FROM jobs WHERE id=?", (job_id,)).fetchone() is not None:
            raise ValueError(f"existing job {job_id} has no matching source handoff")
    with db.db:
        db.db.execute("INSERT INTO entity_handoffs VALUES(?,?,?,?,?)",
                      (digest, bundle["source_receipt_digest"], bundle["as_of"], len(jobs), utc_now()))
        for item in jobs:
            job = item["a2z_job"]
            source = item["source"]
            db.create_job(job, commit=False)
            db.db.execute("INSERT INTO entity_handoff_jobs VALUES(?,?,?,?)",
                          (job["id"], digest, source["entity_id"], source["obligation_id"]))
    return {"created": [item["a2z_job"]["id"] for item in jobs], "unchanged": [],
            "bundle_digest": digest, "source_receipt_digest": bundle["source_receipt_digest"],
            "scope": bundle["scope"]}
