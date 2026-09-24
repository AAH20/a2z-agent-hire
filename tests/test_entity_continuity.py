import copy
import sqlite3
import unittest

from packages.oss.outcome_exchange.core import ECONOMIC_COSTS, ExchangeDB
from packages.oss.outcome_exchange.entity_continuity import _digest, import_handoff, preview_handoff


def fixture(count=1):
    jobs = []
    for index in range(count):
        source = {"entity_id": "synthetic-entity", "obligation_id": f"synthetic-rule:event-{index}",
                  "receipt_digest": "a" * 64, "jurisdiction": "SYNTHETIC", "rule_id": "synthetic-rule",
                  "event_id": f"event-{index}", "due_at": "2026-10-01", "status": "open",
                  "evidence_status": "missing"}
        source_key = {key: source[key] for key in ("entity_id", "obligation_id", "receipt_digest")}
        job_id = "JOB-EC-" + _digest(source_key)[:16].upper()
        criteria = [{"id": key, "description": key, "required": True}
                    for key in ("SOURCE_RECONCILED", "EVIDENCE_GAPS", "HUMAN_ACCEPTANCE")]
        job = {"id": job_id, "title": "Review synthetic obligation", "objective": "Evidence-gap review only",
               "budget_usd": 0, "customer_price_usd": 0,
               "economics": {key: 0 for key in ECONOMIC_COSTS},
               "acceptance_criteria": criteria,
               "worker_policy": {"allowed_worker_types": ["human"], "requires_independent_verifier": True},
               "evidence_class": "SYNTHETIC"}
        jobs.append({"source": source, "a2z_job": job})
    body = {"schema_version": "entity-continuity.a2z-agent-hire.v2",
            "scope": "SYNTHETIC_REVIEW_DRAFTS_ONLY_NO_EXTERNAL_ACTION", "as_of": "2026-09-23",
            "source_receipt_digest": "a" * 64, "jobs": jobs}
    return {**body, "bundle_digest": _digest(body)}


def refresh(bundle):
    bundle["bundle_digest"] = _digest({key: value for key, value in bundle.items() if key != "bundle_digest"})
    return bundle


class EntityContinuityImportTests(unittest.TestCase):
    def test_preview_and_idempotent_import_record_source_and_zero_costs(self):
        db = ExchangeDB(seed_demo=False)
        try:
            self.assertEqual(db.jobs(), [])
            self.assertEqual(db.workers(), [])
            bundle = fixture(2)
            preview = preview_handoff(bundle, verified_bundle_digest=bundle["bundle_digest"])
            self.assertEqual(preview["job_count"], 2)
            first = import_handoff(db, bundle, verified_bundle_digest=bundle["bundle_digest"])
            second = import_handoff(db, bundle, verified_bundle_digest=bundle["bundle_digest"])
            self.assertEqual(first["created"], preview["job_ids"])
            self.assertEqual(set(second["unchanged"]), set(first["created"]))
            self.assertEqual(db.db.execute("SELECT COUNT(*) FROM entity_handoffs").fetchone()[0], 1)
            self.assertEqual(db.db.execute("SELECT COUNT(*) FROM entity_handoff_jobs").fetchone()[0], 2)
            self.assertEqual(db.economics(first["created"][0])["total_cost_usd"], 0)
            with self.assertRaises(sqlite3.IntegrityError):
                db.db.execute("DELETE FROM jobs WHERE id=?", (first["created"][0],))
        finally:
            db.close()

    def test_tampered_nonhuman_or_unverified_draft_rejected(self):
        db = ExchangeDB(seed_demo=False)
        try:
            bundle = fixture()
            changed = copy.deepcopy(bundle)
            changed["jobs"][0]["a2z_job"]["objective"] = "Changed"
            with self.assertRaisesRegex(ValueError, "digest"):
                import_handoff(db, changed, verified_bundle_digest=bundle["bundle_digest"])
            changed = copy.deepcopy(bundle)
            changed["jobs"][0]["a2z_job"]["worker_policy"]["allowed_worker_types"] = ["agent"]
            refresh(changed)
            with self.assertRaisesRegex(ValueError, "human-review"):
                import_handoff(db, changed, verified_bundle_digest=changed["bundle_digest"])
            changed = copy.deepcopy(bundle)
            changed["jobs"][0]["a2z_job"]["economics"]["worker_payout_usd"] = 20
            refresh(changed)
            with self.assertRaisesRegex(ValueError, "demo costs"):
                import_handoff(db, changed, verified_bundle_digest=changed["bundle_digest"])
            with self.assertRaisesRegex(ValueError, "source verification"):
                import_handoff(db, bundle, verified_bundle_digest="b" * 64)
            changed = copy.deepcopy(bundle)
            changed["schema_version"] = "entity-continuity.a2z-agent-hire.v1"
            refresh(changed)
            with self.assertRaisesRegex(ValueError, "unsupported"):
                import_handoff(db, changed, verified_bundle_digest=changed["bundle_digest"])
            changed = copy.deepcopy(bundle)
            changed["jobs"][0]["a2z_job"]["acceptance_criteria"][0]["id"] = {"bad": "type"}
            refresh(changed)
            with self.assertRaisesRegex(ValueError, "acceptance criteria"):
                import_handoff(db, changed, verified_bundle_digest=changed["bundle_digest"])
        finally:
            db.close()

    def test_failed_second_job_rolls_back_entire_bundle(self):
        db = ExchangeDB(seed_demo=False)
        try:
            bundle = fixture(2)
            original = db.create_job
            calls = 0

            def fail_second(data, commit=True):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise ValueError("simulated write failure")
                return original(data, commit=commit)

            db.create_job = fail_second
            with self.assertRaisesRegex(ValueError, "simulated"):
                import_handoff(db, bundle, verified_bundle_digest=bundle["bundle_digest"])
            self.assertEqual(db.db.execute("SELECT COUNT(*) FROM entity_handoffs").fetchone()[0], 0)
            self.assertEqual(db.db.execute("SELECT COUNT(*) FROM entity_handoff_jobs").fetchone()[0], 0)
            for item in bundle["jobs"]:
                self.assertIsNone(db.db.execute("SELECT 1 FROM jobs WHERE id=?", (item["a2z_job"]["id"],)).fetchone())
        finally:
            db.close()

    def test_reimport_detects_changed_stored_contract(self):
        db = ExchangeDB(seed_demo=False)
        try:
            bundle = fixture()
            import_handoff(db, bundle, verified_bundle_digest=bundle["bundle_digest"])
            job_id = bundle["jobs"][0]["a2z_job"]["id"]
            db.db.execute("UPDATE jobs SET objective=? WHERE id=?", ("changed", job_id))
            db.db.commit()
            with self.assertRaisesRegex(ValueError, "contract differs"):
                import_handoff(db, bundle, verified_bundle_digest=bundle["bundle_digest"])
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
