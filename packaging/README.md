# Windows and macOS builds

This fork adds Windows and macOS support to
[Video Downloader](https://github.com/Unrud/video-downloader). Linux keeps
working the same way as upstream (meson, Flatpak, Snap).

## Windows (built on Linux)

The build script downloads ready-made Windows builds of GTK 4, libadwaita,
Python and PyGObject from [MSYS2](https://www.msys2.org/), plus yt-dlp
(PyPI), ffmpeg ([yt-dlp/FFmpeg-Builds](https://github.com/yt-dlp/FFmpeg-Builds))
and deno ([denoland/deno](https://github.com/denoland/deno), which yt-dlp
needs for YouTube). It only unpacks them; nothing runs under Wine. The
result is a portable folder in a zip file.

Install the build tools (CachyOS/Arch):

```sh
sudo pacman -S --needed python meson ninja gettext librsvg glib2 glib2-devel \
    desktop-file-utils gtk-update-icon-cache zstd mingw-w64-gcc
```

`mingw-w64-gcc` is optional. It builds `Video Downloader.exe`. Without it,
you get `Video Downloader.bat`, which briefly opens a console window.

Build:

```sh
./packaging/windows/build_windows.py
```

The output is `packaging/dist/VideoDownloader-<version>-windows-x64.zip`
(about 150–250 MB). Downloads are cached in `packaging/build/`, so later
builds are faster.

**For your friend:** extract the zip (right-click → *Extract All*) and
start `Video Downloader.exe` from the extracted folder. Windows SmartScreen
may say "Windows protected your PC" because the program isn't signed: click
*More info* → *Run anyway*. Windows 10 and 11 (64-bit) are supported.

Each build bundles the newest yt-dlp. Sites change often, so if downloads
stop working, rebuild and send the new zip.

## macOS

A macOS app can only be built on a Mac. There are two ways to build it:

### Without a Mac: GitHub Actions

The workflow `.github/workflows/build-packages.yml` builds on GitHub's
Mac machines. It also builds the Windows version and tests it on a real
Windows machine.

1. Push this repository to GitHub. On forks, enable Actions in the
   *Actions* tab first.
2. *Actions* → *Build Windows and macOS packages* → *Run workflow*,
   or from the terminal: `gh workflow run build-packages.yml`.
   It also runs on its own when files in `packaging/` change.
3. When it finishes, download the artifacts at the bottom of the run page:
   - `VideoDownloader-macos-arm64`: Apple Silicon Macs (M1 and newer)
   - `VideoDownloader-macos-x86_64`: Intel Macs
   - `VideoDownloader-windows-x64`

Mac runners use 10× the minutes of Linux runners on private repositories
(GitHub Free includes 2,000 minutes a month), so each run costs roughly
150–300 minutes.

### On a Mac

Install [Homebrew](https://brew.sh), then run:

```sh
./packaging/macos/build_macos.sh
```

The output is `packaging/dist/VideoDownloader-<version>-macos-<arch>.dmg`.

**For your friend:** open the `.dmg` and drag *Video Downloader* to
*Applications*. The app isn't notarized by Apple, so the first time it
won't open. Go to *System Settings* → *Privacy & Security*, scroll down,
and click *Open Anyway*. Or run this in Terminal:

```sh
xattr -dr com.apple.quarantine "/Applications/Video Downloader.app"
```

## Getting updates from upstream

The changes to upstream files are small. Windows and macOS code lives in
new files (`src/util/os_compat.py` and `packaging/`), so merging new
upstream versions should rarely conflict:

```sh
git remote add upstream https://github.com/Unrud/video-downloader.git  # once
git fetch upstream
git merge upstream/master
```

Then rebuild.

## What was changed for Windows and macOS

- `src/util/os_compat.py` (new): starting and stopping the yt-dlp process
  (job objects instead of process groups on Windows), reading its output
  (threads instead of polling, which doesn't work on Windows), opening
  folders in Explorer/Finder, and finding the Downloads folder.
- `src/downloader/__init__.py`, `src/util/path.py`: use those helpers.
- `src/downloader/yt_dlp_monkey_patch.py`, `src/downloader/yt_dlp_slave.py`:
  Windows can't delete the folder a program is currently in.
- `src/window.py`: download folders on another drive (e.g. `D:`) work.
- `packaging/launcher.py`: starts the app on Windows and macOS (takes the
  place of `src/video-downloader.in`), sets up translations and paths for
  the bundled programs.
- `packaging/smoke_test.py`: downloads a test video from a local web server
  to check that a build works.
