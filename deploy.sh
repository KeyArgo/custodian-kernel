#!/usr/bin/env bash
# Deploy pages-frontend to Cloudflare Pages (rein-custodian project)
set -e
cd "$(dirname "$0")"
env -u CF_API_TOKEN CLOUDFLARE_API_TOKEN="$CF_PAGES_TOKEN" \
  /home/argo/.npm-global/bin/wrangler pages deploy pages-frontend \
  --project-name rein-custodian --commit-dirty=true
