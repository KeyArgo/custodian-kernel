"""Custodian tool layer — governed Hermes skills.

Any skill directory containing a SKILL.md with a `custodian-band:` field in
its YAML frontmatter is automatically registered as a Custodian-governed tool.
The kernel checks the declared band before the skill's execute script runs.
Adding `custodian-band: L1` to an existing Hermes skill is the entire
integration cost.
"""
from custodian.tools.registry import ToolRegistry, CustodianTool

__all__ = ["ToolRegistry", "CustodianTool"]
