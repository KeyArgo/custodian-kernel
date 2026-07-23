#!/usr/bin/env python3
import argparse, json
p = argparse.ArgumentParser()
p.add_argument("--input", required=True, help="Design element or UI description to evaluate")
a = p.parse_args()
criteria = ["clarity", "consistency", "accessibility", "visual_hierarchy", "whitespace"]
scores = {c: 0 for c in criteria}
text = a.input.lower()
if any(w in text for w in ["clear", "simple", "clean"]): scores["clarity"] = 1
if any(w in text for w in ["consistent", "uniform", "aligned"]): scores["consistency"] = 1
if any(w in text for w in ["accessible", "contrast", "aria", "screen reader"]): scores["accessibility"] = 1
if any(w in text for w in ["header", "hierarchy", "heading", "h1", "h2"]): scores["visual_hierarchy"] = 1
if any(w in text for w in ["spacing", "padding", "margin", "whitespace"]): scores["whitespace"] = 1
score = sum(scores.values())
print(json.dumps({"ok": True, "tool": "design-impeccable", "input": a.input[:100],
    "score": score, "max": len(criteria), "criteria": scores,
    "verdict": "excellent" if score >= 4 else "good" if score >= 2 else "needs work"}))
