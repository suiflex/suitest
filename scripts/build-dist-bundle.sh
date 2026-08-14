#!/usr/bin/env bash
# Produce a self-contained tarball of an npm package for the Homebrew tap and the
# Scoop bucket:
#   dist/<bundle-name>-<version>.tar.gz
#   dist/<bundle-name>-<version>.tar.gz.sha256
#
# Both installers extract the archive and shim its bin/ entry, so the tarball has
# to carry its runtime dependencies: `npm pack` alone would leave
# @suiflex/suitest without @suiflex/suitest-mcp. Node stays an external
# dependency (declared by the formula/manifest); only JavaScript is vendored.
#
# Usage: scripts/build-dist-bundle.sh <package-dir> <bundle-name>
#   e.g. scripts/build-dist-bundle.sh packages/suitest-npx suitest-launcher
set -euo pipefail

[ $# -eq 2 ] || { echo "usage: $0 <package-dir> <bundle-name>" >&2; exit 2; }

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PKG_DIR="$(cd "$1" && pwd)"
BUNDLE="$2"
DIST="$ROOT/dist"

VERSION="$(node -p "require('$PKG_DIR/package.json').version")"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

# `npm pack` runs prepack, so the assets/wheels/python sync scripts stay the
# single source of truth for what ships.
# The tarball name is read off disk rather than from stdout: prepack writes its
# own progress there.
(cd "$PKG_DIR" && npm pack --silent --pack-destination "$STAGE" >/dev/null)
tar -xzf "$STAGE"/*.tgz -C "$STAGE"
SRC="$STAGE/package"

npm install --omit=dev --ignore-scripts --no-audit --no-fund --prefix "$SRC"
rm -f "$SRC/package-lock.json"

# Scoop shims the path in the manifest's "bin" verbatim, and a bare .js is not
# executable on Windows — ship a .cmd next to each entry point.
node -e '
const fs = require("fs");
const path = require("path");
const dir = process.argv[1];
const bin = require(path.join(dir, "package.json")).bin || {};
for (const [name, rel] of Object.entries(bin)) {
  const cmd = path.join(dir, path.dirname(rel), name + ".cmd");
  fs.writeFileSync(cmd, "@node \"%~dp0" + path.basename(rel) + "\" %*\r\n");
  fs.chmodSync(path.join(dir, rel), 0o755);
}
' "$SRC"

mkdir -p "$DIST"
ASSET="$BUNDLE-$VERSION.tar.gz"
tar -czf "$DIST/$ASSET" -C "$SRC" .

# `<digest>  <name>`, so consumers read the digest with `cut -d' ' -f1`.
(cd "$DIST" && { shasum -a 256 "$ASSET" 2>/dev/null || sha256sum "$ASSET"; } > "$ASSET.sha256")

echo "$DIST/$ASSET"
