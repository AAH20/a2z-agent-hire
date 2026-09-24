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
    parser.add_argument("--intake-manifest", help="Optional synthetic read-only intake manifest")
    parser.add_argument("--intake-record", help="Optional exact-source intake record")
    parser.add_argument("--db", help="Local A2Z Agent Hire SQLite path; required unless --dry-run")
    parser.add_argument("--dry-run", action="store_true", help="Verify and preview without opening a database")
    args = parser.parse_args()
    try:
        try:
            from entity_continuity.a2z_agent_hire import verify_handoff
            from entity_continuity.engine import read_json_document
            from entity_continuity.read_only_intake import verify_intake
        except ImportError as exc:
            raise ValueError("Entity Continuity must be installed or on PYTHONPATH to verify source files") from exc
        bundle, _ = read_json_document(args.bundle)
        case, case_digest = read_json_document(args.case)
        pack, pack_digest = read_json_document(args.pack)
        receipt, _ = read_json_document(args.receipt)
        verified = verify_handoff(case, pack, args.as_of, receipt, bundle)
        if bool(args.intake_manifest) != bool(args.intake_record):
            raise ValueError("--intake-manifest and --intake-record must be supplied together")
        intake_provenance = None
        if args.intake_manifest:
            manifest, _ = read_json_document(args.intake_manifest, max_bytes=16_384)
            record, _ = read_json_document(args.intake_record)
            verify_intake(manifest, case, pack, args.as_of, case_digest, pack_digest, record)
            if record["receipt"] != receipt or record["entity_id"] != receipt["entity_id"]:
                raise ValueError("intake record does not match the handoff receipt and entity")
            intake_provenance = {"intake_record_digest": record["record_digest"],
                                 "workspace_id": record["workspace_id"]}
        if args.dry_run:
            result = preview_handoff(bundle, verified_bundle_digest=verified["bundle_digest"],
                                     intake_provenance=intake_provenance)
        else:
            if not args.db:
                raise ValueError("--db is required unless --dry-run is used")
            db = ExchangeDB(args.db, seed_demo=False)
            try:
                result = import_handoff(db, bundle, verified_bundle_digest=verified["bundle_digest"],
                                        intake_provenance=intake_provenance)
            finally:
                db.close()
    except (ValueError, OSError, sqlite3.Error, json.JSONDecodeError) as exc:
        parser.exit(2, f"error: {exc}\n")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
