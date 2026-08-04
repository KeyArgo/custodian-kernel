# Security policy

## Supported versions

Security fixes are made on the current development branch and released version
line. Older releases may receive guidance but are not guaranteed patches.

## Reporting a vulnerability

Please report suspected vulnerabilities privately to
<hello@inovinlabs.com>. Do not include credentials, vault contents, approval
codes, private receipts, or production identifiers in public issues.

Include a minimal reproduction, affected version or commit, impact, and any
safe mitigation you have identified. We aim to acknowledge reports within five
business days and will coordinate disclosure after a fix or mitigation exists.

## Scope and boundaries

Custodian governs actions routed through its installed integrations. It is not
a replacement for host operating-system isolation or for controls around an
unintegrated runner. Paladin's strongest credential-isolation mode requires a
ready Linux Bubblewrap sandbox and fails closed when unavailable. The detailed
threat model and known limitations are in [docs/SECURITY.md](docs/SECURITY.md).
