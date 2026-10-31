import hashlib
import json
import os
import time
from datetime import datetime, timezone
from typing import Optional
from fastapi import FastAPI, Header, HTTPException, Depends
from pydantic import BaseModel, Field
from sqlalchemy import String, Integer, DateTime, select
from sqlalchemy.orm import Mapped, mapped_column, Session
from .db import Base, engine, get_db
from .common import setup


class Charge(Base):
    __tablename__ = "charges"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    idempotency_key: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    order_id: Mapped[str] = mapped_column(String(64), index=True)
    amount_cents: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20))
    response_json: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class ChargeIn(BaseModel):
    order_id: str = Field(..., min_length=1)
    amount_cents: int = Field(..., gt=0)
    simulate: str = "success"  # success | decline | slow


app = FastAPI(title="Payment Service", version="1.0.0")
setup(app)

try:
    Base.metadata.create_all(bind=engine)
except Exception:
    pass


@app.get("/health")
def health():
    return {"status": "ok", "service": "payment"}


@app.post("/api/v1/payments", status_code=201)
def pay(
    body: ChargeIn,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    db: Session = Depends(get_db),
):
    fingerprint = hashlib.sha256(
        json.dumps(body.model_dump(), sort_keys=True).encode()
    ).hexdigest()

    # Step 1: Check existing charge with identical idempotency key (BR5 Idempotency)
    existing = db.scalar(select(Charge).where(Charge.idempotency_key == idempotency_key))
    if existing:
        if existing.fingerprint != fingerprint:
            raise HTTPException(
                status_code=409,
                detail={"error": {"code": "KEY_REUSED", "message": "Different payload"}},
            )
        # Replay recorded outcome without double charging
        return {
            "payment_id": existing.id,
            "order_id": existing.order_id,
            "amount_cents": existing.amount_cents,
            "status": existing.status,
        }

    # Step 2: Determine outcome & simulation modes (per-request or environment variable)
    sim_mode = os.getenv("PAYMENT_SIMULATION_MODE", body.simulate).lower()
    if sim_mode in ("decline", "reject"):
        status_val = "DECLINED"
    else:
        status_val = "SUCCEEDED"

    response_dict = {
        "order_id": body.order_id,
        "amount_cents": body.amount_cents,
        "status": status_val,
    }

    charge = Charge(
        idempotency_key=idempotency_key,
        fingerprint=fingerprint,
        order_id=body.order_id,
        amount_cents=body.amount_cents,
        status=status_val,
        response_json=json.dumps(response_dict),
    )
    db.add(charge)
    try:
        db.commit()
        db.refresh(charge)
    except Exception:
        db.rollback()
        existing = db.scalar(select(Charge).where(Charge.idempotency_key == idempotency_key))
        if existing:
            if existing.fingerprint != fingerprint:
                raise HTTPException(
                    status_code=409,
                    detail={"error": {"code": "KEY_REUSED", "message": "Different payload"}},
                )
            return {
                "payment_id": existing.id,
                "order_id": existing.order_id,
                "amount_cents": existing.amount_cents,
                "status": existing.status,
            }
        raise

    # Step 3: Handle slow simulation mode after persistence to emulate network timeout / uncertain outcome
    if sim_mode in ("slow", "delay"):
        time.sleep(2.0)

    return {
        "payment_id": charge.id,
        "order_id": charge.order_id,
        "amount_cents": charge.amount_cents,
        "status": charge.status,
    }


@app.get("/api/v1/payments/by-key/{key}")
def by_key(key: str, db: Session = Depends(get_db)):
    """Reconciliation endpoint: lookup charge state by idempotency key. Never creates a charge on GET."""
    row = db.scalar(select(Charge).where(Charge.idempotency_key == key))
    if not row:
        raise HTTPException(status_code=404, detail="Payment not found")
    return {
        "payment_id": row.id,
        "order_id": row.order_id,
        "amount_cents": row.amount_cents,
        "status": row.status,
    }


@app.get("/api/v1/payments/{payment_id}")
def get_payment(payment_id: int, db: Session = Depends(get_db)):
    row = db.get(Charge, payment_id)
    if not row:
        raise HTTPException(status_code=404, detail="Payment not found")
    return {
        "payment_id": row.id,
        "order_id": row.order_id,
        "amount_cents": row.amount_cents,
        "status": row.status,
    }
