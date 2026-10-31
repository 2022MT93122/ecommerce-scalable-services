# Payment & Notification Services - Data Model and ER Diagram

**Owner**: Meghana Toutam (Payment & Notification Service Lead)  
**Course**: BITS Pilani WILP - Scalable Services (SEZG583)  
**Databases**: `payment_db` and `notification_db` (Isolated PostgreSQL databases)  

---

## 1. Entity-Relationship Diagrams

### Payment Service Data Model (`payment_db`)

```mermaid
erDiagram
    CHARGES {
        int id PK "Auto-incrementing charge identifier"
        string idempotency_key UK "Unique client-provided idempotency key (pay-{order_id})"
        string fingerprint "SHA-256 hash of canonical request body"
        string order_id "External order correlation identifier"
        int amount_cents "Charge amount in INR paise"
        string status "Payment state: SUCCEEDED, DECLINED"
        string response_json "Cached JSON response payload"
        timestamp created_at "UTC timestamp of charge creation"
    }
```

### Notification Service Data Model (`notification_db`)

```mermaid
erDiagram
    MESSAGES {
        int id PK "Auto-incrementing message identifier"
        string order_id UK "Unique external order correlation identifier"
        string recipient "Customer destination email address or phone"
        string content "Notification message body / text"
        string channel "Communication channel: email, sms"
        string status "Delivery state: RECORDED, DELIVERED, FAILED"
        timestamp created_at "UTC timestamp of message recording"
    }
```

---

## 2. Relational Schema Definitions

### `charges` Table (`payment_db`)
```sql
CREATE TABLE charges (
    id SERIAL PRIMARY KEY,
    idempotency_key VARCHAR(120) NOT NULL UNIQUE,
    fingerprint VARCHAR(64) NOT NULL,
    order_id VARCHAR(64) NOT NULL,
    amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
    status VARCHAR(20) NOT NULL,
    response_json VARCHAR(500),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX ix_charges_idempotency_key ON charges(idempotency_key);
CREATE INDEX ix_charges_order_id ON charges(order_id);
```

### `messages` Table (`notification_db`)
```sql
CREATE TABLE messages (
    id SERIAL PRIMARY KEY,
    order_id VARCHAR(64) NOT NULL UNIQUE,
    recipient VARCHAR(120) NOT NULL,
    content VARCHAR(250) NOT NULL,
    channel VARCHAR(30) NOT NULL DEFAULT 'email',
    status VARCHAR(20) NOT NULL DEFAULT 'RECORDED',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX ix_messages_order_id ON messages(order_id);
```

---

## 3. Payment Charge State & Idempotency Transition Machine

```mermaid
stateDiagram-v2
    [*] --> PROCESSING : POST /api/v1/payments (Idempotency-Key)
    PROCESSING --> SUCCEEDED : Default / simulate="success"
    PROCESSING --> DECLINED : simulate="decline" / reject mode
    PROCESSING --> TIMED_OUT : simulate="slow" (sleep 2.0s > client timeout 0.7s)
    
    SUCCEEDED --> SUCCEEDED : Replay identical key & body (HTTP 200/201, BR5)
    DECLINED --> DECLINED : Replay identical key & body (HTTP 200/201, BR5)
    
    SUCCEEDED --> KEY_CONFLICT : Replay identical key with different body (HTTP 409)
    DECLINED --> KEY_CONFLICT : Replay identical key with different body (HTTP 409)
    
    TIMED_OUT --> RECONCILED : Client GET /api/v1/payments/by-key/{key} (Safe Recovery)
```

---

## 4. Challenge 3A Sequence Diagram: Timeout, Retry & Reconciliation

```mermaid
sequenceDiagram
    autonumber
    actor Client
    participant Order as Order Service (8002)
    participant Inventory as Inventory Service (8001)
    participant Payment as Payment Service (8003)
    participant Notification as Notification Service (8004)

    Client->>Order: POST /api/v1/orders (Idempotency-Key: chk-1)
    Order->>Inventory: POST /api/v1/stock/reserve
    Inventory-->>Order: 201 Created (hold_id: 1, status: HELD)
    Order->>Order: Set status = PAYMENT_PENDING

    rect rgb(255, 240, 240)
    Note over Order,Payment: Transient Network Delay (Challenge 3A)
    Order->>Payment: POST /api/v1/payments (Idempotency-Key: pay-ord-1, simulate="slow")
    Note over Payment: Payment persists charge (SUCCEEDED)<br/>Simulates 2.0s delay
    Note over Order: Order client timeout fired at 0.7s!
    Order->>Order: Retry #1 (Backoff 0.2s + jitter)
    Order->>Payment: POST /api/v1/payments (Same key: pay-ord-1)
    end

    rect rgb(240, 255, 240)
    Note over Order,Payment: Safe Read-Only GET Reconciliation
    Order->>Payment: GET /api/v1/payments/by-key/pay-ord-1
    Payment-->>Order: 200 OK (status: SUCCEEDED, payment_id: 1)
    end

    Order->>Inventory: POST /api/v1/stock/1/confirm
    Inventory-->>Order: 200 OK (status: CONFIRMED)
    Order->>Order: Set status = CONFIRMED

    rect rgb(245, 245, 255)
    Note over Order,Notification: Best-effort Non-blocking Notification (BR6)
    Order->>Notification: POST /api/v1/notifications
    Notification-->>Order: 201 Created (status: RECORDED)
    end

    Order-->>Client: 201 Created (order_id: ord-1, status: CONFIRMED)
```
