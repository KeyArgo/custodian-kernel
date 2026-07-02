#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

# Load secrets from env files
set -a
[ -f secrets/stripe.env ] && source secrets/stripe.env
[ -f secrets/openrouter.env ] && source secrets/openrouter.env
[ -f secrets/resend.env ] && source secrets/resend.env
set +a

export CUSTODIAN_DEMO_EMAIL=bogart000@gmail.com

python3 -m custodian.cli.main demo cycle
