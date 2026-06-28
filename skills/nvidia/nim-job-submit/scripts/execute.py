#!/usr/bin/env python3
import argparse, json, os, requests
def main():
    p = argparse.ArgumentParser()
    p.add_argument("--model",default="meta/llama-3.1-8b-instruct")
    p.add_argument("--prompt",required=True)
    p.add_argument("--max-tokens",type=int,default=256,dest="max_tokens")
    a = p.parse_args()
    key = os.environ.get("NVIDIA_API_KEY","")
    if not key:
        print(json.dumps({"ok":False,"stub":True,"tool":"nim-job-submit","message":"Set NVIDIA_API_KEY to enable"})); return
    try:
        r = requests.post("https://integrate.api.nvidia.com/v1/chat/completions",
            headers={"Authorization":f"Bearer {key}"},
            json={"model":a.model,"messages":[{"role":"user","content":a.prompt}],"max_tokens":a.max_tokens},
            timeout=60)
        result = r.json()
        content = result["choices"][0]["message"]["content"]
        print(json.dumps({"ok":True,"tool":"nim-job-submit","model":a.model,"output":content,"usage":result.get("usage")}))
    except Exception as e: print(json.dumps({"ok":False,"tool":"nim-job-submit","error":str(e)}))
if __name__=="__main__": main()
