"""
Run this with NOTHING plugged into any USB port, and paste the full
output back. It shows exactly which check inside usb_device_present()
is firing, so we fix the real cause instead of guessing again.

Run:
    python diagnose_usb.py
"""

import platform
import subprocess
import sys

system = platform.system()
print(f"Platform: {system} {platform.release()}\n")

if system == "Windows":
    import ctypes
    kernel32 = ctypes.windll.kernel32
    DRIVE_TYPES = {0: "UNKNOWN", 1: "NO_ROOT_DIR", 2: "REMOVABLE",
                    3: "FIXED", 4: "REMOTE", 5: "CDROM", 6: "RAMDISK"}

    bitmask = kernel32.GetLogicalDrives()
    print("== Drive letters found ==")
    any_removable = False
    for i in range(26):
        if bitmask & (1 << i):
            letter = f"{chr(65 + i)}:\\"
            dtype = kernel32.GetDriveTypeW(ctypes.c_wchar_p(letter))
            dtype_name = DRIVE_TYPES.get(dtype, str(dtype))
            has_media = None
            if dtype == 2:
                any_removable = True
                try:
                    free_bytes = ctypes.c_ulonglong(0)
                    ok = kernel32.GetDiskFreeSpaceExW(
                        ctypes.c_wchar_p(letter), ctypes.byref(free_bytes), None, None
                    )
                    has_media = bool(ok)
                except Exception as e:
                    has_media = f"ERROR: {e}"
            print(f"  {letter}  type={dtype_name}"
                  + (f"  has_media={has_media}" if dtype == 2 else ""))
    if not any_removable:
        print("  (no REMOVABLE-type drive letters at all)")

    print("\n== Portable device (phone/MTP) PowerShell check ==")
    try:
        ps_command = (
            "Get-CimInstance Win32_PnPEntity -ErrorAction SilentlyContinue | "
            "Where-Object { $_.PNPClass -eq 'Portable Devices' -or $_.Name -match 'phone|android|iphone|ipad|mobile' } | "
            "Select-Object -First 5 Name, PNPClass | Format-Table -AutoSize"
        )
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_command],
            capture_output=True, text=True, timeout=10,
        )
        print("  returncode:", result.returncode)
        print("  stdout:")
        print("  " + (result.stdout.strip().replace("\n", "\n  ") or "(empty)"))
        if result.stderr.strip():
            print("  stderr:", result.stderr.strip())
    except Exception as e:
        print("  ERROR running PowerShell check:", e)

elif system == "Darwin":
    out = subprocess.run(
        ["system_profiler", "SPUSBDataType"],
        capture_output=True, text=True, timeout=10,
    ).stdout
    lowered = out.lower()
    for sig in ("mass storage", "removable media: yes"):
        print(f"  signal '{sig}' present: {sig in lowered}")
    print("\n-- full system_profiler output below --\n")
    print(out)

else:
    print("Linux/other platform — usb_device_present() always returns False here.")

print("\nDone. Paste this whole output back.")
