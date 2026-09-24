"""Explicit local import of Entity Continuity review-job drafts."""

import argparse
import json

from packages.oss.outcome_exchange.core import ExchangeDB
from packages.oss.outcome_exchange.entity_continuity import import_handoff
from entity_continuity.a2z_agent_hire import verify_handoff
from entity_continuity.engine import load_json


def main() -> int:
    parser = argparse.ArgumentParser(description="Import synthetic Entity Continuity review jobs")
    parser.add_argument("bundle")
    parser.add_argument("--case", required=True)
    parser.add_argument("--pack", required=True)
    parser.add_argument("--receipt", required=True)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--db", required=True, help="Local A2Z Agent Hire SQLite path")
    args = parser.parse_args()
    try:
        with open(args.bundle, encoding="utf-8") as stream:
            bundle = json.load(stream)
        verify_handoff(load_json(args.case), load_json(args.pack), args.as_of,
                       load_json(args.receipt), bundle)
        db = ExchangeDB(args.db)
        try:
            result = import_handoff(db, bundle)
        finally:
            db.close()
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        parser.exit(2, f"error: {exc}\n")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
