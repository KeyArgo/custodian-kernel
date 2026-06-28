#!/usr/bin/env python3
import argparse, json, glob, os
def main():
    p = argparse.ArgumentParser(); p.add_argument("--path",required=True); p.add_argument("--pattern",default="*")
    a = p.parse_args()
    try:
        files = sorted(glob.glob(os.path.join(a.path, a.pattern)))
        print(json.dumps({"ok":True,"tool":"file-list","path":a.path,"files":files[:500],"count":len(files)}))
    except Exception as e: print(json.dumps({"ok":False,"tool":"file-list","error":str(e)}))
if __name__=="__main__": main()
