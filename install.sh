#!/bin/sh
set -eu

REPOSITORY=${MIRRORMATE_REPOSITORY:-free-programmers/MirrorMate}
BASE_URL=${MIRRORMATE_RELEASE_URL:-https://github.com/$REPOSITORY/releases/latest/download}
TEMP_DIR=$(mktemp -d)
PACKAGE="$TEMP_DIR/mirrormate_all.deb"
CHECKSUM="$TEMP_DIR/mirrormate_all.deb.sha256"

cleanup() {
    rm -rf -- "$TEMP_DIR"
}
trap cleanup EXIT INT TERM

download() {
    source_url=$1
    destination=$2
    if command -v curl >/dev/null 2>&1; then
        curl --fail --location --silent --show-error "$source_url" --output "$destination"
    elif command -v wget >/dev/null 2>&1; then
        wget --quiet --output-document="$destination" "$source_url"
    else
        printf '%s\n' "curl or wget is required to install MirrorMate." >&2
        exit 1
    fi
}

download "$BASE_URL/mirrormate_all.deb" "$PACKAGE"
download "$BASE_URL/mirrormate_all.deb.sha256" "$CHECKSUM"

expected=$(awk 'NR == 1 { print $1 }' "$CHECKSUM")
actual=$(sha256sum "$PACKAGE" | awk '{ print $1 }')
if [ -z "$expected" ] || [ "$expected" != "$actual" ]; then
    printf '%s\n' "MirrorMate package checksum verification failed." >&2
    exit 1
fi

if [ "$(id -u)" -eq 0 ]; then
    apt-get install -y "$PACKAGE"
elif command -v sudo >/dev/null 2>&1; then
    sudo apt-get install -y "$PACKAGE"
else
    printf '%s\n' "Root access is required; rerun this installer with sudo." >&2
    exit 1
fi

printf '%s\n' "MirrorMate installed. Run: mirrormate"
