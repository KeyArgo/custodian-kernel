# What This Unlocks — Beyond One Homelab

Custodian is the engine. The ops-officer demo (real ArgoBox infrastructure, real
judgment, real spend) is one instance of a pattern, not the product itself. The pattern
is: **bounded authority + structural enforcement + human escalation** — and it
generalizes to any situation where an AI agent needs real authority over real
operations, not just infrastructure monitoring.

These are concrete shapes of business this pattern unlocks. None are built — naming
them is the point: each is the kind of thing that's genuinely risky to turn on today
*because* the trust problem is unsolved, and genuinely viable the moment it is.

## 1. AI Bookkeeper-on-a-Budget

Pays a small business's recurring vendor bills — hosting, SaaS subscriptions, domain
renewals — autonomously, up to a cap. Anything unusual escalates via a real text to the
owner. The owner can kill-switch it instantly if something looks wrong.

**Why the trust problem is the blocker, not the AI:** an agent that can read invoices
and decide what to pay already exists in pieces. What doesn't exist is a safe way to
let it actually press "pay" without someone watching every transaction — which means
today it either doesn't get real authority (so it's not actually useful) or it gets
real authority with no enforced boundary (so no rational business turns it on).

## 2. AI Procurement Agent for SMBs

Negotiates and pays for supplies or services within a budget. Refuses purchases that
don't match the stated business need — the same "narrated crisis vs. real telemetry"
judgment already proven in the ops-officer demo, just pointed at purchase requests
instead of infrastructure alerts. Escalates anything large to a human.

## 3. AI Ops/Infra Guardian for Solo Founders

This is the existing ops-officer demo, reframed correctly: one example of the pattern,
not the whole pitch. Monitors infrastructure, spends autonomously on small fixes,
escalates and can be kill-switched for anything bigger.

## 4. AI Grants/Reimbursement Officer

Reviews and pays expense reimbursements, or accepts and files small grant
disbursements, within policy — for a small nonprofit or a distributed team that can't
afford a dedicated finance person. Escalates anything outside normal patterns.

## 5. AI Refund/Support Agent

Issues real refunds for a business autonomously, within a cap — genuinely useful, real
financial stakes, real Stripe calls. Escalates anything large or suspicious.
Kill-switchable the moment it starts behaving wrong.

## The actual claim

None of these are hypothetical because the underlying mechanism is missing — agents
that read, reason, and decide already exist. They're hypothetical because nobody can
hand one of them a real budget and trust the consequences are bounded. That's the
specific, narrow thing Custodian solves, and it's the same solution underneath all five
of these, not five different products.
