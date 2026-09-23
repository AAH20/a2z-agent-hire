"""Dependency-free local job board, hiring, evaluation, and economics core."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def as_money(value: Any) -> float:
    result = round(float(value), 2)
    if result < 0:
        raise ValueError("money values must be nonnegative")
    return result


def dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def loads(value: str, fallback: Any) -> Any:
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


ECONOMIC_COSTS = ("worker_payout_usd", "model_cost_usd", "compute_cost_usd", "human_review_cost_usd", "payment_fee_usd", "support_reserve_usd", "rework_reserve_usd")
DEFAULT_COSTS = {"worker_payout_usd": 28.0, "model_cost_usd": 9.5, "compute_cost_usd": 3.25, "human_review_cost_usd": 10.0, "payment_fee_usd": 2.25, "support_reserve_usd": 2.5, "rework_reserve_usd": 6.0}


SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs(
 id TEXT PRIMARY KEY, title TEXT NOT NULL, objective TEXT NOT NULL, status TEXT NOT NULL,
 budget_usd REAL NOT NULL, customer_price_usd REAL NOT NULL, criteria TEXT NOT NULL,
 policy TEXT NOT NULL, costs TEXT NOT NULL, evidence_class TEXT NOT NULL,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS workers(
 id TEXT PRIMARY KEY, name TEXT NOT NULL, worker_type TEXT NOT NULL,
 capabilities TEXT NOT NULL, evaluation TEXT NOT NULL, availability TEXT NOT NULL,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS applications(
 id TEXT PRIMARY KEY, job_id TEXT NOT NULL, worker_id TEXT NOT NULL, proposal TEXT NOT NULL,
 bid_usd REAL NOT NULL, status TEXT NOT NULL, reviewer TEXT, created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs(
 id TEXT PRIMARY KEY, job_id TEXT NOT NULL, route TEXT NOT NULL, decision TEXT NOT NULL,
 tasks TEXT NOT NULL, evidence TEXT NOT NULL, acceptance TEXT NOT NULL, outcome TEXT NOT NULL,
 failures TEXT NOT NULL, elapsed_seconds INTEGER NOT NULL, rework_cost_usd REAL NOT NULL,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS evolution(
 id TEXT PRIMARY KEY, version TEXT UNIQUE NOT NULL, parent_version TEXT, change_type TEXT NOT NULL,
 suite TEXT NOT NULL, metrics TEXT NOT NULL, gates TEXT NOT NULL, status TEXT NOT NULL,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL,
 entity_id TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL);
"""


class ExchangeDB:
    """SQLite-backed OSS reference runtime; no network or credential assumptions."""

    def __init__(self, path: str | Path = ":memory:"):
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self.db.commit()
        self.seed()

    def close(self) -> None:
        self.db.close()

    def _event(self, kind: str, entity_id: str, payload: Any) -> None:
        self.db.execute("INSERT INTO events(kind, entity_id, payload, created_at) VALUES(?,?,?,?)", (kind, entity_id, dumps(payload), utc_now()))

    def seed(self) -> None:
        if self.db.execute("SELECT 1 FROM workers LIMIT 1").fetchone() is None:
            for data in (
                ("human-reviewer-001", "Human acceptance reviewer", "human", ["acceptance", "policy-review"], {"verified": False}),
                ("agent-reviewer-001", "Evidence review agent", "agent", ["terraform", "evidence", "policy"], {"first_pass_acceptance": 0.82}),
                ("swarm-review-team", "Independent review swarm", "swarm", ["parallel-review", "replay", "rollback"], {"first_pass_acceptance": 0.86}),
            ):
                self.db.execute("INSERT INTO workers VALUES(?,?,?,?,?,?,?)", (data[0], data[1], data[2], dumps(data[3]), dumps(data[4]), "AVAILABLE", utc_now()))
        if self.db.execute("SELECT 1 FROM jobs LIMIT 1").fetchone() is None:
            self.create_job({"id": "JOB-DEMO-001", "title": "Review a multi-cloud Terraform change", "objective": "Produce a reviewable change decision with evidence and human acceptance.", "budget_usd": 75, "customer_price_usd": 75, "acceptance_criteria": [{"id": "PLAN_DIGEST", "description": "Exact plan version recorded", "required": True}, {"id": "SECURITY_EVIDENCE", "description": "Security checks attached", "required": True}, {"id": "HUMAN_ACCEPTANCE", "description": "Accountable human accepts result", "required": True}], "worker_policy": {"allowed_worker_types": ["human", "agent", "swarm"], "requires_independent_verifier": True}, "evidence_class": "SYNTHETIC"}, commit=False)
        if self.db.execute("SELECT 1 FROM evolution LIMIT 1").fetchone() is None:
            self.create_evolution({"version": "router-0.1.0", "parent_version": None, "change_type": "initial-reference", "benchmark_suite": ["synthetic-cloud-change-v1"], "metrics": {"first_pass_acceptance": 0.0, "rework_rate": 1.0, "cost_per_accepted_outcome_usd": None, "holdout_passed": False}, "gates": {"min_first_pass_acceptance": 1.0, "max_rework_rate": 0.05, "max_cost_per_accepted_outcome_usd": 75}}, commit=False)
        self.db.commit()

    def create_job(self, data: dict[str, Any], commit: bool = True) -> dict[str, Any]:
        title, objective = str(data.get("title", "")).strip(), str(data.get("objective", "")).strip()
        criteria, policy = data.get("acceptance_criteria"), data.get("worker_policy")
        if not title or not objective or not isinstance(criteria, list) or not criteria:
            raise ValueError("title, objective, and acceptance_criteria are required")
        if not isinstance(policy, dict) or not policy.get("allowed_worker_types"):
            raise ValueError("worker_policy.allowed_worker_types is required")
        if any(item not in {"human", "agent", "swarm"} for item in policy["allowed_worker_types"]):
            raise ValueError("unsupported worker type")
        ids = [str(item.get("id", "")) for item in criteria]
        if any(not item for item in ids) or len(ids) != len(set(ids)):
            raise ValueError("acceptance criterion ids must be unique")
        job_id, created = str(data.get("id") or f"JOB-{uuid.uuid4().hex[:10].upper()}"), utc_now()
        costs = {key: as_money((data.get("economics") or {}).get(key, value)) for key, value in DEFAULT_COSTS.items()}
        self.db.execute("INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (job_id, title, objective, "OPEN", as_money(data.get("budget_usd", 0)), as_money(data.get("customer_price_usd", data.get("budget_usd", 0))), dumps(criteria), dumps(policy), dumps(costs), str(data.get("evidence_class", "SYNTHETIC")), created, created))
        self._event("JOB_CREATED", job_id, {"title": title})
        if commit: self.db.commit()
        return self.job(job_id)

    def _job(self, row: sqlite3.Row) -> dict[str, Any]:
        return {"id": row["id"], "title": row["title"], "objective": row["objective"], "status": row["status"], "budget_usd": row["budget_usd"], "customer_price_usd": row["customer_price_usd"], "acceptance_criteria": loads(row["criteria"], []), "worker_policy": loads(row["policy"], {}), "evidence_class": row["evidence_class"], "created_at": row["created_at"], "updated_at": row["updated_at"]}

    def jobs(self) -> list[dict[str, Any]]:
        return [self._job(row) for row in self.db.execute("SELECT * FROM jobs ORDER BY created_at DESC")]

    def job(self, job_id: str) -> dict[str, Any]:
        row = self.db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row is None: raise KeyError("job not found")
        result = self._job(row)
        result["applications"] = self.applications(job_id)
        result["runs"] = [self._run(row) for row in self.db.execute("SELECT * FROM runs WHERE job_id=? ORDER BY created_at DESC", (job_id,))]
        result["economics"] = self.economics(job_id)
        return result

    def create_worker(self, data: dict[str, Any]) -> dict[str, Any]:
        name, worker_type = str(data.get("name", "")).strip(), str(data.get("worker_type", "")).strip()
        if not name or worker_type not in {"human", "agent", "swarm"}: raise ValueError("name and valid worker_type are required")
        worker_id = str(data.get("id") or f"WORKER-{uuid.uuid4().hex[:10].upper()}")
        self.db.execute("INSERT INTO workers VALUES(?,?,?,?,?,?,?)", (worker_id, name, worker_type, dumps(data.get("capabilities", [])), dumps(data.get("evaluation", {})), "AVAILABLE", utc_now()))
        self._event("WORKER_REGISTERED", worker_id, {"worker_type": worker_type})
        self.db.commit()
        return self.worker(worker_id)

    def worker(self, worker_id: str) -> dict[str, Any]:
        row = self.db.execute("SELECT * FROM workers WHERE id=?", (worker_id,)).fetchone()
        if row is None: raise KeyError("worker not found")
        return {"id": row["id"], "name": row["name"], "worker_type": row["worker_type"], "capabilities": loads(row["capabilities"], []), "evaluation": loads(row["evaluation"], {}), "availability": row["availability"]}

    def workers(self) -> list[dict[str, Any]]:
        return [self.worker(row["id"]) for row in self.db.execute("SELECT id FROM workers ORDER BY name")]

    def apply(self, job_id: str, data: dict[str, Any]) -> dict[str, Any]:
        self.job(job_id); worker_id = str(data.get("worker_id", "")); self.worker(worker_id)
        application_id = f"APP-{uuid.uuid4().hex[:10].upper()}"
        self.db.execute("INSERT INTO applications VALUES(?,?,?,?,?,?,?,?,?)", (application_id, job_id, worker_id, str(data.get("proposal", "")).strip(), as_money(data.get("bid_usd", 0)), "PENDING", None, utc_now(), utc_now()))
        self.db.execute("UPDATE jobs SET status='APPLIED', updated_at=? WHERE id=? AND status='OPEN'", (utc_now(), job_id))
        self._event("APPLICATION_SUBMITTED", application_id, {"job_id": job_id, "worker_id": worker_id}); self.db.commit()
        return next(item for item in self.applications(job_id) if item["id"] == application_id)

    def applications(self, job_id: str) -> list[dict[str, Any]]:
        rows = self.db.execute("SELECT a.*,w.name,w.worker_type,w.capabilities FROM applications a JOIN workers w ON w.id=a.worker_id WHERE a.job_id=? ORDER BY a.created_at", (job_id,))
        return [{"id": row["id"], "job_id": row["job_id"], "worker_id": row["worker_id"], "worker_name": row["name"], "worker_type": row["worker_type"], "capabilities": loads(row["capabilities"], []), "proposal": row["proposal"], "bid_usd": row["bid_usd"], "status": row["status"], "reviewer": row["reviewer"], "created_at": row["created_at"]} for row in rows]

    def decide_application(self, application_id: str, status: str, reviewer: str) -> dict[str, Any]:
        if status not in {"SHORTLISTED", "SELECTED", "REJECTED"} or not reviewer.strip(): raise ValueError("named human reviewer and valid decision are required")
        row = self.db.execute("SELECT * FROM applications WHERE id=?", (application_id,)).fetchone()
        if row is None: raise KeyError("application not found")
        self.db.execute("UPDATE applications SET status=?, reviewer=?, updated_at=? WHERE id=?", (status, reviewer.strip(), utc_now(), application_id))
        if status == "SELECTED":
            self.db.execute("UPDATE applications SET status='REJECTED', reviewer=?, updated_at=? WHERE job_id=? AND id<>? AND status IN('PENDING','SHORTLISTED')", (reviewer.strip(), utc_now(), row["job_id"], application_id))
            self.db.execute("UPDATE jobs SET status='IN_PROGRESS', updated_at=? WHERE id=?", (utc_now(), row["job_id"]))
        self._event("APPLICATION_DECIDED", application_id, {"status": status, "reviewer": reviewer.strip()}); self.db.commit(); return self.job(row["job_id"])

    def route(self, job_id: str) -> dict[str, Any]:
        job = self.job(job_id); preferred = "swarm" if job["worker_policy"].get("requires_independent_verifier") and len(job["acceptance_criteria"]) >= 2 else "agent"
        if preferred not in job["worker_policy"]["allowed_worker_types"]: preferred = job["worker_policy"]["allowed_worker_types"][0]
        options = job["worker_policy"]["allowed_worker_types"]; probabilities = {item: (0.65 if item == preferred else round(0.35 / max(len(options) - 1, 1), 4)) for item in options}
        return {"model": "laya-compatible-local-router", "type": "choice", "selected": preferred, "options": options, "probabilities": probabilities, "human_approval_required": True}

    def launch(self, job_id: str) -> dict[str, Any]:
        job = self.job(job_id); decision = self.route(job_id); run_id = f"RUN-{uuid.uuid4().hex[:10].upper()}"
        tasks = [{"id": name, "status": "COMPLETED", "evidence": []} for name in ("intake", "execution", "independent-verifier")]
        evidence = [item["id"] for item in job["acceptance_criteria"] if item["id"] != "HUMAN_ACCEPTANCE"]
        self.db.execute("INSERT INTO runs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", (run_id, job_id, decision["selected"], dumps(decision), dumps(tasks), dumps(evidence), "NOT_RECORDED", "UNRESOLVED", dumps(["HUMAN_ACCEPTANCE_NOT_ESTABLISHED", "REQUIRED_EVIDENCE_GAP"]), 184, 12.0, utc_now(), utc_now()))
        self.db.execute("UPDATE jobs SET status='IN_REVIEW', updated_at=? WHERE id=?", (utc_now(), job_id)); self._event("SWARM_RUN_LAUNCHED", run_id, {"route": decision["selected"]}); self.db.commit(); return self.job(job_id)

    def accept(self, job_id: str, decision: str, reviewer: str) -> dict[str, Any]:
        if decision not in {"ACCEPTED", "REJECTED", "CORRECTION_REQUIRED"} or not reviewer.strip(): raise ValueError("named reviewer and valid acceptance decision are required")
        row = self.db.execute("SELECT * FROM runs WHERE job_id=? ORDER BY created_at DESC LIMIT 1", (job_id,)).fetchone()
        if row is None: raise ValueError("launch a run first")
        outcome = "ACCEPTED" if decision == "ACCEPTED" and "HUMAN_ACCEPTANCE" in loads(row["evidence"], []) else "UNRESOLVED"
        failures = [] if outcome == "ACCEPTED" else ["REQUIRED_EVIDENCE_GAP"] if decision == "ACCEPTED" else ["HUMAN_ACCEPTANCE_NOT_ESTABLISHED"]
        status = "ACCEPTED" if outcome == "ACCEPTED" else "UNRESOLVED" if decision == "REJECTED" else "IN_REVIEW"
        self.db.execute("UPDATE runs SET acceptance=?, outcome=?, failures=?, updated_at=? WHERE id=?", (decision, outcome, dumps(failures), utc_now(), row["id"]))
        self.db.execute("UPDATE jobs SET status=?, updated_at=? WHERE id=?", (status, utc_now(), job_id)); self._event("HUMAN_ACCEPTANCE_RECORDED", row["id"], {"decision": decision, "reviewer": reviewer.strip()}); self.db.commit(); return self.job(job_id)

    def _run(self, row: sqlite3.Row) -> dict[str, Any]:
        return {"id": row["id"], "route": row["route"], "decision": loads(row["decision"], {}), "tasks": loads(row["tasks"], []), "observed_evidence": loads(row["evidence"], []), "human_acceptance": row["acceptance"], "outcome": row["outcome"], "failure_codes": loads(row["failures"], []), "elapsed_seconds": row["elapsed_seconds"], "rework_cost_usd": row["rework_cost_usd"], "created_at": row["created_at"]}

    def economics(self, job_id: str) -> dict[str, Any]:
        row = self.db.execute("SELECT customer_price_usd,costs FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row is None: raise KeyError("job not found")
        costs = loads(row["costs"], {}); total = round(sum(float(costs.get(key, 0)) for key in ECONOMIC_COSTS), 2); price = round(float(row["customer_price_usd"]), 2); contribution = round(price - total, 2)
        return {"customer_price_usd": price, "costs": costs, "total_cost_usd": total, "contribution_margin_usd": contribution, "contribution_margin_pct": round((contribution / price * 100) if price else 0, 4), "cost_basis": "SYNTHETIC_OR_USER_DECLARED_ESTIMATE"}

    def create_evolution(self, data: dict[str, Any], commit: bool = True) -> dict[str, Any]:
        metrics, gates = data.get("metrics") or {}, data.get("gates") or {"min_first_pass_acceptance": 0.95, "max_rework_rate": 0.1, "max_cost_per_accepted_outcome_usd": 75}
        promoted = bool(metrics.get("holdout_passed")) and float(metrics.get("first_pass_acceptance", 0)) >= float(gates["min_first_pass_acceptance"]) and float(metrics.get("rework_rate", 1)) <= float(gates["max_rework_rate"]) and metrics.get("cost_per_accepted_outcome_usd") is not None and float(metrics["cost_per_accepted_outcome_usd"]) <= float(gates["max_cost_per_accepted_outcome_usd"])
        candidate_id = f"EVO-{uuid.uuid4().hex[:10].upper()}"
        self.db.execute("INSERT INTO evolution VALUES(?,?,?,?,?,?,?,?,?)", (candidate_id, str(data["version"]), data.get("parent_version"), str(data.get("change_type", "candidate")), dumps(data.get("benchmark_suite", [])), dumps(metrics), dumps(gates), "PROMOTED" if promoted else "BLOCKED", utc_now()))
        if commit: self.db.commit()
        return self.evolution(candidate_id)

    def evolution(self, candidate_id: str) -> dict[str, Any]:
        row = self.db.execute("SELECT * FROM evolution WHERE id=?", (candidate_id,)).fetchone()
        if row is None: raise KeyError("evolution candidate not found")
        return {"id": row["id"], "version": row["version"], "parent_version": row["parent_version"], "change_type": row["change_type"], "benchmark_suite": loads(row["suite"], []), "metrics": loads(row["metrics"], {}), "gates": loads(row["gates"], {}), "status": row["status"], "created_at": row["created_at"]}

    def evolutions(self) -> list[dict[str, Any]]:
        return [self.evolution(row["id"]) for row in self.db.execute("SELECT id FROM evolution ORDER BY created_at DESC")]
