#!/usr/bin/env python3
import argparse, json
try:
    import requests
except ImportError:
    import subprocess, sys; subprocess.check_call([sys.executable,"-m","pip","install","requests","-q"])
    import requests
def main():
    p = argparse.ArgumentParser()
    p.add_argument("--amount",type=float,required=True)
    p.add_argument("--from",dest="from_c",required=True)
    p.add_argument("--to",dest="to_c",required=True)
    a = p.parse_args()
    try:
        r = requests.get(f"https://open.er-api.com/v6/latest/{a.from_c.upper()}", timeout=10)
        data = r.json()
        if data.get("result") != "success": raise ValueError(data.get("error-type","API error"))
        rate = data["rates"][a.to_c.upper()]
        result = round(a.amount * rate, 6)
        print(json.dumps({"ok":True,"tool":"currency-convert","from":a.from_c,"to":a.to_c,"amount":a.amount,"result":result,"rate":rate}))
    except Exception as e: print(json.dumps({"ok":False,"tool":"currency-convert","error":str(e)}))
if __name__=="__main__": main()
