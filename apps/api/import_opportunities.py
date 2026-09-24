"""Import one public Lever company board into the local reference database."""

from __future__ import annotations

import argparse
import json

from packages.oss.outcome_exchange.core import ExchangeDB


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh one public Lever job board")
    parser.add_argument("--db", default="a2z-agent-hire.db")
    parser.add_argument("--site", required=True, help="Employer's Lever board slug")
    parser.add_argument("--region", choices=("global", "eu"), default="global")
    parser.add_argument("--max-pages", type=int, default=20)
    args = parser.parse_args()
    db = ExchangeDB(args.db)
    try:
        result = db.opportunities.refresh_lever(args.site, region=args.region, max_pages=args.max_pages)
        print(json.dumps(result, indent=2, sort_keys=True))
    finally:
        db.close()


if __name__ == "__main__":
    main()
