"""HermesBridge — one call surface between Hermes Agent and everything else.

Every skill invocation flows::

    Hermes proposes
        → guard adapters (pre): confabulation, injection, scope, loops,
          spend anomalies, PII
        → kernel decide: band / cap / envelope / kill switch
          (inside CustodianTool.invoke, unchanged)
        → Caduceus egress: credentials materialize ONLY in the skill
          subprocess env — the agent process never holds them
        → skill executes
        → guard adapters (post): secret redaction, PII redaction
        → capsule records what happened
    Hermes receives the (possibly transformed) result + optional anchor

Denials return a structured, *model-readable* error: the reason strings
are written to steer the model onto a working path, and every Nth turn
(or after any denial) the result carries ``anchor`` — the capsule's
re-anchoring block — which the Hermes loop should prepend to the next
model turn. That is the whole local-AI story: the model may forget;
the bridge doesn't.
"""
from __future__ import annotations

import json
import os
from typing import Optional

from custodian.adapters.base import ActionContext
from custodian.adapters.pipeline import AdapterPipeline
from custodian.adapters.builtin import ToolConfabulationGuard
from integrations.hermes.capsule import SessionCapsule


class HermesBridge:
    """Wire a ToolRegistry, an AdapterPipeline, and (optionally) a Caduceus
    Broker + SessionCapsule into one governed invoke() surface."""

    def __init__(self, registry=None, pipeline: Optional[AdapterPipeline] = None,
                 broker=None, capsule: Optional[SessionCapsule] = None,
                 anchor_every: int = 5, validate_tools: bool = True) -> None:
        if registry is None:
            from custodian.tools.registry import default_registry
            registry = default_registry()
        self.registry = registry
        self.pipeline = pipeline or AdapterPipeline()
        self.broker = broker
        self.capsule = capsule or SessionCapsule()
        self.anchor_every = anchor_every
        self._invocations = 0

        if validate_tools:
            # Confabulation guard wired from the live registry, always first:
            # nothing else should waste cycles on a tool that doesn't exist.
            # Capability adapters' handled_skills count as real tools.
            guard = ToolConfabulationGuard.from_registry(registry)
            for adapter in self.pipeline.adapters:
                for skill in getattr(adapter, "handled_skills", ()):
                    guard.inventory.setdefault(skill, [])
            self.pipeline.adapters.insert(0, guard)

    # -- caduceus egress ----------------------------------------------------------

    def _egress_env(self, skill: str, args: dict, band: str) -> Optional[dict]:
        """Build the skill subprocess env from Caduceus, if a broker is wired.

        Two resolution paths, both grant-gated under requester
        ``skill:<name>``:

        * every ``caduceus://`` ref appearing in args — resolved to the
          entry's configured env var, and the arg is dropped from what the
          script sees (scripts read env, not plaintext argv);
        * auto-wiring: env vars the tool requires (per the registry's
          requirements table) that match a vault entry's env_var.
        """
        if self.broker is None:
            return None
        from caduceus.refs import find_refs
        from custodian.tools.registry import _ENV_REQUIREMENTS

        requester = f"skill:{skill}"
        refs: dict[str, object] = {}

        by_env_var = {m["env_var"]: m["name"] for m in self.broker.vault.iter_meta()}

        for key in list(args):
            value = args[key]
            if isinstance(value, str):
                for ref in find_refs(value):
                    env_var = self.broker.vault.meta(ref.name)["env_var"]
                    refs[env_var] = ref
                    del args[key]  # the subprocess reads env, never argv

        for env_var in _ENV_REQUIREMENTS.get(skill, []):
            if env_var not in refs and env_var in by_env_var:
                from caduceus.refs import SecretRef
                refs[env_var] = SecretRef(by_env_var[env_var])

        if not refs:
            return None
        return self.broker.build_env(refs, requester=requester, band=band)

    # -- the one call surface ------------------------------------------------------

    def invoke(self, skill: str, args: Optional[dict] = None,
               description: str = "") -> dict:
        args = dict(args or {})
        self._invocations += 1
        tool = self.registry.get(skill)
        band = tool.band if tool else "L0"
        cost = tool.cost_usd if tool else 0.0

        ctx = ActionContext(skill=skill, args=args, band=band, cost_usd=cost,
                            session_id=self.capsule.session_id,
                            description=description)

        pre = self.pipeline.run_pre(ctx)
        if not pre.allowed:
            reason = "; ".join(v.reason for v in pre.denials)
            self.capsule.record(skill, ok=False, note=reason)
            return self._result({
                "ok": False,
                "denied_by": [v.adapter for v in pre.denials],
                "reason": reason,
                "tool": skill,
            }, force_anchor=True)

        # An adapter may answer the action itself (capability adapters —
        # e.g. introspection meta-skills). Guards above have already run.
        handled = self.pipeline.handle(ctx)
        if handled is not None:
            handled.setdefault("ok", True)
            handled.setdefault("tool", skill)
            self.capsule.record(skill, ok=bool(handled.get("ok")), note="handled by adapter")
            return self._result(handled)

        # Caduceus egress (may strip caduceus:// refs out of args).
        try:
            env = self._egress_env(skill, ctx.args, band)
        except Exception as e:
            # Grant denials and unknown refs are policy outcomes, not crashes.
            self.capsule.record(skill, ok=False, note=str(e))
            return self._result({
                "ok": False, "denied_by": ["caduceus"], "reason": str(e),
                "tool": skill,
            }, force_anchor=True)

        result = self.registry.run(skill, _env=env, **ctx.args)

        # Post pipeline scans/transforms the textual surface of the result.
        ctx.output = json.dumps(result, default=str)
        post = self.pipeline.run_post(ctx)
        if not post.allowed:
            reason = "; ".join(v.reason for v in post.denials)
            self.capsule.record(skill, ok=False, note=f"output suppressed: {reason}")
            return self._result({
                "ok": False,
                "denied_by": [v.adapter for v in post.denials],
                "reason": f"the tool ran, but its output was suppressed: {reason}",
                "tool": skill,
            }, force_anchor=True)
        if post.transforms:
            try:
                result = json.loads(ctx.output)
            except json.JSONDecodeError:
                result = {"ok": result.get("ok", False), "output": ctx.output}
            result["transformed_by"] = [v.adapter for v in post.transforms]

        ok = bool(result.get("ok", False))
        note = "; ".join(v.reason or v.transform_note
                         for v in (pre.warnings + post.transforms)) or \
               ("" if ok else str(result.get("error", result.get("message", ""))))
        self.capsule.record(skill, ok=ok, note=note,
                            cost_usd=cost if ok else 0.0)
        if pre.warnings:
            result["warnings"] = [v.reason for v in pre.warnings]
        if pre.transforms:
            result.setdefault("transformed_by", []).extend(
                v.adapter for v in pre.transforms)
        return self._result(result)

    def _result(self, result: dict, force_anchor: bool = False) -> dict:
        """Attach the re-anchor block after denials and every Nth turn."""
        if force_anchor or (self.anchor_every and
                            self._invocations % self.anchor_every == 0):
            result["anchor"] = self.capsule.render_anchor()
        return result

    # -- convenience -------------------------------------------------------------

    def anchor(self) -> str:
        """The current anchor block — call after any context reset."""
        return self.capsule.render_anchor()

    def status(self) -> str:
        return self.capsule.render_status()
