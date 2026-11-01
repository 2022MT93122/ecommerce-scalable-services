from typing import Literal
from pydantic import BaseModel, Field


class Checkout(BaseModel):
    product_id: int = Field(gt=0)
    quantity: int = Field(gt=0)
    amount_cents: int = Field(gt=0)
    recipient: str = Field(min_length=3, max_length=120)
    simulate: Literal["success", "decline", "slow"] = "success"


