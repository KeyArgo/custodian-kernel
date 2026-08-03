"""Broker-only adapter for Bitwarden Secrets Manager's ``bws`` CLI.

This module deliberately exposes neither secret inventory nor a general CLI
runner.  A trusted broker gets an explicitly configured reference name and
fixed UUID; an agent can name only that reference through normal Paladin
egress.  The BWS access token remains in the broker's environment.
"""
from __future__ import annotations

import json
import os
import subprocess
import uuid
from dataclasses import dataclass
from typing import Callable, Mapping, Optional, Sequence

from paladin.errors import ExternalSecretProviderError, UnknownRefError


@dataclass(frozen=True)
class BitwardenSecret:
    """One preconfigured BWS secret, with its mandatory egress ceiling."""

    secret_id: str
    allowed_hosts: tuple[str, ...]

    def __post_init__(self) -> None:
        try:
            uuid.UUID(self.secret_id)
        except (ValueError, AttributeError, TypeError) as exc:
            raise ValueError("Bitwarden secret_id must be a UUID") from exc
        if not self.allowed_hosts:
            raise ValueError("Bitwarden secrets require at least one allowed host")


class BitwardenSecretProvider:
    """Resolve a fixed BWS secret for a trusted broker only.

    ``mapping`` is configured by the operator, not supplied by the agent.
    The only command this provider can execute is ``bws secret get`` for the
    preconfigured UUID.  It never supports ``list`` or ``run``.
    """

    def __init__(self, mapping: Mapping[str, BitwardenSecret], *,
                 binary: str = "bws", access_token_env: str = "BWS_ACCESS_TOKEN",
                 config_file: Optional[str] = None,
                 runner: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> None:
        self._mapping = dict(mapping)
        self._binary = binary
        self._access_token_env = access_token_env
        self._config_file = config_file
        self._runner = runner

    def has_ref(self, name: str) -> bool:
        return name in self._mapping

    def allowed_hosts(self, name: str) -> tuple[str, ...]:
        try:
            return self._mapping[name].allowed_hosts
        except KeyError as exc:
            raise UnknownRefError(f"unknown external ref {name!r}") from exc

    def resolve(self, name: str) -> str:
        try:
            spec = self._mapping[name]
        except KeyError as exc:
            raise UnknownRefError(f"unknown external ref {name!r}") from exc
        token = os.environ.get(self._access_token_env)
        if not token:
            raise ExternalSecretProviderError("Bitwarden broker token is unavailable")
        argv: list[str] = [self._binary, "secret", "get", spec.secret_id, "--output", "json"]
        if self._config_file:
            argv.extend(["--config-file", self._config_file])
        # Do not pass through proxy, shell, or application variables. The BWS
        # token is visible only to this broker subprocess, never agent code.
        env = {"PATH": os.defpath, self._access_token_env: token}
        try:
            completed = self._runner(argv, env=env, capture_output=True, text=True,
                                     timeout=30, shell=False, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ExternalSecretProviderError("Bitwarden secret retrieval failed") from exc
        if completed.returncode != 0:
            # stdout/stderr may contain sensitive material: never propagate it.
            raise ExternalSecretProviderError("Bitwarden secret retrieval was rejected")
        try:
            payload = json.loads(completed.stdout)
            if not isinstance(payload, dict) or payload.get("id") != spec.secret_id:
                raise ValueError("unexpected secret response")
            value = payload.get("value")
            if not isinstance(value, str) or not value:
                raise ValueError("missing secret value")
            return value
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ExternalSecretProviderError("Bitwarden returned an invalid secret response") from exc
