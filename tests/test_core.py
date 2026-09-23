import unittest

from packages.oss.outcome_exchange.core import ExchangeDB


class ExchangeCoreTests(unittest.TestCase):
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
