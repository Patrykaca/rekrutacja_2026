import os
from dataclasses import dataclass


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "y"}


@dataclass(frozen=True)
class Settings:
    project_id: str
    pubsub_topic: str
    bq_dataset: str
    bq_table: str
    bq_timeout: float
    max_request_bytes: int
    max_raw_payload_bytes: int
    max_rows_per_batch: int
    require_pubsub_oidc: bool
    pubsub_oidc_audience: str | None
    pubsub_oidc_service_account: str | None
    log_level: str

    def __post_init__(self) -> None:
        if self.bq_timeout <= 0:
            raise ValueError("BQ_TIMEOUT must be greater than 0.")
        if self.max_request_bytes <= 0:
            raise ValueError("MAX_REQUEST_BYTES must be greater than 0.")
        if self.max_raw_payload_bytes <= 0:
            raise ValueError("MAX_RAW_PAYLOAD_BYTES must be greater than 0.")
        if self.max_raw_payload_bytes > self.max_request_bytes:
            raise ValueError("MAX_RAW_PAYLOAD_BYTES must be less than or equal to MAX_REQUEST_BYTES.")
        if self.max_rows_per_batch <= 0:
            raise ValueError("MAX_ROWS_PER_BATCH must be greater than 0.")
        if self.require_pubsub_oidc and not self.pubsub_oidc_audience:
            raise ValueError("PUBSUB_OIDC_AUDIENCE is required when REQUIRE_PUBSUB_OIDC is true.")


settings = Settings(
    project_id=os.environ["PROJECT_ID"],
    pubsub_topic=os.environ["PUBSUB_TOPIC"],
    bq_dataset=os.environ["BQ_DATASET"],
    bq_table=os.environ["BQ_TABLE"],
    bq_timeout=float(os.getenv("BQ_TIMEOUT", 30)),
    max_request_bytes=int(os.getenv("MAX_REQUEST_BYTES", 9 * 1024 * 1024)),
    max_raw_payload_bytes=int(os.getenv("MAX_RAW_PAYLOAD_BYTES", 8 * 1024 * 1024)),
    max_rows_per_batch=int(os.getenv("MAX_ROWS_PER_BATCH", 250)),
    require_pubsub_oidc=_env_bool("REQUIRE_PUBSUB_OIDC", True),
    pubsub_oidc_audience=os.getenv("PUBSUB_OIDC_AUDIENCE"),
    pubsub_oidc_service_account=os.getenv("PUBSUB_OIDC_SERVICE_ACCOUNT"),
    log_level=os.getenv("LOG_LEVEL", "INFO"),

)
