#!/usr/bin/env bash
# Sube este proyecto a un repositorio de GitHub.
# Uso:  bash SUBIR_A_GITHUB.sh https://github.com/TU_USUARIO/seguimiento-erm-2026.git
set -e

REPO_URL="$1"
if [ -z "$REPO_URL" ]; then
  echo "Falta la URL del repo."
  echo "Uso: bash SUBIR_A_GITHUB.sh https://github.com/TU_USUARIO/seguimiento-erm-2026.git"
  exit 1
fi

cd "$(dirname "$0")"

if [ ! -d .git ]; then
  git init
  git branch -M main
fi

git add .
git commit -m "Tablero de seguimiento ERM 2026 (Lima y San Borja)" || echo "Nada nuevo que commitear."

if git remote | grep -q origin; then
  git remote set-url origin "$REPO_URL"
else
  git remote add origin "$REPO_URL"
fi

git push -u origin main
echo ""
echo "Listo. Ahora activa GitHub Pages: Settings → Pages → Branch main, carpeta /docs."
