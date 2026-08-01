"""
Build script for USB Shield on Windows (replaces py2app's setup.py,
which only works on macOS).

Produces a single-file Windows .exe using PyInstaller.

SETUP
======
    pip install pyinstaller Pillow

BUILD
======
    python build_windows.py

Output goes to dist\\USB Shield.exe

NOTES
======
- Registry writes (UsbStor) require admin rights, so the build
  embeds a manifest requesting elevation — Windows will show the
  UAC prompt automatically when the .exe is launched.
- The 'assets' folder (toggle_on.png, toggle_off.png, usb_enabled.png,
  usb_disabled.png) is bundled into the exe via --add-data.
"""

import os
import subprocess
import sys

ASSETS_SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")

MANIFEST = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<assembly xmlns="urn:schemas-microsoft-com:asm.v1" manifestVersion="1.0">
  <trustInfo xmlns="urn:schemas-microsoft-com:asm.v3">
    <security>
      <requestedPrivileges>
        <requestedExecutionLevel level="requireAdministrator" uiAccess="false"/>
      </requestedPrivileges>
    </security>
  </trustInfo>
</assembly>
"""

if __name__ == "__main__":
    manifest_path = "usb_shield.manifest"
    with open(manifest_path, "w") as f:
        f.write(MANIFEST)

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", "USB Shield",
        "--onefile",
        "--windowed",
        "--manifest", manifest_path,
        f"--add-data={ASSETS_SRC};assets",
        "main.py",
    ]
    print("Running:", " ".join(cmd))
    subprocess.run(cmd, check=True)
