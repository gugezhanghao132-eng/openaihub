#!/bin/bash
set -euo pipefail

INSTALL_ROOT="$HOME/.openaihub"
BIN_ROOT="$INSTALL_ROOT/bin"
RUNTIME_ROOT="$INSTALL_ROOT/npm-runtime"

show_step() {
  printf '[%s] %s\n' "$1" "$2"
}

show_step '1/1' 'Cleaning shell PATH entries...'
for rc in "$HOME/.zshrc" "$HOME/.bashrc"; do
  if [ -f "$rc" ]; then
    tmp="$rc.tmp.openaihub"
    grep -Fv "export PATH=\"$BIN_ROOT:\$PATH\"" "$rc" > "$tmp" || true
    mv "$tmp" "$rc"
  fi
done

echo "OpenAI Hub uninstall complete."
if [ -d "$RUNTIME_ROOT" ]; then
  rm -rf "$RUNTIME_ROOT"
  echo "Removed runtime files at: $RUNTIME_ROOT"
fi
echo "User data preserved at: $INSTALL_ROOT"
echo "Delete that folder manually if you want to remove saved accounts and config."
