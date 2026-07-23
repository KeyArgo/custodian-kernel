#!/usr/bin/env python3
import argparse, json, os
CRONS = os.environ.get("CUSTODIAN_CRONS_PATH", os.path.expanduser("~/.custodian/crons.json"))
def main():
    p = argparse.ArgumentParser(); p.add_argument("--name",required=True)
    a = p.parse_args()
    try:
        crons = json.loads(open(CRONS).read()) if os.path.exists(CRONS) else []
        before = len(crons); crons = [c for c in crons if c.get("name")!=a.name]
        open(CRONS,"w").write(json.dumps(crons,indent=2))
        print(json.dumps({"ok":True,"tool":"cron-delete","deleted":a.name,"removed":before-len(crons)}))
    except Exception as e: print(json.dumps({"ok":False,"tool":"cron-delete","error":str(e)}))
if __name__=="__main__": main()
