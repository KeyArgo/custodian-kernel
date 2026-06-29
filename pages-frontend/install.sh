#!/usr/bin/env bash
# Custodian quickstart — installs the kernel, scaffolds a workspace,
# optionally starts the NemoClaw sandbox if Docker is available.
set -euo pipefail

GREEN='\033[92m'
AMBER='\033[93m'
DIM='\033[90m'
RESET='\033[0m'
BOLD='\033[1m'

header() { echo -e "\n${BOLD}→ $1${RESET}"; }
ok()     { echo -e "  ${GREEN}✓${RESET} $1"; }
warn()   { echo -e "  ${AMBER}!${RESET} $1"; }
dim()    { echo -e "  ${DIM}$1${RESET}"; }

echo -e "${BOLD}"
echo "============================================"
echo " CUSTODIAN QUICKSTART"
echo " Kernel-enforced authority for AI agents"
echo "============================================"
echo -e "${RESET}"
dim "Runtime: ~60 seconds · No credentials required for the demo"

# ── 1. Python check ────────────────────────────────────────────────────────
header "Checking Python version"
if ! command -v python3 &>/dev/null; then
    echo "  ✗ python3 not found. Install Python 3.11+ and re-run this script."
    exit 1
fi
PYVER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PYMAJ=$(echo "$PYVER" | cut -d. -f1)
PYMIN=$(echo "$PYVER" | cut -d. -f2)
if [ "$PYMAJ" -lt 3 ] || { [ "$PYMAJ" -eq 3 ] && [ "$PYMIN" -lt 11 ]; }; then
    echo "  ✗ Python $PYVER found. Custodian requires 3.11+."
    exit 1
fi
ok "Python $PYVER"

# ── 2. Install custodian-kernel ────────────────────────────────────────────
header "Installing custodian-kernel"
dim "pip install custodian-kernel"
if pip install custodian-kernel -q 2>&1; then
    ok "custodian-kernel installed"
else
    warn "pip install failed — trying with --user flag"
    pip install custodian-kernel -q --user
    ok "custodian-kernel installed (user)"
fi

# ── 3. Verify the install ──────────────────────────────────────────────────
header "Running claim verifier demo"
dim "custodian demo-verify"
echo ""
custodian demo-verify
echo ""

# ── 4. Scaffold a workspace ────────────────────────────────────────────────
WORKSPACE="${1:-myagent}"
header "Scaffolding workspace at ./$WORKSPACE"
custodian init --dir "$WORKSPACE"
ok "Workspace ready at ./$WORKSPACE"
dim "Edit $WORKSPACE/policy.yaml to configure spend caps and authority bands"

# ── 5. Docker / NemoClaw (optional) ───────────────────────────────────────
header "Checking for Docker (NemoClaw sandbox)"
if command -v docker &>/dev/null && docker info &>/dev/null 2>&1; then
    ok "Docker detected"
    dim "Building the Custodian kernel container..."
    if docker build -q -t custodian-kernel:latest "$(pip show custodian-kernel 2>/dev/null | grep Location | awk '{print $2}')/../../hermes-hackathon-2026" 2>/dev/null; then
        ok "custodian-kernel Docker image built"
        dim "Run: docker run --rm custodian-kernel:latest custodian demo-verify"
    else
        # Fall back to pulling from source if available
        REPO_DIR="$(dirname "$(realpath "${BASH_SOURCE[0]}")")"
        if [ -f "$REPO_DIR/Dockerfile" ]; then
            dim "Building from local repo..."
            docker build -q -t custodian-kernel:latest "$REPO_DIR"
            ok "custodian-kernel:latest built from source"
            dim "Run: docker run --rm custodian-kernel:latest custodian demo-verify"
        else
            warn "Docker available but no image source found — skipping container build"
            dim "Clone the repo and run: docker build -t custodian-kernel:latest ."
        fi
    fi
    echo ""
    dim "NemoClaw sandbox (full Landlock LSM isolation) requires Linux + NVIDIA drivers."
    dim "If you have a DGX or Spark node, see docs/NEMOCLAW.md for the full setup."
else
    warn "Docker not detected — skipping NemoClaw sandbox setup"
    dim "The Python kernel works without Docker. Docker enables full Landlock LSM isolation."
fi

# ── 6. Next steps ─────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}============================================"
echo -e " ${GREEN}CUSTODIAN READY${RESET}${BOLD}"
echo "============================================${RESET}"
echo ""
echo "  Quick commands:"
echo -e "    ${AMBER}custodian request --amount 1.00 --description 'API call'${RESET}"
echo -e "    ${AMBER}custodian status${RESET}"
echo -e "    ${AMBER}custodian tools list${RESET}"
echo -e "    ${AMBER}custodian demo-verify${RESET}   # run the claim verifier demo"
echo ""
echo -e "  Prove the security guarantee:"
echo -e "    ${AMBER}python3 verify_kit.py${RESET}   # 90-second self-verifying proof"
echo ""
echo -e "  Docs: ${DIM}https://getcustodian.xyz${RESET}"
echo -e "  Repo: ${DIM}https://git.argobox.com/KeyArgo/hermes-hackathon-2026${RESET}"
echo ""
