#!/usr/bin/env bash
# Optional persistent HTTPS hostname with the free Tailscale Personal account.
# Prerequisite: tailscale installed and authenticated on the host PC.
set -euo pipefail
cd "$(dirname "$0")/.."
if ! command -v tailscale >/dev/null 2>&1; then
  echo "Installe Tailscale sur ce PC (https://tailscale.com/download), puis connecte-toi." >&2
  exit 1
fi
if ! docker compose version >/dev/null 2>&1; then
  echo "Docker Compose v2 est requis." >&2
  exit 1
fi
if [[ ! -f .env ]]; then (umask 077; touch .env); fi
if ! grep -qE '^APP_API_TOKEN=[A-Za-z0-9_-]{32,}$' .env; then
  if grep -q '^APP_API_TOKEN=' .env; then
    echo "APP_API_TOKEN invalide dans .env." >&2
    exit 1
  fi
  secret="$(python3 -c 'import secrets;print(secrets.token_urlsafe(36))' 2>/dev/null || openssl rand -hex 36)"
  (umask 077; printf 'APP_API_TOKEN=%s\n' "$secret" >> .env)
fi
docker compose up --build -d
# A first invocation may ask the tailnet owner to approve Funnel permissions.
tailscale funnel --bg 8000
status="$(tailscale funnel status 2>&1)"
url="$(printf '%s' "$status" | grep -Eo 'https://[A-Za-z0-9.-]+\.ts\.net' | head -n 1 || true)"
if [[ -z "$url" ]]; then
  echo "Funnel n'a pas fourni de lien HTTPS. Vérifie : tailscale funnel status" >&2
  exit 1
fi
secret="$(sed -n 's/^APP_API_TOKEN=//p' .env | head -n 1)"
printf '\n==== MONTEUR STUDIO : URL HTTPS STABLE ===\n'
printf 'Site Android : https://dbrckk.github.io/monteur-video/\n'
printf 'Moteur : %s\n' "$url"
printf 'Clé privée : %s\n' "$secret"
printf '=========================================\n'
printf 'Le PC doit rester allumé et connecté à Tailscale.\n'
