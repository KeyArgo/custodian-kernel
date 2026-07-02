#!/usr/bin/env python3
import argparse, json, os, sys
TOOL = "modal-invoke"

def _use_sdk(app_name, func_name, payload):
    import modal
    f = modal.Function.from_name(app_name, func_name)
    args = payload if payload else ()
    kwargs = payload if isinstance(payload, dict) else {}
    if isinstance(payload, list):
        result = f.remote(*args)
    elif isinstance(payload, dict):
        result = f.remote(**kwargs)
    else:
        result = f.remote(payload) if payload is not None else f.remote()
    return result, None

def _use_rest(tid, tsec, app_name, func_name, payload):
    import requests
    base = "https://api.modal.com/v1"
    hdr = {"Authorization": f"Token {tid}:{tsec}"}

    # Resolve function_id from app_name + function_name
    r = requests.get(f"{base}/apps", headers=hdr, timeout=15)
    r.raise_for_status()
    apps = r.json().get("apps", [])
    if app_name:
        app_ids = [a["app_id"] for a in apps if a.get("description") == app_name]
    else:
        app_ids = [a["app_id"] for a in apps] if apps else []

    call_result = None
    call_id = None
    for app_id in app_ids:
        fr = requests.get(f"{base}/apps/{app_id}/functions", headers=hdr, timeout=15)
        if fr.ok:
            funcs = fr.json().get("functions", [])
            for fn in funcs:
                if fn.get("function_name", "").endswith(func_name):
                    fn_id = fn["function_id"]
                    body = {"args": [], "kwargs": {}}
                    if payload is not None:
                        if isinstance(payload, list):
                            body["args"] = payload
                        elif isinstance(payload, dict):
                            body["kwargs"] = payload
                        else:
                            body["args"] = [payload]
                    cr = requests.post(f"{base}/function/{fn_id}/call", headers=hdr,
                                       json=body, timeout=60)
                    cr.raise_for_status()
                    data = cr.json()
                    call_result = data
                    call_id = data.get("call_id", fn_id)
                    return call_result, call_id
    raise RuntimeError(f"Function '{func_name}' not found in app '{app_name or 'any'}'. "
                       f"Checked {len(app_ids)} app(s).")

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--function-name", default="benchmark")
    p.add_argument("--app-name", default="custodian-benchmark")
    p.add_argument("--payload", default=None)
    a = p.parse_args()

    tid = os.environ.get("MODAL_TOKEN_ID")
    tsec = os.environ.get("MODAL_TOKEN_SECRET")
    if not tid or not tsec:
        print(json.dumps({"ok": False, "stub": True, "tool": TOOL,
                          "message": "Set MODAL_TOKEN_ID and MODAL_TOKEN_SECRET to enable"}))
        sys.exit(0)

    payload = None
    if a.payload:
        try:
            payload = json.loads(a.payload)
        except json.JSONDecodeError:
            payload = a.payload

    app_name = a.app_name or "custodian-benchmark"
    func_name = a.function_name or "benchmark"

    try:
        try:
            result, call_id = _use_sdk(app_name, func_name, payload)
        except Exception:
            result, call_id = _use_rest(tid, tsec, app_name, func_name, payload)
        out = {"ok": True, "tool": TOOL, "function": func_name, "result": result}
        if call_id:
            out["call_id"] = call_id
        print(json.dumps(out))
    except Exception as e:
        print(json.dumps({"ok": False, "tool": TOOL, "error": str(e)}))

if __name__ == "__main__":
    main()
