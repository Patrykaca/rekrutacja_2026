from datetime import datetime, timezone
from decimal import Decimal
from email.utils import parsedate_to_datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from pydantic import field_validator


class ProductAttribute(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    value: str

    @field_validator("key", "value")
    @classmethod
    def must_be_non_empty_string(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must be a non-empty string")
        return value


class ProductPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    name: str
    description: str | None = None
    is_in_stock: bool
    price: Decimal
    last_update: datetime
    attributes: list[ProductAttribute] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def name_must_be_non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must be a non-empty string")
        return value

    @field_validator("is_in_stock", mode="before")
    @classmethod
    def parse_bool(cls, value: Any) -> bool:
        if isinstance(value, bool):
            return value

        if isinstance(value, str):
            lowered = value.lower()
            if lowered == "true":
                return True
            if lowered == "false":
                return False

        raise ValueError("must be true or false")

    @field_validator("price")
    @classmethod
    def price_must_be_non_negative(cls, value: Decimal) -> Decimal:
        if value < 0:
            raise ValueError("must be greater than or equal to 0")
        return value

    @field_validator("last_update", mode="before")
    @classmethod
    def parse_rfc2822_timestamp(cls, value: Any) -> datetime:
        try:
            parsed = parsedate_to_datetime(str(value))
        except (TypeError, ValueError) as exc:
            raise ValueError("must be an RFC 2822 timestamp") from exc

        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)

        return parsed.astimezone(timezone.utc)


def parse_product(
    payload: dict[str, Any],
    message_id: str | None,
    raw_payload: str,
) -> dict[str, Any]:
    product = ProductPayload.model_validate(payload)

    return {
        "id": str(product.id),
        "name": product.name,
        "description": product.description,
        "is_in_stock": product.is_in_stock,
        "price": str(product.price),
        "last_update": product.last_update.isoformat(),
        "attributes": [attribute.model_dump() for attribute in product.attributes],
        "_insert_timestamp": datetime.now(timezone.utc).isoformat(),
        "_source_message_id": message_id,
        "_raw_payload": raw_payload,
    }
