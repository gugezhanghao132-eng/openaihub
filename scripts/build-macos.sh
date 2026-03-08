#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ENTRY_SCRIPT="$ROOT_DIR/package/app/openai_launcher.py"
HELPER_SCRIPT="$ROOT_DIR/package/app/openai_codex_login_helper.mjs"
OAUTH_DIR="$ROOT_DIR/package/app/bundled_runtime/oauth"
DIST_DIR="$ROOT_DIR/dist"
BUILD_DIR="$ROOT_DIR/build-macos"
SPEC_DIR="$ROOT_DIR/spec-macos"
TMP_DIR="$ROOT_DIR/.tmp-runtime-macos"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 not found on macOS."
  exit 1
fi

if ! python3 -m PyInstaller --version >/dev/null 2>&1; then
  echo "PyInstaller not found. Run: python3 -m pip install pyinstaller"
  exit 1
fi

rm -rf "$DIST_DIR/openaihub-macos" "$BUILD_DIR" "$SPEC_DIR" "$TMP_DIR"
mkdir -p "$TMP_DIR/bundled_runtime/node"

if command -v node >/dev/null 2>&1; then
  cp "$(command -v node)" "$TMP_DIR/bundled_runtime/node/node"
fi

ARGS=(
  --noconfirm
  --clean
  --onedir
  --name openaihub
  --distpath "$DIST_DIR"
  --workpath "$BUILD_DIR"
  --specpath "$SPEC_DIR"
  --add-data "$HELPER_SCRIPT:."
  --add-data "$OAUTH_DIR:bundled_runtime/oauth"
)

if [ -f "$TMP_DIR/bundled_runtime/node/node" ]; then
  ARGS+=(--add-data "$TMP_DIR/bundled_runtime/node:bundled_runtime/node")
fi

python3 -m PyInstaller "${ARGS[@]}" "$ENTRY_SCRIPT"

mv "$DIST_DIR/openaihub" "$DIST_DIR/openaihub-macos"
mv "$DIST_DIR/openaihub-macos/openaihub" "$DIST_DIR/openaihub-macos/openaihub-bin"
cp "$ROOT_DIR/package/bin/openaihub" "$DIST_DIR/openaihub-macos/openaihub"
cp "$ROOT_DIR/package/bin/OAH" "$DIST_DIR/openaihub-macos/OAH"
chmod +x "$DIST_DIR/openaihub-macos/openaihub" "$DIST_DIR/openaihub-macos/OAH" "$DIST_DIR/openaihub-macos/openaihub-bin"

echo "macOS build complete: $DIST_DIR/openaihub-macos"
