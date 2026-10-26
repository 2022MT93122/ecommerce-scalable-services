from concurrent.futures import ThreadPoolExecutor
import uuid
import requests

p = requests.post(
    "http://localhost:8001/api/v1/products",
    json={"name": "Idempotency Sample", "price_cents": 999, "available": 5},
    timeout=10,
).json()

key = str(uuid.uuid4())
body = {
    "product_id": p["id"],
    "quantity": 1,
    "amount_cents": 999,
    "recipient": "student@example.com",
}


def send(payload):
    r = requests.post(
        "http://localhost:8002/api/v1/orders",
        json=payload,
        headers={"Idempotency-Key": key},
        timeout=20,
    )
    return r.status_code, r.json()


with ThreadPoolExecutor(max_workers=2) as pool:
    answers = list(pool.map(send, [body, body]))

print("Simultaneous:", answers)
assert answers[0][1]["order_id"] == answers[1][1]["order_id"]
print("Replay:", send(body))
changed = {**body, "quantity": 2}
print("Different payload:", send(changed))
assert send(changed)[0] == 409
orders = {x[1]["order_id"] for x in answers}
assert len(orders) == 1
print("PASS: one logical order")
