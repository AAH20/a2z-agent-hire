# Entity Continuity import: local operations

A2Z Agent Hire v0.2 accepts **v2 synthetic human-review bundles** exported by [Entity Continuity](https://github.com/AAH20/entity-continuity). This is a local, offline import. It is not a provider marketplace, legal-work order, employment decision, or filing channel.

## Import contract

```mermaid
flowchart LR
  C["Exact case + pack + date"] --> V["Entity Continuity receipt verifier"]
  R["Receipt"] --> V
  B["v2 bundle"] --> V
  V --> P["Dry-run preview"]
  V --> G["Strict A2Z contract gate"]
  G --> T["Single SQLite transaction"]
  T --> M["Handoff manifest and source mapping"]
  T --> J["Zero-dollar human-review jobs"]
  M --> I["Idempotent replay check"]
  J --> I
  classDef record fill:#111827,stroke:#22D3EE,stroke-width:2px,color:#FFFFFF;
  class R,B,M,J record;
```

The importer checks the exact source files, v2 schema, dates, digest, stable job IDs, human-only worker policy, three required acceptance criteria and seven explicit zero-cost fields. It inserts the manifest, foreign-key-bound mappings and jobs in one transaction. A second import returns the recorded job IDs. A changed or incomplete stored job stops replay. The digests bind local bytes; they do not authenticate the customer, reviewer or document origin.

## Reproduce with sibling checkouts

Generate a receipt and bundle in Entity Continuity as described in its [integration guide](https://github.com/AAH20/entity-continuity/blob/main/docs/A2Z_AGENT_HIRE_INTEGRATION.md). Then, from this repository:

```bash
PYTHONPATH=.:../entity-continuity/src python3 -m apps.api.import_entity_continuity \
  /tmp/entity-a2z-bundle.json \
  --case ../entity-continuity/examples/egypt-to-us-synthetic-case.json \
  --pack ../entity-continuity/examples/us-de-synthetic-pack.json \
  --receipt /tmp/entity-receipt.json --as-of 2026-09-23 --dry-run
```

After reviewing the IDs and scope, repeat with `--db /tmp/a2z-entity-demo.db` instead of `--dry-run`. To view the local board without demo workers or jobs:

```bash
python3 -m apps.api.server --db /tmp/a2z-entity-demo.db --no-demo-seed --port 8787
```

The server is loopback-only and unauthenticated. Use it only for local reference work. `--no-demo-seed` prevents fictional workers and the seeded cloud job from appearing in a clean database; it does not add production authentication.

## Version migration and recovery

The previous v1 handoff omitted explicit zero-cost fields. Re-export from Entity Continuity v0.4 to obtain v2. The v2 importer **rejects v1** rather than guessing economics. A v1 job already in a local database has no v2 manifest and causes a stable-ID conflict; use a separate clean demo database or plan a reviewed migration. Do not delete customer records to work around a conflict.

On an import failure, the transaction leaves no partial handoff jobs. Keep the original bundle and source files for investigation. Correct the source or contract and regenerate a new receipt and bundle; do not edit a digest by hand. A recorded bundle whose job content or mapping changed is rejected on replay.

## Pilot boundary

The local reference has no user authentication, tenant isolation, trusted source custody, qualified-provider verification, payment settlement, audit-log immutability or legal conclusion engine. Before a customer pilot, use private source storage, a named reviewer, consented and redacted records, an independent baseline, encrypted backups, deletion rules and a manual exception process. The [Entity Continuity pilot runbook](https://github.com/AAH20/entity-continuity/blob/main/docs/PILOT_READINESS.md) defines that scope. None of these controls is implied by a passing unit test.
