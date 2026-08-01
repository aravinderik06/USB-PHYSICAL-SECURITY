import ctypes
import subprocess
import sys

kernel32 = ctypes.windll.kernel32
DRIVE_UNKNOWN = 0
DRIVE_NO_ROOT_DIR = 1
DRIVE_REMOVABLE = 2
DRIVE_FIXED = 3
DRIVE_REMOTE = 4
DRIVE_CDROM = 5
DRIVE_RAMDISK = 6

bitmask = kernel32.GetLogicalDrives()
print(f"Logical drives bitmask: {bitmask:#010x}")
for i in range(26):
    if bitmask & (1 << i):
        letter = f"{chr(65 + i)}:\\\\"
        dt = kernel32.GetDriveTypeW(ctypes.c_wchar_p(letter))
        print(f"Drive {letter} type: {dt}")
        if dt == DRIVE_REMOVABLE:
            # check for media
            try:
                free_bytes = ctypes.c_ulonglong(0)
                ok = kernel32.GetDiskFreeSpaceExW(ctypes.c_wchar_p(letter), ctypes.byref(free_bytes), None, None)
            except Exception as e:
                ok = False
            print(f"  Has media (GetDiskFreeSpaceExW ok): {bool(ok)}")

print("\nRunning PowerShell portable-device query (timeout 5s)...")
ps_command_filtered = (
    "Get-CimInstance Win32_PnPEntity -ErrorAction SilentlyContinue | "
    "Where-Object { ($_.PNPClass -eq 'Portable Devices') -and ($_.Name -match 'phone|android|iphone|ipad|mobile|mtp|ptp|samsung|pixel|huawei|oneplus') } | "
    "Select-Object -First 1 -ExpandProperty Name"
)

ps_command_all_portable = (
    "Get-CimInstance Win32_PnPEntity -ErrorAction SilentlyContinue | "
    "Where-Object { $_.PNPClass -eq 'Portable Devices' } | "
    "Select-Object -Property Name, PNPClass | Format-List -Force"
)

ps_command_all = (
    "Get-CimInstance Win32_PnPEntity -ErrorAction SilentlyContinue | "
    "Select-Object -First 30 -Property Name, PNPClass | Format-List -Force"
)
try:
    # Filtered (likely phone keywords)
    result = subprocess.run(["powershell", "-NoProfile", "-Command", ps_command_filtered], capture_output=True, text=True, timeout=6)
    print("--- Filtered portable-device query ---")
    print("Returncode:", result.returncode)
    print("Stdout:", repr(result.stdout))
    print("Stderr:", repr(result.stderr))
    print("Filtered result non-empty:", bool(result.stdout.strip()))

    # All portable devices (PNPClass)
    result2 = subprocess.run(["powershell", "-NoProfile", "-Command", ps_command_all_portable], capture_output=True, text=True, timeout=6)
    print("\n--- All devices with PNPClass == 'Portable Devices' ---")
    print(result2.stdout or "(none)")

    # Top Win32_PnPEntity sample to inspect other names
    result3 = subprocess.run(["powershell", "-NoProfile", "-Command", ps_command_all], capture_output=True, text=True, timeout=6)
    print("\n--- Sample Win32_PnPEntity entries (first 30) ---")
    print(result3.stdout or "(none)")
except Exception as e:
    print("PowerShell check failed:", e)

# Summarize: reproduce usb_device_present logic
present = False
try:
    bitmask = kernel32.GetLogicalDrives()
    for i in range(26):
        if bitmask & (1 << i):
            letter = f"{chr(65 + i)}:\\\\"
            if kernel32.GetDriveTypeW(ctypes.c_wchar_p(letter)) == DRIVE_REMOVABLE:
                try:
                    free_bytes = ctypes.c_ulonglong(0)
                    ok = kernel32.GetDiskFreeSpaceExW(ctypes.c_wchar_p(letter), ctypes.byref(free_bytes), None, None)
                except Exception:
                    ok = False
                if ok:
                    present = True
    # portable fallback
    found = False
    try:
        result = subprocess.run(["powershell", "-NoProfile", "-Command", ps_command_filtered], capture_output=True, text=True, timeout=5)
        found = result.returncode == 0 and bool(result.stdout.strip())
    except Exception:
        found = False
    if found:
        present = True
except Exception:
    present = False

print('\nFinal usb_device_present():', present)
