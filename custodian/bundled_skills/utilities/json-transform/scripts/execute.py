#!/usr/bin/env python3
import argparse, json, re
def walk(data, path):
    if path.strip() == ".": return data
    parts = re.split(r"(?=\[|\.(?!\d))", path.lstrip("."))
    result = data
    for part in parts:
        part = part.lstrip(".")
        if not part: continue
        m = re.match(r"^([^[]*)\[(\d+)\]$", part)
        if m:
            key, idx = m.group(1), int(m.group(2))
            if key: result = result[key]
            result = result[idx]
        else:
            result = result[part]
    return result
def main():
    p = argparse.ArgumentParser(); p.add_argument("--input",required=True); p.add_argument("--filter",default=".")
    a = p.parse_args()
    try:
        data = json.loads(a.input)
        result = walk(data, a.filter)
        print(json.dumps({"ok":True,"tool":"json-transform","result":result}))
    except Exception as e: print(json.dumps({"ok":False,"tool":"json-transform","error":str(e)}))
if __name__=="__main__": main()
