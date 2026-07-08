import logging

from fastapi import Header, HTTPException, status
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

from app.config.settings import settings

logger = logging.getLogger(__name__)
_google_request = google_requests.Request()


async def verify_pubsub_oidc(authorization: str | None = Header(default=None)) -> str:
    if not settings.require_pubsub_oidc:
        logger.warning("Pub/Sub OIDC verification is disabled.")
        return "auth-disabled"

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header.",
        )

    token = authorization.removeprefix("Bearer ").strip()

    try:
        claims = id_token.verify_oauth2_token(
            token,
            _google_request,
            audience=settings.pubsub_oidc_audience,
        )
    except ValueError as exc:
        logger.warning("Invalid Pub/Sub OIDC token: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid OIDC token.",
        ) from exc

    email = claims.get("email")
    email_verified = claims.get("email_verified", False)

    if not isinstance(email, str) or not email_verified:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="OIDC token does not contain a verified service account email.",
        )

    if settings.pubsub_oidc_service_account and email != settings.pubsub_oidc_service_account:
        logger.warning("Rejected Pub/Sub push from unexpected service account: %s", email)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Unexpected Pub/Sub service account.",
        )

    return email
