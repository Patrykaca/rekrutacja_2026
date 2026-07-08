import json
from collections.abc import Iterator
from typing import Any

from google.cloud import bigquery
from google.api_core.retry import Retry

from app.config.settings import settings


class BigQueryOperator:
    def __init__(self) -> None:
        self.client = bigquery.Client(project=settings.project_id)
        self.retry_policy = Retry(
            initial=1.0,
            maximum=10.0,
            multiplier=2.0,
            timeout=30.0,
        )

    def json_size(self, json_data: dict[str, Any]) -> int:
        return len(json.dumps(json_data, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))

    def prepare_batch(
        self,
        rows: list[dict[str, Any]],
        row_ids: list[str] | None = None,
    ) -> Iterator[tuple[list[dict[str, Any]], list[str] | None]]:
        if row_ids is not None and len(row_ids) != len(rows):
            raise ValueError("row_ids length must match rows length.")

        batch = []
        batch_row_ids = [] if row_ids is not None else None
        batch_size = 0

        for index, row in enumerate(rows):
            row_size = self.json_size(row)
            if row_size > settings.max_request_bytes:
                raise ValueError(f"Row size exceeds maximum request size: {row_size} bytes.")

            if batch and (
                    len(batch) >= settings.max_rows_per_batch
                    or (batch_size + row_size) > settings.max_request_bytes):
                yield batch, batch_row_ids
                batch = []
                batch_row_ids = [] if row_ids is not None else None
                batch_size = 0

            batch.append(row)
            if batch_row_ids is not None:
                batch_row_ids.append(row_ids[index])
            batch_size += row_size

        if batch:
            yield batch, batch_row_ids

    def insert(self, rows: list[dict[str, Any]], row_ids: list[str] | None = None) -> None:
        for batch, batch_row_ids in self.prepare_batch(rows, row_ids):
            insert_kwargs = {
                "table": settings.bq_table,
                "json_rows": batch,
                "timeout": settings.bq_timeout,
                "retry": self.retry_policy,
            }
            if batch_row_ids is not None:
                insert_kwargs["row_ids"] = batch_row_ids

            errors = self.client.insert_rows_json(**insert_kwargs)
            if errors:
                raise RuntimeError(f"BigQuery insert failed for {settings.bq_table}: {errors}.")
