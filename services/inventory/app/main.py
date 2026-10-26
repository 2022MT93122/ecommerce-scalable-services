from fastapi import FastAPI
from .common import setup
from .db import Base, engine

app = FastAPI(title="Inventory Service", version="1.0.0")
setup(app)
Base.metadata.create_all(bind=engine)


@app.get("/health")
def health():
    return {"status": "ok", "service": "inventory"}
