"""NemoClaw inference router — tries endpoints in priority order with fallback.

Implements the same LLMClient protocol as NvidiaNemotronClient so it is a
drop-in replacement. Endpoint order: OpenRouter → NVIDIA NIM.

OpenRouter is primary: faster failover between its upstream providers, more
reliable uptime than NIM direct. NIM is secondary in case OpenRouter is down.

Note: DGX Spark runs the enforcement kernel only (:8095/decide). Inference
always goes to a cloud endpoint — never local.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

DEFAULT_ENDPOINTS = [
    # 1. OpenRouter — primary (reliable, fast failover between providers)
    "https://openrouter.ai/api/v1/chat/completions",
    # 2. NVIDIA NIM — secondary, requires NVIDIA key
    "https://integrate.api.nvidia.com/v1/chat/completions",
]
NVIDIA_HOSTED = "integrate.api.nvidia.com"
OPENROUTER_HOSTED = "openrouter.ai"
OLLAMA_HOSTED = "ollama"

# Model to use on OpenRouter when falling back — env-overridable.
OPENROUTER_FALLBACK_MODEL = os.environ.get(
    "OPENROUTER_FALLBACK_MODEL", "nvidia/nemotron-3-super-120b-a12b:free"
)

# Local Ollama inference — set OLLAMA_HOST to enable fallback (default: localhost:11434).
# Only used when all cloud endpoints are unreachable or have no keys configured.
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")


@dataclass
class NemoClawRouter:
    """Tries endpoints in order, falls back on timeout or connection error.
    Endpoint priority: OpenRouter (cloud) → NVIDIA NIM (cloud). DGX Spark runs
    the enforcement kernel only (:8095/decide) — it never serves inference.
    name and live reflect the endpoint that actually responded."""
    endpoints: list[str] = field(default_factory=lambda: list(DEFAULT_ENDPOINTS))
    model: str = "nvidia/llama-3.3-nemotron-super-49b-v1"
    timeout: int = 2        # seconds per endpoint attempt before fallback
    nvidia_api_key_file: Optional[Path] = None
    openrouter_key_file: Optional[Path] = None
    name: str = "nemoclaw-router (not yet called)"
    live: bool = False

    def _nvidia_key(self) -> Optional[str]:
        if env_key := os.environ.get("NVIDIA_API_KEY"):
            return env_key
        if self.nvidia_api_key_file and self.nvidia_api_key_file.exists():
            for line in self.nvidia_api_key_file.read_text().splitlines():
                if line.startswith("NVIDIA_API_KEY="):
                    return line.split("=", 1)[1].strip()
        return None

    def _openrouter_key(self) -> Optional[str]:
        if env_key := os.environ.get("OPENROUTER_API_KEY"):
            return env_key
        if self.openrouter_key_file and self.openrouter_key_file.exists():
            for line in self.openrouter_key_file.read_text().splitlines():
                if line.startswith("OPENROUTER_API_KEY="):
                    return line.split("=", 1)[1].strip()
        return None

    def _model_for(self, endpoint: str) -> str:
        if OPENROUTER_HOSTED in endpoint:
            return OPENROUTER_FALLBACK_MODEL
        return self.model

    def _headers_for(self, endpoint: str) -> dict:
        headers = {"Content-Type": "application/json"}
        if NVIDIA_HOSTED in endpoint:
            key = self._nvidia_key()
            if key:
                headers["Authorization"] = f"Bearer {key}"
        elif OPENROUTER_HOSTED in endpoint:
            key = self._openrouter_key()
            if key:
                headers["Authorization"] = f"Bearer {key}"
            headers["HTTP-Referer"] = "https://getcustodian.xyz"
            headers["X-Title"] = "Custodian"
        return headers

    @staticmethod
    def _strip_thinking(text: str) -> str:
        """Remove <think>...</think> and <thinking>...</thinking> reasoning tokens."""
        import re
        text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
        text = re.sub(r'<thinking>.*?</thinking>', '', text, flags=re.DOTALL)
        return text.strip()

    # 2200 (was 1200, live bug 2026-07-05): this reasoning model spends real
    # token budget on chain-of-thought before ever emitting output. Callers
    # that need a full structured JSON envelope (multiple claims, policy
    # citations) were routinely running out of budget mid-reasoning, either
    # truncating the JSON mid-object ("Expecting property name...") or never
    # reaching it at all ("no JSON object found") -- both were silently
    # falling back to a generic placeholder that looked like every triage
    # submission "just escalating" rather than a token-budget failure.
    def complete(self, system: str, user: str, max_tokens: int = 2200) -> str:
        last_error: Exception = RuntimeError("no endpoints configured")
        for endpoint in self.endpoints:
            headers = self._headers_for(endpoint)
            # Skip cloud endpoints that have no key configured
            if NVIDIA_HOSTED in endpoint and "Authorization" not in headers:
                continue
            if OPENROUTER_HOSTED in endpoint and "Authorization" not in headers:
                continue
            payload_body = {
                "model": self._model_for(endpoint),
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "max_tokens": max_tokens,
                "temperature": 0.2,
            }
            # chat_template_kwargs.thinking=False is NIM-specific; OpenRouter
            # returns 422 for unknown fields (confirmed 2026-07-02). Only send
            # it when the endpoint is actually NVIDIA NIM.
            if NVIDIA_HOSTED in endpoint:
                payload_body["chat_template_kwargs"] = {"thinking": False}

            payload = json.dumps(payload_body).encode()
            try:
                req = urllib.request.Request(endpoint, data=payload, headers=headers)
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    result = json.loads(resp.read())
                # A 200 response under concurrent load can still be a
                # provider-side error body (rate limit, capacity, etc.)
                # rather than a completion — no "choices" key. Treat that
                # the same as a network failure: move on to the next
                # endpoint rather than raising an uncaught KeyError, which
                # was surfacing as an unhandled 500 (non-JSON body) that the
                # Cloudflare Worker in front of this then misread as an
                # infra outage instead of an application-level hiccup.
                choices = result.get("choices")
                if not choices:
                    last_error = RuntimeError(
                        f"{endpoint} returned no choices: {result.get('error', result)}"
                    )
                    continue
                content = choices[0]["message"]["content"]
                self.name = f"nemoclaw-router → {endpoint}"
                self.live = True
                return self._strip_thinking(content)
            except (urllib.error.URLError, OSError, TimeoutError,
                    KeyError, IndexError, json.JSONDecodeError) as e:
                last_error = e
                continue

        # All cloud endpoints exhausted — try local Ollama if configured.
        ollama_host = os.environ.get("OLLAMA_HOST")
        if ollama_host:
            try:
                ollama_payload = {
                    "model": os.environ.get("OLLAMA_MODEL", "qwen3:8b"),
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "stream": False,
                    "options": {
                        "temperature": 0.2,
                        "num_predict": max_tokens,
                    },
                }
                ollama_headers = {"Content-Type": "application/json"}
                req = urllib.request.Request(
                    f"{ollama_host}/api/chat",
                    data=json.dumps(ollama_payload).encode(),
                    headers=ollama_headers,
                )
                with urllib.request.urlopen(req, timeout=30) as resp:
                    ollama_result = json.loads(resp.read())
                # Ollama returns {"message":{"content":"..."}}, not {"choices":...}
                content = ollama_result.get("message", {}).get("content", "")
                if content:
                    self.name = f"nemoclaw-router → {ollama_host} (ollama)"
                    self.live = True
                    return self._strip_thinking(content)
            except Exception:
                pass  # Ollama not available — that's OK, this is best-effort

        raise RuntimeError(
            f"NemoClawRouter: all {len(self.endpoints)} cloud endpoints failed, "
            f"Ollama also unavailable. Last error: {last_error}"
        )
