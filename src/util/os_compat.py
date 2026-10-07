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

"""Helpers for running on Windows and macOS.

Everything platform specific that the upstream code does differently on
Linux lives here, so that changes to upstream files stay small.
"""

import contextlib
import os
import signal
import subprocess
import sys
import threading
import traceback

from gi.repository import GLib

from video_downloader.util import g_log

IS_WINDOWS = sys.platform == 'win32'
IS_MACOS = sys.platform == 'darwin'

if not IS_WINDOWS:
    import fcntl


def python_module_command(module):
    """Command line that runs `module` like `python -m module`."""
    if getattr(sys, 'frozen', False):
        # Bundled app (PyInstaller). The launcher handles this argument.
        return [sys.executable, '--run-module', module]
    executable = sys.executable
    if IS_WINDOWS:
        # Use the console interpreter instead of pythonw.exe. Combined with
        # CREATE_NO_WINDOW, programs started by yt-dlp (ffmpeg, deno)
        # inherit a hidden console instead of opening new windows.
        console_executable = os.path.join(
            os.path.dirname(executable), 'python.exe')
        if os.path.isfile(console_executable):
            executable = console_executable
    return [executable, '-u', '-m', module]


def popen_process_group(args, **kwargs):
    """Start a process with its own process group (job object on Windows),
       which can later be killed with `kill_process_group`."""
    if not IS_WINDOWS:
        return subprocess.Popen(args, preexec_fn=os.setpgrp, **kwargs)
    process = subprocess.Popen(
        args, creationflags=subprocess.CREATE_NO_WINDOW, **kwargs)
    try:
        process.win32_job = _win32_create_job(process)
    except OSError:
        process.win32_job = None
        g_log(None, GLib.LogLevelFlags.LEVEL_WARNING, '%s',
              traceback.format_exc())
    return process


def kill_process_group(process):
    """Kill all remaining processes in the group of `process`."""
    if not IS_WINDOWS:
        with contextlib.suppress(OSError):
            os.killpg(process.pid, signal.SIGKILL)
        return
    job, process.win32_job = getattr(process, 'win32_job', None), None
    if job:
        _win32_kernel32().TerminateJobObject(job, 1)
        _win32_kernel32().CloseHandle(job)


def watch_pipe(pipe, callback, *args):
    """Call `callback(data, *args)` from the GLib main loop whenever `data`
       was read from `pipe`. `data` is empty when the pipe got closed."""
    if not IS_WINDOWS:
        # WARNING: O_NONBLOCK can break multibyte decoding and line
        # splitting of `pipe` (use `pipe.buffer` directly)
        fcntl.fcntl(pipe, fcntl.F_SETFL, os.O_NONBLOCK)
        GLib.unix_fd_add_full(
            GLib.PRIORITY_DEFAULT_IDLE, pipe.fileno(), GLib.IOCondition.IN,
            lambda *_: callback(pipe.buffer.read(), *args))
        return

    # Windows doesn't support polling pipes, read them in a thread instead
    def dispatch(data):
        callback(data, *args)
        return GLib.SOURCE_REMOVE

    def read_pipe():
        while True:
            try:
                data = pipe.buffer.read1()
            except (OSError, ValueError):
                data = b''
            GLib.idle_add(dispatch, data,
                          priority=GLib.PRIORITY_DEFAULT_IDLE)
            if not data:
                break
    threading.Thread(target=read_pipe, daemon=True).start()


def open_in_file_manager(directory, filenames):
    """Show `directory` (with the first existing file of `filenames`
       selected) in the file manager.
       Returns `False` if the platform isn't handled here."""
    if not IS_WINDOWS and not IS_MACOS:
        return False
    path = directory
    for filename in filenames:
        if os.path.exists(os.path.join(directory, filename)):
            path = os.path.join(directory, filename)
            break
    if IS_WINDOWS:
        if path == directory:
            command = ['explorer', os.path.normpath(directory)]
        else:
            command = ['explorer', '/select,', os.path.normpath(path)]
    else:
        command = ['open', directory] if path == directory else [
            'open', '-R', path]
    try:
        # explorer.exe always returns a non-zero exit code
        subprocess.Popen(command)
    except OSError:
        g_log(None, GLib.LogLevelFlags.LEVEL_WARNING, '%s',
              traceback.format_exc())
    return True


def user_special_dir(name):
    """Look up a special folder by its xdg-user-dir name (e.g. DOWNLOAD)."""
    names = {'PUBLICSHARE': 'PUBLIC_SHARE'}
    directory = getattr(GLib.UserDirectory,
                        'DIRECTORY_' + names.get(name, name), None)
    if directory is None:
        return None
    return GLib.get_user_special_dir(directory)


_kernel32 = None


def _win32_kernel32():
    global _kernel32
    if _kernel32 is None:
        import ctypes
        from ctypes import wintypes
        _kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        _kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        _kernel32.CreateJobObjectW.argtypes = (
            wintypes.LPVOID, wintypes.LPCWSTR)
        _kernel32.SetInformationJobObject.argtypes = (
            wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD)
        _kernel32.AssignProcessToJobObject.argtypes = (
            wintypes.HANDLE, wintypes.HANDLE)
        _kernel32.TerminateJobObject.argtypes = (
            wintypes.HANDLE, wintypes.UINT)
        _kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    return _kernel32


def _win32_create_job(process):
    """Put `process` (and all its future children) into a job object."""
    import ctypes
    from ctypes import wintypes

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [(name, ctypes.c_ulonglong) for name in [
            'ReadOperationCount', 'WriteOperationCount',
            'OtherOperationCount', 'ReadTransferCount',
            'WriteTransferCount', 'OtherTransferCount']]

    class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [('PerProcessUserTimeLimit', ctypes.c_int64),
                    ('PerJobUserTimeLimit', ctypes.c_int64),
                    ('LimitFlags', wintypes.DWORD),
                    ('MinimumWorkingSetSize', ctypes.c_size_t),
                    ('MaximumWorkingSetSize', ctypes.c_size_t),
                    ('ActiveProcessLimit', wintypes.DWORD),
                    ('Affinity', ctypes.c_size_t),
                    ('PriorityClass', wintypes.DWORD),
                    ('SchedulingClass', wintypes.DWORD)]

    class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [('BasicLimitInformation',
                     JOBOBJECT_BASIC_LIMIT_INFORMATION),
                    ('IoInfo', IO_COUNTERS),
                    ('ProcessMemoryLimit', ctypes.c_size_t),
                    ('JobMemoryLimit', ctypes.c_size_t),
                    ('PeakProcessMemoryUsed', ctypes.c_size_t),
                    ('PeakJobMemoryUsed', ctypes.c_size_t)]

    JobObjectExtendedLimitInformation = 9
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
    kernel32 = _win32_kernel32()
    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = (
            JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE)
        if not kernel32.SetInformationJobObject(
                job, JobObjectExtendedLimitInformation,
                ctypes.byref(info), ctypes.sizeof(info)):
            raise ctypes.WinError(ctypes.get_last_error())
        if not kernel32.AssignProcessToJobObject(job, int(process._handle)):
            raise ctypes.WinError(ctypes.get_last_error())
    except BaseException:
        kernel32.CloseHandle(job)
        raise
    return job
