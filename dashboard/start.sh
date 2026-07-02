#!/bin/bash
# Always include argonaut local bin so nemohermes is found
export PATH="/home/argonaut/.local/bin:/home/argonaut/.nvm/versions/node/v22.23.0/bin:$PATH"
cd /tmp/hermes-dash-v4/dashboard
source /tmp/hermes-dash-venv/bin/activate
# Source secrets into env so Flask can read them via os.environ
set -a
[ -f secrets/stripe.env ] && source secrets/stripe.env
[ -f secrets/nvidia.env ] && source secrets/nvidia.env
set +a
exec python app.py "$@"
