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
