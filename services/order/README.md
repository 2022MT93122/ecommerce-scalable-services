# Order service

Owns checkout orchestration, stored idempotency results, order state and explicit recovery. Calls Inventory, Payment and Notification only over HTTP; no other service's database is accessed.

## Run and verify

From the repository root, start the existing stack with `docker compose up --build -d`. Order listens on host port 8002. Open `http://localhost:8002/docs` or `http://localhost:8002/openapi.json`.

For standalone Python execution (Python 3.9+):

```bash
cd services/order
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# Export DATABASE_URL and downstream URLs using .env.example as a reference.
uvicorn app.main:app --host 0.0.0.0 --port 8002
```

Without DATABASE_URL, Order uses its own local SQLite file. `.env.example` is documentation, not automatically loaded. Existing tables remain compatible: startup adds `checkout_records` without changing `orders` columns. Startup fails if schema initialization fails; health checks execute SELECT 1.

Run tests from this service directory in a separate process. All services use a package named `app`, so collecting them together from the repository root causes import collisions.

```bash
python -m pytest -q
python scripts/verify.py
```

The live script requires all four services, creates demo products/orders, asserts simultaneous requests return the same result, verifies replay and changed-payload rejection, and checks stock after success/decline/slow payment. Override INVENTORY_URL and ORDER_URL for alternate ports.

For an actual stopped-Payment demonstration, from the repository root:

```bash
docker compose stop payment
python services/order/scripts/verify.py --payment-outage
docker compose start payment
python services/order/scripts/verify.py --reconcile ORDER_ID_FROM_OUTPUT
```

## API and business rules

- `POST /api/v1/orders`: mandatory Idempotency-Key (1-120 characters). A unique database key prevents duplicate orders. SHA-256 of the canonical validated request detects changed payloads (BR3, BR4). Concurrent insertion conflicts are handled explicitly, not by catching every database error.
- Duplicate requests wait up to REPLAY_WAIT for the winner's stored response. Completed responses are immutable replays. When processing exceeds that bound, a duplicate receives a 202 snapshot for the same order; it does not run downstream work again. GET returns current state after reconciliation, while POST retains the original response.
- `GET /api/v1/orders/{id}`: inspect current state.
- `POST /api/v1/orders/{id}/reconcile`: retry pending inventory reservation, lookup/retry pending payments, or complete pending stock confirmation/release. Uses the original persisted simulation mode and stable payment key `pay-{order_id}`.
- Positive product ID, quantity and amount; recipient length 3-120; simulation success/decline/slow. Errors share `{error: {code, message}, request_id}` and correlation headers.
- Notification failures are logged after confirmation is committed; they cannot undo a paid order (BR6). Delivery remains synchronous best effort, not a queue.

## State and failure handling

| Current state | Allowed next states |
| --- | --- |
| PENDING | INVENTORY_PENDING, PAYMENT_PENDING, OUT_OF_STOCK |
| INVENTORY_PENDING | PAYMENT_PENDING, OUT_OF_STOCK |
| PAYMENT_PENDING | STOCK_CONFIRM_PENDING, CONFIRMED, RELEASE_PENDING, FAILED |
| STOCK_CONFIRM_PENDING | CONFIRMED |
| RELEASE_PENDING | FAILED |

CONFIRMED, FAILED and OUT_OF_STOCK are terminal. Repeat transitions to the same state are safe. Payment transport/HTTP failures have bounded attempts with exponential backoff and jitter, followed by lookup. An unknown outcome remains PAYMENT_PENDING; it is never assumed declined. An explicit decline releases stock. Failed confirmation/release remains recoverable. Malformed successful downstream responses retain a pending state.

## Configuration

DATABASE_URL and INVENTORY_URL / PAYMENT_URL / NOTIFICATION_URL are shown in `.env.example`. PAYMENT_TIMEOUT defaults to 0.7 seconds for downstream HTTP. PAYMENT_ATTEMPTS defaults to 3, RETRY_BACKOFF to 0.1 seconds, and REPLAY_WAIT to 10 seconds. Order's container supports PORT, default 8000. Compose maps 8002 to the default internal port.

## Verification and limits

Tests cover BR3/BR4/BR6, forced concurrent identical/different key conflicts, original response persistence, stable retry keys, dependency transport/HTTP outages, compensation, notification failure, state transitions, validation, OpenAPI and DB health. Tests use temporary SQLite databases and mocked downstream responses. See `evidence/` for captured results; a local HTTP run is not proof of PostgreSQL deployment behavior.

Reconciliation has no cross-process serialization and must have one caller per order; do not reconcile an actively running checkout. There is no recovery scheduler or notification outbox. Legacy orders without checkout_records cannot safely recreate an unknown payment payload, so recovery only finalizes known outcomes rather than guessing simulation settings. Client-supplied amounts are a demo assumption. Strict byte-identical responses for requests exceeding REPLAY_WAIT are not guaranteed. Inventory's confirm/release concurrency behavior belongs to Inventory and is outside this change.
