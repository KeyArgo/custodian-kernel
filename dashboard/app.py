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
import api.triage as triage

app = Flask(__name__, template_folder='templates')
app.register_blueprint(hermes.bp, url_prefix='/api/v1/hermes')
app.register_blueprint(playground.bp, url_prefix='/api/v1/playground')
app.register_blueprint(debug.bp, url_prefix='/api/v1/debug')
app.register_blueprint(nemotron_chat.bp, url_prefix='/api/v1/nemotron')
app.register_blueprint(operator.bp, url_prefix='/api/v1/operator')
app.register_blueprint(stripe_panel.bp, url_prefix='/api/v1/stripe')
app.register_blueprint(triage.bp, url_prefix='/api/v1/triage')

# Allows the separately-hosted static frontend (Cloudflare Pages) to call
# this backend's read-only/sandboxed-demo API cross-origin. rein.argobox.com
# is now a custom domain bound to the Pages project -- a browser visiting it
# sends that hostname as the real Origin, not rein-custodian.pages.dev, so
# both need to be allowed. This app itself is reached at rein-local.argobox.com
# now, not rein.argobox.com -- see commit history for the cutover. Deliberately
# scoped to only the /api/ routes -- never the root page route -- and to
# GET/POST, matching what those endpoints actually do.
ALLOWED_ORIGINS = {
    'https://rein.argobox.com',           # custom domain bound to the Pages project
    'https://rein-custodian.pages.dev',   # the underlying Pages domain
    'https://getcustodian.xyz',           # primary public domain
    'https://www.getcustodian.xyz',       # www variant
}


@app.after_request
def add_cors_headers(response):
    from flask import request
    origin = request.headers.get('Origin')
    if origin in ALLOWED_ORIGINS:
        response.headers['Access-Control-Allow-Origin'] = origin
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    return response


@app.route('/favicon.svg')
def favicon():
    return send_from_directory(app.static_folder, 'favicon.svg', mimetype='image/svg+xml')


@app.route('/')
@app.route('/hermes')
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
