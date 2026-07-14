"""The Broker — the only door between an agent and a secret value.

The rules it enforces:

1. **Grants first.** Every resolution passes ``GrantPolicy.check`` —
   deny-by-default, band-ceilinged, expirable.
2. **Egress only.** There is no public "give me the plaintext" method
   for agent code. Secrets leave the broker exclusively as environment
   variables of a *subprocess* (or a NemoClaw sandbox exec) that the
   broker itself launches. The agent gets the child's stdout — never
   the env.
3. **Everything audited.** Resolve, deny, grant, revoke — all land in
   the hash-chained audit log.
4. **Leak tripwire.** Every value that crosses egress registers its
   SHA-256 (of the value, and per-token) in ``leak_sentinel``. The
   secret-leak-guard adapter hashes candidate tokens in tool output and
   trips if any match — catching a secret coming *back* into the
   agent's context even though the agent never saw it go out.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path
from typing import Mapping, Optional, Sequence

from warden.audit import AuditLog
from warden.errors import GrantDeniedError, UnknownRefError
from warden.grants import GrantPolicy
from warden.refs import SecretRef
from warden.vault import Vault

AUDIT_FILENAME = "audit.jsonl"


class LeakSentinel:
    """In-memory registry of hashes of every value that crossed egress.

    Stores only SHA-256 digests — holding the sentinel never yields a
    secret. ``seen()`` answers: does this exact token match any value
    (or any whitespace-split token of a value) that Warden released?
    """

    def __init__(self) -> None:
        self._hashes: set[str] = set()

    @staticmethod
    def _h(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8", "surrogatepass")).hexdigest()

    def register(self, value: str) -> None:
        self._hashes.add(self._h(value))
        for tok in value.split():
            if len(tok) >= 8:  # skip trivially guessable fragments
                self._hashes.add(self._h(tok))

    def seen(self, token: str) -> bool:
        return len(token) >= 8 and self._h(token) in self._hashes

    def __len__(self) -> int:
        return len(self._hashes)


class Broker:
    """Grant-gated, audited egress for one vault."""

    def __init__(self, vault: Vault, audit_path: Optional[Path] = None) -> None:
        self.vault = vault
        self.grants = GrantPolicy(vault)
        self.audit = AuditLog(
            audit_path or vault.path.parent / AUDIT_FILENAME, vault.audit_key()
        )
        self.leak_sentinel = LeakSentinel()

    # -- internal resolution (audited, grant-gated) ---------------------------

    def _resolve(self, ref: SecretRef | str, requester: str, band: str) -> str:
        ref = SecretRef.parse(str(ref))
        try:
            grant = self.grants.check(ref.name, requester, band)
        except GrantDeniedError:
            self.audit.append("deny", ref.name, requester, band, "no matching grant")
            raise
        try:
            value = self.vault._resolve_value(ref.name)
        except UnknownRefError:
            self.audit.append("deny", ref.name, requester, band, "unknown ref")
            raise
        self.audit.append("resolve", ref.name, requester, band,
                          f"grant={grant.ref_pattern}")
        self.leak_sentinel.register(value)
        return value

    # -- egress surfaces -------------------------------------------------------

    def build_env(self, refs: Mapping[str, SecretRef | str], requester: str,
                  band: str = "L0", base_env: Optional[Mapping[str, str]] = None) -> dict:
        """Materialize {ENV_VAR: value} for the given {ENV_VAR: ref} map.

        Host-side glue (bridge/executor) may call this to hand an env to a
        transport it controls. It must never be exposed to agent code as a
        tool — the tool surface is spawn()/NemoClaw exec only.
        """
        env = dict(base_env if base_env is not None else os.environ)
        for var, ref in refs.items():
            env[var] = self._resolve(ref, requester, band)
        return env

    def env_for_profile(self, profile: str, requester: str, band: str = "L0",
                        base_env: Optional[Mapping[str, str]] = None) -> dict:
        """Env-manager mode: materialize every entry in a profile under its
        configured env var name (e.g. the whole `prod` profile at once)."""
        env = dict(base_env if base_env is not None else os.environ)
        for meta in self.vault.iter_meta(profile):
            var = meta["env_var"]
            env[var] = self._resolve(SecretRef(meta["name"]), requester, band)
        return env

    def spawn(self, cmd: Sequence[str], refs: Mapping[str, SecretRef | str],
              requester: str, band: str = "L0", profile: Optional[str] = None,
              timeout: Optional[float] = None,
              capture_output: bool = True) -> subprocess.CompletedProcess:
        """Run `cmd` with secrets injected into its environment.

        This is the canonical egress: the child process sees the values;
        the caller sees only the CompletedProcess. shell=False always —
        cmd is an argv list, never a string handed to a shell.
        """
        env = self.build_env(refs, requester, band)
        if profile:
            env = self.env_for_profile(profile, requester, band, base_env=env)
        return subprocess.run(
            list(cmd), env=env, timeout=timeout,
            capture_output=capture_output, text=True, shell=False,
        )

    # -- passthrough management (CLI convenience, all audited) ----------------

    def grant(self, ref_pattern: str, requester: str, max_band: str = "L2",
              ttl_seconds: Optional[float] = None, note: str = ""):
        g = self.grants.grant(ref_pattern, requester, max_band, ttl_seconds, note)
        self.audit.append("grant", ref_pattern, requester, max_band, note)
        return g

    def revoke(self, ref_pattern: str, requester: str) -> int:
        removed = self.grants.revoke(ref_pattern, requester)
        self.audit.append("revoke", ref_pattern, requester, "-", f"removed={removed}")
        return removed
