#!/usr/bin/env python3
import argparse, json, os, uuid
from datetime import datetime, timezone
QUEUE = os.environ.get("CUSTODIAN_QUEUE_PATH", os.path.expanduser("~/.custodian/queue.json"))
def load():
    os.makedirs(os.path.dirname(QUEUE), exist_ok=True)
    try: return json.loads(open(QUEUE).read())
    except: return []
def main():
    p = argparse.ArgumentParser()
    p.add_argument("--task",required=True); p.add_argument("--run-at"); p.add_argument("--tool")
    a = p.parse_args()
    try:
        q = load()
        entry = {"id":str(uuid.uuid4())[:8],"task":a.task,"status":"pending","created_at":datetime.now(timezone.utc).isoformat(),"run_at":a.run_at,"tool":a.tool}
        q.append(entry); open(QUEUE,"w").write(json.dumps(q,indent=2))
        print(json.dumps({"ok":True,"tool":"task-queue-add","id":entry["id"],"task":a.task}))
    except Exception as e: print(json.dumps({"ok":False,"tool":"task-queue-add","error":str(e)}))
if __name__=="__main__": main()
