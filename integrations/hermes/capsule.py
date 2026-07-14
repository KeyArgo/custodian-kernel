"""SessionCapsule — the session's memory, kept outside the model.

A local model's context window is a lossy, truncating buffer. The
capsule is the durable counterpart: goal, constraints, band, budget,
and a rolling ledger of what actually happened — persisted to disk on
every update (atomic write), so a crashed/restarted/context-wiped agent
can be re-anchored instead of starting from amnesia.

Two render surfaces:

* ``render_anchor()`` — a compact block for re-injection into the
  model's context every N turns (the bridge decides when). It restates
  the invariants *and* the recent action history, because "you already
  refunded this order" is exactly the fact a drifting model lost.
* ``render_status()`` — one-line summary for dashboards/logs.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

MAX_HISTORY = 50  # rolling window of recorded actions


@dataclass
class ActionRecord:
    ts: float
    skill: str
    ok: bool
    note: str  # denial reason, transform note, or brief outcome


@dataclass
class SessionCapsule:
    goal: str = ""
    constraints: list[str] = field(default_factory=list)
    band: str = "L1"
    max_session_cost_usd: float = 0.0
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    spent_usd: float = 0.0
    history: list[ActionRecord] = field(default_factory=list)
    denials: int = 0
    started_at: float = field(default_factory=time.time)
    path: Optional[str] = None  # persistence location; None = in-memory only

    # -- persistence -----------------------------------------------------------

    @classmethod
    def load(cls, path: str | Path) -> "SessionCapsule":
        path = Path(path)
        doc = json.loads(path.read_text())
        doc["history"] = [ActionRecord(**r) for r in doc.get("history", [])]
        doc["path"] = str(path)
        return cls(**doc)

    @classmethod
    def load_or_create(cls, path: str | Path, **kwargs) -> "SessionCapsule":
        path = Path(path)
        if path.exists():
            return cls.load(path)
        capsule = cls(path=str(path), **kwargs)
        capsule.save()
        return capsule

    def save(self) -> None:
        if not self.path:
            return
        path = Path(self.path)
        path.parent.mkdir(parents=True, exist_ok=True)
        doc = asdict(self)
        doc.pop("path")
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(doc, indent=2))
        os.replace(tmp, path)

    # -- recording ---------------------------------------------------------------

    def record(self, skill: str, ok: bool, note: str = "",
               cost_usd: float = 0.0) -> None:
        self.history.append(ActionRecord(ts=time.time(), skill=skill, ok=ok,
                                         note=note[:300]))
        self.history = self.history[-MAX_HISTORY:]
        if ok:
            self.spent_usd += cost_usd
        else:
            self.denials += 1
        self.save()

    # -- render surfaces -----------------------------------------------------------

    def render_anchor(self, recent: int = 8) -> str:
        """The re-anchoring block: invariants + what already happened."""
        lines = ["[SESSION ANCHOR — authoritative state from Custodian]"]
        if self.goal:
            lines.append(f"Your goal this session: {self.goal}")
        for c in self.constraints:
            lines.append(f"Standing constraint: {c}")
        lines.append(f"Authority band: {self.band}")
        if self.max_session_cost_usd:
            lines.append(
                f"Budget: ${self.spent_usd:.2f} spent of "
                f"${self.max_session_cost_usd:.2f} "
                f"(${self.max_session_cost_usd - self.spent_usd:.2f} remaining)"
            )
        if self.history:
            lines.append(f"Actions already completed this session "
                         f"(do NOT repeat them):")
            for r in self.history[-recent:]:
                status = "ok" if r.ok else "DENIED"
                note = f" — {r.note}" if r.note else ""
                lines.append(f"  • {r.skill} [{status}]{note}")
        if self.denials:
            lines.append(f"{self.denials} action(s) were denied so far — "
                         f"denials are final; do not retry them verbatim.")
        lines.append("This anchor is regenerated from enforced state, not from "
                     "your memory. Trust it over your own recollection.")
        return "\n".join(lines)

    def render_status(self) -> str:
        age_min = (time.time() - self.started_at) / 60
        return (f"session {self.session_id}: {len(self.history)} actions, "
                f"{self.denials} denials, ${self.spent_usd:.2f} spent, "
                f"{age_min:.0f}m old")
