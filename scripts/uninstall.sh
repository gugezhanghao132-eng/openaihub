#!/bin/bash
set -euo pipefail

INSTALL_ROOT="$HOME/.openaihub"
BIN_ROOT="$INSTALL_ROOT/bin"

show_step() {
  printf '[%s] %s\n' "$1" "$2"
}

show_step '1/2' 'Removing installed files...'
rm -rf "$INSTALL_ROOT"

show_step '2/2' 'Cleaning shell PATH entries...'
for rc in "$HOME/.zshrc" "$HOME/.bashrc"; do
  if [ -f "$rc" ]; then
    tmp="$rc.tmp.openaihub"
    grep -Fv "export PATH=\"$BIN_ROOT:\$PATH\"" "$rc" > "$tmp" || true
    mv "$tmp" "$rc"
  fi
done

echo "OpenAI Hub uninstall complete."
echo "Removed path: $INSTALL_ROOT"
