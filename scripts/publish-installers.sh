#!/usr/bin/env bash
# Render the Homebrew formula and the Scoop manifest for a released bundle and
# push them to suiflex/homebrew-tap and suiflex/scoop-bucket.
#
# Usage: scripts/publish-installers.sh <name> <bundle-name> <base-url>
#   e.g. scripts/publish-installers.sh suitest suitest-launcher \
#          https://github.com/suiflex/suitest/releases/download/launcher-v0.6.7
#
# Reads dist/<bundle-name>-<version>.tar.gz.sha256 written by
# build-dist-bundle.sh. Set DRY_RUN=1 to render and validate without cloning or
# pushing anything -- that is what the pull-request jobs run.
# Pushing needs GH_TOKEN with write access to both repositories.
set -euo pipefail

[ $# -eq 3 ] || { echo "usage: $0 <name> <bundle-name> <base-url>" >&2; exit 2; }

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
NAME="$1"
BUNDLE="$2"
BASE="$3"
DIST="$ROOT/dist"

ASSET="$(cd "$DIST" && ls "$BUNDLE"-*.tar.gz)"
VERSION="${ASSET#"$BUNDLE"-}"
VERSION="${VERSION%.tar.gz}"
SHA="$(cut -d' ' -f1 < "$DIST/$ASSET.sha256")"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

render() {
  sed -e "s|@VERSION@|$VERSION|g" -e "s|@BASE@|$BASE|g" -e "s|@SHA@|$SHA|g" \
    "$ROOT/packaging/$1" > "$WORK/$2"
  # A surviving placeholder means a missing input; fail rather than publish a
  # formula that cannot install.
  ! grep -q '@[A-Z_]*@' "$WORK/$2"
}

render "$NAME.rb.tmpl" "$NAME.rb"
render "$NAME.json.tmpl" "$NAME.json"
ruby -c "$WORK/$NAME.rb" > /dev/null
jq empty "$WORK/$NAME.json"

if [ "${DRY_RUN:-0}" = "1" ]; then
  echo "rendered $NAME $VERSION (dry run, nothing pushed)"
  exit 0
fi

push() {
  local repo="$1" dir="$2" file="$3"
  git clone --depth 1 "https://x-access-token:${GH_TOKEN}@github.com/$repo.git" "$WORK/$repo"
  mkdir -p "$WORK/$repo/$dir"
  cp "$WORK/$file" "$WORK/$repo/$dir/$file"
  cd "$WORK/$repo"
  git config user.name "github-actions[bot]"
  git config user.email "github-actions[bot]@users.noreply.github.com"
  git add "$dir/$file"
  git commit -m "$NAME $VERSION" || { echo "$repo already at $VERSION"; return 0; }
  git push
  cd "$ROOT"
}

push suiflex/homebrew-tap Formula "$NAME.rb"
push suiflex/scoop-bucket bucket "$NAME.json"
