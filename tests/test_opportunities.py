import unittest
from datetime import datetime, timedelta, timezone

from packages.oss.outcome_exchange.core import ExchangeDB
from packages.oss.outcome_exchange.opportunities import freshness


def page(*ids):
    return [{"id": item, "text": f"Platform Engineer {item}",
             "categories": {"location": "Remote"}} for item in ids]


class OpportunityTests(unittest.TestCase):
    def setUp(self):
        self.db = ExchangeDB()

    def tearDown(self):
        self.db.close()

    def test_refresh_deduplicates_preserves_id_and_closes_only_after_complete_scan(self):
        store = self.db.opportunities
        first = store.refresh_lever("example", fetch_page=lambda *_: page("a", "b"))
        self.assertEqual(first["count"], 2)
        rows = store.list()
        self.assertEqual({row["freshness"] for row in rows}, {"FRESH"})
        ids = {row["external_id"]: row["id"] for row in rows}
        self.assertEqual(rows[0]["source_url"].split("/")[2], "jobs.lever.co")

        second = store.refresh_lever("example", fetch_page=lambda *_: page("b", "c"))
        self.assertEqual(second["closed_count"], 0)
        self.assertEqual(len(store.list()), 3)
        self.assertEqual(next(row for row in store.list() if row["external_id"] == "a")["missing_count"], 1)
        self.assertEqual(next(row for row in store.list() if row["external_id"] == "a")["freshness"], "MISSING_ONCE")
        third = store.refresh_lever("example", fetch_page=lambda *_: page("b", "c"))
        self.assertEqual(third["closed_count"], 1)
        self.assertEqual(len(store.list()), 2)
        self.assertEqual(store.list("CLOSED")[0]["id"], ids["a"])
        self.assertEqual(next(row for row in store.list() if row["external_id"] == "b")["id"], ids["b"])
        self.assertEqual(store.refresh_lever("example", fetch_page=lambda *_: page("b", "c"))["closed_count"], 0)

        store.refresh_lever("example", fetch_page=lambda *_: page("a", "b", "c"))
        self.assertEqual(store.list("CLOSED"), [])
        self.assertEqual(next(row for row in store.list() if row["external_id"] == "a")["id"], ids["a"])

    def test_failed_or_partial_refresh_cannot_close_known_posting(self):
        store = self.db.opportunities
        store.refresh_lever("example", fetch_page=lambda *_: page("a"))
        with self.assertRaises(RuntimeError):
            store.refresh_lever("example", fetch_page=lambda *_: (_ for _ in ()).throw(RuntimeError("timeout")))
        self.assertEqual(len(store.list()), 1)
        with self.assertRaises(ValueError):
            store.refresh_lever("example", max_pages=1, fetch_page=lambda *_: page(*range(100)))
        self.assertEqual(len(store.list()), 1)

    def test_local_tracking_and_freshness(self):
        store = self.db.opportunities
        store.refresh_lever("example", region="eu", fetch_page=lambda *_: page("a"))
        item = store.list()[0]
        self.assertIn("jobs.eu.lever.co", item["source_url"])
        tracked = store.track(item["id"], "APPLIED", "Sent direct application",
                              "2026-10-01T10:00:00+02:00")
        self.assertEqual(tracked["follow_up_at"], "2026-10-01T08:00:00+00:00")
        self.assertEqual(store.tracks()[0]["status"], "APPLIED")
        with self.assertRaises(ValueError):
            store.track(item["id"], "APPLIED", follow_up_at="tomorrow")
        with self.assertRaises(KeyError):
            store.track("missing", "SAVED")

        ref = datetime.now(timezone.utc)
        self.assertEqual(freshness((ref - timedelta(hours=25)).isoformat(), "ACTIVE", ref), "AGING")
        self.assertEqual(freshness((ref - timedelta(hours=73)).isoformat(), "ACTIVE", ref), "STALE")
        self.assertEqual(freshness(ref.isoformat(), "CLOSED", ref), "CLOSED")

    def test_slug_and_bad_postings_are_rejected_before_writes(self):
        store = self.db.opportunities
        with self.assertRaises(ValueError):
            store.refresh_lever("../private", fetch_page=lambda *_: [])
        with self.assertRaises(ValueError):
            store.refresh_lever("example", fetch_page=lambda *_: [{"id": "x"}])
        with self.assertRaises(ValueError):
            store.refresh_lever("example", fetch_page=lambda *_: page("a", "a"))
        self.assertEqual(store.list(), [])


if __name__ == "__main__":
    unittest.main()
