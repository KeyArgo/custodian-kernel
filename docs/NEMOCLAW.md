# NemoClaw

> Inference routing layer for Custodian. Not a separate product — a drop-in
> replacement for `NvidiaNemotronClient`.
>
> Note: "NemoClaw" is also the name of a real, separate NVIDIA sandboxing
> product (github.com/NVIDIA/NemoClaw) installed independently on
> argobox-lite for agent process isolation. `NemoClawRouter` below is
> unrelated to that product — it's our own inference-routing class that
> happens to share the name.

## What it is

NemoClaw is the router in `custodian/inference/router.py`. It sends every
LLM call to a chain of OpenAI-compatible `/v1/chat/completions` endpoints
in order, falling back to the next hop on a timeout or connection error.
The first endpoint to respond wins; `name` and `live` reflect which one
served the call. It implements the same `LLMClient` protocol as
`NvidiaNemotronClient` (`name: str`, `live: bool`,
`complete(system, user) -> str`), so any caller accepting the protocol can
swap one for the other with no other changes.

## Endpoint priority chain

Default order in `NemoClawRouter.endpoints` (`DEFAULT_ENDPOINTS`):

1. `https://openrouter.ai/api/v1/chat/completions` — primary. Faster
   failover between its own upstream providers and more reliable uptime
   than NIM direct.
2. `https://integrate.api.nvidia.com/v1/chat/completions` — secondary,
   used if OpenRouter is down. Requires `NVIDIA_API_KEY`.

**DGX Spark does not serve inference.** It runs the enforcement kernel
only (`:8095/decide`) — a separate, deterministic process from anything in
this router. Inference always goes to a cloud endpoint, never local. Any
earlier documentation describing local `dgx-spark-01`/`dgx-spark-02` NIM
containers in this chain was aspirational and was never implemented —
that hardware runs enforcement, not inference.

Endpoints with no configured key are skipped automatically (see
`complete()`), so the router degrades gracefully rather than raising if,
say, only the OpenRouter key is set.

## Configuration

`NemoClawRouter(endpoints=[...], model=..., timeout=2,
nvidia_api_key_file=Path("..."), openrouter_key_file=Path("..."))`. Keys
are read from `NVIDIA_API_KEY`/`OPENROUTER_API_KEY` env vars first, falling
back to the given key files. Default per-hop timeout is 2 seconds; default
model is `nvidia/llama-3.3-nemotron-super-49b-v1`, with a separate
`OPENROUTER_FALLBACK_MODEL` (env-overridable, default
`nvidia/nemotron-3-super-120b-a12b:free`) used specifically for the
OpenRouter hop.

Worst-case latency the router can incur (both hops timing out slowly
rather than failing fast) informs the Cloudflare Worker's `TIMEOUT_SLOW_MS`
for `/api/v1/nemotron/*` and `/api/v1/triage/custom` — see
`pages-frontend/_worker.js`.

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
    nvidia_api_key_file=Path("secrets/nvidia.env"),
    openrouter_key_file=Path("secrets/openrouter.env"),
    timeout=2,
)
text = client.complete(system="...", user="...")
print(client.name)  # e.g. "nemoclaw-router → https://openrouter.ai/api/v1/chat/completions"
```

`NemoClawRouter` satisfies `LLMClient`; the pack pipeline (`parse_envelope`,
verifier, kernel) works unchanged against it.
