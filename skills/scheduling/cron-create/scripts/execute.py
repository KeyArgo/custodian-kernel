#!/usr/bin/env python3
import argparse, json, os
from datetime import datetime, timezone
CRONS = os.environ.get("CUSTODIAN_CRONS_PATH", os.path.expanduser("~/.custodian/crons.json"))
def load():
    os.makedirs(os.path.dirname(CRONS), exist_ok=True)
    try: return json.loads(open(CRONS).read())
    except: return []
def main():
    p = argparse.ArgumentParser()
    p.add_argument("--name",required=True); p.add_argument("--schedule",required=True); p.add_argument("--command",required=True)
    a = p.parse_args()
    try:
        crons = [c for c in load() if c.get("name")!=a.name]
        crons.append({"name":a.name,"schedule":a.schedule,"command":a.command,"created_at":datetime.now(timezone.utc).isoformat()})
        open(CRONS,"w").write(json.dumps(crons,indent=2))
        print(json.dumps({"ok":True,"tool":"cron-create","name":a.name,"schedule":a.schedule}))
    except Exception as e: print(json.dumps({"ok":False,"tool":"cron-create","error":str(e)}))
if __name__=="__main__": main()
