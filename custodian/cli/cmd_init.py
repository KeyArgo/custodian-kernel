from __future__ import annotations

import shutil
from pathlib import Path

from custodian.policy.loader import load_policy
from custodian.storage.sqlite import SqliteStorage
from custodian.types import AuthorityState

_PRESET_PATH = Path(__file__).resolve().parent.parent / "policy" / "presets" / "default.yaml"

# The session budget has no policy field -- bands only carry a per-action
# max_spend -- so it is a runtime default. This value is the one the default
# preset's own header documents ("$2.00 per-action cap, $10.00 session cap").
DEFAULT_SESSION_CAP = 10.00


def run(args) -> None:
    target = Path(args.dir).resolve()
    target.mkdir(parents=True, exist_ok=True)

    policy_dest = target / "policy.yaml"
    policy_was_preexisting = policy_dest.exists()
    if policy_was_preexisting:
        print(f"policy.yaml already exists at {policy_dest}, skipping")
    else:
        if not _PRESET_PATH.exists():
            print(f"error: default policy preset not found at {_PRESET_PATH}")
            raise SystemExit(1)
        shutil.copy2(str(_PRESET_PATH), str(policy_dest))
        print(f"created {policy_dest}")

    state_dir = target / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    print(f"created {state_dir}/")

    secrets_dir = target / "secrets"
    secrets_dir.mkdir(parents=True, exist_ok=True)
    print(f"created {secrets_dir}/")

    gitkeep = secrets_dir / ".gitkeep"
    gitkeep.write_text("")
    print(f"created {gitkeep}")

    readme = secrets_dir / "README.md"
    readme.write_text(
        "# Secrets Directory\n\n"
        "Supply your secret files here. These files are never committed.\n"
        "See custodian documentation for required environment variables and file formats.\n"
    )
    print(f"created {readme}")

    # Initialize the authority state, so `init` actually initializes. Without
    # this it created an empty state/ dir and left the workspace stateless:
    # every subsequent command printed "warning: no authority state found,
    # using defaults", and `custodian status` answered "No authority state
    # initialized" immediately after init announced the opposite. Deriving the
    # cap from the policy also means editing policy.yaml before the first
    # request is honoured, rather than silently overridden by a hardcoded 2.0.
    db_path = state_dir / "custodian.db"
    if db_path.exists():
        print(f"authority state already exists at {db_path}, skipping")
    else:
        session_cap = getattr(args, "session_cap", None) or DEFAULT_SESSION_CAP
        try:
            policy = load_policy(policy_dest)
            band = policy.default_band
            cap = policy.bands[band].max_spend
            state = AuthorityState(
                band=band,
                # max_spend is None for an unbounded band (L4). The session cap
                # is then the only ceiling left, so use it rather than writing
                # a None the state schema does not accept.
                per_action_cap=session_cap if cap is None else float(cap),
                session_cap=session_cap,
                spent_this_session=0.0,
            )
            if state.per_action_cap > state.session_cap:
                # Not an error -- the session budget is legitimately the tighter
                # ceiling -- but a per-action cap above it can never be reached,
                # so the band's max_spend is dead config and every request that
                # relies on it escalates for a reason the operator did not set.
                # Worth saying out loud, because session_cap is not editable in
                # policy.yaml and they would otherwise have nowhere to look.
                print(f"warning: band {band.value} allows ${state.per_action_cap:.2f} per "
                      f"action but the session cap is ${state.session_cap:.2f}, so no single "
                      f"action can use the full band. Raise it with "
                      f"--session-cap if that is not what you want.")
            SqliteStorage(db_path).save_authority_state(state)
            print(f"created {db_path} "
                  f"(band {band.value}, ${state.per_action_cap:.2f} per action, "
                  f"${state.session_cap:.2f} session)")
        except Exception as e:
            if policy_was_preexisting:
                # Their policy.yaml, not ours -- quite possibly a stub they are
                # still writing. Scaffolding succeeded, so don't fail the whole
                # command because state cannot be derived from it yet. Say what
                # was skipped and how to finish.
                print(f"note: authority state not initialized — policy.yaml did not "
                      f"load ({e}). Fix it and run 'custodian init' again.")
            else:
                # We just wrote this file from our own preset. If it does not
                # load, the package is broken, and a scaffold that
                # half-succeeded is worse than one that says so.
                print(f"error: the default policy preset was written but did not "
                      f"load: {e}")
                raise SystemExit(1)

    print("\nCustodian workspace initialized. Edit policy.yaml to configure authority bands.")

    # The other commands default to ./policy.yaml and ./state, so a workspace
    # scaffolded into a subdirectory only works if the user cd's in (or passes
    # --state-dir/--policy). Spell out the exact next steps rather than leaving
    # `validate policy.yaml` / `status` to fail from the current directory.
    cwd = Path.cwd().resolve()
    if target != cwd:
        try:
            rel = target.relative_to(cwd)
            hint = str(rel)
        except ValueError:
            hint = str(target)
        print("\nNext steps:")
        print(f"  cd {hint}")
        print("  custodian validate policy.yaml")
        print("  custodian request --amount 1.00 --description \"first request\"")
        print("  custodian status")
    else:
        print("\nNext steps:")
        print("  custodian validate policy.yaml")
        print("  custodian request --amount 1.00 --description \"first request\"")
        print("  custodian status")
