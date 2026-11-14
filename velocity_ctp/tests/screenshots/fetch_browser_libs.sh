#!/usr/bin/env bash
# Optional, no sudo: download the shared libraries Playwright's Chromium needs on a bare WSL/Ubuntu
# and unpack them into tests/screenshots/.browser-libs (git-ignored). run.js picks them up
# automatically. Only needed when the browser fails with "error while loading shared libraries".
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
LIBS="$HERE/.browser-libs"
DEBS="$LIBS/debs"
mkdir -p "$DEBS"
cd "$DEBS"

fetch() {
	# Try each available version (newest first); stale indexes can 404 on the newest one.
	local pkg="$1"
	for version in $(apt-cache madison "$pkg" 2>/dev/null | awk -F'|' '{gsub(/ /, "", $2); print $2}'); do
		if apt-get download "$pkg=$version" >/dev/null 2>&1; then
			echo "downloaded $pkg $version"
			return 0
		fi
	done
	echo "could not download $pkg" >&2
	return 1
}

fetch libnspr4
fetch libnss3
fetch libasound2t64 2>/dev/null || fetch libasound2

for deb in *.deb; do
	dpkg-deb -x "$deb" "$LIBS"
done
echo "Libraries unpacked to $LIBS/usr/lib/x86_64-linux-gnu"
