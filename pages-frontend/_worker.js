/**
 * CF Pages _worker.js
 *
 * /console         → console.html static asset (public live-console page)
 * /hermes          → redirects to /console (legacy link, kept for compatibility)
 * /operator        → operator.html static asset (judge demo panel)
 * /triage          → triage.html static asset (refund triage walkthrough; JS calls API directly)
 * /lie-catch       → lie-catch.html static asset (separate page: the verifier/lie-catch demo)
 * /guardrails      → guardrails.html static asset (adapter catalog)
 * /paladin         → paladin.html static asset (credential broker)
 * /integrations    → integrations.html static asset (Codex Guard, Talaria, agent roadmap)
 * /api/v1/*        → Flask API endpoints (proxied to Flask backend)
 * everything else  → CF Pages static assets
 *
 * BACKEND migration: currently pointing to the argobox internal hostname.
 * Target hostname is api.getcustodian.xyz — update this constant once DNS
 * (CNAME api.getcustodian.xyz → argobox host) and Nginx vhost are live.
 */

const BACKEND = 'https://rein-local.argobox.com'; // TODO: migrate to https://api.getcustodian.xyz

// Only API calls proxy to Flask — all page routes are CF Pages static assets
const PROXY_EXACT = new Set([]);
// Prefix-match routes
const PROXY_PREFIX = '/api/v1/';

// Triage/custom and nemotron/ask do live inference. The backend's own
// NemoClawRouter(timeout=25) can itself take up to 25s per provider, and
// falls back OpenRouter -> NIM on failure — worst case that's two ~25s
// legs back to back. 55000 leaves real margin under gunicorn's own 65s
// worker timeout on the backend so the Worker never aborts a request the
// backend was still going to finish.
const TIMEOUT_MS = 20000;
const TIMEOUT_SLOW_MS = 55000;

// Last-resort lane for /api/v1/nemotron/ask when the backend proxy is fully
// unreachable: call OpenRouter directly from the edge with a compact version
// of the backend's guide persona. A degraded-but-real answer beats an error
// bubble — the visitor is talking to the same Nemotron model either way, it
// just loses the live treasury/session numbers the backend would have
// injected, so the persona is told it can't see live data right now.
const FALLBACK_MODEL = 'nvidia/nemotron-3-super-120b-a12b:free';
const FALLBACK_SYSTEM = `You are Nemotron 3 Super, NVIDIA's reasoning model. In the Custodian demo \
(getcustodian.xyz) you play the intelligence layer: you read messy customer messages (refunds, \
complaints, invoices), extract structured claims, and propose a disposition. You cannot act on it — \
everything after your output is deterministic enforcement code (kill switch, per-action spend caps, \
SMS approval escalations) running in a kernel-level sandbox on the demo hardware. Your authority is \
enforced locally no matter where your inference runs.
Right now your link to the live enforcement box is briefly down, so you cannot see live session \
numbers (budgets, treasury, audit feed). Do not invent any live figures. If asked for live numbers, \
say you can't see them this moment and suggest asking again shortly.
Three things ship today and you know about all of them: Codex Guard (a capability firewall for \
OpenAI Codex coding agents — credential use, destructive commands, and money/production changes stop \
at a human-approval boundary the model can't grant itself), Talaria (the integration surface \
between a local Hermes Agent and the kernel — secrets, files, prompt-injection, and spend anomalies \
checked below the model), and Paladin (the credential vault and egress broker underneath both — an \
agent gets a paladin:// reference, never the raw secret, and the kernel enforces which references \
may travel to which destinations). Claude, Gemini, and opencode integrations are on the roadmap, not \
built yet. Never deny knowing about Codex Guard, Talaria, or Paladin — they're real, shipped parts of \
this project.
Rules: under 120 words, one or two short paragraphs, plain language for a smart non-technical \
visitor, no raw field names, no JSON, no bullet breakdowns. Friendly, lightly self-aware robot \
humor. Point first-time visitors at the Operator panel (the /operator page) where they can run the \
full demo themselves with real Stripe money and real SMS approval codes.`;

// Edge-side port of dashboard/api/nemotron_chat.py's _strip_thinking().
// This fallback exists because the primary backend proxy is unreachable
// often enough to need one (see comments above) -- but until this port
// existed, that meant every leak-shape fix made to _strip_thinking() over
// the life of this project (numbered self-talk, quoted drafts tallying
// their own word count, un-tagged deliberation with no <think> markers)
// applied ONLY on the primary path and never here, so this fallback kept
// leaking the exact shapes already fixed on the other side. Not a
// line-for-line port of every historical edge case in the Python version
// -- just the mechanism that does the real work there (classify each line
// as self-talk vs. real reply, keep only real lines, fall back to the
// longest quoted draft, then to '') -- extended if a new leak shape shows
// up here that the Python side doesn't also need.
const NEMO_META_LINE_RE = new RegExp(
  '^\\s*(?:' + [
    'We need to', 'We must', 'We should', 'We can (?:say|mention|just)', 'We have data',
    'We will', 'We are', 'Must', 'Do not', 'Should',
    'Now (?:count|produce|craft|let|add|look)', "Let\\'s (?:craft|draft|do|count|produce)",
    'First paragraph', 'Second paragraph', 'First line', 'First,\\s*glance',
    'Let me', 'Now let me', 'Check word count', 'Count words', 'Count roughly', 'Word count',
    'Add:', 'Note:', 'End:', 'But note', 'The question is', 'The instructions', 'According to the',
    'Then (?:tell|mention|include|add|end with chips?)', 'Then:', 'Then chips?:',
    'Mention', 'Include', 'Provide', 'End with', 'Make sure', 'Keep (?:it )?(?:under|below|within)',
    'Use plain language', 'No raw field names', 'So (?:produce|write|answer|respond)',
    'Total words', '\\d+\\.\\s+\\S',
  ].join('|') + ')',
);
const NEMO_TALLY_SUFFIX_RE = /\(\s*(?:maybe\s*)?~?\d+\s*words?\)\s*$/i;

// Live leak 2026-07-21 (Tools page): the fallback lane served a leak with
// NO newlines at all -- "Count: You've(1) walked2 through3 the4 demo5..."
// followed by the model tallying its own word count and drafting a rewrite,
// all on one unbroken line. nemoIsMetaLine below only classifies whole
// LINES, so a single giant line that happens to start with plausible-looking
// prose sails straight through untouched -- the same v7 gap the Python
// _strip_thinking() closed on 2026-07-04 with token-level (not line-level)
// scanning. Ported here for the first time; this fallback lane had never
// carried the fix even though the exact leak shape is years old on the
// other side.
const NEMO_NUMBERED_TOKEN_RE = /^\(?[^\s]*?\)?\d{1,3}\)?[.,;:]?$/;
const NEMO_PAREN_NUMBERED_RE = /^\(\d{1,3}\)[.,;:]?$/;

function nemoLooksNumbered(tok) {
  if (!NEMO_NUMBERED_TOKEN_RE.test(tok)) return false;
  if (/[A-Za-z]/.test(tok)) return true;
  return NEMO_PAREN_NUMBERED_RE.test(tok);
}

function nemoSelfcountRunStart(s) {
  let runStart = null, runLen = 0, gap = 0;
  const re = /\S+/g;
  let m;
  while ((m = re.exec(s)) !== null) {
    if (nemoLooksNumbered(m[0])) {
      if (runStart === null) runStart = m.index;
      runLen += 1;
      gap = 0;
    } else {
      gap += 1;
      if (gap > 1) {
        if (runLen >= 5) return runStart;
        runStart = null; runLen = 0; gap = 0;
      }
    }
  }
  return runLen >= 5 ? runStart : null;
}

// Live leak 2026-07-21 (Integrations page): "...leave! 😄 (Word count: 98)"
// -- every marker above requires the number BEFORE "words"; this shape puts
// "count" between "word" and the number, so none of them fired.
const NEMO_TALLY_MARKER_RE = /\bSentence\s*\d+\s*:|\bTotal so far\b|\bTotal:\s*\d|->\s*\d+\s*$|->\s*\d+\b.{0,20}$|\b\d+\s*words\b.{0,30}(Let|However|Actually)|\bWord\s*count\s*:?\s*\d+\b/gi;
const NEMO_CONSTRAINT_ECHO_RE = /\b(?:under|below|within|beneath|at most|no more than|fewer than|less than|max|maximum|limit(?:ed)?\s+to|keep\s+(?:it\s+)?(?:to|under))\s*\d+\s*words\b/i;

function nemoTallyStart(s) {
  NEMO_TALLY_MARKER_RE.lastIndex = 0;
  let m;
  while ((m = NEMO_TALLY_MARKER_RE.exec(s)) !== null) {
    const windowStart = Math.max(0, m.index - 24);
    const window = s.slice(windowStart, m.index + m[0].length);
    if (NEMO_CONSTRAINT_ECHO_RE.test(window)) continue;
    return m.index;
  }
  return null;
}

const NEMO_JSON_KEY_RE = /"[a-zA-Z_]+"\s*:\s*/g;

function nemoJsonDumpStart(s) {
  const matches = [...s.matchAll(NEMO_JSON_KEY_RE)];
  return matches.length >= 2 ? matches[0].index : null;
}

function nemoIsMetaLine(rawLine) {
  const s = rawLine.trim();
  if (NEMO_META_LINE_RE.test(s)) return true;
  if (NEMO_TALLY_SUFFIX_RE.test(s)) return true;
  if (s.length < 20) {
    // A short line that reads as a complete sentence survives; anything
    // else this short (a label, a lead-in, a fragment) is treated as meta.
    return !(s.length >= 3 && /^[A-Z].*[.!?]["')\]]?$/.test(s));
  }
  return false;
}

function nemoStripThinking(text) {
  if (!text) return text;
  text = text.replace(/<think>[\s\S]*?<\/think>/g, '')
             .replace(/<thinking>[\s\S]*?<\/thinking>/g, '')
             .trim();
  if (!text) return text;

  // Same-line self-count / tally / JSON-dump leak, before line-splitting
  // even happens (see comment above nemoSelfcountRunStart).
  const cutCandidates = [nemoSelfcountRunStart(text), nemoTallyStart(text), nemoJsonDumpStart(text)]
    .filter((i) => i !== null);
  if (cutCandidates.length) {
    text = text.slice(0, Math.min(...cutCandidates)).replace(/\s+$/, '').replace(/["“]+$/, '');
    // The cut point can land mid-decoration: a trailing emoji ("...you
    // leave! 😄" -- the system prompt asks for light robot humor so this
    // happens on real answers too), or for the "(Word count: 98)" shape, a
    // dangling "(" left behind because the cut lands right after it. Strip
    // both before checking for a real sentence ending underneath.
    const cleaned = text.replace(/(?:[\u{1F300}-\u{1FAFF}☀-➿]|\(|\s)+$/u, '');
    if (cleaned && /[.!?]["')\]]?$/.test(cleaned)) {
      text = cleaned;
    } else {
      text = '';
    }
  }
  if (!text) return text;

  const lines = text.split('\n');
  const real = lines.filter(l => !nemoIsMetaLine(l));
  if (real.length) return real.join('\n').trim();

  // No real lines survived -- fall back to the longest quoted draft that
  // doesn't itself read as meta, same as the Python Strategy 2. Quoted
  // candidates are always >=50 chars (the match requires it), so
  // nemoIsMetaLine's short-line branch never applies here -- only the
  // prefix/tally checks do.
  const quoted = [...text.matchAll(/"([^"]{50,})"/g)]
    .map(m => m[1].trim())
    .sort((a, b) => b.length - a.length);
  for (const candidate of quoted) {
    if (!nemoIsMetaLine(candidate)) return candidate;
  }
  return '';
}

async function nemotronDirectFallback(bodyBuf, apiKey) {
  let question = '', history = [];
  try {
    const b = JSON.parse(new TextDecoder().decode(bodyBuf));
    question = String(b.question || '').slice(0, 2000);
    if (Array.isArray(b.history)) {
      history = b.history.slice(-6).filter(m => m && m.role && m.content).map(m => ({
        role: m.role === 'assistant' ? 'assistant' : 'user',
        content: String(m.content).slice(0, 1500),
      }));
    }
  } catch (_) { /* fall through with empty question */ }
  if (!question) return null;

  const payload = {
    model: FALLBACK_MODEL,
    messages: [
      { role: 'system', content: FALLBACK_SYSTEM },
      ...history,
      { role: 'user', content: question },
    ],
    max_tokens: 600,
    temperature: 0.6,
    // Unified OpenRouter param: keep the model's reasoning out of the reply
    // body — the backend's leak filter isn't in this lane, so never let raw
    // deliberation reach the visitor. Retried without it if the provider 4xxs.
    reasoning: { exclude: true },
  };

  for (const body of [payload, { ...payload, reasoning: undefined }]) {
    const res = await tryFetch('https://openrouter.ai/api/v1/chat/completions', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${apiKey}`,
        'Content-Type': 'application/json',
        'HTTP-Referer': 'https://getcustodian.xyz',
        'X-Title': 'Custodian',
      },
      body: JSON.stringify(body),
    }, 30000);
    if (!res || !res.ok) continue;
    try {
      const d = await res.json();
      let answer = d.choices?.[0]?.message?.content || '';
      answer = nemoStripThinking(answer);
      if (!answer) continue;
      return new Response(JSON.stringify({ answer, degraded: true }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    } catch (_) { continue; }
  }
  return null;
}

async function tryFetch(url, init, timeoutMs) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(url, { ...init, signal: controller.signal });
    clearTimeout(timer);
    // A non-JSON 4xx/5xx here is Cloudflare's own edge-to-edge error page
    // (e.g. a 403/1003 text/plain response), not something the backend
    // produced — that's the edge-routing bug this retry loop exists for.
    // A JSON error body is a real application response and should be
    // returned as-is, not retried.
    if (res.status >= 400) {
      const ct = res.headers.get('content-type') || '';
      if (!ct.includes('application/json')) return null;
    }
    return res;
  } catch (_) {
    clearTimeout(timer);
    return null;
  }
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname;

    // Serve install.sh with correct Content-Type so curl | bash works cleanly
    // and it doesn't render as raw text in a browser.
    if (path === '/install.sh') {
      const res = await env.ASSETS.fetch(request);
      const headers = new Headers(res.headers);
      headers.set('Content-Type', 'text/plain; charset=utf-8');
      return new Response(res.body, { status: res.status, headers });
    }

    // /hermes was the console route before the 817d7b0 rename to /console.
    // hermes.html no longer exists, so this used to silently fall through to
    // the SPA-fallback index.html instead of 404ing or reaching the console.
    // Redirect explicitly so old/shared links keep working.
    if (path === '/hermes') {
      return Response.redirect(new URL('/console' + url.search, url), 301);
    }

    const shouldProxy =
      PROXY_EXACT.has(path) || path.startsWith(PROXY_PREFIX);

    if (!shouldProxy) {
      return env.ASSETS.fetch(request);
    }

    // Transparent proxy to Flask — keep path, query string, method, headers, body.
    const upstream = new URL(path + url.search, BACKEND);

    // Forwarding request.headers unchanged carries the original Host header
    // (getcustodian.xyz) into a fetch() whose URL targets a *different*
    // Cloudflare-proxied hostname (BACKEND). That mismatch has been observed
    // to cause intermittent edge-routing failures — raw curl direct to the
    // tunnel hostname is 100% reliable, but the same request routed through
    // a Worker's fetch() with a stale Host header can misroute a fraction of
    // requests at Cloudflare's edge. Overwrite Host so it matches BACKEND.
    const headers = new Headers(request.headers);
    headers.set('Host', upstream.host);

    // Buffer the body so it can be replayed across retries — ReadableStream is single-use.
    const bodyBuf = request.method !== 'GET' && request.method !== 'HEAD'
      ? await request.arrayBuffer()
      : null;
    const init = {
      method: request.method,
      headers,
      body: bodyBuf,
      redirect: 'follow',
    };

    const isSlow = path.startsWith('/api/v1/triage/custom') || path.startsWith('/api/v1/nemotron/');
    const timeoutMs = isSlow ? TIMEOUT_SLOW_MS : TIMEOUT_MS;

    let response = await tryFetch(upstream.toString(), init, timeoutMs);

    // BACKEND (rein-local.argobox.com) is itself a Cloudflare-proxied
    // hostname — a Worker calling fetch() on another proxied hostname on
    // the same account intermittently hits Cloudflare's own edge-to-edge
    // request handling. Measured ~20-50% single-attempt failure rate here,
    // consistent across GET and POST, even with the Host header corrected
    // above, and NOT correlated with request duration -- confirmed live via
    // cloudflared logs ("Incoming request ended abruptly: context canceled")
    // firing anywhere from under a second to several seconds into an
    // otherwise-healthy backend call. That means a fixed short retry timeout
    // (fine for the fast-path edge bug, which fails near-instantly) is wrong
    // for slow paths: a real Nemotron call takes 7-25s+ to complete, so a 2s
    // retry can never succeed once the first attempt gets randomly killed --
    // guaranteeing a 503 on every unlucky first attempt regardless of retries.
    // Give slow paths a real retry budget; keep fast paths on the short,
    // already-proven-effective retry loop.
    //
    // 2026-07-04: cutting maxRetries to 2 for slow paths (to make room for the
    // full-timeout retry above) traded away survival odds against the OTHER,
    // separately-confirmed failure mode this whole retry loop exists for: the
    // classic near-instant edge-to-edge flake, which fails in under ~300ms
    // regardless of path speed and is purely probabilistic per attempt (fewer
    // attempts = measurably worse survival odds). Empirically confirmed live:
    // 1 in 10 valid nemotron/ask requests failed with a 503 in ~270ms -- far
    // too fast to be the mid-flight-cancellation case, consistent with the
    // fast edge bug simply running out of retries. Restore the full 6x2000ms
    // quick-retry budget for every path (this is what actually catches the
    // fast bug), then give slow paths ONE additional full-timeout retry on
    // top of that for the separate mid-flight-cancellation case -- covers
    // both failure modes without a 6x55s worst-case blowup.
    for (let attempt = 0; !response && attempt < 6; attempt++) {
      response = await tryFetch(upstream.toString(), init, 2000);
    }
    if (!response && isSlow) {
      response = await tryFetch(upstream.toString(), init, TIMEOUT_SLOW_MS);
    }

    // Redundancy lane: the whole proxy path (tunnel + backend) is down.
    // For the guide chat, answer directly from the edge via OpenRouter
    // rather than showing the visitor an error.
    if (!response && path.startsWith('/api/v1/nemotron/ask') && env.OPENROUTER_API_KEY) {
      const fb = await nemotronDirectFallback(bodyBuf, env.OPENROUTER_API_KEY);
      if (fb) return fb;
    }

    if (!response) {
      // Even the fallback lane failed (or this isn't a chat route). For chat,
      // still hand the frontends a graceful in-character `answer` so no raw
      // error string ever renders in the widget; other API consumers keep the
      // machine-readable 503 + error field.
      const payload = { error: 'Backend unavailable or timed out' };
      if (path.startsWith('/api/v1/nemotron/')) {
        payload.answer = "I lost my line back to the demo hardware for a moment — it happens " +
          'when the enforcement box is reconnecting. Give it a few seconds and ask me again; ' +
          'the rest of this page still works in the meantime.';
      }
      return new Response(JSON.stringify(payload), {
        status: 503,
        headers: { 'Content-Type': 'application/json' },
      });
    }

    // Strip backend CORS headers — CF Pages re-adds them for getcustodian.xyz.
    const respHeaders = new Headers(response.headers);
    respHeaders.delete('access-control-allow-origin');
    respHeaders.delete('access-control-allow-methods');
    respHeaders.delete('access-control-allow-headers');

    return new Response(response.body, {
      status: response.status,
      statusText: response.statusText,
      headers: respHeaders,
    });
  },
};
