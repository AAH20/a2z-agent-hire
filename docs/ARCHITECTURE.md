# Architecture and product boundary

## Monorepo layout

```text
apps/
  api/       dependency-free HTTP API and local serving entrypoint
  web/       local dashboard UI
packages/
  oss/       contracts, SQLite reference runtime, deterministic replay
  commercial/extension interfaces only; no private implementation or secrets
protocols/   versioned JSON contracts
fixtures/    synthetic-only examples
tests/       OSS runtime tests
```

## OSS runtime

The OSS runtime owns the portable job contract, worker/application records,
human-controlled hiring state machine, typed routing decision, replayable swarm
tasks, acceptance/evidence state, evolution promotion gate, and unit-economics
calculation. It is framework-neutral and local-first.

The routing decision has `choice`, `options`, `probabilities`, and an explicit
`human_approval_required` flag. This is a compatibility seam for Laya/Jev-like
decision models, not a claim that the OSS runtime ships those weights.

The swarm is represented as a replayable task graph. A real adapter may later
connect workers, but the acceptance verifier remains independent of the worker
that produced the result.

## Commercial control plane

The commercial product should be a separate deployable and separate access
boundary. It may implement tenant identity, private benchmark packs, policy
versioning, hosted orchestration, connectors, payments/escrow, tax/fraud,
durable workflows, enterprise retention, audit exports, and support. It should
consume the OSS contracts instead of forking their meaning.

Do not put private customer data, protected employment attributes, payment
secrets, proprietary evaluation weights, or negotiated rates in the OSS repo.

## Hiring safety boundary

The reference system does not autonomously hire or reject people. It records
applications and evaluation evidence, then requires a named human for
shortlisting, selection, rejection, and final acceptance. A production system
needs legal review, consent, anti-discrimination controls, explainability,
appeal handling, retention controls, and an independent security review.

## Unit economics

```text
contribution margin = customer price
  - worker payout
  - model cost
  - compute cost
  - human review
  - payment fees
  - support reserve
  - rework reserve
```

The product metric is cost per accepted outcome, not cost per completed task.
An unresolved or rejected outcome must not be counted as an accepted success.
