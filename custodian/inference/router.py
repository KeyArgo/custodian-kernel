"""NemoClaw inference router — tries endpoints in priority order with fallback.

Implements the same LLMClient protocol as NvidiaNemotronClient so it is a
drop-in replacement. Endpoint order: DGX Spark → local NIM → NVIDIA hosted API.
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
    # 1. DGX Spark — local inference, air-gapped, primary
    "http://192.168.50.56:11434/v1/chat/completions",
    # 2. NVIDIA hosted API — always available, requires key
    "https://integrate.api.nvidia.com/v1/chat/completions",
]
NVIDIA_HOSTED = "integrate.api.nvidia.com"


@dataclass
class NemoClawRouter:
    """Tries endpoints in order, falls back on timeout or connection error.
    The NVIDIA hosted endpoint requires an API key; local endpoints do not.
    name and live reflect the endpoint that actually responded."""
    endpoints: list[str] = field(default_factory=lambda: list(DEFAULT_ENDPOINTS))
    model: str = "nvidia/nemotron-3-super-120b-a12b"
    timeout: int = 2        # seconds per endpoint attempt before fallback
    nvidia_api_key_file: Optional[Path] = None
    name: str = "nemoclaw-router (not yet called)"
    live: bool = False

    def _key(self) -> Optional[str]:
        if env_key := os.environ.get("NVIDIA_API_KEY"):
            return env_key
        if self.nvidia_api_key_file and self.nvidia_api_key_file.exists():
            for line in self.nvidia_api_key_file.read_text().splitlines():
                if line.startswith("NVIDIA_API_KEY="):
                    return line.split("=", 1)[1].strip()
        return None

    def _model_for(self, endpoint: str) -> str:
        """Local Ollama endpoints use a different model identifier than the cloud API."""
        if "11434" in endpoint:
            # Ollama model name — must match what's pulled on that host
            return os.environ.get("LOCAL_MODEL", "llama3.3:latest")
        return self.model

    def complete(self, system: str, user: str) -> str:
        last_error: Exception = RuntimeError("no endpoints configured")
        for endpoint in self.endpoints:
            headers = {"Content-Type": "application/json"}
            if NVIDIA_HOSTED in endpoint:
                key = self._key()
                if key:
                    headers["Authorization"] = f"Bearer {key}"
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
