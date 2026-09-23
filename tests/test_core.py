import unittest
import math

from packages.oss.outcome_exchange.core import ExchangeDB, as_money
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
        self.assertEqual(launched["runs"][0]["observed_evidence"], [])
        accepted = db.accept(job_id, "ACCEPTED", "accountable-owner")
        self.assertEqual(accepted["status"], "IN_REVIEW")
        self.assertEqual(accepted["runs"][0]["failure_codes"], ["REQUIRED_EVIDENCE_GAP"])
        self.assertEqual(db.economics(job_id)["contribution_margin_usd"], 13.5)
        db.close()

    def test_explicit_evidence_and_named_acceptance_can_finish_a_run(self):
        db = ExchangeDB()
        job_id = db.jobs()[0]["id"]
        worker = next(item for item in db.workers() if item["worker_type"] == "swarm")
        application = db.apply(job_id, {"worker_id": worker["id"], "proposal": "review", "bid_usd": 28})
        db.decide_application(application["id"], "SELECTED", "human-selector")
        run = db.launch(job_id)["runs"][0]
        for criterion in ("PLAN_DIGEST", "SECURITY_EVIDENCE"):
            with self.assertRaises(ValueError):
                db.record_evidence(run["id"], criterion, worker["id"], "a" * 64)
            db.record_evidence(run["id"], criterion, "independent-reviewer", "a" * 64)
        accepted = db.accept(job_id, "ACCEPTED", "accountable-owner")
        self.assertEqual(accepted["status"], "ACCEPTED")
        self.assertEqual(accepted["runs"][0]["outcome"], "ACCEPTED")
        self.assertEqual(len(accepted["runs"][0]["observed_evidence"]), 2)
        with self.assertRaises(ValueError):
            db.accept(job_id, "ACCEPTED", "accountable-owner")
        db.close()

    def test_launch_requires_human_selection_and_single_route_is_normalized(self):
        db = ExchangeDB()
        job_id = db.jobs()[0]["id"]
        with self.assertRaises(ValueError):
            db.launch(job_id)
        one = db.create_job({"title": "Human task", "objective": "Review fixture", "budget_usd": 10,
                             "acceptance_criteria": [{"id": "HUMAN_ACCEPTANCE", "required": True}],
                             "worker_policy": {"allowed_worker_types": ["human"]}})
        self.assertEqual(db.route(one["id"])["probabilities"], {"human": 1.0})
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

    def test_job_list_has_dashboard_details_and_single_selection(self):
        db = ExchangeDB()
        job_id = db.jobs()[0]["id"]
        workers = db.workers()[:2]
        apps = [db.apply(job_id, {"worker_id": worker["id"], "proposal": "review", "bid_usd": 10})
                for worker in workers]
        self.assertEqual(len(db.jobs()[0]["applications"]), 2)
        selected = db.decide_application(apps[0]["id"], "SELECTED", "human-selector")
        selected_worker = next(item for item in selected["applications"] if item["status"] == "SELECTED")
        self.assertEqual(db.route(job_id)["selected"], selected_worker["worker_type"])
        with self.assertRaises(ValueError):
            db.decide_application(apps[1]["id"], "SELECTED", "second-selector")
        with self.assertRaises(ValueError):
            db.apply(job_id, {"worker_id": workers[1]["id"], "proposal": "late", "bid_usd": 10})
        db.close()

    def test_invalid_money_and_disallowed_worker_are_rejected(self):
        for value in (math.nan, math.inf, -1):
            with self.assertRaises(ValueError):
                as_money(value)
        db = ExchangeDB()
        job = db.create_job({"title": "Human review", "objective": "Review",
                             "budget_usd": 10,
                             "acceptance_criteria": [{"id": "HUMAN_ACCEPTANCE", "required": True}],
                             "worker_policy": {"allowed_worker_types": ["human"]}})
        agent = next(item for item in db.workers() if item["worker_type"] == "agent")
        with self.assertRaises(ValueError):
            db.apply(job["id"], {"worker_id": agent["id"], "bid_usd": 10})
        db.close()


if __name__ == "__main__":
    unittest.main()
