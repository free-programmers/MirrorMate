#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

printf '%s\n' "MirrorMate's legacy script.sh entrypoint is deprecated; use 'mirrormate' instead." >&2

if [ -d "$SCRIPT_DIR/src/mirrormate" ]; then
    PYTHONPATH="$SCRIPT_DIR/src${PYTHONPATH:+:$PYTHONPATH}" exec python3 -m mirrormate "$@"
fi

if command -v mirrormate >/dev/null 2>&1; then
    exec mirrormate "$@"
fi

printf '%s\n' "MirrorMate is not installed. Run install.sh or install the .deb package." >&2
exit 127
