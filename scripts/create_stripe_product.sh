#!/usr/bin/env bash
# Create Stripe product + payment link for Custodian AI Safety Review
# Run on argobox-lite where STRIPE_SECRET_KEY is set, or export it first.
# Usage: bash scripts/create_stripe_product.sh

set -euo pipefail

# Load from operator.env if present
ENV_FILE="/tmp/hermes-dash-v4/dashboard/secrets/operator.env"
if [[ -f "$ENV_FILE" ]]; then
  while IFS='=' read -r k v; do
    [[ "$k" =~ ^# ]] && continue
    [[ -z "$k" ]] && continue
    export "$k"="$v"
  done < "$ENV_FILE"
fi

KEY="${STRIPE_SECRET_KEY:-}"
if [[ -z "$KEY" ]]; then
  echo "ERROR: STRIPE_SECRET_KEY not set. Export it or add it to $ENV_FILE"
  exit 1
fi

MODE="TEST"
[[ "$KEY" == sk_live_* ]] && MODE="LIVE"
echo "Using $MODE mode"

stripe_post() {
  local path="$1"; shift
  curl -s -X POST "https://api.stripe.com/v1/$path" \
    -u "$KEY:" \
    "$@"
}

# 1. Create product
echo ""
echo "Creating product..."
PRODUCT=$(stripe_post products \
  -d "name=Custodian AI Safety Review" \
  -d "description=One AI agent governance audit: we run the Custodian verify_kit against your agent workflow, identify policy gaps (self-approval, unbounded spend, missing kill-switch), and deliver a written safety report.")
PRODUCT_ID=$(echo "$PRODUCT" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
echo "  Product: $PRODUCT_ID"

# 2. Create $25 price
echo "Creating price (\$25 each)..."
PRICE=$(stripe_post prices \
  -d "product=$PRODUCT_ID" \
  -d "unit_amount=2500" \
  -d "currency=usd" \
  -d "nickname=AI Safety Review - single seat")
PRICE_ID=$(echo "$PRICE" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
echo "  Price: $PRICE_ID"

# 3. Create payment link (qty=4 so dad can buy 4 seats = $100, or just 1 = $25)
echo "Creating payment link..."
LINK=$(stripe_post payment_links \
  -d "line_items[0][price]=$PRICE_ID" \
  -d "line_items[0][quantity]=4" \
  -d "line_items[0][adjustable_quantity][enabled]=true" \
  -d "line_items[0][adjustable_quantity][minimum]=1" \
  -d "line_items[0][adjustable_quantity][maximum]=4" \
  -d "after_completion[type]=redirect" \
  -d "after_completion[redirect][url]=https://getcustodian.xyz" \
  -d "metadata[source]=hackathon-demo" \
  -d "metadata[product]=custodian-safety-review")
LINK_URL=$(echo "$LINK" | python3 -c "import sys,json; print(json.load(sys.stdin)['url'])")
LINK_ID=$(echo "$LINK" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
echo ""
echo "================================================"
echo "PAYMENT LINK (share this with dad/judges):"
echo "  $LINK_URL"
echo ""
echo "Link ID: $LINK_ID"
echo "Price ID: $PRICE_ID  (save this for the revenue endpoint)"
echo "================================================"
echo ""
echo "Dad buys 4 seats = \$100 total. Or 1 seat = \$25."
echo "Adjustable quantity so he picks at checkout."
