#!/usr/bin/env bash
# End-to-end acceptance test for a built custodian-kernel install.
#
# Drives the REAL `custodian` and `paladin` CLIs (not the unit tests) through
# the flows a new user actually runs, and asserts the observable behavior.
# Runs identically on Windows (git-bash) and Linux.
#
# Prereqs: install the package into the active environment first, e.g.
#     pip install -e ".[dev,paladin]"          # or your venv equivalent
#     uv pip install -e ".[dev,paladin]"        # if you use uv
# Then:
#     bash scripts/acceptance-test.sh
#
# No network, no Stripe key, and no real money: the CLI decision surface is
# exercised, not live charges. Everything runs under a throwaway temp dir that
# is removed on exit; your real ~/.paladin and ~/.custodian are never touched.

set -u

PASS=0; FAIL=0
WORK="$(mktemp -d 2>/dev/null || echo "${TMPDIR:-/tmp}/custodian-accept.$$")"
mkdir -p "$WORK"
export PALADIN_HOME="$WORK/.paladin"
export PALADIN_PASSPHRASE="acceptance-passphrase"
# A developer or CI runner may normally unlock Paladin with a keyfile. This
# test deliberately creates a fresh passphrase vault; ambient keyfile aliases
# would otherwise override that choice and redirect every command elsewhere.
unset PALADIN_KEYFILE WARDEN_KEYFILE WARDEN_PASSPHRASE
export PYTHONUTF8=1
cleanup() { rm -rf "$WORK"; }
trap cleanup EXIT

ok()   { PASS=$((PASS+1)); printf '  \033[32mPASS\033[0m  %s\n' "$1"; }
bad()  { FAIL=$((FAIL+1)); printf '  \033[31mFAIL\033[0m  %s\n' "$1"; [ -n "${2:-}" ] && printf '        %s\n' "$2"; }
# assert that "$3" (haystack) contains "$2" (needle); label "$1"
has()  { case "$3" in *"$2"*) ok "$1";; *) bad "$1" "expected to see: $2";; esac; }
hasnt(){ case "$3" in *"$2"*) bad "$1" "did NOT expect: $2";; *) ok "$1";; esac; }

section() { printf '\n\033[1m%s\033[0m\n' "$1"; }

# Resolve the CLIs.  When the repository's development virtualenv exists, use
# its scripts explicitly: a same-version global install can otherwise make a
# source-tree acceptance run silently exercise stale code.  Packaged/fresh
# install tests still use the active PATH, then fall back to ``python -m``.
REPO_ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
if [ -x "$REPO_ROOT/.venv-dev/bin/python" ]; then
    PYTHON="$REPO_ROOT/.venv-dev/bin/python"
elif [ -x "$REPO_ROOT/.venv-dev/Scripts/python.exe" ]; then
    PYTHON="$REPO_ROOT/.venv-dev/Scripts/python.exe"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON="python3"
else
    PYTHON="python"
fi
if [ -x "$REPO_ROOT/.venv-dev/bin/custodian" ]; then
    CUSTODIAN="$REPO_ROOT/.venv-dev/bin/custodian"
elif command -v custodian >/dev/null 2>&1; then
    CUSTODIAN="custodian"
else
    CUSTODIAN="$PYTHON -m custodian.cli.main"
fi
if [ -x "$REPO_ROOT/.venv-dev/bin/paladin" ]; then
    PALADIN="$REPO_ROOT/.venv-dev/bin/paladin"
elif command -v paladin >/dev/null 2>&1; then
    PALADIN="paladin"
else
    PALADIN="$PYTHON -m paladin.cli"
fi

printf 'custodian-kernel acceptance test\n'
printf 'work dir: %s\n' "$WORK"
$CUSTODIAN --version 2>&1 | sed 's/^/version: /'

# ---------------------------------------------------------------------------
section "custodian — authority & spend governance"
# ---------------------------------------------------------------------------
cd "$WORK"
out="$($CUSTODIAN init --dir agent 2>&1)"
has "init creates authority state" "custodian.db" "$out"
cd "$WORK/agent"

out="$($CUSTODIAN status 2>&1)"
has "status shows the configured band" "Band: L2" "$out"
hasnt "status has no 'not initialized' warning" "No authority state" "$out"

out="$($CUSTODIAN request --amount 1.00 --description 'api credits' 2>&1)"
has "under-cap spend is autonomous" "AUTONOMOUS" "$out"

out="$($CUSTODIAN request --amount 50.00 --description 'server' 2>&1)"
has "over-cap spend escalates" "ESCALATION_REQUIRED" "$out"

$CUSTODIAN kill --by tester --reason "acceptance" >/dev/null 2>&1
out="$($CUSTODIAN request --amount 0.50 --description 'blocked?' 2>&1)"
has "kill switch denies all spend" "kill switch" "$out"
$CUSTODIAN resume --by tester >/dev/null 2>&1
out="$($CUSTODIAN request --amount 0.50 --description 'after resume' 2>&1)"
has "resume restores normal decisions" "AUTONOMOUS" "$out"

out="$($CUSTODIAN tools list 2>&1)"
has "tool registry lists tools" "tools" "$out"

# ---------------------------------------------------------------------------
section "paladin — credential broker (agent never sees values)"
# ---------------------------------------------------------------------------
out="$($PALADIN init 2>&1)"
has "vault init" "vault created" "$out"

$PALADIN add stripe_key --stdin <<<'sk_test_ABC123SECRET' >/dev/null 2>&1
out="$($PALADIN list 2>&1)"
has "list shows the ref name" "stripe_key" "$out"
hasnt "list never prints the value" "sk_test_ABC123SECRET" "$out"

# Credential injection is proven without printing the value.  Paladin's leak
# guard must redact a child that echoes a secret, so checking the raw value here
# would make the acceptance test demand the vulnerability we just closed.
out="$($PALADIN exec --with stripe_key=STRIPE_KEY -- \
        "$PYTHON" -c "import os,sys; ok=os.environ.get('STRIPE_KEY')=='sk_test_ABC123SECRET'; print('injected-ok' if ok else 'injected-wrong'); sys.exit(0 if ok else 1)" 2>&1)"
has "exec injects the value into the child" "injected-ok" "$out"

# ---------------------------------------------------------------------------
section "paladin import — .env / CSV / JSON (value-free reports)"
# ---------------------------------------------------------------------------
printf 'GITHUB_TOKEN=ghp_realtoken\nDB_PASS="P@ss #withhash"\n' > "$WORK/.env"
out="$($PALADIN import env "$WORK/.env" --dry-run 2>&1)"
has "env import previews names" "github_token" "$out"
hasnt "env import hides values" "ghp_realtoken" "$out"

printf 'name,url,username,password\nAWS,https://aws,me,AKIAEXAMPLE\n' > "$WORK/pw.csv"
out="$($PALADIN import csv "$WORK/pw.csv" --dry-run 2>&1)"
has "csv import auto-detects the password column" "aws" "$out"
hasnt "csv import hides values" "AKIAEXAMPLE" "$out"

printf '{"OPENAI_KEY":"sk-jsonsecret","PORT":8080}\n' > "$WORK/s.json"
out="$($PALADIN import json "$WORK/s.json" --dry-run 2>&1)"
has "json import reads a flat dump" "openai_key" "$out"
hasnt "json import hides values" "sk-jsonsecret" "$out"

# quoted .env value containing '#' must survive intact (regression)
$PALADIN import env "$WORK/.env" >/dev/null 2>&1
out="$($PALADIN exec --with db_pass=DB -- \
        "$PYTHON" -c "import os,sys; ok=os.environ.get('DB')=='P@ss #withhash'; print('quoted-value-ok' if ok else 'quoted-value-wrong'); sys.exit(0 if ok else 1)" 2>&1)"
has "quoted '#' value not truncated" "quoted-value-ok" "$out"

# ---------------------------------------------------------------------------
section "paladin backup / restore (round-trip)"
# ---------------------------------------------------------------------------
$PALADIN backup "$WORK/backup.zip" >/dev/null 2>&1
has "backup archive written" "backup.zip" "$(ls "$WORK" 2>&1)"
PALADIN_HOME="$WORK/.restored" $PALADIN restore "$WORK/backup.zip" >/dev/null 2>&1
out="$(PALADIN_HOME="$WORK/.restored" $PALADIN list 2>&1)"
has "restored vault has the secret" "stripe_key" "$out"
hasnt "restored vault still hides values" "sk_test_ABC123SECRET" "$out"

# ---------------------------------------------------------------------------
printf '\n\033[1mResult: %d passed, %d failed\033[0m\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ] || exit 1
