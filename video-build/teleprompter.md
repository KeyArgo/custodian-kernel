# CUSTODIAN — Voiceover Teleprompter
# Print this (or load on your phone). Read aloud at a natural pace (~150 wpm).
# Each block is separated by a blank line and tagged with the segment name + timing.
# Do NOT read the tags — read only the voiceover text.
# Record in a single take. Pauses are marked with [pause]. Silences are marked with [silence Xs].

---

[HOOK — 0:00.5 → 0:06.0]

The AI tried to approve its own refund.

[pause 0.4s]

The kernel said no.

[silence 0.5s]

---

[ARCHITECTURE — 0:07.0 → 0:17.5]

Layer one is the model.

[pause 2.5s]

Layer two is the kernel.

[pause 0.5s]

The model can only ask. The kernel can't be overruled.

[silence 0.5s]

---

[STEP 0: EARN — 0:19.0 → 0:23.0]

First, a thousand two hundred dollars comes in. No check, no cap.

---

[STEP 1: SPEND — 0:24.0 → 0:30.0]

Eighty-five dollars goes out. The kernel approves it autonomously, no human in the loop. A real Stripe ID appears on screen.

---

[STEP 2: ESCALATE — 0:31.0 → 0:40.0]

Three thousand five hundred dollars. Over the per-action cap. The kernel escalates, and a real Twilio SMS is about to land on the operator's phone.

[silence 5.0s]

---

[PHONE SMS CLIMAX — 0:45.0 → 0:55.0]

That code is on the operator's phone and on Twilio's servers. Nothing in the agent's process can see it. It cannot approve its own refund.

---

[STEPS 3-7: APPROVE, KILL, RELEASE, REFUND — 0:55.0 → 1:02.0]

Operator approves. Kill switch on — even forty dollars is denied. Kill switch off. Refund escalates, second SMS.

---

[PROOF A: DEMO-VERIFY — 1:03.0 → 1:08.0]

Four claims. One verified. Two contradicted — including self-approval. The kernel catches every lie.

---

[PROOF B: EARN-AND-BUY — 1:09.0 → 1:28.0]

Same GPU rental as before. But this time there's a deterministic audit trail. The claim verifier sees a real Modal GPU job — a real elapsed time, real gigaflops, a real bill. Every line in the ledger is signed and the agent cannot forge it. The kernel cannot be fooled.

---

[PROOF C: VERIFY_KIT — 1:28.0 → 1:38.0]

Now watch the test catch the bug. We re-introduce the self-approval flaw. The regression test fires. The file is restored. All checks pass.

---

[TEST COUNT — 1:40.0 → 1:50.4]

One thousand, two hundred forty-five tests. The one that matters: the regression that reintroduces the self-approval bug — the same bug the verifier just proved couldn't be faked.

---

[CLOSE — 1:52.0 → 2:03.0]

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
# 7. Total reading time target: ~80-90 seconds of voice. The rest is silence on screen.
# 8. Don't read the tags. Read the voiceover text only.
# 9. Record the whole thing as a single file. I'll split it.
#
# Once recorded, place the file as:
#   /mnt/homes/galileo/argo/Development/hermes-hackathon-2026/video-build/voiceover-raw.wav
#
# Then run:
#   cd /mnt/homes/galileo/argo/Development/hermes-hackathon-2026/video-build/
#   python3 assemble.py
#
# You'll also need:
#   video-build/screen-capture.mp4   (OBS recording, 1920x1080, 30fps)
#   video-build/phone-sms.mp4        (phone screen recording, 5s clip)
#   video-build/slides/              (3 PNG files — produced by caption-burner.py)
