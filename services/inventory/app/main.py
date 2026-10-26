from datetime import datetime, timezone
from typing import Literal
from fastapi import FastAPI, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import Integer, String, ForeignKey, CheckConstraint, update, select
from sqlalchemy.orm import Mapped, mapped_column, Session
from .common import setup
from .db import Base, engine, get_db


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    price_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    available: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (CheckConstraint("available >= 0", name="check_positive_available"),)


class Hold(Base):
    __tablename__ = "holds"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    order_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="HELD", nullable=False)


class ProductIn(BaseModel):
    name: str = Field(min_length=1)
    price_cents: int = Field(gt=0)
    available: int = Field(ge=0)


class ReserveIn(BaseModel):
    order_id: str = Field(min_length=1)
    product_id: int
    quantity: int = Field(gt=0)


def init_db(target_engine=None):
    b_engine = target_engine or engine
    Base.metadata.create_all(bind=b_engine)


app = FastAPI(title="Inventory Service", version="1.0.0")
setup(app)

try:
    init_db()
except Exception:
    pass


@app.get("/health")
def health():
    return {"status": "ok", "service": "inventory"}


@app.post("/api/v1/products", status_code=201)
def create_product(body: ProductIn, db: Session = Depends(get_db)):
    product = Product(**body.model_dump())
    db.add(product)
    db.commit()
    db.refresh(product)
    return {"id": product.id, **body.model_dump()}


@app.get("/api/v1/products")
def list_products(db: Session = Depends(get_db)):
    return [
        {
            "id": p.id,
            "name": p.name,
            "price_cents": p.price_cents,
            "available": p.available,
        }
        for p in db.scalars(select(Product).order_by(Product.id)).all()
    ]


@app.get("/api/v1/products/{product_id}")
def get_product(product_id: int, db: Session = Depends(get_db)):
    p = db.get(Product, product_id)
    if not p:
        raise HTTPException(status_code=404, detail="Product not found")
    return {
        "id": p.id,
        "name": p.name,
        "price_cents": p.price_cents,
        "available": p.available,
    }


def handle_reservation(body: ReserveIn, db: Session):
    # 1. Deduplication check: Has this order_id already reserved?
    previous = db.scalar(select(Hold).where(Hold.order_id == body.order_id))
    if previous:
        if (previous.product_id, previous.quantity) != (body.product_id, body.quantity):
            raise ValueError("Order ID reused with different stock request")
        return {"hold_id": previous.id, "status": previous.status}

    # 2. Atomic conditional decrement (BR1: Stock never negative)
    result = db.execute(
        update(Product)
        .where(Product.id == body.product_id, Product.available >= body.quantity)
        .values(available=Product.available - body.quantity)
        .returning(Product.id)
    ).first()

    if not result:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail={"error": {"code": "OUT_OF_STOCK", "message": "Insufficient stock"}},
        )

    # 3. Insert reservation record in the same transaction
    hold = Hold(
        order_id=body.order_id,
        product_id=body.product_id,
        quantity=body.quantity,
        status="HELD",
    )
    db.add(hold)
    try:
        db.commit()
    except Exception:
        db.rollback()
        # Race condition handling: check if competing concurrent request committed
        previous = db.scalar(select(Hold).where(Hold.order_id == body.order_id))
        if previous and (previous.product_id, previous.quantity) == (body.product_id, body.quantity):
            return {"hold_id": previous.id, "status": previous.status}
        raise

    db.refresh(hold)
    return {"hold_id": hold.id, "status": hold.status}


@app.post("/api/v1/stock/reserve", status_code=201)
def reserve_stock(body: ReserveIn, db: Session = Depends(get_db)):
    return handle_reservation(body, db)


@app.post("/api/v1/stock/reservations", status_code=201)
def reserve_stock_alias(body: ReserveIn, db: Session = Depends(get_db)):
    return handle_reservation(body, db)


def handle_confirmation(hold_id: int, db: Session):
    hold = db.get(Hold, hold_id)
    if hold is None:
        raise HTTPException(status_code=404, detail="Hold not found")
    if hold.status == "RELEASED":
        raise ValueError("Released hold cannot be confirmed")
    if hold.status == "CONFIRMED":
        return {"hold_id": hold.id, "status": hold.status}

    hold.status = "CONFIRMED"
    db.commit()
    return {"hold_id": hold.id, "status": hold.status}


@app.post("/api/v1/stock/{hold_id}/confirm")
def confirm_stock(hold_id: int, db: Session = Depends(get_db)):
    return handle_confirmation(hold_id, db)


@app.post("/api/v1/stock/reservations/{hold_id}/confirm")
def confirm_stock_alias(hold_id: int, db: Session = Depends(get_db)):
    return handle_confirmation(hold_id, db)


def handle_release(hold_id: int, db: Session):
    # Lock row to prevent concurrent release anomalies
    is_sqlite = db.bind.dialect.name == "sqlite"
    if is_sqlite:
        hold = db.get(Hold, hold_id)
    else:
        hold = db.get(Hold, hold_id, with_for_update=True)

    if hold is None:
        raise HTTPException(status_code=404, detail="Hold not found")

    # BR2: Confirmed hold cannot be released
    if hold.status == "CONFIRMED":
        raise ValueError("Confirmed stock cannot be released")

    # Safe repeated release (idempotent)
    if hold.status == "RELEASED":
        return {"hold_id": hold.id, "status": hold.status}

    if hold.status == "HELD":
        db.execute(
            update(Product)
            .where(Product.id == hold.product_id)
            .values(available=Product.available + hold.quantity)
        )
        hold.status = "RELEASED"
        db.commit()

    return {"hold_id": hold.id, "status": hold.status}


@app.post("/api/v1/stock/{hold_id}/release")
def release_stock(hold_id: int, db: Session = Depends(get_db)):
    return handle_release(hold_id, db)


@app.post("/api/v1/stock/reservations/{hold_id}/release")
def release_stock_alias(hold_id: int, db: Session = Depends(get_db)):
    return handle_release(hold_id, db)
