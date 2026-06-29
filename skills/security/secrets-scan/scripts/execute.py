#!/usr/bin/env python3
import argparse, json, re
PATTERNS = {
    "aws_key": r"AKIA[0-9A-Z]{16}",
    "stripe_secret": r"sk_(live|test)_[a-zA-Z0-9_]{20,}",
    "stripe_publishable": r"pk_(live|test)_[a-zA-Z0-9_]{20,}",
    "github_token": r"gh[pousr]_[A-Za-z0-9_]{36,}",
    "openai_key": r"sk-[a-zA-Z0-9_-]{32,}",
    "private_key": r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----",
    "password_assign": r"(?i)(password|passwd|pwd)\s*[:=]\s*['\"]?[^\s'\"]{6,}",
    "generic_secret": r"(?i)(secret|api[_-]?key|token)\s*[:=]\s*['\"]?[a-zA-Z0-9+/_-]{12,}",
}
p = argparse.ArgumentParser()
p.add_argument("--text", required=True)
a = p.parse_args()
findings = []
for name, pat in PATTERNS.items():
    for m in re.finditer(pat, a.text):
        findings.append({"type": name, "match": m.group()[:40] + ("..." if len(m.group()) > 40 else ""), "pos": m.start()})
print(json.dumps({"ok": True, "tool": "secrets-scan", "findings": findings, "count": len(findings), "clean": len(findings) == 0}))
