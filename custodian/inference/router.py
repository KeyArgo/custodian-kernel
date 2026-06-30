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

# Model to use on OpenRouter when falling back — env-overridable.
OPENROUTER_FALLBACK_MODEL = os.environ.get(
    "OPENROUTER_FALLBACK_MODEL", "nvidia/llama-3.3-nemotron-super-49b-v1"
)


@dataclass
class NemoClawRouter:
    """Tries endpoints in order, falls back on timeout or connection error.
    Endpoint priority: DGX Spark (local) → NVIDIA NIM (cloud) → OpenRouter (fallback).
    name and live reflect the endpoint that actually responded."""
    endpoints: list[str] = field(default_factory=lambda: list(DEFAULT_ENDPOINTS))
    model: str = "nvidia/nemotron-3-super-120b-a12b"
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

    def complete(self, system: str, user: str) -> str:
        last_error: Exception = RuntimeError("no endpoints configured")
        for endpoint in self.endpoints:
            headers = self._headers_for(endpoint)
            # Skip cloud endpoints that have no key configured
            if NVIDIA_HOSTED in endpoint and "Authorization" not in headers:
                continue
            if OPENROUTER_HOSTED in endpoint and "Authorization" not in headers:
                continue
            payload = json.dumps({
                "model": self._model_for(endpoint),
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "max_tokens": 1200,
                "temperature": 0.2,
                **({"chat_template_kwargs": {"thinking": False}}
                   if NVIDIA_HOSTED in endpoint else {}),
            }).encode()
            try:
                req = urllib.request.Request(endpoint, data=payload, headers=headers)
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    result = json.loads(resp.read())
                self.name = f"nemoclaw-router → {endpoint}"
                self.live = True
                return result["choices"][0]["message"]["content"]
            except (urllib.error.URLError, OSError, TimeoutError) as e:
                last_error = e
                continue

        raise RuntimeError(
            f"NemoClawRouter: all {len(self.endpoints)} endpoints failed. "
            f"Last error: {last_error}"
        )
