#!/usr/bin/env python3
import argparse, json, re
p = argparse.ArgumentParser()
p.add_argument("--colors", default="", help="Comma-separated hex colors to evaluate")
p.add_argument("--font", default="", help="Font name to evaluate")
p.add_argument("--layout", default="", help="Layout description")
a = p.parse_args()
findings = []
if a.colors:
    colors = [c.strip() for c in a.colors.split(",") if c.strip()]
    findings.append({"aspect": "color_palette", "count": len(colors), "note": "3-5 colors is ideal" if 2 <= len(colors) <= 5 else "consider simplifying"})
if a.font:
    system_fonts = ["inter", "system-ui", "helvetica", "georgia", "roboto", "sans-serif", "serif"]
    is_system = any(f in a.font.lower() for f in system_fonts)
    findings.append({"aspect": "typography", "font": a.font, "note": "good system font choice" if is_system else "ensure font is loaded"})
if a.layout:
    findings.append({"aspect": "layout", "description": a.layout[:100], "note": "evaluated"})
print(json.dumps({"ok": True, "tool": "design-taste", "findings": findings, "count": len(findings)}))
