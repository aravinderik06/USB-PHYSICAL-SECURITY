# USB Shield — Windows Build

## What changed from the macOS package

`main.py` and `watchdog.py` were **already cross-platform** — they had real
Windows code paths for everything that matters:

| Feature | Windows implementation |
|---|---|
| USB enforcement | `apply_usb_state()` toggles the `UsbStor` registry key (`HKLM\SYSTEM\CurrentControlSet\Services\UsbStor`) via `reg add`, which actually disables/enables USB mass storage at the OS level — unlike macOS, which is stubbed (no public API without an MDM profile). |
| USB detection | `usb_device_present()` uses `ctypes` + `kernel32.GetLogicalDrives`/`GetDriveTypeW` to find removable drives. |
| Alert sound | `play_alert_sound()` uses `winsound.MessageBeep`. |
| App data folder | `app_data_dir()` already resolves to `%APPDATA%\USBShield` on Windows. |

So no logic changes were required there. Two things genuinely needed
converting:

1. **Asset/state-file path resolution for a packaged .exe.** The original
   code assumed `assets/` and `usb_state.json` always sit next to the
   running `.py`/`.app` file. That's fine for `python main.py`, but a
   PyInstaller `--onefile` .exe unpacks bundled data into a temp folder
   (`sys._MEIPASS`), not next to the executable. I added a `frozen` check
   in `main.py` so assets load from the right place and `usb_state.json`
   is written next to the .exe (writable) instead of into the read-only
   bundle.

2. **Packaging.** `setup.py` used `py2app`, which is macOS-only and
   targets `arm64` — it cannot build a Windows artifact at all. I replaced
   it with `build_windows.py`, which uses **PyInstaller** to produce a
   single-file `USB Shield.exe`.

## Building the .exe

```cmd
pip install pyinstaller Pillow
python build_windows.py
```

Output: `dist\USB Shield.exe`

The build embeds an application manifest requesting `requireAdministrator`,
so Windows will show a UAC prompt on launch — this is required because
writing to `HKLM\...\UsbStor` needs admin rights (the existing code already
detects and reports this failure if you skip elevation; the manifest just
makes it automatic instead of needing "Run as administrator" manually).

## Running without building (dev/testing)

```cmd
pip install Pillow
python main.py
```

## Auto-start watchdog (always-on protection)

`watchdog.py` already documents the Windows steps (Startup folder shortcut
using `pythonw.exe` so no console window appears) — see the docstring at
the top of that file. If you build the watchdog as a separate .exe too:

```cmd
python -m PyInstaller --name "USB Shield Watchdog" --onefile --windowed --manifest usb_shield.manifest --add-data "assets;assets" watchdog.py
```

then drop a shortcut to the resulting `.exe` into
`shell:startup` (Win+R → `shell:startup`).

## Known limitation carried over

`reg add` requires admin rights — if the app isn't elevated, the toggle
will report a clear "re-run as Administrator" message rather than silently
failing (this was already handled in `apply_usb_state`).
