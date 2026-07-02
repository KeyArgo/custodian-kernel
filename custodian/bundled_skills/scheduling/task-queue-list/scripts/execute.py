#!/usr/bin/env python3
import argparse, json, os
QUEUE = os.environ.get("CUSTODIAN_QUEUE_PATH", os.path.expanduser("~/.custodian/queue.json"))
def main():
    p = argparse.ArgumentParser(); p.add_argument("--status",default="all")
    a = p.parse_args()
    try:
        try: tasks = json.loads(open(QUEUE).read())
        except: tasks = []
        if a.status != "all": tasks = [t for t in tasks if t.get("status")==a.status]
        print(json.dumps({"ok":True,"tool":"task-queue-list","tasks":tasks,"count":len(tasks)}))
    except Exception as e: print(json.dumps({"ok":False,"tool":"task-queue-list","error":str(e)}))
if __name__=="__main__": main()
