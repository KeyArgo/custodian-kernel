#!/usr/bin/env python3
"""paladin-import tool: bulk credential import, value-free output.

Invoked by the Custodian tool registry as
``execute.py --source X [--path P] [--dry-run true] ...`` after the kernel
gate (band L2) has passed. Prints ONE JSON object to stdout. That object
carries names, kinds, sources, and counts — never a secret value: this
script's stdout goes straight into the agent's context, so a value here
would hand the agent exactly what Paladin exists to keep from it.
"""
import argparse
import json
import sys
from pathlib import Path


def _ensure_paladin_importable() -> None:
    """Running installed, `paladin` sits in site-packages next to `custodian`
    and imports fine. Running as a bare script from a repo checkout, nothing
    put the repo root on sys.path — walk up from this file until we find the
    directory that contains the paladin package and add it."""
    try:
        import paladin  # noqa: F401
        return
    except ImportError:
        pass
    for parent in Path(__file__).resolve().parents:
        if (parent / "paladin" / "__init__.py").exists():
            sys.path.insert(0, str(parent))
            return


_ensure_paladin_importable()


def _bool(v):
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--source", required=True,
                   choices=["discover", "env", "csv", "json", "bitwarden", "1password"])
    p.add_argument("--path", default=None)
    p.add_argument("--recursive", default="false")
    p.add_argument("--pattern", default=".env*")
    p.add_argument("--search", default=None)
    p.add_argument("--folder", default=None)
    p.add_argument("--from-vault", dest="from_vault", default=None)
    p.add_argument("--profile", default="default")
    p.add_argument("--dry-run", dest="dry_run", default="false")
    p.add_argument("--overwrite", default="false")
    a = p.parse_args()

    try:
        from paladin import importer as imp
        from paladin.errors import PaladinError, VaultLockedError, VaultMissingError
        from paladin.vault import Vault
    except ImportError as e:
        print(json.dumps({"ok": False, "error": f"paladin not importable: {e}"}))
        return 1

    try:
        if a.source == "discover":
            print(json.dumps(imp.discover()))
            return 0

        if a.source == "env":
            if not a.path:
                raise PaladinError("source=env requires path=<file or directory>")
            from pathlib import Path
            root = Path(a.path).expanduser()
            files = imp.collect_env_files(root, pattern=a.pattern,
                                          recursive=_bool(a.recursive))
            if not files:
                raise PaladinError(f"no files matching {a.pattern!r} under {root}")
            candidates = [c for f in files for c in imp.candidates_from_env(f)]
        elif a.source in ("csv", "json"):
            if not a.path:
                raise PaladinError(f"source={a.source} requires path=<file>")
            from pathlib import Path
            fpath = Path(a.path).expanduser()
            if not fpath.is_file():
                raise PaladinError(f"no such file: {fpath}")
            reader = (imp.candidates_from_csv if a.source == "csv"
                      else imp.candidates_from_json)
            candidates = reader(fpath)
        elif a.source == "bitwarden":
            candidates = imp.bitwarden_candidates(search=a.search, folder=a.folder)
        else:
            candidates = imp.onepassword_candidates(vault=a.from_vault,
                                                    search=a.search)

        try:
            vault = Vault.open_from_env(interactive=False)
        except (VaultLockedError, VaultMissingError) as e:
            print(json.dumps({
                "ok": False, "locked": True,
                "message": (f"paladin vault is not unlockable non-interactively "
                            f"({e}). Ask the human to set PALADIN_PASSPHRASE / "
                            f"PALADIN_KEYFILE, or run `paladin init` first."),
            }))
            return 1
        try:
            report = imp.import_candidates(
                vault, candidates, profile=a.profile, dry_run=_bool(a.dry_run),
                skip_existing=not _bool(a.overwrite))
            if not _bool(a.dry_run) and report.imported:
                from paladin.broker import Broker
                Broker(vault).audit.append(
                    "add", f"import:{a.source}", "adapter:paladin-import", "-",
                    f"count={len(report.imported)} "
                    f"skipped={len(report.skipped_existing)}")
        finally:
            vault.close()
        print(json.dumps(report.to_dict()))
        return 0
    except PaladinError as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
