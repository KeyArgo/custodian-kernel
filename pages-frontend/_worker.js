/**
 * CF Pages _worker.js
 *
 * /hermes          → hermes.html static asset (public live-console page)
 * /operator        → operator.html static asset (judge demo panel)
 * /triage          → triage.html static asset (lie-catch demo; JS calls API directly)
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

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname;

    const shouldProxy =
      PROXY_EXACT.has(path) || path.startsWith(PROXY_PREFIX);

    if (!shouldProxy) {
      // /hermes falls here — CF Pages ASSETS serves hermes.html at /hermes automatically
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

    const proxied = new Request(upstream.toString(), {
      method: request.method,
      headers,
      body: request.body,
      redirect: 'follow',
    });

    const isSlow = path.startsWith('/api/v1/triage/custom') || path.startsWith('/api/v1/nemotron/');
    const timeoutMs = isSlow ? TIMEOUT_SLOW_MS : TIMEOUT_MS;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);

    let response;
    try {
      response = await fetch(proxied, { signal: controller.signal });
    } catch (_) {
      return new Response(JSON.stringify({ error: 'Backend unavailable or timed out' }), {
        status: 503,
        headers: { 'Content-Type': 'application/json' },
      });
    } finally {
      clearTimeout(timer);
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
