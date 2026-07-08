import asyncio
import base64
import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

os.environ.setdefault("PROJECT_ID", "test-project")
os.environ.setdefault("PUBSUB_TOPIC", "test-topic")
os.environ.setdefault("BQ_DATASET", "test_dataset")
os.environ.setdefault("BQ_TABLE", "test-project.test_dataset.products")
os.environ.setdefault("PUBSUB_OIDC_AUDIENCE", "https://example.run.app")

from app import main


class FakeRequest:
    def __init__(self, body):
        self.body = body

    async def json(self):
        return self.body


class FakeBigQueryOperator:
    def __init__(self):
        self.calls = []

    def insert(self, rows, row_ids=None):
        self.calls.append((rows, row_ids))


def pubsub_envelope(payload, message_id="message-1"):
    raw_payload = payload if isinstance(payload, str) else json.dumps(payload)
    encoded_payload = base64.b64encode(raw_payload.encode("utf-8")).decode("utf-8")
    return {
        "message": {
            "messageId": message_id,
            "data": encoded_payload,
        }
    }


class PubSubEndpointTest(unittest.TestCase):
    def valid_payload(self) -> dict:
        return {
            "id": "57b2d226-4e29-4d00-a7cb-663a81d42229",
            "name": "Test product",
            "description": "Lorem ipsum",
            "is_in_stock": "true",
            "price": "10.50",
            "last_update": "Mon, 17 Jun 2024 13:47:16 UTC",
            "attributes": [{"key": "color", "value": "red"}],
        }

    def run_pubsub(self, envelope):
        return asyncio.run(main.pubsub(FakeRequest(envelope), invoker_email="pubsub-sa@example.com"))

    def test_valid_message_is_inserted_with_message_id_as_row_id(self):
        operator = FakeBigQueryOperator()

        with patch.object(main, "get_bq_operator", return_value=operator):
            response = self.run_pubsub(pubsub_envelope(self.valid_payload(), "message-1"))

        self.assertEqual(response.status_code, 204)
        self.assertEqual(len(operator.calls), 1)
        rows, row_ids = operator.calls[0]
        self.assertEqual(row_ids, ["message-1"])
        self.assertEqual(rows[0]["id"], "57b2d226-4e29-4d00-a7cb-663a81d42229")
        self.assertEqual(rows[0]["_source_message_id"], "message-1")

    def test_missing_message_id_is_rejected(self):
        envelope = pubsub_envelope(self.valid_payload())
        del envelope["message"]["messageId"]

        with self.assertRaises(HTTPException) as context:
            self.run_pubsub(envelope)

        self.assertEqual(context.exception.status_code, 400)
        self.assertEqual(context.exception.detail, "Missing Pub/Sub messageId")

    def test_invalid_payload_is_rejected_without_insert(self):
        operator = FakeBigQueryOperator()
        payload = self.valid_payload()
        payload["price"] = "not-a-number"

        with patch.object(main, "get_bq_operator", return_value=operator):
            with self.assertRaises(HTTPException) as context:
                self.run_pubsub(pubsub_envelope(payload))

        self.assertEqual(context.exception.status_code, 400)
        self.assertEqual(operator.calls, [])

    def test_invalid_json_payload_is_rejected_without_insert(self):
        operator = FakeBigQueryOperator()

        with patch.object(main, "get_bq_operator", return_value=operator):
            with self.assertRaises(HTTPException) as context:
                self.run_pubsub(pubsub_envelope("{not-json}"))

        self.assertEqual(context.exception.status_code, 400)
        self.assertEqual(context.exception.detail, "Payload must be valid JSON")
        self.assertEqual(operator.calls, [])

    def test_payload_too_large_is_rejected_before_insert(self):
        operator = FakeBigQueryOperator()

        with (
            patch.object(main, "settings", SimpleNamespace(max_raw_payload_bytes=5)),
            patch.object(main, "get_bq_operator", return_value=operator),
        ):
            with self.assertRaises(HTTPException) as context:
                self.run_pubsub(pubsub_envelope(self.valid_payload()))

        self.assertEqual(context.exception.status_code, 413)
        self.assertEqual(operator.calls, [])


if __name__ == "__main__":
    unittest.main()
