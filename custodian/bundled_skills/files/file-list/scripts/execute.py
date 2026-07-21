#!/usr/bin/env python3
import argparse, json, glob, os
ALLOWED = os.environ.get("CUSTODIAN_ALLOWED_READ_DIR", "/tmp")
def main():
    p = argparse.ArgumentParser(); p.add_argument("--path",required=True); p.add_argument("--pattern",default="*")
    a = p.parse_args()
    try:
        real = os.path.realpath(a.path)
        allowed_real = os.path.realpath(ALLOWED)
        if real != allowed_real and not real.startswith(allowed_real + os.sep):
            raise PermissionError(f"Path must be under {ALLOWED}")
        # A pattern like "../../etc/*" would escape --path's own directory
        # even though --path itself passed the check above -- glob() joins
        # the two and resolves the traversal. Reject any match that lands
        # outside the allowed root, the same boundary check as above.
        files = []
        for match in glob.glob(os.path.join(a.path, a.pattern)):
            match_real = os.path.realpath(match)
            if match_real == allowed_real or match_real.startswith(allowed_real + os.sep):
                files.append(match)
        files.sort()
        print(json.dumps({"ok":True,"tool":"file-list","path":a.path,"files":files[:500],"count":len(files)}))
    except Exception as e: print(json.dumps({"ok":False,"tool":"file-list","error":str(e)}))
if __name__=="__main__": main()
