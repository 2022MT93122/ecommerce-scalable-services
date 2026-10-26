import requests

BASE = "http://localhost:8001"
p = requests.post(
    f"{BASE}/api/v1/products",
    json={"name": "Mechanical Keyboard", "price_cents": 200000, "available": 5},
    timeout=10,
)
p.raise_for_status()
print("Seeded product:", p.json())
