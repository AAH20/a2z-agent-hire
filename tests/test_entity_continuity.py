import copy
import unittest

from packages.oss.outcome_exchange.core import ExchangeDB
from packages.oss.outcome_exchange.entity_continuity import _digest, import_handoff


def fixture():
    source = {"entity_id": "synthetic-entity", "obligation_id": "synthetic-rule:event-1",
              "receipt_digest": "a" * 64}
    job_id = "JOB-EC-" + _digest(source)[:16].upper()
    job = {"id": job_id, "title": "Review synthetic obligation", "objective": "Evidence-gap review only",
           "budget_usd": 0, "customer_price_usd": 0,
           "acceptance_criteria": [{"id": "HUMAN_ACCEPTANCE", "description": "Human review", "required": True}],
           "worker_policy": {"allowed_worker_types": ["human"], "requires_independent_verifier": True},
           "evidence_class": "SYNTHETIC"}
    body = {"schema_version": "entity-continuity.a2z-agent-hire.v1",
            "scope": "SYNTHETIC_REVIEW_DRAFTS_ONLY_NO_EXTERNAL_ACTION", "as_of": "2026-09-23",
            "source_receipt_digest": "a" * 64, "jobs": [{"source": source, "a2z_job": job}]}
    return {**body, "bundle_digest": _digest(body)}


class EntityContinuityImportTests(unittest.TestCase):
    def test_import_is_idempotent(self):
        db = ExchangeDB()
        try:
            bundle = fixture()
            first = import_handoff(db, bundle)
            second = import_handoff(db, bundle)
            self.assertEqual(first["created"], [bundle["jobs"][0]["a2z_job"]["id"]])
            self.assertEqual(second["unchanged"], first["created"])
        finally:
            db.close()

    def test_tampered_or_nonhuman_draft_rejected(self):
        db = ExchangeDB()
        try:
            bundle = fixture()
            altered = copy.deepcopy(bundle)
            altered["jobs"][0]["a2z_job"]["objective"] = "Changed"
            with self.assertRaisesRegex(ValueError, "digest"):
                import_handoff(db, altered)
            altered["bundle_digest"] = _digest({k: v for k, v in altered.items() if k != "bundle_digest"})
            altered["jobs"][0]["a2z_job"]["worker_policy"]["allowed_worker_types"] = ["agent"]
            altered["bundle_digest"] = _digest({k: v for k, v in altered.items() if k != "bundle_digest"})
            with self.assertRaisesRegex(ValueError, "human-review"):
                import_handoff(db, altered)
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
