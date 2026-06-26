/**
 * CF Pages _worker.js
 *
 * /hermes          → hermes.html static asset (public live-console page)
 * /operator        → Flask operator panel (proxied, password-gated)
 * /triage          → Flask triage walkthrough (proxied)
 * /api/v1/*        → Flask API endpoints (proxied)
 * everything else  → CF Pages static assets
 */

const BACKEND = 'https://rein-local.argobox.com';

// Routes proxied to Flask
const PROXY_EXACT = new Set(['/operator', '/triage']);
// Prefix-match routes
const PROXY_PREFIX = '/api/v1/';

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
    const proxied = new Request(upstream.toString(), {
      method: request.method,
      headers: request.headers,
      body: request.body,
      redirect: 'follow',
    });

    const response = await fetch(proxied);

    // Rewrite the backend's CORS headers so they reflect rein.argobox.com,
    // not rein-local.argobox.com (same-origin from the browser's perspective).
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
