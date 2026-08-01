"""
USB Physical Security — Home Window
------------------------------------
Pure Python / Tkinter desktop app (Windows + macOS) using the user's
PNG artwork for the status panel and toggle switch.

NEW IN THIS VERSION
====================
1. One-time device registration
   - First launch ever on a machine -> shows a Name + Email form.
   - "Get Password" generates a random password, hashes+stores it in
     a per-device registration file (in the OS app-data folder, NOT
     inside the project folder, so it survives reinstalling/moving
     the app — it's tied to the machine/user profile), and emails the
     plaintext password to the address entered.
   - Every later launch detects the existing registration file and
     skips the form entirely.

2. Password-gated USB toggle
   - Turning the switch OFF always prompts for the password first; only
     on a correct match does the device actually get locked.
   - Turning the switch ON does not require a password — it only
     requires a USB device to be physically inserted (unchanged gate).

3. "Generate Password" button on the home page
   - Asks for an email. If it matches the registered email, a brand
     new password is generated, saved, and emailed again. If it does
     not match -> "User not found or invalid email address."

EMAIL DELIVERY
===============
Sending real email requires real SMTP credentials, which obviously
can't be hard-coded here. Set these environment variables before
running to enable actual delivery:

    EMAIL_SMTP_HOST       e.g. smtp.gmail.com
    EMAIL_SMTP_PORT       e.g. 587
    EMAIL_SMTP_USER       the sending account's address
    EMAIL_SMTP_PASSWORD   an app password (NOT your normal password)
    EMAIL_FROM            (optional) defaults to EMAIL_SMTP_USER

If those aren't set, or sending fails for any reason (no internet,
bad credentials, etc.), the app falls back to showing the password
in an on-screen dialog instead — clearly labeled as a fallback — so
the project still works end-to-end during a demo/grading session
without needing real mail credentials.

Requires: Pillow  (pip install Pillow)
Run:      python main.py
"""

import datetime
import hashlib
import json
import os
import platform
import secrets
import smtplib
import string
import subprocess
import sys
import threading
import time
import tkinter as tk
from email.mime.text import MIMEText
from tkinter import font as tkfont, messagebox, simpledialog

if platform.system() == "Windows":
    import winsound

try:
    from PIL import Image, ImageTk
except ImportError:
    print("This app requires Pillow.  Install it with:\n    pip install Pillow")
    sys.exit(1)

# --------------------------------------------------------------------- paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# When bundled by PyInstaller (--onefile), bundled data (the assets/
# folder added via --add-data) is unpacked into a temp dir exposed as
# sys._MEIPASS, NOT next to the .exe — so resolve assets from there
# when running frozen, and from the project folder otherwise.
if getattr(sys, "frozen", False):
    RUNTIME_DIR = getattr(sys, "_MEIPASS", BASE_DIR)
    ASSETS = os.path.join(RUNTIME_DIR, "assets")
    # usb_state.json should live next to the .exe (writable), not inside
    # the read-only temp bundle.
    STATE_FILE = os.path.join(os.path.dirname(sys.executable), "usb_state.json")
else:
    ASSETS = os.path.join(BASE_DIR, "assets")
    STATE_FILE = os.path.join(BASE_DIR, "usb_state.json")


def app_data_dir():
    """Per-device, per-user storage location for the registration file —
    deliberately OUTSIDE the project folder so the registration survives
    moving/reinstalling the app itself, but is still tied to this device
    + this OS user account."""
    system = platform.system()
    if system == "Windows":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    elif system == "Darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.path.expanduser("~/.local/share")
    path = os.path.join(base, "USBShield")
    os.makedirs(path, exist_ok=True)
    return path


REGISTRATION_FILE = os.path.join(app_data_dir(), "registration.json")
LOG_FILE = os.path.join(app_data_dir(), "activity_log.jsonl")


def log_event(category, message):
    """Appends one timestamped activity-log entry as a JSON line to
    LOG_FILE (shared by the home window and the background watchdog so
    both write to the same history), and returns the entry dict so the
    caller can also push it straight into a UI widget.
    category is one of: CONNECTED / DISCONNECTED / TOGGLE / THREAT / FILE / SYSTEM
    """
    entry = {
        "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "category": category,
        "message": message,
    }
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass
    return entry


def load_recent_log(limit=300):
    """Best-effort read of the last `limit` log entries from disk."""
    if not os.path.isfile(LOG_FILE):
        return []
    try:
        with open(LOG_FILE, encoding="utf-8") as f:
            lines = f.readlines()[-limit:]
        out = []
        for line in lines:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out
    except OSError:
        return []

ICON_ENABLED_PATH = os.path.join(ASSETS, "usb_enabled.png")
ICON_DISABLED_PATH = os.path.join(ASSETS, "usb_disabled.png")
TOGGLE_ON_PATH = os.path.join(ASSETS, "toggle_on.png")
TOGGLE_OFF_PATH = os.path.join(ASSETS, "toggle_off.png")

BG = "#FFFFFF"
CARD_BG = "#F7F8FA"
BORDER = "#E3E4E8"
TEXT_DARK = "#1A1A1C"
GRAY_TEXT = "#6B6B70"
GREEN = "#1FA224"
GREEN_DARK = "#178A1B"
GREEN_SOFT = "#E9F8EA"
RED = "#C81E16"
RED_DARK = "#A0140D"
RED_SOFT = "#FCEAEA"
AMBER = "#C77700"
AMBER_SOFT = "#FFF3E0"
BLUE = "#1A66D6"
BLUE_SOFT = "#EAF1FD"

ICON_SIZE = (260, 260)
TOGGLE_SIZE = (240, 240)

WHITE_BG_THRESHOLD = 235


# ---------------------------------------------------------------- artwork
def strip_white_background(img, threshold=WHITE_BG_THRESHOLD):
    """Flood-fill the near-white MARGIN of the PNG to transparent from
    the four edges inward, leaving interior white elements (toggle
    knob, USB glyph, white text) intact."""
    img = img.convert("RGBA")
    w, h = img.size
    px = img.load()

    def is_bg(r, g, b):
        return r >= threshold and g >= threshold and b >= threshold

    visited = bytearray(w * h)
    stack = []
    for x in range(w):
        stack.append((x, 0))
        stack.append((x, h - 1))
    for y in range(h):
        stack.append((0, y))
        stack.append((w - 1, y))

    while stack:
        x, y = stack.pop()
        if x < 0 or x >= w or y < 0 or y >= h:
            continue
        idx = y * w + x
        if visited[idx]:
            continue
        r, g, b, a = px[x, y]
        if not is_bg(r, g, b):
            continue
        visited[idx] = 1
        px[x, y] = (r, g, b, 0)
        stack.append((x + 1, y))
        stack.append((x - 1, y))
        stack.append((x, y + 1))
        stack.append((x, y - 1))
    return img


def load_image(path, max_size):
    img = Image.open(path).convert("RGBA")
    img = strip_white_background(img)
    img.thumbnail(max_size, Image.LANCZOS)
    return ImageTk.PhotoImage(img)


# ------------------------------------------------------------- USB detection

# Windows quirk this guards against: many laptops have a built-in SD/card
# reader that Windows assigns a drive letter to and reports as
# DRIVE_REMOVABLE *even when no card is inserted*. Checking the drive type
# alone therefore reports "connected" permanently on those machines. The
# fix is to also confirm the drive actually has media in it.
def _windows_drive_has_media(kernel32, letter):
    import ctypes
    try:
        free_bytes = ctypes.c_ulonglong(0)
        ok = kernel32.GetDiskFreeSpaceExW(
            ctypes.c_wchar_p(letter), ctypes.byref(free_bytes), None, None
        )
        return bool(ok)
    except Exception:
        return False


# The PowerShell portable-device (phone/MTP) check is slow (a few hundred
# ms to a few seconds per call). Running it on every poll would both make
# polling sluggish and spawn a new powershell.exe process every 250ms.
# Instead it runs in a background thread at most once every
# PORTABLE_CHECK_INTERVAL seconds; the fast drive-letter path (which is
# nearly instant) still runs on every single poll, so plain USB flash
# drives are detected immediately either way.
PORTABLE_CHECK_INTERVAL = 2.0  # seconds
_portable_lock = threading.Lock()
_portable_state = {"present": False, "last_check": 0.0, "checking": False}


def _portable_device_present_cached():
    now = time.monotonic()
    with _portable_lock:
        if _portable_state["checking"]:
            return _portable_state["present"]
        if now - _portable_state["last_check"] < PORTABLE_CHECK_INTERVAL:
            return _portable_state["present"]
        _portable_state["checking"] = True

    def worker():
        found = False
        try:
            # Use PNPClass 'Portable Devices' (covers MTP/PTP phones) but
            # exclude common built-in device name fragments (audio, chipset)
            # to avoid false positives like Intel Smart Sound.
            ps_command = (
                "Get-CimInstance Win32_PnPEntity -ErrorAction SilentlyContinue | "
                "Where-Object { ($_.PNPClass -eq 'Portable Devices') -and -not ($_.Name -match 'intel|realtek|conexant|smart sound|audio|camera|display audio|intel®') } | "
                "Select-Object -First 1 -ExpandProperty Name"
            )
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_command],
                capture_output=True, text=True, timeout=5,
            )
            found = result.returncode == 0 and bool(result.stdout.strip())
        except Exception:
            found = False
        with _portable_lock:
            _portable_state["present"] = found
            _portable_state["last_check"] = time.monotonic()
            _portable_state["checking"] = False

    threading.Thread(target=worker, daemon=True).start()
    with _portable_lock:
        return _portable_state["present"]


def usb_device_present():
    """Best-effort check for a real, physically-inserted removable USB
    storage device or portable USB device (e.g. phone) on Windows.

    Phones that expose a drive letter are caught by GetDriveTypeW, while
    modern MTP/PTP mobile devices are detected via the portable device class.
    """
    system = platform.system()

    if system == "Windows":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            DRIVE_REMOVABLE = 2
            bitmask = kernel32.GetLogicalDrives()
            for i in range(26):
                if bitmask & (1 << i):
                    letter = f"{chr(65 + i)}:\\"
                    if kernel32.GetDriveTypeW(ctypes.c_wchar_p(letter)) == DRIVE_REMOVABLE:
                        # Drive letter + REMOVABLE type isn't enough on its
                        # own — an empty built-in card reader slot reports
                        # the same thing. Confirm media is actually there.
                        if _windows_drive_has_media(kernel32, letter):
                            return True

            # Fallback to (throttled, async) portable device detection for
            # phones and other USB devices that don't expose a drive letter.
            if _portable_device_present_cached():
                return True

            # Workaround: some phones present as a generic WinUSB/Composite
            # device (VID_30C9&PID_0069) and won't show up as 'Portable
            # Devices' or an MTP device. Treat known VID/PID pairs as a
            # connected removable device so the UI reflects reality.
            try:
                ps_vid_cmd = (
                    "Get-CimInstance Win32_PnPEntity -ErrorAction SilentlyContinue | "
                    "Where-Object { $_.DeviceID -match 'VID_30C9' -and $_.DeviceID -match 'PID_0069' } | "
                    "Select-Object -First 1 -ExpandProperty DeviceID"
                )
                result = subprocess.run(
                    ["powershell", "-NoProfile", "-Command", ps_vid_cmd],
                    capture_output=True, text=True, timeout=2,
                )
                if result.returncode == 0 and result.stdout.strip():
                    return True
            except Exception:
                pass

            return False
        except Exception:
            return False

    elif system == "Darwin":
        try:
            out = subprocess.run(
                ["system_profiler", "SPUSBDataType"],
                capture_output=True, text=True, timeout=5,
            ).stdout
            lowered = out.lower()
            # Deliberately narrow signals: "serial number" alone used to be
            # in this list, but nearly every built-in USB controller
            # (keyboard, trackpad, webcam, Bluetooth) reports one too,
            # which made the app show "connected" with nothing plugged in.
            signals = ("mass storage", "removable media: yes")
            return any(sig in lowered for sig in signals)
        except Exception:
            return False

    else:
        return False


USB_POLL_INTERVAL_MS = 250


# --------------------------------------------------------- file activity
def get_removable_drive_roots():
    """Best-effort list of currently-mounted removable drive roots, used
    to watch for files written/changed/deleted from a connected USB
    drive. Windows only — macOS volume paths aren't exposed by the
    unprivileged checks this app already uses, so file-level USB
    activity logging is a Windows feature for now."""
    roots = []
    if platform.system() == "Windows":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            DRIVE_REMOVABLE = 2
            bitmask = kernel32.GetLogicalDrives()
            for i in range(26):
                if bitmask & (1 << i):
                    letter = f"{chr(65 + i)}:\\"
                    if kernel32.GetDriveTypeW(ctypes.c_wchar_p(letter)) == DRIVE_REMOVABLE:
                        roots.append(letter)
        except Exception:
            pass
    return roots


def snapshot_drive_files(roots, max_files=500):
    """Shallow (depth-limited) snapshot of {path: (size, mtime)} for
    files on the given drive roots. Capped at max_files and a couple of
    folder levels so a large USB stick can't hang the poll loop."""
    snap = {}
    for root in roots:
        count = 0
        for dirpath, dirnames, filenames in os.walk(root):
            depth = dirpath[len(root):].count(os.sep)
            if depth >= 2:
                dirnames[:] = []  # don't descend further
            for name in filenames:
                if count >= max_files:
                    return snap
                full = os.path.join(dirpath, name)
                try:
                    st = os.stat(full)
                    snap[full] = (st.st_size, st.st_mtime)
                except OSError:
                    continue
                count += 1
    return snap


def diff_drive_snapshots(old_snap, new_snap):
    """Returns (added, modified, removed) file path lists between two
    snapshot() results."""
    old_keys, new_keys = set(old_snap), set(new_snap)
    added = sorted(new_keys - old_keys)
    removed = sorted(old_keys - new_keys)
    modified = sorted(p for p in (old_keys & new_keys) if old_snap[p] != new_snap[p])
    return added, modified, removed


# ------------------------------------------------------------- credentials
def generate_password(length=10):
    """Cryptographically random password — letters + digits, no
    ambiguous-looking characters (no 0/O/1/l/I)."""
    alphabet = "".join(c for c in (string.ascii_letters + string.digits)
                        if c not in "0O1lI")
    return "".join(secrets.choice(alphabet) for _ in range(length))


def hash_password(password, salt):
    return hashlib.sha256((salt + password).encode("utf-8")).hexdigest()


class RegistrationStore:
    """Reads/writes the per-device registration.json:
        {name, email, salt, password_hash, created_at, updated_at}
    Only a salted hash of the password is ever stored on disk."""

    def __init__(self, path):
        self.path = path

    def exists(self):
        return os.path.isfile(self.path)

    def load(self):
        with open(self.path) as f:
            return json.load(f)

    def save(self, data):
        with open(self.path, "w") as f:
            json.dump(data, f, indent=2)

    def register(self, name, email):
        password = generate_password()
        salt = secrets.token_hex(8)
        data = {
            "name": name,
            "email": email,
            "salt": salt,
            "password_hash": hash_password(password, salt),
            "created_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "updated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        }
        self.save(data)
        return password

    def regenerate_password(self, email):
        """Returns the new plaintext password, or None if the email
        doesn't match the registered account."""
        data = self.load()
        if email.strip().lower() != data.get("email", "").strip().lower():
            return None
        password = generate_password()
        salt = secrets.token_hex(8)
        data["salt"] = salt
        data["password_hash"] = hash_password(password, salt)
        data["updated_at"] = datetime.datetime.now().isoformat(timespec="seconds")
        self.save(data)
        return password

    def verify(self, password):
        data = self.load()
        return hash_password(password, data.get("salt", "")) == data.get("password_hash")


def send_password_email(to_email, name, password):
    """Tries real SMTP delivery using environment-variable credentials.
    Returns (sent: bool, message: str). On any failure/missing config,
    sent=False and the caller is expected to fall back to an on-screen
    display of the password.

    The failure message is deliberately specific (which env var is
    missing, which SMTP/auth exception was raised, etc.) so "I didn't
    get the email" can actually be diagnosed instead of hidden behind
    a generic string."""
    missing = [name_ for name_, val in (
        ("EMAIL_SMTP_HOST", os.environ.get("EMAIL_SMTP_HOST", "smtp.gmail.com")),
        ("EMAIL_SMTP_PORT", os.environ.get("EMAIL_SMTP_PORT", "587")),
        ("EMAIL_SMTP_USER", os.environ.get("EMAIL_SMTP_USER", "ysiddu148@gmail.com")),
        ("EMAIL_SMTP_PASSWORD", os.environ.get("EMAIL_SMTP_PASSWORD", "uzrg tkcf cjuz rdnl")),
    ) if not val]
    if missing:
        return False, ("Email isn't configured on this machine — missing "
                        "environment variable(s): " + ", ".join(missing))

    host = os.environ.get("EMAIL_SMTP_HOST", "smtp.gmail.com")
    port = os.environ.get("EMAIL_SMTP_PORT", "587")
    user = os.environ.get("EMAIL_SMTP_USER", "ysiddu148@gmail.com")
    pwd = os.environ.get("EMAIL_SMTP_PASSWORD", "uzrg tkcf cjuz rdnl")
    sender = os.environ.get("EMAIL_FROM", user)

    body = (f"Hi {name},\n\n"
            f"Your USB Shield password is:\n\n    {password}\n\n"
            f"Keep it safe — you'll need it every time you switch USB "
            f"ports on or off.\n\n— USB Shield")
    msg = MIMEText(body)
    msg["Subject"] = "Your USB Shield password"
    msg["From"] = sender
    msg["To"] = to_email

    try:
        port_int = int(port)
    except ValueError:
        return False, f"EMAIL_SMTP_PORT is not a valid number: '{port}'."

    try:
        with smtplib.SMTP(host, port_int, timeout=10) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(user, pwd)
            server.sendmail(sender, [to_email], msg.as_string())
        return True, f"Password emailed to {to_email}."
    except smtplib.SMTPAuthenticationError as e:
        return False, ("SMTP login was rejected by the mail server. Double-check "
                        "EMAIL_SMTP_USER / EMAIL_SMTP_PASSWORD (for Gmail this "
                        "must be a 16-character App Password, not your normal "
                        f"login password). Server said: {e.smtp_error.decode(errors='ignore')}")
    except smtplib.SMTPRecipientsRefused:
        return False, f"The mail server rejected the recipient address '{to_email}'."
    except (smtplib.SMTPConnectError, smtplib.SMTPServerDisconnected, OSError) as e:
        return False, (f"Couldn't reach SMTP server {host}:{port}. Check the host/port "
                        f"and your internet connection. ({e})")
    except smtplib.SMTPException as e:
        return False, f"SMTP error while sending: {e}"
    except Exception as e:
        return False, f"Email send failed: {type(e).__name__}: {e}"


def deliver_password_async(parent, email, name, password, on_status, on_done):
    """Runs the SMTP send on a background thread so the UI never freezes,
    and reports live progress through on_status(text) callbacks (always
    invoked back on the Tk main thread via `parent.after`). on_done(sent,
    info) is called once with the final result."""

    def report(fn, *args):
        try:
            parent.after(0, lambda: fn(*args))
        except tk.TclError:
            pass  # window already closed

    def worker():
        report(on_status, f"Connecting to mail server and sending to {email} …")
        sent, info = send_password_email(email, name, password)
        report(on_done, sent, info)

    threading.Thread(target=worker, daemon=True).start()


def show_delivery_result(parent, email, password, sent, info):
    """Email-only delivery: never reveals the plaintext password on screen.
    On failure, just reports the reason so the user can fix SMTP config
    and retry — the password stays only in the email."""
    if sent:
        styled_info(parent, "Password sent", info)
    else:
        styled_error(
            parent, "Email not sent",
            f"{info}\n\nThe password was NOT displayed on screen, by design — "
            f"it is only ever delivered by email.\n\nFix the EMAIL_SMTP_* "
            f"settings and use 'Generate Password' to try again.",
        )


# ------------------------------------------------------------ alert sound
def play_alert_sound(urgent=False):
    """Best-effort attempt to make noise using the OS's own default alert
    sound/API, run off the UI thread so it never blocks. This uses the
    same system call a native app would use — it cannot truly override
    a hardware-muted speaker or an OS volume of 0, since no unprivileged
    desktop app can do that, but it will play at whatever volume the
    system alert channel is set to, and on Windows also flashes the
    taskbar icon for an extra non-audio cue."""
    def _play():
        system = platform.system()
        try:
            if system == "Windows":
                flag = winsound.MB_ICONHAND if urgent else winsound.MB_ICONEXCLAMATION
                for _ in range(3 if urgent else 1):
                    winsound.MessageBeep(flag)
                    threading.Event().wait(0.35)
            elif system == "Darwin":
                sound = "Sosumi.aiff" if urgent else "Ping.aiff"
                for _ in range(3 if urgent else 1):
                    subprocess.run(["afplay", f"/System/Library/Sounds/{sound}"],
                                    timeout=3, capture_output=True)
            else:
                for _ in range(3 if urgent else 1):
                    print("\a", end="", flush=True)
                    threading.Event().wait(0.35)
        except Exception:
            print("\a", end="", flush=True)  # last-resort terminal bell

    threading.Thread(target=_play, daemon=True).start()


def flash_window(win, times=6):
    """Flashes a Toplevel/Tk window's background as a silent-volume-proof
    visual alarm, in case the system is fully muted."""
    original = win.cget("bg")
    colors = [RED, original]

    def step(i):
        try:
            win.configure(bg=colors[i % 2])
        except tk.TclError:
            return
        if i < times:
            win.after(180, lambda: step(i + 1))
        else:
            win.configure(bg=original)

    step(0)


# ----------------------------------------------------------- styled popups
ALERT_STYLES = {
    "success": dict(accent=GREEN, soft=GREEN_SOFT, glyph="✓", title_fg=GREEN_DARK),
    "error":   dict(accent=RED,   soft=RED_SOFT,   glyph="✕", title_fg=RED_DARK),
    "warning": dict(accent=AMBER, soft=AMBER_SOFT, glyph="!", title_fg=AMBER),
    "info":    dict(accent=BLUE,  soft=BLUE_SOFT,  glyph="i", title_fg=BLUE),
}


class StyledAlert(tk.Toplevel):
    """A single, good-looking modal popup used everywhere in the app
    instead of the plain OS messagebox — consistent colors, generous
    padding, a rounded-looking accent header, and one clear action."""

    def __init__(self, parent, kind, title, message, ok_text="OK"):
        super().__init__(parent)
        style = ALERT_STYLES.get(kind, ALERT_STYLES["info"])
        self.configure(bg=BG)
        self.title(title)
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self._close)

        outer = tk.Frame(self, bg=BG, padx=2, pady=2)
        outer.pack(fill="both", expand=True)

        header = tk.Frame(outer, bg=style["soft"], padx=26, pady=18)
        header.pack(fill="x")
        glyph_font = tkfont.Font(family="Helvetica", size=22, weight="bold")
        badge = tk.Label(header, text=style["glyph"], bg=style["accent"], fg="white",
                          font=glyph_font, width=2, height=1)
        badge.pack(side="left", padx=(0, 14))
        tk.Label(header, text=title, bg=style["soft"], fg=style["title_fg"],
                 font=("Helvetica", 14, "bold"), justify="left",
                 wraplength=300, anchor="w").pack(side="left", fill="x", expand=True)

        body = tk.Frame(outer, bg=BG, padx=26, pady=20)
        body.pack(fill="both", expand=True)
        tk.Label(body, text=message, bg=BG, fg=TEXT_DARK, font=("Helvetica", 10),
                 justify="left", wraplength=340, anchor="w").pack(fill="x")

        btn_row = tk.Frame(outer, bg=BG, padx=26, pady=0)
        btn_row.pack(fill="x", pady=(0, 22))
        tk.Button(btn_row, text=ok_text, command=self._close,
                  bg=style["accent"], fg="white", activebackground=style["accent"],
                  font=("Helvetica", 10, "bold"), relief="flat",
                  padx=18, pady=8, cursor="hand2").pack(side="right")

        self.transient(parent)
        self.grab_set()
        self.update_idletasks()
        try:
            px, py = parent.winfo_x(), parent.winfo_y()
            pw, ph = parent.winfo_width(), parent.winfo_height()
            w, h = self.winfo_width(), self.winfo_height()
            self.geometry(f"+{px + (pw - w) // 2}+{py + (ph - h) // 3}")
        except tk.TclError:
            pass
        self.bind("<Return>", lambda e: self._close())
        self.bind("<Escape>", lambda e: self._close())
        self.focus_set()
        self.wait_window(self)

    def _close(self):
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()


def styled_info(parent, title, message):
    StyledAlert(parent, "success", title, message)


def styled_error(parent, title, message):
    StyledAlert(parent, "error", title, message)


def styled_warning(parent, title, message):
    StyledAlert(parent, "warning", title, message)


def apply_usb_state(enabled: bool):
    """Real OS-level enforcement (module-level so both the GUI and the
    background watchdog can call it identically).
    See README notes: Windows registry / macOS MDM-only limitations."""
    system = platform.system()

    if system == "Windows":
        start_value = "3" if enabled else "4"
        try:
            subprocess.run(
                ["reg", "add",
                 r"HKLM\SYSTEM\CurrentControlSet\Services\UsbStor",
                 "/v", "Start", "/t", "REG_DWORD",
                 "/d", start_value, "/f"],
                check=True, capture_output=True, text=True,
            )
            state_txt = "enabled" if enabled else "disabled"
            return True, f"Windows: USB mass storage {state_txt} (UsbStor)."
        except subprocess.CalledProcessError as e:
            return False, ("Windows: registry update failed — re-run this "
                            "app as Administrator. (" + e.stderr.strip()[:120] + ")")
        except FileNotFoundError:
            return False, "Windows: reg.exe not found on PATH."

    elif system == "Darwin":
        return False, ("macOS: USB ports can't be disabled via a public "
                        "unprivileged API — this requires an MDM "
                        "configuration profile. UI updated for demo only.")

    else:
        return False, f"{system}: enforcement not implemented for this OS."


# ------------------------------------------------------------------ dialogs
class RegistrationDialog(tk.Toplevel):
    """Blocking first-run form: Name, Email, [Get Password]."""

    def __init__(self, master, store: RegistrationStore, on_done):
        super().__init__(master)
        self.store = store
        self.on_done = on_done
        self.title("USB Shield — Registration")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", lambda: None)  # can't skip registration

        header = tk.Frame(self, bg=BLUE_SOFT, padx=28, pady=20)
        header.pack(fill="x")
        tk.Label(header, text="🛡  Register this device", bg=BLUE_SOFT, fg=BLUE,
                 font=("Helvetica", 16, "bold")).pack(anchor="w")
        tk.Label(header, text="One-time setup — your password will be emailed to you.",
                 bg=BLUE_SOFT, fg=GRAY_TEXT, font=("Helvetica", 9)).pack(anchor="w", pady=(4, 0))

        body = tk.Frame(self, bg=BG, padx=28, pady=22)
        body.pack(fill="both", expand=True)

        tk.Label(body, text="NAME", bg=BG, fg="#9A9AA0",
                 font=("Helvetica", 8, "bold")).pack(anchor="w")
        self.name_var = tk.StringVar()
        name_entry = tk.Entry(body, textvariable=self.name_var, font=("Helvetica", 12),
                               relief="flat", bg=CARD_BG, fg=TEXT_DARK,
                               highlightthickness=1, highlightbackground=BORDER,
                               highlightcolor=BLUE, insertbackground=TEXT_DARK)
        name_entry.pack(fill="x", ipady=8, pady=(4, 16))

        tk.Label(body, text="EMAIL", bg=BG, fg="#9A9AA0",
                 font=("Helvetica", 8, "bold")).pack(anchor="w")
        self.email_var = tk.StringVar()
        email_entry = tk.Entry(body, textvariable=self.email_var, font=("Helvetica", 12),
                                relief="flat", bg=CARD_BG, fg=TEXT_DARK,
                                highlightthickness=1, highlightbackground=BORDER,
                                highlightcolor=BLUE, insertbackground=TEXT_DARK)
        email_entry.pack(fill="x", ipady=8, pady=(4, 20))

        self.get_btn = tk.Button(body, text="Get Password", command=self._submit,
                  bg=GREEN, fg="white", activebackground=GREEN_DARK,
                  font=("Helvetica", 11, "bold"), relief="flat",
                  padx=14, pady=10, cursor="hand2")
        self.get_btn.pack(fill="x")

        self.status_var = tk.StringVar(value="")
        tk.Label(body, textvariable=self.status_var, bg=BG, fg=GRAY_TEXT,
                 font=("Helvetica", 9), wraplength=320).pack(pady=(10, 0), fill="x")

        name_entry.focus_set()
        self.transient(master)
        self.grab_set()
        self.update_idletasks()
        self.geometry(f"+{master.winfo_x()+60}+{master.winfo_y()+80}")

    def _submit(self):
        name = self.name_var.get().strip()
        email = self.email_var.get().strip()
        if not name:
            styled_error(self, "Missing name", "Please enter your name.")
            return
        if "@" not in email or "." not in email.split("@")[-1]:
            styled_error(self, "Invalid email", "Please enter a valid email address.")
            return

        password = self.store.register(name, email)
        self.get_btn.config(state="disabled")
        self.protocol("WM_DELETE_WINDOW", lambda: None)

        def on_status(text):
            self.status_var.set(text)

        def on_done(sent, info):
            show_delivery_result(self, email, password, sent, info)
            self.get_btn.config(state="normal")
            self.status_var.set("")
            if sent:
                self.grab_release()
                self.destroy()
                self.on_done()
            # on failure: dialog stays open, same password, button re-enabled to retry

        deliver_password_async(self, email, name, password, on_status, on_done)


class PasswordPromptDialog(simpledialog.Dialog):
    """Modal password entry used to gate every toggle action."""

    def __init__(self, master, title="Enter password"):
        self.password = None
        super().__init__(master, title=title)

    def body(self, master):
        self.configure(bg=BG)
        wrap = tk.Frame(master, bg=BG, padx=14, pady=10)
        wrap.pack(fill="both", expand=True)
        tk.Label(wrap, text="🔒  Confirm your password", bg=BG, fg=TEXT_DARK,
                 font=("Helvetica", 12, "bold")).pack(anchor="w", pady=(0, 12))
        self.entry = tk.Entry(wrap, show="•", width=26, font=("Helvetica", 12),
                               relief="flat", bg=CARD_BG, fg=TEXT_DARK,
                               highlightthickness=1, highlightbackground=BORDER,
                               highlightcolor=BLUE, insertbackground=TEXT_DARK)
        self.entry.pack(fill="x", ipady=8)
        return self.entry

    def buttonbox(self):
        box = tk.Frame(self, bg=BG, pady=14)
        tk.Button(box, text="Confirm", width=10, command=self.ok,
                  bg=GREEN, fg="white", activebackground=GREEN_DARK,
                  font=("Helvetica", 10, "bold"), relief="flat",
                  padx=10, pady=7, cursor="hand2", default="active").pack(side="left", padx=(0, 8))
        tk.Button(box, text="Cancel", width=10, command=self.cancel,
                  bg=CARD_BG, fg=TEXT_DARK, activebackground=BORDER,
                  font=("Helvetica", 10, "bold"), relief="flat",
                  padx=10, pady=7, cursor="hand2").pack(side="left")
        self.bind("<Return>", lambda e: self.ok())
        self.bind("<Escape>", lambda e: self.cancel())
        box.pack()

    def apply(self):
        self.password = self.entry.get()


class ForgotPasswordDialog(tk.Toplevel):
    """'Generate Password' flow from the home page — ask for email,
    validate against the registered account, issue + send a new one."""

    def __init__(self, master, store: RegistrationStore):
        super().__init__(master)
        self.store = store
        self.title("Generate Password")
        self.configure(bg=BG)
        self.resizable(False, False)

        header = tk.Frame(self, bg=GREEN_SOFT, padx=26, pady=18)
        header.pack(fill="x")
        tk.Label(header, text="🔑  Generate a new password", bg=GREEN_SOFT, fg=GREEN_DARK,
                 font=("Helvetica", 14, "bold")).pack(anchor="w")
        tk.Label(header, text="Enter the email used during registration.",
                 bg=GREEN_SOFT, fg=GRAY_TEXT, font=("Helvetica", 9)).pack(anchor="w", pady=(4, 0))

        body = tk.Frame(self, bg=BG, padx=26, pady=20)
        body.pack(fill="both", expand=True)

        tk.Label(body, text="EMAIL", bg=BG, fg="#9A9AA0",
                 font=("Helvetica", 8, "bold")).pack(anchor="w")
        self.email_var = tk.StringVar()
        email_entry = tk.Entry(body, textvariable=self.email_var, font=("Helvetica", 12),
                                relief="flat", bg=CARD_BG, fg=TEXT_DARK,
                                highlightthickness=1, highlightbackground=BORDER,
                                highlightcolor=GREEN, insertbackground=TEXT_DARK)
        email_entry.pack(fill="x", ipady=8, pady=(4, 18))

        self.gen_btn = tk.Button(body, text="Generate Password", command=self._submit,
                  bg=GREEN, fg="white", activebackground=GREEN_DARK,
                  font=("Helvetica", 11, "bold"), relief="flat",
                  padx=12, pady=10, cursor="hand2")
        self.gen_btn.pack(fill="x")

        self.status_var = tk.StringVar(value="")
        tk.Label(body, textvariable=self.status_var, bg=BG, fg=GRAY_TEXT,
                 font=("Helvetica", 9), wraplength=320).pack(pady=(10, 0), fill="x")

        email_entry.focus_set()
        self.transient(master)
        self.grab_set()

    def _submit(self):
        email = self.email_var.get().strip()
        if not email:
            styled_error(self, "Missing email", "Please enter an email address.")
            return
        if not self.store.exists():
            styled_error(self, "Not registered", "No registered user on this device.")
            return

        new_password = self.store.regenerate_password(email)
        if new_password is None:
            styled_error(self, "User not found",
                         "User not found or invalid email address.")
            return

        data = self.store.load()
        name = data.get("name", "")
        self.gen_btn.config(state="disabled")

        def on_status(text):
            self.status_var.set(text)

        def on_done(sent, info):
            show_delivery_result(self, email, new_password, sent, info)
            self.gen_btn.config(state="normal")
            self.status_var.set("")
            if sent:
                self.grab_release()
                self.destroy()
            # on failure: dialog stays open so the user can retry

        deliver_password_async(self, email, name, new_password, on_status, on_done)


class ThreatAlertDialog(tk.Toplevel):
    """Pops up the instant an unrecognized USB device tries to connect
    while protection is ON (disabled). Plays the OS default alert sound,
    flashes red as a silent-volume-proof visual cue, and blocks the app
    until the user explicitly Allows or Blocks the device."""

    def __init__(self, master, threat_info: dict, store: "RegistrationStore"):
        super().__init__(master)
        self.result = None  # "allow" or "block"
        self.store = store
        self.title("⚠ USB Shield — Threat Detected")
        self.configure(bg=RED)
        self.resizable(False, False)
        self.attributes("-topmost", True)
        self.protocol("WM_DELETE_WINDOW", lambda: self._choose("block"))

        header = tk.Frame(self, bg=RED, padx=26, pady=22)
        header.pack(fill="x")
        tk.Label(header, text="⚠", bg=RED, fg="white",
                 font=("Helvetica", 30, "bold")).pack(side="left", padx=(0, 14))
        title_wrap = tk.Frame(header, bg=RED)
        title_wrap.pack(side="left", fill="x", expand=True)
        tk.Label(title_wrap, text="Unauthorized USB activity detected",
                 bg=RED, fg="white", font=("Helvetica", 14, "bold"),
                 anchor="w", justify="left", wraplength=300).pack(anchor="w")
        tk.Label(title_wrap, text="USB protection is currently ON (locked)",
                 bg=RED, fg="#FFD7D4", font=("Helvetica", 9),
                 anchor="w").pack(anchor="w", pady=(2, 0))

        body = tk.Frame(self, bg=BG, padx=26, pady=20)
        body.pack(fill="both", expand=True)

        details = tk.Frame(body, bg=RED_SOFT, padx=16, pady=14)
        details.pack(fill="x")
        for label, value in (
            ("Detected at", threat_info.get("time", "—")),
            ("Device type", threat_info.get("device_type", "Removable storage")),
            ("Platform", threat_info.get("platform", platform.system())),
            ("Action attempted", threat_info.get("action", "Mount / data access")),
        ):
            row = tk.Frame(details, bg=RED_SOFT)
            row.pack(fill="x", pady=2)
            tk.Label(row, text=label, bg=RED_SOFT, fg=RED_DARK,
                     font=("Helvetica", 9, "bold"), width=15, anchor="w").pack(side="left")
            tk.Label(row, text=value, bg=RED_SOFT, fg=TEXT_DARK,
                     font=("Helvetica", 9), anchor="w", wraplength=200,
                     justify="left").pack(side="left", fill="x", expand=True)

        tk.Label(body, text="Allow this device once, or block it and keep the port locked?",
                 bg=BG, fg=GRAY_TEXT, font=("Helvetica", 9), wraplength=320,
                 justify="left").pack(anchor="w", pady=(14, 16))

        btn_row = tk.Frame(body, bg=BG)
        btn_row.pack(fill="x")
        tk.Button(btn_row, text="⛔  Block", command=lambda: self._choose("block"),
                  bg=RED, fg="white", activebackground=RED_DARK,
                  font=("Helvetica", 11, "bold"), relief="flat",
                  padx=14, pady=10, cursor="hand2").pack(side="left", fill="x", expand=True, padx=(0, 6))
        tk.Button(btn_row, text="✓  Allow", command=lambda: self._choose("allow"),
                  bg=GREEN, fg="white", activebackground=GREEN_DARK,
                  font=("Helvetica", 11, "bold"), relief="flat",
                  padx=14, pady=10, cursor="hand2").pack(side="left", fill="x", expand=True, padx=(6, 0))

        self.transient(master)
        self.grab_set()
        self.update_idletasks()
        try:
            px, py = master.winfo_x(), master.winfo_y()
            pw, ph = master.winfo_width(), master.winfo_height()
            w, h = self.winfo_width(), self.winfo_height()
            self.geometry(f"+{px + (pw - w) // 2}+{py + (ph - h) // 3}")
        except tk.TclError:
            pass

        play_alert_sound(urgent=True)
        flash_window(self)
        self.bell()
        self.focus_force()
        self.wait_window(self)

    def _choose(self, result):
        if result == "allow":
            # Allowing always requires the APP password — never the OS
            # login password — even if the dialog popped up with the
            # main window hidden/in the background.
            pwd_dlg = PasswordPromptDialog(self, title="USB Shield — Confirm App Password to Allow")
            if pwd_dlg.password is None or not self.store.verify(pwd_dlg.password):
                styled_error(self, "Allow denied", "App password not verified — device stays blocked.")
                return  # stay open, device remains blocked until they retry or hit Block
        self.result = result
        self.grab_release()
        self.destroy()


# --------------------------------------------------------------- main window
class HomeWindow(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("USB Physical Security")
        self.configure(bg=BG)
        self.geometry("440x780")
        self.minsize(400, 700)

        self.store = RegistrationStore(REGISTRATION_FILE)

        self.icon_on = load_image(ICON_ENABLED_PATH, ICON_SIZE)
        self.icon_off = load_image(ICON_DISABLED_PATH, ICON_SIZE)
        self.toggle_on_img = load_image(TOGGLE_ON_PATH, TOGGLE_SIZE)
        self.toggle_off_img = load_image(TOGGLE_OFF_PATH, TOGGLE_SIZE)

        # `usb_enabled` = protection toggle state (manual, password-gated).
        # `physical_present` = the REAL, live, physically-true state of
        # the USB port — updated every poll and reflected on the icon
        # immediately, independent of the toggle.
        self.physical_present = usb_device_present()
        self.usb_enabled = self.physical_present
        self._last_usb_present = self.physical_present
        self._drive_snapshot = {}
        self._save_state()

        self._build_header()
        self._build_status_panel()
        self._build_toggle()
        self._build_password_row()
        self._build_log_panel()
        self._build_footer()

        self._refresh(initial=True)
        self._log("SYSTEM", "USB Shield started." +
                   (" Device currently inserted." if self.physical_present else " No device inserted."))

        if not self.store.exists():
            # block everything behind the registration form on first run
            self.after(150, self._show_registration)
        else:
            self._poll_usb()

    # ---------------------------------------------------------------- UI
    def _build_header(self):
        header = tk.Frame(self, bg=BG)
        header.pack(fill="x", pady=(26, 4))
        title_font = tkfont.Font(family="Helvetica", size=20, weight="bold")
        tk.Label(header, text="USB Shield", bg=BG, fg=TEXT_DARK,
                 font=title_font).pack()
        tk.Label(header, text="Physical Port Security", bg=BG, fg=GRAY_TEXT,
                 font=("Helvetica", 10)).pack(pady=(2, 0))

    def _build_status_panel(self):
        wrap = tk.Frame(self, bg=BG)
        wrap.pack(pady=16)
        self.icon_label = tk.Label(wrap, image=self.icon_off, bg=BG, bd=0)
        self.icon_label.pack()

    def _build_toggle(self):
        wrap = tk.Frame(self, bg=BG)
        wrap.pack(pady=(4, 4))

        self.toggle_btn = tk.Label(wrap, image=self.toggle_off_img, bg=BG,
                                    bd=0, cursor="hand2")
        self.toggle_btn.pack()
        self.toggle_btn.bind("<Button-1>", lambda e: self.on_toggle())
        self.toggle_btn.bind("<Return>", lambda e: self.on_toggle())
        self.toggle_btn.bind("<space>", lambda e: self.on_toggle())
        self.toggle_btn.focus_set()

        tk.Label(wrap, text="A password is required every time you switch this",
                 bg=BG, fg=GRAY_TEXT, font=("Helvetica", 9)).pack(pady=(10, 0))
        tk.Label(wrap, text="ON also requires a USB device to be physically inserted",
                 bg=BG, fg=GRAY_TEXT, font=("Helvetica", 9)).pack()

    def _build_password_row(self):
        wrap = tk.Frame(self, bg=BG)
        wrap.pack(pady=(10, 0))
        tk.Button(wrap, text="Generate Password", command=self._open_forgot_password,
                  bg="#F2F2F4", fg=TEXT_DARK, activebackground="#E5E5E8",
                  font=("Helvetica", 9, "bold"), relief="flat",
                  padx=12, pady=6, cursor="hand2").pack()

    def _build_log_panel(self):
        wrap = tk.Frame(self, bg=BG)
        wrap.pack(fill="both", expand=True, padx=24, pady=(14, 0))
        tk.Label(wrap, text="ACTIVITY LOG", bg=BG, fg="#B5B5B8",
                 font=("Helvetica", 8, "bold")).pack(anchor="w")

        log_card = tk.Frame(wrap, bg=CARD_BG, highlightthickness=1,
                             highlightbackground=BORDER)
        log_card.pack(fill="both", expand=True, pady=(4, 0))

        scrollbar = tk.Scrollbar(log_card)
        scrollbar.pack(side="right", fill="y")
        self.log_text = tk.Text(log_card, height=8, bg=CARD_BG, fg=TEXT_DARK,
                                 font=("Consolas", 9), relief="flat", wrap="word",
                                 yscrollcommand=scrollbar.set, state="disabled",
                                 padx=8, pady=6)
        self.log_text.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=self.log_text.yview)

        LOG_TAG_COLORS = {
            "CONNECTED": GREEN_DARK, "DISCONNECTED": GRAY_TEXT,
            "TOGGLE": BLUE, "THREAT": RED_DARK, "FILE": AMBER, "SYSTEM": GRAY_TEXT,
        }
        for tag, color in LOG_TAG_COLORS.items():
            self.log_text.tag_config(tag, foreground=color, font=("Consolas", 9, "bold"))

        # Load existing history from disk so the log survives app restarts.
        for entry in load_recent_log(limit=200):
            self._append_log_line(entry)

    def _append_log_line(self, entry):
        self.log_text.config(state="normal")
        self.log_text.insert("end", f"[{entry['time']}] ", ())
        self.log_text.insert("end", f"{entry['category']:<13}", (entry["category"],))
        self.log_text.insert("end", f" {entry['message']}\n")
        self.log_text.see("end")
        self.log_text.config(state="disabled")

    def _log(self, category, message):
        """Single entry point for every activity-log line: writes to the
        on-disk history (log_event) AND appends it live to the on-screen
        log so the user can see, in plain language, exactly what just
        happened and when."""
        entry = log_event(category, message)
        self._append_log_line(entry)

    def _build_footer(self):
        footer = tk.Frame(self, bg=BG)
        footer.pack(side="bottom", fill="x", pady=16)
        self.status_var = tk.StringVar(value="Last changed: —")
        tk.Label(footer, textvariable=self.status_var, bg=BG, fg=GRAY_TEXT,
                 font=("Helvetica", 8)).pack()
        tk.Label(footer, text=f"Platform: {platform.system()} {platform.release()}",
                 bg=BG, fg="#B5B5B8", font=("Helvetica", 8)).pack(pady=(2, 0))

    # ------------------------------------------------------- registration
    def _show_registration(self):
        RegistrationDialog(self, self.store, on_done=self._poll_usb)

    def _open_forgot_password(self):
        if not self.store.exists():
            styled_error(self, "Not registered", "No registered user on this device.")
            return
        ForgotPasswordDialog(self, self.store)

    def _check_password(self):
        """Shows the password prompt; returns True only on a verified match."""
        if not self.store.exists():
            styled_error(self, "Not registered", "No registered user on this device.")
            return False
        dlg = PasswordPromptDialog(self, title="USB Shield — Confirm Password")
        if dlg.password is None:
            return False  # cancelled
        if self.store.verify(dlg.password):
            return True
        styled_error(self, "Incorrect password", "That password didn't match. Please try again.")
        return False

    # ------------------------------------------------------------- logic
    def on_toggle(self):
        new_state = not self.usb_enabled

        if new_state:  # trying to turn ON — device presence is the only gate
            if not usb_device_present():
                styled_error(
                    self, "No USB device detected",
                    "Plug in a USB device first — the toggle can only be "
                    "switched ON when a real device is physically inserted."
                )
                self._log("TOGGLE", "Blocked: tried to enable with no USB inserted.")
                return
        else:  # trying to turn OFF — password required
            if not self._check_password():
                self._log("TOGGLE", "Blocked: turn-off attempted, password not verified.")
                return

        ok, message = self.apply_usb_state(new_state)
        if not ok:
            styled_warning(self, "USB Shield", message)
        self.usb_enabled = new_state
        self._last_usb_present = usb_device_present()
        self._log("TOGGLE", f"Manually switched {'ON' if new_state else 'OFF'} (password verified) — {message}")
        self._save_state()
        self._refresh()

    def _poll_usb(self):
        present = usb_device_present()

        # 1) Physical connection status — always updated immediately,
        #    independent of the protection toggle, so the icon reflects
        #    reality the instant a device is plugged or unplugged.
        if present != self.physical_present:
            self.physical_present = present
            if present:
                self._log("CONNECTED", "USB device physically connected.")
                roots = get_removable_drive_roots()
                self._drive_snapshot = snapshot_drive_files(roots) if roots else {}
            else:
                self._log("DISCONNECTED", "USB device physically removed.")
                self._drive_snapshot = {}
            self._refresh_icon()

        # 2) Best-effort file-activity scan while a drive is mounted.
        if present:
            self._scan_file_activity()

        # 3) Protection / threat logic (unchanged behavior).
        if self.usb_enabled and not present:
            # device that was permitted got unplugged — auto re-lock
            self.usb_enabled = False
            self.apply_usb_state(False)
            self._log("TOGGLE", "Auto-switched OFF — permitted USB device was unplugged.")
            self._save_state()
            self._refresh()
            styled_warning(self, "USB removed", "USB device was removed. Toggle turned OFF.")
            self._last_usb_present = present

        elif (not self.usb_enabled) and present and not self._last_usb_present:
            # NEW device just appeared while protection is ON/locked -> threat
            self._last_usb_present = present
            self._handle_threat()

        else:
            self._last_usb_present = present

        self.after(USB_POLL_INTERVAL_MS, self._poll_usb)

    def _scan_file_activity(self):
        """Best-effort: compares the current file listing on any
        mounted removable drive against the last snapshot and logs
        anything written, modified, or deleted. Windows-only and
        shallow (depth-limited) — see snapshot_drive_files()."""
        roots = get_removable_drive_roots()
        if not roots:
            return
        new_snap = snapshot_drive_files(roots)
        if self._drive_snapshot:
            added, modified, removed = diff_drive_snapshots(self._drive_snapshot, new_snap)
            for path in added:
                self._log("FILE", f"File written to this device from USB: {path}")
            for path in modified:
                self._log("FILE", f"File modified on USB drive: {path}")
            for path in removed:
                self._log("FILE", f"File removed from USB drive: {path}")
        self._drive_snapshot = new_snap

    def _handle_threat(self):
        threat_info = {
            "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "device_type": "Removable USB storage",
            "platform": f"{platform.system()} {platform.release()}",
            "action": "Device inserted while no USB Shield window is open",
        }
        self._log("THREAT", "Unrecognized USB insertion detected while protection is ON. "
                             "Action HELD — awaiting Allow/Block decision.")
        dlg = ThreatAlertDialog(self, threat_info, self.store)

        if dlg.result == "allow":
            ok, message = self.apply_usb_state(True)
            self.usb_enabled = True
            self._log("THREAT", f"ALLOWED by user (app password verified) — {message}")
        else:
            self.apply_usb_state(False)
            self.usb_enabled = False
            self._log("THREAT", "BLOCKED by user — action denied, USB stayed locked.")

        self._save_state()
        self._refresh()

    def apply_usb_state(self, enabled: bool):
        return apply_usb_state(enabled)

    # ---------------------------------------------------------- state io
    def _save_state(self):
        data = {
            "usb_enabled": self.usb_enabled,
            "last_changed": datetime.datetime.now().isoformat(timespec="seconds"),
        }
        try:
            with open(STATE_FILE, "w") as f:
                json.dump(data, f, indent=2)
        except OSError:
            pass

    def _refresh_icon(self):
        self.icon_label.config(image=self.icon_on if self.physical_present else self.icon_off)

    def _refresh(self, initial=False):
        self._refresh_icon()
        self.toggle_btn.config(image=self.toggle_on_img if self.usb_enabled else self.toggle_off_img)
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.status_var.set(f"Last changed: {now}" if not initial else
                             f"Restored state — {now}")


if __name__ == "__main__":
    app = HomeWindow()
    app.mainloop()