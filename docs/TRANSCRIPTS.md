# Session transcripts

Append-only index of raw Claude Code session transcripts for work on this
repo. Each entry is a pointer, not a copy — the JSONL files live under
`~/.claude/projects/` on the machine that ran the session (not portable,
not checked into this repo: they're large, contain full raw tool
input/output including anything sensitive that passed through a shell
command, and are Claude Code's own local state rather than project
content). If you need more detail than a handover doc gives you, read the
referenced file directly with the `Read` tool (use the `pages` param for
partial reads — these files get large) or open it with Claude Code's
`--resume`/`--continue` against that session id.

When you write a new handover doc, add one entry here for the session it
covers, so the two stay linked.

| Date | Session id (jsonl filename) | Path | Handover doc | Summary |
|---|---|---|---|---|
| 2026-07-14 → 2026-07-15 | `0192eba3-ffe3-425d-a1a9-dc69eb427522` | `/home/dev/.claude/projects/-home-dev/0192eba3-ffe3-425d-a1a9-dc69eb427522.jsonl` | [HANDOVER-2026-07-15.md](HANDOVER-2026-07-15.md) | PII/integrity audit of PyPI 0.3.0/0.3.1 + KeyArgo/custodian-kernel mirror, GitHub Releases creation, second adversarial-review pass (8 confirmed bugs fixed across path-fence/egress-guard/policy compilers/vault), broker naming finalized to Custodian Paladin + full rename + live vault migration, `talaria dashboard` built, custodian/paladin/talaria package-boundary enforcement added. |

Note: this session's transcript itself spans a **compaction boundary** —
context was summarized partway through by the harness, but the session id
stayed the same and the jsonl file is continuous, so one row above covers
the whole thing. A `--continue`/`--resume` against this session id picks
up the live conversation state, not just the raw log.
