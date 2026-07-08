import unittest

from pydantic import ValidationError

from app.parser import parse_product


class ParseProductTest(unittest.TestCase):
    def valid_payload(self) -> dict:
        return {
            "id": "57b2d226-4e29-4d00-a7cb-663a81d42229",
            "name": "Test product",
            "description": "Lorem ipsum",
            "is_in_stock": "false",
            "price": "873.06",
            "last_update": "Mon, 17 Jun 2024 13:47:16 UTC",
            "attributes": [{"key": "color", "value": "red"}],
        }

    def test_parse_valid_product(self):
        row = parse_product(self.valid_payload(), "message-1", '{"id":"test"}')

        self.assertEqual(row["id"], "57b2d226-4e29-4d00-a7cb-663a81d42229")
        self.assertEqual(row["name"], "Test product")
        self.assertFalse(row["is_in_stock"])
        self.assertEqual(row["price"], "873.06")
        self.assertEqual(row["last_update"], "2024-06-17T13:47:16+00:00")
        self.assertEqual(row["attributes"], [{"key": "color", "value": "red"}])
        self.assertEqual(row["_source_message_id"], "message-1")
        self.assertEqual(row["_raw_payload"], '{"id":"test"}')
        self.assertIn("_insert_timestamp", row)

    def test_rejects_invalid_price(self):
        payload = self.valid_payload()
        payload["price"] = "not-a-number"

        with self.assertRaises(ValidationError) as context:
            parse_product(payload, "message-1", "{}")

        self.assertEqual(context.exception.errors()[0]["loc"], ("price",))

    def test_rejects_negative_price(self):
        payload = self.valid_payload()
        payload["price"] = "-1.00"

        with self.assertRaises(ValidationError) as context:
            parse_product(payload, "message-1", "{}")

        error = context.exception.errors()[0]
        self.assertEqual(error["loc"], ("price",))
        self.assertIn("greater than or equal to 0", error["msg"])

    def test_rejects_extra_payload_fields(self):
        payload = self.valid_payload()
        payload["unexpected"] = "value"

        with self.assertRaises(ValidationError) as context:
            parse_product(payload, "message-1", "{}")

        self.assertEqual(context.exception.errors()[0]["loc"], ("unexpected",))

    def test_rejects_extra_attribute_fields(self):
        payload = self.valid_payload()
        payload["attributes"] = [{"key": "color", "value": "red", "extra": "nope"}]

        with self.assertRaises(ValidationError) as context:
            parse_product(payload, "message-1", "{}")

        self.assertEqual(context.exception.errors()[0]["loc"], ("attributes", 0, "extra"))


if __name__ == "__main__":
    unittest.main()
