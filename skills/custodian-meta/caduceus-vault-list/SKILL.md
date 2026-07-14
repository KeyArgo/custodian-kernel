---
name: caduceus-vault-list
description: "List the credential references available in the Caduceus vault (names, profiles, env var targets — never values). Use the returned caduceus:// refs verbatim in tool arguments; Caduceus injects the real value into the tool's process at egress. You cannot read, print, or export the values themselves."
version: 1.0.0
metadata:
  hermes:
    tags: [Caduceus, Credentials, Introspection]
  custodian:
    band: L0
    cost_usd: 0.00
    configured: true
    handler: hermes-introspection
---

# caduceus-vault-list

Value-free inventory of the Caduceus vault. Every access is written to the
tamper-evident audit chain.

Requires the Hermes bridge with the `hermes-introspection` adapter enabled
and a Caduceus broker wired; without them this skill does not exist.
