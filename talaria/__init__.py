"""Talaria — the Hermes Agent + NemoClaw integration suite.

Named for Hermes' winged sandals: the layer that lets Hermes Agent move
fast and safely, governed end to end by the (brand-neutral) Custodian
kernel underneath. Talaria is where every Hermes/NemoClaw-specific
assumption lives — the kernel itself, the guard-adapter framework, and
the credential broker know nothing about Hermes and never will; a future
Claude or Codex integration would get its own equivalent package next to
this one, resting on the same neutral core.

Pieces:

* :class:`~talaria.bridge.HermesBridge` — one call surface
  (``bridge.invoke(skill, args)``) that runs every Hermes skill through
  guard adapters → kernel decide → Warden credential egress → post-scan.
* :class:`~talaria.capsule.SessionCapsule` — the session's
  goals/constraints/history persisted *outside* the model, with a
  ``render_anchor()`` block to re-inject when a local model drifts.
* :mod:`~talaria.soul` — compiles SOUL.md sections from the
  live policy so the system prompt never contradicts kernel truth.
* :mod:`~talaria.nemoclaw_egress` — Warden secrets into a
  NemoClaw sandbox exec without ever writing them to sandbox disk or
  the command line.
"""
from talaria.capsule import SessionCapsule
from talaria.bridge import HermesBridge

__all__ = ["HermesBridge", "SessionCapsule"]
