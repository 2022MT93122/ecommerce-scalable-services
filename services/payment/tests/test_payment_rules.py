import json
import os
import sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import pytest

# Ensure app is discoverable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# In-memory SQLite for isolated, fast, and repeatable testing
test_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(bind=test_engine, expire_on_commit=False)

from app.db import Base, get_db
from app.main import app, Charge


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
    """Verify Payment service health endpoint."""
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok", "service": "payment"}


def test_successful_payment_charge():
    """Verify processing a single valid payment charge."""
    key = "pay-key-001"
    payload = {"order_id": "order-101", "amount_cents": 200000, "simulate": "success"}
    res = client.post("/api/v1/payments", json=payload, headers={"Idempotency-Key": key})
    assert res.status_code == 201
    data = res.json()
    assert data["order_id"] == "order-101"
    assert data["amount_cents"] == 200000
    assert data["status"] == "SUCCEEDED"
    assert "payment_id" in data


def test_br5_payment_idempotency_same_key_replays_charge():
    """BR5 Invariant: Sequential replay with the same idempotency key and identical payload

    must return the exact same payment record and NEVER charge twice.
    """
    key = "pay-key-002"
    payload = {"order_id": "order-102", "amount_cents": 150000, "simulate": "success"}

    # First request
    res1 = client.post("/api/v1/payments", json=payload, headers={"Idempotency-Key": key})
    assert res1.status_code == 201
    d1 = res1.json()

    # Second request (Replay)
    res2 = client.post("/api/v1/payments", json=payload, headers={"Idempotency-Key": key})
    assert res2.status_code in (200, 201)
    d2 = res2.json()

    assert d1["payment_id"] == d2["payment_id"]
    assert d1["status"] == d2["status"]
    assert d1["order_id"] == d2["order_id"]

    # Verify database holds exactly one charge row
    with TestingSessionLocal() as db:
        charges = db.scalars(select(Charge).where(Charge.idempotency_key == key)).all()
        assert len(charges) == 1


def test_br5_payment_conflict_different_payload_returns_409():
    """BR5 Invariant: Same idempotency key with conflicting payload must be rejected with HTTP 409."""
    key = "pay-key-003"
    initial_payload = {"order_id": "order-103", "amount_cents": 250000, "simulate": "success"}
    res1 = client.post("/api/v1/payments", json=initial_payload, headers={"Idempotency-Key": key})
    assert res1.status_code == 201

    # Mismatched amount
    conflicting_payload = {"order_id": "order-103", "amount_cents": 350000, "simulate": "success"}
    res2 = client.post("/api/v1/payments", json=conflicting_payload, headers={"Idempotency-Key": key})
    assert res2.status_code == 409
    body = res2.json()
    assert body["error"]["code"] == "KEY_REUSED"


def test_payment_simulation_decline():
    """Verify simulated decline marks status as DECLINED."""
    key = "pay-key-decline-001"
    payload = {"order_id": "order-decline-01", "amount_cents": 50000, "simulate": "decline"}
    res = client.post("/api/v1/payments", json=payload, headers={"Idempotency-Key": key})
    assert res.status_code == 201
    assert res.json()["status"] == "DECLINED"


def test_payment_simulation_env_var_reject(monkeypatch):
    """Verify environment variable simulation mode PAYMENT_SIMULATION_MODE=reject."""
    monkeypatch.setenv("PAYMENT_SIMULATION_MODE", "reject")
    key = "pay-key-env-reject"
    payload = {"order_id": "order-env-01", "amount_cents": 80000, "simulate": "success"}
    res = client.post("/api/v1/payments", json=payload, headers={"Idempotency-Key": key})
    assert res.status_code == 201
    assert res.json()["status"] == "DECLINED"


def test_reconciliation_get_by_key_success():
    """Verify safe reconciliation query GET /api/v1/payments/by-key/{key}."""
    key = "pay-key-recon-001"
    payload = {"order_id": "order-recon-01", "amount_cents": 99900, "simulate": "success"}
    res_post = client.post("/api/v1/payments", json=payload, headers={"Idempotency-Key": key})
    assert res_post.status_code == 201
    charge_id = res_post.json()["payment_id"]

    res_get = client.get(f"/api/v1/payments/by-key/{key}")
    assert res_get.status_code == 200
    d = res_get.json()
    assert d["payment_id"] == charge_id
    assert d["order_id"] == "order-recon-01"
    assert d["status"] == "SUCCEEDED"


def test_reconciliation_get_by_key_not_found_404():
    """Verify reconciliation lookup for non-existent key returns 404."""
    res = client.get("/api/v1/payments/by-key/non-existent-key")
    assert res.status_code == 404


def test_get_payment_by_id():
    """Verify lookup by payment ID."""
    key = "pay-key-id-001"
    payload = {"order_id": "order-id-01", "amount_cents": 120000, "simulate": "success"}
    res = client.post("/api/v1/payments", json=payload, headers={"Idempotency-Key": key})
    pid = res.json()["payment_id"]

    res_get = client.get(f"/api/v1/payments/{pid}")
    assert res_get.status_code == 200
    assert res_get.json()["payment_id"] == pid


def test_br5_concurrent_duplicate_charges():
    """Concurrent duplicate payment charge requests with identical key produce exactly one payment row."""
    key = "pay-key-concurrent-001"
    payload = {"order_id": "order-concur-01", "amount_cents": 450000, "simulate": "success"}

    def send_payment(_):
        return client.post("/api/v1/payments", json=payload, headers={"Idempotency-Key": key})

    with ThreadPoolExecutor(max_workers=5) as executor:
        responses = list(executor.map(send_payment, range(5)))

    # All responses should return success (either 201 or replay 200)
    for r in responses:
        assert r.status_code in (200, 201)
        assert r.json()["status"] == "SUCCEEDED"

    # All responses must reference the same payment_id
    payment_ids = {r.json()["payment_id"] for r in responses}
    assert len(payment_ids) == 1

    # Exactly one record exists in database
    with TestingSessionLocal() as db:
        count = len(db.scalars(select(Charge).where(Charge.idempotency_key == key)).all())
        assert count == 1
