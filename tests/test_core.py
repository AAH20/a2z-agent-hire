import unittest

from packages.oss.outcome_exchange.core import ExchangeDB
from packages.oss.outcome_exchange.failure_clinic import (
    COMMITTED,
    NOT_COMMITTED,
    UNRESOLVED,
    state_digest,
    verify_cloud_change,
)


class ExchangeCoreTests(unittest.TestCase):
    def test_failure_clinic_cloud_timeout_has_three_verdicts(self):
        intent_id = "intent-cloud-001"
        baseline = {"region_a": "absent", "region_b": "absent"}
        desired = {"region_a": "present", "region_b": "present"}

        committed = verify_cloud_change(
            intent_id=intent_id,
            desired_state=desired,
            baseline_state=baseline,
            local_state=desired,
            provider_state=desired,
            provider_receipt={"intent_id": intent_id, "state_digest": state_digest(desired)},
        )
        self.assertEqual(committed["verdict"], COMMITTED)

        not_committed = verify_cloud_change(
            intent_id=intent_id,
            desired_state=desired,
            baseline_state=baseline,
            local_state=baseline,
            provider_state=baseline,
            provider_receipt=None,
            absence_proven=True,
        )
        self.assertEqual(not_committed["verdict"], NOT_COMMITTED)

        unresolved = verify_cloud_change(
            intent_id=intent_id,
            desired_state=desired,
            baseline_state=baseline,
            local_state=desired,
            provider_state=None,
            provider_receipt=None,
            provider_read="TIMEOUT",
        )
        self.assertEqual(unresolved["verdict"], UNRESOLVED)

        divergence = verify_cloud_change(
            intent_id=intent_id,
            desired_state=desired,
            baseline_state=baseline,
            local_state=desired,
            provider_state=baseline,
            provider_receipt=None,
            absence_proven=False,
        )
        self.assertEqual(divergence["verdict"], UNRESOLVED)
        self.assertIn("LOCAL_PROVIDER_DIVERGENCE", divergence["failure_codes"])

    def test_job_board_hiring_swarm_acceptance_and_economics(self):
        db = ExchangeDB()
        job_id = db.jobs()[0]["id"]
        worker = next(item for item in db.workers() if item["worker_type"] == "swarm")
        application = db.apply(job_id, {"worker_id": worker["id"], "proposal": "Replay and verify the contract.", "bid_usd": 28})
        selected = db.decide_application(application["id"], "SELECTED", "named-human-reviewer")
        self.assertEqual(selected["status"], "IN_PROGRESS")
        launched = db.launch(job_id)
        self.assertEqual(launched["runs"][0]["outcome"], "UNRESOLVED")
        accepted = db.accept(job_id, "ACCEPTED", "accountable-owner")
        self.assertEqual(accepted["status"], "IN_REVIEW")
        self.assertEqual(accepted["runs"][0]["failure_codes"], ["REQUIRED_EVIDENCE_GAP"])
        self.assertEqual(db.economics(job_id)["contribution_margin_usd"], 13.5)
        db.close()

    def test_evolution_requires_holdout_and_gates(self):
        db = ExchangeDB()
        candidate = db.create_evolution({"version": "router-0.2.0", "parent_version": "router-0.1.0", "change_type": "routing-change", "benchmark_suite": ["synthetic-cloud-change-v1"], "metrics": {"first_pass_acceptance": 0.99, "rework_rate": 0.01, "cost_per_accepted_outcome_usd": 50, "holdout_passed": False}})
        self.assertEqual(candidate["status"], "BLOCKED")
        db.close()

    def test_hiring_decision_requires_named_human(self):
        db = ExchangeDB(); job_id = db.jobs()[0]["id"]; worker = db.workers()[0]
        app = db.apply(job_id, {"worker_id": worker["id"], "proposal": "proposal", "bid_usd": 10})
        with self.assertRaises(ValueError): db.decide_application(app["id"], "SELECTED", "")
        db.close()


if __name__ == "__main__":
    unittest.main()
