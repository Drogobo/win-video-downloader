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

"""Smoke test for a build: loads GTK and downloads a generated video from a
local web server (converting it to MP3), without needing the internet.

Usage: smoke_test.py PREFIX
  PREFIX contains `share/video-downloader` (e.g. the Windows bundle or a
  meson installation). Run it with the Python interpreter of the build.
"""

import functools
import http.server
import os
import shutil
import subprocess
import sys
import tempfile
import threading


def main():
    prefix = os.path.abspath(sys.argv[1])
    pkgdatadir = os.path.join(prefix, 'share', 'video-downloader')
    sys.path.insert(0, pkgdatadir)
    bundle = os.path.exists(os.path.join(pkgdatadir, 'launcher.py'))
    if bundle:
        import launcher
        launcher.setup_environment()

    import gi
    gi.require_version('Gdk', '4.0')
    gi.require_version('Gtk', '4.0')
    gi.require_version('Adw', '1')
    from gi.repository import Adw, GLib, Gtk  # noqa: F401
    print('GTK %d.%d.%d' % (Gtk.MAJOR_VERSION, Gtk.MINOR_VERSION,
                            Gtk.MICRO_VERSION), flush=True)
    for tool in ['ffmpeg', 'ffprobe', 'deno']:
        print('%s: %s' % (tool, shutil.which(tool)), flush=True)
        assert shutil.which(tool) or not bundle and tool == 'deno', tool

    from video_downloader.downloader import Downloader, HandlerInterface
    from video_downloader.util.path import expand_path
    print('Download folder: %s' % expand_path('xdg-download/VideoDownloader'))

    tmp = tempfile.mkdtemp()
    serve_dir = os.path.join(tmp, 'serve')
    download_dir = os.path.join(tmp, 'download')
    os.makedirs(serve_dir)
    os.makedirs(download_dir)
    subprocess.run([
        'ffmpeg', '-loglevel', 'error',
        '-f', 'lavfi', '-i', 'testsrc=duration=3:size=320x240:rate=10',
        '-f', 'lavfi', '-i', 'sine=duration=3',
        '-shortest', os.path.join(serve_dir, 'test video.mp4')], check=True)
    server = http.server.ThreadingHTTPServer(
        ('127.0.0.1', 0), functools.partial(
            http.server.SimpleHTTPRequestHandler, directory=serve_dir))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = 'http://127.0.0.1:%d/test%%20video.mp4' % server.server_address[1]

    loop = GLib.MainLoop()
    result = {'errors': [], 'files': [], 'pulses': 0}

    class Handler(HandlerInterface):
        def get_download_dir(self):
            return download_dir

        def get_prefer_mpeg(self):
            return False

        def get_automatic_subtitles(self):
            return []

        def get_url(self):
            return url

        def get_mode(self):
            return 'audio'

        def get_resolution(self):
            return 1080

        def on_playlist_request(self):
            return False

        def on_error(self, msg):
            print('Error: %s' % msg, flush=True)
            result['errors'].append(msg)

        def on_progress(self, *args):
            pass

        def on_download_start(self, playlist_index, playlist_count, title):
            print('Downloading %r' % title, flush=True)

        def on_download_lock(self, name):
            return True

        def on_download_thumbnail(self, thumbnail):
            pass

        def on_download_finished(self, filename):
            print('Finished %r' % filename, flush=True)
            result['files'].append(filename)

        def on_pulse(self):
            result['pulses'] += 1

        def on_finished(self, success):
            result['success'] = success
            loop.quit()

    downloader = Downloader(Handler())
    downloader.start()
    GLib.timeout_add_seconds(300, loop.quit)
    loop.run()
    server.shutdown()
    print('Result: %r' % result, flush=True)
    print('Files: %r' % os.listdir(download_dir), flush=True)
    assert result.get('success'), 'download failed'
    assert not result['errors']
    assert result['files'] and result['files'][0].endswith('.mp3')
    assert os.listdir(download_dir) == result['files'], 'leftover files'
    shutil.rmtree(tmp)
    print('OK', flush=True)


if __name__ == '__main__':
    main()
