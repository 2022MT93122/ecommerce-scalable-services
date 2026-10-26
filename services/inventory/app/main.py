from datetime import datetime, timezone
from fastapi import FastAPI, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import Integer, String, CheckConstraint, select
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


class ProductIn(BaseModel):
    name: str = Field(min_length=1)
    price_cents: int = Field(gt=0)
    available: int = Field(ge=0)


app = FastAPI(title="Inventory Service", version="1.0.0")
setup(app)
Base.metadata.create_all(bind=engine)


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
        for p in db.scalars(select(Product)).all()
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
