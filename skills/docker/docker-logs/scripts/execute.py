#!/usr/bin/env python3
import argparse, json, subprocess
def main():
    p = argparse.ArgumentParser(); p.add_argument("--container",required=True); p.add_argument("--lines",type=int,default=50)
    a = p.parse_args()
    try:
        r = subprocess.run(["docker","logs","--tail",str(a.lines),a.container], capture_output=True, text=True, timeout=15)
        print(json.dumps({"ok":r.returncode==0,"tool":"docker-logs","container":a.container,"logs":r.stdout[:3000]}))
    except FileNotFoundError: print(json.dumps({"ok":False,"tool":"docker-logs","error":"docker not in PATH"}))
    except Exception as e: print(json.dumps({"ok":False,"tool":"docker-logs","error":str(e)}))
if __name__=="__main__": main()
