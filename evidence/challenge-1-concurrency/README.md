# Challenge 1 Evidence: Concurrency Control

**Lead Owner**: Dr. Sunanda Pandita (Inventory Service)  
**Evaluator Reference**: BITS Pilani WILP - Scalable Services (SEZG583) Assignment 1

---

## 1. Challenge Objective & Invariant (BR1)

Demonstrate that when multiple competing threads attempt to reserve the same finite inventory stock simultaneously, the system guarantees:
1. **Zero Overselling**: Stock never drops below zero (`available >= 0`).
2. **Deterministic Allocation**: For $N$ available units and $M$ competing requests ($M > N$), exactly $N$ requests succeed with HTTP `201 Created` and $M - N$ requests are rejected with HTTP `409 Conflict (OUT_OF_STOCK)`.
3. **Traceability**: All successful reservations are immutably persisted in `holds` with unique `order_id` values.

---

## 2. Evidence Files Index

| File | Purpose / Description |
|------|------------------------|
| [`run-log.txt`](file:///Users/harshchavan/Documents/GitHub/MTECHPROJECT2/ecommerce-scalable-services/evidence/challenge-1-concurrency/run-log.txt) | Raw execution log showing the concurrent dispatch of 20 requests against a product with stock = 5. Contains individual response codes, latency figures, and invariant check assertions. |
| [`sql-proof.txt`](file:///Users/harshchavan/Documents/GitHub/MTECHPROJECT2/ecommerce-scalable-services/evidence/challenge-1-concurrency/sql-proof.txt) | Post-execution SQL database state dump verifying that `products.available == 0` and exactly 5 active reservation rows were committed in `holds`. |
| `../../scripts/concurrency.py` | Complete multi-threaded Python harness using `concurrent.futures.ThreadPoolExecutor(max_workers=20)`. |

---

## 3. Why Check-Then-Update Fails in Distributed Systems

In naive implementations, stock reservation is written as:
```python
# ANTI-PATTERN: Prone to race conditions
product = db.query(Product).filter_by(id=product_id).first()
if product.available >= quantity:
    # Context switch / interleaving occurs here!
    product.available -= quantity
    db.commit()
```
When 20 concurrent threads read `product.available` simultaneously before any thread commits, all 20 threads observe `available = 5`. Consequently, all 20 threads proceed to decrement and commit, driving the available stock down to $-15$ (severe overselling).

### Our Solution: Atomic Conditional SQL Update
We eliminate application-level read-modify-write races by executing a single atomic conditional SQL statement at the database engine level:
```sql
UPDATE products
SET available = available - :quantity
WHERE id = :product_id AND available >= :quantity
RETURNING id, available;
```
Because PostgreSQL and SQLite evaluate the `WHERE available >= :quantity` predicate and the row lock atomically within the database engine:
- Exactly 5 threads acquire the row update lock and satisfy the condition.
- The remaining 15 threads find zero rows matching `available >= 1` and return zero rows.
- The application immediately aborts the transaction and returns a structured HTTP `409 Conflict` with `{"error": {"code": "OUT_OF_STOCK", "message": "Insufficient stock"}}`.
