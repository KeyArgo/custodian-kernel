---
name: warden-vault-list
description: "List the credential references available in the Warden vault (names, profiles, env var targets — never values). Use the returned warden:// refs verbatim in tool arguments; Warden injects the real value into the tool's process at egress. You cannot read, print, or export the values themselves."
version: 1.0.0
metadata:
  hermes:
    tags: [Warden, Credentials, Introspection]
  custodian:
    band: L0
    cost_usd: 0.00
    configured: true
    handler: hermes-introspection
---

# warden-vault-list

Value-free inventory of the Warden vault. Every access is written to the
tamper-evident audit chain.

Requires the Hermes bridge with the `hermes-introspection` adapter enabled
and a Warden broker wired; without them this skill does not exist.
