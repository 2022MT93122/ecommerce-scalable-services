# Business Rules and Code Mapping

This document formalizes the core business invariants for the E-Commerce Microservices system (BITS Pilani WILP - SEZG583).
Each rule is enforced at the database or transactional boundary and validated by automated tests and challenge scripts.

---

## Business Invariants Summary

| Rule ID | Invariant Title | Owning Service | Mechanism / Implementation | Verification Script / Test |
|---------|-----------------|----------------|----------------------------|----------------------------|
| **BR1** | **Stock Never Negative** | Inventory Service | Single atomic conditional `UPDATE products SET available = available - :qty WHERE id = :product_id AND available >= :qty RETURNING id, available;` | `scripts/concurrency.py`, `services/inventory/tests/test_business_rules.py` |
| **BR2** | **Confirmed Hold Cannot Be Released** | Inventory Service | State-machine constraint: `release` rejects holds in `CONFIRMED` status with `409 Conflict`. Restores stock only when transitioning from `HELD` to `RELEASED`. | `services/inventory/tests/test_business_rules.py` |
| **BR3** | **Duplicate Checkout Key Means One Order** | Order Service | Deduplication via `Idempotency-Key` header with unique database constraint. Replays stored terminal order. | `scripts/idempotency.py` |
| **BR4** | **Key With Different Payload Returns 409** | Order Service | Payload fingerprinting (SHA-256 of canonical JSON). Mismatched payload returns `409 Conflict`. | `scripts/idempotency.py` |
| **BR5** | **Payment Key Charges Once** | Payment Service | PostgreSQL unique index on `idempotency_key`. Concurrent duplicate charge returns recorded payment. | `services/payment/tests/` |
| **BR6** | **Notification Failure Cannot Cancel Paid Order** | Order / Notification | Asynchronous best-effort notification delivery. Downstream notification timeout/failure logs error without rolling back confirmed order. | `scripts/e2e.py` |

---

## Detailed Rule Specifications (Inventory Domain - Dr. Sunanda Pandita)

### BR1: Stock Never Negative (Atomic Conditional Reservation)
- **Problem Statement**: Under concurrent high-traffic bursts (e.g., flash sales), multiple threads reading stock before writing (`SELECT available ... IF available >= qty THEN UPDATE ...`) experience race conditions, causing stock overselling (stock < 0).
- **Enforcement Level**:
  1. Database Table Constraint: `CHECK (available >= 0)` on `products` table ensures the database physically rejects any negative stock value.
  2. Single SQL Statement Atomic Conditional Decrement:
     ```sql
     UPDATE products
     SET available = available - :quantity
     WHERE id = :product_id AND available >= :quantity
     RETURNING id, available;
     ```
  3. Row locking inside an explicit transaction ensures that if `RETURNING` produces no row, the operation aborts and immediately raises HTTP `409 Conflict` (`OUT_OF_STOCK`).
- **Idempotent Retry**: If the same `order_id` issues a reserve request again with identical parameters, the existing hold record is returned without decrementing stock a second time. If `order_id` is reused with different parameters, `409 Conflict` is returned.

### BR2: Confirmed Hold Cannot Be Released
- **Problem Statement**: Once payment is completed and an inventory hold transitions to `CONFIRMED`, an unauthorized or out-of-order `release` request (e.g. from an erroneous refund or late timeout signal) must never erroneously return stock to available inventory.
- **Enforcement Level**:
  1. Valid hold lifecycle states: `HELD` $\rightarrow$ `CONFIRMED` or `HELD` $\rightarrow$ `RELEASED`.
  2. Inspection with row-level lock (`with_for_update=True`):
     - If `hold.status == "CONFIRMED"`: Immediate rejection with `ValueError("Confirmed stock cannot be released")` mapped to HTTP `409 Conflict`.
     - If `hold.status == "RELEASED"`: Idempotent no-op returning `200 OK` (stock is NOT incremented twice).
     - If `hold.status == "HELD"`: Product available stock is incremented by `hold.quantity`, status is updated to `RELEASED`, and transaction commits.


---

## Detailed Rule Specifications (Payment & Notification Domains - Meghana Toutam)

### BR5: Payment Key Charges Once (Idempotency and Conflict Detection)
- **Problem Statement**: In distributed networks, transient timeouts frequently trigger automated client retries. If the original charge succeeded at the payment processor but the acknowledgment was lost in transit, retrying the charge naively causes customers to be billed multiple times. Conversely, reusing a previous payment key with altered transaction details (e.g., higher amount or different order) indicates transaction spoofing or cache corruption.
- **Enforcement Level**:
  1. Unique Constraint on Idempotency Key:
     ```sql
     CREATE UNIQUE INDEX ix_charges_idempotency_key ON charges(idempotency_key);
     ```
  2. Payload Fingerprinting:
     Incoming payloads are canonically serialized (`json.dumps(..., sort_keys=True)`) and hashed via SHA-256:
     $$\text{fingerprint} = \text{SHA-256}(\text{canonical\_json}(\text{payload}))$$
  3. Strict Conflict Resolution:
     - If `idempotency_key` is unseen: Insert new record with status (`SUCCEEDED` or `DECLINED`), fingerprint, and amount; commit and return HTTP `201 Created`.
     - If `idempotency_key` exists and incoming fingerprint == stored fingerprint: Return existing persisted record with HTTP `200/201`. No secondary payment processing occurs.
     - If `idempotency_key` exists and incoming fingerprint != stored fingerprint: Immediately reject with HTTP `409 Conflict` (`KEY_REUSED`, "Different payload").
  4. Safe GET Reconciliation:
     `GET /api/v1/payments/by-key/{key}` is strictly a read-only query. It guarantees recovery of existing transaction states after network timeouts without causing mutations.

### BR6: Notification Failure Cannot Cancel Paid Order
- **Problem Statement**: Notifications (email, SMS, push) depend on third-party carrier gateways that have lower SLA availability than primary core banking systems. If a customer's payment succeeds and warehouse inventory is reserved, failing to deliver a confirmation SMS must never roll back or abort the entire customer order.
- **Enforcement Level**:
  1. Decoupled Best-Effort Delivery:
     In `order/app/main.py`, the notification dispatch is isolated in `notify_best_effort()`:
     ```python
     try:
         downstream("POST", f"{NOTIFICATION}/api/v1/notifications", request_id, json={...})
     except httpx.HTTPError as exc:
         logger.warning(f"Notification gateway unavailable: {exc}. Non-critical failure.")
     ```
  2. Transaction Finality:
     Once payment succeeds and inventory hold is confirmed, the order is immutably committed to `CONFIRMED`.
  3. Resilient Outbox Simulation:
     The notification service logs message payloads in `messages` table with status `RECORDED` or simulated carrier drop (`500`). In production, this powers an asynchronous retry worker without placing the customer's checkout on the critical synchronous path.
