import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("PROJECT_ID", "test-project")
os.environ.setdefault("PUBSUB_TOPIC", "test-topic")
os.environ.setdefault("BQ_DATASET", "test_dataset")
os.environ.setdefault("BQ_TABLE", "test-project.test_dataset.products")
os.environ.setdefault("PUBSUB_OIDC_AUDIENCE", "https://example.run.app")

from app import bigquery_operator as bq_module
from app.bigquery_operator import BigQueryOperator


class FakeBigQueryClient:
    def __init__(self, errors=None):
        self.calls = []
        self.errors = errors or []

    def insert_rows_json(self, **kwargs):
        self.calls.append(kwargs)
        return self.errors


class BigQueryOperatorTest(unittest.TestCase):
    def make_operator(self) -> BigQueryOperator:
        operator = object.__new__(BigQueryOperator)
        operator.client = FakeBigQueryClient()
        operator.retry_policy = object()
        return operator

    def test_prepare_batch_splits_by_row_count_and_keeps_row_ids(self):
        operator = self.make_operator()
        operator.json_size = lambda row: 1
        settings = SimpleNamespace(max_request_bytes=100, max_rows_per_batch=2)

        with patch.object(bq_module, "settings", settings):
            batches = list(
                operator.prepare_batch(
                    [{"id": 1}, {"id": 2}, {"id": 3}],
                    row_ids=["m1", "m2", "m3"],
                )
            )

        self.assertEqual(
            batches,
            [
                ([{"id": 1}, {"id": 2}], ["m1", "m2"]),
                ([{"id": 3}], ["m3"]),
            ],
        )

    def test_prepare_batch_splits_by_byte_size(self):
        operator = self.make_operator()
        operator.json_size = lambda row: row["size"]
        settings = SimpleNamespace(max_request_bytes=10, max_rows_per_batch=100)

        with patch.object(bq_module, "settings", settings):
            batches = list(
                operator.prepare_batch(
                    [{"size": 6}, {"size": 6}, {"size": 2}],
                    row_ids=["m1", "m2", "m3"],
                )
            )

        self.assertEqual(
            batches,
            [
                ([{"size": 6}], ["m1"]),
                ([{"size": 6}, {"size": 2}], ["m2", "m3"]),
            ],
        )

    def test_prepare_batch_rejects_row_id_count_mismatch(self):
        operator = self.make_operator()

        with self.assertRaises(ValueError):
            list(operator.prepare_batch([{"id": 1}], row_ids=[]))

    def test_prepare_batch_rejects_single_row_over_limit(self):
        operator = self.make_operator()
        operator.json_size = lambda row: 11
        settings = SimpleNamespace(max_request_bytes=10, max_rows_per_batch=100)

        with patch.object(bq_module, "settings", settings):
            with self.assertRaises(ValueError):
                list(operator.prepare_batch([{"id": 1}]))

    def test_insert_passes_row_ids_to_bigquery(self):
        operator = self.make_operator()
        operator.json_size = lambda row: 1
        settings = SimpleNamespace(
            max_request_bytes=100,
            max_rows_per_batch=1,
            bq_table="project.dataset.table",
            bq_timeout=30.0,
        )

        with patch.object(bq_module, "settings", settings):
            operator.insert([{"id": 1}, {"id": 2}], row_ids=["m1", "m2"])

        self.assertEqual(len(operator.client.calls), 2)
        self.assertEqual(operator.client.calls[0]["row_ids"], ["m1"])
        self.assertEqual(operator.client.calls[1]["row_ids"], ["m2"])

    def test_insert_raises_on_bigquery_errors(self):
        operator = self.make_operator()
        operator.client = FakeBigQueryClient(errors=[{"index": 0, "errors": ["bad"]}])
        operator.json_size = lambda row: 1
        settings = SimpleNamespace(
            max_request_bytes=100,
            max_rows_per_batch=100,
            bq_table="project.dataset.table",
            bq_timeout=30.0,
        )

        with patch.object(bq_module, "settings", settings):
            with self.assertRaises(RuntimeError):
                operator.insert([{"id": 1}], row_ids=["m1"])


if __name__ == "__main__":
    unittest.main()
