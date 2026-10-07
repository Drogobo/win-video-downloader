#!/bin/bash
# Build "Video Downloader.app" and a .dmg on macOS.
#
# Requires Homebrew (https://brew.sh). Must run on a Mac: apps for macOS
# can't be built on Linux. Without a Mac, use the GitHub Actions workflow
# (.github/workflows/build-packages.yml) instead.
#
# The app is built for the architecture of the Mac it is built on
# (Apple Silicon or Intel).

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PACKAGING_DIR="$ROOT_DIR/packaging"
BUILD_DIR="$PACKAGING_DIR/build/macos"
DIST_DIR="$PACKAGING_DIR/dist"

log() { printf '==> %s\n' "$*" >&2; }

if [[ "$(uname -s)" != Darwin ]]; then
    echo "ERROR: this script must run on macOS" >&2
    exit 1
fi
if ! command -v brew >/dev/null; then
    echo "ERROR: Homebrew is required (https://brew.sh)" >&2
    exit 1
fi

log "Installing dependencies with Homebrew"
brew install --quiet meson ninja gettext librsvg desktop-file-utils \
    gtk4 libadwaita adwaita-icon-theme pygobject3 ffmpeg deno
BREW_PREFIX="$(brew --prefix)"
export PATH="$BREW_PREFIX/bin:$BREW_PREFIX/opt/gettext/bin:$PATH"

# Use the Python version that pygobject3 was built for
PYTHON_FORMULA="$(brew deps --direct pygobject3 | grep -E '^python@3' |
    sort -V | tail -n 1)"
PYTHON="$(brew --prefix "$PYTHON_FORMULA")/libexec/bin/python3"
log "Using $PYTHON_FORMULA"

mkdir -p "$BUILD_DIR" "$DIST_DIR"
VENV="$BUILD_DIR/venv"
if [[ ! -x "$VENV/bin/python" ]] ||
        ! "$VENV/bin/python" -c 'import gi' 2>/dev/null; then
    rm -rf "$VENV"
    "$PYTHON" -m venv --system-site-packages "$VENV"
fi
log "Installing PyInstaller and yt-dlp"
"$VENV/bin/python" -m pip install --quiet --upgrade pip
"$VENV/bin/python" -m pip install --quiet --upgrade \
    pyinstaller pyinstaller-hooks-contrib 'yt-dlp[default]' yt-dlp-ejs

log "Building app with meson"
MESON_DIR="$BUILD_DIR/meson"
STAGE_DIR="$BUILD_DIR/stage"
rm -rf "$STAGE_DIR"
if [[ ! -f "$MESON_DIR/build.ninja" ]]; then
    rm -rf "$MESON_DIR"
    meson setup "$MESON_DIR" "$ROOT_DIR" --prefix=/usr
fi
meson install -C "$MESON_DIR" --destdir "$STAGE_DIR"
VERSION="$("$VENV/bin/python" -c 'import json, sys
print(json.load(sys.stdin)["version"])' \
    < <(meson introspect "$MESON_DIR" --projectinfo))"

log "Preparing resources"
RES_DIR="$BUILD_DIR/resources"
rm -rf "$RES_DIR"
mkdir -p "$RES_DIR/schemas" "$RES_DIR/icon.iconset"
sed "s/@VERSION@/$VERSION/" "$PACKAGING_DIR/launcher.py" \
    > "$RES_DIR/launcher.py"
glib-compile-schemas --targetdir="$RES_DIR/schemas" \
    "$STAGE_DIR/usr/share/glib-2.0/schemas"
ICON_SVG="$STAGE_DIR/usr/share/icons/hicolor/scalable/apps/com.github.unrud.VideoDownloader.svg"
for size in 16 32 128 256 512; do
    rsvg-convert --width "$size" --height "$size" --keep-aspect-ratio \
        "$ICON_SVG" -o "$RES_DIR/icon.iconset/icon_${size}x${size}.png"
    rsvg-convert --width "$((size * 2))" --height "$((size * 2))" \
        --keep-aspect-ratio "$ICON_SVG" \
        -o "$RES_DIR/icon.iconset/icon_${size}x${size}@2x.png"
done
iconutil -c icns "$RES_DIR/icon.iconset" -o "$RES_DIR/icon.icns"

log "Bundling with PyInstaller"
export VD_VERSION="$VERSION" VD_STAGE="$STAGE_DIR/usr" VD_RESOURCES="$RES_DIR"
VD_FFMPEG="$(realpath "$(command -v ffmpeg)")"
VD_FFPROBE="$(realpath "$(command -v ffprobe)")"
VD_DENO="$(realpath "$(command -v deno)")"
export VD_FFMPEG VD_FFPROBE VD_DENO
"$VENV/bin/python" -m PyInstaller --noconfirm --clean \
    --distpath "$BUILD_DIR/dist" --workpath "$BUILD_DIR/pyinstaller" \
    "$PACKAGING_DIR/macos/video-downloader.spec"
APP="$BUILD_DIR/dist/Video Downloader.app"
# Ad-hoc signature (required on Apple Silicon)
codesign --force --deep --sign - "$APP"

log "Creating disk image"
ARCH="$(uname -m)"
DMG="$DIST_DIR/VideoDownloader-$VERSION-macos-$ARCH.dmg"
DMG_DIR="$BUILD_DIR/dmg"
rm -rf "$DMG_DIR" "$DMG"
mkdir -p "$DMG_DIR"
cp -R "$APP" "$DMG_DIR/"
ln -s /Applications "$DMG_DIR/Applications"
hdiutil create -volname "Video Downloader" -srcfolder "$DMG_DIR" \
    -fs HFS+ -format UDZO -ov "$DMG"
log "Done: $DMG"
