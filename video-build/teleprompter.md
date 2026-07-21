# CUSTODIAN — Voiceover Teleprompter
# OpenAI Devpost Hackathon — Build Week 2026
# Target video length: 170s (2:50). Voice time: ~95s. Silence: ~75s.
# Print this (or load on your phone). Read aloud at a natural pace (~150 wpm).
# Each block is separated by a blank line and tagged with the segment name + timing.
# Do NOT read the tags — read only the voiceover text.
# Record in a single take. Pauses are marked with [pause]. Silences are marked with [silence Xs].

---

[DANGER — 0.5 → 12.0]

AI agents are running code on real systems. A single bad command can delete data, leak secrets, or move money. Prompt instructions cannot reliably stop that.

[pause 0.4s]

---

[INTRODUCE CUSTODIAN — 13.0 → 30.0]

Custodian is a safety kernel between AI agents and the tools they use. It evaluates every action before the action reaches the system. The agent proposes. Custodian decides.

[silence 0.5s]

---

[THE 3-DECISION LIVE DEMO — 31.0 → 85.0]

A read-only inspection is allowed. A production-touching command is held for human approval. A destructive command is blocked before execution. Every decision is recorded in an HMAC hash-chained audit log.

[silence 0.5s]

---

[WHAT MAKES IT TECHNICALLY DIFFERENT — 86.0 → 115.0]

Custodian is agent-independent. Enforcement happens at the tool boundary, outside the acting agent. The same protection works across coding agents, infrastructure agents, and credential brokers.

[silence 0.5s]

---

[CODEX & GPT-5.6 — 116.0 → 140.0]

I used Codex with GPT-5.6 to build this during OpenAI Build Week. Codex implemented the policy bridge, the MCP server, and the seven dedicated test files. It adversarially tested the false-positive rate. GPT-5.6 powers the contextual risk analysis; deterministic rules keep final control over prohibited actions.

[silence 0.5s]

---

[PROOF IT WORKS — 141.0 → 155.0]

The same scenarios are covered by automated tests. Every decision is auditable, cryptographically chained, and cannot be forged.

[silence 0.5s]

---

[CLOSE — 156.0 → 170.0]

[NO VOICEOVER. Silent slides. Read nothing.]

---

# RECORDING INSTRUCTIONS
#
# 1. Load this file on your phone or print it.
# 2. Sit in a quiet room. Phone on airplane mode.
# 3. Record on a separate device (phone voice recorder, lav mic, whatever).
# 4. Read each block in order. Keep the [pause] tags as ~0.3-0.5s pauses.
# 5. The [silence] tags are dead air between segments — don't speak during them.
# 6. After each block, take a breath. The blocks will be split and timed in post.
# 7. Total reading time target: ~95 seconds of voice. The rest is silence on screen.
# 8. Don't read the tags. Read the voiceover text only.
# 9. Record the whole thing as a single file. I'll split it.
#
# Once recorded, place the file as:
#   video-build/voiceover-raw.wav
#
# Then run:
#   cd video-build/
#   ./assemble.sh
#
# You'll also need:
#   video-build/screen-capture.mp4   (OBS recording, 1920x1080, 30fps)
#   video-build/slides/              (3 PNG files — produced by build_captions.py)
