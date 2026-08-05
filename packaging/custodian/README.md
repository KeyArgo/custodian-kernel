# Custodian Suite

One install for the whole Custodian governance suite.

```bash
pip install custodian-suite
custodian setup --profile hermes --enable
custodian doctor --profile hermes
```

(Note: the PyPI package is `custodian-suite`, not `custodian` — the bare
`custodian` name is taken on PyPI by an unrelated JIT job framework.)

Installing `custodian-suite` pulls in the full suite:

| Package | What it provides |
|---------|------------------|
| `custodian-kernel` | The core engine: authority bands, guard pipeline, policy DSL, receipts, CLI |
| `custodian-codex-guard` | Guard adapter for Codex (MCP server + CLI) |
| `custodian-talaria` | Hermes Agent + NemoClaw integration: guard plugin, vault, dashboard |

This package itself contains no code — it exists so a new user only has to
remember one name. The individual packages keep their own names, version
lines, and release cadences; `custodian-suite` simply ties them together
and is re-released whenever any component's floor moves.

## Why not rename `custodian-kernel`?

The kernel name is baked into existing installs, lockfiles, and the
repository's history. Renaming the published package would break every
`pip install custodian-kernel` and every downstream pin. Instead, the suite
identity lives here: a zero-code meta-package that depends on the real
packages. The kernel can keep its name (and its stars) while the *suite* gets
the name people actually want to type.

## Development

This tree lives at `packaging/custodian/` inside the custodian-dev monorepo.
To build:

```bash
python -m build packaging/custodian
```
