/**
 * CF Pages _worker.js — transparent reverse proxy for the Flask dashboard.
 *
 * Routes proxied to the Flask backend (rein-local.argobox.com):
 *   /hermes          → live ops dashboard HTML
 *   /operator        → password-gated operator panel HTML
 *   /triage          → Flask-served triage walkthrough (without .html)
 *   /api/v1/*        → all API endpoints
 *
 * Everything else → env.ASSETS.fetch() to serve the CF Pages static files
 * (index.html, triage.html, favicon.svg, etc.)
 */

const BACKEND = 'https://rein-local.argobox.com';

// Exact-match routes proxied to Flask (no sub-paths needed)
const PROXY_EXACT = new Set(['/hermes', '/operator', '/triage']);
// Prefix-match routes (Flask has many /api/v1/* endpoints)
const PROXY_PREFIX = '/api/v1/';

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname;

    const shouldProxy =
      PROXY_EXACT.has(path) || path.startsWith(PROXY_PREFIX);

    if (!shouldProxy) {
      // Serve static CF Pages asset (index.html, triage.html, favicon.svg…)
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
