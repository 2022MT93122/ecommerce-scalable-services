import sys
from pathlib import Path
import pytest

# Ensure app is discoverable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

test_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(bind=test_engine, expire_on_commit=False)

from app.db import Base, get_db
from app.main import app, Message


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
    """Verify Notification service health endpoint."""
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok", "service": "notification"}


def test_create_notification_success():
    """Verify recording a notification for a confirmed order."""
    payload = {
        "order_id": "ord-notif-001",
        "recipient": "customer@example.com",
        "content": "Your order ord-notif-001 has been confirmed!",
        "channel": "email",
        "simulate": "success",
    }
    res = client.post("/api/v1/notifications", json=payload)
    assert res.status_code == 201
    d = res.json()
    assert d["order_id"] == "ord-notif-001"
    assert d["recipient"] == "customer@example.com"
    assert d["status"] == "RECORDED"
    assert "notification_id" in d


def test_notification_idempotency_same_order():
    """BR6 Helper: Repeated notifications for the same order return existing record without duplication."""
    payload = {
        "order_id": "ord-notif-002",
        "recipient": "customer2@example.com",
        "content": "Your order is confirmed",
    }
    res1 = client.post("/api/v1/notifications", json=payload)
    assert res1.status_code == 201
    nid1 = res1.json()["notification_id"]

    res2 = client.post("/api/v1/notifications", json=payload)
    assert res2.status_code in (200, 201)
    nid2 = res2.json()["notification_id"]
    assert nid1 == nid2

    with TestingSessionLocal() as db:
        count = len(db.scalars(select(Message).where(Message.order_id == "ord-notif-002")).all())
        assert count == 1


def test_get_notification_by_id():
    """Verify retrieval of notification by message ID."""
    payload = {
        "order_id": "ord-notif-003",
        "recipient": "vip@example.com",
        "content": "VIP Order Confirmation",
    }
    res = client.post("/api/v1/notifications", json=payload)
    nid = res.json()["notification_id"]

    res_get = client.get(f"/api/v1/notifications/{nid}")
    assert res_get.status_code == 200
    assert res_get.json()["notification_id"] == nid
    assert res_get.json()["order_id"] == "ord-notif-003"


def test_get_notification_by_order():
    """Verify retrieval of notification by order ID."""
    payload = {
        "order_id": "ord-notif-004",
        "recipient": "user@test.org",
        "content": "Order dispatched",
    }
    client.post("/api/v1/notifications", json=payload)

    res_get = client.get("/api/v1/notifications/order/ord-notif-004")
    assert res_get.status_code == 200
    assert res_get.json()["order_id"] == "ord-notif-004"


def test_get_notification_not_found_404():
    """Verify 404 for unknown notification ID."""
    res = client.get("/api/v1/notifications/99999")
    assert res.status_code == 404


def test_simulated_notification_failure_500():
    """Verify forced failure simulation raises HTTP 500 without crashing service."""
    payload = {
        "order_id": "ord-notif-fail-01",
        "recipient": "fail@test.org",
        "content": "This will fail",
        "simulate": "failure",
    }
    res = client.post("/api/v1/notifications", json=payload)
    assert res.status_code == 500
    assert res.json()["error"]["code"] == "NOTIFICATION_GATEWAY_ERROR"


def test_simulated_env_var_notification_failure(monkeypatch):
    """Verify NOTIFICATION_SIMULATION_MODE=failure causes HTTP 500."""
    monkeypatch.setenv("NOTIFICATION_SIMULATION_MODE", "failure")
    payload = {
        "order_id": "ord-notif-fail-02",
        "recipient": "fail2@test.org",
        "content": "Env var simulated failure",
    }
    res = client.post("/api/v1/notifications", json=payload)
    assert res.status_code == 500
