# Hackathon Fast-Comprehension Spec

_Last updated: 2026-06-30_

## Goal

The site has one real job in the hackathon:

**help a new visitor understand what Custodian is, why it matters, and what proof they should look at next.**

Everything else is secondary.

This means the product site should optimize for:

1. fast understanding
2. guided proof
3. business relevance
4. deeper exploration after the core idea lands

Not for:

1. maximum feature exposure up front
2. freeform browsing as the primary mode
3. making the AI feel omnipresent for its own sake

## Core narrative

The visitor should understand this in under a minute:

1. AI can make judgments about money.
2. That is dangerous unless a separate deterministic layer controls execution.
3. Custodian is that layer.
4. The model can request.
5. The kernel decides.
6. Humans are required only when the request crosses the boundary.

Short version:

**Custodian is the layer that lets you give an AI agent a real budget without trusting the AI itself.**

## Primary journey

This is the intended hackathon path:

1. Home
2. Console
3. Operator
4. Back to Console
5. Triage
6. Tools
7. Docs

But the site should mentally frame those as:

1. Understand
2. Watch proof
3. Interpret proof
4. Explore deeper

## Page roles

### Home

Purpose:
- orient the visitor
- make the big idea legible
- send them to the best next page

Required outcome:
- user knows this is not “AI payments”
- user knows this is “AI plus a separate enforcement layer”
- user knows the next click should usually be Console

Home should answer:
- What is Custodian?
- Why does this matter?
- What should I do next?

Home should not try to tell the entire story.

### Console

Purpose:
- primary explanation surface
- best “start here” page

Required outcome:
- user understands the 6-step explanation
- user understands the relationship between AI, kernel, human approval, and audit
- user is ready to open Operator

Console is the main guided-tour page.

### Operator

Purpose:
- live proof surface
- hands-on demonstration

Required outcome:
- user sees real actions happen
- user feels the system is real
- user completes the proof arc

Operator should not carry the burden of explaining the whole product from scratch.
It is a proof chapter, not the best orientation chapter.

### Back to Console

Purpose:
- interpret what just happened
- connect proof to meaning

Required outcome:
- user sees the exact audit entries
- user understands what the kernel policy log proves
- user sees that the operator actions were not fake theater

This return trip is critical.

### Triage

Purpose:
- show why the verifier matters
- prove that the AI alone is not the product

Required outcome:
- user understands lie-catching as a business-critical property
- user sees why deterministic verification changes deployment trust

### Tools

Purpose:
- expand the scope
- answer “what else can this govern?”

Required outcome:
- user understands this is a general authority layer, not a one-off payments demo

### Docs

Purpose:
- deep dive
- satisfy technical curiosity

Required outcome:
- user can self-serve details without needing the tour

## AI assistant role

The AI is not primarily a chatbot.

For the hackathon, the AI is:

**a guided explainer and proof interpreter**

That means:
- explain first
- narrate transitions
- stay quiet during dense interaction
- come back at milestones

The AI should avoid:
- talking constantly
- asking open-ended questions too early
- acting like generic website chat support

## Recommended assistant behavior

### Desktop

#### Home
- no full-screen blocking popup
- soft invite after engagement, not just time
- trigger heuristic:
  - 45 to 60 seconds on page, or
  - meaningful scroll, or
  - idle after reading hero
- message should be simple:
  - “Want the quickest explanation? Start with the live console.”

#### Console
- this is where the AI becomes active
- walk through the 6-step “how this works” explanation
- then recommend opening Operator

#### Operator
- AI arrives with prior context
- knows the user is now in proof mode
- mostly stays quiet during steps 0 through 8
- only interrupts for:
  - explicit question
  - failure/error
  - major milestone
- after final refund approval:
  - invite user back to Console
  - explicitly say the next interesting thing is the audit trail

#### Back to Console
- highlight exact entries
- explain what each means
- show kernel policy
- invite “try it yourself”

#### Triage
- explain why this matters for real business deployment

#### Tools
- spotlight a few high-value examples
- explain how the list generalizes the core idea

#### Docs
- close with technical depth and self-serve reading

### Mobile

Rule:

**never auto-open a blocking assistant panel**

Instead:
- show a small bubble or compact banner
- greeting only
- user must opt in

Suggested copy:
- “Hi, I’m Nemotron. Feel free to ask any questions.”

The mobile assistant should be:
- non-blocking
- dismissible
- reopenable

## Tour structure

### Step 1: Understand

Start on Console.

AI explains:
- AI decides
- kernel enforces
- human signs off only when needed
- audit trail proves what happened

### Step 2: Watch proof

Move to Operator.

User runs:
- earn
- autonomous spend
- over-cap escalation
- SMS approval
- kill switch
- denial under kill switch
- release
- refund
- refund approval

### Step 3: Interpret proof

Return to Console.

AI highlights:
- the exact audit records
- the kernel policy trail
- what those records prove

### Step 4: Explore deeper

Then:
- Triage for lie-catch
- Tools for scope
- Docs for detail

## Design principles

1. One primary story at a time.
2. Explanation before proof.
3. Proof before breadth.
4. Business meaning before feature inventory.
5. AI should guide the visitor, not compete with the interface.

## Product voice

The site can be excited, but should not feel sloppy.

Good tone:
- direct
- impressed by the proof
- technically grounded
- slightly dramatic when deserved

Bad tone:
- generic chatbot politeness
- too many choices too early
- hype that outruns the artifact

## Implementation priorities

### Priority 1
- Make Console the explicit “start here” explanation page.
- Make Operator a proof page with a return-to-Console handoff.

### Priority 2
- Unify assistant continuity across Console, Operator, and Triage.
- Standardize history and tour state storage.

### Priority 3
- Add lightweight guided assistant presence to Tools and Docs.

### Priority 4
- Rework the current console flow chart so it supports the guided tour instead of only explaining architecture.

## Success criteria

A first-time hackathon judge should be able to say, after a short visit:

1. “I understand what this product is.”
2. “I understand what part is AI and what part is deterministic.”
3. “I saw real proof.”
4. “I understand why this matters for real businesses.”

If those four things happen, the site is doing its job.

