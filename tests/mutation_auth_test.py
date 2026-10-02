# Copyright 2026 Grapevine

import json
import unittest
from unittest import mock

from analytics_mcp.mutations.auth import (
    ANALYTICS_EDIT_SCOPE,
    CredentialManager,
)


class FakeCredentialStore:
    def __init__(self, value=None):
        self.value = value

    def load(self):
        return self.value

    def save(self, value):
        self.value = value

    def delete(self):
        self.value = None


class FakeCredentials:
    def __init__(self, *, valid=True, expired=False, refresh_token="refresh"):
        self.valid = valid
        self.expired = expired
        self.refresh_token = refresh_token
        self.scopes = [ANALYTICS_EDIT_SCOPE]
        self.refresh = mock.Mock(side_effect=self._mark_valid)

    def _mark_valid(self, request):
        self.valid = True
        self.expired = False

    def to_json(self):
        return json.dumps(
            {
                "token": "access-token",
                "refresh_token": self.refresh_token,
                "scopes": self.scopes,
            }
        )


class CredentialManagerTest(unittest.TestCase):
    def test_authorize_requests_edit_scope_and_persists_credentials(self):
        store = FakeCredentialStore()
        credentials = FakeCredentials()
        flow = mock.Mock()
        flow.run_local_server.return_value = credentials
        flow_factory = mock.Mock(return_value=flow)
        manager = CredentialManager(
            store=store,
            flow_factory=flow_factory,
            credentials_loader=mock.Mock(),
            request_factory=mock.Mock(),
        )

        result = manager.authorize("/tmp/oauth-client.json")

        flow_factory.assert_called_once_with(
            "/tmp/oauth-client.json", [ANALYTICS_EDIT_SCOPE]
        )
        flow.run_local_server.assert_called_once_with(
            host="localhost",
            port=0,
            authorization_prompt_message=(
                "Open this URL to authorize Google Analytics access: {url}"
            ),
            success_message=(
                "Authorization complete. You can close this browser window."
            ),
            open_browser=True,
            access_type="offline",
            prompt="consent",
        )
        self.assertIn("refresh_token", json.loads(store.value))
        self.assertEqual(
            result, {"authorized": True, "scope": ANALYTICS_EDIT_SCOPE}
        )

    def test_get_credentials_refreshes_and_persists_expired_token(self):
        stored = json.dumps({"refresh_token": "refresh"})
        store = FakeCredentialStore(stored)
        credentials = FakeCredentials(valid=False, expired=True)
        loader = mock.Mock(return_value=credentials)
        request = object()
        manager = CredentialManager(
            store=store,
            flow_factory=mock.Mock(),
            credentials_loader=loader,
            request_factory=mock.Mock(return_value=request),
        )

        result = manager.get_credentials()

        self.assertIs(result, credentials)
        loader.assert_called_once_with(
            json.loads(stored), [ANALYTICS_EDIT_SCOPE]
        )
        credentials.refresh.assert_called_once_with(request)
        self.assertTrue(json.loads(store.value)["refresh_token"])

    def test_status_and_disconnect_do_not_return_tokens(self):
        store = FakeCredentialStore(json.dumps({"refresh_token": "secret"}))
        credentials = FakeCredentials()
        manager = CredentialManager(
            store=store,
            flow_factory=mock.Mock(),
            credentials_loader=mock.Mock(return_value=credentials),
            request_factory=mock.Mock(),
        )

        status = manager.status()
        disconnected = manager.disconnect()

        self.assertEqual(
            status, {"authorized": True, "scope": ANALYTICS_EDIT_SCOPE}
        )
        self.assertNotIn("secret", repr(status))
        self.assertEqual(disconnected, {"authorized": False})
        self.assertIsNone(store.value)

    def test_missing_credentials_fail_with_authorization_instruction(self):
        manager = CredentialManager(
            store=FakeCredentialStore(),
            flow_factory=mock.Mock(),
            credentials_loader=mock.Mock(),
            request_factory=mock.Mock(),
        )

        with self.assertRaisesRegex(RuntimeError, "authorize"):
            manager.get_credentials()


if __name__ == "__main__":
    unittest.main()
