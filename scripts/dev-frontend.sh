#!/usr/bin/env bash
# Run the React dev server (port 5173). Requires Node/npm on PATH.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if [ -x /opt/homebrew/bin/npm ]; then
  export PATH="/opt/homebrew/bin:$PATH"
elif [ -x /usr/local/bin/npm ]; then
  export PATH="/usr/local/bin:$PATH"
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "npm not found. Install Node.js, then retry:"
  echo "  brew install node"
  echo "  # or https://nodejs.org/"
  exit 1
fi

cd "$ROOT/frontend"
npm install
npm run dev
