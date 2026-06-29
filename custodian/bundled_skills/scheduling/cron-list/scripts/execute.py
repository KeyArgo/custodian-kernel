#!/usr/bin/env python3
import json, os
CRONS = os.environ.get("CUSTODIAN_CRONS_PATH", os.path.expanduser("~/.custodian/crons.json"))
try: crons = json.loads(open(CRONS).read()) if os.path.exists(CRONS) else []
except: crons = []
print(json.dumps({"ok":True,"tool":"cron-list","crons":crons,"count":len(crons)}))
