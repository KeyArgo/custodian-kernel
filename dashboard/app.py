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
from flask import Flask, render_template, send_from_directory

import sys
from pathlib import Path as _Path
# Ensure the repo root (which holds the `custodian` package) is importable
# regardless of the cwd gunicorn is started from. Without this a restart
# from dashboard/ crash-loops on ModuleNotFoundError: custodian.
sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

import api.debug as debug
import api.hermes as hermes
import api.nemotron_chat as nemotron_chat
import api.operator as operator
import api.playground as playground
import api.stripe_panel as stripe_panel
import api.stripe_webhook as stripe_webhook
import api.pnl as pnl
import api.triage as triage
import api.triage_live as triage_live
import api.tools as tools_api

app = Flask(__name__, template_folder='templates')
app.register_blueprint(hermes.bp, url_prefix='/api/v1/hermes')
app.register_blueprint(playground.bp, url_prefix='/api/v1/playground')
app.register_blueprint(debug.bp, url_prefix='/api/v1/debug')
app.register_blueprint(nemotron_chat.bp, url_prefix='/api/v1/nemotron')
app.register_blueprint(operator.bp, url_prefix='/api/v1/operator')
app.register_blueprint(stripe_panel.bp, url_prefix='/api/v1/stripe')
app.register_blueprint(stripe_webhook.bp, url_prefix='/api/v1/stripe')
app.register_blueprint(pnl.bp, url_prefix='/api/v1/pnl')
app.register_blueprint(triage.bp, url_prefix='/api/v1/triage')
app.register_blueprint(triage_live.bp, url_prefix='/api/v1/triage')
app.register_blueprint(tools_api.tools_bp, url_prefix='/api/v1/tools')

# CORS allowlist for the separately-hosted Cloudflare Pages frontend.
# Scoped to /api/ routes only — never the root page route.
# rein.argobox.com + rein-custodian.pages.dev kept during CF Pages rename transition.
# Target: getcustodian.xyz only, once the CF Pages project is renamed.
ALLOWED_ORIGINS = {
    'https://getcustodian.xyz',           # primary public domain
    'https://www.getcustodian.xyz',       # www variant
    'https://rein.argobox.com',           # legacy — remove after CF Pages rename
    'https://rein-custodian.pages.dev',   # legacy — remove after CF Pages rename
}


@app.before_request
def handle_preflight():
    from flask import request, make_response
    if request.method == 'OPTIONS':
        origin = request.headers.get('Origin')
        resp = make_response('', 204)
        if origin in ALLOWED_ORIGINS:
            resp.headers['Access-Control-Allow-Origin'] = origin
            resp.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
            resp.headers['Access-Control-Allow-Headers'] = 'Content-Type, X-Operator-Token'
            resp.headers['Access-Control-Max-Age'] = '86400'
        return resp


@app.after_request
def add_cors_headers(response):
    from flask import request
    origin = request.headers.get('Origin')
    if origin in ALLOWED_ORIGINS:
        response.headers['Access-Control-Allow-Origin'] = origin
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, X-Operator-Token'
        response.headers['Access-Control-Max-Age'] = '86400'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    return response


@app.route('/favicon.svg')
def favicon():
    return send_from_directory(app.static_folder, 'favicon.svg', mimetype='image/svg+xml')


@app.route('/')
@app.route('/hermes')
@app.route('/console')
def dashboard():
    return render_template('hermes/dashboard.html')


@app.route('/triage')
def triage_panel():
    return render_template('hermes/triage.html')


@app.route('/operator')
def operator_panel():
    # Deliberately NOT linked from the public dashboard or robots-indexed --
    # see api/operator.py's module docstring for why this stays operator-only.
    return render_template('hermes/operator.html')


if __name__ == '__main__':
    # threaded=True so one slow/concurrent request doesn't block every other
    # visitor -- the Werkzeug dev server is single-threaded by default, which
    # is fine for local testing but a real liability once this is reachable
    # publicly during judging. gunicorn (wsgi:app) is the more robust option
    # for sustained traffic; this is the cheap, immediate mitigation.
    app.run(host='0.0.0.0', port=8094, debug=False, threaded=True)
