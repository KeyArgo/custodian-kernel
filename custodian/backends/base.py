"""Abstract approval-backend interface.

A backend's job is narrow and security-critical: send a real, human-checkable
challenge, and later confirm whether a human actually passed it. It must
never be able to hand the code back to the same process that's asking for
approval -- that's the property that makes self-approval structurally
impossible, and every backend implementation must preserve it.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class ApprovalBackend(ABC):
    name: str

    @abstractmethod
    def send_challenge(self, *, amount: float, description: str) -> None:
        """Dispatch a real challenge to a human. Must not return the secret
        challenge value to the caller -- only confirmation that it was sent."""

    @abstractmethod
    def check_response(self, response: str) -> bool:
        """Check a human-supplied response against the backend's own record
        of what was sent. The backend is the only thing that can answer this
        -- it must never be answerable from local state the requesting
        process could have written itself."""
