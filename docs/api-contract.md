# Frozen API Contract (Multi-Service Interface Specifications)

All microservices adhere to versioned REST APIs mounted at `/api/v1/...`.  
Every service exposes an unversioned operational health endpoint at `/health`.

---

## 1. Inventory Service (Port 8001)

| Method | Endpoint | Description | Status Codes |
|---|---|---|---|
| `GET` | `/health` | Service operability check | `200 OK` |
| `POST` | `/api/v1/products` | Create a new catalog product | `201 Created` |
| `GET` | `/api/v1/products` | List all catalog products and available stock | `200 OK` |
| `GET` | `/api/v1/products/{id}` | Inspect specific product details | `200 OK`, `404 Not Found` |
| `POST` | `/api/v1/stock/reserve` | Atomically reserve inventory hold (BR1) | `201 Created`, `409 OUT_OF_STOCK` |
| `POST` | `/api/v1/stock/{id}/confirm` | Confirm reservation upon payment success | `200 OK`, `404 Not Found`, `409 Conflict` |
| `POST` | `/api/v1/stock/{id}/release` | Release reserved inventory on failure/timeout (BR2) | `200 OK`, `404 Not Found`, `409 Conflict` |

---

## 2. Order Service (Port 8002)

| Method | Endpoint | Description | Status Codes |
|---|---|---|---|
| `GET` | `/health` | Service operability check | `200 OK` |
| `POST` | `/api/v1/orders` | Checkout with mandatory `Idempotency-Key` header | `201 Created`, `202 Accepted`, `409 Conflict` |
| `GET` | `/api/v1/orders/{id}` | Inspect current order lifecycle state | `200 OK`, `404 Not Found` |
| `POST` | `/api/v1/orders/{id}/reconcile` | Reconcile timed-out / pending payment outcomes | `200 OK`, `404 Not Found` |

---

## 3. Payment Service (Port 8003)

| Method | Endpoint | Description | Status Codes |
|---|---|---|---|
| `GET` | `/health` | Service operability check | `200 OK` |
| `POST` | `/api/v1/payments` | Idempotent mock charge processing | `201 Created`, `409 Conflict` |
| `GET` | `/api/v1/payments/by-key/{key}` | Safe lookup of prior charge for reconciliation | `200 OK`, `404 Not Found` |

---

## 4. Notification Service (Port 8004)

| Method | Endpoint | Description | Status Codes |
|---|---|---|---|
| `GET` | `/health` | Service operability check | `200 OK` |
| `POST` | `/api/v1/notifications` | Record asynchronous notification event | `201 Created` |
| `GET` | `/api/v1/notifications/{id}` | Retrieve delivery status and logs | `200 OK`, `404 Not Found` |
