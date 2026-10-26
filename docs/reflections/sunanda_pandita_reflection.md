# Individual Student Reflection: Dr. Sunanda Pandita

- **Student Name**: Dr. Sunanda Pandita
- **Student ID**: 2025tm93132
- **Email**: `2025tm93132@wilp.bits-pilani.ac.in`
- **Role / Ownership**: Inventory Service Lead (P1), Business Rules Lead (`docs/business-rules.md`), Challenge 1 Concurrency Lead (`evidence/challenge-1-concurrency/`)
- **Course**: BITS Pilani WILP - Scalable Services (SEZG583)

---

## 1. What I Built
As the Inventory Service owner, I designed and implemented the entire stock catalog and inventory hold lifecycle management component:
1. **Isolated PostgreSQL Service**: Implemented the service using FastAPI and SQLAlchemy 2.0 with a dedicated database schema (`products` and `holds` tables) adhering strictly to the database-per-service microservice pattern.
2. **Atomic Stock Decrement (BR1)**: Designed the conditional update mechanism `UPDATE products SET available = available - :qty WHERE id = :product_id AND available >= :qty RETURNING id, available` to prevent overselling under high concurrency.
3. **Hold State Machine (BR2)**: Built the state transitions (`HELD` $\rightarrow$ `CONFIRMED` or `RELEASED`), guaranteeing that confirmed purchases cannot be released and that duplicate release/confirm calls behave idempotently without corrupting inventory balance.
4. **Validation and Health Check**: Added OpenAPI specifications, Pydantic request models, health probes (`/health`), and structured JSON request correlation ID logging (`X-Request-ID` / `X-Correlation-ID`).
5. **Testing & Evidence**: Authored comprehensive unit tests (`test_business_rules.py`) covering all state transitions, and built the multi-threaded Challenge 1 concurrency harness (`scripts/concurrency.py`) along with raw execution logs and SQL proofs.

---

## 2. Hardest Problem Solved
The most challenging engineering hurdle was preventing race conditions under high-throughput concurrent requests without degrading service responsiveness. 

Initially, separating the availability check from the update in application logic (`SELECT` followed by `UPDATE`) resulted in severe overselling when 20 parallel threads competed for the last 5 keyboard units. When exploring pessimist table locks (`SELECT FOR UPDATE`), concurrency throughput dropped due to lock contention.

I resolved this by enforcing an atomic conditional `UPDATE ... WHERE available >= :qty RETURNING id, available` executed in a single atomic database transaction. This shifted the locking boundary directly to the row-level update step in the database engine. If zero rows are returned, the transaction rolls back cleanly and returns a 409 `OUT_OF_STOCK` error immediately. Furthermore, by placing a unique constraint on `order_id` in the `holds` table, any identical retry from a network hiccup returns the previously created hold without re-decrementing stock.

---

## 3. What I Would Change / Future Improvements
If expanding this application for production scale in Assignment 2:
1. **Distributed Caching with Redis**: For extreme burst traffic, maintaining an in-memory Redis cache with atomic Lua scripts for preliminary stock reservation would offload repetitive reads from the primary PostgreSQL database.
2. **Automated Hold Expiration (Time-Bound Reservations)**: Implement background worker tasks (or Celery/Redis TTLs) to automatically release `HELD` stock back to `available` if the customer does not finalize payment within a 15-minute checkout window.
3. **Asynchronous Event-Driven Inventory Sync**: Instead of relying solely on synchronous REST orchestration from the Order Service, publish domain events (`OrderCancelled`, `PaymentFailed`) to a message broker (RabbitMQ/Kafka) so inventory release occurs asynchronously with guaranteed eventual consistency.
