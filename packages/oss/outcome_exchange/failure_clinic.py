"""Small, dependency-free synthetic failure-clinic verifiers."""

from __future__ import annotations

import hashlib
import json
from typing import Any


COMMITTED = "COMMITTED"
NOT_COMMITTED = "NOT_COMMITTED"
UNRESOLVED = "UNRESOLVED"


def state_digest(state: dict[str, Any] | None) -> str | None:
    """Return a stable digest for a provider or local state snapshot."""

    if state is None:
        return None
    encoded = json.dumps(state, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def verify_cloud_change(
    *,
    intent_id: str,
    desired_state: dict[str, Any],
    baseline_state: dict[str, Any],
    local_state: dict[str, Any] | None,
    provider_state: dict[str, Any] | None,
    provider_receipt: dict[str, Any] | None,
    provider_read: str = "AVAILABLE",
    absence_proven: bool = False,
) -> dict[str, Any]:
    """Verify a Terraform-like change without trusting the executor's claim.

    The provider read is treated as an observation, not as permission to
    invent a receipt. A local/provider mismatch is deliberately unresolved:
    reconciliation must explain the divergence before a retry or acceptance.
    """

    local_digest = state_digest(local_state)
    provider_digest = state_digest(provider_state)
    result = {
        "intent_id": intent_id,
        "verdict": UNRESOLVED,
        "local_state_digest": local_digest,
        "provider_state_digest": provider_digest,
        "divergence": local_digest != provider_digest,
        "failure_codes": [],
    }

    if provider_read != "AVAILABLE":
        result["failure_codes"] = ["PROVIDER_STATE_UNAVAILABLE"]
        return result

    if absence_proven and provider_state == baseline_state:
        result["verdict"] = NOT_COMMITTED
        return result

    receipt_matches = bool(
        provider_receipt
        and provider_receipt.get("intent_id") == intent_id
        and provider_receipt.get("state_digest") == provider_digest
    )
    if provider_state == desired_state and receipt_matches and not result["divergence"]:
        result["verdict"] = COMMITTED
        return result

    if provider_state != desired_state:
        result["failure_codes"].append("POSTCONDITION_MISMATCH")
    if not receipt_matches:
        result["failure_codes"].append("RECEIPT_GAP")
    if result["divergence"]:
        result["failure_codes"].append("LOCAL_PROVIDER_DIVERGENCE")
    return result
