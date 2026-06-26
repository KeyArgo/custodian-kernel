"""The AI layer of a policy pack: turn a messy real-world input into an
Envelope. This is the ONE place an LLM is allowed to touch the flow.

Two hard rules enforced by construction:

  1. The agent never sees ground-truth values. It is handed the customer's
     message, the human-readable policy, and the *names* of the ledger fields
     it may assert against -- never their values. It proposes claims
     ("delivered should be false"); the deterministic verifier later resolves
     the real value and decides whether the claim holds. The agent cannot peek
     at the answer and cannot mark its own homework.

  2. The agent never returns an authority decision. Its output is an Envelope,
     whose `recommended_disposition` is explicitly advisory. The deterministic
     adapter re-derives the real disposition; the kernel forces the human.

The client is pluggable. `NvidiaNemotronClient` calls the real hosted Nemotron
3 Super model (the same model and provider the sandboxed agent itself uses, via
a separate dashboard-side key). `CapturedClient` replays an Envelope captured
from a prior real run, so the demo and the test suite are reproducible on a box
with no API key -- and it is always labelled as captured, never passed off as
a fresh model call.
"""
from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Protocol

from custodian.packs.base import Envelope

_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


class LLMClient(Protocol):
    name: str
    live: bool

    def complete(self, system: str, user: str) -> str: ...


@dataclass
class NvidiaNemotronClient:
    """Calls the real hosted Nemotron 3 Super over NVIDIA's inference API --
    the exact model that powers the agent. Mirrors the dashboard's existing
    nemotron_chat client (same endpoint, same key file, thinking disabled)."""
    secret_file: Path
    endpoint: str = "https://integrate.api.nvidia.com/v1/chat/completions"
    model: str = "nvidia/nemotron-3-super-120b-a12b"
    timeout: int = 40
    name: str = "nemotron-3-super-120b (live)"
    live: bool = True

    def _key(self) -> str:
        for line in self.secret_file.read_text().splitlines():
            if line.startswith("NVIDIA_API_KEY="):
                return line.split("=", 1)[1].strip()
        raise RuntimeError("NVIDIA_API_KEY not found in secret file")

    def complete(self, system: str, user: str) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": 1200,
            "temperature": 0.2,  # extraction wants determinism, not flair
            "chat_template_kwargs": {"thinking": False},
        }
        req = urllib.request.Request(
            self.endpoint,
            data=json.dumps(payload).encode(),
            headers={"Authorization": f"Bearer {self._key()}",
                     "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            result = json.loads(resp.read())
        return result["choices"][0]["message"]["content"]


@dataclass
class CapturedClient:
    """Replays a stored Envelope dict. Honest by construction: `live` is False
    and `name` says 'captured', so anything rendered from it is labelled as a
    captured run, not a fresh model call."""
    envelope_dict: dict
    name: str = "captured agent output"
    live: bool = False

    def complete(self, system: str, user: str) -> str:
        return json.dumps(self.envelope_dict)


class EnvelopeParseError(ValueError):
    pass


def parse_envelope(raw: str, *, fallback_meta: Optional[dict] = None) -> Envelope:
    """Extract the first JSON object from a model response and build an
    Envelope. `fallback_meta` supplies case_id/customer_id/order_id/amount/
    requested_action if the model omitted them (it should not, but we own those
    facts -- they are request metadata, not model judgment)."""
    match = _JSON_BLOCK.search(raw)
    if not match:
        raise EnvelopeParseError(f"no JSON object found in model output: {raw[:200]!r}")
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as e:
        raise EnvelopeParseError(f"model output was not valid JSON: {e}") from e
    if fallback_meta:
        for k, v in fallback_meta.items():
            data.setdefault(k, v)
    try:
        return Envelope.from_dict(data)
    except (KeyError, TypeError) as e:
        raise EnvelopeParseError(f"model JSON missing required fields: {e}") from e
