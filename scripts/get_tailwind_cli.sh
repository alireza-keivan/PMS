#!/usr/bin/env bash
# Fetches the standalone Tailwind CLI (no Node/npm required) into .bin/.
# Pinned to v3.4.17 to match tailwind.config.js and package.json - do not
# bump to v4 here without migrating the config, which uses a different
# (CSS-first) syntax.
set -euo pipefail

VERSION="v3.4.17"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="$ROOT/.bin/tailwindcss"

case "$(uname -s)-$(uname -m)" in
  Linux-x86_64) ASSET="tailwindcss-linux-x64" ;;
  Linux-aarch64) ASSET="tailwindcss-linux-arm64" ;;
  Darwin-x86_64) ASSET="tailwindcss-macos-x64" ;;
  Darwin-arm64) ASSET="tailwindcss-macos-arm64" ;;
  *) echo "Unsupported platform: $(uname -s)-$(uname -m)" >&2; exit 1 ;;
esac

mkdir -p "$ROOT/.bin"
curl -sL -o "$DEST" "https://github.com/tailwindlabs/tailwindcss/releases/download/$VERSION/$ASSET"
chmod +x "$DEST"
echo "Tailwind CLI $VERSION installed at $DEST"
