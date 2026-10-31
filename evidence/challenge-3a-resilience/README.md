# Challenge 3A Evidence: Resilience, Timeouts & Payment Reconciliation

**Lead Owner**: Meghana Toutam (Payment & Notification Service Lead)  
**Co-Owner**: Tarun (Order Service Lead & Integration)  
**Evaluator Reference**: BITS Pilani WILP - Scalable Services (SEZG583) Assignment 1  
**GitHub Branch**: `feature/payment-notification`  

---

## 1. Challenge Objective & Invariants (BR5 & BR6)

In a distributed microservice architecture, network communication between independent boundaries is inherently unreliable. This challenge demonstrates how our system implements **resilient transaction choreography** when downstream dependencies suffer from:
1. **Network Latency / Slow Responses (Transient Delays)**: Downstream payment gateways experiencing high response latencies.
2. **Timeouts & Client Retries with Exponential Backoff + Jitter**: Order orchestration capping payment requests to a tight timeout (0.7s) and retrying up to 3 times without creating duplicate charges.
3. **Safe In-Doubt Reconciliation via GET-by-key**: A timed-out request must **never** be presumed failed. Reconciling via `GET /api/v1/payments/by-key/{key}` allows safely recovering payment status before proceeding to stock confirmation.
4. **Definite Failure Isolation**: A definitive rejection (`simulate="decline"`) immediately halts the workflow, triggers compensatory stock release, and transitions the order to `FAILED`.
5. **BR5 — Payment Key Charges Once**: Idempotency keys (`pay-{order_id}`) stored with a PostgreSQL unique constraint ensure sequential and concurrent duplicate attempts return the original charge record without secondary debiting. Conflicting payloads return HTTP `409 Conflict`.
6. **BR6 — Notification Failure Cannot Cancel Paid Order**: Outbound notifications are executed best-effort. Gateway drops or HTTP 500 errors are logged but strictly prohibited from rolling back a confirmed financial charge.

---

## 2. Evidence Files Index

| File | Purpose / Description |
|------|------------------------|
| [`README.md`](file:///c:/Meghana/ecommerce-scalable-services/evidence/challenge-3a-resilience/README.md) | Technical architecture overview, failure mode analysis, and invariant explanations. |
| [`run-log.txt`](file:///c:/Meghana/ecommerce-scalable-services/evidence/challenge-3a-resilience/run-log.txt) | Complete execution transcript of `scripts/resilience.py` with timestamps, HTTP statuses, and assertion validations. |
| [`payment-logs.txt`](file:///c:/Meghana/ecommerce-scalable-services/evidence/challenge-3a-resilience/payment-logs.txt) | Structured service-side JSON correlation logs from the Payment and Notification services detailing requests, delays, and reconciliations. |
| [`resilience-proof.txt`](file:///c:/Meghana/ecommerce-scalable-services/evidence/challenge-3a-resilience/resilience-proof.txt) | Database state verification proving exactly one payment record was persisted per order ID with zero double charges. |
| `../../scripts/resilience.py` | Automated multi-phase test script driving slow payment, retry backoff, decline rollback, and notification fault injection. |

---

## 3. Distributed Systems Deep-Dive: Why Timeouts Cannot Be Treated as Failures

### The Two-Generals Problem & In-Doubt Transactions
In synchronous HTTP calls between Order and Payment:
$$\text{Order Service} \xrightarrow{\text{POST /payments (timeout=0.7s)}} \text{Payment Gateway}$$

When a timeout occurs after 0.7 seconds, three distinct real-world situations are indistinguishable to the client:
1. The request was dropped on the wire before reaching the payment service (Payment was never processed).
2. The payment service received the request, charged the customer, but the network connection died before the HTTP 201 response reached the caller (Payment succeeded).
3. The payment service is experiencing heavy garbage collection or database contention and is still actively writing the record (Payment is in-flight).

### Our Solution: Stable Idempotency Keys + Explicit Reconciliation
1. **Stable Key Construction**: Order service generates a deterministic payment idempotency key:
   $$\text{Idempotency-Key} = \text{"pay-" } + \text{order.id}$$
   Every subsequent retry transmits the identical key and identical JSON body fingerprint.
2. **Bounded Exponential Backoff with Jitter**:
   Retries occur with intervals $t = 0.1 \times 2^i + \text{Uniform}(0, 0.04)\text{ seconds}$.
3. **Safe Read-Only GET Reconciliation**:
   Before abandoning an order, the orchestrator issues:
   $$\text{GET /api/v1/payments/by-key/pay-}\{order\_id\}$$
   Because `GET` is idempotent and read-only, it safely recovers the state (`SUCCEEDED` or `DECLINED`) without causing a double charge. If still indeterminate, the order remains in `PAYMENT_PENDING` for asynchronous reconciliation rather than prematurely cancelling a customer's purchase.

---

## 4. Verification Summary

```
===========================================================================
CHALLENGE 3A: RESILIENCE & RECONCILIATION VERIFICATION
===========================================================================
[✓] Step 1: Health Probes for all 4 microservices operational (HTTP 200).
[✓] Step 2: BR5 Verified — Idempotent replay returns same payment ID; payload conflict rejected (HTTP 409).
[✓] Step 3: Challenge 3A Slow Payment Verified — Client timeout handled gracefully, GET reconciliation resolves to CONFIRMED.
[✓] Step 4: Definite Failure Verified — Simulated decline releases inventory and sets order to FAILED.
[✓] Step 5: BR6 Verified — Notification gateway failure (HTTP 500) does not cancel paid order.
===========================================================================
```
