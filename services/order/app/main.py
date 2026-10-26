import hashlib
import json
import os
import random
import time
import uuid
import httpx
from fastapi import FastAPI, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import String, Integer, select
from sqlalchemy.orm import Mapped, mapped_column, Session
from .db import Base, engine, get_db
from .common import setup

INVENTORY = os.getenv("INVENTORY_URL", "http://localhost:8001")
PAYMENT = os.getenv("PAYMENT_URL", "http://localhost:8003")
NOTIFICATION = os.getenv("NOTIFICATION_URL", "http://localhost:8004")
TIMEOUT = float(os.getenv("PAYMENT_TIMEOUT", "0.7"))


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    key: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    product_id: Mapped[int] = mapped_column(Integer)
    quantity: Mapped[int] = mapped_column(Integer)
    amount_cents: Mapped[int] = mapped_column(Integer)
    recipient: Mapped[str] = mapped_column(String(120))
    hold_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="PENDING")


class Checkout(BaseModel):
    product_id: int
    quantity: int = Field(gt=0)
    amount_cents: int = Field(gt=0)
    recipient: str = Field(min_length=3)
    simulate: str = "success"


app = FastAPI(title="Order Service")
setup(app)

try:
    Base.metadata.create_all(bind=engine)
except Exception:
    pass


def snapshot(o):
    return {"order_id": o.id, "status": o.status, "hold_id": o.hold_id}


def downstream(method, url, request_id, **kwargs):
    headers = {"X-Request-ID": request_id, **kwargs.pop("headers", {})}
    with httpx.Client(timeout=TIMEOUT) as client:
        return client.request(method, url, headers=headers, **kwargs)


def confirm_stock(order, request_id):
    r = downstream("POST", f"{INVENTORY}/api/v1/stock/{order.hold_id}/confirm", request_id)
    r.raise_for_status()


def notify_best_effort(order, request_id):
    try:
        downstream(
            "POST",
            f"{NOTIFICATION}/api/v1/notifications",
            request_id,
            json={
                "order_id": order.id,
                "recipient": order.recipient,
                "content": "Your order is confirmed",
            },
        )
    except httpx.HTTPError:
        pass


def finalize(order, db, request_id, payment_status):
    if payment_status == "SUCCEEDED":
        try:
            confirm_stock(order, request_id)
        except httpx.HTTPError:
            order.status = "STOCK_CONFIRM_PENDING"
            db.commit()
            return
        order.status = "CONFIRMED"
        db.commit()
        notify_best_effort(order, request_id)
    elif payment_status == "DECLINED":
        try:
            downstream(
                "POST",
                f"{INVENTORY}/api/v1/stock/{order.hold_id}/release",
                request_id,
            ).raise_for_status()
        except httpx.HTTPError:
            order.status = "RELEASE_PENDING"
            db.commit()
            return
        order.status = "FAILED"
        db.commit()


def process(order, db, request_id, simulate):
    if order.hold_id is None:
        try:
            r = downstream(
                "POST",
                f"{INVENTORY}/api/v1/stock/reserve",
                request_id,
                json={
                    "order_id": order.id,
                    "product_id": order.product_id,
                    "quantity": order.quantity,
                },
            )
        except httpx.HTTPError:
            order.status = "INVENTORY_PENDING"
            db.commit()
            return

        if r.status_code == 409:
            order.status = "OUT_OF_STOCK"
            db.commit()
            return
        r.raise_for_status()
        order.hold_id = r.json()["hold_id"]
        order.status = "PAYMENT_PENDING"
        db.commit()

    payload = {
        "order_id": order.id,
        "amount_cents": order.amount_cents,
        "simulate": simulate,
    }
    for i in range(3):
        try:
            r = downstream(
                "POST",
                f"{PAYMENT}/api/v1/payments",
                request_id,
                json=payload,
                headers={"Idempotency-Key": "pay-" + order.id},
            )
            r.raise_for_status()
            finalize(order, db, request_id, r.json()["status"])
            return
        except (httpx.TimeoutException, httpx.TransportError):
            if i < 2:
                time.sleep(0.1 * (2**i) + random.uniform(0, 0.04))

    try:
        r = downstream(
            "GET",
            f"{PAYMENT}/api/v1/payments/by-key/pay-{order.id}",
            request_id,
        )
        if r.status_code == 200:
            finalize(order, db, request_id, r.json()["status"])
    except httpx.HTTPError:
        pass


@app.get("/health")
def health():
    return {"status": "ok", "service": "order"}


@app.post("/api/v1/orders", status_code=201)
def checkout(
    body: Checkout,
    request: Request,
    key: str = Header(..., alias="Idempotency-Key"),
    db: Session = Depends(get_db),
):
    fingerprint = hashlib.sha256(
        json.dumps(body.model_dump(), sort_keys=True).encode()
    ).hexdigest()

    existing = db.scalar(select(Order).where(Order.key == key))
    if existing:
        if existing.fingerprint != fingerprint:
            raise HTTPException(
                status_code=409,
                detail={"error": {"code": "KEY_REUSED", "message": "Payload differs"}},
            )
        return snapshot(existing)

    order_id = str(uuid.uuid4())
    order = Order(
        id=order_id,
        key=key,
        fingerprint=fingerprint,
        product_id=body.product_id,
        quantity=body.quantity,
        amount_cents=body.amount_cents,
        recipient=body.recipient,
        status="PENDING",
    )
    db.add(order)
    try:
        db.commit()
        db.refresh(order)
    except Exception:
        db.rollback()
        existing = db.scalar(select(Order).where(Order.key == key))
        if existing:
            if existing.fingerprint != fingerprint:
                raise HTTPException(
                    status_code=409,
                    detail={"error": {"code": "KEY_REUSED", "message": "Payload differs"}},
                )
            return snapshot(existing)
        raise

    process(order, db, getattr(request.state, "request_id", str(uuid.uuid4())), body.simulate)
    db.refresh(order)
    return snapshot(order)


@app.get("/api/v1/orders/{order_id}")
def get_order(order_id: str, db: Session = Depends(get_db)):
    row = db.get(Order, order_id)
    if not row:
        raise HTTPException(status_code=404, detail="Order not found")
    return snapshot(row)


@app.post("/api/v1/orders/{order_id}/reconcile")
def reconcile(order_id: str, request: Request, db: Session = Depends(get_db)):
    row = db.get(Order, order_id)
    if not row:
        raise HTTPException(status_code=404, detail="Order not found")
    rid = getattr(request.state, "request_id", str(uuid.uuid4()))
    if row.status == "STOCK_CONFIRM_PENDING":
        try:
            confirm_stock(row, rid)
            row.status = "CONFIRMED"
            db.commit()
            notify_best_effort(row, rid)
        except httpx.HTTPError:
            pass
    elif row.status == "RELEASE_PENDING":
        try:
            downstream(
                "POST",
                f"{INVENTORY}/api/v1/stock/{row.hold_id}/release",
                rid,
            ).raise_for_status()
            row.status = "FAILED"
            db.commit()
        except httpx.HTTPError:
            pass
    elif row.status == "PAYMENT_PENDING":
        try:
            r = downstream("GET", f"{PAYMENT}/api/v1/payments/by-key/pay-{row.id}", rid)
            if r.status_code == 200:
                finalize(row, db, rid, r.json()["status"])
        except httpx.HTTPError:
            pass
    return snapshot(row)
