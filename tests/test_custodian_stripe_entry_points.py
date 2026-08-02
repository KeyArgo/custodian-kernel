"""Verify custodian_stripe's entry-point targets are real, correctly-shaped
objects.

The entry points (declared in packaging/custodian_stripe/pyproject.toml, used
when this package is built and installed as its own standalone distribution)
are:
  - custodian.skills           -> custodian_stripe.skills:SKILL_ROOT
  - custodian.setup_components -> custodian_stripe.setup:COMPONENT
  - custodian.setup_profiles   -> custodian_stripe.setup:PROFILE_COMPONENTS

Resolution through a real installed distribution's importlib.metadata is
verified separately against the release tree built by
scripts/build-custodian-stripe-release-tree.py, not here -- inside this
monorepo, custodian_stripe is a plain sibling package to custodian (both
importable from the same editable install), so there is no second
distribution for importlib.metadata to resolve against.
"""

from pathlib import Path

from custodian_stripe.skills import SKILL_ROOT
from custodian_stripe.setup import COMPONENT, PROFILE_COMPONENTS


def test_skills_entry_point_target_is_existing_dir():
    assert isinstance(SKILL_ROOT, Path)
    assert SKILL_ROOT.is_dir()
    assert SKILL_ROOT.name == "skills"


def test_setup_component_entry_point_target_shape():
    assert isinstance(COMPONENT, dict)
    assert set(COMPONENT) == {"description", "pip_spec"}
    assert isinstance(COMPONENT["description"], str)
    assert isinstance(COMPONENT["pip_spec"], str)


def test_setup_profile_entry_point_target_shape():
    assert PROFILE_COMPONENTS == ["stripe"]
