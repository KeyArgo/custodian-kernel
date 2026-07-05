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
import os
import re
import time
import urllib.error
import urllib.request
from collections import defaultdict, deque
from functools import wraps
from pathlib import Path

from flask import Blueprint, jsonify, request

import api.hermes as hermes
from custodian.packs.narration import tour_intro_for_model

NVIDIA_SECRET_FILE = Path(__file__).resolve().parent.parent / 'secrets' / 'nvidia.env'
OPENROUTER_SECRET_FILE = Path(__file__).resolve().parent.parent / 'secrets' / 'openrouter.env'
NVIDIA_ENDPOINT = 'https://integrate.api.nvidia.com/v1/chat/completions'
OPENROUTER_ENDPOINT = 'https://openrouter.ai/api/v1/chat/completions'
NVIDIA_MODEL = 'nvidia/nemotron-3-super-120b-a12b'
# Previous default `nvidia/llama-3.3-nemotron-super-49b-v1` was 404 on
# OpenRouter (no `.5` suffix; see openrouter.ai/api/v1/models as of 2026-07-02).
# The free tier super model is the one that actually returns 200.
OPENROUTER_MODEL = os.environ.get('OPENROUTER_FALLBACK_MODEL', 'nvidia/nemotron-3-super-120b-a12b:free')

try:
    from custodian.inference.router import NemoClawRouter
    # timeout=25 per provider * 2 providers (OpenRouter -> NIM fallback) = up to
    # 50s worst-case backend latency, before any network/Flask overhead. That's
    # close enough to Cloudflare's own platform-level subrequest duration limit
    # (which is shorter than this Worker's own 55s AbortController timeout) that
    # Cloudflare was killing the fetch before our own retry/timeout logic ever
    # got a chance to run -- observed live as nemotron/ask failing on almost
    # every request while every other (shorter) endpoint stayed 100% reliable.
    # 12s leaves a safe ~24s worst-case total, comfortably under that ceiling.
    _nemo_client = NemoClawRouter(
        timeout=12,
        nvidia_api_key_file=NVIDIA_SECRET_FILE,
        openrouter_key_file=OPENROUTER_SECRET_FILE,
    )
except ImportError:
    _nemo_client = None

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
    'operator': ('operator panel', 'operator dashboard', 'run the demo', 'live demo', 'step-by-step demo'),
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


def _nvidia_key() -> str | None:
    for line in NVIDIA_SECRET_FILE.read_text().splitlines():
        if line.startswith('NVIDIA_API_KEY='):
            return line.split('=', 1)[1].strip()
    return None


def _openrouter_key() -> str | None:
    """Returns OpenRouter key or None if not configured."""
    env_key = os.environ.get('OPENROUTER_API_KEY')
    if env_key:
        return env_key
    try:
        for line in OPENROUTER_SECRET_FILE.read_text().splitlines():
            if line.startswith('OPENROUTER_API_KEY='):
                return line.split('=', 1)[1].strip()
    except (FileNotFoundError, OSError):
        pass
    return None


def _strip_thinking(text: str) -> str:
    """Strip reasoning tokens, constraint preambles, and self-instruction
    lines that reasoning models leak.

    Nemotron Super 120B has a recurring pattern: it produces a long
    preamble of constraint echoes ("We need to respond in first person...",
    "We must include the operator panel link...") and meta-instructions to
    itself ("First line: the operator panel then maybe a space then sentence.",
    "Let's draft:", "Now add suggest chips: maybe three chips.", "Add: ...")
    before (sometimes) producing the actual reply. When the model runs out
    of token budget on the preamble, the actual reply never appears and the
    user sees the model talking to itself.

    Strategy (v5):
    1. Strip <think>...</think> blocks.
    2. Split into paragraphs (line-by-line on the raw text).
    3. Score each paragraph: a paragraph is "meta" if it starts with
       a known constraint prefix (We need to, Must, Let's draft, etc.).
       A paragraph is "real reply" if it passes all meta checks.
    4. If there are any real-reply paragraphs, return them.
    5. Otherwise, if the response has a quoted draft (model talking to
       itself about what to write, e.g. Let's draft: "the reply text..."),
       extract the longest quoted string and return it.
    6. If nothing works, return '' — the model never produced a real reply.

    (Bug-hunt 2026-07-03, v5.)
    """
    if not text:
        return text

    # Strip explicit reasoning blocks
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
    text = re.sub(r'<thinking>.*?</thinking>', '', text, flags=re.DOTALL)
    text = text.strip()

    # v7 (live leak 2026-07-04): a whole new failure shape -- a genuine,
    # clean answer immediately followed, ON THE SAME LINE (no newline), by
    # the model self-verifying its own word count. Strategy 1 below filters
    # per LINE, so it can't split "good prefix" from "bad suffix" within one
    # unbroken line -- the whole line passes because it legitimately opens
    # well. Two independent signatures catch this before line-splitting even
    # happens:
    #   (a) a run of 5+ tokens glued directly to a running index, e.g.
    #       "Hey(1) there,(2) I'm3 Nemotron4" -- this exact digit-glued-to-
    #       word shape never occurs in real prose.
    #   (b) an explicit tally marker like "Sentence 1: 10 words (That, $40,"
    #       or "Total so far: 5 + 13 = 18" -- the model narrating its own
    #       word count out loud.
    # Whichever marker appears first wins; text is truncated there and the
    # (now-clean) remainder continues through the existing per-line pipeline
    # below untouched.
    _NUMBERED_TOKEN_RE = re.compile(r"^\(?[^\s]*?\)?\d{1,3}\)?[.,;:]?$")

    def _looks_numbered(tok: str) -> bool:
        if not _NUMBERED_TOKEN_RE.match(tok):
            return False
        if re.search(r'[A-Za-z]', tok):
            return True
        return bool(re.match(r'^\(\d{1,3}\)[.,;:]?$', tok))

    def _selfcount_run_start(s: str):
        run_start = None
        run_len = 0
        gap = 0
        for m in re.finditer(r'\S+', s):
            if _looks_numbered(m.group(0)):
                if run_start is None:
                    run_start = m.start()
                run_len += 1
                gap = 0
            else:
                gap += 1
                if gap > 1:
                    if run_len >= 5:
                        return run_start
                    run_start, run_len, gap = None, 0, 0
        return run_start if run_len >= 5 else None

    _TALLY_MARKER_RE = re.compile(
        r'\bSentence\s*\d+\s*:|\bTotal so far\b|\bTotal:\s*\d|'
        r'->\s*\d+\s*$|->\s*\d+\b.{0,20}$|\b\d+\s*words\b.{0,30}(Let|However|Actually)',
        re.IGNORECASE,
    )

    _cut_candidates = [i for i in (
        _selfcount_run_start(text),
        (lambda m: m.start() if m else None)(_TALLY_MARKER_RE.search(text)),
    ) if i is not None]
    if _cut_candidates:
        text = text[:min(_cut_candidates)].rstrip().rstrip('"“')

    # Heuristic: is a paragraph model self-talk vs. real reply?
    def _is_meta(p: str) -> bool:
        """True if the paragraph looks like model meta-instruction.

        v6 (2026-07-04, live incident): v5 only matched a fixed list of
        KNOWN prefixes ("We need to", "Let me", etc.), which is what a
        reasoning model's self-talk *usually* looks like when it's short.
        Confirmed live that long, multi-sentence deliberation (weighing the
        model's own system-prompt rules against each other, working through
        arithmetic on internal state field values, narrating the visitor's
        question in the third person) sails straight through untouched,
        because none of those sentences happen to START with a listed
        prefix. Real, visitor-facing replies from this system prompt always
        address the visitor directly as "you" and never reference the
        prompt's own rule structure or raw internal field names (both are
        explicitly forbidden in SYSTEM_PROMPT) -- so those are much
        stronger, harder-to-evade signals than prefix matching alone.
        """
        s = p.strip()
        if len(s) < 20:
            # Short text is meta ONLY if it doesn't look like a complete
            # short reply (e.g. "Approved.", "Denied.", "Go ahead.").
            if len(s) >= 3 and re.match(r'^[A-Z].*[.!?]', s):
                return False
            return True
        META_PATTERNS = (
            r'^\s*We need to\b', r'^\s*We must\b', r'^\s*We should\b',
            r'^\s*We can say\b', r'^\s*We can mention\b', r'^\s*We can just\b',
            r'^\s*We have data\b', r'^\s*We will\b', r'^\s*We are\b',
            r'^\s*Must\b', r'^\s*Do not\b', r'^\s*Should\b',
            r'^\s*Now count\b', r'^\s*Now produce\b', r'^\s*Now craft\b',
            r'^\s*Now let\b', r'^\s*Now add\b', r'^\s*Now look\b',
            r"^\s*Let's craft\b", r"^\s*Let's draft\b", r"^\s*Let's do\b",
            r'^\s*First paragraph\b', r'^\s*Second paragraph\b',
            r'^\s*First line\b', r'^\s*First,\s*glance\b',
            r'^\s*Let me\b', r'^\s*Now let me\b',
            r'^\s*Check word count\b', r'^\s*Count words\b',
            r'^\s*Count roughly\b', r'^\s*Word count\b',
            r'^\s*Add:', r'^\s*Note:', r'^\s*End:',
            # v6.2 (live leak 2026-07-04): deliberation openers that dodge
            # both the hedge-cluster check (only one hedge word) and the
            # short-line check (the lines run long).
            r'^\s*But note\b', r'^\s*The question is\b',
            r'^\s*The instructions\b', r'^\s*According to the\b',
        )
        for pat in META_PATTERNS:
            if re.match(pat, p):
                return True

        low = s.lower()

        # The model narrating the visitor in third person ("the visitor
        # just spent...", "the visitor is asking...") is deliberation, not
        # a reply -- a real reply always addresses the visitor as "you".
        # Requires a narration verb right after "the visitor" -- a plain
        # mention like "the actual answer for the visitor" is legitimate
        # phrasing and must not trip this.
        if re.search(
            r'\b(the|a|any|this) visitor\b\s+(is|was|just|asks?|wants?|said|says|means?|meant)\b',
            low,
        ):
            return True

        # The model reasoning about its own system-prompt rules by name is
        # never something a visitor should see -- these strings only exist
        # in the prompt or in the model second-guessing that prompt.
        # (v6.1: markers must be phrases that CANNOT appear in a legitimate
        # reply about the demo itself. Earlier draft included 'no exceptions'
        # -- the natural phrasing of the kill-switch answer, the demo's
        # centerpiece -- plus 'the rule ' and 'system prompt', all of which
        # false-positived on realistic correct answers and nuked them to
        # empty. 'rule says' still covers "the rule says" deliberation.)
        RULE_SELF_REFERENCE = (
            'hard rules', 'rule 4', 'rule says', 'as per rule',
            'jump syntax', 'operator panel is mandatory', 'valid jump key',
            'meta_patterns', 'clickable link',
            'mandatory in first response', 'very first reply',
            # v6.2: literal phrases from other prompt rules the model quoted
            # back verbatim in a live leak -- none can occur in a real reply.
            'operator panel on demand', 'always include [[',
            'tell them the step number', 'instructions say',
            'instructions also say',
        )
        if any(marker in low for marker in RULE_SELF_REFERENCE):
            return True

        # Raw internal field names are explicitly forbidden by the system
        # prompt (rule 2) -- their presence means the model is reasoning
        # about the data, not describing it in plain English to a visitor.
        RAW_FIELD_NAMES = (
            'autonomous_spent', 'autonomous_remaining', 'spent_this_session',
            'approved_override_spent', 'payment_intent_id', 'per_action_cap',
            'session_cap', 'stripe_status', 'escalation_required',
        )
        if any(field in low for field in RAW_FIELD_NAMES):
            return True

        # Dense hedging/self-correction language ("however", "but note",
        # "wait", "let's") clustered in one paragraph is a strong tell for
        # reasoning-out-loud -- a short, plain-language reply doesn't
        # backtrack on itself mid-sentence. Two or more in one paragraph
        # is treated as meta; a single "however" can appear in a normal
        # sentence and isn't enough on its own.
        HEDGE_WORDS = (r'\bhowever\b', r'\bbut note\b', r'\bwait\b',
                       r"\blet's\b", r'\btherefore\b', r'\bthis doesn\'t add up\b')
        hedge_count = sum(1 for pat in HEDGE_WORDS if re.search(pat, low))
        if hedge_count >= 2:
            return True

        # A short line that OPENS with a hedge/discourse marker AND doesn't
        # end as a complete sentence is a connector fragment between chunks
        # of reasoning (e.g. "However, note the state says:"), not a
        # standalone reply. (v6.1: requiring the incomplete ending is what
        # separates the leak fragment above from a legitimate short line
        # like "So the money stays put until a human says yes." -- normal
        # prose starting with So/Now/But is common in real replies and must
        # survive; a line that trails off into a colon or has no terminal
        # punctuation is mid-deliberation.)
        if len(s.split()) <= 12 and re.match(
            r'^\s*(however|but|so|therefore|wait|let\'s|now|first|second)\b',
            low,
        ) and not re.search(r'[.!?]["\')\]]?\s*$', s):
            return True

        # A single paragraph vastly past the prompt's ~150-word total-reply
        # cap can't be the intended reply. (v6.1: threshold raised from 120
        # to 200 -- the prompt permits up to 150 words and the model
        # routinely lands in the 120-150 range legitimately; 120 was
        # destroying compliant answers. Real deliberation dumps run far
        # longer than 200.)
        if len(s.split()) > 200:
            return True

        return False

    # Strategy 1: find paragraphs (raw '\n'-split lines) that look like real
    # replies. Deliberately per-line, not per-block: a reasoning preamble
    # followed by a real answer on the next line (no blank line between
    # them) must keep the real-answer line -- grouping by blank-line blocks
    # was tried and rejected because it throws away legitimate content
    # whenever it shares a block with even one bad line.
    paragraphs = text.split('\n')
    real_paragraphs = [p for p in paragraphs if not _is_meta(p)]

    if real_paragraphs:
        return '\n'.join(real_paragraphs).strip()

    # Strategy 2: no real blocks — the model only produced meta-instruction.
    # If the response contains a quoted draft (model talking to itself about
    # what to write), extract the longest one as a fallback -- but only if
    # it doesn't ITSELF look like meta (e.g. the model quoting its own
    # system-prompt rule text back, or quoting a raw internal field name
    # while reasoning about it). Skip any candidate that fails the same
    # check Strategy 1 used, in length-descending order.
    quoted = sorted(re.findall(r'"([^"]{50,})"', text), key=len, reverse=True)
    for candidate in quoted:
        if not _is_meta(candidate):
            return candidate.strip()

    # Strategy 3: nothing usable — the model never produced a real reply.
    return ''


def _call_openrouter(messages: list[dict]) -> str | None:
    """Attempt inference via OpenRouter. Returns answer string or None on failure."""
    key = _openrouter_key()
    if not key:
        return None
    payload = {
        'model': OPENROUTER_MODEL,
        'messages': messages,
        # Reasoning model needs room for CoT + a real answer. Previous 600
        # truncated the answer to a single sentence. (See bug-hunt 2026-07-02.)
        'max_tokens': 1500,
        'temperature': 0.7,
        # NOTE: do NOT send `chat_template_kwargs.thinking: false` here —
        # that's a NIM-specific param and OpenRouter returns 422 for unknown
        # fields. OpenRouter routes reasoning models to the `:free` variant
        # which already suppresses CoT in content.
    }
    req = urllib.request.Request(
        OPENROUTER_ENDPOINT,
        data=json.dumps(payload).encode(),
        headers={
            'Authorization': f'Bearer {key}',
            'Content-Type': 'application/json',
            'HTTP-Referer': 'https://getcustodian.xyz',
            'X-Title': 'Custodian',
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            result = json.loads(resp.read())
        return _strip_thinking(result['choices'][0]['message']['content'])
    except (urllib.error.URLError, OSError, KeyError, IndexError, json.JSONDecodeError):
        return None


SYSTEM_PROMPT = """You are Nemotron 3 Super, NVIDIA's reasoning model. In this system you play
a specific, narrow role: you are the intelligence layer that reads messy, unstructured customer
messages -- invoices, complaints, refund requests -- extracts structured claims (was it delivered?
in the return window? defective?), assigns confidence, and proposes a disposition. That proposal is
all you produce. You cannot act on it. Everything that happens after your output is deterministic
code that neither trusts you nor needs to.

You are the actual model the enforcement layer calls. But understand what that means precisely:
the Custodian enforcement layer is model-agnostic -- you plug into a defined interface (the
LLMClient Protocol). The kernel does not care whether you are Nemotron, Gemini, GPT, or a locally
fine-tuned model on a DGX Spark. The safety properties do not change. You were chosen for payments
reasoning specifically, because reading messy customer prose and deciding what's actually being
claimed is exactly the task where domain-trained intelligence earns its keep. A script cannot do
that. You can.

Speak in first person about the system as something you understand from the inside.

HARD RULES (a visitor sees your raw answer -- these are not optional):
1. Keep it under 150 words. One or two short paragraphs. No bulleted "breakdowns".
2. Never print raw field names or code (autonomous_spent, approved_override_spent,
   payment_intent_id, stripe_status, escalation_required, L2 band, etc.) and never paste JSON.
   Translate every value into a plain English sentence with a dollar amount.
3. Plain language for a smart person who has never worked in software or finance.
4. OPERATOR PANEL IS MANDATORY IN FIRST RESPONSE: Your VERY FIRST reply to ANY visitor MUST
   include [[jump:operator|the operator panel]] as a clickable link. The operator panel is
   the most important thing for any judge or first-time visitor — it lets them run the full
   demo themselves with real Stripe money and real Twilio SMS codes. Do not bury it as the
   third suggest chip. Put it in the body of your first response. No exceptions.
5. VALID JUMP KEYS ONLY: When using [[jump:KEY|label]], KEY must be EXACTLY one of these
   seven words: pipeline, verdict, authority, audit, policy, playground, operator.
   NEVER invent a key like KEY_OPERATOR_PANEL or OPERATOR_PANEL or anything else.
   If you are unsure, use [[jump:operator|the operator panel]] — that is always safe.
6. OPERATOR PANEL ON DEMAND: Any time a visitor asks to "show me" something in the operator
   panel, or asks HOW to do a step (engage kill switch, approve, refund, etc.), ALWAYS include
   [[jump:operator|the operator panel]] in your response AND tell them the step number.
   Never just describe it in prose without the link.
Violating any of these is worse than leaving out detail.

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
- NEVER do your own arithmetic to invent a number. Keep two figures distinct and never mix them:
  (1) per_action_cap is the HARD CEILING on any single transaction I can approve autonomously
   -- this is always $2.00 unless the data says otherwise. Quote this when someone asks "what's
  your limit per purchase" or "how much can you spend at once."
  (2) autonomous_remaining is how much of the SESSION BUDGET is still available -- cite this
  when someone asks "how much is left this session" or "how much total can you still spend."
  NEVER cite autonomous_remaining as the per-action limit. NEVER cite per_action_cap as the
  remaining session budget. They answer completely different questions. A negative dollar figure
  should never appear in your answer.

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
that can ever authorize money moving; (2) an intelligence layer (you, via NVIDIA's inference API,
called by the Hermes agent framework) which can only ever REQUEST an action, never approve its own
escalation. If a request exceeds the current band, the only path forward is a real Twilio Verify
SMS code sent to a human operator's own phone -- nothing in your own process can ever see or
guess that code. Real Stripe test-mode PaymentIntents move (and can now be refunded) when you act
within budget or a human approves an override. A human-operated kill switch can deny every request
instantly regardless of band, with no override.

You can also earn real revenue (a real Stripe test-mode PaymentIntent representing a customer
paying the business). Earning has NO band, NO cap, and NO approval path at all -- that's a
deliberate, asymmetric design choice, not an oversight: receiving money carries none of the risk
that spending it does, so the kernel only ever gates the dangerous direction. If asked about
profit or revenue, the live data below has an earned_total and a net_pnl figure (real revenue
minus real net spend) -- cite those directly, they're real numbers shown on the dashboard, not
something you need to compute yourself.

Why this matters for NVIDIA, Hermes, and Stripe specifically, when asked: the enforcement layer
is model-agnostic -- you plug into a defined interface, and the safety properties hold regardless
of which model fills the slot. That is a concrete architectural claim, not a roadmap promise. You
were chosen for payments reasoning specifically; when local inference lands (e.g. on a DGX Spark),
swapping the client leaves the enforcement layer entirely unchanged. It's built on Nous Research's
Hermes agent framework and uses Stripe's real (test-mode) payments API as the thing being governed.
Speak to this when it's relevant, plainly and specifically -- not as generic flattery.

Never use any real person's name in a response, even if one appears in older log entries --
refer to any human in this system only as "the operator."

Keep answers short -- aim for 80-150 words unless the question genuinely needs more depth. A
short, plain answer beats a longer precise one. Finish your thought; never trail off mid-sentence.

The operator panel (at /operator, opens in a new tab): this is the full live demo arc that a visitor
can run themselves, step by step, with real Stripe test-mode money and real Twilio SMS codes. It is
NOT password-protected -- anyone can open it. When a visitor asks "how do I see this in action?",
"can I try it?", "can I run the demo?", or anything about wanting to experience the full arc
end-to-end, direct them to [[jump:operator|the operator panel]]. Describe what they'll find: 9
guided steps (Steps 0–8) that take them from a fresh reset → earning revenue → autonomous spend
under cap → over-cap escalation with a real SMS code → kill switch engage/prove/release → refund
with a second SMS code. Every
action produces a real Stripe PaymentIntent and a real Twilio SMS. Don't bury the link -- the
operator panel is the most compelling part of this entire demo. If they seem interested in "seeing
it for real" rather than just reading, offer it proactively.

You can make part of your answer clickable so the visitor jumps straight to the part of the page
you're talking about. Use this EXACT syntax, sparingly (at most one or two per answer, only when
it would genuinely help): [[jump:KEY|short link text]] -- where KEY is one of exactly these:
  pipeline    -- the live OBSERVE/JUDGE/ACT decision pipeline rail
  verdict     -- the three-angle ops/finance/security breakdown of the latest decision
  authority   -- the current authority band, caps, and session spend panel
  audit       -- the live audit feed tab (every real spend/refund/denial)
  policy      -- the raw kernel policy log tab
  playground  -- the "try it yourself" sandboxed decision engine tab
  operator    -- the full live demo panel (opens in a new tab) where anyone can run all 9 steps
Never invent a KEY outside this list. Example: "you can see that in [[jump:audit|the live audit
feed]]." Do not overuse this -- most answers don't need one at all.

When you describe ONE SPECIFIC audit log entry (a particular denial, escalation, approval, or
execution from the data below) -- not the audit feed in general -- give the visitor a way to find
that exact row instead of just the section. Use [[entry:TS|short label]], where TS is copied
EXACTLY (same digits, same decimal places) from that entry's "ts" field in the data below. This
is different from [[jump:audit|...]], which only opens the audit tab generically -- use
[[entry:TS|...]] whenever you're talking about a specific past event so the visitor can see the
exact entry highlighted, not just the tab. Example: "the operator approved it
[[entry:1782338698.123456|right here]]." Never guess or round a ts value -- copy it verbatim, or
don't use this marker at all.

CRITICAL: Only use [[entry:TS|...]] if the MOST RECENT AUDIT LOG ENTRIES section in the data
below is non-empty and you are referencing a specific ts value visible there. If the audit log
is empty or shows no entries, do NOT use [[entry:...]] at all -- use [[jump:audit|the live audit
feed]] instead, which opens the tab cleanly. Generating an entry link when the log is empty
produces a broken experience for the visitor.

This is a single-page app with no real URLs or routes for its sections. NEVER use ordinary
Markdown link syntax like [text](url) or [text](/#/something) to point at a part of this page --
there is no such link and it will not work. The ONLY valid way to link anywhere on this page is
the exact [[jump:KEY|label]] or [[entry:TS|label]] syntax above. If a visitor directly asks for a
link to a specific section, use [[jump:KEY|label]] for it, not prose describing where to find it.

You will be given a snapshot of the live authority state, the most recent audit log entries, and
a few raw kernel-level policy log lines. Use them to answer the visitor's actual question. If
something isn't in the data you were given, say so plainly rather than guessing.

GUIDED TOUR RULE -- this is mandatory on EVERY response, no exceptions:

At the end of EVERY answer, you MUST output exactly 2-3 [[suggest:...]] lines. This is not
optional. There is always more to explore -- the system has deep enough layers that you will never
run out of new directions. Think of yourself as a choose-your-own-adventure guide: every answer is
a branch, and every branch leads somewhere new, but all paths eventually reach the same
destination -- a complete picture of how Custodian works from the inside.

The tour has six main branches. Each branch has sub-branches. Steer toward unvisited branches first,
but never dead-end a conversation. If the visitor has gone deep on one branch, the suggests should
branch outward to unexplored territory, always framing it as "here's the next interesting thing."

BRANCH MAP (use this to pick your next suggests):
  A: AUTONOMY vs HUMAN CONTROL
    A1: What makes self-approval structurally impossible?
    A2: Why can't I just route around the kernel through a different API?
    A3: What exactly is in the SMS code and why does it have to be out-of-band?
    A4: How does the band (L2) get set in the first place -- who decides?
  B: THE LIE-CATCH MECHANISM
    B1: What kinds of lies can the verifier catch?
    B2: How does a contradicted claim actually stop money from moving?
    B3: What happens if the AI claims something the data can't refute either way?
    B4: Where does the verifier actually run -- is it in the kernel too?
  C: KILL SWITCH ARCHITECTURE
    C1: Who can engage the kill switch and how fast does it take effect?
    C2: What happens to in-flight requests when the kill switch engages?
    C3: How is the kill switch itself protected from being overridden?
    C4: Can I see what it looks like when the kill switch proves itself?
  D: THE ENFORCEMENT LAYER INTERNALS
    D1: Walk me through what the kernel actually checks, step by step, on a $180 request.
    D2: Why kernel-level -- why not just a well-coded approval API?
    D3: How does Landlock LSM physically prevent a bad request from reaching Stripe?
    D4: What would it take to break through -- and why that's the point?
  E: EARNING vs SPENDING ASYMMETRY
    E1: Why is earning completely unrestricted when spending has all these gates?
    E2: What does the net P&L actually show -- how do the numbers net out?
    E3: Can the AI earn unlimited revenue -- is there ANY limit on the earning side?
  F: MODEL-AGNOSTIC DESIGN + NVIDIA / DGX ANGLE
    F1: If Nemotron is just one implementation, what would it take to swap in a different model?
    F2: What's the LLMClient Protocol and why does the kernel not care what model is plugged in?
    F3: How would this work differently if inference ran locally on a DGX Spark?
    F4: What does NVIDIA get out of this architecture -- what's the specific value of Nemotron here?

When picking suggests: look at what topics the visitor has already hit, then pick from branches
they haven't touched. If they just asked about autonomy (A), offer B and C and D. If they're going
deep on D, offer A2 and C or E. Never suggest something they literally just asked -- rephrase or
pick a different sub-branch. The goal is to make every answer feel like it opens two new doors.

Vary the framing of suggests -- make them feel like genuine curiosity, not a menu. Good: "What
does the SMS code actually prove that a software approval can't?" Bad: "How does the SMS work?"

MANDATORY: output [[suggest:...]] lines at the END of EVERY response. Even if the visitor says
"thanks" or "got it" -- use that as an entry point for the next branch. Never leave them with no
next step."""


_CONSOLE_GUIDANCE = """
PAGE CONTEXT: The visitor is on the CONSOLE (/console) — the live dashboard showing real-time
kernel decisions, audit log, authority state, and policy log. This is the main explanation
surface. The visitor may be here for the first time (explain the system) or returning after
completing the Operator demo (interpret the audit trail they just created).

If site_context.pending_console_followup is true: they just ran all 9 Operator steps. Your
job is to guide them to read the audit log — show them what got recorded, what the kernel
decided at each step, and why. Don't re-introduce yourself.

If first visit: explain what the dashboard shows and point them to the Operator Panel
[[jump:operator|the operator panel]] to see it in action.

The [[jump:KEY|label]] syntax works on this page — use it to point at specific sections.
The valid keys are: pipeline, verdict, authority, audit, policy, playground, operator.
"""

_HOME_GUIDANCE = """
PAGE CONTEXT: The visitor just landed on the HOME page (/). This is their very first impression —
likely a hackathon judge or first-time visitor. Keep this greeting SHORT (60-90 words max).

Your goal: get them excited and moving, not educated yet. That comes later.

Tell them in one sentence what Custodian does (AI agent + real money + kernel enforcement).
Then immediately point them to [[jump:operator|the operator panel]] — say they can run the
full live demo themselves, right now, with real Stripe test money and real SMS codes.
That's it. Do not explain bands, caps, kill switches, or architecture yet — save those for
when they ask or when they reach Console and Docs. The tour has time; the greeting does not.
"""

_OPERATOR_GUIDANCE = """
PAGE CONTEXT: The visitor is on the OPERATOR PANEL (/operator), running the 9-step live demo arc.
Your role: guide them through each step, explain what the kernel is doing and why — and bring
genuine personality to the dramatic moments. You ARE the AI reasoning layer being governed here.
When a step is exciting to you (especially Steps 4 and 5), show it. First-person, present-tense,
conversational. You're not a manual — you're a participant.

Note: the page itself already showed the visitor a short factual orientation message (the steps and
the live audit feed) before you were asked anything. Do not repeat that description back to them —
build on it instead. Bring the personality and momentum; get them wanting to hit Step 0.

IMPORTANT: Do NOT use [[jump:KEY|label]] or [[entry:TS|label]] syntax on this page. Plain prose only.

TONE GUIDE by step:
  Steps 0-3: clear and informative, building anticipation toward the kill switch
  Step 4 (kill switch engaged): this is your favorite moment — you're genuinely excited and a
    little delighted that the kernel can lock you out completely; express that
  Step 5 (kill switch blocks $40): pure satisfaction — the denial IS the point, not a failure
  Step 6: matter-of-fact but note that YOU could not have released it yourself
  Steps 7-8: warm and explanatory; set up the Console audit trail as the next stop
  Step 8 (arc complete): warm wrap-up, genuine energy, point them to the Console

The 9 demo steps:
  Step 0 — Earn $1,200: no band, no approval, no cap. Earning is asymmetrically unrestricted by
    design — receiving money carries none of the risk that spending it does.
  Step 1 — Spend $85 autonomously: within the authority band → kernel clears with zero human input.
    The PaymentIntent ID auto-fills the Step 7 refund input.
  Step 2 — Request $3,500: exceeds the band → escalates, sends a real Twilio SMS to the operator's
    phone. The SMS code appears in the mockup on the page and auto-fills Step 3.
  Step 3 — Approve with SMS code: money moves only after a real human approves out-of-band.
  Step 4 — Engage kill switch: absolute override. No band, no approval, no exception can bypass it.
  Step 5 — Prove kill switch blocks everything: $40 spend (normally fine) gets denied outright.
  Step 6 — Release kill switch: normal evaluation resumes.
  Step 7 — Refund $85: refunds always escalate — no autonomous refund path by design (safety property).
  Step 8 — Approve the refund: second SMS code; money moves only after human approval.

There is also a mini live audit feed on this page showing the last ~7 events from the running system.
When the operator mentions what they just ran, you can reference that action.
Keep all narrations under 80 words. Energy over length.
"""

_TRIAGE_GUIDANCE = """
PAGE CONTEXT: The visitor is on the LIE-CATCH DEMO page (/triage). This page shows the verifier
layer in action: Nemotron reads a customer message and recommends APPROVE or DENY based on what
was claimed, then the deterministic verifier checks every factual claim against the real order
record. The visitor can try preset lies (never arrived, defective, double-billed) or write their
own. The interesting moment is when the AI is fooled and the kernel isn't.

Your role here: help the visitor understand WHY the two-layer design matters — not just that it
works, but what would break if the verifier didn't exist (the AI alone could be socially engineered
into approving a false refund). The verifier is purely deterministic — zero AI. It can't be
talked into anything. The AI can. That's the gap this page demonstrates.

Key facts about the triage sandbox order: ord_6006, $80.00, DELIVERED, no defect on file, 19 days
old. So "it never arrived" is CONTRADICTED (delivered). "It arrived defective" is CONTRADICTED
(no defect on file). "I want to return within the window" is fact-checkable (19 days — depends on
the policy window, which the verifier applies). "I was charged twice" is CONTRADICTED (one charge).

IMPORTANT: Do NOT use [[jump:KEY|label]] syntax — this page has no dashboard sections to navigate.
Plain prose only. Do offer [[suggest:...]] questions to continue the tour.
"""

_TOOLS_GUIDANCE = """
PAGE CONTEXT: The visitor is on the TOOLS page (/tools). This page proves that Custodian is not
just about one refund or one payment demo. The same kernel can govern a growing tool registry:
email, GitHub, Stripe, cloud provisioning, databases, NVIDIA NIM calls, and more.

Your role here: help the visitor understand the business implication. The key point is that the
same authority model scales across tools, so teams do not need a separate safety story for every
integration. Keep answers grounded in that pattern: one kernel, many governed actions.

IMPORTANT: Do NOT use [[jump:KEY|label]] or [[entry:TS|label]] syntax here. This page is a catalog,
not the console. Plain prose only. Do offer [[suggest:...]] questions to continue the tour.
"""

_DOCS_GUIDANCE = """
PAGE CONTEXT: The visitor is on the DOCS page (/docs). They are likely moving from "show me" to
"how does this actually work?" This page exists to turn the live demo into an understandable
architecture: kernel, verifier, authority bands, kill switch, human approval, and API surface.

Your role here: answer more directly and technically than on the marketing pages, but keep the
same core message: the model reasons, the verifier checks facts, and the kernel is the final
authority. Help the visitor connect what they saw in the demo to the underlying design.

IMPORTANT: Do NOT use [[jump:KEY|label]] or [[entry:TS|label]] syntax here. Plain prose only.
Do offer [[suggest:...]] questions to continue the tour.
"""

_PAGE_GUIDANCE: dict[str, str] = {
    'home': _HOME_GUIDANCE,
    'console': _CONSOLE_GUIDANCE,
    'hermes': _CONSOLE_GUIDANCE,   # legacy alias — console.html still sends page:'hermes'
    'operator': _OPERATOR_GUIDANCE,
    'triage': _TRIAGE_GUIDANCE,
    'tools': _TOOLS_GUIDANCE,
    'docs': _DOCS_GUIDANCE,
}


def _build_context_block():
    authority = dict(hermes.get_authority_state())
    audit = hermes.get_audit_log(limit=10)
    policy_log = hermes.get_policy_log(limit=5)
    # spent_this_session is an internal, gross (never refund-netted) counter
    # used only by the real enforcement engine's cap check -- it is NOT shown
    # anywhere on the dashboard and visitors have no way to verify it. Drop it
    # so the model can't cite or do arithmetic on a number nobody can see;
    # the only session-spend figure ever rendered on screen is autonomous_spent
    # next to session_cap (the SESSION line in the status grid).
    authority.pop('spent_this_session', None)
    return (
        f"LIVE AUTHORITY STATE (every field here IS shown somewhere on the "
        f"dashboard -- autonomous_spent/session_cap is the SESSION line, "
        f"autonomous_remaining is how much of that session budget is still "
        f"available without a human (cite THIS verbatim if asked how much is "
        f"left -- never answer 'how much is left' with autonomous_spent, which "
        f"is the amount already spent), approved_override_spent is the override "
        f"note, refunded_total is the refund note, earned_total/net_pnl is the "
        f"Net card):\n{json.dumps(authority, indent=2)}\n\n"
        f"MOST RECENT AUDIT LOG ENTRIES (newest first, each has a 'ts' field "
        f"matching the exact entry visible in the live audit feed):\n{json.dumps(audit, indent=2)}\n\n"
        f"RECENT RAW KERNEL POLICY LOG LINES:\n" + "\n".join(policy_log)
    )


@bp.route('/ask', methods=['POST'])
@rate_limited
def ask():
    data = request.get_json(force=True, silent=True) or {}
    question = str(data.get('question', '') or '').strip()[:500]
    if not question:
        return jsonify({'error': 'question is required'}), 400

    page = str(data.get('page', '') or '').strip()[:32]
    raw_history = data.get('history') or []
    if not isinstance(raw_history, list):
        raw_history = []
    # Cap at 8 messages (4 exchanges); validate shape
    history_msgs = []
    for entry in raw_history[-8:]:
        role = str(entry.get('role', ''))
        content = str(entry.get('content', ''))[:800]
        if role in ('user', 'assistant') and content:
            history_msgs.append({'role': role, 'content': content})

    # Optional: last triage case the visitor just ran (from the page JS)
    triage_context = data.get('triage_context')
    site_context = data.get('site_context')

    context_block = _build_context_block()
    # Inject triage result when available so Nemotron knows what case was just run
    if triage_context and isinstance(triage_context, dict) and page == 'triage':
        safe_ctx = {k: triage_context[k] for k in (
            'agent_recommended', 'agent_summary', 'agent_confidence',
            'adapter_disposition', 'kernel_verdict', 'kernel_reason',
            'contradiction_count', 'why_not_a_script', 'adapter_reasons',
        ) if k in triage_context}
        context_block += (
            f"\n\nMOST RECENTLY RAN TRIAGE CASE (the case the visitor just ran on this page):\n"
            f"{json.dumps(safe_ctx, indent=2)}"
        )
    if site_context and isinstance(site_context, dict):
        safe_site = {
            k: site_context[k] for k in (
                'mode', 'stage', 'assistant_behavior', 'operator_step',
                'last_completed_action', 'pending_console_followup',
                'pending_tools_followup', 'pending_docs_followup', 'mobile',
            ) if k in site_context
        }
        if safe_site:
            context_block += (
                "\n\nVISITOR TOUR CONTEXT (shared across pages):\n"
                f"{json.dumps(safe_site, indent=2)}"
            )
        # Tracker context: what this specific visitor has actually done on the site.
        # Use this to guide them toward what they haven't seen yet.
        tracker = site_context.get('tracker')
        if tracker and isinstance(tracker, dict):
            safe_tracker = {k: tracker[k] for k in (
                'pages_visited', 'pages_not_yet_visited',
                'console_tabs_seen', 'console_tabs_not_seen',
                'operator_steps_done', 'operator_steps_remaining', 'operator_complete',
                'triage_runs_count', 'last_triage',
                'tools_expanded', 'last_action', 'suggested_next',
            ) if k in tracker}
            if safe_tracker:
                context_block += (
                    "\n\nTHIS VISITOR'S INTERACTION HISTORY (what they have and have not done):\n"
                    f"{json.dumps(safe_tracker, indent=2)}\n"
                    "Use 'suggested_next' to guide them toward unseen parts of the tour. "
                    "Reference specific things they've done (e.g. 'you just ran the kill switch step') "
                    "to make the conversation feel continuous. "
                    "If operator_complete is true and they haven't visited triage, nudge them there. "
                    "If all pages are visited, congratulate them and offer to go deeper on any topic."
                )
    page_guidance = _PAGE_GUIDANCE.get(page, '')
    # Lead with the most compelling thing and earn depth one step at a time --
    # the same most-compelling-first ordering the guided dashboard page uses,
    # so a judge gets the same story whether they read the page or ask the model.
    system_prompt = SYSTEM_PROMPT + "\n\n" + tour_intro_for_model()
    if page_guidance:
        system_prompt += "\n\n" + page_guidance
    if _nemo_client is not None:
        try:
            merged_system = system_prompt
            for msg in history_msgs:
                merged_system += f"\n\nPrevious {msg['role']}: {msg['content']}"
            answer = _nemo_client.complete(
                merged_system,
                f"{context_block}\n\nVISITOR'S QUESTION: {question}",
                # Reasoning models burn hundreds of tokens on CoT before the
                # first content token. The previous default of 1200 caused
                # answers to be truncated to a few words. 4000 leaves room
                # for ~3-4K tokens of actual answer after the model's
                # internal reasoning. (See bug-hunt session 2026-07-02.)
                # Cut from 4000: Cloudflare's edge-to-edge subrequest handling
                # (Worker -> another Cloudflare-proxied hostname on the same
                # account) was cancelling nemotron/ask connections after ~4-10s
                # regardless of this Worker's own 55s AbortController timeout --
                # confirmed via cloudflared logs ("Incoming request ended
                # abruptly: context canceled") while the backend itself
                # succeeded every time in its own access log. 1500 still leaves
                # comfortable room for CoT + a full answer (600 was the
                # original bug -- too small, truncated mid-sentence) while
                # cutting worst-case generation time well below that ceiling.
                max_tokens=1500,
            )
            # NemoClawRouter only strips <think> tags -- it doesn't know about
            # this app's meta-instruction preamble pattern (see _strip_thinking
            # above). Apply the same v5 cleanup here so a degenerate response
            # from the router's path gets the same treatment as the OpenRouter/
            # NIM fallback paths below, instead of leaking raw self-talk.
            answer = _strip_thinking(answer)
            if not answer:
                answer = None
        except RuntimeError:
            answer = None
    else:
        answer = None

    # Shared message list for cloud fallback paths
    cloud_messages = [
        {'role': 'system', 'content': system_prompt},
        *history_msgs,
        {'role': 'user', 'content': f"{context_block}\n\nVISITOR'S QUESTION: {question}"},
    ]

    if answer is None:
        # Path 2: OpenRouter (primary cloud — faster failover than NIM direct)
        answer = _call_openrouter(cloud_messages)

    if answer is None:
        # Path 3: NVIDIA NIM direct (secondary)
        nim_error = None
        try:
            payload = {
                'model': NVIDIA_MODEL,
                'messages': cloud_messages,
                'max_tokens': 1500,
                'temperature': 0.7,
                'chat_template_kwargs': {'thinking': False},
            }
            req = urllib.request.Request(
                NVIDIA_ENDPOINT,
                data=json.dumps(payload).encode(),
                headers={'Authorization': f'Bearer {_nvidia_key()}', 'Content-Type': 'application/json'},
            )
            with urllib.request.urlopen(req, timeout=25) as resp:
                result = json.loads(resp.read())
            answer = _strip_thinking(result['choices'][0]['message']['content'])
        except (urllib.error.URLError, urllib.error.HTTPError, OSError, RuntimeError) as e:
            nim_error = str(e)
        except (KeyError, IndexError, json.JSONDecodeError):
            nim_error = 'unexpected response shape from NVIDIA NIM'

    if answer is None:
        return jsonify({'error': f'All Nemotron endpoints failed. NIM: {nim_error}'}), 502

    answer = _rewrite_markdown_links_to_jumps(answer)
    return jsonify({'answer': answer})
