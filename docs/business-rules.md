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
