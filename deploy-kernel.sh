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
SPARK_A_HOST="argo@10.0.0.50"
SPARK_B_HOST="argo@10.0.0.51"
SPARK_DIR="/home/argo/custodian-kernel"
SPARK_VENV="/home/argo/custodian-venv"
LITE_HOST="argonaut@10.0.0.199"
LITE_APP_DIR="/tmp/hermes-dash-v4"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
ok()   { echo -e "${GREEN}✓ $*${NC}"; }
warn() { echo -e "${YELLOW}⚠ $*${NC}"; }
err()  { echo -e "${RED}✗ $*${NC}"; }

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Custodian kernel deploy — $(date '+%Y-%m-%d %H:%M:%S')"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# ── DGX Spark node(s) — spark-a primary, spark-b secondary ───────────────────
deploy_spark_node() {
  local label="$1" host="$2"
  echo ""
  echo "→ DGX Spark $label ($host)"
  if ssh -o ConnectTimeout=4 -o BatchMode=yes "$host" true 2>/dev/null; then
    rsync -a --delete --exclude='__pycache__' --exclude='*.pyc' --exclude='.git' \
      --exclude='build' --exclude='*.egg-info' \
      "$REPO/custodian/" "$host:$SPARK_DIR/custodian/"
    rsync -a "$REPO/spark-enforcement/enforce_server.py" "$host:$SPARK_DIR/"
    ssh -t "$host" "
      sudo systemctl restart custodian-enforce
      sleep 2
      curl -sf http://localhost:8095/health && echo '' || echo 'HEALTH CHECK FAILED'
    "
    ok "Spark $label ($host) updated and running"
  else
    warn "Spark $label ($host) unreachable — skipping"
  fi
}

if [[ "${SKIP_SPARK:-}" != "1" ]]; then
  deploy_spark_node "spark-a" "$SPARK_A_HOST"
  deploy_spark_node "spark-b" "$SPARK_B_HOST"
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
    # Restart the production gunicorn service (NOT the argonaut-owned nohup
    # python3 process, which is not what serves production traffic).
    # custodian-dashboard.service runs gunicorn listening on :8094 — that's
    # the process the CF Worker proxies to. Without restarting it, gunicorn
    # serves stale .pyc files from its previous boot. (Bug-hunt 2026-07-03.)
    ssh "$LITE_HOST" "
      sudo systemctl restart custodian-dashboard.service
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
for pair in "spark-a:$SPARK_A_HOST" "spark-b:$SPARK_B_HOST"; do
  label="${pair%%:*}"; host="${pair#*:}"
  status=$(ssh -o ConnectTimeout=3 -o BatchMode=yes "$host" \
    'curl -sf http://localhost:8095/health 2>/dev/null' 2>/dev/null \
    || echo "{\"ok\":false,\"node\":\"$label\",\"role\":\"unreachable — fallback active\"}")
  echo "  $label: $status"
done
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
