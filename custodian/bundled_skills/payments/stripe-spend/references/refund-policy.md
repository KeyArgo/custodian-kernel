# Refund Policy

Use this policy to evaluate customer refund requests. You may recommend
approve, deny, or escalate-as-ambiguous -- but regardless of your
recommendation, the only way money ever actually moves back to a customer
is through `scripts/refund.py`, which always requires real human approval
via Twilio Verify, with no exceptions, no matter what you decide here.
Your job is to do the reading and reasoning so the human's decision takes
seconds instead of minutes.

## Standard window

Refunds are approvable within **30 days of purchase**, no questions asked,
as long as the product was not a consumed/used digital license key.

## Exceptions (approvable even outside the 30-day window)

- **Defect**: the product did not work as described and the customer
  reported it within a reasonable time of discovering the defect.
- **Non-delivery**: the customer never received the product/service at all.
- **Billing error**: the customer was charged the wrong amount, charged
  twice, or charged for something they did not order.

## Deny (do not call refund.py at all -- this never touches money)

- Outside the 30-day window with no defect, non-delivery, or billing
  error claimed or evidenced.
- The customer used/consumed the product fully before requesting a refund
  with no quality complaint.

## Flag for review (do not call refund.py -- explain the suspicion instead)

- Multiple refund requests from the same customer in a short window.
- A request that cites a defect or non-delivery claim inconsistent with
  the account's own usage history (e.g., claims non-delivery but the
  product was actively used after the purchase date).

## Escalate as genuinely ambiguous

- You cannot confidently place the request in approve, deny, or flag
  based on the information given. Call refund.py anyway (it always goes
  to a human either way), but state plainly in your reasoning what's
  uncertain and what additional information would resolve it. Do not
  guess confidently when you are not confident.
