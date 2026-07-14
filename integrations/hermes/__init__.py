"""Hermes integration — the bridge that takes Hermes Agent to kernel-grade.

Pieces:

* :class:`~integrations.hermes.bridge.HermesBridge` — one call surface
  (``bridge.invoke(skill, args)``) that runs every Hermes skill through
  guard adapters → kernel decide → Caduceus credential egress → post-scan.
* :class:`~integrations.hermes.capsule.SessionCapsule` — the session's
  goals/constraints/history persisted *outside* the model, with a
  ``render_anchor()`` block to re-inject when a local model drifts.
* :mod:`~integrations.hermes.soul` — compiles SOUL.md sections from the
  live policy so the system prompt never contradicts kernel truth.
* :mod:`~integrations.hermes.nemoclaw_egress` — Caduceus secrets into a
  NemoClaw sandbox exec without ever writing them to sandbox disk or
  the command line.
"""
from integrations.hermes.capsule import SessionCapsule
from integrations.hermes.bridge import HermesBridge

__all__ = ["HermesBridge", "SessionCapsule"]
