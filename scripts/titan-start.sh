#!/bin/bash
# Custodian Flask — Titan failover node
# Deploy: rsync dashboard/ to root@titan:/opt/custodian-dash/
# Run: bash /opt/custodian-dash/start-titan.sh
# Secrets needed: copy stripe.env + operator.env to /opt/custodian-dash/secrets/

SECRETS_DIR="/opt/custodian-dash/secrets"
set -a
[ -f "$SECRETS_DIR/stripe.env" ]   && source "$SECRETS_DIR/stripe.env"
[ -f "$SECRETS_DIR/operator.env" ] && source "$SECRETS_DIR/operator.env"
set +a

cd /opt/custodian-dash
exec /opt/custodian-venv/bin/python3 app.py
