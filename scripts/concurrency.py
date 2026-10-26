#!/usr/bin/env python3
"""
Challenge 1: Concurrency Validation Script
Owner: Dr. Sunanda Pandita (Inventory Service Lead)
Course: BITS Pilani WILP - Scalable Services (SEZG583)

Demonstrates BR1: Atomic conditional stock reservation prevents overselling under heavy concurrency.
Scenario:
- 1 product seeded with available_stock = 5
- 20 competing concurrent threads issue reservation requests for 1 unit each with unique order IDs
- Invariant assertions: Exactly 5 succeed (201 Created), 15 rejected (409 Conflict OUT_OF_STOCK)
- Final stock must equal exactly 0 (no overselling, never negative)
"""

import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import requests

BASE = "http://localhost:8001"


def run_concurrency_test():
    print("=" * 70)
    print("CHALLENGE 1: CONCURRENT STOCK RESERVATION TEST")
    print(f"Timestamp: {datetime.now(timezone.utc).isoformat()}")
    print(f"Target Service: {BASE}")
    print("=" * 70)

    # 1. Health check
    try:
        h = requests.get(f"{BASE}/health", timeout=5)
        print(f"[*] Health Check: HTTP {h.status_code} -> {h.json()}")
        assert h.status_code == 200, "Inventory service is not healthy!"
    except Exception as e:
        print(f"[!] Cannot connect to {BASE}: {e}")
        print("Please ensure Inventory Service is running on port 8001.")
        sys.exit(1)

    # 2. Seed initial product with stock = 5
    initial_stock = 5
    prod_payload = {
        "name": f"Mechanical Keyboard (Batch-{uuid.uuid4().hex[:6]})",
        "price_cents": 200000,
        "available": initial_stock,
    }
    p_res = requests.post(f"{BASE}/api/v1/products", json=prod_payload, timeout=10)
    assert p_res.status_code == 201, f"Failed to create product: {p_res.text}"
    product = p_res.json()
    product_id = product["id"]
    print(f"\n[+] Created Test Product ID: {product_id}")
    print(f"    Name: {product['name']}")
    print(f"    Initial Stock: {product['available']} units")
    print(f"    Price: INR {product['price_cents'] / 100:.2f}")

    # 3. Launch 20 concurrent requests
    num_requests = 20
    print(f"\n[*] Dispatching {num_requests} concurrent reservation requests (1 unit each)...")
    print("-" * 70)

    def attempt_reservation(index):
        order_id = f"ord-burst-{index:02d}-{uuid.uuid4().hex[:8]}"
        req_id = f"req-c1-{index:02d}"
        payload = {"order_id": order_id, "product_id": product_id, "quantity": 1}
        headers = {"X-Request-ID": req_id, "X-Correlation-ID": req_id}
        start_t = time.perf_counter()
        resp = requests.post(
            f"{BASE}/api/v1/stock/reserve",
            json=payload,
            headers=headers,
            timeout=15,
        )
        elapsed = (time.perf_counter() - start_t) * 1000
        return {
            "index": index,
            "order_id": order_id,
            "status_code": resp.status_code,
            "elapsed_ms": elapsed,
            "response": resp.json() if resp.status_code in (200, 201, 409) else resp.text,
        }

    results = []
    with ThreadPoolExecutor(max_workers=num_requests) as pool:
        futures = [pool.submit(attempt_reservation, i) for i in range(1, num_requests + 1)]
        for f in as_completed(futures):
            res = f.result()
            results.append(res)
            code = res["status_code"]
            tag = "SUCCESS" if code == 201 else "REJECTED (OUT_OF_STOCK)" if code == 409 else "UNEXPECTED"
            print(f"  Request #{res['index']:02d} | Order: {res['order_id']} | HTTP {code} ({tag}) in {res['elapsed_ms']:.1f}ms")

    # 4. Verify post-test state
    get_res = requests.get(f"{BASE}/api/v1/products", timeout=10)
    all_products = get_res.json()
    final_prod = next(x for x in all_products if x["id"] == product_id)

    success_count = sum(1 for r in results if r["status_code"] == 201)
    rejected_count = sum(1 for r in results if r["status_code"] == 409)
    other_count = sum(1 for r in results if r["status_code"] not in (201, 409))

    print("\n" + "=" * 70)
    print("CONCURRENCY TEST SUMMARY & INVARIANT VERIFICATION")
    print("=" * 70)
    print(f"Total Requests Dispatched : {num_requests}")
    print(f"Successful Reservations   : {success_count}  (Expected: 5)")
    print(f"Rejected Reservations     : {rejected_count} (Expected: 15)")
    print(f"Unexpected Responses      : {other_count}    (Expected: 0)")
    print(f"Initial Product Stock     : {initial_stock}")
    print(f"Final Available Stock     : {final_prod['available']}  (Expected: 0)")

    # Assertions
    assert success_count == 5, f"Expected 5 successes, got {success_count}"
    assert rejected_count == 15, f"Expected 15 rejections, got {rejected_count}"
    assert other_count == 0, f"Expected 0 other errors, got {other_count}"
    assert final_prod["available"] == 0, f"Expected 0 final stock, got {final_prod['available']}"

    print("\n[✓] PASS: All concurrency invariants verified!")
    print("[✓] BR1 Enforced: Stock never dropped below zero (No overselling).")
    print("=" * 70)


if __name__ == "__main__":
    run_concurrency_test()
