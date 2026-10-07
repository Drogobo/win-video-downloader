#!/usr/bin/env python3
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

"""Build a portable Windows version of Video Downloader on Linux.

GTK, libadwaita, Python and PyGObject come from the MSYS2 (UCRT64)
repository, yt-dlp and its pure Python dependencies from PyPI, ffmpeg from
yt-dlp/FFmpeg-Builds and deno from denoland/deno. Nothing gets executed
from the downloaded packages, they are only unpacked.

The result is a zip file containing a folder that can be extracted anywhere
on a Windows 10/11 (x64) computer.
"""

import argparse
import hashlib
import io
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile

MSYS2_REPO = 'https://repo.msys2.org/mingw/ucrt64/'
MSYS2_DB = 'ucrt64.db'
MSYS2_PREFIX = 'mingw-w64-ucrt-x86_64-'
MSYS2_ROOT = 'ucrt64/'
MSYS2_PACKAGES = [
    'python',
    'python-gobject',
    'gtk4',
    'libadwaita',
    'adwaita-icon-theme',
    'gdk-pixbuf2',
    'librsvg',  # SVG support for icons
]
# Usually pulled in as dependencies anyway, and C extensions used by yt-dlp
MSYS2_OPTIONAL_PACKAGES = [
    'hicolor-icon-theme',
    'python-brotli',
    'python-pycryptodomex',
]
# Dependencies that are not needed (tkinter)
MSYS2_EXCLUDED_PACKAGES = ['tcl', 'tk']
# yt-dlp and its pure Python dependencies (always the latest version)
PYPI_PACKAGES = [
    'yt-dlp',
    'yt-dlp-ejs',
    'certifi',
    'requests',
    'urllib3',
    'idna',
    'charset-normalizer',
    'mutagen',
    'websockets',
]
FFMPEG_URL = ('https://github.com/yt-dlp/FFmpeg-Builds/releases/download/'
              'latest/ffmpeg-master-latest-win64-gpl.zip')
FFMPEG_CHECKSUMS_URL = ('https://github.com/yt-dlp/FFmpeg-Builds/releases/'
                        'download/latest/checksums.sha256')
DENO_URL = ('https://github.com/denoland/deno/releases/latest/download/'
            'deno-x86_64-pc-windows-msvc.zip')
DENO_CHECKSUM_URL = DENO_URL + '.sha256sum'
# Paths (relative to the MSYS2 root) that are not needed at runtime
EXCLUDED_PATHS = re.compile(r'''^(
    include/ | share/doc/ | share/man/ | share/info/ | share/gtk-doc/ |
    share/gir-1\.0/ | share/aclocal/ | share/pkgconfig/ | share/vala/ |
    share/gettext/ | share/bash-completion/ | share/zsh/ |
    lib/pkgconfig/ | lib/cmake/ | .*\.a$ |
    lib/python3\.[0-9]+/(test|idlelib|tkinter|turtledemo|lib2to3)/
)''', re.VERBOSE)
ICON_SIZES = [16, 24, 32, 48, 64, 128, 256]

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
PACKAGING_DIR = os.path.join(ROOT_DIR, 'packaging')


def log(message, *args):
    print('==> ' + message % args, file=sys.stderr, flush=True)


def fetch(url):
    request = urllib.request.Request(
        url, headers={'User-Agent': 'video-downloader-build'})
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def download(url, path, sha256=None):
    """Download `url` to `path` (skipped if it exists with `sha256`)."""
    if os.path.exists(path):
        if sha256 is None or file_sha256(path) == sha256:
            return path
    log('Downloading %s', url)
    request = urllib.request.Request(
        url, headers={'User-Agent': 'video-downloader-build'})
    tmp_path = path + '.tmp'
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with urllib.request.urlopen(request, timeout=120) as response, \
            open(tmp_path, 'wb') as f:
        shutil.copyfileobj(response, f, 1024 * 1024)
    if sha256 is not None and file_sha256(tmp_path) != sha256:
        os.remove(tmp_path)
        raise RuntimeError('checksum mismatch: %s' % url)
    os.replace(tmp_path, path)
    return path


def file_sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def open_decompressed(path):
    """Open a (possibly zstd, gzip or xz compressed) file for reading."""
    with open(path, 'rb') as f:
        magic = f.read(4)
    if magic != b'\x28\xb5\x2f\xfd':  # not zstd
        return open(path, 'rb')
    try:
        from compression import zstd  # Python >= 3.14
        return zstd.open(path, 'rb')
    except ImportError:
        pass
    try:
        import zstandard
        return zstandard.ZstdDecompressor().stream_reader(open(path, 'rb'))
    except ImportError:
        pass
    if not shutil.which('zstd'):
        sys.exit('ERROR: zstd is required (install the "zstd" package)')
    return io.BytesIO(subprocess.run(
        ['zstd', '-d', '-c', path], check=True, stdout=subprocess.PIPE
    ).stdout)


# ---------------------------------------------------------------- MSYS2 --

def parse_desc(text):
    fields = {}
    for block in text.strip().split('\n\n'):
        lines = block.strip().split('\n')
        if lines and re.fullmatch(r'%[A-Z0-9]+%', lines[0]):
            fields[lines[0].strip('%')] = lines[1:]
    return fields


def strip_version(dependency):
    return re.split(r'[<>=:]', dependency, maxsplit=1)[0].strip()


def load_msys2_db(cache_dir):
    db_path = os.path.join(cache_dir, MSYS2_DB)
    if os.path.exists(db_path):
        os.remove(db_path)  # always use the latest package versions
    download(MSYS2_REPO + MSYS2_DB, db_path)
    packages = {}
    provides = {}
    with open_decompressed(db_path) as f, \
            tarfile.open(fileobj=f, mode='r|*') as tar:
        for member in tar:
            if not member.isfile() or not member.name.endswith('/desc'):
                continue
            desc = parse_desc(tar.extractfile(member).read().decode())
            name = desc['NAME'][0]
            packages[name] = desc
            for provided in desc.get('PROVIDES', []):
                provides.setdefault(strip_version(provided), name)
    return packages, provides


def resolve_msys2_packages(packages, provides):
    excluded = {MSYS2_PREFIX + n for n in MSYS2_EXCLUDED_PACKAGES}
    required = [MSYS2_PREFIX + n for n in MSYS2_PACKAGES]
    for name in MSYS2_OPTIONAL_PACKAGES:
        if MSYS2_PREFIX + name in packages:
            required.append(MSYS2_PREFIX + name)
        else:
            log('WARNING: optional package %s not found', name)
    resolved = {}
    queue = list(required)
    while queue:
        name = strip_version(queue.pop(0))
        if name in excluded:
            continue
        if name not in packages:
            if name not in provides:
                raise RuntimeError('MSYS2 package not found: %s' % name)
            name = provides[name]
        if name in resolved:
            continue
        resolved[name] = packages[name]
        queue.extend(packages[name].get('DEPENDS', []))
    return resolved


def extract_msys2_package(path, dest):
    with open_decompressed(path) as f, \
            tarfile.open(fileobj=f, mode='r|*') as tar:
        for member in tar:
            if not member.name.startswith(MSYS2_ROOT):
                continue  # .PKGINFO, .BUILDINFO, .MTREE, ...
            rel_path = member.name[len(MSYS2_ROOT):]
            if (not rel_path or EXCLUDED_PATHS.match(rel_path) or
                    '..' in rel_path.split('/')):
                continue
            target = os.path.join(dest, *rel_path.split('/'))
            if member.isdir():
                os.makedirs(target, exist_ok=True)
            elif member.isfile():
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with tar.extractfile(member) as src, \
                        open(target, 'wb') as dst:
                    shutil.copyfileobj(src, dst)
            elif member.islnk() or member.issym():
                link = member.linkname
                if member.islnk():
                    if not link.startswith(MSYS2_ROOT):
                        continue
                    source = os.path.join(
                        dest, *link[len(MSYS2_ROOT):].split('/'))
                else:
                    source = os.path.join(os.path.dirname(target), link)
                if os.path.isfile(source):
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    shutil.copyfile(source, target)


def install_msys2(cache_dir, dest):
    log('Resolving MSYS2 packages')
    packages, provides = load_msys2_db(cache_dir)
    resolved = resolve_msys2_packages(packages, provides)
    log('Installing %d MSYS2 packages', len(resolved))
    for name, desc in sorted(resolved.items()):
        filename = desc['FILENAME'][0]
        path = download(MSYS2_REPO + filename,
                        os.path.join(cache_dir, 'msys2', filename),
                        desc['SHA256SUM'][0])
        extract_msys2_package(path, dest)
    return sorted('%s %s' % (name[len(MSYS2_PREFIX):], desc['VERSION'][0])
                  for name, desc in resolved.items())


# ----------------------------------------------------------------- PyPI --

def install_pypi(cache_dir, site_packages):
    versions = []
    for name in PYPI_PACKAGES:
        info = json.loads(fetch('https://pypi.org/pypi/%s/json' % name))
        wheels = [f for f in info['urls'] if f['packagetype'] == 'bdist_wheel'
                  and f['filename'].endswith('-none-any.whl')
                  and re.search(r'-py3[0-9]*(\.py3[0-9]*)*-',
                                f['filename'])]
        if not wheels:
            log('WARNING: no pure Python wheel for %s', name)
            continue
        wheel = wheels[0]
        path = download(wheel['url'], os.path.join(
            cache_dir, 'pypi', wheel['filename']), wheel['digests']['sha256'])
        log('Installing %s %s', name, info['info']['version'])
        with zipfile.ZipFile(path) as z:
            for member in z.infolist():
                parts = member.filename.split('/')
                if member.is_dir() or '..' in parts:
                    continue
                if parts[0].endswith('.data'):
                    if len(parts) < 3 or parts[1] not in ('purelib',
                                                          'platlib'):
                        continue  # scripts, man pages, ...
                    parts = parts[2:]
                target = os.path.join(site_packages, *parts)
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with z.open(member) as src, open(target, 'wb') as dst:
                    shutil.copyfileobj(src, dst)
        versions.append('%s %s' % (name, info['info']['version']))
    return versions


# ---------------------------------------------------------------- tools --

def install_tools(cache_dir, tools_dir):
    os.makedirs(tools_dir, exist_ok=True)
    # ffmpeg
    checksums = fetch(FFMPEG_CHECKSUMS_URL).decode()
    filename = FFMPEG_URL.rsplit('/', 1)[1]
    match = re.search(r'([0-9a-f]{64})\s+\*?%s\s*$' % re.escape(filename),
                      checksums, re.MULTILINE)
    path = download(FFMPEG_URL, os.path.join(cache_dir, 'tools', filename),
                    match.group(1) if match else None)
    with zipfile.ZipFile(path) as z:
        for member in z.namelist():
            if re.search(r'/bin/(ffmpeg|ffprobe)\.exe$', member):
                with z.open(member) as src, open(os.path.join(
                        tools_dir, os.path.basename(member)), 'wb') as dst:
                    shutil.copyfileobj(src, dst)
    # deno
    match = re.search(r'\b([0-9a-fA-F]{64})\b',
                      fetch(DENO_CHECKSUM_URL).decode())
    path = download(DENO_URL, os.path.join(
        cache_dir, 'tools', DENO_URL.rsplit('/', 1)[1]),
        match.group(1).lower() if match else None)
    with zipfile.ZipFile(path) as z:
        with z.open('deno.exe') as src, \
                open(os.path.join(tools_dir, 'deno.exe'), 'wb') as dst:
            shutil.copyfileobj(src, dst)


# ----------------------------------------------------------- app & glue --

def meson_stage(build_dir):
    """Build and install the app with meson (the same way as on Linux)."""
    meson_dir = os.path.join(build_dir, 'meson')
    stage_dir = os.path.join(build_dir, 'stage')
    shutil.rmtree(stage_dir, ignore_errors=True)
    if not os.path.exists(os.path.join(meson_dir, 'build.ninja')):
        shutil.rmtree(meson_dir, ignore_errors=True)
        subprocess.run(['meson', 'setup', meson_dir, ROOT_DIR,
                        '--prefix=/usr'], check=True)
    subprocess.run(['meson', 'install', '-C', meson_dir,
                    '--destdir', stage_dir], check=True)
    version = json.loads(subprocess.run(
        ['meson', 'introspect', meson_dir, '--projectinfo'], check=True,
        stdout=subprocess.PIPE).stdout)['version']
    return os.path.join(stage_dir, 'usr'), version


def install_app(stage, dest, version):
    share = os.path.join(dest, 'share')
    for subdir in ['video-downloader', 'locale', 'icons',
                   os.path.join('glib-2.0', 'schemas')]:
        shutil.copytree(os.path.join(stage, 'share', subdir),
                        os.path.join(share, subdir), dirs_exist_ok=True)
    with open(os.path.join(PACKAGING_DIR, 'launcher.py')) as f:
        launcher = f.read().replace('@VERSION@', version)
    with open(os.path.join(share, 'video-downloader', 'launcher.py'),
              'w') as f:
        f.write(launcher)
    subprocess.run(['glib-compile-schemas',
                    os.path.join(share, 'glib-2.0', 'schemas')], check=True)


def make_ico(stage, path):
    """Create a Windows icon from the PNG icons (PNG compressed ICO)."""
    svg = os.path.join(stage, 'share', 'icons', 'hicolor', 'scalable',
                       'apps', 'com.github.unrud.VideoDownloader.svg')
    images = []
    for size in ICON_SIZES:
        images.append(subprocess.run(
            ['rsvg-convert', '--width', str(size), '--height', str(size),
             '--keep-aspect-ratio', '--format', 'png', svg],
            check=True, stdout=subprocess.PIPE).stdout)
    header = struct.pack('<HHH', 0, 1, len(images))
    offset = len(header) + 16 * len(images)
    entries = b''
    for size, data in zip(ICON_SIZES, images):
        entries += struct.pack('<BBBBHHII', size % 256, size % 256, 0, 0, 1,
                               32, len(data), offset)
        offset += len(data)
    with open(path, 'wb') as f:
        f.write(header + entries + b''.join(images))


def build_launcher(build_dir, stage, dest):
    gcc = shutil.which('x86_64-w64-mingw32-gcc')
    windres = shutil.which('x86_64-w64-mingw32-windres')
    if not gcc or not windres:
        log('WARNING: mingw-w64-gcc not found, using a .bat file to start '
            'the program (it briefly shows a console window)')
        with open(os.path.join(dest, 'Video Downloader.bat'), 'w',
                  newline='\r\n') as f:
            f.write('@echo off\n'
                    'start "" "%~dp0bin\\pythonw.exe" -X utf8 '
                    '"%~dp0share\\video-downloader\\launcher.py" %*\n')
        return
    ico = os.path.join(build_dir, 'icon.ico')
    make_ico(stage, ico)
    rc = os.path.join(build_dir, 'icon.rc')
    with open(rc, 'w') as f:
        f.write('1 ICON "icon.ico"\n')
    res = os.path.join(build_dir, 'icon.o')
    subprocess.run([windres, rc, '-O', 'coff', '-o', res], check=True,
                   cwd=build_dir)
    subprocess.run([gcc, '-municode', '-mwindows', '-O2', '-s', '-o',
                    os.path.join(dest, 'Video Downloader.exe'),
                    os.path.join(PACKAGING_DIR, 'windows', 'launcher.c'),
                    res], check=True)


def write_readme(dest, version, versions):
    with open(os.path.join(dest, 'README.txt'), 'w', newline='\r\n') as f:
        title = 'Video Downloader %s for Windows' % version
        f.write('%s\n%s\n\n' % (title, '=' * len(title)))
        f.write('Start "Video Downloader.exe" (or "Video Downloader.bat").\n'
                'Keep all files in this folder together.\n\n'
                'Downloads are saved to Downloads\\VideoDownloader by '
                'default.\n\n'
                'Video Downloader is free software (GPL-3.0-or-later), '
                'source code:\nhttps://github.com/Unrud/video-downloader\n\n'
                'Bundled components:\n')
        for line in versions:
            f.write('  %s\n' % line)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--build-dir', default=os.path.join(
        PACKAGING_DIR, 'build', 'windows'),
        help='directory for temporary files and download cache')
    parser.add_argument('--output-dir', default=os.path.join(
        PACKAGING_DIR, 'dist'), help='where to put the zip file')
    parser.add_argument('--no-zip', action='store_true',
                        help='only create the folder, not the zip file')
    args = parser.parse_args()

    for program in ['meson', 'ninja', 'glib-compile-schemas',
                    'glib-compile-resources', 'msgfmt', 'rsvg-convert']:
        if not shutil.which(program):
            sys.exit('ERROR: %s not found (see packaging/README.md)'
                     % program)

    build_dir = os.path.abspath(args.build_dir)
    cache_dir = os.path.join(build_dir, 'cache')
    os.makedirs(cache_dir, exist_ok=True)

    log('Building app with meson')
    stage, version = meson_stage(build_dir)
    name = 'VideoDownloader-%s-windows-x64' % version
    dest = os.path.join(build_dir, name)
    shutil.rmtree(dest, ignore_errors=True)
    os.makedirs(dest)

    versions = install_msys2(cache_dir, dest)
    python_libs = [d for d in os.listdir(os.path.join(dest, 'lib'))
                   if re.fullmatch(r'python3\.[0-9]+', d)]
    if len(python_libs) != 1:
        sys.exit('ERROR: could not find Python in MSYS2 packages')
    site_packages = os.path.join(dest, 'lib', python_libs[0],
                                 'site-packages')
    versions += install_pypi(cache_dir, site_packages)
    log('Installing ffmpeg and deno')
    install_tools(cache_dir, os.path.join(dest, 'tools'))
    log('Installing Video Downloader %s', version)
    install_app(stage, dest, version)
    build_launcher(build_dir, stage, dest)
    write_readme(dest, version, versions)

    if args.no_zip:
        log('Done: %s', dest)
        return
    os.makedirs(args.output_dir, exist_ok=True)
    zip_path = os.path.join(os.path.abspath(args.output_dir), name + '.zip')
    log('Creating %s', zip_path)
    with tempfile.NamedTemporaryFile(
            dir=os.path.dirname(zip_path), suffix='.zip',
            delete=False) as tmp:
        tmp_path = tmp.name
    try:
        with zipfile.ZipFile(tmp_path, 'w', zipfile.ZIP_DEFLATED,
                             compresslevel=9) as z:
            for dirpath, dirnames, filenames in os.walk(dest):
                dirnames.sort()
                for filename in sorted(filenames):
                    path = os.path.join(dirpath, filename)
                    z.write(path, os.path.join(
                        name, os.path.relpath(path, dest)))
        os.replace(tmp_path, zip_path)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
    log('Done: %s', zip_path)


if __name__ == '__main__':
    main()
