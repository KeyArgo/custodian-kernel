"""IntrospectionAdapter — meta-skills served by the governance layer itself.

An opt-in capability adapter (see ``Adapter.handle_action``). When
enabled, Hermes gains three value-free skills answered host-side —
they never spawn a subprocess and never require the vault passphrase in
any environment the agent can reach:

* ``custodian-status``    — session state: band, spend, denials, age.
* ``custodian-anchor``    — the full re-anchoring block on demand, so a
  model that *feels* itself losing the thread can ask to be re-grounded.
* ``paladin-vault-list``   — names/profiles/env-vars of vault entries
  (metadata only, values structurally absent), so the model knows which
  ``paladin://`` refs exist instead of guessing.

Not enabling this adapter removes the capability entirely — the skills
aren't stubbed, they're gone. Modularity over built-ins.
"""
from __future__ import annotations

from typing import Optional

from custodian.adapters.base import ActionContext, Adapter

META_SKILLS = ("custodian-status", "custodian-anchor", "paladin-vault-list")


class IntrospectionAdapter(Adapter):
    """Serves custodian-status / custodian-anchor / paladin-vault-list."""

    name = "hermes-introspection"
    category = "integration"
    handled_skills = META_SKILLS

    def __init__(self, config: dict | None = None, capsule=None, broker=None) -> None:
        super().__init__(config)
        self.capsule = capsule
        self.broker = broker

    def handle_action(self, ctx: ActionContext) -> Optional[dict]:
        if ctx.skill == "custodian-status":
            out = {"ok": True}
            if self.capsule is not None:
                out.update({
                    "session": self.capsule.session_id,
                    "band": self.capsule.band,
                    "goal": self.capsule.goal,
                    "spent_usd": round(self.capsule.spent_usd, 2),
                    "budget_usd": self.capsule.max_session_cost_usd,
                    "actions": len(self.capsule.history),
                    "denials": self.capsule.denials,
                    "status": self.capsule.render_status(),
                })
            return out

        if ctx.skill == "custodian-anchor":
            if self.capsule is None:
                return {"ok": False, "error": "no session capsule wired"}
            return {"ok": True, "anchor": self.capsule.render_anchor()}

        if ctx.skill == "paladin-vault-list":
            if self.broker is None:
                return {"ok": False, "error": "no paladin broker wired"}
            self.broker.audit.append("meta", "-", "skill:paladin-vault-list",
                                     ctx.band, "vault inventory listed")
            entries = [
                {"ref": f"paladin://{m['name']}", "profile": m["profile"],
                 "env_var": m["env_var"], "kind": m["kind"]}
                for m in self.broker.vault.iter_meta()
            ]
            return {"ok": True, "entries": entries,
                    "note": "values are never accessible; pass the ref string "
                            "in tool arguments and Paladin injects at egress"}

        return None
