import os
import sys
from pathlib import Path
import pytest

# Ensure app is discoverable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Use in-memory SQLite with StaticPool so all connections share the same memory DB
test_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(bind=test_engine, expire_on_commit=False)

from app.db import Base, get_db
from app.main import app, Product, Hold


def override_get_db():
    with TestingSessionLocal() as db:
        yield db


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_database():
    Base.metadata.drop_all(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)
    yield
    Base.metadata.drop_all(bind=test_engine)


def test_health_check():
    """Verify inventory service health check."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "inventory"}


def test_create_and_get_product():
    """Verify creating and retrieving product catalog items."""
    res = client.post(
        "/api/v1/products",
        json={"name": "Gaming Mechanical Keyboard", "price_cents": 200000, "available": 10},
    )
    assert res.status_code == 201
    p = res.json()
    assert p["id"] is not None
    assert p["name"] == "Gaming Mechanical Keyboard"
    assert p["price_cents"] == 200000
    assert p["available"] == 10

    # Retrieve by ID
    get_res = client.get(f"/api/v1/products/{p['id']}")
    assert get_res.status_code == 200
    assert get_res.json()["available"] == 10


def test_br1_atomic_reserve_prevents_oversell():
    """
    BR1: Stock never negative.
    Verify that when stock is exhausted, reservation returns 409 OUT_OF_STOCK
    and stock count remains exactly 0 (never negative).
    """
    res = client.post(
        "/api/v1/products",
        json={"name": "Limited Edition Mouse", "price_cents": 50000, "available": 2},
    )
    prod_id = res.json()["id"]

    # First reserve: take all 2 available units
    res1 = client.post(
        "/api/v1/stock/reserve",
        json={"order_id": "order-br1-001", "product_id": prod_id, "quantity": 2},
    )
    assert res1.status_code == 201
    assert res1.json()["status"] == "HELD"

    # Verify available stock is now 0
    p = client.get(f"/api/v1/products/{prod_id}").json()
    assert p["available"] == 0

    # Second reserve: request 1 more unit -> must fail with 409 OUT_OF_STOCK
    res2 = client.post(
        "/api/v1/stock/reserve",
        json={"order_id": "order-br1-002", "product_id": prod_id, "quantity": 1},
    )
    assert res2.status_code == 409
    detail = res2.json()["detail"]
    assert detail["error"]["code"] == "OUT_OF_STOCK"

    # Verify stock never became negative
    final_p = client.get(f"/api/v1/products/{prod_id}").json()
    assert final_p["available"] == 0


def test_reserve_idempotency_same_order():
    """Repeating an identical stock reservation for the same order_id is safe and idempotent."""
    res = client.post(
        "/api/v1/products",
        json={"name": "Keycaps Set", "price_cents": 30000, "available": 5},
    )
    prod_id = res.json()["id"]

    body = {"order_id": "order-idem-001", "product_id": prod_id, "quantity": 2}
    res1 = client.post("/api/v1/stock/reserve", json=body)
    assert res1.status_code == 201
    hold_id = res1.json()["hold_id"]

    # Replay same reservation
    res2 = client.post("/api/v1/stock/reserve", json=body)
    assert res2.status_code == 201
    assert res2.json()["hold_id"] == hold_id

    # Stock should have only been deducted ONCE (5 - 2 = 3)
    p = client.get(f"/api/v1/products/{prod_id}").json()
    assert p["available"] == 3


def test_reserve_conflict_different_payload():
    """Reusing order_id with different payload parameters must return 409 Conflict."""
    res = client.post(
        "/api/v1/products",
        json={"name": "Desk Mat", "price_cents": 15000, "available": 5},
    )
    prod_id = res.json()["id"]

    res1 = client.post(
        "/api/v1/stock/reserve",
        json={"order_id": "order-conflict-001", "product_id": prod_id, "quantity": 1},
    )
    assert res1.status_code == 201

    # Replay same order_id with quantity: 2
    res2 = client.post(
        "/api/v1/stock/reserve",
        json={"order_id": "order-conflict-001", "product_id": prod_id, "quantity": 2},
    )
    assert res2.status_code == 409
    data = res2.json()
    assert "error" in data
    assert data["error"]["code"] == "BUSINESS_CONFLICT"


def test_br2_confirmed_hold_cannot_be_released():
    """
    BR2: Confirmed hold cannot be released.
    Once payment is confirmed, an attempt to release the hold must be rejected with 409 Conflict.
    """
    res = client.post(
        "/api/v1/products",
        json={"name": "Wireless Headset", "price_cents": 120000, "available": 3},
    )
    prod_id = res.json()["id"]

    # 1. Reserve 1 unit
    res_hold = client.post(
        "/api/v1/stock/reserve",
        json={"order_id": "order-br2-001", "product_id": prod_id, "quantity": 1},
    )
    assert res_hold.status_code == 201
    hold_id = res_hold.json()["hold_id"]

    # 2. Confirm hold (payment succeeded)
    res_confirm = client.post(f"/api/v1/stock/{hold_id}/confirm")
    assert res_confirm.status_code == 200
    assert res_confirm.json()["status"] == "CONFIRMED"

    # 3. Attempt release -> Must fail because hold is CONFIRMED
    res_release = client.post(f"/api/v1/stock/{hold_id}/release")
    assert res_release.status_code == 409
    err = res_release.json()["error"]
    assert err["code"] == "BUSINESS_CONFLICT"
    assert "Confirmed stock cannot be released" in err["message"]

    # Stock must NOT be restored (3 - 1 = 2)
    p = client.get(f"/api/v1/products/{prod_id}").json()
    assert p["available"] == 2


def test_release_held_stock_restores_inventory():
    """Releasing an active hold restores stock and is idempotent."""
    res = client.post(
        "/api/v1/products",
        json={"name": "USB Hub", "price_cents": 25000, "available": 5},
    )
    prod_id = res.json()["id"]

    # Reserve 2 units
    res_hold = client.post(
        "/api/v1/stock/reserve",
        json={"order_id": "order-rel-001", "product_id": prod_id, "quantity": 2},
    )
    hold_id = res_hold.json()["hold_id"]
    assert client.get(f"/api/v1/products/{prod_id}").json()["available"] == 3

    # Release hold (e.g. payment failed)
    res_release = client.post(f"/api/v1/stock/{hold_id}/release")
    assert res_release.status_code == 200
    assert res_release.json()["status"] == "RELEASED"

    # Stock is restored to 5
    assert client.get(f"/api/v1/products/{prod_id}").json()["available"] == 5

    # Safe repeated release (idempotent no-op)
    res_release2 = client.post(f"/api/v1/stock/{hold_id}/release")
    assert res_release2.status_code == 200
    assert res_release2.json()["status"] == "RELEASED"
    assert client.get(f"/api/v1/products/{prod_id}").json()["available"] == 5


def test_released_hold_cannot_be_confirmed():
    """A released hold cannot be transitioned to CONFIRMED."""
    res = client.post(
        "/api/v1/products",
        json={"name": "HDMI Cable", "price_cents": 10000, "available": 5},
    )
    prod_id = res.json()["id"]

    res_hold = client.post(
        "/api/v1/stock/reserve",
        json={"order_id": "order-relconf-001", "product_id": prod_id, "quantity": 1},
    )
    hold_id = res_hold.json()["hold_id"]

    # Release
    client.post(f"/api/v1/stock/{hold_id}/release")

    # Confirm released hold -> Must fail with 409
    res_confirm = client.post(f"/api/v1/stock/{hold_id}/confirm")
    assert res_confirm.status_code == 409
    assert "Released hold cannot be confirmed" in res_confirm.json()["error"]["message"]
