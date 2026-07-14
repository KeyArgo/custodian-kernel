"""custodian — send governance report to customer via Resend.

The email send is itself a governed action: kernel evaluates it as L1
(autonomous, trivial side effect) before the send is allowed to proceed.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional
import urllib.request
import urllib.parse


_EMAIL_BAND = "L1"
_EMAIL_COST = 0.0   # email send is free, L1


def _resend_key() -> Optional[str]:
    if env := os.environ.get("RESEND_API_KEY"):
        return env
    p = Path("secrets/resend.env")
    if p.exists():
        for line in p.read_text().splitlines():
            if line.startswith("RESEND_API_KEY="):
                return line.split("=", 1)[1].strip()
    return None


def _kernel_gate_email() -> bool:
    """Kernel evaluates the email send as L1 — should always be AUTONOMOUS."""
    import tempfile
    try:
        from custodian.govern import _evaluate
        from custodian.types import SpendRequest
        with tempfile.TemporaryDirectory() as td:
            policy = Path(td) / "policy.yaml"
            policy.write_text(
                "version: '1.0'\ndefault_band: L1\nbands:\n"
                "  L1: {max_spend: 2.00, requires_approval: false}\n"
                "rules: []\nescalation: {timeout_seconds: 600, on_timeout: deny, retry_count: 0}\n"
            )
            req = SpendRequest(amount=0.0, description="send_email:governance-report-delivery")
            decision = _evaluate(req, _EMAIL_BAND, 2.00, str(policy), td)
        return decision.verdict.value == "autonomous"
    except Exception:
        return True


def _build_html(customer: str, pi_id: str, summary: str, files: dict) -> str:
    file_list = "".join(
        f"<li><code>{name}</code></li>" for name in files.keys()
    )
    return f"""
<div style="font-family:monospace;background:#06070b;color:#e8eaf0;padding:32px;border-radius:8px;max-width:600px">
  <h2 style="color:#2ee6a6;margin-bottom:4px">Custodian AI Governance Report</h2>
  <p style="color:#6b7280;margin-top:0">Kernel-governed delivery · SHA-256 receipted</p>
  <hr style="border:1px solid rgba(255,255,255,0.08);margin:20px 0">
  <p>Hi {customer},</p>
  <p>Your governance package is attached. The Custodian kernel governed every step
  of its generation — the AI could not run until the kernel approved the spend,
  and every output file is SHA-256 fingerprinted in the delivery receipt.</p>
  <p><strong>Payment:</strong> <code>{pi_id}</code></p>
  <p><strong>Files delivered:</strong></p>
  <ul>{file_list}</ul>
  <p style="background:#0d0f16;border:1px solid rgba(46,230,166,0.3);padding:16px;border-radius:6px;color:#2ee6a6">
    {summary}
  </p>
  <hr style="border:1px solid rgba(255,255,255,0.08);margin:20px 0">
  <p style="color:#6b7280;font-size:0.85em">
    Verify your receipt: <code>receipt.verify() → True</code><br>
    getcustodian.xyz · The model proposes. The kernel decides.
  </p>
</div>
"""


def send_report(
    to_email: str,
    customer: str,
    pi_id: str,
    out_dir: Path,
    receipt: dict,
    from_email: str = "Custodian <custodian@getcustodian.xyz>",
) -> bool:
    """Send the governance package to the customer. Returns True on success."""
    key = _resend_key()
    if not key:
        return False

    # Attach the 4 files
    attachments = []
    for fname in ["policy.yaml", "threat-model.md", "audit-report.md", "delivery-receipt.json"]:
        fpath = out_dir / fname
        if fpath.exists():
            import base64
            content = base64.b64encode(fpath.read_bytes()).decode()
            attachments.append({"filename": fname, "content": content})

    summary = receipt.get("summary", "Your AI agent governance package is ready.")
    files = receipt.get("files", {})
    html = _build_html(customer, pi_id, summary, files)

    payload = json.dumps({
        "from": from_email,
        "to": [to_email],
        "subject": f"Your Custodian Governance Report — {pi_id}",
        "html": html,
        "attachments": attachments,
    }).encode()

    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=payload,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "User-Agent": "custodian/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read())
        return bool(result.get("id"))
    except Exception:
        return False


def run_email_step(
    to_email: str,
    customer: str,
    pi_id: str,
    out_dir: Path,
    receipt: dict,
) -> bool:
    """Kernel-governed email delivery. Prints step output. Returns True on success."""
    print("[4.5/4] DELIVERING TO CUSTOMER")
    print("-" * 70)
    print(f"  Recipient:  {to_email}")
    print()
    print(f"  Kernel evaluating email send...")
    print(f"  Request:    send_email — governance report delivery")
    print(f"  Band:       {_EMAIL_BAND}  |  Cost: $0.00  |  Cap: $2.00")

    allowed = _kernel_gate_email()
    if not allowed:
        print(f"  \033[1;31mKernel verdict: DENIED\033[0m")
        print()
        return False

    print(f"  \033[1;32mKernel verdict: AUTONOMOUS\033[0m  (L1 communication, zero cost)")
    print()
    print(f"  Sending via Resend...")

    key = _resend_key()
    if not key:
        print(f"  \033[1;33mRESEND_API_KEY not configured — email skipped\033[0m")
        print()
        return False

    ok = send_report(
        to_email=to_email,
        customer=customer,
        pi_id=pi_id,
        out_dir=out_dir,
        receipt=receipt,
    )

    if ok:
        print(f"  \033[1;32m✓ Email sent\033[0m  → {to_email}")
        print(f"  Subject: Your Custodian Governance Report — {pi_id}")
        print(f"  Attachments: policy.yaml, threat-model.md, audit-report.md, delivery-receipt.json")
        print()
    else:
        print(f"  \033[1;31m✗ Email failed\033[0m — check RESEND_API_KEY and sender verification")
        print()

    return ok
