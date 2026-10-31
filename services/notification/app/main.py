import os
import time
from datetime import datetime, timezone
from typing import Optional
from fastapi import FastAPI, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import String, DateTime, select
from sqlalchemy.orm import Mapped, mapped_column, Session
from .db import Base, engine, get_db
from .common import setup


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    order_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    recipient: Mapped[str] = mapped_column(String(120))
    content: Mapped[str] = mapped_column(String(250))
    channel: Mapped[str] = mapped_column(String(30), default="email")
    status: Mapped[str] = mapped_column(String(20), default="RECORDED")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class MessageIn(BaseModel):
    order_id: str = Field(..., min_length=1)
    recipient: str = Field(..., min_length=1)
    content: str = Field(..., min_length=1)
    channel: str = "email"
    simulate: str = "success"  # success | failure | delay


app = FastAPI(title="Notification Service", version="1.0.0")
setup(app)

try:
    Base.metadata.create_all(bind=engine)
except Exception:
    pass


@app.get("/health")
def health():
    return {"status": "ok", "service": "notification"}


@app.post("/api/v1/notifications", status_code=201)
def notify(body: MessageIn, db: Session = Depends(get_db)):
    # Check simulation modes (per-request or environment variable)
    sim_mode = os.getenv("NOTIFICATION_SIMULATION_MODE", body.simulate).lower()
    if sim_mode in ("failure", "fail", "reject"):
        raise HTTPException(
            status_code=500,
            detail={
                "error": {
                    "code": "NOTIFICATION_GATEWAY_ERROR",
                    "message": "Simulated downstream SMS/Email gateway provider failure",
                }
            },
        )
    if sim_mode in ("delay", "slow"):
        time.sleep(2.0)

    # Idempotent deduplication: duplicate notification for same order_id returns existing
    found = db.scalar(select(Message).where(Message.order_id == body.order_id))
    if found:
        return {
            "notification_id": found.id,
            "order_id": found.order_id,
            "recipient": found.recipient,
            "channel": found.channel,
            "status": found.status,
        }

    msg = Message(
        order_id=body.order_id,
        recipient=body.recipient,
        content=body.content,
        channel=body.channel,
        status="RECORDED",
    )
    db.add(msg)
    try:
        db.commit()
        db.refresh(msg)
    except Exception:
        db.rollback()
        found = db.scalar(select(Message).where(Message.order_id == body.order_id))
        if found:
            return {
                "notification_id": found.id,
                "order_id": found.order_id,
                "recipient": found.recipient,
                "channel": found.channel,
                "status": found.status,
            }
        raise

    return {
        "notification_id": msg.id,
        "order_id": msg.order_id,
        "recipient": msg.recipient,
        "channel": msg.channel,
        "status": msg.status,
    }


@app.get("/api/v1/notifications/{message_id}")
def get_notification(message_id: int, db: Session = Depends(get_db)):
    msg = db.get(Message, message_id)
    if msg is None:
        raise HTTPException(status_code=404, detail="Notification not found")
    return {
        "notification_id": msg.id,
        "order_id": msg.order_id,
        "recipient": msg.recipient,
        "content": msg.content,
        "channel": msg.channel,
        "status": msg.status,
    }


@app.get("/api/v1/notifications/order/{order_id}")
def get_notification_by_order(order_id: str, db: Session = Depends(get_db)):
    msg = db.scalar(select(Message).where(Message.order_id == order_id))
    if msg is None:
        raise HTTPException(status_code=404, detail="Notification for order not found")
    return {
        "notification_id": msg.id,
        "order_id": msg.order_id,
        "recipient": msg.recipient,
        "content": msg.content,
        "channel": msg.channel,
        "status": msg.status,
    }
