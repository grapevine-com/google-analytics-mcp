"""Human confirmation for model-requested Google Analytics mutations."""

import platform
import secrets
import subprocess
import time
from dataclasses import dataclass
from typing import Callable


class ConfirmationError(RuntimeError):
    """Raised when a pending mutation cannot be confirmed safely."""


@dataclass(frozen=True)
class PendingMutation:
    operation: str
    arguments: dict
    expires_at: float


class PendingMutationStore:
    """Stores exact mutation previews as short-lived, one-use operations."""

    def __init__(
        self,
        ttl_seconds: int = 300,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.ttl_seconds = ttl_seconds
        self.clock = clock
        self._pending: dict[str, PendingMutation] = {}

    def prepare(self, operation: str, arguments: dict) -> str:
        mutation_id = secrets.token_urlsafe(24)
        self._pending[mutation_id] = PendingMutation(
            operation=operation,
            arguments=dict(arguments),
            expires_at=self.clock() + self.ttl_seconds,
        )
        return mutation_id

    def consume(self, mutation_id: str) -> PendingMutation:
        mutation = self._pending.pop(mutation_id, None)
        if mutation is None:
            raise ConfirmationError(
                "pending mutation not found or already used"
            )
        if self.clock() > mutation.expires_at:
            raise ConfirmationError("pending mutation expired")
        return mutation


class MacOSConfirmer:
    """Requires a click in a native macOS dialog before a mutation executes."""

    _SCRIPT = """
on run argv
  display dialog (item 1 of argv) with title "Google Analytics mutation" buttons {"Cancel", "Confirm"} default button "Cancel" cancel button "Cancel" with icon caution
  return "OK"
end run
""".strip()

    def __init__(self, platform_name: str | None = None):
        self.platform_name = platform_name or platform.system()

    def confirm(self, message: str) -> None:
        if self.platform_name != "Darwin":
            raise ConfirmationError(
                "mutation confirmation requires a local macOS session"
            )
        result = subprocess.run(
            ["osascript", "-e", self._SCRIPT, message],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0 or result.stdout.strip() != "OK":
            raise ConfirmationError("mutation cancelled by user")
