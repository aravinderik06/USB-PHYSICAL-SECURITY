"""
USB Shield — Background Watchdog
----------------------------------
Keeps monitoring for USB insertion even when the main USB Shield window
isn't open, and pops the same password-gated Allow/Block threat alert
the instant a new device is detected.

WHY A SEPARATE PROCESS, AND ITS REAL LIMITS
=============================================
A plain desktop Python app (this one included) only runs code while its
process is alive — there's no way for a closed app to "wake up" on its
own. To get something that behaves like an always-on guard, this script
runs as its own lightweight background process with no visible window
(it shows a popup ONLY when there's something to alert on), and you set
it to start automatically with your OS login (see bottom of this file).

This is the honest, real-world version of "always on": a small resident
process polling in the background, not a kernel-level driver. It can
detect insertion and gate the decision behind the APP password (never
your OS/Windows/macOS login password) — but on macOS it still can't
physically sever a USB port without an MDM profile, same limitation as
the main app.

RUNNING IT
===========
    python watchdog.py

INSTALLING IT TO AUTO-START (so it's truly "always on")
===========================================================
Windows:
    1. Press Win+R, type: shell:startup, hit Enter
    2. Create a shortcut to:  pythonw.exe  "<full path to>\\watchdog.py"
       (use pythonw.exe, not python.exe, so no console window appears)

macOS (LaunchAgent):
    1. Create ~/Library/LaunchAgents/com.usbshield.watchdog.plist with:

       <?xml version="1.0" encoding="UTF-8"?>
       <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
         "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
       <plist version="1.0"><dict>
         <key>Label</key><string>com.usbshield.watchdog</string>
         <key>ProgramArguments</key>
         <array>
           <string>/usr/bin/python3</string>
           <string>/full/path/to/watchdog.py</string>
         </array>
         <key>RunAtLoad</key><true/>
         <key>KeepAlive</key><true/>
       </dict></plist>

    2. Run:  launchctl load ~/Library/LaunchAgents/com.usbshield.watchdog.plist
"""

import datetime
import platform
import tkinter as tk

from main import (
    REGISTRATION_FILE, RegistrationStore, ThreatAlertDialog,
    apply_usb_state, usb_device_present, USB_POLL_INTERVAL_MS, log_event,
)


class Watchdog:
    def __init__(self):
        self.store = RegistrationStore(REGISTRATION_FILE)

        # A withdrawn (invisible) root window — required by Tk to run any
        # dialogs/timers at all, but never shown to the user.
        self.root = tk.Tk()
        self.root.withdraw()

        if not self.store.exists():
            print("USB Shield Watchdog: no device registration found yet. "
                  "Run main.py once to register before starting the watchdog.")
            self.root.destroy()
            return

        self._last_present = usb_device_present()
        self._locked = True  # watchdog assumes locked/protected by default
        print("USB Shield Watchdog: running in the background. Ctrl+C to stop.")
        self._poll()
        self.root.mainloop()

    def _poll(self):
        present = usb_device_present()

        if present != self._last_present:
            log_event("CONNECTED" if present else "DISCONNECTED",
                       f"(watchdog) USB device {'connected' if present else 'removed'}.")

        if self._locked and present and not self._last_present:
            self._handle_threat()

        self._last_present = present
        self.root.after(USB_POLL_INTERVAL_MS, self._poll)

    def _handle_threat(self):
        threat_info = {
            "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "device_type": "Removable USB storage",
            "platform": f"{platform.system()} {platform.release()}",
            "action": "Device inserted while no USB Shield window is open",
        }
        log_event("THREAT", "(watchdog) Unrecognized USB insertion — action HELD, awaiting decision.")
        dlg = ThreatAlertDialog(self.root, threat_info, self.store)
        if dlg.result == "allow":
            apply_usb_state(True)
            self._locked = False
            log_event("THREAT", "(watchdog) ALLOWED by user (app password verified).")
            print(f"[{threat_info['time']}] Threat ALLOWED (app password verified).")
        else:
            apply_usb_state(False)
            log_event("THREAT", "(watchdog) BLOCKED by user.")
            print(f"[{threat_info['time']}] Threat BLOCKED.")


if __name__ == "__main__":
    Watchdog()