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

    // Strip backend CORS headers — CF Pages re-adds them for getcustodian.xyz.
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
