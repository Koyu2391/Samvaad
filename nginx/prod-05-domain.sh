#!/bin/sh
# Runs inside the frontend container via /docker-entrypoint.d (before nginx starts).
# Renders TLS_DOMAIN into the prod nginx template. Fails fast on misconfig.
set -eu

TEMPLATE=/etc/nginx/nginx.prod.template
TARGET=/etc/nginx/nginx.conf

if [ ! -f "$TEMPLATE" ]; then
  echo "05-domain: no $TEMPLATE mounted, keeping baked nginx.conf" >&2
  exit 0
fi

if [ -z "${TLS_DOMAIN:-}" ]; then
  echo "05-domain: TLS_DOMAIN is not set" >&2
  exit 1
fi

CERT=/etc/letsencrypt/live/${TLS_DOMAIN}/fullchain.pem
KEY=/etc/letsencrypt/live/${TLS_DOMAIN}/privkey.pem
if [ ! -f "$CERT" ] || [ ! -f "$KEY" ]; then
  echo "05-domain: cert/key missing for ${TLS_DOMAIN} ($CERT)" >&2
  exit 1
fi

sed "s/CHANGE_ME_YOUR_DOMAIN/${TLS_DOMAIN}/g" "$TEMPLATE" > "$TARGET"
echo "05-domain: rendered nginx.conf for ${TLS_DOMAIN}"
nginx -t -c "$TARGET"
