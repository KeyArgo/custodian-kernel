"""Entry point for the kernel's skill discovery.

Exposes ``SKILL_ROOT`` pointing at this package's ``skills/`` directory,
which the kernel's discovery code loads via the ``custodian.skills`` entry
point and requires to be an existing directory (``path.is_dir()``).
"""

from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent / "skills"
