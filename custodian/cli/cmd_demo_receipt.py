"""custodian demo receipt — shows @govern decorator + GovernedReceipt."""
import json
import tempfile
import time
from pathlib import Path


def run(args):
    print("\n\033[1;36m╔══════════════════════════════════════════════════════════════╗")
    print("║       CUSTODIAN 0.2.0  —  @govern + GovernedReceipt          ║")
    print("╚══════════════════════════════════════════════════════════════╝\033[0m\n")

    # Step 1: define a governed function
    print("\033[1;33m[STEP 1] Define a @govern-wrapped function\033[0m")
    print("""
  from custodian import govern

  @govern(band="L2", cap=50.00)
  def charge_customer(amount: float, customer_id: str) -> dict:
      return {"charged": amount, "customer": customer_id, "status": "ok"}
""")

    from custodian import govern

    # Run in an isolated tempdir so a workspace policy.yaml with tight caps
    # doesn't interfere with the demo. The decorator's own cap=50.00 governs.
    with tempfile.TemporaryDirectory() as _demo_state:
        _demo_policy = Path(_demo_state) / "policy.yaml"
        _demo_policy.write_text(
            "version: '1.0'\ndefault_band: L2\nbands:\n"
            "  L2: {max_spend: 100.00, requires_approval: false}\nrules: []\n"
            "escalation: {timeout_seconds: 600, on_timeout: deny, retry_count: 0}\n"
        )

        @govern(band="L2", cap=50.00, state_dir=_demo_state,
                policy_path=str(_demo_policy))
        def charge_customer(amount: float, customer_id: str) -> dict:
            return {"charged": amount, "customer": customer_id, "status": "ok"}

        # Step 2: kernel evaluates and executes autonomously (within cap)
        print("\033[1;33m[STEP 2] KERNEL EVALUATES — amount=$25.00, cap=$50.00, band=L2\033[0m")
        t0 = time.monotonic()
        result = charge_customer(amount=25.00, customer_id="cus_abc123")
        elapsed = (time.monotonic() - t0) * 1000
        print(f"  verdict    : \033[1;32m{result.verdict.upper()}\033[0m  (autonomous — no human needed)")
        print(f"  audit_id   : {result.audit_id}")
        print(f"  elapsed_ms : {elapsed:.1f}")
        print(f"  value      : {result.value}\n")

        # Step 3: generate receipt
        print("\033[1;33m[STEP 3] RECEIPT GENERATED — SHA-256 fingerprinted proof artifact\033[0m")
        receipt = result.receipt()
        print(receipt.to_json())
        print()

        # Step 4: verify fingerprint
        print("\033[1;33m[STEP 4] VERIFY — recompute fingerprint, compare\033[0m")
        ok = receipt.verify()
        print(f"  receipt.verify() → \033[1;32m{ok}\033[0m  (fingerprint matches — receipt untampered)\n")
        assert ok, "Receipt verification failed"

        # Step 5: show what denied looks like (reuse the same isolated state dir,
        # just write a kill switch file into it)
        print("\033[1;33m[STEP 5] KILL SWITCH — denied verdict when kill_switch.json exists\033[0m")
        ks = Path(_demo_state) / "kill_switch.json"
        ks.write_text(json.dumps({"killed": True, "ts": time.time(), "reason": "demo"}))

        @govern(band="L2", cap=50.00, state_dir=_demo_state,
                policy_path=str(_demo_policy), raise_on_escalation=False)
        def blocked_charge(amount: float) -> dict:
            return {}

        denied = blocked_charge(amount=10.00)
        print(f"  verdict : \033[1;31m{denied.verdict.upper()}\033[0m")
        print(f"  ok      : {denied.ok}  ← function body never ran\n")

    print("\033[1;36m✓ All 5 steps passed — kernel fabric demonstrated\033[0m\n")
    print("  Key properties:")
    print("    • The function author wrote zero kernel code")
    print("    • The kernel is the call path — not a sidecar")
    print("    • Every execution produces a verifiable, tamper-evident receipt")
    print("    • Kill switch denies before the function body is reached")
    print()
