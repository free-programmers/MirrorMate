#!/bin/sh
set -eu

PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
DEFAULT_VERSION=$(sed -n 's/^version = "\([^"]*\)"/\1/p' "$PROJECT_DIR/pyproject.toml" | head -n 1)
VERSION=${VERSION:-$DEFAULT_VERSION}
OUTPUT_DIR="$PROJECT_DIR/dist"
BUILD_DIR=$(mktemp -d)
PACKAGE_ROOT="$BUILD_DIR/mirrormate"

cleanup() {
    rm -rf -- "$BUILD_DIR"
}
trap cleanup EXIT INT TERM

mkdir -p \
    "$PACKAGE_ROOT/DEBIAN" \
    "$PACKAGE_ROOT/usr/bin" \
    "$PACKAGE_ROOT/usr/lib/python3/dist-packages" \
    "$PACKAGE_ROOT/usr/share/doc/mirrormate" \
    "$OUTPUT_DIR"

sed "s/@VERSION@/$VERSION/g" "$PROJECT_DIR/packaging/debian/control" > "$PACKAGE_ROOT/DEBIAN/control"
cp -R "$PROJECT_DIR/src/mirrormate" "$PACKAGE_ROOT/usr/lib/python3/dist-packages/mirrormate"
find "$PACKAGE_ROOT/usr/lib/python3/dist-packages/mirrormate" -type d -name __pycache__ -prune -exec rm -rf {} +
find "$PACKAGE_ROOT/usr/lib/python3/dist-packages/mirrormate" -type d -exec chmod 0755 {} +
find "$PACKAGE_ROOT/usr/lib/python3/dist-packages/mirrormate" -type f -exec chmod 0644 {} +
install -m 0755 "$PROJECT_DIR/packaging/debian/mirrormate" "$PACKAGE_ROOT/usr/bin/mirrormate"
install -m 0644 "$PROJECT_DIR/LICENSE" "$PACKAGE_ROOT/usr/share/doc/mirrormate/copyright"

dpkg-deb --root-owner-group --build "$PACKAGE_ROOT" "$OUTPUT_DIR/mirrormate_all.deb"
cd "$OUTPUT_DIR"
sha256sum mirrormate_all.deb > mirrormate_all.deb.sha256

printf '%s\n' "Built $OUTPUT_DIR/mirrormate_all.deb"
