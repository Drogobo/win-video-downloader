# This file is part of Video Downloader.
#
# Video Downloader is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Video Downloader is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Video Downloader.  If not, see <http://www.gnu.org/licenses/>.

"""Launcher for the Windows and macOS bundles.

Takes the place of `src/video-downloader.in` (which is used on Linux).
It expects the files installed by meson below `<prefix>/share` and the
bundled tools (ffmpeg, ffprobe, deno) in `<prefix>/tools`.

Windows: `<prefix>/bin/pythonw.exe <prefix>/share/video-downloader/launcher.py`
macOS:   frozen with PyInstaller, `<prefix>` is `sys._MEIPASS`
"""

import contextlib
import ctypes
import ctypes.util
import gettext
import io
import locale
import os
import runpy
import signal
import subprocess
import sys

VERSION = '@VERSION@'
DOMAIN = 'video-downloader'

IS_WINDOWS = sys.platform == 'win32'
IS_MACOS = sys.platform == 'darwin'
FROZEN = getattr(sys, 'frozen', False)

if FROZEN:
    prefix = sys._MEIPASS
else:
    prefix = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))
datadir = os.path.join(prefix, 'share')
pkgdatadir = os.path.join(datadir, 'video-downloader')
localedir = os.path.join(datadir, 'locale')


def prepend_env_path(name, *paths):
    paths = [p for p in paths if os.path.isdir(p)]
    old = os.environ.get(name)
    os.environ[name] = os.pathsep.join([*paths, *([old] if old else [])])


def system_language():
    """Language of the desktop (e.g. `de_DE`), these platforms don't set
       the environment variables used by gettext."""
    with contextlib.suppress(Exception):
        if IS_WINDOWS:
            lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            return locale.windows_locale[lang_id]
        if IS_MACOS:
            for args in [['defaults', 'read', '-g', 'AppleLanguages'],
                         ['defaults', 'read', '-g', 'AppleLocale']]:
                output = subprocess.run(
                    args, capture_output=True, text=True).stdout
                for token in output.replace(',', ' ').split():
                    token = token.strip('()"').split('@')[0]
                    if token[:1].isalpha():
                        return token.replace('-', '_')
    return None


def bind_c_textdomain():
    """Translations in GtkBuilder files use libintl of the C library."""
    candidates = []
    if IS_WINDOWS:
        candidates.append('libintl-8.dll')
    else:
        candidates.extend([os.path.join(prefix, 'libintl.8.dylib'),
                           os.path.join(prefix, 'lib', 'libintl.8.dylib')])
        candidates.append(ctypes.util.find_library('intl'))
    for candidate in filter(None, candidates):
        try:
            libintl = ctypes.CDLL(candidate)
        except OSError:
            continue
        for symbol_prefix in ['libintl_', '']:
            try:
                bindtextdomain = getattr(
                    libintl, symbol_prefix + 'bindtextdomain')
                codeset = getattr(
                    libintl, symbol_prefix + 'bind_textdomain_codeset')
                textdomain = getattr(libintl, symbol_prefix + 'textdomain')
            except AttributeError:
                continue
            for function in [bindtextdomain, codeset, textdomain]:
                function.restype = ctypes.c_char_p
            if IS_WINDOWS:
                # libintl on Windows expects paths in the ANSI code page
                bindtextdomain.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
                bindtextdomain(DOMAIN.encode(), localedir.encode('mbcs'))
            else:
                bindtextdomain(DOMAIN.encode(), os.fsencode(localedir))
            codeset(DOMAIN.encode(), b'UTF-8')
            textdomain(DOMAIN.encode())
            return


def setup_environment():
    os.environ.setdefault('PYTHONUTF8', '1')
    # ffmpeg, ffprobe and deno (JavaScript runtime required by yt-dlp)
    prepend_env_path('PATH', os.path.join(prefix, 'tools'),
                     os.path.join(prefix, 'bin'))
    prepend_env_path('XDG_DATA_DIRS', datadir)
    prepend_env_path('GSETTINGS_SCHEMA_DIR',
                     os.path.join(pkgdatadir, 'schemas'))
    if not FROZEN:
        prepend_env_path('GI_TYPELIB_PATH',
                         os.path.join(prefix, 'lib', 'girepository-1.0'))
    with contextlib.suppress(ImportError):
        import certifi
        os.environ.setdefault('SSL_CERT_FILE', certifi.where())
    if not any(os.environ.get(name) for name in [
            'LANGUAGE', 'LC_ALL', 'LC_MESSAGES', 'LANG']):
        language = system_language()
        if language:
            os.environ['LANG'] = language + ('' if IS_WINDOWS else '.UTF-8')
    if IS_WINDOWS and not FROZEN:
        setup_gdk_pixbuf_loaders()


def setup_gdk_pixbuf_loaders():
    """Create `loaders.cache` (usually done by the package manager).
       It contains absolute paths, recreate it when the folder moved."""
    base = os.path.join(prefix, 'lib', 'gdk-pixbuf-2.0', '2.10.0')
    loaders_dir = os.path.join(base, 'loaders')
    query_loaders = os.path.join(prefix, 'bin',
                                 'gdk-pixbuf-query-loaders.exe')
    if not os.path.isdir(loaders_dir) or not os.path.isfile(query_loaders):
        return
    cache_files = [os.path.join(base, 'loaders.cache'), os.path.join(
        os.environ.get('LOCALAPPDATA') or os.path.expanduser('~'),
        'VideoDownloader', 'loaders.cache')]
    for cache_file in cache_files:
        with contextlib.suppress(OSError):
            with open(cache_file, encoding='utf-8') as f:
                if loaders_dir.replace('\\', '/') in f.read().replace(
                        '\\\\', '/').replace('\\', '/'):
                    os.environ['GDK_PIXBUF_MODULE_FILE'] = cache_file
                    return
    try:
        cache = subprocess.run(
            [query_loaders], capture_output=True, check=True,
            env={**os.environ, 'GDK_PIXBUF_MODULEDIR': loaders_dir},
            creationflags=subprocess.CREATE_NO_WINDOW).stdout
    except (OSError, subprocess.CalledProcessError):
        return
    for cache_file in cache_files:
        with contextlib.suppress(OSError):
            os.makedirs(os.path.dirname(cache_file), exist_ok=True)
            with open(cache_file, 'wb') as f:
                f.write(cache)
            os.environ['GDK_PIXBUF_MODULE_FILE'] = cache_file
            return


def run_module(module, args):
    """Used by the frozen app to run `video_downloader.downloader`
       (see `video_downloader.util.os_compat.python_module_command`)."""
    # Same as `python -u`
    for name, fd in [('stdout', 1), ('stderr', 2)]:
        setattr(sys, name, io.TextIOWrapper(
            io.FileIO(fd, 'w', closefd=False), encoding='utf-8',
            errors='backslashreplace', write_through=True))
    if sys.stdin is None:
        sys.stdin = io.TextIOWrapper(
            io.FileIO(0, 'r', closefd=False), encoding='utf-8')
    sys.argv = [module, *args]
    runpy.run_module(module, run_name='__main__', alter_sys=True)


def main():
    if FROZEN and sys.argv[1:2] == ['--run-module']:
        sys.path.insert(1, pkgdatadir)
        run_module(sys.argv[2], sys.argv[3:])
        return 0

    setup_environment()
    sys.path.insert(1, pkgdatadir)
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    with contextlib.suppress(AttributeError):  # missing on Windows/macOS
        locale.bindtextdomain(DOMAIN, localedir)
        locale.textdomain(DOMAIN)
    gettext.bindtextdomain(DOMAIN, localedir)
    gettext.textdomain(DOMAIN)
    with contextlib.suppress(locale.Error):
        locale.setlocale(locale.LC_ALL, '')
    bind_c_textdomain()

    import gi
    gi.require_version('Gdk', '4.0')
    gi.require_version('Gtk', '4.0')
    gi.require_version('Adw', '1')
    from gi.repository import Gio
    resource = Gio.Resource.load(os.path.join(
        pkgdatadir, 'video-downloader.gresource'))
    resource._register()

    from video_downloader import main
    return main.main(VERSION)


if __name__ == '__main__':
    sys.exit(main())
