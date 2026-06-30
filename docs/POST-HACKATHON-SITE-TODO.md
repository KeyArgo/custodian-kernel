# Post-Hackathon Site Updates

These were deliberately deferred past the June 30 deadline. Do these first when you come back.

---

## 1. Add `@govern` decorator section to landing page (HIGH — changes perception from tool → platform)

Add a code block section to `pages-frontend/index.html` between the hero and the "how it works" section showing:

```python
from custodian import govern

@govern(band="L2", cap=50.00)
def charge_customer(amount: float, customer_id: str) -> dict:
    return stripe.charge(amount=amount, customer=customer_id)

# Every caller is governed. The caller doesn't know Custodian exists.
result = charge_customer(85.00, "cus_123")
receipt = result.receipt()
receipt.verify()  # True — SHA-256 fingerprinted, tamper-evident
```

**Why it matters:** Judges and visitors who see a decorator immediately understand "platform", not "CLI tool". This is the single biggest perception shift available.

---

## 2. Update architecture diagram copy

Current copy describes the 2-layer model (Hermes agent + Custodian kernel) as two separate things.

Update to show 3 entry points into the kernel:
- `@govern` decorator (any Python function)
- `CustodianMiddleware` (any FastAPI/Flask route)
- `CustodianSession` (any bounded execution context)

All three route through the same `decide()` evaluator.

---

## 3. Add `CustodianMiddleware` FastAPI example

```python
from fastapi import FastAPI
from custodian.middleware import CustodianMiddleware

app = FastAPI()
app.add_middleware(CustodianMiddleware, policy="policy.yaml")
app.state.custodian.register_path("/charge", band="L2", cap=50.00)

# Now /charge returns 402 before your handler runs if amount > cap
# No kernel code in your handler. Zero.
```

---

## 4. Update Quick Start on docs.html

Add 0.2.0 path showing `@govern` not just `custodian request`.

---

## 5. Update README in repo

Section "Custodian 0.2.0 — kernel as fabric" with the decorator pattern, receipt example, and middleware mount.

---

## 6. Delete PyPI 0.1.0

`pypi.org` → Manage → custodian-kernel → Delete version 0.1.0  
**Reason:** Has private LAN IP (10.0.0.199) baked in from early dev.

---

## 7. Publish PyPI 0.2.0

Current published version: 0.1.2  
Repo is at: 0.2.0  
Command: `python3 -m twine upload dist/*` (needs PYPI_TOKEN)
