"""Talaria dashboard — a local web UI for the "protect my agent" workflow.

Everything here was previously only reachable via three separate CLIs
(custodian/paladin/talaria) and a hand-edited YAML file — found to be
the exact friction a first-time user hit: no single place to see what's
blocked, what's in the vault, or what the current rules actually are.

This is deliberately NOT the `dashboard/` Flask app elsewhere in this
repo — that one is the hackathon's Stripe/spend operator panel, a
different tool for a different audience. This page shows exactly three
things, backed directly by the same objects the CLI uses (no duplicated
logic): the denial log timeline, vault entries (metadata only, values
are never sent to the browser), and the current policy with the
genuinely-togglable guards editable in place.

Security: binds to 127.0.0.1 only by default, and every /api/ route
requires a per-launch random token (like Jupyter's) passed as
?token=... — printed once at startup. The token is embedded into the
served HTML page itself so the page's own fetch() calls work without
the user copy-pasting it anywhere.
"""
from __future__ import annotations

import os
import secrets
import time
from pathlib import Path
from typing import Optional

from flask import Flask, jsonify, request, Response

from talaria.policy import default_policy_path, load_policy, save_policy

# Guards a policy.yaml is actually allowed to toggle -- must stay in
# sync with talaria/policy.py's build_pipeline(). Kernel-grade guards
# (self_protection, prompt_injection, secret_leak) are deliberately
# absent: they're unconditional in build_pipeline() and a UI that let
# you flip them would be lying about what saving the toggle does.
TOGGLABLE_GUARDS = ["pii", "repetition", "tool_confabulation"]


def _redact_ts(ts: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))


def create_app(vault=None, denial_log=None, policy_path: Optional[Path] = None,
              token: Optional[str] = None) -> Flask:
    app = Flask(__name__)
    app.config["POLICY_PATH"] = Path(policy_path) if policy_path else default_policy_path()
    app.config["DASHBOARD_TOKEN"] = token or secrets.token_urlsafe(24)
    app.config["VAULT"] = vault
    app.config["DENIAL_LOG"] = denial_log

    def _check_token():
        supplied = request.args.get("token") or request.headers.get("X-Dashboard-Token")
        if supplied != app.config["DASHBOARD_TOKEN"]:
            return jsonify({"error": "missing or invalid token"}), 401
        return None

    @app.before_request
    def _auth():
        if request.path.startswith("/api/"):
            denied = _check_token()
            if denied:
                return denied

    @app.route("/")
    def index():
        return Response(_PAGE_HTML.replace("__TOKEN__", app.config["DASHBOARD_TOKEN"]),
                        mimetype="text/html")

    @app.route("/api/status")
    def api_status():
        vault = app.config["VAULT"]
        dl = app.config["DENIAL_LOG"]
        policy_path = app.config["POLICY_PATH"]
        return jsonify({
            "policy_path": str(policy_path),
            "policy_exists": policy_path.exists(),
            "vault_open": vault is not None,
            "vault_path": str(vault.path) if vault is not None else None,
            "denial_count": len(dl.records()) if dl is not None else 0,
        })

    @app.route("/api/denials")
    def api_denials():
        dl = app.config["DENIAL_LOG"]
        if dl is None:
            return jsonify({"records": []})
        records = dl.records()
        records.sort(key=lambda r: r.get("ts", 0), reverse=True)
        out = [{
            "ts": _redact_ts(r.get("ts", 0)),
            "event": r.get("event"),
            "tool": r.get("ref"),
            "adapter": r.get("requester"),
            "reason": r.get("detail"),
        } for r in records[:200]]
        return jsonify({"records": out})

    @app.route("/api/vault", methods=["GET", "POST"])
    def api_vault():
        vault = app.config["VAULT"]
        if vault is None:
            return jsonify({"error": "no vault open for this dashboard session"}), 503
        if request.method == "GET":
            entries = sorted(vault.iter_meta(), key=lambda m: m["name"])
            return jsonify({"entries": entries})
        # POST: add a new entry. The value is used once, here, to call
        # vault.add() -- it is never written to a log, never echoed back
        # in the response, and never stored anywhere but the vault.
        body = request.get_json(force=True, silent=True) or {}
        name = (body.get("name") or "").strip()
        value = body.get("value") or ""
        if not name or not value:
            return jsonify({"error": "name and value are required"}), 400
        try:
            ref = vault.add(
                name, value,
                kind=body.get("kind") or "secret",
                profile=body.get("profile") or "default",
                env_var=body.get("env_var") or None,
                note=body.get("note") or "",
                allowed_hosts=body.get("allowed_hosts") or [],
            )
            vault.save()
        except Exception as e:
            return jsonify({"error": str(e)}), 400
        return jsonify({"ref": ref.uri}), 201

    @app.route("/api/policy", methods=["GET", "POST"])
    def api_policy():
        policy_path = app.config["POLICY_PATH"]
        if request.method == "GET":
            policy = load_policy(policy_path)
            guards = policy.get("guards") or {}
            return jsonify({
                "raw": policy,
                "tools_forbid": (policy.get("tools") or {}).get("forbid", []),
                "tools_allow": (policy.get("tools") or {}).get("allow", []),
                "paths_forbid": (policy.get("paths") or {}).get("forbid", []),
                "paths_forbid_globs": (policy.get("paths") or {}).get("forbid_globs", []),
                "paths_allow": (policy.get("paths") or {}).get("allow", []),
                "privacy_redact": (policy.get("privacy") or {}).get("redact", []),
                "log_denials": policy.get("log_denials", True),
                "guards": {g: guards.get(g, True) for g in TOGGLABLE_GUARDS},
                "kernel_grade_guards": ["self_protection", "prompt_injection", "secret_leak"],
            })
        body = request.get_json(force=True, silent=True) or {}
        policy = load_policy(policy_path)
        policy.setdefault("tools", {})["forbid"] = body.get("tools_forbid", [])
        policy["tools"]["allow"] = body.get("tools_allow", [])
        policy.setdefault("paths", {})["forbid"] = body.get("paths_forbid", [])
        policy["paths"]["forbid_globs"] = body.get("paths_forbid_globs", [])
        policy["paths"]["allow"] = body.get("paths_allow", [])
        policy.setdefault("privacy", {})["redact"] = body.get("privacy_redact", [])
        policy["log_denials"] = bool(body.get("log_denials", True))
        guards = policy.setdefault("guards", {})
        for g in TOGGLABLE_GUARDS:
            if g in body.get("guards", {}):
                guards[g] = bool(body["guards"][g])
        save_policy(policy, policy_path)
        return jsonify({"ok": True})

    return app


def run_dashboard(host: str = "127.0.0.1", port: int = 8765,
                  vault=None, denial_log=None, policy_path=None) -> None:
    app = create_app(vault=vault, denial_log=denial_log, policy_path=policy_path)
    token = app.config["DASHBOARD_TOKEN"]
    url = f"http://{host}:{port}/?token={token}"
    print(f"Talaria dashboard: {url}")
    print("(token changes every launch -- this URL is only valid for this session)")
    app.run(host=host, port=port, debug=False)


_PAGE_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Talaria Dashboard</title>
<style>
  :root {
    --bg: #0f1216; --panel: #171b21; --border: #262c35; --text: #e6e9ef;
    --muted: #8a93a3; --accent: #d4a45a; --deny: #e0625a; --warn: #d4a45a;
    --allow: #5ab98a; --mono: "SF Mono", Consolas, Menlo, monospace;
  }
  * { box-sizing: border-box; }
  body {
    background: var(--bg); color: var(--text); margin: 0;
    font: 14px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  }
  header {
    padding: 20px 28px; border-bottom: 1px solid var(--border);
    display: flex; align-items: baseline; gap: 12px;
  }
  header h1 { font-size: 17px; margin: 0; font-weight: 600; letter-spacing: 0.2px; }
  header .sub { color: var(--muted); font-size: 12px; }
  main { padding: 24px 28px; max-width: 1100px; margin: 0 auto; }
  .stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 28px; }
  .stat { background: var(--panel); border: 1px solid var(--border); border-radius: 8px; padding: 14px 16px; }
  .stat .label { color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; }
  .stat .value { font-size: 22px; font-weight: 600; margin-top: 4px; font-variant-numeric: tabular-nums; }
  section { margin-bottom: 32px; }
  section h2 { font-size: 13px; text-transform: uppercase; letter-spacing: 0.5px; color: var(--muted); margin: 0 0 12px; }
  .panel { background: var(--panel); border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th { text-align: left; padding: 8px 14px; color: var(--muted); font-weight: 500; font-size: 11px; text-transform: uppercase; border-bottom: 1px solid var(--border); }
  td { padding: 9px 14px; border-bottom: 1px solid var(--border); vertical-align: top; }
  tr:last-child td { border-bottom: none; }
  .mono { font-family: var(--mono); font-size: 12px; }
  .pill { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 11px; font-weight: 600; }
  .pill.deny { background: rgba(224,98,90,0.15); color: var(--deny); }
  .pill.warn { background: rgba(212,164,90,0.15); color: var(--warn); }
  .empty { padding: 24px; text-align: center; color: var(--muted); }
  form.inline { display: flex; gap: 8px; padding: 14px; flex-wrap: wrap; border-top: 1px solid var(--border); }
  input, textarea { background: #0c0f13; border: 1px solid var(--border); color: var(--text); border-radius: 5px; padding: 7px 10px; font-size: 13px; font-family: inherit; }
  input[type=text], input[type=password] { flex: 1; min-width: 140px; }
  button { background: var(--accent); color: #16130a; border: none; border-radius: 5px; padding: 7px 14px; font-weight: 600; font-size: 13px; cursor: pointer; }
  button:hover { filter: brightness(1.08); }
  button.secondary { background: transparent; border: 1px solid var(--border); color: var(--text); }
  .taglist { display: flex; flex-wrap: wrap; gap: 6px; padding: 12px 14px; }
  .tag { background: #0c0f13; border: 1px solid var(--border); border-radius: 5px; padding: 4px 8px; font-family: var(--mono); font-size: 12px; display: flex; align-items: center; gap: 6px; }
  .tag button { background: none; color: var(--muted); padding: 0; font-size: 14px; line-height: 1; }
  .taglist input { flex: 1; min-width: 160px; border: none; background: none; padding: 4px; }
  .guardrow { display: flex; justify-content: space-between; align-items: center; padding: 10px 14px; border-bottom: 1px solid var(--border); }
  .guardrow:last-child { border-bottom: none; }
  .guardrow .name { font-family: var(--mono); font-size: 13px; }
  .guardrow .desc { color: var(--muted); font-size: 12px; margin-top: 2px; }
  .switch { position: relative; width: 38px; height: 21px; }
  .switch input { opacity: 0; width: 0; height: 0; }
  .slider { position: absolute; inset: 0; background: #333; border-radius: 21px; cursor: pointer; transition: 0.15s; }
  .slider::before { content: ""; position: absolute; height: 15px; width: 15px; left: 3px; top: 3px; background: white; border-radius: 50%; transition: 0.15s; }
  input:checked + .slider { background: var(--allow); }
  input:checked + .slider::before { transform: translateX(17px); }
  .kernelgrade { padding: 12px 14px; color: var(--muted); font-size: 12px; }
  .kernelgrade code { color: var(--text); }
  .saverow { padding: 12px 14px; display: flex; justify-content: flex-end; gap: 8px; }
  .toast { position: fixed; bottom: 20px; right: 20px; background: var(--panel); border: 1px solid var(--border); border-radius: 6px; padding: 10px 16px; font-size: 13px; opacity: 0; transform: translateY(8px); transition: 0.2s; }
  .toast.show { opacity: 1; transform: translateY(0); }
</style>
</head>
<body>
<header>
  <h1>Talaria</h1>
  <span class="sub">protect my agent — denials, vault, policy</span>
</header>
<main>
  <div class="stats" id="stats"></div>

  <section>
    <h2>Denial log</h2>
    <div class="panel"><div id="denials"></div></div>
  </section>

  <section>
    <h2>Vault — <code>paladin://</code> refs (values are never shown here)</h2>
    <div class="panel">
      <div id="vault"></div>
      <form class="inline" id="addSecretForm">
        <input type="text" name="name" placeholder="name (e.g. stripe_sk)" required>
        <input type="password" name="value" placeholder="value" required>
        <input type="text" name="env_var" placeholder="env var (optional)">
        <button type="submit">Add secret</button>
      </form>
    </div>
  </section>

  <section>
    <h2>Policy — <span class="mono" id="policyPath"></span></h2>
    <div class="panel">
      <table>
        <tr><th style="width:33%">Forbidden tools</th><td id="toolsForbid"></td></tr>
        <tr><th>Forbidden paths</th><td id="pathsForbid"></td></tr>
        <tr><th>Forbidden globs</th><td id="pathsGlobs"></td></tr>
        <tr><th>PII kinds redacted</th><td id="privacyRedact"></td></tr>
      </table>
    </div>
    <div style="height:12px"></div>
    <div class="panel">
      <div id="guards"></div>
      <div class="kernelgrade">
        Always on, not configurable here (documented promise, not a policy toggle):
        <code id="kernelGuards"></code>
      </div>
      <div class="saverow">
        <span id="saveStatus" style="color:var(--muted); font-size:12px; align-self:center;"></span>
        <button class="secondary" onclick="loadPolicy()">Discard changes</button>
        <button onclick="savePolicy()">Save policy.yaml</button>
      </div>
    </div>
  </section>
</main>
<div class="toast" id="toast"></div>

<script>
const TOKEN = "__TOKEN__";
const api = (path, opts) => fetch(path + (path.includes("?") ? "&" : "?") + "token=" + TOKEN, opts)
  .then(r => r.json());

function toast(msg) {
  const t = document.getElementById("toast");
  t.textContent = msg; t.classList.add("show");
  setTimeout(() => t.classList.remove("show"), 2200);
}

function esc(s) { return String(s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c])); }

async function loadStatus() {
  const s = await api("/api/status");
  document.getElementById("stats").innerHTML = `
    <div class="stat"><div class="label">Vault</div><div class="value">${s.vault_open ? "open" : "closed"}</div></div>
    <div class="stat"><div class="label">Denials logged</div><div class="value">${s.denial_count}</div></div>
    <div class="stat"><div class="label">Policy file</div><div class="value">${s.policy_exists ? "active" : "missing"}</div></div>
    <div class="stat"><div class="label">Path</div><div class="value mono" style="font-size:12px">${esc(s.policy_path.split("/").slice(-2).join("/"))}</div></div>
  `;
}

async function loadDenials() {
  const d = await api("/api/denials");
  const el = document.getElementById("denials");
  if (!d.records.length) { el.innerHTML = '<div class="empty">Nothing blocked yet.</div>'; return; }
  el.innerHTML = `<table>
    <tr><th>When</th><th>Tool</th><th>Blocked by</th><th>Reason</th></tr>
    ${d.records.map(r => `<tr>
      <td class="mono">${esc(r.ts)}</td>
      <td class="mono">${esc(r.tool || "-")}</td>
      <td><span class="pill ${r.event === 'deny' ? 'deny' : 'warn'}">${esc(r.adapter || r.event)}</span></td>
      <td>${esc(r.reason || "")}</td>
    </tr>`).join("")}
  </table>`;
}

async function loadVault() {
  const v = await api("/api/vault");
  const el = document.getElementById("vault");
  if (v.error) { el.innerHTML = `<div class="empty">${esc(v.error)}</div>`; return; }
  if (!v.entries.length) { el.innerHTML = '<div class="empty">No secrets yet.</div>'; return; }
  el.innerHTML = `<table>
    <tr><th>Ref</th><th>Kind</th><th>Profile</th><th>Env var</th><th>Hosts</th><th>Length</th></tr>
    ${v.entries.map(e => `<tr>
      <td class="mono">paladin://${esc(e.name)}</td>
      <td>${esc(e.kind)}</td>
      <td>${esc(e.profile)}</td>
      <td class="mono">${esc(e.env_var || "-")}</td>
      <td class="mono">${(e.allowed_hosts||[]).length ? esc(e.allowed_hosts.join(", ")) : "any"}</td>
      <td>${e.length} chars</td>
    </tr>`).join("")}
  </table>`;
}

document.getElementById("addSecretForm").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const f = new FormData(ev.target);
  const body = { name: f.get("name"), value: f.get("value"), env_var: f.get("env_var") || null };
  const r = await api("/api/vault", { method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body) });
  if (r.error) { toast("Error: " + r.error); return; }
  ev.target.reset();
  toast("Added " + r.ref);
  loadVault(); loadStatus();
});

let policyState = null;

function tagList(id, items, key) {
  const el = document.getElementById(id);
  el.innerHTML = `<div class="taglist">
    ${items.map((v, i) => `<span class="tag">${esc(v)}<button onclick="removeTag('${key}',${i})">&times;</button></span>`).join("")}
    <input type="text" placeholder="add + Enter" onkeydown="if(event.key==='Enter'){event.preventDefault(); addTag('${key}', this.value); this.value='';}">
  </div>`;
}
function addTag(key, val) { if (!val.trim()) return; policyState[key].push(val.trim()); renderPolicy(); }
function removeTag(key, i) { policyState[key].splice(i, 1); renderPolicy(); }

function renderPolicy() {
  tagList("toolsForbid", policyState.tools_forbid, "tools_forbid");
  tagList("pathsForbid", policyState.paths_forbid, "paths_forbid");
  tagList("pathsGlobs", policyState.paths_forbid_globs, "paths_forbid_globs");
  tagList("privacyRedact", policyState.privacy_redact, "privacy_redact");

  const guardDescs = {
    pii: "Redact emails, phones, SSNs, cards, IPs from args and output",
    repetition: "Stop hammering / ping-pong / retry storms",
    tool_confabulation: "Catch calls to tools/args that don't exist",
  };
  document.getElementById("guards").innerHTML = Object.entries(policyState.guards).map(([k, v]) => `
    <div class="guardrow">
      <div><div class="name">${k}</div><div class="desc">${guardDescs[k] || ""}</div></div>
      <label class="switch"><input type="checkbox" ${v ? "checked" : ""} onchange="policyState.guards['${k}']=this.checked">
        <span class="slider"></span></label>
    </div>`).join("");
  document.getElementById("kernelGuards").textContent = policyState.kernel_grade_guards.join(", ");
}

async function loadPolicy() {
  policyState = await api("/api/policy");
  document.getElementById("policyPath").textContent = "~/.talaria/policy.yaml";
  renderPolicy();
  document.getElementById("saveStatus").textContent = "";
}

async function savePolicy() {
  const r = await api("/api/policy", { method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(policyState) });
  document.getElementById("saveStatus").textContent = r.ok ? "saved" : ("error: " + r.error);
  toast(r.ok ? "Policy saved" : "Save failed");
}

loadStatus(); loadDenials(); loadVault(); loadPolicy();
</script>
</body>
</html>
"""
