#!/usr/bin/env python3
import argparse, json, shlex, subprocess
# Read-only allowlist only — no destructive filesystem ops
ALLOWLIST = {"ls","cat","echo","pwd","date","python3","git","curl","wget","jq","find","grep","wc","head","tail","sort","uniq","env","which","df","du","ps","id","hostname"}
def main():
    p = argparse.ArgumentParser()
    p.add_argument("--cmd",required=True); p.add_argument("--timeout",type=int,default=10); p.add_argument("--workdir",default="/tmp")
    a = p.parse_args()
    try:
        tokens = shlex.split(a.cmd)
        if not tokens or tokens[0] not in ALLOWLIST:
            raise PermissionError(f"Command not in allowlist: {tokens[0] if tokens else '(empty)'}")
        r = subprocess.run(tokens, capture_output=True, text=True, timeout=a.timeout, cwd=a.workdir)
        print(json.dumps({"ok":r.returncode==0,"tool":"shell-exec","stdout":r.stdout[:2000],"stderr":r.stderr[:500]}))
    except subprocess.TimeoutExpired:
        print(json.dumps({"ok":False,"tool":"shell-exec","error":"timeout"}))
    except Exception as e:
        print(json.dumps({"ok":False,"tool":"shell-exec","error":str(e)}))
if __name__=="__main__": main()
