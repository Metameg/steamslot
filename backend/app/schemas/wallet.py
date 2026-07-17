from pydantic import BaseModel


class BalanceResponse(BaseModel):
    balance_cents: int
    currency: str = "USD"
