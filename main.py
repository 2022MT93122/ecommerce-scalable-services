import uuid
import sqlite3
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from .config import settings
from .logging_config import setup_logger
from .database import init_db, get_connection, reset_product_stock
from .schemas import (
    StandardErrorResponse, ErrorDetail,
    ProductResponse, ReservationRequest, ReservationResponse,
    ReleaseRequest, ReleaseResponse, ConfirmRequest, ConfirmResponse,
    ResetStockRequest
)
logger = setup_logger(settings.SERVICE_NAME, settings.LOG_LEVEL)
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize database on startup
    init_db()
    logger.info("Inventory Service initialized with SQLite WAL mode", extra={"service": settings.SERVICE_NAME})
    yield
    logger.info("Inventory Service shutting down", extra={"service": settings.SERVICE_NAME})
app = FastAPI(
    title="Inventory Service",
    description="Manages product stock catalog and atomic reservations with strict concurrency guarantees (BR1).",
    version="1.0.0",
    lifespan=lifespan
)
 Correlation ID Middleware & Request Logging
@app.middleware("http")
async def correlation_id_middleware(request: Request, call_next):
    correlation_id = request.headers.get("X-Correlation-ID") or f"corr-{uuid.uuid4()}"
    request.state.correlation_id = correlation_id
    
    logger.info(
        f"Incoming {request.method} {request.url.path}",
        extra={"correlation_id": correlation_id, "service": settings.SERVICE_NAME}
    )
    
    response: Response = await call_next(request)
    response.headers["X-Correlation-ID"] = correlation_id
    return response
     Validation Error Handler matching standardized error format
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    correlation_id = getattr(request.state, "correlation_id", "N/A")
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "Invalid request parameters",
                "details": exc.errors()
            },
            "correlation_id": correlation_id,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    )
    # Operational Health Endpoint
@app.get("/health", tags=["Operability"])
def health_check(request: Request):
    correlation_id = getattr(request.state, "correlation_id", "N/A")
    try:
        conn = get_connection()
        conn.execute("SELECT 1;")
        conn.close()
        db_status = "healthy"
    except Exception as e:
        db_status = f"unhealthy: {str(e)}"
    return {
        "status": "UP",
        "service": settings.SERVICE_NAME,
        "version": "1.0.0",
        "database": db_status,
        "correlation_id": correlation_id,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    # API v1: List Products
@app.get("/api/v1/inventory/products", response_model=list[ProductResponse], tags=["Inventory"])
def list_products():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM products ORDER BY product_id ASC;")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]
    # API v1: Get Product Details
@app.get("/api/v1/inventory/products/{product_id}", response_model=ProductResponse, tags=["Inventory"])
def get_product(product_id: str, request: Request):
    correlation_id = getattr(request.state, "correlation_id", "N/A")
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM products WHERE product_id = ?;", (product_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "error": {
                    "code": "PRODUCT_NOT_FOUND",
                    "message": f"Product with ID '{product_id}' was not found.",
                    "details": None
                },
                "correlation_id": correlation_id,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        )
    return dict(row)
    # API v1: Reserve Stock (Challenge 1 Concurrency Control - BR1)
@app.post("/api/v1/inventory/reserve", response_model=ReservationResponse, status_code=status.HTTP_200_OK, tags=["Inventory"])
def reserve_stock(payload: ReservationRequest, request: Request):
    correlation_id = getattr(request.state, "correlation_id", "N/A")
    conn = get_connection()
    cursor = conn.cursor()
    now = datetime.now(timezone.utc).isoformat()
    reservation_id = f"resv-{uuid.uuid4()}"
    try:
        # Atomic Transaction with immediate exclusive lock
        cursor.execute("BEGIN IMMEDIATE;")
        
        # Check if product exists first
        cursor.execute("SELECT available_stock FROM products WHERE product_id = ?;", (payload.product_id,))
        prod = cursor.fetchone()
        if not prod:
            cursor.execute("ROLLBACK;")
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={
                    "error": {
                        "code": "PRODUCT_NOT_FOUND",
                        "message": f"Product '{payload.product_id}' not found.",
                        "details": None
                    },
                    "correlation_id": correlation_id,
                    "timestamp": now
                }
            )
                    # Atomic conditional update (BR1: Stock Conservation Rule)
        # Prevents over-allocation even under massive parallel contention
        cursor.execute("""
            UPDATE products
            SET available_stock = available_stock - ?,
                reserved_stock = reserved_stock + ?,
                version = version + 1,
                updated_at = ?
            WHERE product_id = ? AND available_stock >= ?;
        """, (payload.quantity, payload.quantity, now, payload.product_id, payload.quantity))
        if cursor.rowcount == 0:
            # Over-allocation avoided: current stock was insufficient to fulfill requested quantity
            available = prod["available_stock"]
            cursor.execute("ROLLBACK;")
            logger.warning(
                f"Stock reservation rejected for product {payload.product_id}: requested {payload.quantity}, available {available}",
                extra={"correlation_id": correlation_id, "service": settings.SERVICE_NAME}
            )
            return JSONResponse(
                status_code=status.HTTP_409_CONFLICT,
                content={
                    "error": {
                        "code": "INSUFFICIENT_STOCK",
                        "message": f"Cannot reserve {payload.quantity} units for product '{payload.product_id}'. Available: {available}.",
                        "details": {"requested": payload.quantity, "available": available}
                    },
                    "correlation_id": correlation_id,
                    "timestamp": now
                }
            )
                    # Insert reservation record
        cursor.execute("""
            INSERT INTO reservations (reservation_id, order_id, product_id, quantity, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'RESERVED', ?, ?);
        """, (reservation_id, payload.order_id, payload.product_id, payload.quantity, now, now))
        # Retrieve updated stock
        cursor.execute("SELECT available_stock FROM products WHERE product_id = ?;", (payload.product_id,))
        remaining = cursor.fetchone()["available_stock"]
        cursor.execute("COMMIT;")
        logger.info(
            f"Successfully reserved {payload.quantity} units of {payload.product_id} for order {payload.order_id}. Remaining stock: {remaining}",
            extra={"correlation_id": correlation_id, "service": settings.SERVICE_NAME}
        )
        return ReservationResponse(
            reservation_id=reservation_id,
            order_id=payload.order_id,
            product_id=payload.product_id,
            quantity=payload.quantity,
            status="RESERVED",
            remaining_available_stock=remaining,
            created_at=now
        )
    except Exception as e:
        cursor.execute("ROLLBACK;")
        logger.error(f"Error during inventory reservation: {str(e)}", extra={"correlation_id": correlation_id, "service": settings.SERVICE_NAME})
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": {
                    "code": "INTERNAL_SERVER_ERROR",
                    "message": "Failed to process inventory reservation due to database exception.",
                    "details": str(e)
                },
                "correlation_id": correlation_id,
                "timestamp": now
                 }
        )
    finally:
        conn.close()
        # API v1: Release Stock (Compensation endpoint for Saga - Challenge 3)
@app.post("/api/v1/inventory/release", response_model=ReleaseResponse, status_code=status.HTTP_200_OK, tags=["Inventory"])
def release_stock(payload: ReleaseRequest, request: Request):
    correlation_id = getattr(request.state, "correlation_id", "N/A")
    conn = get_connection()
    cursor = conn.cursor()
    now = datetime.now(timezone.utc).isoformat()
    try:
        cursor.execute("BEGIN IMMEDIATE;")
        cursor.execute("SELECT * FROM reservations WHERE reservation_id = ?;", (payload.reservation_id,))
        resv = cursor.fetchone()
        if not resv:
            cursor.execute("ROLLBACK;")
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={
                    "error": {
                        "code": "RESERVATION_NOT_FOUND",
                        "message": f"Reservation '{payload.reservation_id}' not found.",
                        "details": None
                    },
                    "correlation_id": correlation_id,
                    "timestamp": now
                }
            )
             if resv["status"] == "RELEASED":
            # Idempotent release
            cursor.execute("SELECT available_stock FROM products WHERE product_id = ?;", (resv["product_id"],))
            current = cursor.fetchone()["available_stock"]
            cursor.execute("COMMIT;")
            return ReleaseResponse(
                reservation_id=resv["reservation_id"],
                order_id=resv["order_id"],
                product_id=resv["product_id"],
                released_quantity=resv["quantity"],
                status="RELEASED",
                restored_available_stock=current
            )
              # Restore stock back to product
        cursor.execute("""
            UPDATE products
            SET available_stock = available_stock + ?,
                reserved_stock = reserved_stock - ?,
                version = version + 1,
                updated_at = ?
            WHERE product_id = ?;
        """, (resv["quantity"], resv["quantity"], now, resv["product_id"]))
         # Mark reservation as RELEASED
        cursor.execute("""
            UPDATE reservations
            SET status = 'RELEASED', updated_at = ?
            WHERE reservation_id = ?;
        """, (now, payload.reservation_id))
        cursor.execute("SELECT available_stock FROM products WHERE product_id = ?;", (resv["product_id"],))
        restored = cursor.fetchone()["available_stock"]
        cursor.execute("COMMIT;")
        logger.info(
            f"Compensating action: Released reservation {payload.reservation_id} for order {payload.order_id}. Restored stock to {restored}",
            extra={"correlation_id": correlation_id, "service": settings.SERVICE_NAME}
        )
        return ReleaseResponse(
            reservation_id=resv["reservation_id"],
            order_id=resv["order_id"],
            product_id=resv["product_id"],
            released_quantity=resv["quantity"],
            status="RELEASED",
            restored_available_stock=restored
        )
    except Exception as e:
        cursor.execute("ROLLBACK;")
        logger.error(f"Error releasing inventory: {str(e)}", extra={"correlation_id": correlation_id, "service": settings.SERVICE_NAME})
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": {
                    "code": "INTERNAL_SERVER_ERROR",
                    "message": "Failed to release reservation.",
                    "details": str(e)
                },
                "correlation_id": correlation_id,
                "timestamp": now
            }
        )
    finally:
        conn.close()
         API v1: Confirm Stock Reservation (Happy path commit)
@app.post("/api/v1/inventory/confirm", response_model=ConfirmResponse, status_code=status.HTTP_200_OK, tags=["Inventory"])
def confirm_stock(payload: ConfirmRequest, request: Request):
    correlation_id = getattr(request.state, "correlation_id", "N/A")
    conn = get_connection()
    cursor = conn.cursor()
    now = datetime.now(timezone.utc).isoformat()
        try:
        cursor.execute("BEGIN IMMEDIATE;")
        cursor.execute("SELECT * FROM reservations WHERE reservation_id = ?;", (payload.reservation_id,))
        resv = cursor.fetchone()
        if not resv:
            cursor.execute("ROLLBACK;")
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={
                    "error": {
                        "code": "RESERVATION_NOT_FOUND",
                        "message": f"Reservation '{payload.reservation_id}' not found.",
                        "details": None
                    },
                    "correlation_id": correlation_id,
                    "timestamp": now
                }
            )
            cursor.execute("""
            UPDATE reservations
            SET status = 'CONFIRMED', updated_at = ?
            WHERE reservation_id = ?;
        """, (now, payload.reservation_id))
        cursor.execute("COMMIT;")
        return ConfirmResponse(reservation_id=payload.reservation_id, order_id=payload.order_id, status="CONFIRMED")
    except Exception as e:
        cursor.execute("ROLLBACK;")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": {
                    "code": "INTERNAL_SERVER_ERROR",
                    "message": "Failed to confirm reservation.",
                    "details": str(e)
                },
                "correlation_id": correlation_id,
                "timestamp": now
            }
        )
    finally:
        conn.close()
        # API v1: Reset Stock (Test Harness utility)
@app.post("/api/v1/inventory/reset", tags=["Testing"])
def reset_stock(payload: ResetStockRequest):
    reset_product_stock(payload.product_id, payload.stock)
    return {"status": "SUCCESS", "product_id": payload.product_id, "available_stock": payload.stock}
    