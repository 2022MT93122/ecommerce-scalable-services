# Order verification evidence

- `unit-tests.txt`: actual pytest output for 30 Order tests. Covers BR3 and BR4, simultaneous identical/different requests forced past the first SELECT, original response persistence, bounded replay waiting, BR6, compensation, pending recovery, malformed downstream responses, stable retry payloads, backoff, validation, OpenAPI and database health.
- `http-verification.txt`: actual HTTP output from four temporary Uvicorn processes using separate SQLite databases on ports 18001-18004. Shows identical simultaneous checkout responses for success, decline and slow payment; replay and changed-payload assertions; stock checks; Payment process stop/restart; and reconciliation of the same pending order to CONFIRMED.

Reproduce unit tests with `python -m pytest -q` from `services/order`. Reproduce live checks using `python services/order/scripts/verify.py` from the repository root against the running four-service stack. See the service README for the stopped-Payment commands.

These files do not claim Docker, PostgreSQL or Kubernetes verification. Complete PostgreSQL runs and SQL-state evidence before making deployment-specific concurrency claims. Other services were used as dependencies without changing their source code.
