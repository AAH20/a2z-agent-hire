"""Explicit local import of Entity Continuity review-job drafts."""

import argparse
import json
import sqlite3

from packages.oss.outcome_exchange.core import ExchangeDB
from packages.oss.outcome_exchange.entity_continuity import import_handoff, preview_handoff


def main() -> int:
    parser = argparse.ArgumentParser(description="Import synthetic Entity Continuity review jobs")
    parser.add_argument("bundle")
    parser.add_argument("--case", required=True)
    parser.add_argument("--pack", required=True)
    parser.add_argument("--receipt", required=True)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--db", help="Local A2Z Agent Hire SQLite path; required unless --dry-run")
    parser.add_argument("--dry-run", action="store_true", help="Verify and preview without opening a database")
    args = parser.parse_args()
    try:
        try:
            from entity_continuity.a2z_agent_hire import verify_handoff
            from entity_continuity.engine import load_json
        except ImportError as exc:
            raise ValueError("Entity Continuity must be installed or on PYTHONPATH to verify source files") from exc
        with open(args.bundle, encoding="utf-8") as stream:
            bundle = json.load(stream)
        verified = verify_handoff(load_json(args.case), load_json(args.pack), args.as_of,
                                  load_json(args.receipt), bundle)
        if args.dry_run:
            result = preview_handoff(bundle, verified_bundle_digest=verified["bundle_digest"])
        else:
            if not args.db:
                raise ValueError("--db is required unless --dry-run is used")
            db = ExchangeDB(args.db, seed_demo=False)
            try:
                result = import_handoff(db, bundle, verified_bundle_digest=verified["bundle_digest"])
            finally:
                db.close()
    except (ValueError, OSError, sqlite3.Error, json.JSONDecodeError) as exc:
        parser.exit(2, f"error: {exc}\n")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
