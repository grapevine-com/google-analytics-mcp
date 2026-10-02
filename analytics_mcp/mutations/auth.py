"""Personal Google OAuth credentials stored in the operating-system keyring."""

import asyncio
import json
import os
import threading
from typing import Callable

from analytics_mcp.tools import client as analytics_client

ANALYTICS_EDIT_SCOPE = "https://www.googleapis.com/auth/analytics.edit"
ANALYTICS_READ_SCOPE = "https://www.googleapis.com/auth/analytics.readonly"
ANALYTICS_SCOPES = [ANALYTICS_EDIT_SCOPE, ANALYTICS_READ_SCOPE]
_KEYRING_SERVICE = "analytics-mutations-mcp"
_KEYRING_USERNAME = "google-oauth-credentials"
_CLIENT_SECRETS_ENV = "GOOGLE_ANALYTICS_OAUTH_CLIENT_SECRETS"


class KeyringCredentialStore:
    """Stores OAuth credentials in the user's operating-system keyring."""

    def __init__(
        self,
        service_name: str = _KEYRING_SERVICE,
        username: str = _KEYRING_USERNAME,
    ):
        self.service_name = service_name
        self.username = username

    def load(self) -> str | None:
        import keyring

        return keyring.get_password(self.service_name, self.username)

    def save(self, value: str) -> None:
        import keyring

        keyring.set_password(self.service_name, self.username, value)

    def delete(self) -> None:
        import keyring
        from keyring.errors import PasswordDeleteError

        try:
            keyring.delete_password(self.service_name, self.username)
        except PasswordDeleteError:
            pass


def _flow_factory(client_secrets_file: str, scopes: list[str]):
    from google_auth_oauthlib.flow import InstalledAppFlow

    return InstalledAppFlow.from_client_secrets_file(
        client_secrets_file, scopes=scopes, autogenerate_code_verifier=True
    )


def _credentials_loader(info: dict, scopes: list[str]):
    from google.oauth2.credentials import Credentials

    return Credentials.from_authorized_user_info(info, scopes=scopes)


def _request_factory():
    from google.auth.transport.requests import Request

    return Request()


class CredentialManager:
    """Owns the installed-app OAuth lifecycle for one local operator."""

    def __init__(
        self,
        store=None,
        flow_factory: Callable = _flow_factory,
        credentials_loader: Callable = _credentials_loader,
        request_factory: Callable = _request_factory,
    ):
        self.store = store or KeyringCredentialStore()
        self.flow_factory = flow_factory
        self.credentials_loader = credentials_loader
        self.request_factory = request_factory
        self._lock = threading.RLock()

    def authorize(self, client_secrets_file: str) -> dict:
        with self._lock:
            return self._authorize(client_secrets_file)

    def _authorize(self, client_secrets_file: str) -> dict:
        flow = self.flow_factory(client_secrets_file, ANALYTICS_SCOPES)
        credentials = flow.run_local_server(
            host="localhost",
            port=0,
            authorization_prompt_message=None,
            success_message=(
                "Authorization complete. You can close this browser window."
            ),
            open_browser=True,
            access_type="offline",
            prompt="consent",
        )
        if not credentials.refresh_token:
            raise RuntimeError(
                "Google did not return a refresh token; revoke the app grant "
                "and authorize again"
            )
        self.store.save(credentials.to_json())
        self._activate(credentials)
        return {"authorized": True, "scopes": ANALYTICS_SCOPES}

    def get_credentials(self):
        with self._lock:
            return self._get_credentials()

    def _get_credentials(self):
        serialized = self.store.load()
        if not serialized:
            raise RuntimeError(
                "Google Analytics is not authorized; call "
                "google_analytics_authorize first"
            )
        credentials = self.credentials_loader(
            json.loads(serialized), ANALYTICS_SCOPES
        )
        if not credentials.valid:
            if credentials.expired and credentials.refresh_token:
                credentials.refresh(self.request_factory())
                self.store.save(credentials.to_json())
            else:
                raise RuntimeError(
                    "Stored Google authorization is invalid; authorize again"
                )
        self._activate(credentials)
        return credentials

    def status(self) -> dict:
        with self._lock:
            if not self.store.load():
                return {"authorized": False, "scopes": ANALYTICS_SCOPES}
            self.get_credentials()
            return {"authorized": True, "scopes": ANALYTICS_SCOPES}

    def disconnect(self) -> dict:
        with self._lock:
            self.store.delete()
            with analytics_client._client_lock:
                analytics_client._CREDENTIALS = None
            return {"authorized": False}

    @staticmethod
    def _activate(credentials) -> None:
        with analytics_client._client_lock:
            analytics_client._CREDENTIALS = credentials


credential_manager = CredentialManager()


async def google_analytics_authorize(
    client_secrets_file: str | None = None,
) -> dict:
    """Authorize this local server as you with full Analytics edit access.

    A browser window opens for Google consent. The resulting refresh credential
    is stored in the operating-system keyring. Set
    GOOGLE_ANALYTICS_OAUTH_CLIENT_SECRETS or pass the downloaded OAuth desktop
    client JSON path.
    """
    path = client_secrets_file or os.environ.get(_CLIENT_SECRETS_ENV)
    if not path:
        raise ValueError(
            "client_secrets_file is required unless "
            f"{_CLIENT_SECRETS_ENV} is set"
        )
    return await asyncio.to_thread(credential_manager.authorize, path)


async def google_analytics_auth_status() -> dict:
    """Return whether personal Google Analytics OAuth is currently usable."""
    return await asyncio.to_thread(credential_manager.status)


async def google_analytics_disconnect() -> dict:
    """Delete the locally stored Google OAuth credential."""
    return await asyncio.to_thread(credential_manager.disconnect)
