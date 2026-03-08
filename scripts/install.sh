#!/bin/bash
set -euo pipefail

INSTALL_ROOT="$HOME/.openaihub"
BIN_ROOT="$INSTALL_ROOT/bin"
SOURCE_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SOURCE_DIST="$SOURCE_ROOT/dist/openaihub-macos"
VERSION_FILE="$SOURCE_ROOT/package/version.txt"
REPO_OWNER="gugezhanghao132-eng"
REPO_NAME="openaihub"
ASSET_NAME="openaihub-macos.tar.gz"
LATEST_RELEASE_API="https://api.github.com/repos/$REPO_OWNER/$REPO_NAME/releases/latest"
ALREADY_INSTALLED=0

if [ -x "$BIN_ROOT/openaihub-bin" ]; then
  ALREADY_INSTALLED=1
fi

show_step() {
  printf '[%s] %s\n' "$1" "$2"
}

show_step '1/5' 'Preparing install directory...'
mkdir -p "$INSTALL_ROOT" "$BIN_ROOT"

TMP_ROOT="$(mktemp -d 2>/dev/null || mktemp -d -t openaihub-install)"
PAYLOAD_ROOT="$TMP_ROOT/payload"
PAYLOAD_BIN_ROOT="$PAYLOAD_ROOT/bin"
REMOTE_MODE=1

if [ -x "$SOURCE_DIST/openaihub-bin" ]; then
  REMOTE_MODE=0
fi

cleanup() {
  rm -rf "$TMP_ROOT"
}

trap cleanup EXIT

mkdir -p "$PAYLOAD_ROOT"

if [ "$REMOTE_MODE" -eq 1 ]; then
  JSON_PATH="$TMP_ROOT/latest-release.json"
  ARCHIVE_PATH="$TMP_ROOT/$ASSET_NAME"

  show_step '2/5' 'Downloading release metadata...'
  curl -fsSL "$LATEST_RELEASE_API" -o "$JSON_PATH"

  VERSION_TEXT="$(grep -m1 '"tag_name":' "$JSON_PATH" | sed -E 's/.*"v?([^"]+)".*/\1/')"
  REMOTE_URL="$(grep -m1 'browser_download_url": ".*openaihub-macos.tar.gz"' "$JSON_PATH" | sed -E 's/.*"(https:[^"]+)".*/\1/')"

  if [ -z "$REMOTE_URL" ]; then
    echo "Latest release does not contain the macOS asset yet."
    exit 1
  fi

  show_step '3/5' 'Downloading release package...'
  curl -fsSL "$REMOTE_URL" -o "$ARCHIVE_PATH"

  show_step '4/5' 'Extracting release package...'
  tar -xzf "$ARCHIVE_PATH" -C "$PAYLOAD_ROOT"

  PAYLOAD_BIN_ROOT="$(find "$PAYLOAD_ROOT" -type f -name 'openaihub-bin' -print -quit | xargs -I{} dirname "{}")"
  if [ -z "$PAYLOAD_BIN_ROOT" ] || [ ! -x "$PAYLOAD_BIN_ROOT/openaihub-bin" ]; then
    echo "Downloaded package does not contain openaihub-bin."
    exit 1
  fi
else
  VERSION_TEXT="$(cat "$VERSION_FILE")"
  PAYLOAD_BIN_ROOT="$SOURCE_DIST"
fi

show_step '2/5' 'Cleaning previous files...'
rm -rf "$BIN_ROOT/_internal" "$BIN_ROOT/openaihub" "$BIN_ROOT/openaihub-bin" "$BIN_ROOT/OAH"
show_step '3/5' 'Copying bundled runtime...'
cp -R "$PAYLOAD_BIN_ROOT"/* "$BIN_ROOT/"
if [ -f "$SOURCE_ROOT/package/bin/openaihub" ] && [ -f "$SOURCE_ROOT/package/bin/OAH" ]; then
  cp "$SOURCE_ROOT/package/bin/openaihub" "$BIN_ROOT/openaihub"
  cp "$SOURCE_ROOT/package/bin/OAH" "$BIN_ROOT/OAH"
fi
printf '%s\n' "$VERSION_TEXT" > "$INSTALL_ROOT/version.txt"
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
