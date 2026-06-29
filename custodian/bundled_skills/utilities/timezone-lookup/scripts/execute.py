#!/usr/bin/env python3
import argparse, json
from datetime import datetime
try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo
def main():
    p = argparse.ArgumentParser()
    p.add_argument("--datetime",required=True,dest="dt_str")
    p.add_argument("--from-tz",required=True)
    p.add_argument("--to-tz",required=True)
    a = p.parse_args()
    try:
        dt = datetime.fromisoformat(a.dt_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo(a.from_tz))
        converted = dt.astimezone(ZoneInfo(a.to_tz))
        print(json.dumps({"ok":True,"tool":"timezone-lookup","input":a.dt_str,"output":converted.isoformat(),"from_tz":a.from_tz,"to_tz":a.to_tz}))
    except Exception as e: print(json.dumps({"ok":False,"tool":"timezone-lookup","error":str(e)}))
if __name__=="__main__": main()
