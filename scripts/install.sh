#!/usr/bin/env bash
# One-liner installer (openclaw-style):
#   curl -fsSL https://raw.githubusercontent.com/suiflex/suitest/main/scripts/install.sh | bash
set -euo pipefail

have() { command -v "$1" >/dev/null 2>&1; }

# Node >= 18
node_ok() {
  have node && [ "$(node -p 'Number(process.versions.node.split(".")[0])')" -ge 18 ]
}
if ! node_ok; then
  echo "==> Node.js >= 18 not found, installing…"
  if have brew; then
    brew install node
  elif have apt-get; then
    sudo apt-get update -qq && sudo apt-get install -y nodejs npm
  elif have dnf; then
    sudo dnf install -y nodejs npm
  else
    echo "Could not auto-install Node.js. Install it from https://nodejs.org and re-run." >&2
    exit 1
  fi
  node_ok || { echo "Node.js install did not produce >= 18." >&2; exit 1; }
fi

# uv (provisions Python 3.12 on demand for the venv)
if ! have uv; then
  echo "==> Installing uv…"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi

echo "==> Running suitest onboard…"
exec npx -y @suiflex/suitest onboard "$@"
