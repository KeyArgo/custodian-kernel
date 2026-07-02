#!/usr/bin/env python3
import argparse, json, urllib.request
p = argparse.ArgumentParser()
p.add_argument("--ip", required=True)
a = p.parse_args()
try:
    with urllib.request.urlopen(f"https://ipapi.co/{a.ip}/json/", timeout=10) as r:
        d = json.loads(r.read())
    print(json.dumps({"ok": True, "tool": "ip-geolocation", "ip": a.ip,
        "country": d.get("country_name"), "region": d.get("region"),
        "city": d.get("city"), "org": d.get("org"), "latitude": d.get("latitude"), "longitude": d.get("longitude")}))
except Exception as e:
    print(json.dumps({"ok": False, "tool": "ip-geolocation", "ip": a.ip, "error": str(e)}))
