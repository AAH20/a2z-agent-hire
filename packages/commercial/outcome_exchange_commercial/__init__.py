"""Commercial extension contracts only.

The OSS repository intentionally contains interfaces and policy boundaries, not
private tenant data, payment credentials, proprietary evaluation packs, or
hosted-service implementation.
"""

from typing import Protocol


class CommercialBoundary(Protocol):
    def authorize_tenant(self, tenant_id: str, action: str) -> bool: ...
    def price_job(self, job_contract: dict) -> dict: ...
    def settle_accepted_outcome(self, outcome_id: str) -> dict: ...
