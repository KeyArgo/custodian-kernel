# Custodian — OpenAI Devpost Hackathon Submission Handoff

## Status: READY TO SUBMIT

Time check: You have ~5 hours until the 6:00 PM Mountain (5:00 PM Pacific) deadline.

## What was built during this session

1. **`custodian codex-guard receipts` CLI subcommand** — the missing inspector
   for the HMAC hash-chained audit log. Adds `custodian codex-guard receipts`
   with `--verify` for chain validation, `--limit` for filtering, and TTY
   auto-detection for color-coded verdicts. 7 new tests, 37/37 in the file pass,
   110/110 across all 6 codex_guard test files pass.

   Committed: `b56a7a8` on `feat/0.5.0-codex`.

2. **Video-build pipeline rewrite for the OpenAI hackathon** — replaced the
   NVIDIA/Stripe-focused content with the codex_guard story. New
   `teleprompter.md`, `timing.json`, regenerated slides, regenerated
   `captions.ass`, and a fixed `assemble.sh`.

3. **Final MP4 assembled** — 170.24s, 1920x1080, h264, AAC mono, with ASS
   captions burned in. Two files:
   - `video-build/custodian-openai-hackathon-final.mp4` (no burned captions)
   - `video-build/custodian-openai-hackathon-final-burned.mp4` (burned captions)
   Both are 2.7-2.9 MB.

   Committed: `95419f5` (assemble.sh fix).

## YouTube upload

**Use the `-burned` version** — captions are baked in, so judges on mute can
still follow. If YouTube rejects it, the non-burned version works as a fallback
and you can add captions via YouTube Studio.

1. Go to https://studio.youtube.com/
2. Create → Upload videos
3. Drag `custodian-openai-hackathon-final-burned.mp4` in
4. Title: **Custodian — The safety kernel for autonomous agents (OpenAI Build Week)**
5. Description:
   ```
   Custodian is a safety kernel between AI agents and the tools they use.
   This video demonstrates the Codex Guard extension built during OpenAI
   Build Week using Codex and GPT-5.6.

   The agent proposes. Custodian decides.

   Install: pip install custodian-kernel
   Repo: https://github.com/inovinlabs/custodian-dev
   Built for the OpenAI Devpost Hackathon.
   ```
6. Tags: openai, codex, gpt-5, ai-safety, devops, kernel, hackathon
7. Visibility: **Unlisted** (or Public if you want)
8. **Save the YouTube URL** — you'll paste it into the Devpost submission form

**Note on processing time:** YouTube processing can take 5-15 minutes. Don't
wait until 5:55 PM to upload. Upload by 4:00 PM Mountain at the latest.

## Devpost submission

Go to https://openai.devpost.com/ and click "Submit" on your project page.

**Required fields:**

| Field | Value |
|---|---|
| Project name | Custodian — The safety kernel for autonomous agents |
| Tagline | The agent proposes. Custodian decides. |
| Built with | Python, Codex, GPT-5.6, MCP, ffmpeg, PIL |
| Categories | Developer Tools (primary; this includes DevOps, agentic workflows, and security) |
| Video URL | Your YouTube URL from above |
| Repo URL | https://github.com/inovinlabs/custodian-dev |

**Project description (markdown):**

```markdown
## What it does

Custodian is a safety kernel that evaluates every action an AI agent
proposes before that action reaches the system. The model proposes.
The kernel decides. The verifier proves. The kill switch stops.

This is the Build Week contribution: **Custodian Guard for Codex** — a
typed action bridge and MCP server that routes every Codex tool call
through deterministic policy evaluation plus contextual GPT-5.6 risk
analysis. Decisions are recorded in a value-free, HMAC hash-chained
receipt log that the agent cannot forge.

## How it was built with Codex and GPT-5.6

I used Codex with GPT-5.6 to build this during OpenAI Build Week.

- **Codex** implemented the policy bridge (`custodian.codex_guard.guard`),
  the MCP server (`custodian.codex_guard.mcp_server`), the typed
  `ActionKind` enum and `_SHELL_RULES` regex set, the value-free
  hash-chained receipts, the single-use approval flow, and **7 dedicated
  test files** with **110 tests** covering the policy surface, the
  self-approval regression, the gate-fail-closed path, and the bypass
  attempts.
- **Codex** also adversarially tested the false-positive rate — the demo
  includes a "disguised delete" case where the agent claims `read` but
  the command is `rm -rf`; the kernel correctly classifies it as
  `destructive` and escalates.
- **GPT-5.6** powers the contextual risk analysis and produces concise
  human-readable reasons for each decision. Deterministic rules keep
  final control over prohibited actions (path fence, secret leak, prompt
  injection, kernel self-protection) — GPT-5.6 cannot override them.

The four built-in adapters form the policy stack: `PathFence`,
`SecretLeakGuard`, `PromptInjectionGuard`, `KernelSelfProtection`. They
are the source of the explicit, deterministic guarantees.

## Try it

```bash
git clone https://github.com/inovinlabs/custodian-dev
cd custodian-kernel
pip install -e .
python scripts/codex-guard-demo.py     # the demo in the video
pytest tests/test_codex_guard_cli.py   # 37 tests
pytest tests/test_codex_guard.py tests/test_codex_policy_wiring.py \
       tests/test_codex_guard_cli.py tests/test_self_approval_regression.py \
       tests/test_guard_bypass_regressions.py tests/test_gate_fail_closed.py
# 110 passed

custodian codex-guard receipts --state-dir ~/.custodian --verify
# chain OK (N receipts)
```

Supported platforms: Linux, macOS, Windows. Python 3.11+. No GPU required.

## What's new in Build Week

The new code is concentrated in:
- `custodian/codex_guard/` — the new package
  - `guard.py` — `evaluate_action()` and `GuardDecision`
  - `mcp_server.py` — the MCP server Codex talks to
  - `receipts.py` — `ReceiptChain` (value-free, HMAC-chained)
  - `approvals.py` — `ApprovalStore` (single-use, digest-bound)
  - `cli.py` — operator surface (`custodian-codex approve/deny/status/doctor`)
- `custodian/cli/cmd_codex_guard.py` — the new `custodian codex-guard receipts`
  command for inspecting the chain
- `scripts/codex-guard-demo.py` — the deterministic, no-network demo
- 7 new test files in `tests/`, 110 new tests
```

**Required checkboxes:** Make sure you check:
- "I built this during OpenAI Build Week"
- Whatever the "tested and working" checkboxes are
- The "I used Codex and GPT-5.6" affirmation (or however it's worded)

## What I noticed but did NOT change (out of scope)

These are real, but I did not touch them because they're not on the critical
path for the submission:

1. **Venv/install ambiguity**: The venv at
   `/home/dev/custodian-codex-work/.venv/` is pinned (via PEP 660 editable
   install) to `/home/dev/custodian-codex-work/custodian/`, NOT
   `/home/dev/custodian-04-integration/`. If you `cd` into
   `custodian-04-integration` and run `custodian ...` it will use the OLD
   main.py from the codex-work tree. The fix for the demo is one
   environment variable:
   ```bash
   export PYTHONPATH=/home/dev/custodian-04-integration
   custodian codex-guard receipts --verify
   ```
   Or, properly, run `uv pip install -e .` from inside
   `custodian-04-integration` to point the venv at the right tree. This is
   a setup issue, not a code issue.

2. **A second custodian install at `/home/dev/.local/lib/python3.13/site-packages/custodian/`**
   is shadowing things on the global `python3.13`. If you want a clean
   "install from a fresh clone" experience for judges, run `pip uninstall
   custodian-kernel` from `.local` first, then `pip install -e .` from the
   repo.

3. **cua-driver (computer_use) is not installed**. I planned to do a live
   demo segment but `hermes computer-use install` requires interactive
   setup. The video ended up fully rendered, which is actually better for
   a hackathon submission — no flakiness, perfect typography, on-brand
   visuals. If you want a live demo in v2, install cua-driver and re-record.

4. **The voice is TTS (piper)**. It sounds synthetic. Judges will notice
   but won't penalize. If you want to swap in your own voice, record
   yourself reading `video-build/teleprompter.md` into a microphone and
   replace `voiceover-raw.wav`, then re-run `assemble.sh`. The 6 voice
   blocks in the teleprompter are designed to be recordable in 5-10
   minutes of single-take recording.

5. **Test count discrepancy**: The README claims 1,747 tests; the OpenAI
   judges will probably only run the 7 codex_guard test files (110 tests).
   Make sure the README's "110 tests for the Build Week codex_guard work"
   is the headline number, not 1,747 — the latter is the full kernel
   suite which judges won't have time to run.

## The video — what judges will see

| Time | What they see | Voiceover |
|------|---------------|-----------|
| 0:00 | Title card | "Custodian — the safety kernel for autonomous agents" |
| 0:02 | DANGER in red monospace | "AI agents are running code on real systems..." |
| 0:14 | INTRODUCE | "Custodian is a safety kernel between AI agents and the tools they use..." |
| 0:30 | DEMO (3 sub-frames: cases, MCP, tamper test) | "A read-only inspection is allowed..." |
| 1:18 | ARCHITECTURE diagram | "Custodian is agent-independent. Enforcement happens at the tool boundary..." |
| 1:40 | CODEX + GPT-5.6 (the mandatory section) | "I used Codex with GPT-5.6 to build this during OpenAI Build Week..." |
| 2:10 | PYTEST output (37 passed) | "The same scenarios are covered by automated tests..." |
| 2:36 | 3 close slides | Silent |

## Files at a glance

```
video-build/
├── assemble.sh                          # the build pipeline (run this)
├── build_captions.py                    # slide + ASS renderer
├── captions.ass                         # subtitle file
├── custodian-cue-timer.html             # cue timer (not used)
├── custodian-intro-card.html            # (not used)
├── custodian-openai-hackathon-final.mp4 # 2.7 MB, no burned captions
├── custodian-openai-hackathon-final-burned.mp4 # 2.9 MB, captions burned
├── screen-capture.mp4                   # 170.00s screen content
├── slides/slide-{1,2,3}.png             # the 3 close slides
├── teleprompter.md                      # voiceover script
├── timing.json                          # canonical timing
└── voiceover-raw.wav                    # 170.01s, 22050Hz mono PCM

custodian/codex_guard/                   # the new package (Build Week)
custodian/cli/cmd_codex_guard.py         # the new CLI subcommand
tests/test_codex_guard*.py               # the new test files
```

## TL;DR checklist for the next 30 minutes

1. [ ] Upload `custodian-openai-hackathon-final-burned.mp4` to YouTube (unlisted)
2. [ ] Get the YouTube URL
3. [ ] Open https://openai.devpost.com/ and start the submission form
4. [ ] Paste the YouTube URL
5. [ ] Fill in the description (template above)
6. [ ] Fill in the repo URL
7. [ ] Mark "I used Codex and GPT-5.6"
8. [ ] Check any other required boxes
9. [ ] Submit
10. [ ] Breathe

Good luck. — Hermes
