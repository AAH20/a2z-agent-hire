"""Import synthetic Entity Continuity review drafts into the local A2Z job board."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .core import ExchangeDB


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def import_handoff(db: ExchangeDB, bundle: dict[str, Any]) -> dict[str, Any]:
    """Import locally after source verification; this does not authenticate source identity."""
    if not isinstance(bundle, dict) or bundle.get("schema_version") != "entity-continuity.a2z-agent-hire.v1":
        raise ValueError("unsupported Entity Continuity handoff schema")
    if bundle.get("scope") != "SYNTHETIC_REVIEW_DRAFTS_ONLY_NO_EXTERNAL_ACTION":
        raise ValueError("only synthetic review drafts are accepted")
    body = {key: value for key, value in bundle.items() if key != "bundle_digest"}
    if set(bundle) != set(body) | {"bundle_digest"} or bundle.get("bundle_digest") != _digest(body):
        raise ValueError("handoff digest does not match bundle")
    jobs = bundle.get("jobs")
    if not isinstance(jobs, list):
        raise ValueError("handoff jobs must be a list")
    seen: set[str] = set()
    for item in jobs:
        if not isinstance(item, dict) or set(item) != {"source", "a2z_job"}:
            raise ValueError("handoff job has invalid shape")
        source, job = item["source"], item["a2z_job"]
        if not isinstance(source, dict) or not isinstance(job, dict):
            raise ValueError("handoff source and job must be objects")
        source_key = {"entity_id": source.get("entity_id"), "obligation_id": source.get("obligation_id"),
                      "receipt_digest": source.get("receipt_digest")}
        expected_id = "JOB-EC-" + _digest(source_key)[:16].upper()
        if (job.get("id") != expected_id or expected_id in seen or
                source.get("receipt_digest") != bundle.get("source_receipt_digest") or
                job.get("evidence_class") != "SYNTHETIC" or
                job.get("worker_policy") != {"allowed_worker_types": ["human"], "requires_independent_verifier": True} or
                job.get("budget_usd") != 0 or job.get("customer_price_usd") != 0):
            raise ValueError("handoff job is not a valid synthetic human-review draft")
        seen.add(expected_id)
    # Check every existing contract before creating any job, so a later conflict
    # cannot leave an earlier draft imported from the same bundle.
    existing_by_id = {}
    for item in jobs:
        job = item["a2z_job"]
        try:
            existing = db.job(job["id"])
        except KeyError:
            existing_by_id[job["id"]] = None
        else:
            fields = ("title", "objective", "budget_usd", "customer_price_usd", "acceptance_criteria",
                      "worker_policy", "evidence_class")
            if any(existing[field] != job.get(field) for field in fields):
                raise ValueError(f"existing job {job['id']} conflicts with handoff")
            existing_by_id[job["id"]] = existing
    created, unchanged = [], []
    for item in jobs:
        job = item["a2z_job"]
        if existing_by_id[job["id"]] is None:
            db.create_job(job)
            created.append(job["id"])
        else:
            unchanged.append(job["id"])
    return {"created": created, "unchanged": unchanged,
            "source_receipt_digest": bundle["source_receipt_digest"],
            "scope": bundle["scope"]}
