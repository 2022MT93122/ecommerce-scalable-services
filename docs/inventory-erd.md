# Inventory Service - Data Model and ER Diagram

**Owner**: Dr. Sunanda Pandita (Inventory Service Lead)  
**Course**: BITS Pilani WILP - Scalable Services (SEZG583)  
**Database**: `inventory_db` (Isolated PostgreSQL database)

---

## 1. Entity-Relationship Diagram

```mermaid
erDiagram
    PRODUCTS ||--o{ HOLDS : "reserves"
    PRODUCTS {
        int id PK "Auto-incrementing product identifier"
        string name "Product title / descriptor (120 chars)"
        int price_cents "Unit price in INR paise (e.g. 200000 = Rs 2,000)"
        int available "Currently available stock count (CHECK >= 0)"
    }
    HOLDS {
        int id PK "Auto-incrementing hold identifier"
        string order_id UK "Unique external order correlation ID"
        int product_id FK "Foreign key reference to products.id"
        int quantity "Requested quantity reserved"
        string status "Reservation state: HELD, CONFIRMED, RELEASED"
    }
```

---

## 2. Relational Schema Definitions

### `products` Table
```sql
CREATE TABLE products (
    id SERIAL PRIMARY KEY,
    name VARCHAR(120) NOT NULL,
    price_cents INTEGER NOT NULL CHECK (price_cents > 0),
    available INTEGER NOT NULL CHECK (available >= 0)
);
```

### `holds` Table (Stock Reservations)
```sql
CREATE TABLE holds (
    id SERIAL PRIMARY KEY,
    order_id VARCHAR(64) NOT NULL UNIQUE,
    product_id INTEGER NOT NULL REFERENCES products(id),
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    status VARCHAR(20) NOT NULL DEFAULT 'HELD'
);
```

---

## 3. Hold State Machine

```mermaid
stateDiagram-v2
    [*] --> HELD : reserve() with stock available
    [*] --> OUT_OF_STOCK : reserve() when available < qty
    HELD --> CONFIRMED : confirm() called after payment SUCCEEDED
    HELD --> RELEASED : release() called after payment DECLINED / TIMEOUT
    CONFIRMED --> REJECTED : release() called (Illegal Transition - BR2)
    RELEASED --> RELEASED : repeated release() (Idempotent No-op)
    CONFIRMED --> CONFIRMED : repeated confirm() (Idempotent No-op)
```

### State Definitions
1. **HELD**: Stock has been conditionally deducted from `available` in an atomic SQL statement and reserved specifically for `order_id`.
2. **CONFIRMED**: Payment succeeded downstream. The stock is permanently allocated to the customer order. Transition to `RELEASED` is permanently blocked (BR2).
3. **RELEASED**: Order was canceled or payment failed. Stock is incremented back into `products.available`. Further attempts to confirm or re-release are safely handled.
