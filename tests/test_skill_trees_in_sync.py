"""skills/ and custodian/bundled_skills/ must stay byte-identical.

Both trees are LIVE. `custodian.tools.registry.default_registry()` walks up
from the package looking for a workspace `skills/` and only falls back to the
packaged `bundled_skills/` when it finds none. So a cloned repo (and anything
deployed from one) runs `skills/`, while `pip install custodian-kernel` runs
`bundled_skills/`. Which money code executes depends on how you installed.

They diverged silently and it cost real correctness:

* 652c1b2 added a Stripe mock fallback and atomic writes to `bundled_skills`
  only. The tree that actually runs in a clone never got either -- so
  CUSTODIAN_STRIPE_MOCK=true did nothing there and charged real money -- while
  the tree pip users get had an `_atomic_write` that raised on every call,
  losing every spend it made.
* `custodian-meta/` (custodian-status, custodian-anchor, paladin-vault-list)
  existed only in `skills/`, so pip-installed users were missing three skills
  that `talaria.introspection.META_SKILLS` names explicitly.

Neither was caught, because nothing compared the trees. This does.

If this fails: do not "fix" it by copying blindly -- work out which side is
newer, port the real change, and copy. The whole point is that a difference
here is a decision, not an accident.
"""
import hashlib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
WORKSPACE = REPO / "skills"
BUNDLED = REPO / "custodian" / "bundled_skills"

IGNORE = {"__pycache__", ".pytest_cache"}


def _files(root: Path) -> dict[str, str]:
    """Relative path -> sha256, skipping generated dirs."""
    out = {}
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if any(part in IGNORE for part in p.relative_to(root).parts):
            continue
        if p.suffix in {".pyc", ".pyo"}:
            continue
        out[p.relative_to(root).as_posix()] = hashlib.sha256(
            p.read_bytes()
        ).hexdigest()
    return out


@pytest.mark.skipif(
    not WORKSPACE.is_dir() or not BUNDLED.is_dir(),
    reason="only meaningful in a cloned repo where both trees exist",
)
def test_skill_trees_contain_the_same_files():
    ws, bd = _files(WORKSPACE), _files(BUNDLED)
    only_workspace = sorted(set(ws) - set(bd))
    only_bundled = sorted(set(bd) - set(ws))
    assert not only_workspace, (
        "present in skills/ but NOT packaged -- pip users will not get these:\n  "
        + "\n  ".join(only_workspace)
    )
    assert not only_bundled, (
        "packaged but missing from skills/ -- a clone will not run these:\n  "
        + "\n  ".join(only_bundled)
    )


@pytest.mark.skipif(
    not WORKSPACE.is_dir() or not BUNDLED.is_dir(),
    reason="only meaningful in a cloned repo where both trees exist",
)
def test_skill_trees_have_identical_contents():
    ws, bd = _files(WORKSPACE), _files(BUNDLED)
    differing = sorted(k for k in set(ws) & set(bd) if ws[k] != bd[k])
    assert not differing, (
        "same path, different bytes -- a clone and a pip install would run "
        "DIFFERENT code:\n  " + "\n  ".join(differing)
    )
