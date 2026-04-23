#!/usr/bin/env bash
set -euo pipefail

FRONTEND_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$FRONTEND_DIR"

# ── Environment ──────────────────────────────────────────────────────────────
export REACT_APP_API_URL="${REACT_APP_API_URL:-http://localhost:8000}"

# ── Dependency check ─────────────────────────────────────────────────────────
if ! command -v node &>/dev/null; then
  echo "ERROR: node is not installed. Install Node.js >= 18 and try again."
  exit 1
fi

if ! command -v npm &>/dev/null; then
  echo "ERROR: npm is not installed."
  exit 1
fi

NODE_VERSION=$(node -e "process.stdout.write(process.versions.node.split('.')[0])")
if [ "$NODE_VERSION" -lt 18 ]; then
  echo "WARNING: Node.js $NODE_VERSION detected. Node >= 18 is recommended."
fi

# ── Install dependencies ──────────────────────────────────────────────────────
if [ ! -d node_modules ]; then
  echo "Installing dependencies..."
  npm install
else
  echo "node_modules found — skipping install. Run 'npm install' manually if deps changed."
fi

# ── Start dev server ──────────────────────────────────────────────────────────
echo ""
echo "Starting Decision Sys frontend..."
echo "  API backend : $REACT_APP_API_URL"
echo "  App URL     : http://localhost:3000"
echo ""

npm start
