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
// Triage/custom and nemotron/ask do live inference. The backend's own
// NemoClawRouter(timeout=25) can itself take up to 25s per provider, and
// falls back from OpenRouter to NVIDIA NIM on failure — worst case that's
// two ~25s legs back to back. Live-measured a direct (non-Worker) call at
// 23.8s on a single leg alone. 25000 here was cutting it dangerously close
// and was killing legitimate in-flight requests, not just runaway ones.
// 55000 leaves real margin under gunicorn's own 65s worker timeout on the
// backend (see custodian-dashboard.service) so the Worker never aborts a
// request the backend was still going to finish.
const TIMEOUT_SLOW_MS = 55000;

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

    // Forwarding request.headers unchanged carries the original Host header
    // (getcustodian.xyz) into a fetch() whose URL targets a *different*
    // Cloudflare-proxied hostname (rein-local.argobox.com / SECONDARY). That
    // mismatch is consistent with the intermittent failures observed here:
    // raw curl direct to the tunnel hostname was 100% reliable, but the same
    // request routed through this Worker's fetch() failed ~20-25% of the
    // time even across independent retries — Cloudflare's tunnel ingress
    // matches on Host/SNI, and a stale Host header can misroute a fraction
    // of requests at the edge. Overwrite Host per-target so it always
    // matches the actual destination.
    function makeInit(targetUrl) {
      const headers = new Headers(request.headers);
      headers.set('Host', new URL(targetUrl).host);
      return {
        method:  request.method,
        headers,
        body:    bodyBuf,
        redirect: 'follow',
      };
    }

    // Slow paths: live Nemotron inference can take 10-20s — give them full budget
    const isSlow = path.startsWith('/api/v1/triage/custom') || path.startsWith('/api/v1/nemotron/');
    const primaryTimeout  = isSlow ? TIMEOUT_SLOW_MS : TIMEOUT_MS;
    const secondaryTimeout = isSlow ? TIMEOUT_SLOW_MS : TIMEOUT_MS * 2;

    const primaryUrl = new URL(upstreamPath, PRIMARY).toString();
    const secondaryUrl = new URL(upstreamPath, SECONDARY).toString();

    // Try primary
    let response = await tryFetch(primaryUrl, makeInit(primaryUrl), primaryTimeout);

    // SECONDARY is a Tailscale CGNAT address (100.64.0.0/10) — not publicly
    // routable, so it can never actually be reached from Cloudflare's edge.
    // Retry PRIMARY several times with a SHORT timeout before giving up:
    // PRIMARY (rein-local.argobox.com) is itself a Cloudflare-proxied
    // hostname, and a Worker calling fetch() on another proxied hostname on
    // the same account intermittently hits Cloudflare's own edge-to-edge
    // request handling — observed ~25% single-attempt failure rate even with
    // a corrected Host header, confirmed independent of tunnel/origin health
    // (direct curl to the same hostname was 100% reliable across 30+
    // requests). Each failure is fast (observed sub-200ms fail-fast), so
    // several short retries is far cheaper than one trip to a SECONDARY that
    // is guaranteed to fail. 6 attempts was chosen empirically after 3
    // attempts still left ~7.5% failures live-tested against
    // getcustodian.xyz. This retry runs on slow paths too — the first
    // attempt above already used the full slow timeout, so a real slow
    // inference call already had its fair chance; a failure THIS fast
    // (sub-200ms) is the edge-routing bug, not a real timeout, and 6 * 2s of
    // retry is a small cost next to leaving live Nemotron chat completely
    // exposed to a bug that hits every path equally.
    for (let attempt = 0; !response && attempt < 6; attempt++) {
      response = await tryFetch(primaryUrl, makeInit(primaryUrl), 2000);
    }

    // Fall back to secondary
    if (!response) {
      response = await tryFetch(secondaryUrl, makeInit(secondaryUrl), secondaryTimeout);
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
