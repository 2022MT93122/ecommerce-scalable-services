import pytest
import os
import tempfile
from fastapi.testclient import TestClient
from concurrent.futures import ThreadPoolExecutor
# Set temporary test database environment variable before importing app
db_file = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
db_file.close()
os.environ["DB_PATH"] = db_file.name
from src.main import app
from src.database import init_db, reset_product_stock, get_connection
@pytest.fixture(scope="module", autouse=True)
def setup_test_db():
    init_db(db_file.name)
    yield
    if os.path.exists(db_file.name):
        try:
            os.remove(db_file.name)
        except Exception:
            pass
@pytest.fixture
def client():
    return TestClient(app)
def test_health_check(client):
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "UP"
    assert data["service"] == "inventory-service"
    assert data["database"] == "healthy"
    assert "correlation_id" in data
def test_list_products(client):
    response = client.get("/api/v1/inventory/products")
    assert response.status_code == 200
    products = response.json()
    assert len(products) >= 3
    iphone = next(p for p in products if p["product_id"] == "PROD-IPHONE15")
    assert iphone["price"] == 999.0
def test_br1_stock_conservation_success_and_conflict(client):
    """
     Test Business Rule 1 (BR1): Stock Conservation Rule.
    Available stock must decrement accurately and over-allocation must be strictly rejected with 409.
    """
    # Reset iPhone stock to 2
    reset_product_stock("PROD-IPHONE15", 2, db_file.name)
    # 1. Reserve 1 unit (Should succeed)
    res1 = client.post("/api/v1/inventory/reserve", json={
        "product_id": "PROD-IPHONE15",
        "order_id": "ord-test-01",
        "quantity": 1
    })
    assert res1.status_code == 200
    data1 = res1.json()
    assert data1["remaining_available_stock"] == 1
    assert data1["status"] == "RESERVED"
    # 2. Reserve 1 unit (Should succeed)
    res2 = client.post("/api/v1/inventory/reserve", json={
        "product_id": "PROD-IPHONE15",
        "order_id": "ord-test-02",
        "quantity": 1
    })
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["remaining_available_stock"] == 0
    # 3. Reserve 1 more unit (Must fail with 409 CONFLICT - BR1 enforced)
    res3 = client.post("/api/v1/inventory/reserve", json={
        "product_id": "PROD-IPHONE15",
        "order_id": "ord-test-03",
        "quantity": 1
    })
    assert res3.status_code == 409
    err3 = res3.json()
    assert err3["error"]["code"] == "INSUFFICIENT_STOCK"
def test_saga_compensation_release_stock(client):
    """
    Test release compensation endpoint used by Challenge 3 Saga.
    """
     reset_product_stock("PROD-IPHONE15", 5, db_file.name)
    # Reserve 2 units
    res = client.post("/api/v1/inventory/reserve", json={
        "product_id": "PROD-IPHONE15",
        "order_id": "ord-comp-01",
        "quantity": 2
    })
    assert res.status_code == 200
    resv_id = res.json()["reservation_id"]
    assert res.json()["remaining_available_stock"] == 3
    # Release (Compensate)
    rel = client.post("/api/v1/inventory/release", json={
        "reservation_id": resv_id,
        "order_id": "ord-comp-01",
        "reason": "PAYMENT_FAILED"
    })
    assert rel.status_code == 200
    assert rel.json()["status"] == "RELEASED"
    assert rel.json()["restored_available_stock"] == 5
def test_concurrent_reservations_race_condition_prevention(client):
    """
    Challenge 1 unit test: 20 simultaneous threads requesting 1 item when capacity is 5.
    Exactly 5 must succeed and 15 must be rejected with 409. Available stock must end at 0.
    """
    reset_product_stock("PROD-IPHONE15", 5, db_file.name)
    def attempt_reservation(idx):
        return client.post("/api/v1/inventory/reserve", json={
            "product_id": "PROD-IPHONE15",
            "order_id": f"ord-concurrent-{idx}",
            "quantity": 1
        })
        with ThreadPoolExecutor(max_workers=20) as executor:
        responses = list(executor.map(attempt_reservation, range(20)))
    successes = [r for r in responses if r.status_code == 200]
    conflicts = [r for r in responses if r.status_code == 409]
    assert len(successes) == 5, f"Expected exactly 5 successes, got {len(successes)}"
    assert len(conflicts) == 15, f"Expected 15 conflicts, got {len(conflicts)}"
    # Check final database state
    prod_res = client.get("/api/v1/inventory/products/PROD-IPHONE15")
    assert prod_res.status_code == 200
    prod_data = prod_res.json()
    assert prod_data["available_stock"] == 0
    assert prod_data["reserved_stock"] == 5
    