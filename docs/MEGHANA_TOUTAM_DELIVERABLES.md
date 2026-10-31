# Meghana Toutam - Complete Assignment Deliverables Package

**Course**: BITS Pilani WILP - Scalable Services (SEZG583)  
**Assignment**: Assignment 1: Design and Development of a Microservices Application  
**Student Name**: Meghana Toutam  
**Student ID**: 2025tm93231  
**Institutional Email**: `2025tm93231@wilp.bits-pilani.ac.in`  
**GitHub Username**: `@MeghanaToutam15`  
**Assigned Role**: Owner P3 — Payment & Notification Services Lead, Challenge 3A (Resilience & Reconciliation) Owner, Business Rules Lead for BR5 & BR6  

---

## Part 1: GitHub Repository & Code Deliverables

All deliverables have been designed, implemented, tested, verified against business invariants, and committed under the local and remote identity of Meghana Toutam (`MeghanaToutam15`):
- **Repository**: [2022MT93122/ecommerce-scalable-services](https://github.com/2022MT93122/ecommerce-scalable-services)
- **Branch**: `feature/payment-notification`
- **Pull Request**: `PR #3: feat(payment-notification): Complete Payment & Notification Services and Challenge 3A Resilience Harness`

### File Manifest for Meghana's Ownership
1. **Payment Microservice** (`services/payment/`):
   - `services/payment/app/main.py`: Complete FastAPI application exposing `/health`, idempotent charge processing (`POST /api/v1/payments`), reconciliation query (`GET /api/v1/payments/by-key/{key}`), charge lookup (`GET /api/v1/payments/{payment_id}`), and controllable simulation modes (`simulate="success"`, `"decline"`, `"slow"`).
   - `services/payment/app/db.py`: Database engine and session lifecycle with isolated PostgreSQL `payment_db` configuration and transparent local SQLite fallback.
   - `services/payment/app/common.py`: Structured JSON request logging, Correlation ID middleware (`X-Request-ID` / `X-Correlation-ID`), and standardized error response handler.
   - `services/payment/Dockerfile` & `requirements.txt`: Container definition and pinned dependencies.
   - `services/payment/.env.example`: Environment configuration template.
2. **Notification Microservice** (`services/notification/`):
   - `services/notification/app/main.py`: Complete FastAPI application exposing `/health`, mock message recording (`POST /api/v1/notifications`), message inspection (`GET /api/v1/notifications/{message_id}`), order-based message lookup (`GET /api/v1/notifications/order/{order_id}`), and simulated carrier failure/delay modes (`simulate="failure"`, `"delay"`).
   - `services/notification/app/db.py`: Database engine and session lifecycle with isolated PostgreSQL `notification_db` configuration and transparent local SQLite fallback.
   - `services/notification/app/common.py`: Structured JSON request logging, Correlation ID middleware (`X-Request-ID` / `X-Correlation-ID`), and standardized error response handler.
   - `services/notification/Dockerfile` & `requirements.txt`: Container definition and pinned dependencies.
   - `services/notification/.env.example`: Environment configuration template.
3. **Automated Unit Tests** (`services/payment/tests/` & `services/notification/tests/`):
   - `services/payment/tests/test_payment_rules.py`: 10 comprehensive unit tests covering BR5 (database unique constraint on `idempotency_key`, payload SHA-256 fingerprinting, replay without double charging, 409 conflict detection, GET-by-key reconciliation, simulation modes, and concurrent duplicate charge handling).
   - `services/notification/tests/test_notification_rules.py`: 8 comprehensive unit tests covering BR6 (message recording, order-level deduplication, lookup by ID/order, simulated 500 carrier failure, and non-blocking decoupled delivery).
   - `services/payment/tests/test_contract.py` & `services/notification/tests/test_contract.py`: Service health and FastAPI contract verification.
4. **Challenge 3A Resilience Harness** (`scripts/`):
   - `scripts/resilience.py`: Executable end-to-end resilience validation harness verifying health of all 4 microservices, direct BR5 idempotency & conflict handling, Challenge 3A transient payment delays (2.0s sleep vs 0.7s timeout), client retries with exponential backoff & jitter, safe GET-by-key reconciliation, simulated decline inventory rollback, and BR6 non-blocking notification failure.
5. **Challenge 3A Evidence Folder** (`evidence/challenge-3a-resilience/`):
   - `evidence/challenge-3a-resilience/README.md`: Technical documentation explaining the network timeout dilemma, why timeouts cannot be treated as failures, and how stable idempotency keys + safe GET reconciliation eliminate duplicate charges.
   - `evidence/challenge-3a-resilience/run-log.txt`: Verifiable execution output with millisecond-level timestamps showing successful retry and reconciliation.
   - `evidence/challenge-3a-resilience/payment-logs.txt`: Service-side structured JSON logs capturing incoming charge requests, slow simulation delays, and reconciliation lookups.
   - `evidence/challenge-3a-resilience/resilience-proof.txt`: Post-run SQL database state dump verifying zero duplicate charges in `payment_db` and proper order state transitions in `order_db` and `inventory_db`.
6. **Test Evidence Folder** (`evidence/tests/`):
   - `evidence/tests/payment_test_results.txt`: Terminal pytest test execution log for Payment Service (10/10 passed).
   - `evidence/tests/notification_test_results.txt`: Terminal pytest test execution log for Notification Service (8/8 passed).
   - `evidence/tests/resilience_evidence_table.txt`: Consolidated BR1 through BR6 invariant verification matrix and Challenge 3A scenario outcomes.
7. **Documentation & Architecture** (`docs/`):
   - `docs/business-rules.md`: Business invariant mapping for BR5 and BR6 authored by Meghana Toutam.
   - `docs/payment-erd.md`: Entity-relationship diagrams, schema definitions, charge state machine, and Challenge 3A sequence diagram.
   - `docs/AI_USE_LOG.md`: Formal AI-use disclosure log for all payment, notification, and resilience tasks.
   - `docs/reflections/meghana_toutam_reflection.md`: Individual student reflection.

---

## Part 2: Design and Technical Report Sections (For the 15-Page PDF)

*(These sections are structured for direct insertion into the team's combined Design and Technical Report PDF).*

### Section 1: Business Invariants (Lead: Meghana Toutam)
* **BR5 — Payment Key Charges Once**:
  In a distributed system, network timeouts or retries must never bill a customer twice for the same logical purchase. 
  - Enforced via a PostgreSQL unique index on `charges(idempotency_key)`.
  - Payloads are normalized and hashed via SHA-256 fingerprinting:
    $$\text{fingerprint} = \text{SHA-256}(\text{canonical\_json}(\text{payload}))$$
  - If a subsequent request arrives with an existing key and identical fingerprint, the service performs an idempotent replay, returning the exact previously committed outcome (`SUCCEEDED` or `DECLINED`) with HTTP `200/201` without charging again.
  - If a request arrives with an existing key but a different payload (e.g. modified `amount_cents` or `order_id`), it is immediately rejected with HTTP `409 Conflict` (`KEY_REUSED`, "Different payload").
* **BR6 — Notification Failure Cannot Cancel Paid Order**:
  Third-party communication services (SMS gateways, email delivery agents) operate with lower SLA guarantees than transactional banking layers.
  - When payment succeeds and warehouse stock is confirmed, the order has reached commercial finality.
  - The notification call in `order/app/main.py` is executed best-effort inside a protected `try...except httpx.HTTPError` block.
  - Simulated carrier drops or HTTP 500 errors from the Notification Service are logged as warnings and queued for background retry, but are strictly prohibited from aborting or rolling back a confirmed customer order.

### Section 2 & 4: Service Boundaries & Data Design (Payment & Notification Services)
* **Payment Service Boundary Rationale**:
  - The Payment Service isolates financial charge processing, card/gateway tokenization, and transaction reconciliation.
  - It maintains zero dependencies on Inventory or Order schemas; cross-service references are stored strictly as unconstrained foreign attributes (`order_id VARCHAR(64)`).
  - All currency is represented as integer paise (`amount_cents INTEGER CHECK > 0`), strictly preventing IEEE-754 floating-point rounding errors.
* **Notification Service Boundary Rationale**:
  - The Notification Service decouples customer alerting (email, SMS) from core synchronous ordering.
  - It logs message requests to `messages(id, order_id, recipient, content, channel, status, created_at)` and simulates asynchronous delivery.
* **Database Isolation**:
  - `payment_db` is owned by `payment_user` and `notification_db` is owned by `notification_user`.
  - No cross-service SQL joins or shared database credentials exist.

### Section 5: Payment & Notification API Specifications
* **Payment Service (`http://localhost:8003`)**:
  - `GET /health` $\rightarrow$ `200 OK {"status": "ok", "service": "payment"}`
  - `POST /api/v1/payments` $\rightarrow$ `201 Created` (Success) or `409 Conflict` (Mismatched Payload). Requires `Idempotency-Key` header.
  - `GET /api/v1/payments/by-key/{key}` $\rightarrow$ `200 OK` (Reconciliation query, strictly read-only, never creates charges).
  - `GET /api/v1/payments/{payment_id}` $\rightarrow$ `200 OK`
* **Notification Service (`http://localhost:8004`)**:
  - `GET /health` $\rightarrow$ `200 OK {"status": "ok", "service": "notification"}`
  - `POST /api/v1/notifications` $\rightarrow$ `201 Created` (Status: `RECORDED`) or `500 Internal Server Error` (simulated failure).
  - `GET /api/v1/notifications/{message_id}` $\rightarrow$ `200 OK`
  - `GET /api/v1/notifications/order/{order_id}` $\rightarrow$ `200 OK`

### Section 6: Engineering Challenge 3A — Resilience, Timeouts & Reconciliation
* **Problem**: In microservices, network communication is unreliable. When the Order Service calls Payment with a 0.7s timeout and Payment takes 2.0s due to transient gateway latency, treating the timeout as a failed charge leads to disastrous outcomes (e.g. charging the customer while cancelling their order, or double charging on user retry).
* **Engineering Choice**: 
  1. Tight client-side timeout (0.7s) to protect server worker pools.
  2. Bounded exponential backoff retries with randomized jitter ($t = 0.1 \times 2^i + \text{jitter}$) using deterministic keys (`pay-{order.id}`).
  3. Safe read-only `GET /api/v1/payments/by-key/{key}` reconciliation query before abandoning order state.
  4. Non-blocking asynchronous notification dispatch (BR6).
* **Rejected Alternative 1: Two-Phase Commit (2PC / XA Transactions)**:
  Rejected because 2PC requires distributed locks across independent databases. If the coordinator or payment database stalls, locks are held across Inventory and Order, drastically reducing availability and violating CAP theorem principles.
* **Rejected Alternative 2: Naive Client Retry Without Idempotency**:
  Rejected because retrying a non-idempotent charge endpoint after a network timeout causes duplicate billing.
* **Rejected Alternative 3: Synchronous Notification Blocking**:
  Rejected because coupling customer checkout completion to third-party SMS/email gateway latency causes slow checkouts and causes orders to fail when carrier networks experience outages.

---

## Part 3: Demo Video Script (Minutes 6:00 – 9:00)

*(Allocated Speaking Slot: Meghana Toutam)*

| Timestamp | Visual / Terminal Action | Spoken Script |
|---|---|---|
| **6:00 – 6:45** | Display Swagger UI for Payment Service (`http://localhost:8003/docs`). Execute `GET /health` and `POST /api/v1/payments` with `Idempotency-Key: pay-demo-01`. | *"Hello everyone, I am Meghana Toutam. For our scalable microservices application, I designed and developed the Payment Service, the Notification Service, and Challenge 3A on Resilience and Fault Tolerance. Here you see the Payment Service running on port 8003. When processing a charge, we enforce Business Rule 5: every payment requires a unique Idempotency-Key. As I execute this initial request, the charge is committed to payment_db with status SUCCEEDED."* |
| **6:45 – 7:30** | Re-execute `POST /api/v1/payments` with the SAME key and payload. Show identical `payment_id`. Then change amount to 500000 and execute to show HTTP 409 `KEY_REUSED`. | *"Now, notice what happens if an upstream network hiccup replays this exact request: the service recognizes the duplicate key and identical SHA-256 fingerprint, replaying the exact same payment ID without billing the customer a second time. However, if a malicious client attempts to reuse that same key with a different amount, the service immediately blocks it with HTTP 409 Conflict. This guarantees strict financial integrity."* |
| **7:30 – 8:30** | Switch to terminal. Run `python scripts/resilience.py`. Point to the terminal output during simulated slow payment and retry log. | *"Next, let's demonstrate Challenge 3A: Resilience under Failing Dependencies. In distributed systems, a network timeout does NOT mean a transaction failed. In this live demonstration, we inject a 2.0-second payment delay while our Order client has a 0.7-second timeout. Notice the terminal: the Order Service detects the timeout, applies exponential backoff retries with jitter, and safely queries our read-only GET-by-key reconciliation endpoint. Because the charge succeeded, the order safely resolves to CONFIRMED with zero double charges."* |
| **8:30 – 9:00** | Display Notification Swagger (`http://localhost:8004/docs`). Show recorded messages and test summary. | *"Finally, our Notification Service on port 8004 enforces Business Rule 6: notifications are delivered best-effort. Even when we inject a simulated carrier failure, the confirmed order is never cancelled or rolled back. All 18 automated unit tests pass across our services. Thank you!"* |

---

## Part 4: Report Appendix Items

### 1. Contribution Table Entry
| Student Name | Student ID | Email | Service Owned | Challenge Owned | Deliverables / Evidence |
|---|---|---|---|---|---|
| **Meghana Toutam** | 2025tm93231 | `2025tm93231@wilp.bits-pilani.ac.in` | Payment Service & Notification Service | Challenge 3A (Resilience & Reconciliation) | Payment & Notification REST APIs, BR5 idempotent charge replay & conflict detection, safe GET-by-key reconciliation, simulation modes, BR6 decoupled notification delivery, unit test suites (18 tests), `scripts/resilience.py`, `evidence/challenge-3a-resilience/` |

### 2. Individual Reflection (Half Page)
*Available at: [`docs/reflections/meghana_toutam_reflection.md`](file:///c:/Meghana/ecommerce-scalable-services/docs/reflections/meghana_toutam_reflection.md)*

### 3. AI Assistance Log
*Documented at: [`docs/AI_USE_LOG.md`](file:///c:/Meghana/ecommerce-scalable-services/docs/AI_USE_LOG.md)*
