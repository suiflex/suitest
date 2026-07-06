#!/usr/bin/env bash
# Produce the GitHub Release assets for @suiflex/suitest bundle-v<version>:
#   dist/bundle/web.tar.gz     (apps/web Vite build)
#   dist/bundle/wheels.tar.gz  (all workspace wheels, hatchling)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${1:-$ROOT/dist/bundle}"
case "$OUT" in
  "$ROOT"/*) ;;
  *) echo "OUT must be inside the repo root (got: $OUT)" >&2; exit 1 ;;
esac

rm -rf "$OUT"
mkdir -p "$OUT/web" "$OUT/wheels"

echo "==> web build"
(cd "$ROOT/apps/web" && npm run build)
cp -R "$ROOT/apps/web/dist/." "$OUT/web/"

echo "==> python wheels"
(cd "$ROOT" && uv build --all-packages --wheel -o "$OUT/wheels")

rm -f "$OUT/wheels/.gitignore"

echo "==> tarballs"
tar -czf "$OUT/web.tar.gz" -C "$OUT/web" .
tar -czf "$OUT/wheels.tar.gz" -C "$OUT/wheels" .

echo "Assets ready in $OUT:"
ls -lh "$OUT"/*.tar.gz
echo "Upload web.tar.gz + wheels.tar.gz to release tag: bundle-v$(node -p "require('$ROOT/packages/suitest-npx/package.json').version")"
