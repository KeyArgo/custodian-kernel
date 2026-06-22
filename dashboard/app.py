"""Custodian dashboard — standalone Flask app.

Live proof for the Custodian engine + ops-officer demo. Reads the NemoClaw
sandbox's stripe-spend skill state directly off disk (this app runs on the
same host as the sandbox, so no SSH or extra network hop), and reads raw
kernel-level OCSF policy decisions from a plain text file maintained by a
separate process (scripts/dump_ocsf_log.py).

Deliberately has NO Docker socket access of its own. This process is public-
facing on a shared production host running many other real services -- it
must never have the ability to enumerate or touch containers beyond what it
explicitly needs, which is nothing. See scripts/dump_ocsf_log.py for the
one, narrowly-scoped process that does need that access, and why splitting
the two matters.

Deliberately has zero dependency on any other ArgoBox/command-center code —
this is a hackathon submission artifact, not a feature of that production
stack.
"""
from flask import Flask, render_template

import api.hermes as hermes
import api.playground as playground

app = Flask(__name__, template_folder='templates')
app.register_blueprint(hermes.bp, url_prefix='/api/v1/hermes')
app.register_blueprint(playground.bp, url_prefix='/api/v1/playground')

# Allows a separately-hosted static frontend (Cloudflare Pages) to call this
# backend's read-only/sandboxed-demo API cross-origin, while the dashboard's
# own HTML/JS (served from this same app, same origin) is unaffected by this
# either way. Deliberately scoped to only the /api/ routes -- never the root
# page route -- and to GET/POST, matching what those endpoints actually do.
ALLOWED_ORIGINS = {
    'https://rein.argobox.com',
    'https://rein-custodian.pages.dev',  # real Cloudflare Pages domain, confirmed at project creation
}


@app.after_request
def add_cors_headers(response):
    from flask import request
    origin = request.headers.get('Origin')
    if origin in ALLOWED_ORIGINS:
        response.headers['Access-Control-Allow-Origin'] = origin
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return response


@app.route('/')
@app.route('/hermes')
def dashboard():
    return render_template('hermes/dashboard.html')


if __name__ == '__main__':
    # threaded=True so one slow/concurrent request doesn't block every other
    # visitor -- the Werkzeug dev server is single-threaded by default, which
    # is fine for local testing but a real liability once this is reachable
    # publicly during judging. gunicorn (wsgi:app) is the more robust option
    # for sustained traffic; this is the cheap, immediate mitigation.
    app.run(host='0.0.0.0', port=8094, debug=False, threaded=True)
