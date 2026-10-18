#!/usr/bin/env bash
# Launch an authenticated video render engine + temporary free HTTPS tunnel.
set -euo pipefail
cd "$(dirname "$0")/.."

if ! docker compose version >/dev/null 2>&1; then
  echo "Docker Compose v2 n'est pas disponible. Installe Docker Desktop ou Docker Engine + Compose." >&2
  exit 1
fi

if [[ ! -f .env ]]; then
  (umask 077; touch .env)
fi
if ! grep -qE '^APP_API_TOKEN=[A-Za-z0-9_-]{32,}$' .env; then
  if grep -qE '^APP_API_TOKEN=' .env; then
    echo "Une clé APP_API_TOKEN invalide est présente dans .env. Corrige-la manuellement." >&2
    exit 1
  fi
  secret="$(python3 -c 'import secrets;print(secrets.token_urlsafe(36))' 2>/dev/null || openssl rand -hex 36)"
  (umask 077; printf '\nAPP_API_TOKEN=%s\n' "$secret" >> .env)
  echo "Clé APP_API_TOKEN créée et enregistrée dans .env (ne partage jamais ce fichier)."
fi
if ! grep -qE '^MAX_UPLOAD_GB=' .env; then
  printf 'MAX_UPLOAD_GB=20\n' >> .env
fi

compose=(docker compose -f compose.yaml -f compose.remote.yaml)
"${compose[@]}" config --quiet
"${compose[@]}" up --build -d

url=""
for _ in $(seq 1 40); do
  url=$("${compose[@]}" logs --no-color tunnel 2>&1 |
    grep -Eo 'https://[A-Za-z0-9-]+\.trycloudflare\.com' | tail -n 1 || true)
  [[ -n "$url" ]] && break
  sleep 2
done
if [[ -z "$url" ]]; then
  echo "Le tunnel HTTPS n'a pas retourné d'adresse. Examine : " >&2
  printf 'docker compose -f compose.yaml -f compose.remote.yaml logs tunnel\n' >&2
  exit 1
fi
secret="$(sed -n 's/^APP_API_TOKEN=//p' .env | head -n 1)"
printf '\n====== MONTEUR STUDIO : CONNEXION ANDROID ======\n'
printf '1. Ouvre : https://dbrckk.github.io/monteur-video/\n'
printf '2. Adresse HTTPS du moteur : %s\n' "$url"
printf '3. Clé d\x27accès (privée) : %s\n' "$secret"
printf '4. Sélectionne tes vidéos, puis crée le montage.\n'
printf '================================================\n'
printf '\nNote : le PC doit rester allumé. Le lien temporaire change au redémarrage du tunnel.\n'
