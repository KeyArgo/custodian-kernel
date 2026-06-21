from __future__ import annotations

import shutil
from pathlib import Path

_PRESET_PATH = Path(__file__).resolve().parent.parent / "policy" / "presets" / "default.yaml"


def run(args) -> None:
    target = Path(args.dir).resolve()
    target.mkdir(parents=True, exist_ok=True)

    policy_dest = target / "policy.yaml"
    if policy_dest.exists():
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

    print("\nCustodian workspace initialized. Edit policy.yaml to configure authority bands.")
