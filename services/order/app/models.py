from typing import Optional
from sqlalchemy import Integer, String, JSON
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    key: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    product_id: Mapped[int] = mapped_column(Integer)
    quantity: Mapped[int] = mapped_column(Integer)
    amount_cents: Mapped[int] = mapped_column(Integer)
    recipient: Mapped[str] = mapped_column(String(120))
    hold_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="PENDING")


class CheckoutRecord(Base):
    """Persist recovery options and the original checkout response."""
    __tablename__ = "checkout_records"

    order_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    simulate: Mapped[str] = mapped_column(String(20), nullable=False)
    response: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

