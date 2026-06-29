#!/usr/bin/env python3
import argparse, json, subprocess
def main():
    p = argparse.ArgumentParser(); p.add_argument("--container",required=True)
    a = p.parse_args()
    try:
        r = subprocess.run(["docker","start",a.container], capture_output=True, text=True, timeout=30)
        print(json.dumps({"ok":r.returncode==0,"tool":"docker-start","container":a.container}))
    except Exception as e: print(json.dumps({"ok":False,"tool":"docker-start","error":str(e)}))
if __name__=="__main__": main()
