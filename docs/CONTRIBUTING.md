# Contributing

Thank you for helping improve Custodian.

## Before opening a change

- Search existing issues and pull requests.
- For security vulnerabilities, do not open a public issue. Follow
  [SECURITY.md](SECURITY.md).
- Keep changes focused and add regression tests for behavior changes.
- Never commit credentials, vaults, approval records, ledgers, or other
  operator data.

## Development setup

Custodian supports Python 3.11 through 3.13.

```bash
python -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python -m pytest
```

On Windows, replace `.venv/bin/python` with `.venv\Scripts\python.exe`.

Before submitting a security-sensitive change, also run:

```bash
.venv/bin/python -m pytest \
  tests/test_guard_mutation_gate.py \
  tests/test_guard_gate_corpus.py \
  tests/test_no_credentials_tracked.py
```

## Pull requests

Explain the problem, the chosen behavior, and how it was tested. By submitting
a contribution, you agree that it is licensed under the repository's MIT
License.
