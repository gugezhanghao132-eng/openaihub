#!/bin/bash
set -euo pipefail

INSTALL_ROOT="$HOME/.openaihub"
BIN_ROOT="$INSTALL_ROOT/bin"
SOURCE_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SOURCE_DIST="$SOURCE_ROOT/dist/openaihub-macos"
VERSION_FILE="$SOURCE_ROOT/package/version.txt"
ALREADY_INSTALLED=0

if [ -x "$BIN_ROOT/openaihub-bin" ]; then
  ALREADY_INSTALLED=1
fi

show_step() {
  printf '[%s] %s\n' "$1" "$2"
}

show_step '1/5' 'Preparing install directory...'
mkdir -p "$INSTALL_ROOT" "$BIN_ROOT"

if [ ! -x "$SOURCE_DIST/openaihub-bin" ]; then
  echo "Missing built macOS binary. Build on macOS first."
  exit 1
fi

show_step '2/5' 'Cleaning previous files...'
rm -rf "$BIN_ROOT/_internal" "$BIN_ROOT/openaihub" "$BIN_ROOT/openaihub-bin" "$BIN_ROOT/OAH"
show_step '3/5' 'Copying bundled runtime...'
cp -R "$SOURCE_DIST"/* "$BIN_ROOT/"
cp "$SOURCE_ROOT/package/bin/openaihub" "$BIN_ROOT/openaihub"
cp "$SOURCE_ROOT/package/bin/OAH" "$BIN_ROOT/OAH"
cp "$VERSION_FILE" "$INSTALL_ROOT/version.txt"
chmod +x "$BIN_ROOT/openaihub" "$BIN_ROOT/OAH" "$BIN_ROOT/openaihub-bin"

SHELL_RC="$HOME/.zshrc"
if [ -n "${BASH_VERSION:-}" ]; then
  SHELL_RC="$HOME/.bashrc"
fi

if [ ! -f "$SHELL_RC" ]; then
  touch "$SHELL_RC"
fi

if ! grep -Fq "$BIN_ROOT" "$SHELL_RC"; then
  show_step '4/5' 'Updating shell PATH...'
  printf '\nexport PATH="%s:$PATH"\n' "$BIN_ROOT" >> "$SHELL_RC"
else
  show_step '4/5' 'Shell PATH already configured.'
fi

show_step '5/5' 'Finalizing install result...'
if [ $ALREADY_INSTALLED -eq 1 ]; then
  echo "OpenAI Hub update complete."
else
  echo "OpenAI Hub install complete."
fi
echo "Install path: $INSTALL_ROOT"
echo "Version: $(cat "$INSTALL_ROOT/version.txt")"
echo "Reopen terminal, then use:"
echo "  openaihub"
echo "  OAH"
