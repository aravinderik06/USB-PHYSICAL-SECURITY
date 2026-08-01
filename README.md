# USB Shield for Windows

USB Shield is a Windows utility for enforcing USB storage access by toggling USB mass storage support through the Windows registry. This repository contains the Windows build and packaging support for the project.

## Repository structure

- `usb_shield_windows/` - main application package and build support
- `usb_shield_windows/main.py` - application entry point
- `usb_shield_windows/watchdog.py` - persistent watchdog helper
- `usb_shield_windows/diagnose_usb.py` - USB diagnosis utilities
- `usb_shield_windows/usb_detect_debug.py` - USB detection helper code
- `usb_shield_windows/assets/` - static assets used by the app
- `usb_shield_windows/usb_state.json` - USB state persistence file
- `usb_shield_windows/build_windows.py` - build script for Windows executable

## Features

- Enable or disable USB mass storage by toggling the `UsbStor` service registry key
- Detect connected removable USB drives in Windows
- Play alert sound through Windows API on important events
- Support packaging as a standalone Windows executable

## Requirements

- Python 3.10+
- Windows OS
- `Pillow` (for bundled asset handling)
- `PyInstaller` (for building a standalone executable)

## Running in development

```cmd
cd usb_shield_windows\usb_shield_windows
python main.py
```

## Building the Windows executable

```cmd
pip install pyinstaller Pillow
cd usb_shield_windows\usb_shield_windows
python build_windows.py
```

Output: `dist\USB Shield.exe`

## Notes

- Administrator rights are required to modify `HKLM\SYSTEM\CurrentControlSet\Services\UsbStor`.
- The code includes Windows-specific logic for USB detection, alert sound playback, and app data path resolution.
- Packaged executables resolve bundled asset and state file paths correctly.

## License

This project is licensed under the MIT License. See the `LICENSE` file for details.
