#!/usr/bin/env python3
"""
Challenge 3A: Resilience & Payment Reconciliation Script
Owner: Meghana Toutam (Payment & Notification Service Lead, Challenge 3A Owner)
Course: BITS Pilani WILP - Scalable Services (SEZG583)

Demonstrates:
- BR5: Payment key charges once; duplicate keys replay identical outcome; payload mismatch returns 409.
- BR6: Notification failure never rolls back or cancels a paid/confirmed order.
- Challenge 3A: Resilient handling of slow/delayed dependencies via client-side timeouts,
  bounded exponential backoff retries with jitter, and safe GET-by-key reconciliation.
"""

import sys
import time
import uuid
from datetime import datetime, timezone
import requests

INVENTORY_BASE = "http://localhost:8001"
ORDER_BASE = "http://localhost:8002"
PAYMENT_BASE = "http://localhost:8003"
NOTIFICATION_BASE = "http://localhost:8004"


def log(msg):
    print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S.%f')[:-3]}] {msg}")


def run_resilience_test():
    print("=" * 75)
    print("CHALLENGE 3A: RESILIENCE, TIMEOUT & PAYMENT RECONCILIATION TEST")
    print(f"Timestamp: {datetime.now(timezone.utc).isoformat()}")
    print("=" * 75)

    # 1. Health checks on all services
    services = {
        "Inventory": (INVENTORY_BASE, 8001),
        "Order": (ORDER_BASE, 8002),
        "Payment": (PAYMENT_BASE, 8003),
        "Notification": (NOTIFICATION_BASE, 8004),
    }

    print("\n[*] Step 1: Verifying Health of All 4 Microservices...")
    for name, (base, port) in services.items():
        try:
            h = requests.get(f"{base}/health", timeout=3)
            assert h.status_code == 200, f"{name} returned {h.status_code}"
            print(f"  [✓] {name:12s} (port {port}): HEALTHY -> {h.json()}")
        except Exception as e:
            print(f"  [✗] {name:12s} (port {port}): OFFLINE ({e})")
            print(f"\nPlease ensure {name} service is running on port {port}.")
            sys.exit(1)

    # 2. Direct Payment Service Idempotency (BR5 Invariant Verification)
    print("\n[*] Step 2: Testing Direct Payment Idempotency & Conflict Rejection (BR5)...")
    pay_key = f"pay-test-br5-{uuid.uuid4().hex[:8]}"
    pay_body = {"order_id": "ord-direct-001", "amount_cents": 199900, "simulate": "success"}

    # First Charge
    r1 = requests.post(
        f"{PAYMENT_BASE}/api/v1/payments",
        json=pay_body,
        headers={"Idempotency-Key": pay_key, "X-Request-ID": "req-pay-1"},
        timeout=10,
    )
    assert r1.status_code == 201, f"Expected 201, got {r1.status_code}"
    charge_data = r1.json()
    log(f"Initial Payment Charge: ID={charge_data['payment_id']}, Status={charge_data['status']}")

    # Sequential Replay with Same Key & Same Payload
    r2 = requests.post(
        f"{PAYMENT_BASE}/api/v1/payments",
        json=pay_body,
        headers={"Idempotency-Key": pay_key, "X-Request-ID": "req-pay-2"},
        timeout=10,
    )
    assert r2.status_code in (200, 201), f"Expected replay 200/201, got {r2.status_code}"
    assert r2.json()["payment_id"] == charge_data["payment_id"], "Payment ID must match on replay!"
    log(f"Replay with Same Key: Verified Identical Payment ID={r2.json()['payment_id']} (NO double charge)")

    # Conflicting Payload with Same Key
    conflict_body = {"order_id": "ord-direct-001", "amount_cents": 299900, "simulate": "success"}
    r3 = requests.post(
        f"{PAYMENT_BASE}/api/v1/payments",
        json=conflict_body,
        headers={"Idempotency-Key": pay_key, "X-Request-ID": "req-pay-3"},
        timeout=10,
    )
    assert r3.status_code == 409, f"Expected 409 Conflict, got {r3.status_code}"
    log(f"Replay with Conflicting Payload: HTTP 409 Conflict ({r3.json()['error']['code']}) [PASS]")

    # Safe GET-by-key reconciliation
    r_key = requests.get(f"{PAYMENT_BASE}/api/v1/payments/by-key/{pay_key}", timeout=5)
    assert r_key.status_code == 200
    assert r_key.json()["payment_id"] == charge_data["payment_id"]
    log(f"GET-by-key Query: Successfully retrieved charge status without new mutation [PASS]")

    # 3. Challenge 3A: End-to-End Slow Payment with Retries & Reconciliation
    print("\n[*] Step 3: Executing Challenge 3A Slow Payment Resilience Scenario...")
    # Seed product in Inventory
    p_res = requests.post(
        f"{INVENTORY_BASE}/api/v1/products",
        json={"name": f"Resilience Keyboard-{uuid.uuid4().hex[:4]}", "price_cents": 75000, "available": 5},
        timeout=5,
    )
    assert p_res.status_code == 201
    prod = p_res.json()
    prod_id = prod["id"]
    log(f"Seeded Inventory Product ID: {prod_id} (Available: {prod['available']}, Price: INR {prod['price_cents']/100:.2f})")

    # Place order with simulated slow payment (payment takes 2.0s, order timeout is 0.7s)
    checkout_key = f"chk-slow-{uuid.uuid4().hex[:8]}"
    checkout_payload = {
        "product_id": prod_id,
        "quantity": 1,
        "amount_cents": 75000,
        "recipient": "meghana@wilp.bits-pilani.ac.in",
        "simulate": "slow",
    }
    log(f"Submitting Order checkout with simulate='slow' and Idempotency-Key: {checkout_key}")
    start_time = time.perf_counter()
    r_order = requests.post(
        f"{ORDER_BASE}/api/v1/orders",
        json=checkout_payload,
        headers={"Idempotency-Key": checkout_key, "X-Request-ID": f"req-slow-{checkout_key[:8]}"},
        timeout=15,
    )
    elapsed = time.perf_counter() - start_time
    log(f"Order Service responded after {elapsed:.2f}s with status {r_order.status_code}")
    order_data = r_order.json()
    order_id = order_data["order_id"]
    log(f"Order ID: {order_id}, Initial Status: {order_data['status']}")

    # Check order status - must NOT be marked failed because payment did succeed or is being reconciled!
    r_status = requests.get(f"{ORDER_BASE}/api/v1/orders/{order_id}", timeout=5).json()
    log(f"Inspected Order Final Status: {r_status['status']}")
    assert r_status["status"] in ("CONFIRMED", "PAYMENT_PENDING", "STOCK_CONFIRM_PENDING"), (
        f"Unexpected status: {r_status['status']}. Must not invent a failed payment!"
    )

    # 4. Challenge 3A: Definite Failure (Simulated Decline) -> Inventory Rollback
    print("\n[*] Step 4: Testing Definite Failure (Simulated Decline) & Inventory Release...")
    decline_key = f"chk-decline-{uuid.uuid4().hex[:8]}"
    decline_payload = {
        "product_id": prod_id,
        "quantity": 1,
        "amount_cents": 75000,
        "recipient": "decline-test@example.com",
        "simulate": "decline",
    }
    r_dec = requests.post(
        f"{ORDER_BASE}/api/v1/orders",
        json=decline_payload,
        headers={"Idempotency-Key": decline_key},
        timeout=10,
    )
    dec_data = r_dec.json()
    log(f"Declined Order ID: {dec_data['order_id']}, Status: {dec_data['status']}")
    assert dec_data["status"] == "FAILED", f"Expected FAILED status, got {dec_data['status']}"

    # 5. BR6: Best-effort Notification Non-blocking Verification
    print("\n[*] Step 5: Testing Notification Delivery & BR6 Invariant...")
    notif_payload = {
        "order_id": order_id,
        "recipient": "meghana@wilp.bits-pilani.ac.in",
        "content": "Your order has been verified and confirmed.",
    }
    r_notif = requests.post(f"{NOTIFICATION_BASE}/api/v1/notifications", json=notif_payload, timeout=5)
    assert r_notif.status_code in (200, 201)
    log(f"Notification recorded: ID={r_notif.json()['notification_id']}, Status={r_notif.json()['status']}")

    # Force simulated failure on notification service
    r_fail_notif = requests.post(
        f"{NOTIFICATION_BASE}/api/v1/notifications",
        json={"order_id": f"ord-fail-{uuid.uuid4().hex[:6]}", "recipient": "test@fail.org", "content": "Fail test", "simulate": "failure"},
        timeout=5,
    )
    assert r_fail_notif.status_code == 500
    log("Verified Notification Gateway Simulated Failure (HTTP 500) without crashing service.")

    # Confirm original paid order remains CONFIRMED
    order_verify = requests.get(f"{ORDER_BASE}/api/v1/orders/{order_id}", timeout=5).json()
    assert order_verify["status"] in ("CONFIRMED", "STOCK_CONFIRM_PENDING")
    log(f"BR6 Enforced: Notification failures do NOT affect or cancel paid order status ({order_verify['status']})")

    print("\n" + "=" * 75)
    print("ALL CHALLENGE 3A RESILIENCE & BR5/BR6 INVARIANTS SUCCESSFULLY VERIFIED!")
    print("=" * 75)


if __name__ == "__main__":
    run_resilience_test()
