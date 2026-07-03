/**
 * CF Pages _worker.js
 *
 * /console          → console.html static asset (public live-console page)
 * /operator        → operator.html static asset (judge demo panel)
 * /triage          → triage.html static asset (lie-catch demo; JS calls API directly)
 * /api/v1/*        → Flask API endpoints (proxied to Flask backend)
 * everything else  → CF Pages static assets
 *
 * Failover: tries PRIMARY first with a 4s timeout, falls back to SECONDARY.
 * Primary: argobox-lite (full functionality — NemoClaw sandbox lives here)
 * Secondary: titan (read endpoints + degraded operator — no sandbox)
 */

const PRIMARY   = 'https://rein-local.argobox.com';
const SECONDARY = 'http://100.68.107.42:8094';
const TIMEOUT_MS = 4000;
// Triage/custom does live Nemotron inference — allow 25s before falling back
const TIMEOUT_SLOW_MS = 25000;

const PROXY_PREFIX = '/api/v1/';

async function tryFetch(url, init, timeoutMs) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(url, { ...init, signal: controller.signal });
    clearTimeout(timer);
    // Fall through to secondary only on infra failures (non-JSON error bodies).
    // JSON 5xx = application/inference error — return it directly so the client
    // sees a useful message instead of a misleading "both nodes unreachable" 503.
    // JSON 4xx = real app error (bad input, etc.) — return directly.
    // Non-JSON 4xx or 5xx = Cloudflare/infra error page (e.g. 1003 as 403 text/plain) — fall through.
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

    // Serve install.sh with correct Content-Type so curl | bash works
    if (path === '/install.sh') {
      const res = await env.ASSETS.fetch(request);
      const headers = new Headers(res.headers);
      headers.set('Content-Type', 'text/plain; charset=utf-8');
      return new Response(res.body, { status: res.status, headers });
    }

    if (!path.startsWith(PROXY_PREFIX)) {
      return env.ASSETS.fetch(request);
    }

    const upstreamPath = path + url.search;

    // Buffer the body so it can be replayed on failover — ReadableStream is single-use.
    const bodyBuf = request.method !== 'GET' && request.method !== 'HEAD'
      ? await request.arrayBuffer()
      : null;

    function makeInit() {
      return {
        method:  request.method,
        headers: request.headers,
        body:    bodyBuf,
        redirect: 'follow',
      };
    }

    // Slow paths: live Nemotron inference can take 10-20s — give them full budget
    const isSlow = path.startsWith('/api/v1/triage/custom') || path.startsWith('/api/v1/nemotron/');
    const primaryTimeout  = isSlow ? TIMEOUT_SLOW_MS : TIMEOUT_MS;
    const secondaryTimeout = isSlow ? TIMEOUT_SLOW_MS : TIMEOUT_MS * 2;

    // Try primary
    let response = await tryFetch(new URL(upstreamPath, PRIMARY).toString(), makeInit(), primaryTimeout);

    // SECONDARY is a Tailscale CGNAT address (100.64.0.0/10) — not publicly
    // routable, so it can never actually be reached from Cloudflare's edge.
    // On fast paths, retry PRIMARY once with a short timeout first: a real
    // transient blip usually clears in under a second, and that's strictly
    // faster than burning the full secondaryTimeout on an address that is
    // guaranteed to fail. Skip the retry on slow paths — a real failure
    // there is more likely a genuine timeout than a blip, and doubling to
    // ~50s would make a failing request feel broken rather than just slow.
    if (!response && !isSlow) {
      response = await tryFetch(new URL(upstreamPath, PRIMARY).toString(), makeInit(), 2000);
    }

    // Fall back to secondary
    if (!response) {
      response = await tryFetch(new URL(upstreamPath, SECONDARY).toString(), makeInit(), secondaryTimeout);
    }

    if (!response) {
      return new Response(JSON.stringify({ error: 'Backend unavailable — both nodes unreachable' }), {
        status: 503,
        headers: { 'Content-Type': 'application/json' },
      });
    }

    const headers = new Headers(response.headers);
    headers.delete('access-control-allow-origin');
    headers.delete('access-control-allow-methods');
    headers.delete('access-control-allow-headers');

    return new Response(response.body, {
      status: response.status,
      statusText: response.statusText,
      headers,
    });
  },
};
