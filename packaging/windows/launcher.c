/* Starts "bin\pythonw.exe share\video-downloader\launcher.py" relative to
 * the location of this executable.
 *
 * Build: x86_64-w64-mingw32-gcc -municode -mwindows -O2 launcher.c
 */

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>
#include <wchar.h>

#define MAX_LEN 32768

int WINAPI wWinMain(HINSTANCE instance, HINSTANCE prev_instance,
                    PWSTR args, int show)
{
    static wchar_t dir[MAX_LEN], python[MAX_LEN], command[MAX_LEN];
    STARTUPINFOW startup_info = {sizeof(startup_info)};
    PROCESS_INFORMATION process_info;
    wchar_t *sep;
    DWORD len;

    (void)instance;
    (void)prev_instance;
    (void)show;
    len = GetModuleFileNameW(NULL, dir, MAX_LEN);
    if (len == 0 || len >= MAX_LEN)
        return 1;
    sep = wcsrchr(dir, L'\\');
    if (sep)
        *sep = L'\0';
    _snwprintf(python, MAX_LEN, L"%ls\\bin\\pythonw.exe", dir);
    _snwprintf(command, MAX_LEN,
               L"\"%ls\" -X utf8 \"%ls\\share\\video-downloader\\launcher.py\""
               L" %ls", python, dir, args ? args : L"");
    python[MAX_LEN - 1] = command[MAX_LEN - 1] = L'\0';
    if (!CreateProcessW(python, command, NULL, NULL, FALSE, 0, NULL, dir,
                        &startup_info, &process_info)) {
        MessageBoxW(NULL, L"Failed to start bin\\pythonw.exe.\n"
                    L"Extract the whole folder before running the program.",
                    L"Video Downloader", MB_ICONERROR);
        return 1;
    }
    CloseHandle(process_info.hThread);
    CloseHandle(process_info.hProcess);
    return 0;
}
