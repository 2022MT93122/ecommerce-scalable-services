import hashlib
import json
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from . import logic
from .common import logger, setup
from .db import Base, engine, get_db
from .models import CheckoutRecord, Order
from .schemas import Checkout


@asynccontextmanager
async def lifespan(app):
    # Fail startup if persistence is unavailable instead of serving a false healthy state.
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title="Order Service", version="1.0.0", lifespan=lifespan)
setup(app)


def replay(order, db, response, request_id):
    """Wait briefly for the winning request; never repeat its external effects."""
    order_id = order.id
    deadline = time.monotonic() + logic.REPLAY_WAIT
    while True:
        record = db.get(CheckoutRecord, order_id)
        if record and record.response is not None:
            result = record.response
            break
        if record is None or time.monotonic() >= deadline:
            result = logic.snapshot(order)
            break
        # End the read transaction so another process's commit becomes visible.
        db.rollback()
        time.sleep(0.025)
        db.expire_all()
        order = db.get(Order, order_id)
    logger.info(json.dumps({"event": "idempotency_replay", "order_id": order_id,
                            "request_id": request_id}))
    response.status_code = 201 if result["status"] in logic.TERMINAL_STATES else 202
    return result


def check_fingerprint(order, fingerprint):
    if order.fingerprint != fingerprint:
        raise HTTPException(status_code=409, detail={
            "error": {"code": "KEY_REUSED", "message": "Payload differs"}})


@app.get("/health")
def health(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail="Database unavailable")
    return {"status": "ok", "service": "order"}


@app.post("/api/v1/orders", status_code=201, responses={202: {"description": "Processing pending"},
                                                       409: {"description": "Key reused with a different payload"}})
def checkout(
    body: Checkout,
    request: Request,
    response: Response,
    key: str = Header(..., alias="Idempotency-Key", min_length=1, max_length=120),
    db: Session = Depends(get_db),
):
    fingerprint = hashlib.sha256(json.dumps(body.model_dump(), sort_keys=True).encode()).hexdigest()
    rid = request.state.request_id
    existing = db.scalar(select(Order).where(Order.key == key))
    if existing:
        check_fingerprint(existing, fingerprint)
        return replay(existing, db, response, rid)

    order = Order(id=str(uuid.uuid4()), key=key, fingerprint=fingerprint,
                  product_id=body.product_id, quantity=body.quantity,
                  amount_cents=body.amount_cents, recipient=body.recipient, status="PENDING")
    record = CheckoutRecord(order_id=order.id, simulate=body.simulate)
    db.add_all([order, record])
    try:
        # Persist identity and recovery options before any external side effect.
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(select(Order).where(Order.key == key))
        if existing is None:
            raise
        check_fingerprint(existing, fingerprint)
        return replay(existing, db, response, rid)

    logic.process(order, db, rid, body.simulate)
    record.response = logic.snapshot(order)
    db.commit()
    response.status_code = 201 if order.status in logic.TERMINAL_STATES else 202
    return record.response


@app.get("/api/v1/orders/{order_id}")
def get_order(order_id: str, db: Session = Depends(get_db)):
    order = db.get(Order, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return logic.snapshot(order)


@app.post("/api/v1/orders/{order_id}/reconcile")
def reconcile(order_id: str, request: Request, db: Session = Depends(get_db)):
    order = db.get(Order, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    logic.reconcile(order, db, request.state.request_id)
    return logic.snapshot(order)
