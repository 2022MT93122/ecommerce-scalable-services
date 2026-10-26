import uuid
import requests

p = requests.post(
    "http://localhost:8001/api/v1/products",
    json={"name": "Slow Payment Sample", "price_cents": 750, "available": 2},
    timeout=10,
).json()

body = {
    "product_id": p["id"],
    "quantity": 1,
    "amount_cents": 750,
    "recipient": "student@example.com",
    "simulate": "slow",
}

r = requests.post(
    "http://localhost:8002/api/v1/orders",
    headers={"Idempotency-Key": str(uuid.uuid4())},
    json=body,
    timeout=20,
)
print("Checkout under simulated slow payment:", r.json())
order_id = r.json()["order_id"]
status = requests.get(f"http://localhost:8002/api/v1/orders/{order_id}", timeout=10).json()
print("Final / pending status:", status)
assert status["status"] in ("PAYMENT_PENDING", "CONFIRMED", "STOCK_CONFIRM_PENDING")
print("PASS: no invented failed payment; reconcile later if pending")
