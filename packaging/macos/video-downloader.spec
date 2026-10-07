# -*- mode: python -*-
# PyInstaller spec for macOS, used by build_macos.sh (which sets the VD_*
# environment variables).

import os

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

version = os.environ['VD_VERSION']
stage = os.environ['VD_STAGE']
resources = os.environ['VD_RESOURCES']
pkgdatadir = os.path.join(stage, 'share', 'video-downloader')

a = Analysis(
    [os.path.join(resources, 'launcher.py')],
    pathex=[pkgdatadir],
    binaries=[
        (os.environ['VD_FFMPEG'], 'tools'),
        (os.environ['VD_FFPROBE'], 'tools'),
        (os.environ['VD_DENO'], 'tools'),
    ],
    datas=[
        (os.path.join(pkgdatadir, 'video-downloader.gresource'),
         'share/video-downloader'),
        (os.path.join(resources, 'schemas'), 'share/video-downloader/schemas'),
        (os.path.join(stage, 'share', 'locale'), 'share/locale'),
        (os.path.join(stage, 'share', 'icons'), 'share/icons'),
        *collect_data_files('yt_dlp_ejs'),
    ],
    hiddenimports=[
        *collect_submodules('video_downloader'),
        'video_downloader.downloader.__main__',
    ],
    hooksconfig={
        'gi': {
            'module-versions': {'Gtk': '4.0', 'Gdk': '4.0'},
            'icons': ['Adwaita', 'hicolor'],
        },
    },
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Video Downloader',
    console=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name='Video Downloader', upx=False)
app = BUNDLE(
    coll,
    name='Video Downloader.app',
    icon=os.path.join(resources, 'icon.icns'),
    bundle_identifier='com.github.unrud.VideoDownloader',
    version=version,
    info_plist={
        'CFBundleDisplayName': 'Video Downloader',
        'CFBundleShortVersionString': version,
        'NSHighResolutionCapable': True,
        'NSHumanReadableCopyright': 'GPL-3.0-or-later',
    },
)
