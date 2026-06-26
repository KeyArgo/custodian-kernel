/**
 * CF Pages catch-all Function — transparent reverse proxy for the Flask dashboard.
 *
 * Routes that should hit the Flask backend (rein-local.argobox.com):
 *   /hermes          → the live ops dashboard HTML
 *   /operator        → the password-gated operator panel HTML
 *   /triage          → the Flask-served triage walkthrough
 *   /api/v1/*        → all API endpoints (hermes, triage, nemotron, stripe, playground…)
 *
 * Everything else falls through to CF Pages static assets (index.html, triage.html,
 * favicon.svg, etc.) — returning null from onRequest tells Pages to serve the static file.
 */

const BACKEND = 'https://rein-local.argobox.com';

// Prefixes that should be proxied to the Flask server.
const PROXY_PREFIXES = ['/hermes', '/operator', '/triage', '/api/v1/'];

export async function onRequest(context) {
  const url = new URL(context.request.url);
  const path = url.pathname;

  // Only intercept backend routes; let static files pass through.
  const shouldProxy = PROXY_PREFIXES.some(
    (prefix) => path === prefix || path.startsWith(prefix),
  );
  if (!shouldProxy) return; // null → Pages serves the static file

  // Build the upstream URL, preserving the path and query string.
  const upstream = new URL(path + url.search, BACKEND);

  // Forward the original request headers so the Flask app sees the real
  // origin, content-type, operator token, etc.
  const proxied = new Request(upstream.toString(), {
    method: context.request.method,
    headers: context.request.headers,
    body: context.request.body,
    redirect: 'follow',
  });

  const response = await fetch(proxied);

  // Strip the backend's CORS headers — the Pages domain already owns this
  // origin so the browser won't need them, and keeping them can cause
  // duplicate-header problems.
  const headers = new Headers(response.headers);
  headers.delete('access-control-allow-origin');
  headers.delete('access-control-allow-methods');
  headers.delete('access-control-allow-headers');

  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers,
  });
}
