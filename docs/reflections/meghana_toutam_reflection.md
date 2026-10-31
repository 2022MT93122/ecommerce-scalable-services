# Individual Student Reflection: Meghana Toutam

- **Student Name**: Meghana Toutam
- **Student ID**: 2025tm93231
- **Email**: `2025tm93231@wilp.bits-pilani.ac.in`
- **GitHub Username**: `@MeghanaToutam15`
- **Role / Ownership**: Payment & Notification Service Lead (P3), Challenge 3A Resilience & Reconciliation Owner, Business Rules Lead for BR5 & BR6
- **Course**: BITS Pilani WILP - Scalable Services (SEZG583)

---

## 1. What I Built

As the Payment and Notification Service owner, I engineered two completely isolated microservices adhering strictly to cloud-native architectural patterns and distributed systems invariants:
1. **Mock Payment Microservice (`services/payment`)**:
   - Implemented with FastAPI and SQLAlchemy 2.0 with an isolated PostgreSQL database (`payment_db`).
   - Built strict financial idempotency (BR5): enforced a database-level unique index on `idempotency_key` and canonical SHA-256 fingerprinting of incoming request bodies. Identical requests replay the stored transaction outcome (`200/201`), while conflicting payloads with an identical key are safely rejected with HTTP `409 Conflict`.
   - Engineered controllable failure and latency simulation modes (`simulate="success"`, `"decline"`, `"slow"`) and environment variable overrides (`PAYMENT_SIMULATION_MODE`).
   - Built a dedicated, read-only reconciliation endpoint (`GET /api/v1/payments/by-key/{key}`) enabling upstream services to query in-doubt charges without triggering secondary mutations.
2. **Mock Notification Microservice (`services/notification`)**:
   - Implemented with FastAPI and an isolated database (`notification_db`, `messages` table).
   - Designed non-blocking, best-effort message delivery (BR6) with simulated carrier drops (`simulate="failure"`) and latency injection (`simulate="delay"`).
3. **Challenge 3A Resilience & Reconciliation Architecture**:
   - Collaborated with Tarun (Order Service) to model transient gateway latency (2.0s sleep) against tight client timeouts (0.7s).
   - Designed bounded exponential backoff retries with jitter and the safe GET-by-key reconciliation loop.
   - Authored complete test suites for Payment (`test_payment_rules.py`) and Notification (`test_notification_rules.py`), along with executable verification scripts (`scripts/resilience.py`) and empirical evidence dossiers (`evidence/challenge-3a-resilience/`).

---

## 2. Hardest Problem Solved

The most intricate engineering dilemma I faced was managing the **In-Doubt Transaction Dilemma** under network timeouts. 

In a distributed environment, when the Order Service experiences an HTTP timeout while waiting for the Payment Service, it is impossible for the caller to determine whether the network packet dropped before reaching Payment, or if Payment processed the financial transaction successfully and only the return acknowledgment dropped. 

If the system naively treats a timeout as a failure and triggers stock release or tells the user to retry with a new payment, the customer gets double-billed when the original transaction actually succeeded. Conversely, if it naively treats a timeout as success, unpaid orders get confirmed.

I solved this by decoupling transaction processing from synchronous acknowledgment through three coordinated mechanisms:
1. **Deterministic Upstream Idempotency Keys**: The Order Service generates a stable key: `pay-{order.id}`. Every automated retry passes this exact key.
2. **Database Unique Key Guard**: In `payment_db`, the unique index on `idempotency_key` guarantees that PostgreSQL physically aborts and prevents duplicate charge rows, returning the previously committed record.
3. **Safe Read-Only GET Reconciliation**: When client-side retries fail or time out, the Order Service does not abort; it queries `GET /api/v1/payments/by-key/pay-{order.id}`. Because GET operations are idempotent and side-effect-free, this reliably resolves the in-doubt status. If the payment is found in `SUCCEEDED`, the order safely transitions to `CONFIRMED`; if `DECLINED`, it rolls back stock; if still absent, it safely transitions to `PAYMENT_PENDING` for asynchronous reconciliation.

---

## 3. What I Would Change / Future Improvements

If scaling this system to production or extending into Assignment 2:
1. **Transactional Outbox Pattern for Notifications**: Rather than having the Order Service initiate a direct HTTP call to the Notification Service, the Order Service should write notification intents directly to an `outbox` table in its own database in the same transaction. An asynchronous CDC relay (such as Debezium or a Kafka publisher) would then stream events to Notification, achieving complete decoupling.
2. **Distributed Sagas with Event Sourcing (Temporal / Cadence)**: For multi-service workflows spanning dozens of steps, replacing synchronous REST orchestration with an event-driven Saga orchestrator or stateful workflow engine would provide durable timers, automated compensation trees, and transparent crash-recovery.
3. **Circuit Breakers with Resilience4j or Polly**: When downstream payment gateways experience consecutive failures, wrapping calls in an adaptive Circuit Breaker would prevent cascading exhaustion of upstream connection pools and worker threads.
