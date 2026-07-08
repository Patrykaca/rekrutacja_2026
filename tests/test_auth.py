import asyncio
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

from app import auth


class PubSubOidcAuthTest(unittest.TestCase):
    def auth_settings(self, expected_service_account="pubsub-push@test-project.iam.gserviceaccount.com"):
        return SimpleNamespace(
            require_pubsub_oidc=True,
            pubsub_oidc_audience="https://example.run.app",
            pubsub_oidc_service_account=expected_service_account,
        )

    def test_missing_authorization_header_is_rejected_when_auth_required(self):
        settings = self.auth_settings()

        with patch.object(auth, "settings", settings):
            with self.assertRaises(HTTPException) as context:
                asyncio.run(auth.verify_pubsub_oidc(None))

        self.assertEqual(context.exception.status_code, 401)

    def test_auth_can_be_disabled_for_local_development(self):
        settings = SimpleNamespace(require_pubsub_oidc=False)

        with patch.object(auth, "settings", settings):
            invoker = asyncio.run(auth.verify_pubsub_oidc(None))

        self.assertEqual(invoker, "auth-disabled")

    def test_valid_oidc_token_returns_verified_service_account_email(self):
        settings = self.auth_settings()
        claims = {
            "email": "pubsub-push@test-project.iam.gserviceaccount.com",
            "email_verified": True,
        }

        with (
            patch.object(auth, "settings", settings),
            patch.object(auth.id_token, "verify_oauth2_token", return_value=claims) as verify_token,
        ):
            invoker = asyncio.run(auth.verify_pubsub_oidc("Bearer valid-token"))

        self.assertEqual(invoker, "pubsub-push@test-project.iam.gserviceaccount.com")
        verify_token.assert_called_once()
        args, kwargs = verify_token.call_args
        self.assertEqual(args[0], "valid-token")
        self.assertEqual(kwargs["audience"], "https://example.run.app")

    def test_unexpected_service_account_is_rejected(self):
        settings = self.auth_settings()
        claims = {
            "email": "other-sa@test-project.iam.gserviceaccount.com",
            "email_verified": True,
        }

        with (
            patch.object(auth, "settings", settings),
            patch.object(auth.id_token, "verify_oauth2_token", return_value=claims),
        ):
            with self.assertRaises(HTTPException) as context:
                asyncio.run(auth.verify_pubsub_oidc("Bearer valid-token"))

        self.assertEqual(context.exception.status_code, 403)
        self.assertEqual(context.exception.detail, "Unexpected Pub/Sub service account.")


if __name__ == "__main__":
    unittest.main()
