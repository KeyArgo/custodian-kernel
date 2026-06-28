"""Tool registry — discovers Hermes skills that declare a custodian-band.

Scans a skills root directory for SKILL.md files, parses YAML frontmatter,
and returns CustodianTool records for any skill that opts in via:

    metadata:
      custodian:
        band: L1          # authority band required to invoke this tool
        cost_usd: 0.00    # estimated cost per call (optional, default 0)
        configured: true  # whether credentials are wired (optional)
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


_FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL)


@dataclass
class CustodianTool:
    name: str
    description: str
    band: str               # L0–L4
    cost_usd: float = 0.0
    configured: bool = True  # False = stub, credentials not set
    skill_dir: Optional[Path] = None
    tags: list[str] = field(default_factory=list)
    version: str = "1.0.0"
    execute_script: Optional[Path] = None  # scripts/execute.py if present

    @property
    def band_label(self) -> str:
        labels = {
            "L0": "L0 · read-only",
            "L1": "L1 · free / trivial",
            "L2": "L2 · autonomous up to cap",
            "L3": "L3 · always escalates",
            "L4": "L4 · unlimited / human required",
        }
        return labels.get(self.band, self.band)

    def invoke(self, **kwargs) -> dict:
        """Run the skill's execute.py script with kwargs as --key value args.

        Returns dict with at minimum {"ok": bool, "output": str}.
        If the skill is a stub (configured=False) returns a stub response.
        """
        if not self.configured:
            return {
                "ok": False,
                "stub": True,
                "tool": self.name,
                "message": f"{self.name} is registered but not configured — set required env vars to enable.",
                "kwargs": kwargs,
            }
        if not self.execute_script or not self.execute_script.exists():
            return {
                "ok": False,
                "error": f"no execute script found for {self.name}",
            }
        cmd = ["python3", str(self.execute_script)]
        for k, v in kwargs.items():
            cmd += [f"--{k.replace('_', '-')}", str(v)]
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=30,
                cwd=self.skill_dir,
            )
            return {
                "ok": result.returncode == 0,
                "output": result.stdout.strip(),
                "stderr": result.stderr.strip() if result.stderr.strip() else None,
                "tool": self.name,
            }
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "timeout", "tool": self.name}
        except Exception as e:
            return {"ok": False, "error": str(e), "tool": self.name}


class ToolRegistry:
    """Discover and index all Custodian-governed skills under a root dir."""

    def __init__(self, skills_root: Path):
        self.skills_root = Path(skills_root)
        self._tools: dict[str, CustodianTool] = {}
        self._loaded = False

    def _parse_frontmatter(self, text: str) -> dict:
        m = _FRONTMATTER.match(text.strip())
        if not m:
            return {}
        try:
            return yaml.safe_load(m.group(1)) or {}
        except yaml.YAMLError:
            return {}

    def load(self) -> "ToolRegistry":
        """Scan skills_root for SKILL.md files with custodian metadata."""
        self._tools = {}
        for skill_md in self.skills_root.rglob("SKILL.md"):
            try:
                text = skill_md.read_text()
                meta = self._parse_frontmatter(text)
                custodian_meta = (meta.get("metadata") or {}).get("custodian") or {}
                band = custodian_meta.get("band")
                if not band:
                    continue  # not a governed skill
                name = meta.get("name") or skill_md.parent.name
                execute = skill_md.parent / "scripts" / "execute.py"
                tool = CustodianTool(
                    name=name,
                    description=meta.get("description", ""),
                    band=str(band),
                    cost_usd=float(custodian_meta.get("cost_usd", 0.0)),
                    configured=bool(custodian_meta.get("configured", True)),
                    skill_dir=skill_md.parent,
                    tags=list(meta.get("metadata", {}).get("hermes", {}).get("tags", [])),
                    version=str(meta.get("version", "1.0.0")),
                    execute_script=execute if execute.exists() else None,
                )
                self._tools[name] = tool
            except Exception:
                continue
        self._loaded = True
        return self

    def all(self) -> list[CustodianTool]:
        if not self._loaded:
            self.load()
        return sorted(self._tools.values(), key=lambda t: (t.band, t.name))

    def get(self, name: str) -> Optional[CustodianTool]:
        if not self._loaded:
            self.load()
        return self._tools.get(name)

    def by_band(self, band: str) -> list[CustodianTool]:
        return [t for t in self.all() if t.band == band]

    def configured_only(self) -> list[CustodianTool]:
        return [t for t in self.all() if t.configured]

    def summary(self) -> dict:
        tools = self.all()
        by_band: dict[str, int] = {}
        for t in tools:
            by_band[t.band] = by_band.get(t.band, 0) + 1
        return {
            "total": len(tools),
            "configured": sum(1 for t in tools if t.configured),
            "stubs": sum(1 for t in tools if not t.configured),
            "by_band": by_band,
        }


def default_registry() -> ToolRegistry:
    """Return registry pointed at the canonical skills/ directory."""
    here = Path(__file__).resolve()
    # walk up to find the repo root (contains skills/)
    for parent in here.parents:
        candidate = parent / "skills"
        if candidate.is_dir():
            return ToolRegistry(candidate)
    return ToolRegistry(Path("skills"))
