from fastapi import FastAPI, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import String, select
from sqlalchemy.orm import Mapped, mapped_column, Session
from .db import Base, engine, get_db
from .common import setup


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    order_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    recipient: Mapped[str] = mapped_column(String(120))
    content: Mapped[str] = mapped_column(String(250))
    status: Mapped[str] = mapped_column(String(20), default="RECORDED")


class MessageIn(BaseModel):
    order_id: str
    recipient: str
    content: str


app = FastAPI(title="Mock Notification Service")
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
    found = db.scalar(select(Message).where(Message.order_id == body.order_id))
    if found:
        return {"notification_id": found.id, "status": found.status}
    msg = Message(**body.model_dump(), status="RECORDED")
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return {"notification_id": msg.id, "status": msg.status}


@app.get("/api/v1/notifications/{message_id}")
def get_notification(message_id: int, db: Session = Depends(get_db)):
    msg = db.get(Message, message_id)
    if msg is None:
        raise HTTPException(status_code=404, detail="Notification not found")
    return {"notification_id": msg.id, "order_id": msg.order_id, "status": msg.status}
