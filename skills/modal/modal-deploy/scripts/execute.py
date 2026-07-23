#!/usr/bin/env python3
import argparse, json, os, re, subprocess, sys
TOOL = "modal-deploy"

def _deploy_via_sdk(app_file, app_name):
    import importlib.util, modal
    spec = importlib.util.spec_from_file_location("_modal_deploy", os.path.abspath(app_file))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    app_obj = getattr(mod, "app", None)
    if app_obj is None:
        for v in vars(mod).values():
            if isinstance(v, modal.App):
                app_obj = v
                break
    if app_obj is None:
        raise RuntimeError(f"No modal.App object found in {app_file}")
    app_obj.deploy(app_name or app_obj.name)
    url = f"https://{(app_name or app_obj.name) or 'app'}.modal.run"
    return (app_name or app_obj.name), url

def _deploy_via_cli(app_file, app_name):
    env = {**os.environ, "MODAL_TOKEN_ID": os.environ["MODAL_TOKEN_ID"],
           "MODAL_TOKEN_SECRET": os.environ["MODAL_TOKEN_SECRET"]}
    cmd = ["modal", "deploy", os.path.abspath(app_file)]
    r = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=120)
    if r.returncode != 0:
        raise RuntimeError(f"modal deploy failed: {r.stderr.strip() or r.stdout.strip()}")
    name = app_name
    url = None
    for line in r.stdout.splitlines():
        m = re.search(r'https://[\w.-]+\.modal\.run', line)
        if m:
            url = m.group(0)
        m2 = re.search(r'"([^"]+)"\s+deployed', line)
        if m2 and not name:
            name = m2.group(1)
    if not name:
        name = app_name or os.path.splitext(os.path.basename(app_file))[0]
    return name, url or f"https://{name}.modal.run"

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--app-file", required=True)
    p.add_argument("--app-name", default=None)
    a = p.parse_args()

    if not os.environ.get("MODAL_TOKEN_ID") or not os.environ.get("MODAL_TOKEN_SECRET"):
        print(json.dumps({"ok": False, "stub": True, "tool": TOOL,
                          "message": "Set MODAL_TOKEN_ID and MODAL_TOKEN_SECRET to enable"}))
        sys.exit(0)

    if not os.path.isfile(a.app_file):
        print(json.dumps({"ok": False, "tool": TOOL, "error": f"File not found: {a.app_file}"}))
        sys.exit(0)

    try:
        try:
            name, url = _deploy_via_sdk(a.app_file, a.app_name)
        except Exception:
            name, url = _deploy_via_cli(a.app_file, a.app_name)
        print(json.dumps({"ok": True, "tool": TOOL, "app_name": name, "url": url}))
    except Exception as e:
        print(json.dumps({"ok": False, "tool": TOOL, "error": str(e)}))

if __name__ == "__main__":
    main()
