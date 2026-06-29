#!/usr/bin/env bash
# Sync the custodian kernel to both enforcement nodes and restart services.
# Run after any kernel code change or pip update.
#
# Usage:
#   ./deploy-kernel.sh               — update both nodes
#   SKIP_SPARK=1 ./deploy-kernel.sh  — argobox-lite only (if kronos is down)
#   SKIP_LITE=1  ./deploy-kernel.sh  — Spark only

set -euo pipefail

REPO="$(cd "$(dirname "$0")" && pwd)"
SPARK_HOST="bogart@192.168.50.56"
SPARK_DIR="/home/bogart/custodian-kernel"
SPARK_VENV="/home/bogart/custodian-venv"
LITE_HOST="argonaut@10.0.0.199"
LITE_APP_DIR="/tmp/hermes-dash-v4"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
ok()   { echo -e "${GREEN}✓ $*${NC}"; }
warn() { echo -e "${YELLOW}⚠ $*${NC}"; }
err()  { echo -e "${RED}✗ $*${NC}"; }

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Custodian kernel deploy — $(date '+%Y-%m-%d %H:%M:%S')"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# ── DGX Spark (primary enforcement node) ──────────────────────────────────────
if [[ "${SKIP_SPARK:-}" != "1" ]]; then
  echo ""
  echo "→ DGX Spark (primary enforcement node)"
  if ssh -o ConnectTimeout=4 -o BatchMode=yes "$SPARK_HOST" true 2>/dev/null; then
    rsync -a --delete --exclude='__pycache__' --exclude='*.pyc' --exclude='.git' \
      --exclude='build' --exclude='*.egg-info' \
      "$REPO/custodian/" "$SPARK_HOST:$SPARK_DIR/custodian/"
    rsync -a "$REPO/spark-enforcement/enforce_server.py" "$SPARK_HOST:$SPARK_DIR/"
    ssh "$SPARK_HOST" "
      pkill -f enforce_server.py 2>/dev/null || true
      sleep 1
      cd $SPARK_DIR
      nohup $SPARK_VENV/bin/python3 enforce_server.py > /home/bogart/custodian-enforce.log 2>&1 &
      sleep 2
      curl -sf http://localhost:8095/health && echo '' || echo 'HEALTH CHECK FAILED'
    "
    ok "Spark enforcement node updated and running"
  else
    warn "Spark unreachable — skipping (argobox-lite will enforce locally)"
  fi
fi

# ── argobox-lite (API server + local fallback enforcement) ─────────────────────
if [[ "${SKIP_LITE:-}" != "1" ]]; then
  echo ""
  echo "→ argobox-lite (API + failover node)"
  if ssh -o ConnectTimeout=4 -o BatchMode=yes "$LITE_HOST" true 2>/dev/null; then
    rsync -a --delete --exclude='__pycache__' --exclude='*.pyc' --exclude='.git' \
      --exclude='build' --exclude='*.egg-info' --exclude='secrets' \
      "$REPO/custodian/" "$LITE_HOST:$LITE_APP_DIR/custodian/"
    rsync -a --exclude='__pycache__' --exclude='*.pyc' --exclude='secrets' \
      "$REPO/dashboard/" "$LITE_HOST:$LITE_APP_DIR/dashboard/"
    ssh "$LITE_HOST" "
      PID=\$(ss -tlnp 2>/dev/null | grep ':8094' | grep -oP 'pid=\K[0-9]+' | head -1 || true)
      [ -n \"\$PID\" ] && kill \$PID && sleep 1
      cd $LITE_APP_DIR/dashboard
      nohup /tmp/hermes-dash-venv/bin/python3 app.py > /tmp/hermes-dash.log 2>&1 &
      sleep 2
      curl -sf http://localhost:8094/api/v1/hermes/summary > /dev/null && echo 'api ok' || echo 'API HEALTH CHECK FAILED'
    "
    ok "argobox-lite updated and running"
  else
    err "argobox-lite unreachable — demo will be down"
    exit 1
  fi
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
ok "Deploy complete"
SPARK_STATUS=$(ssh -o ConnectTimeout=3 -o BatchMode=yes "$SPARK_HOST" \
  'curl -sf http://localhost:8095/health 2>/dev/null' 2>/dev/null \
  || echo '{"ok":false,"node":"dgx-spark","role":"unreachable — fallback active"}')
echo "  Spark: $SPARK_STATUS"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
