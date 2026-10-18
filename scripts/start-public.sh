#!/usr/bin/env bash
# Free HTTPS access from Android through a Cloudflare Quick Tunnel.
# Requires Docker with the Compose plugin on a PC that remains switched on.
set -euo pipefail
cd "$(dirname "$0")/.."
if ! command -v docker >/dev/null || ! docker compose version >/dev/null 2>&1; then
  echo "Docker et Docker Compose sont nécessaires." >&2
  exit 1
fi
if [[ ! -f .env ]]; then
  touch .env
  chmod 600 .env
fi
if ! grep -Eq '^APP_API_TOKEN=.{32,}$' .env; then
  if grep -q '^APP_API_TOKEN=' .env; then
    echo "APP_API_TOKEN existe mais est vide ou trop court. Modifie .env avant de relancer." >&2
    exit 1
  fi
  if command -v openssl >/dev/null; then
    secret="$(openssl rand -hex 32)"
  else
    secret="$(python3 -c 'import secrets;print(secrets.token_hex(32))')"
  fi
  printf '\nAPP_API_TOKEN=%s\n' "$secret" >> .env
fi
chmod 600 .env
docker compose -f compose.yaml -f compose.public.yaml --profile public up -d --build
echo
echo "Adresse HTTPS du moteur (attendre quelques secondes) :"
docker compose -f compose.yaml -f compose.public.yaml logs --tail=40 tunnel | grep -E 'trycloudflare.com|https://' || true
echo
echo "Sur https://dbrckk.github.io/monteur-video/ :"
echo "1. Renseigner l'adresse https://...trycloudflare.com dans le champ moteur."
echo "2. Copier APP_API_TOKEN depuis .env dans le champ cle d'acces."
echo "3. Choisir les videos et lancer le montage."
echo "Ne partage jamais la cle. Garder le PC allume pendant les transferts et rendus."
