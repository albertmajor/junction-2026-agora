#!/bin/sh
# Deploy Price Monkey.   scripts/deploy.sh [api|web]   (no argument: both)
#   api  Railway, service "api": builds the Dockerfile in the repo root from the files in this folder
#   web  Vercel, pricemonkey.eu: a static copy of agora/web; every other path is passed on to the Railway API
# Needs the railway and vercel CLIs, and four values from Robert in .env.deploy (git ignores it):
#   RAILWAY_TOKEN=...  VERCEL_TOKEN=...  VERCEL_ORG_ID=...  VERCEL_PROJECT_ID=...
# DRY=1 scripts/deploy.sh   checks the values and builds the page folder, but deploys nothing.
set -eu
cd "$(dirname "$0")/.."
if [ -f .env.deploy ]; then set -a; . ./.env.deploy; set +a; fi
what=${1:-all}
case $what in api|web|all) ;; *) echo "usage: scripts/deploy.sh [api|web]" >&2; exit 2 ;; esac

if [ "$what" != web ]; then
  : "${RAILWAY_TOKEN:?missing: put it in .env.deploy (ask Robert)}"
  export RAILWAY_TOKEN
  if [ -n "${DRY:-}" ]; then echo "dry run: would run 'railway up --service api --ci' from $(pwd)"
  else railway up --service api --ci; fi
fi

if [ "$what" != api ]; then
  : "${VERCEL_TOKEN:?missing: put it in .env.deploy (ask Robert)}"
  : "${VERCEL_ORG_ID:?missing: put it in .env.deploy (ask Robert)}"
  : "${VERCEL_PROJECT_ID:?missing: put it in .env.deploy (ask Robert)}"
  export VERCEL_ORG_ID VERCEL_PROJECT_ID
  out=$(mktemp -d)
  cp -R agora/web "$out/web"                  # the page asks for /web/js/..., /web/css/...
  cp agora/web/index.html "$out/index.html"   # and / is the page itself
  cat > "$out/vercel.json" <<'JSON'
{
  "rewrites": [{ "source": "/:path*", "destination": "https://api-production-3ec509d9.up.railway.app/:path*" }],
  "headers": [{ "source": "/web/(js|css)/(.*)", "headers": [{ "key": "Cache-Control", "value": "no-cache" }] }]
}
JSON
  if [ -n "${DRY:-}" ]; then echo "dry run: would deploy $out to Vercel (production):"; ls "$out"
  else vercel deploy "$out" --prod --yes --token "$VERCEL_TOKEN"; fi
fi
