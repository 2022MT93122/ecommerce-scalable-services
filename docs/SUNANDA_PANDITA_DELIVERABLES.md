# Dr. Sunanda Pandita - Complete Assignment Deliverables Package

**Course**: BITS Pilani WILP - Scalable Services (SEZG583)  
**Assignment**: Assignment 1: Design and Development of a Microservices Application  
**Student Name**: Dr. Sunanda Pandita  
**Student ID**: 2025tm93132  
**Institutional Email**: `2025tm93132@wilp.bits-pilani.ac.in`  
**GitHub Username**: `@DrSunandaPandita`  
**Assigned Role**: Owner P1 — Inventory Service Lead, Challenge 1 (Concurrency) Owner, Business Rules Lead  

---

## Part 1: GitHub Repository & Code Deliverables

All deliverables have been developed, tested, committed under `DrSunandaPandita`, pushed to GitHub, and linked to a Pull Request:
- **Repository**: [2022MT93122/ecommerce-scalable-services](https://github.com/2022MT93122/ecommerce-scalable-services)
- **Branch**: `feature/inventory-service`
- **Pull Request**: [PR #1: feat(inventory): Complete Inventory Service and Challenge 1 Concurrency Harness](https://github.com/2022MT93122/ecommerce-scalable-services/pull/1)

### File Manifest for Sunanda's Ownership
1. **Inventory Microservice** (`services/inventory/`):
   - `services/inventory/app/main.py`: Complete FastAPI application exposing `/health`, catalog CRUD APIs, and atomic stock reservation, confirmation, and release.
   - `services/inventory/app/db.py`: Database engine and session lifecycle with isolated PostgreSQL `inventory_db` configuration and local fallback.
   - `services/inventory/app/common.py`: Structured JSON request logging, Correlation ID middleware (`X-Request-ID` / `X-Correlation-ID`), and standardized error response handler.
   - `services/inventory/Dockerfile` & `requirements.txt`: Container definition and pinned dependencies.
   - `services/inventory/.env.example`: Environment configuration template.
2. **Automated Unit Tests** (`services/inventory/tests/`):
   - `tests/test_contract.py`: Contract and health check verification.
   - `tests/test_business_rules.py`: 9 comprehensive test cases covering BR1 (atomic conditional update, zero overselling), BR2 (confirmed hold protection), idempotency replays, and conflict rejections.
3. **Challenge 1 Concurrency Harness** (`scripts/`):
   - `scripts/concurrency.py`: Multi-threaded test harness dispatching 20 parallel requests against 5 available units.
   - `scripts/seed.py`: Product catalog seeding utility.
4. **Challenge 1 Evidence Folder** (`evidence/challenge-1-concurrency/`):
   - `evidence/challenge-1-concurrency/README.md`: Technical documentation explaining why naive check-then-update fails and how atomic conditional updates solve it.
   - `evidence/challenge-1-concurrency/run-log.txt`: Verifiable execution output with timestamps, showing 5 HTTP 201s and 15 HTTP 409s.
   - `evidence/challenge-1-concurrency/sql-proof.txt`: Post-run SQL database dump proving stock is exactly 0 and 5 active holds were committed.
5. **Test Evidence Folder** (`evidence/tests/`):
   - `evidence/tests/inventory_test_results.txt`: Terminal pytest test execution log (9/9 passed).
6. **Documentation & Architecture** (`docs/`):
   - `docs/business-rules.md`: Business invariant mapping for BR1 through BR6.
   - `docs/inventory-erd.md`: Entity-relationship diagram and hold state machine.
   - `docs/AI_USE_LOG.md`: Formal AI-use disclosure log.
   - `docs/reflections/sunanda_pandita_reflection.md`: Individual student reflection.

---

## Part 2: Design and Technical Report Sections (For the 15-Page PDF)

*(These sections are formatted for direct inclusion into the team's combined Design and Technical Report PDF).*

### Section 1: Business Invariants (Lead: Dr. Sunanda Pandita)
* **BR1 — Stock Never Negative**: Inventory reservation must never drive stock below zero under any concurrency level. Enforced via a database `CHECK (available >= 0)` constraint and an atomic conditional SQL update:
  $$\text{UPDATE products SET available = available - } q \text{ WHERE id = } p \text{ AND available } \ge q \text{ RETURNING id, available;}$$
* **BR2 — Confirmed Hold Cannot Be Released**: Once payment succeeds and an inventory hold reaches `CONFIRMED`, downstream compensation calls or delayed cancellation signals are rejected with HTTP 409 (`BUSINESS_CONFLICT`). Stock is only restored when transitioning from `HELD` to `RELEASED`.

### Section 2 & 4: Service Boundaries & Data Design (Inventory Service)
* **Boundary Rationale**: The Inventory Service exclusively owns product definitions, pricing metadata, and physical warehouse stock availability. Neither Order nor Payment services can query or modify inventory tables directly; all interactions occur through REST contracts.
* **Schema & ER Design**:
  - `products(id PK, name VARCHAR(120), price_cents INTEGER CHECK > 0, available INTEGER CHECK >= 0)`
  - `holds(id PK, order_id VARCHAR(64) UNIQUE, product_id INTEGER FK, quantity INTEGER CHECK > 0, status VARCHAR(20))`
* **Cross-Service References**: The `holds` table stores `order_id` as an unconstrained string attribute, deliberately omitting cross-database foreign key constraints to maintain database autonomy.

### Section 5: Inventory API Specifications
* `GET /health` $\rightarrow$ `200 OK {"status": "ok", "service": "inventory"}`
* `POST /api/v1/products` $\rightarrow$ `201 Created`
* `GET /api/v1/products` $\rightarrow$ `200 OK`
* `POST /api/v1/stock/reserve` $\rightarrow$ `201 Created` (Success) or `409 Conflict` (`OUT_OF_STOCK`)
* `POST /api/v1/stock/{id}/confirm` $\rightarrow$ `200 OK` (Confirmed) or `409 Conflict`
* `POST /api/v1/stock/{id}/release` $\rightarrow$ `200 OK` (Released) or `409 Conflict` (BR2 violation)

### Section 6: Engineering Challenge 1 — Concurrency Control
* **Problem**: When 20 simultaneous checkout requests arrive for the last 5 keyboard units, application-level `SELECT ... THEN UPDATE` allows multiple threads to read `available = 5` concurrently before any transaction commits, driving stock to $-15$.
* **Engineering Choice**: Single atomic conditional `UPDATE ... WHERE available >= :qty RETURNING id`. Executed inside an engine-level row lock, this eliminates race conditions without requiring coarse table locks.
* **Rejected Alternative**: Application-level Python mutex locks (`threading.Lock`) were rejected because they fail across multi-process workers (`gunicorn`/`uvicorn` workers) and distributed replicas. Pessimistic `SELECT FOR UPDATE` was evaluated but rejected due to higher lock contention and deadlocking risks under read-heavy traffic.
* **Empirical Outcome**: Out of 20 concurrent threads, exactly 5 acquired the row lock and received `201 Created`, while 15 were safely rejected with `409 Conflict`. Database available stock remained exactly 0.

---

## Part 3: Demo Video Script (Minutes 0:00 – 3:00)

*(Allocated Speaking Slot: Dr. Sunanda Pandita)*

| Timestamp | Visual / Terminal Action | Spoken Script |
|---|---|---|
| **0:00 – 0:45** | Display Architecture Slide & Docker Compose terminal (`docker compose ps`). | *"Hello everyone. I am Dr. Sunanda Pandita. For our team project in Scalable Services, I led the Inventory Service and Challenge 1 on Concurrency Control. As you see on the screen, our system decomposes e-commerce into four isolated microservices, each with its own PostgreSQL database. No service touches another database directly."* |
| **0:45 – 1:30** | Open Swagger UI at `http://localhost:8001/docs`. Execute `GET /health` and `GET /api/v1/products`. | *"Here is the Inventory Service running independently on port 8001. All routes are versioned under `/api/v1`, and our `/health` probe confirms database operability. The catalog stores prices as integer paise to prevent floating-point rounding errors. Next, I'll demonstrate how stock is reserved atomically."* |
| **1:30 – 2:30** | Switch to terminal. Execute `python scripts/concurrency.py`. Point to the output in real time. | *"Now let's demonstrate Challenge 1: Concurrency. We seed a Mechanical Keyboard with exactly 5 available units. Then, using Python's ThreadPoolExecutor, we blast the service with 20 parallel reservation requests at the same millisecond. As the live logs show, exactly 5 requests succeed with HTTP 201, and exactly 15 requests receive a controlled HTTP 409 OUT_OF_STOCK rejection."* |
| **2:30 – 3:00** | Run `sqlite3` or `psql` query showing `products` stock is 0 and `holds` has 5 rows. | *"Finally, querying the database directly confirms that available stock is exactly 0 and never dropped negative, satisfying Business Rule 1. Furthermore, our unit tests prove Business Rule 2: once a hold is confirmed, release calls are strictly rejected. I now hand over to Tarun to demonstrate Order checkout and idempotency."* |

---

## Part 4: Report Appendix Items

### 1. Contribution Table Entry
| Student Name | Student ID | Email | Service Owned | Challenge Owned | Deliverables / Evidence |
|---|---|---|---|---|---|
| **Dr. Sunanda Pandita** | 2025tm93132 | `2025tm93132@wilp.bits-pilani.ac.in` | Inventory Service | Challenge 1 (Concurrency) | Inventory REST APIs, atomic conditional stock update, hold state machine (BR1 & BR2), unit test suite (9 tests), `scripts/concurrency.py`, `evidence/challenge-1-concurrency/` |

### 2. Individual Reflection (Half Page)
*Available at: [`docs/reflections/sunanda_pandita_reflection.md`](file:///Users/harshchavan/Documents/GitHub/MTECHPROJECT2/ecommerce-scalable-services/docs/reflections/sunanda_pandita_reflection.md)*

### 3. AI-Use Declaration
*Available at: [`docs/AI_USE_LOG.md`](file:///Users/harshchavan/Documents/GitHub/MTECHPROJECT2/ecommerce-scalable-services/docs/AI_USE_LOG.md)*
