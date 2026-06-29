#!/usr/bin/env python3
import argparse, json, os, sys
TOOL = "modal-function-list"

def _use_sdk():
    import modal
    apps = modal.apps.list_apps()
    return [{"app_id": a.app_id, "app_name": a.description, "state": str(a.state)} for a in apps]

def _use_rest():
    import requests
    tid, tsec = os.environ["MODAL_TOKEN_ID"], os.environ["MODAL_TOKEN_SECRET"]
    r = requests.get("https://api.modal.com/v1/apps",
                     headers={"Authorization": f"Token {tid}:{tsec}"}, timeout=15)
    r.raise_for_status()
    data = r.json()
    return [{"app_id": a["app_id"], "app_name": a.get("description",""), "state": str(a.get("state",0))}
            for a in data.get("apps", data if isinstance(data, list) else [])]

def main():
    argparse.ArgumentParser().parse_args()  # handles --help
    if not os.environ.get("MODAL_TOKEN_ID") or not os.environ.get("MODAL_TOKEN_SECRET"):
        print(json.dumps({"ok": False, "stub": True, "tool": TOOL,
                          "message": "Set MODAL_TOKEN_ID and MODAL_TOKEN_SECRET to enable"}))
        sys.exit(0)
    try:
        try:
            apps = _use_sdk()
        except Exception:
            apps = _use_rest()
        print(json.dumps({"ok": True, "tool": TOOL, "apps": apps}))
    except Exception as e:
        print(json.dumps({"ok": False, "tool": TOOL, "error": str(e)}))

if __name__ == "__main__":
    main()
