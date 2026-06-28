# NemoClaw

> Inference routing layer for Custodian. Not a separate product — a drop-in
> replacement for `NvidiaNemotronClient`.

## What it is

NemoClaw is the router in `custodian/inference/router.py`. It sends every
LLM call to a chain of OpenAI-compatible `/v1/chat/completions` endpoints
in order, falling back to the next hop on a 2-second timeout or
connection error. The first endpoint to respond wins; `name` and `live`
reflect which one served the call. It implements the same `LLMClient`
protocol as `NvidiaNemotronClient` (`name: str`, `live: bool`,
`complete(system, user) -> str`), so any caller accepting the protocol can
swap one for the other with no other changes.

## Endpoint priority chain

Default order in `NemoClawRouter.endpoints`:

1. `http://dgx-spark-01:8000/v1/chat/completions` — own DGX Spark (NIM)
2. `http://10.0.0.199:8000/v1/chat/completions` — argobox-lite local NIM
3. `https://integrate.api.nvidia.com/v1/chat/completions` — NVIDIA hosted (billed)

Own hardware first (free, no egress), local NIM as fallback, billed
hosted endpoint last. Local endpoints need no API key; the hosted
endpoint reads `NVIDIA_API_KEY=` from the configured key file.

## Configuration

`NEMOCLAW_ENDPOINTS` env var (comma-separated URLs) or the constructor
argument `NemoClawRouter(endpoints=[...], model=..., timeout=2,
nvidia_api_key_file=Path("..."))`. Defaults: DGX Spark → argobox-lite →
NVIDIA hosted, model `nvidia/nemotron-3-super-120b-a12b`, 2-second per-hop
timeout.

## DGX Spark integration (arriving Monday)

The two DGX Spark units arrive Monday. Each runs an NVIDIA NIM container
exposing the same `/v1/chat/completions` shape as the hosted API. Point
NemoClaw at a local NIM instead of the hosted service by replacing the
third hop in the env var — no code change:

```bash
export NEMOCLAW_ENDPOINTS="http://dgx-spark-01:8000/v1/chat/completions,http://10.0.0.199:8000/v1/chat/completions,http://dgx-spark-02:8000/v1/chat/completions"
```

`NVIDIA_API_KEY` is no longer required when both local endpoints respond;
the router only attaches a `Bearer` header when the URL contains
`integrate.api.nvidia.com`.

## Custodian governance of inference spend

NemoClaw is the transport; Custodian governs the spend around it. The
kernel applies the same band/cap/audit logic to inference calls that it
applies to Stripe payments:

- `skills/nvidia/openai-complete` — `custodian-band: L1` ($0.50 per-action cap).
- `skills/modal/modal-invoke` — `custodian-band: L2` ($2.00 per-action, $10.00 session, Twilio Verify on escalation). Same band that authorizes the demo's PaymentIntents.

Every model call goes through the engine: authority band lookup, per-action
and per-session spend check, OCSF audit log entry. If a call's declared
`cost_usd` exceeds the band cap, the kernel escalates to a human the same
way it would for a refund — there is no second path.

## Drop-in code example

```python
from pathlib import Path
from custodian.inference.router import NemoClawRouter

client = NemoClawRouter(
    nvidia_api_key_file=Path("secrets/nvidia.env"),  # only used for the hosted hop
    timeout=2,
)
text = client.complete(system="...", user="...")
print(client.name)  # e.g. "nemoclaw-router → http://dgx-spark-01:8000/..."
```

`NemoClawRouter` satisfies `LLMClient`; the pack pipeline (`parse_envelope`, verifier, kernel) works unchanged against it.