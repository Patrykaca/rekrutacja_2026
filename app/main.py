import base64
import logging
import json
from functools import lru_cache
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from pydantic import ValidationError

from app.auth import verify_pubsub_oidc
from app.bigquery_operator import BigQueryOperator
from app.config.settings import settings
from app.parser import parse_product

logging.basicConfig(level=settings.log_level)
logger = logging.getLogger(__name__)


app = FastAPI()


@lru_cache
def get_bq_operator() -> BigQueryOperator:
    return BigQueryOperator()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/pubsub/push")
async def pubsub(
    request: Request,
    invoker_email: str = Depends(verify_pubsub_oidc),
) -> Response:
    try:
        envelope = await request.json()
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Request body must be valid JSON") from exc

    message = envelope.get("message")
    if not isinstance(message, dict):
        raise HTTPException(status_code=400, detail="Bad Request")

    message_id = message.get("messageId") or message.get("message_id")
    if not isinstance(message_id, str) or not message_id:
        raise HTTPException(status_code=400, detail="Missing Pub/Sub messageId")

    raw_payload = _decode_message_data(message)
    _ensure_raw_payload_size(raw_payload)

    try:
        payload = json.loads(raw_payload)

        if not isinstance(payload, dict):
            logger.info(
                "Invalid payload rejected for message_id=%s field=_payload raw_payload_preview=%s",
                message_id,
                _payload_preview(raw_payload),
            )
            raise HTTPException(status_code=400, detail="Payload must be a JSON object")

        row = parse_product(payload, message_id, raw_payload)

    except json.JSONDecodeError:
        logger.info(
            "Invalid JSON rejected for message_id=%s raw_payload_preview=%s",
            message_id,
            _payload_preview(raw_payload),
        )
        raise HTTPException(status_code=400, detail="Payload must be valid JSON")

    except ValidationError as exc:
        field, reason = _parse_validation_error(exc)
        logger.info(
            "Invalid payload rejected for message_id=%s field=%s raw_payload_preview=%s",
            message_id,
            field,
            _payload_preview(raw_payload),
        )
        raise HTTPException(status_code=400, detail=f"{field}: {reason}") from exc

    get_bq_operator().insert([row], row_ids=[message_id])
    logger.info("Product stored message_id=%s invoker=%s", message_id, invoker_email)

    return Response(status_code=204)


def _parse_validation_error(exc: ValidationError) -> tuple[str, str]:
    error = exc.errors()[0]
    field = ".".join(str(part) for part in error.get("loc", ["_payload"]))
    reason = error.get("msg", "is invalid")

    if reason.startswith("Value error, "):
        reason = reason.removeprefix("Value error, ")

    return field, reason


def _ensure_raw_payload_size(raw_payload: str) -> None:
    payload_size = len(raw_payload.encode("utf-8"))
    if payload_size > settings.max_raw_payload_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"Payload is too large: {payload_size} bytes.",
        )


def _payload_preview(raw_payload: str, max_length: int = 500) -> str:
    if len(raw_payload) <= max_length:
        return raw_payload
    return f"{raw_payload[:max_length]}..."


def _decode_message_data(message: dict[str, Any]) -> str:
    data = message.get("data")

    if not isinstance(data, str):
        raise HTTPException(status_code=400, detail="Missing Pub/Sub message.data")

    try:
        return base64.b64decode(data, validate=True).decode("utf-8")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid base64 message.data") from exc


