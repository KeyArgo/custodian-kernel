#!/usr/bin/env python3
import json, os, requests
key = os.environ.get("NVIDIA_API_KEY","")
if not key:
    print(json.dumps({"ok":False,"stub":True,"tool":"nim-model-list","message":"Set NVIDIA_API_KEY to enable"}))
else:
    try:
        r = requests.get("https://integrate.api.nvidia.com/v1/models", headers={"Authorization":f"Bearer {key}"}, timeout=15)
        models = [m["id"] for m in r.json().get("data",[])]
        print(json.dumps({"ok":True,"tool":"nim-model-list","models":models,"count":len(models)}))
    except Exception as e: print(json.dumps({"ok":False,"tool":"nim-model-list","error":str(e)}))
