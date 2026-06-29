/**
 * CF Pages _worker.js
 *
 * /hermes          → hermes.html static asset (public live-console page)
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
    // Treat 5xx as backend failure — fall through to secondary
    if (res.status >= 500) return null;
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
