# Contributing to Custodian

Thank you for helping improve Custodian. This project welcomes focused bug
fixes, tests, documentation, integrations, and design proposals.

## Before opening a change

- Search existing issues and pull requests.
- Do not disclose vulnerabilities publicly; follow [SECURITY.md](SECURITY.md).
- Keep changes focused and include regression tests for behavior changes.
- Never commit credentials, vaults, approval records, ledgers, backups, or
  other operator data.

## Development

Custodian supports Python 3.11 through 3.13.

```bash
python -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python -m pytest tests/
```

On Windows, use `.venv\\Scripts\\python.exe` instead.

See [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md) for the security-sensitive
test subset and pull-request expectations. Contributions are licensed under
the repository's [MIT License](LICENSE).
