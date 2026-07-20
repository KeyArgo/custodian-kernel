# Custodian vs. Cyberware — security comparison and surpass plan

Reviewed source: `rhCat/cyberware` at commit
`88a94f07c80f66ae736a26f458867817b47dd71c` (2026-07-15).

This is an engineering comparison, not marketing. Custodian must not claim to
be globally more secure than Cyberware until the applicable acceptance tests
below pass. Cyberware has substantial controls that Custodian does not yet
ship; Custodian has different strengths that Cyberware does not replace.

## Current comparison

| Security surface | Cyberware evidence | Custodian evidence | Current verdict |
|---|---|---|---|
| Policy outside model context | `govd`, blessed plan, in-channel executor | kernel evaluator, middleware, adapters, external approval | Both have real enforcement seams; integration coverage must be stated honestly. |
| Credential values absent from governance wire | Value-free claims; credentials resolved by `exod` vault | Paladin refs, grants, subprocess injection, leak sentinel, host restrictions | Custodian/Paladin is competitive and more user-facing, but delegated execution should bind refs to signed action grants. |
| OS confinement | Linux bwrap and gVisor profiles; fail closed if unavailable | NemoClaw/Landlock integration plus software path/egress guards | Cyberware stronger and more explicitly proven at the generic executor boundary. |
| Execution authorization | Ed25519/DSSE, short-lived single-use grants bound to run, plan, workspace, argv, capabilities and credential names | Authority decisions, human approval, signed receipts; no equivalent general single-use execution grant | Cyberware stronger. |
| Independent execution attestation | Separate `exod` principal signs results; agent self-report rejected | Confirmation/receipts and sandbox integration, but not a universal distinct executor identity | Cyberware stronger. |
| Replay/revocation | Issuer-scoped nonces, TTL/skew, in-flight reauthorization, key rotation/revocation | Approval TTL, grants, kill switch, receipt validation | Cyberware stronger as a general action-capability protocol. |
| Ledger durability | One lock across tip-read/link/append/fsync, short-write handling, torn-tail healing, atomic snapshots and directory fsync | Append+fsync; some state locks; Paladin HMAC chain | Cyberware stronger; this is mandatory work for the universal ledger. |
| Ledger verification scale | RFC-8785 chain, independent Go verifier, Merkle checkpoints | Python verification, HMAC/Ed25519 receipts | Cyberware stronger. Independent verifier/checkpoints are future milestones. |
| Tail truncation evidence | Checkpoints and external/transparency anchoring designs | Local chains do not independently prove tail deletion | Neither local chain alone proves non-truncation; Cyberware has the stronger anchoring path. |
| Privacy/erasure | Per-record AES-GCM subject encryption and crypto-shredding | Value-free logs and recursive secret redaction | Custodian minimizes stored data well; Cyberware stronger for intentionally stored personal fields and erasure. |
| Supply-chain security | Signed images, cosign/in-toto/DSSE, pinned root, SBOM, reproducible-build work | Package build/tests; no equivalent complete attestation ladder | Cyberware stronger. |
| Formal verification | L++/TLC and additional model-checking images | Typed deterministic tests and adversarial suites | Cyberware stronger in formal methods; Custodian has broader application-level regression coverage. |
| Human escalation | Not its primary product focus | Twilio Verify, operator separation, denial, kill switch | Custodian stronger and more approachable. |
| Cross-platform usability | Cooperative mode cross-platform; strong confinement Linux-only | Windows/Linux support throughout, provider integrations and installer direction | Custodian stronger in practical Windows integration; do not confuse usability with confinement strength. |
| Provider/action adapters | Skill cartridge and broad governance machinery | Stripe, Paladin, Talaria, middleware, packs, Codex work | Different models; Custodian is stronger for direct business/API integration and human-friendly governance. |
| Secret leak defenses | Value-free wire and isolated executor | raw-token detectors, entropy scanning, output redaction, vault-value sentinel, destination restriction | Custodian/Paladin has strong defense in depth; add signed execution binding to surpass. |

## Mandatory parity work

### P0 — before claiming a fortress-grade universal ledger

1. One cross-process lock must cover reading the chain tip, computing the next
   link/sequence, healing a torn final line, appending fully, and fsyncing.
2. Handle short writes; never assume one `write()` commits all bytes.
3. Atomic snapshots must use same-directory temporary files, fsync, replace,
   and best-effort directory fsync.
4. Detect and report torn-tail recovery while refusing mid-chain corruption.
5. Bind chain genesis to an origin/schema and define version migration as a new
   chain cross-referencing the prior chain—not an in-place rewrite.
6. Add multi-process torture tests and crash/truncation fault injection.
7. State explicitly that a local hash chain does not prove tail deletion; add
   signed external checkpoints before claiming truncation resistance.

### P0 — before allowing Paladin-backed autonomous execution

1. Mint a signed, short-lived, single-use action capability after Custodian
   decides and, where required, a human approves.
2. Bind it to correlation ID, requester, action digest, workspace, exact
   executable/operation, destination, credential reference names, authority
   band, not-before/expiry, and nonce.
3. Verify signature and all bindings before resolving a credential.
4. Spend the nonce only after all other checks pass; persist replay protection
   where restart replay is in scope.
5. Reauthorize immediately before execution so revocation/kill-switch changes
   take effect in flight.
6. Paladin injects only credentials named in the verified capability.
7. Raw values remain absent from the capability, ledger, argv, model context,
   and process logs.

### P0 — execution truth

1. Separate the decision issuer from the executor identity where delegated
   execution is used.
2. The executor signs a result bound to the action grant/correlation ID.
3. The ledger must not treat an agent's self-reported success as authoritative.
4. Test forged result, wrong action, wrong workspace, wrong destination,
   expired grant, replay, revoked grant, and executor-key mismatch.

### P1 — confinement

1. Define a provider-neutral confinement profile: allowed read-only binds, one
   or more explicit writable roots, network policy, environment allowlist,
   process limits, and secret references.
2. On Linux, provide a kernel-backed executor using an established boundary
   (NemoClaw/Landlock, bwrap, gVisor, or equivalent) and refuse rather than
   silently run unconfined when that tier is required.
3. Keep Windows support honest: use Windows-native containment where proven;
   otherwise report the lower assurance tier rather than implying Linux
   namespace parity.
4. Run a red-team corpus with software scans disabled to prove the OS boundary
   itself blocks filesystem, process, credential, and network escape.

### P1 — keys, privacy, and supply chain

1. Introduce a signing-key backend interface supporting non-exportable KMS/HSM
   implementations, rotation, revocation, and key IDs.
2. Encrypt intentionally stored personal ledger fields under subject-scoped
   keys so erasure can destroy the key without breaking the chain.
3. Generate an SBOM and provenance for release artifacts.
4. Sign packages/images and publish offline-verifiable attestations tied to the
   exact source and test run.
5. Add an independent verifier in a second implementation/language before
   claiming verifier diversity.

## Where Custodian should surpass rather than imitate

- One approachable installer and doctor flow on Windows, Linux, and macOS.
- Human escalation and break-glass recovery that remain structurally separate
  from the agent.
- Paladin's user-friendly encrypted vault, per-requester grants, secret leak
  sentinel, and destination-bound egress.
- Provider-neutral ledger plus separately packaged Stripe and other adapters.
- Native Codex, Claude Code, Antigravity, and Hermes integrations sharing one
  conformance contract.
- Clear assurance levels: software guard, governed subprocess, and
  kernel-confined delegated executor—never one vague “secure” badge.
- A small deterministic verifier and demo a customer or judge can run in under
  a minute, alongside deeper security validation.

## Claim discipline

Allowed now:

> Custodian combines deterministic authority, human escalation, Paladin
> credential mediation, provider integrations, and extensive adversarial tests
> in a cross-platform, user-facing platform.

Not yet allowed:

> Custodian is more secure than Cyberware in every respect.

That second claim becomes defensible only surface by surface, with the above
acceptance criteria and external review evidence—not by test count or feature
count alone.
