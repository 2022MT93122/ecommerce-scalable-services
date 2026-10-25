from pydantic import BaseModel, Field
from typing import Optional, List, Any
# Error Model (Standardized across all microservices)
class ErrorDetail(BaseModel):
    code: str = Field(..., description="Machine-readable error code")
    message: str = Field(..., description="Human-readable error description")
    details: Optional[Any] = Field(None, description="Additional context or validation details")
class StandardErrorResponse(BaseModel):
    error: ErrorDetail
    correlation_id: str
    timestamp: str
# Product Models
class ProductResponse(BaseModel):
    product_id: str
    name: str
    price: float
    available_stock: int
    reserved_stock: int
    version: int
    created_at: str
    updated_at: str
# Reservation Models
class ReservationRequest(BaseModel):
    product_id: str = Field(..., min_length=1, description="Target product identifier")
    order_id: str = Field(..., min_length=1, description="Associated order identifier")
    quantity: int = Field(..., gt=0, description="Quantity to reserve")
class ReservationResponse(BaseModel):
    reservation_id: str
    order_id: str
    product_id: str
    quantity: int
    status: str
    remaining_available_stock: int
    created_at: str
class ReleaseRequest(BaseModel):
    reservation_id: str = Field(..., min_length=1)
    order_id: str = Field(..., min_length=1)
    reason: Optional[str] = "ORDER_CANCELLED"
class ReleaseResponse(BaseModel):
    reservation_id: str
    order_id: str
    product_id: str
    released_quantity: int
    status: str
    restored_available_stock: int
class ConfirmRequest(BaseModel):
    reservation_id: str = Field(..., min_length=1)
    order_id: str = Field(..., min_length=1)
class ConfirmResponse(BaseModel):
    reservation_id: str
    order_id: str
    status: str
class ResetStockRequest(BaseModel):
    product_id: str
    stock: int = Field(..., ge=0)