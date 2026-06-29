#!/usr/bin/env python3
import argparse, base64, json
def main():
    p = argparse.ArgumentParser(); p.add_argument("--input",required=True)
    a = p.parse_args()
    try:
        # fix padding
        s = a.input.strip(); s += "=" * ((4 - len(s) % 4) % 4)
        decoded = base64.b64decode(s).decode("utf-8","replace")
        print(json.dumps({"ok":True,"tool":"base64-decode","decoded":decoded}))
    except Exception as e: print(json.dumps({"ok":False,"tool":"base64-decode","error":str(e)}))
if __name__=="__main__": main()
