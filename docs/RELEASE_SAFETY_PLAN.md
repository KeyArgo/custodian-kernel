# Custodian Safe Release Plan

Status: implementation plan; public release actions require separate operator
approval.

## Objective

Never publish an uninstalled or mismatched Custodian release again. One
immutable candidate must be prepared, installed, upgraded, uninstalled,
promoted to the correct KeyArgo repository, published to the matching PyPI
project, attached to the matching GitHub tag/release, downloaded again, and
verified by hash.

This applies to:

- `custodian-kernel` (including the bundled Paladin package and commands);
- `custodian-codex-guard`;
- `custodian-talaria`.

## Non-negotiable safety boundary

Preparation is non-public and may build, inspect, and test. Publication is a
separate operation. Before any KeyArgo commit or push, Git tag, GitHub release,
or PyPI upload, the tool must display the exact package, version, repository,
commit, artifact hashes, and gate results and require the operator to type the
package and version explicitly.

It must never rebuild between preparation and publication. PyPI and GitHub
receive the exact hash-pinned files that passed testing.

## Required workflow

### 1. Prepare

`custodian-release prepare <component> <version>`:

1. resolves the private source and correct public repository;
2. refuses dirty or ambiguous public repositories;
3. builds the filtered public source tree;
4. builds wheel and sdist once;
5. records SHA-256 hashes and source commit/tree identity;
6. runs metadata, credential, package-boundary, and parity checks;
7. installs the actual wheel into clean isolated runtimes;
8. tests a fresh install and upgrade from the latest real PyPI release;
9. tests two managed installs and a data-preserving uninstall;
10. writes an immutable release manifest and human-readable report.

Preparation cannot commit, push, tag, create releases, or upload packages.

### 2. Installation matrix

The exact candidate must pass:

- Python 3.11, 3.12, and 3.13;
- Linux, Windows, and macOS CI;
- an openSUSE/PEP 668 environment where system and `--user` pip installs are
  prohibited;
- a clean environment without the source checkout on `PYTHONPATH`;
- all registered command help paths and representative real commands;
- kernel-only operation without optional adapters;
- kernel + Paladin;
- kernel + Codex Guard;
- kernel + Talaria/Hermes profile where available;
- upgrade from the latest real PyPI versions;
- managed install, second-slot upgrade, rollback preservation, and uninstall.

Tests use a synthetic home/data root and must prove that vaults, policies,
ledgers, receipts, approvals, gate preferences, Paladin data, and Talaria data
are byte-identical afterward. The operator's real data is never used as test
input and is never removed.

### 3. Installed health confirmation

The installed application must provide a machine-readable health command that
reports:

- installed distribution names and versions;
- artifact SHA-256 when installed by the managed installer;
- kernel, Paladin, Codex Guard, and Talaria availability;
- command and policy/ledger integrity checks;
- data locations checked without exposing secrets;
- overall pass/fail and timestamp.

Successful checks append a value-free, tamper-evident release-health event to
the Custodian ledger. The CLI/TUI shows the latest confirmation without
requiring the user to inspect CI logs. Quiet gate mode may suppress routine
notices but not health failures.

### 4. Publish

`custodian-release publish <manifest>`:

1. re-verifies the manifest and artifact hashes;
2. verifies public mirror parity;
3. shows the irreversible action summary;
4. requires an exact typed confirmation such as
   `release custodian-kernel 0.4.1`;
5. commits only the reviewed mirror files to the correct KeyArgo repository;
6. pushes that commit;
7. tags that exact public commit;
8. uses protected GitHub environments and PyPI trusted publishing;
9. uploads the prepared artifacts without rebuilding;
10. creates the GitHub release from the same artifacts.

The implementation must be resumable and idempotent. A partial release must
stop safely and report which external steps completed; it must never move an
existing tag or overwrite an existing PyPI version.

### 5. Verify after publication

The verifier downloads the PyPI wheel/sdist and GitHub release artifacts,
checks them against the prepared hashes, installs the downloaded wheel, runs
health checks, and verifies tag/source parity. Any mismatch fails loudly and
recommends a yank or marked-broken release; deletion, tag movement, and yanking
remain separate operator-approved actions.

## Release evidence

Each component receives a durable report under `release-manifests/` containing:

- component, package, version, public repository, and intended tag;
- private source identity and public tree digest;
- artifact filenames, sizes, and hashes;
- every test command and result;
- platform/Python matrix results;
- fresh-install, upgrade, reinstall, uninstall, and data-preservation results;
- signatures, SBOM, provenance, and post-publication download verification;
- any skipped check, which blocks publication unless explicitly waived and
  recorded by the operator.

## Current release boundary

No existing script implements this complete workflow. `publish-mirror.sh`
copies files locally but intentionally does not use Git or publish.
`.github/workflows/release.yml` creates a GitHub release after a tag but does
not publish to PyPI and currently lives in the private source repository.

The first implementation target is a guarded local preparation controller and
shared public workflow templates. It must reach the explicit operator checkpoint
before any current 0.4.1/0.5.0 candidate is made public.

## Implementation status

The following have been implemented as of this update:

- `scripts/custodian-release.py` — preparation controller with `prepare`
  subcommand, component registry (kernel, codex-guard, talaria), immutable
  artifact SHA-256 hashes, public-repo/version/tag mapping, dirty-public-repo
  refusal, subprocess fail-fast, and explicit non-publishing boundaries.
- `custodian/cli/cmd_health.py` — machine-readable installed health command
  registered as `custodian health --format json`, reporting distribution
  versions, component availability, artifact hash, data locations without
  secrets, and appending a value-free tamper-evident event to the ledger.
- `tests/test_custodian_release.py` — comprehensive unit tests including
  PEP 668/openSUSE simulation, exact artifact install invocation, previous-PyPI
  upgrade planning, two-slot managed reinstall/uninstall planning, protected
  data paths, wrong-repo/version detection, no shell false positives, and proof
  that prepare contains no git push/tag/GitHub/PyPI upload operations.
- `.github/workflows/prepare-release.yml` — safe preparation-only workflow
  template (manual dispatch only, no irreversible publication).
- `custodian health` registered in the kernel CLI parser alongside doctor.

Not yet implemented (separate implementation required):
- `custodian-release.py publish` subcommand.
- Post-publication verification.
- PyPI trusted publishing integration.
- Windows/macOS CI matrix for the preparation workflow.
