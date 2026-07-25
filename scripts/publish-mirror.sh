#!/usr/bin/env bash
# Publish gate between custodian-dev (private, source of truth) and the
# public PyPI-mirror repos (custodian-kernel, custodian-codex-guard).
#
# custodian-dev is the only repo anyone edits directly. The mirror repos
# are public on GitHub and get updated ONLY through this script's reviewed,
# opt-in diff -- never by committing/pushing them directly. Talaria is not
# handled here: it is developed directly in its own public repo, not
# subtree-synced from custodian-dev (see docs/PUBLISH_GATE.md).
#
# Usage:
#   scripts/publish-mirror.sh <kernel|codex-guard>            dry run: show diff only, change nothing
#   scripts/publish-mirror.sh <kernel|codex-guard> --apply    copy changed/new files into the target
#                                                              working tree. Never runs git add/commit/push --
#                                                              that stays a separate, deliberate step you take
#                                                              by hand in the target repo after reviewing
#                                                              `git diff`/`git status` there yourself.
set -euo pipefail

SRC_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET="${1:-}"
APPLY="${2:-}"

case "$TARGET" in
  kernel)
    DEST_ROOT="/mnt/homes/Development/custodian-kernel"
    # custodian-kernel ships custodian/ and paladin/ verbatim, minus the
    # adapter packages that ship as their own separate PyPI distributions.
    MAPPINGS=(
      "custodian:custodian"
      "paladin:paladin"
      "skills:skills"
      "packaging/kernel/pyproject.toml:pyproject.toml"
      "packaging/kernel/MANIFEST.in:MANIFEST.in"
      "packaging/kernel/README.md:README.md"
      "scripts/install-custodian.py:install-custodian.py"
      "CHANGELOG.md:CHANGELOG.md"
      "docs/SECURITY.md:SECURITY.md"
      "docs/CONTRIBUTING.md:CONTRIBUTING.md"
      "docs/CODE_OF_CONDUCT.md:CODE_OF_CONDUCT.md"
      "LICENSE:LICENSE"
    )
    RSYNC_EXCLUDES=(--exclude=codex_guard --exclude=claude_guard --exclude=opencode_guard \
                     --exclude=opencode-prompts --exclude=__pycache__ --exclude='*.pyc')
    ;;
  codex-guard)
    DEST_ROOT="/mnt/homes/Development/custodian-codex-guard"
    MAPPINGS=(
      "custodian/codex_guard:custodian/codex_guard"
      "plugins/custodian-codex-guard:plugins/custodian-codex-guard"
      "docs/CODEX_GUARD.md:docs/CODEX_GUARD.md"
      "packaging/codex_guard/pyproject.toml:pyproject.toml"
      "packaging/codex_guard/MANIFEST.in:MANIFEST.in"
      "packaging/codex_guard/README.md:README.md"
      "docs/SECURITY.md:SECURITY.md"
      "docs/CONTRIBUTING.md:CONTRIBUTING.md"
      "docs/CODE_OF_CONDUCT.md:CODE_OF_CONDUCT.md"
      "LICENSE:LICENSE"
    )
    RSYNC_EXCLUDES=(--exclude=__pycache__ --exclude='*.pyc')
    ;;
  *)
    echo "Usage: $0 <kernel|codex-guard> [--apply]" >&2
    exit 1
    ;;
esac

if [ ! -d "$DEST_ROOT" ]; then
  echo "Target repo not found at $DEST_ROOT -- aborting, nothing touched." >&2
  exit 1
fi

echo "== Publish gate: custodian-dev -> $TARGET ($DEST_ROOT) =="
echo "Source: $SRC_ROOT"
echo

any_changes=0
for mapping in "${MAPPINGS[@]}"; do
  src_rel="${mapping%%:*}"
  dst_rel="${mapping##*:}"
  src="$SRC_ROOT/$src_rel"
  dst="$DEST_ROOT/$dst_rel"

  if [ -f "$src" ]; then
    # single-file mapping (e.g. docs/CODEX_GUARD.md)
    if ! diff -q "$src" "$dst" >/dev/null 2>&1; then
      any_changes=1
      echo "--- CHANGED FILE: $dst_rel ---"
      diff -u "$dst" "$src" || true
      echo
      if [ "$APPLY" = "--apply" ]; then
        cp "$src" "$dst"
        echo "applied: $dst_rel"
      fi
    fi
    continue
  fi

  mkdir -p "$dst"
  echo "-- $src_rel --"
  # Dry-run itemized summary first (always shown)
  rsync -rcn --itemize-changes --delete "${RSYNC_EXCLUDES[@]}" "$src/" "$dst/" | sed '/^$/d' | while read -r line; do
    echo "  $line"
    any_changes=1
  done

  if [ "$APPLY" = "--apply" ]; then
    rsync -rc --delete "${RSYNC_EXCLUDES[@]}" "$src/" "$dst/"
    echo "applied: $src_rel -> $dst_rel"
  fi
  echo
done

echo "== Done =="
if [ "$APPLY" != "--apply" ]; then
  echo "Dry run only -- nothing was changed. Re-run with --apply to copy these files into $DEST_ROOT."
  echo "After --apply, review 'cd $DEST_ROOT && git status && git diff' yourself before committing/pushing."
else
  echo "Files copied into $DEST_ROOT. Nothing was committed or pushed -- do that by hand once you're satisfied."
fi
