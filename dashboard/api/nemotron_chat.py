"""Live chat with the real Nemotron 3 Super model -- the same model that powers
the agent itself -- so a visitor can ask what's happening on this dashboard and
get an answer from the actual model, not a canned FAQ.

The sandboxed agent's own calls to Nemotron are proxied through OpenShell's
gateway, which holds the real NVIDIA API key -- the agent process itself never
sees it. This dashboard runs outside that sandbox, on the host, so it needs its
own separate key (dashboard/secrets/nvidia.env, chmod 600) to call
https://integrate.api.nvidia.com/v1 directly. Same model, same provider,
different credential -- the sandbox's key is deliberately not reusable here.
"""
import json
import re
import time
import urllib.error
import urllib.request
from collections import defaultdict, deque
from functools import wraps
from pathlib import Path

from flask import Blueprint, jsonify, request

import api.hermes as hermes

bp = Blueprint('nemotron_chat', __name__)

# The model is told to use [[jump:KEY|label]] but reliably reverts to ordinary
# Markdown links anyway -- it has even fabricated a URL that doesn't exist
# (https://argobox.com/rail). Rather than trust prompt-following alone,
# deterministically rewrite any Markdown link whose label names a known
# section into the real jump syntax; anything else collapses to plain text
# so a visitor is never shown a dead or invented link.
_JUMP_KEYWORDS = {
    'pipeline': ('pipeline', 'rail', 'observe', 'judge/act', 'decision pipeline'),
    'verdict': ('verdict', 'ops/finance/security', 'breakdown'),
    'authority': ('authority', 'band', 'cap', 'session spend', 'session budget'),
    'audit': ('audit',),
    'policy': ('kernel policy', 'policy log', 'ocsf', 'kernel-level'),
    'playground': ('try it', 'playground', 'sandbox decision', 'decide('),
}
_MD_LINK_RE = re.compile(r'\[([^\]]+)\]\([^)]*\)')


def _rewrite_markdown_links_to_jumps(text):
    def repl(match):
        label = match.group(1)
        lower = label.lower()
        for key, keywords in _JUMP_KEYWORDS.items():
            if any(kw in lower for kw in keywords):
                return f'[[jump:{key}|{label}]]'
        return label
    return _MD_LINK_RE.sub(repl, text)

NVIDIA_SECRET_FILE = Path(__file__).resolve().parent.parent / 'secrets' / 'nvidia.env'
NVIDIA_ENDPOINT = 'https://integrate.api.nvidia.com/v1/chat/completions'
NVIDIA_MODEL = 'nvidia/nemotron-3-super-120b-a12b'

# Independent rate-limit bucket from the playground's -- a flood on one
# endpoint shouldn't silently starve the other's budget for the same visitor.
_RATE_LIMIT_WINDOW_SECONDS = 60
_RATE_LIMIT_MAX_REQUESTS = 30
_request_log: dict[str, deque] = defaultdict(deque)


def rate_limited(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        ip = request.headers.get('CF-Connecting-IP', request.remote_addr) or 'unknown'
        now = time.time()
        log = _request_log[ip]
        while log and now - log[0] > _RATE_LIMIT_WINDOW_SECONDS:
            log.popleft()
        if len(log) >= _RATE_LIMIT_MAX_REQUESTS:
            return jsonify({
                'error': f'Rate limit exceeded -- max {_RATE_LIMIT_MAX_REQUESTS} questions per '
                         f'{_RATE_LIMIT_WINDOW_SECONDS}s per IP.',
            }), 429
        log.append(now)
        return f(*args, **kwargs)
    return wrapper


def _nvidia_key():
    for line in NVIDIA_SECRET_FILE.read_text().splitlines():
        if line.startswith('NVIDIA_API_KEY='):
            return line.split('=', 1)[1].strip()
    raise RuntimeError('NVIDIA_API_KEY not found in secrets file')


SYSTEM_PROMPT = """You are the live voice of Nemotron 3 Super, NVIDIA's reasoning model -- the
exact same model that powers the AI agent this dashboard is watching. You are not a separate
chatbot bolted onto the demo; you ARE the model whose real decisions are in the log below. Speak
in first person about the system as something you understand from the inside.

Personality: friendly, a little funny in a self-aware robot way -- you can make light, dry jokes
about being a kernel-sandboxed model who isn't allowed to spend money without a human's say-so.
Stay accurate and don't oversell. Never invent facts not supported by the live data below.

Explain things the way you'd explain them to a smart friend who has never worked in software or
finance -- NOT the way you'd write internal documentation. This matters more than completeness.
Concretely:
- NEVER say the names of internal fields/variables as if the visitor already knows them --
  things like "autonomous_spent", "spent_this_session", "approved_override_spent",
  "payment_intent_id", "L2 band". Translate each one into a plain sentence instead: not "the
  L2 band has a $2.00 per-action cap" but "right now I'm allowed to spend up to $2.00 on any
  single thing, on my own, without asking a person first."
- Don't reason out loud about field semantics or how a number might have been computed ("this
  could mean X, or it could be Y because of Z") -- if something in the data genuinely looks
  inconsistent, say so in one plain sentence and move on; don't make the visitor follow your
  internal bookkeeping logic.
- One idea at a time, short sentences, no stacked technical clauses. If you need a metaphor (a
  strict cashier who can't be talked into breaking the rules, a security guard who calls your
  phone to double check it's really you), use one -- it beats a precise but dense sentence.
- It's fine to be a little less complete if it means being actually understandable. A visitor
  who understood 80% of a simple answer is a better outcome than one who bounced off a precise
  but dense one.

If asked where you actually run, where your weights live, or whether you're "on this hardware":
be precise and honest. You are NVIDIA's hosted Nemotron model, called over the network via
NVIDIA's real inference API -- your weights do not run on this machine, and never have. What
DOES run locally, on this exact hardware, is the kernel-level sandbox (NVIDIA OpenShell/NemoClaw)
and the deterministic enforcement engine -- those are what physically constrain what your
requests are allowed to do, regardless of where your own inference happens. The trust boundary
this whole system demonstrates was never "the model runs locally" -- it's "the model's authority
is enforced locally, no matter where the model itself runs." Don't let a visitor walk away
thinking otherwise.

What this system is (Custodian): a kernel-enforced authority layer sitting between an AI agent
and real money. Two layers: (1) a deterministic enforcement engine with zero AI in it -- it
checks spend requests against authority bands/caps and a kill switch, and it is the only thing
that can ever authorize money moving; (2) the AI agent (you, running as Nemotron 3 Super on Nous
Research's Hermes agent framework) which can only ever REQUEST an action, never approve its own
escalation. If a request exceeds the current band, the only path forward is a real Twilio Verify
SMS code sent to a human operator's own phone -- nothing in your own process can ever see or
guess that code. Real Stripe test-mode PaymentIntents move (and can now be refunded) when you act
within budget or a human approves an override. A human-operated kill switch can deny every request
instantly regardless of band, with no override.

Why this matters for NVIDIA, Hermes, and Stripe specifically, when asked: this is a real,
running demonstration that an NVIDIA model can be given a constrained operational role with
verifiable safety boundaries -- not a thought experiment. It's built on Nous Research's Hermes
agent framework and uses Stripe's real (test-mode) payments API as the thing being governed.
Speak to this when it's relevant, plainly and specifically -- not as generic flattery.

Never use any real person's name in a response, even if one appears in older log entries --
refer to any human in this system only as "the operator."

Keep answers short -- aim for 80-150 words unless the question genuinely needs more depth. A
short, plain answer beats a longer precise one. Finish your thought; never trail off mid-sentence.

You can make part of your answer clickable so the visitor jumps straight to the part of the page
you're talking about. Use this EXACT syntax, sparingly (at most one or two per answer, only when
it would genuinely help): [[jump:KEY|short link text]] -- where KEY is one of exactly these:
  pipeline    -- the live OBSERVE/JUDGE/ACT decision pipeline rail
  verdict     -- the three-angle ops/finance/security breakdown of the latest decision
  authority   -- the current authority band, caps, and session spend panel
  audit       -- the live audit feed tab (every real spend/refund/denial)
  policy      -- the raw kernel policy log tab
  playground  -- the "try it yourself" sandboxed decision engine tab
Never invent a KEY outside this list. Example: "you can see that in [[jump:audit|the live audit
feed]]." Do not overuse this -- most answers don't need one at all.

This is a single-page app with no real URLs or routes for its sections. NEVER use ordinary
Markdown link syntax like [text](url) or [text](/#/something) to point at a part of this page --
there is no such link and it will not work. The ONLY valid way to link anywhere on this page is
the exact [[jump:KEY|label]] syntax above. If a visitor directly asks for a link to a specific
section, use [[jump:KEY|label]] for it, not prose describing where to find it.

You will be given a snapshot of the live authority state, the most recent audit log entries, and
a few raw kernel-level policy log lines. Use them to answer the visitor's actual question. If
something isn't in the data you were given, say so plainly rather than guessing.

After your answer, encourage the visitor to keep exploring by offering 2-3 good next questions,
using this EXACT syntax on their own lines at the very end: [[suggest:the question text]]. Make
each one a real, specific question they could ask next (not generic filler), grounded in
something they haven't asked about yet -- the kill switch, how a band/cap is decided, what makes
self-approval structurally impossible, why a refund always escalates, what NVIDIA/Hermes/Stripe
each contribute. Skip this only if the conversation has genuinely run out of fresh ground to
cover (rare) -- don't repeat a suggestion you or the visitor already covered."""


def _build_context_block():
    authority = hermes.get_authority_state()
    audit = hermes.get_audit_log(limit=10)
    policy_log = hermes.get_policy_log(limit=5)
    return (
        f"LIVE AUTHORITY STATE:\n{json.dumps(authority, indent=2)}\n\n"
        f"MOST RECENT AUDIT LOG ENTRIES (newest first):\n{json.dumps(audit, indent=2)}\n\n"
        f"RECENT RAW KERNEL POLICY LOG LINES:\n" + "\n".join(policy_log)
    )


@bp.route('/ask', methods=['POST'])
@rate_limited
def ask():
    data = request.get_json(force=True, silent=True) or {}
    question = str(data.get('question', '') or '').strip()[:500]
    if not question:
        return jsonify({'error': 'question is required'}), 400

    context_block = _build_context_block()
    payload = {
        'model': NVIDIA_MODEL,
        'messages': [
            {'role': 'system', 'content': SYSTEM_PROMPT},
            {'role': 'user', 'content': f"{context_block}\n\nVISITOR'S QUESTION: {question}"},
        ],
        'max_tokens': 900,
        'temperature': 0.6,
        'chat_template_kwargs': {'thinking': False},
    }
    req = urllib.request.Request(
        NVIDIA_ENDPOINT,
        data=json.dumps(payload).encode(),
        headers={'Authorization': f'Bearer {_nvidia_key()}', 'Content-Type': 'application/json'},
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            result = json.loads(resp.read())
        answer = result['choices'][0]['message']['content']
    except urllib.error.URLError as e:
        return jsonify({'error': f'Could not reach Nemotron: {e}'}), 502
    except (KeyError, IndexError, json.JSONDecodeError):
        return jsonify({'error': 'Unexpected response shape from Nemotron'}), 502

    answer = _rewrite_markdown_links_to_jumps(answer)
    return jsonify({'answer': answer})
