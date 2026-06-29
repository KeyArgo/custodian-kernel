# NemoClaw

_Last updated: 2026-06-29_

> Inference routing layer for Custodian. Not a separate product — a drop-in
> replacement for `NvidiaNemotronClient`.

## What it is

NemoClaw is the router in `custodian/inference/router.py`. It sends every
LLM call to a chain of OpenAI-compatible `/v1/chat/completions` endpoints
in order, falling back to the next hop on timeout or connection error. The
first endpoint to respond wins; `name` and `live` reflect which one served
the call. It implements the same `LLMClient` protocol as `NvidiaNemotronClient`
(`name: str`, `live: bool`, `complete(system, user) -> str`), so any caller
accepting the protocol can swap one for the other with no other changes.

## Endpoint priority chain

Default order in `NemoClawRouter.DEFAULT_ENDPOINTS` (defined in `router.py`):

1. `https://integrate.api.nvidia.com/v1/chat/completions` — NVIDIA NIM hosted API (primary)
2. `https://openrouter.ai/api/v1/chat/completions` — OpenRouter (fallback)

**Important:** DGX Spark handles kernel enforcement only (`:8095/decide`). It
does not run inference. All Nemotron inference is cloud-side — NIM first,
OpenRouter as fallback.

Cloud endpoints are skipped silently if their key is not configured. The
router only attaches a `Bearer` header when it has a key; otherwise it skips
that hop and moves to the next.

## Configuration

Pass key files to the constructor:

```python
NemoClawRouter(
    nvidia_api_key_file=Path("secrets/nvidia.env"),      # NVIDIA_API_KEY=...
    openrouter_key_file=Path("secrets/openrouter.env"),  # OPENROUTER_API_KEY=...
    timeout=25,
)
```

Or via environment variables: `NVIDIA_API_KEY` and `OPENROUTER_API_KEY`.

The OpenRouter fallback model defaults to `nvidia/llama-3.3-nemotron-super-49b-v1`
and can be overridden with `OPENROUTER_FALLBACK_MODEL=<model-id>`.

The default model for NIM is `nvidia/nemotron-3-super-120b-a12b` (120B parameters,
12B active via Mixture of Experts).

## Drop-in code example

```python
from pathlib import Path
from custodian.inference.router import NemoClawRouter

client = NemoClawRouter(
    nvidia_api_key_file=Path("secrets/nvidia.env"),
    openrouter_key_file=Path("secrets/openrouter.env"),
    timeout=25,
)
text = client.complete(system="...", user="...")
print(client.name)  # e.g. "nemoclaw-router → https://integrate.api.nvidia.com/..."
```

`NemoClawRouter` satisfies `LLMClient`; the pack pipeline (`parse_envelope`,
verifier, kernel) works unchanged against it.

## Custodian governance of inference spend

NemoClaw is the transport; Custodian governs the spend around it. The kernel
applies the same band/cap/audit logic to inference calls that it applies to
Stripe payments:

- `skills/nvidia/openai-complete` — `custodian-band: L1` (trivial per-action cap).
- `skills/modal/modal-invoke` — `custodian-band: L2` (Twilio Verify on escalation).

Every model call goes through the engine: authority band lookup, per-action and
per-session spend check, OCSF audit log entry. If a call's declared `cost_usd`
exceeds the band cap, the kernel escalates to a human exactly as it would for
a payment — there is no second path.
