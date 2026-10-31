# E-Commerce Microservices - BITS Pilani WILP (SEZG583)

A distributed microservices-based e-commerce order processing system demonstrating atomic concurrency control, idempotency, fault tolerance/resilience, and database-per-service architecture.

---

## 1. Team Allocation & Service Ownership

| Member | BITS Email / GitHub | Service Ownership | Challenge Ownership & Proof |
|---|---|---|---|
| **Dr. Sunanda Pandita (P1)** | `2025tm93132@wilp.bits-pilani.ac.in` / `@DrSunandaPandita` | **Inventory Service** (Catalog, stock holds, atomic conditional decrement, confirm/release) | **Challenge 1: Concurrency** (20-way parallel request harness, BR1 & BR2 unit tests, SQL dump proof) |
| **Tarun (P2)** | `2022MT93122` | **Order Service** (Checkout orchestration, state machine, idempotency persistence) | **Challenge 2: Idempotency** (Replay & duplicate protection tests) |
| **Meghana Toutam (P3)** | `2025tm93231@wilp.bits-pilani.ac.in` / `@MeghanaToutam15` | **Payment & Notification Mocks** (Idempotent charges, fault simulation, delivery logs) | **Challenge 3A: Resilience** (Timeout, bounded retry with backoff, reconciliation, BR5 & BR6) |

### Detailed Individual Deliverables Dossiers
- **Dr. Sunanda Pandita**: [`docs/SUNANDA_PANDITA_DELIVERABLES.md`](docs/SUNANDA_PANDITA_DELIVERABLES.md)
- **Meghana Toutam**: [`docs/MEGHANA_TOUTAM_DELIVERABLES.md`](docs/MEGHANA_TOUTAM_DELIVERABLES.md)

---

## 2. Architecture & Service Ports

| Service | Internal Port | Host Port | Database | Responsibilities |
|---|---|---|---|---|
| **PostgreSQL** | 5432 | 5432 | Shared Cluster (4 isolated DBs) | Data persistence with strict credentials separation |
| **Inventory** | 8000 | **8001** | `inventory_db` | Products catalog, atomic reservations (BR1), holds |
| **Order** | 8000 | **8002** | `order_db` | Orchestrator, idempotency records (BR3, BR4) |
| **Payment Mock** | 8000 | **8003** | `payment_db` | Idempotent charges (BR5), failure simulation (slow, decline) |
| **Notification Mock** | 8000 | **8004** | `notification_db` | Asynchronous delivery log, best-effort messaging (BR6) |

---

## 3. Interactive Swagger / OpenAPI Documentation

Each microservice automatically exposes an interactive Swagger UI for API exploration and live execution:
- **Payment Service Swagger**: [http://localhost:8003/docs](http://localhost:8003/docs)
- **Notification Service Swagger**: [http://localhost:8004/docs](http://localhost:8004/docs)
- **Inventory Service Swagger**: [http://localhost:8001/docs](http://localhost:8001/docs)
- **Order Service Swagger**: [http://localhost:8002/docs](http://localhost:8002/docs)

---

## 4. Quick Start with Docker Compose

1. **Start all services and databases**:
   ```bash
   docker compose up --build -d
   ```
2. **Verify health endpoints**:
   ```bash
   curl http://localhost:8001/health   # Inventory
   curl http://localhost:8002/health   # Order
   curl http://localhost:8003/health   # Payment
   curl http://localhost:8004/health   # Notification
   ```

---

## 5. Running Tests & Challenge Scripts

Install script dependencies:
```bash
pip install -r scripts/requirements.txt
```

### Challenge 1: Concurrency Test (Dr. Sunanda Pandita)
Tests 20 concurrent reserve requests against a product with 5 available units.
```bash
python scripts/concurrency.py
```
- Invariant: Exactly 5 succeed (`201 Created`), 15 rejected (`409 OUT_OF_STOCK`), final stock is 0.

### Challenge 2: Idempotency Test
```bash
python scripts/idempotency.py
```

### Challenge 3A: Resilience & Payment Reconciliation Test (Meghana Toutam)
```bash
python scripts/resilience.py
```
- Invariants: BR5 idempotent payment replay, payload conflict rejection, safe timeout handling, GET-by-key reconciliation, and BR6 non-blocking notification failure.

### End-to-End Main Checkout Flow
```bash
python scripts/e2e.py
```

### Service Unit Test Suites
```bash
# Inventory Service (BR1, BR2)
cd services/inventory && pytest -v

# Payment Service (BR5, Idempotency, Simulation, Reconciliation)
cd services/payment && pytest -v

# Notification Service (BR6, Best-effort Delivery, Gateway Failure)
cd services/notification && pytest -v
```
