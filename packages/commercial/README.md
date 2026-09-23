# Commercial layer boundary

This package is intentionally an interface boundary, not a disguised
commercial implementation. The hosted layer should own:

- tenant isolation, SSO, RBAC, consent, and audit retention;
- private evaluation packs, proprietary routing weights, and benchmark data;
- payment/escrow, tax, fraud, refunds, and worker settlement;
- enterprise connectors and durable workflow infrastructure;
- contractual SLAs, support, and privacy operations.

The OSS runtime must remain useful without these services. No API key,
customer record, negotiated rate, private benchmark, or payment secret belongs
in this repository.
