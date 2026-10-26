import hashlib
import json
import time
from fastapi import FastAPI, Header, HTTPException, Depends
from pydantic import BaseModel, Field
from sqlalchemy import String, Integer, select
from sqlalchemy.orm import Mapped, mapped_column, Session
from .db import Base, engine, get_db
from .common import setup


class Charge(Base):
    __tablename__ = "charges"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    idempotency_key: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    order_id: Mapped[str] = mapped_column(String(64))
    amount_cents: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20))


class ChargeIn(BaseModel):
    order_id: str
    amount_cents: int = Field(gt=0)
    simulate: str = "success"  # success | decline | slow


app = FastAPI(title="Mock Payment Service")
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
            "status": existing.status,
        }

    status_val = "DECLINED" if body.simulate == "decline" else "SUCCEEDED"
    charge = Charge(
        idempotency_key=idempotency_key,
        fingerprint=fingerprint,
        order_id=body.order_id,
        amount_cents=body.amount_cents,
        status=status_val,
    )
    db.add(charge)
    try:
        db.commit()
        db.refresh(charge)
    except Exception:
        db.rollback()
        existing = db.scalar(select(Charge).where(Charge.idempotency_key == idempotency_key))
        if existing:
            return {
                "payment_id": existing.id,
                "order_id": existing.order_id,
                "status": existing.status,
            }
        raise

    if body.simulate == "slow":
        time.sleep(2.0)  # emulate uncertain outcome / timeout

    return {
        "payment_id": charge.id,
        "order_id": charge.order_id,
        "status": charge.status,
    }


@app.get("/api/v1/payments/by-key/{key}")
def by_key(key: str, db: Session = Depends(get_db)):
    row = db.scalar(select(Charge).where(Charge.idempotency_key == key))
    if not row:
        raise HTTPException(status_code=404, detail="Payment not found")
    return {"payment_id": row.id, "order_id": row.order_id, "status": row.status}
