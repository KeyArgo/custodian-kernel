"""Setup-profile metadata for the kernel's entry-point discovery.

Shapes must match exactly what the kernel expects:
  - ``COMPONENT``: {"description": str, "pip_spec": str | None}
  - ``PROFILE_COMPONENTS``: list[str] of component names
"""

COMPONENT = {
    "description": "Stripe payment-processor adapter — real charges/refunds/payouts via the Stripe API",
    "pip_spec": "custodian-stripe>=0.1.0,<0.2",
}

PROFILE_COMPONENTS = ["stripe"]
