#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SPEC_FILE="$ROOT_DIR/openaihub.spec"
DIST_DIR="$ROOT_DIR/dist"
BUILD_DIR="$ROOT_DIR/build-macos"
SPEC_DIR="$ROOT_DIR/spec-macos"
RELEASE_DIR="$ROOT_DIR/release-assets"
ARCH_NAME="$(uname -m)"

case "$ARCH_NAME" in
  arm64|aarch64)
    ASSET_ARCH="arm64"
    ;;
  x86_64)
    ASSET_ARCH="x64"
    ;;
  *)
    echo "Unsupported macOS architecture: $ARCH_NAME"
    exit 1
    ;;
esac

OUTPUT_DIR_NAME="openaihub-macos-$ASSET_ARCH"
ASSET_NAME="$OUTPUT_DIR_NAME.tar.gz"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 not found on macOS."
  exit 1
fi

if ! python3 -m PyInstaller --version >/dev/null 2>&1; then
  echo "PyInstaller not found. Run: python3 -m pip install -r scripts/build-requirements.txt"
  exit 1
fi

rm -rf "$DIST_DIR/openaihub" "$DIST_DIR/$OUTPUT_DIR_NAME" "$BUILD_DIR" "$SPEC_DIR"

cd "$ROOT_DIR"
python3 -m PyInstaller "$SPEC_FILE" -y --distpath "$DIST_DIR" --workpath "$BUILD_DIR" --clean

BUILD_OUTPUT_ROOT="$DIST_DIR/openaihub"
if [ ! -d "$BUILD_OUTPUT_ROOT" ]; then
  echo "PyInstaller did not create an onedir output under $DIST_DIR"
  exit 1
fi

if command -v node >/dev/null 2>&1; then
  mkdir -p "$BUILD_OUTPUT_ROOT/bundled_runtime/node"
  cp "$(command -v node)" "$BUILD_OUTPUT_ROOT/bundled_runtime/node/node"
fi

mv "$BUILD_OUTPUT_ROOT" "$DIST_DIR/$OUTPUT_DIR_NAME"
mv "$DIST_DIR/$OUTPUT_DIR_NAME/openaihub" "$DIST_DIR/$OUTPUT_DIR_NAME/openaihub-bin"
cp "$ROOT_DIR/package/bin/openaihub" "$DIST_DIR/$OUTPUT_DIR_NAME/openaihub"
cp "$ROOT_DIR/package/bin/OAH" "$DIST_DIR/$OUTPUT_DIR_NAME/OAH"
chmod +x "$DIST_DIR/$OUTPUT_DIR_NAME/openaihub" "$DIST_DIR/$OUTPUT_DIR_NAME/OAH" "$DIST_DIR/$OUTPUT_DIR_NAME/openaihub-bin"

mkdir -p "$RELEASE_DIR"
tar -czf "$RELEASE_DIR/$ASSET_NAME" -C "$DIST_DIR" "$OUTPUT_DIR_NAME"

echo "macOS build complete: $DIST_DIR/$OUTPUT_DIR_NAME"
echo "macOS archive complete: $RELEASE_DIR/$ASSET_NAME"
