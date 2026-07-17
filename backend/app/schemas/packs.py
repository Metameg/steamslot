import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class PackTypeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    price_cents: int
    description: str


class PurchasePackRequest(BaseModel):
    pack_type_id: uuid.UUID


class PackResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    pack_type_id: uuid.UUID
    status: str
    price_paid_cents: int
    purchased_at: datetime


class PullResponse(BaseModel):
    id: uuid.UUID
    game_title: str
    game_header_image_url: str | None
    locked_value_cents: int
    status: str
    created_at: datetime
