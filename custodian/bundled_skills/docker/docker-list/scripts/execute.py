#!/usr/bin/env python3
import argparse, json, subprocess
def main():
    p = argparse.ArgumentParser(); p.add_argument("--all",action="store_true")
    a = p.parse_args()
    try:
        cmd = ["docker","ps","--format","{{json .}}"] + (["--all"] if a.all else [])
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if r.returncode != 0: raise RuntimeError(r.stderr.strip() or "docker error")
        containers = [json.loads(line) for line in r.stdout.strip().splitlines() if line.strip()]
        print(json.dumps({"ok":True,"tool":"docker-list","containers":containers,"count":len(containers)}))
    except FileNotFoundError: print(json.dumps({"ok":False,"tool":"docker-list","error":"docker not in PATH"}))
    except Exception as e: print(json.dumps({"ok":False,"tool":"docker-list","error":str(e)}))
if __name__=="__main__": main()
