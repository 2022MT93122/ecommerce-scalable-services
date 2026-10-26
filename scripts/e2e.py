import uuid
import requests

BASE = "http://localhost:8001"
p = requests.post(
    f"{BASE}/api/v1/products",
    json={"name": "Demo Keyboard", "price_cents": 200000, "available": 5},
    timeout=10,
).json()

body = {
    "product_id": p["id"],
    "quantity": 1,
    "amount_cents": 200000,
    "recipient": "demo@example.com",
}
r = requests.post(
    "http://localhost:8002/api/v1/orders",
    json=body,
    headers={"Idempotency-Key": str(uuid.uuid4())},
    timeout=20,
)
print("Checkout:", r.status_code, r.json())
assert r.status_code == 201
assert r.json()["status"] == "CONFIRMED", "Expected confirmed booking"
print("PASS: 1 confirmed order")
