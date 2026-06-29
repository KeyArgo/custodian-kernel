#!/usr/bin/env python3
import argparse, base64, json, os, requests
def main():
    p = argparse.ArgumentParser(); p.add_argument("--repo",required=True); p.add_argument("--path",required=True); p.add_argument("--ref",default="main")
    a = p.parse_args()
    try:
        token = os.environ.get("GITHUB_TOKEN","")
        headers = {"Accept":"application/vnd.github+json"}
        if token: headers["Authorization"] = f"Bearer {token}"
        r = requests.get(f"https://api.github.com/repos/{a.repo}/contents/{a.path}", params={"ref":a.ref}, headers=headers, timeout=10)
        r.raise_for_status()
        data = r.json()
        content = base64.b64decode(data["content"]).decode("utf-8","replace") if data.get("encoding")=="base64" else data.get("content","")
        print(json.dumps({"ok":True,"tool":"github-file-read","repo":a.repo,"path":a.path,"content":content[:4000],"size":data.get("size",0)}))
    except Exception as e: print(json.dumps({"ok":False,"tool":"github-file-read","error":str(e)}))
if __name__=="__main__": main()
