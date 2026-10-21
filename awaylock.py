#!/usr/bin/env python3
"""
awaylock - walk-away lock for Linux laptops with an IR camera.

made and tested on asus vivobook

Watches the camera every few seconds. If nobody is in front of the laptop
for a while, it locks the screen. Sits in the tray so you can pause it
(the tray code lives in awaylock_tray.py).

Examples:
    awaylock.py                      run with saved/default settings
    awaylock.py --interval 20        scan every 20 seconds
    awaylock.py --interval 20 --save remember that for next time
    awaylock.py --show-config        print the settings in use and exit

Copyright (C) 2026 awaylock contributors
Licensed under the GNU General Public License v3.0 or later.
This program comes with ABSOLUTELY NO WARRANTY. See the LICENSE file.
"""

import argparse
import fcntl
import hashlib
import json
import logging
import os
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

import cv2
import numpy as np

log = logging.getLogger("awaylock")

CONFIG_HOME = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
DATA_HOME = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "awaylock"
CONFIG_PATH = CONFIG_HOME / "awaylock" / "config.json"
AUTOSTART_PATH = CONFIG_HOME / "autostart" / "awaylock.desktop"
LOCK_PATH = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "awaylock.lock"
MODELS_DIR = DATA_HOME / "models"
OWNER_PATH = DATA_HOME / "owner.npy"  # your face "fingerprints", not photos

# Average brightness (0-255) under which we call a frame black.
BLACK_LEVEL = 8

# With scans this far apart (seconds) we close the camera between them, so the
# camera light and the red IR flashing only happen while we're actually looking.
# Closer together than that it's not worth the warm-up, so we keep it open.
KEEP_OPEN_BELOW = 5

# Frames thrown away after opening so the exposure can settle.
WARMUP_FRAMES = 2

# Face models from the OpenCV model zoo. They're downloaded once and checked
# against these hashes, so a tampered or corrupted file is rejected.
MODELS = {
    "yunet": (
        "face_detection_yunet_2023mar.onnx",
        "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
        "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
    ),
    "sface": (
        "face_recognition_sface_2021dec.onnx",
        "https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx",
        "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79",
    ),
}

DEFAULTS = {
    "camera": 2,              # /dev/video2 - usually the IR one, RGB is normally 0
    "interval": 10,           # seconds between scans
    "battery_interval": 0,    # seconds between scans on battery, 0 = same as interval
    "grace": 0,               # seconds of warning before locking, 0 = lock straight away
    "misses": 3,              # empty scans in a row before we lock
    "min_face": 30,           # smallest face (pixels) we care about
    "black_frame": "absent",  # what a black frame means: "absent" or "skip"
    "detector": "haar",       # "haar" (simple) or "yunet" (more accurate, needs a model download)
    "presence": "owner",      # "owner" only your enrolled face keeps you unlocked, "any" face does too
    "match_threshold": 0.45,  # how similar a face must be to count as you (OpenCV suggests 0.363, we want more margin)
    "detect_threshold": 0.8,  # how sure yunet must be that something is a face
}


# ---------- settings ----------

def load_config():
    # Saved settings sit on top of the defaults; a broken file just gets ignored.
    cfg = dict(DEFAULTS)
    try:
        saved = json.loads(CONFIG_PATH.read_text())
        cfg.update({k: v for k, v in saved.items() if k in DEFAULTS})
    except (OSError, ValueError, AttributeError):
        pass
    return cfg


def save_config(cfg):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2) + "\n")


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Lock the screen when you walk away from your laptop.")
    p.add_argument("--interval", type=float, help=f"seconds between scans (default {DEFAULTS['interval']})")
    p.add_argument("--battery-interval", type=float, dest="battery_interval",
                   help="seconds between scans while on battery, 0 = same as --interval (default 0)")
    p.add_argument("--grace", type=float,
                   help="warn this many seconds before locking and look once more, 0 = no warning (default 0)")
    p.add_argument("--misses", type=int, help=f"empty scans in a row before locking (default {DEFAULTS['misses']})")
    p.add_argument("--camera", type=int, help=f"camera index, N in /dev/videoN (default {DEFAULTS['camera']})")
    p.add_argument("--min-face", type=int, dest="min_face", help="smallest face size in pixels")
    p.add_argument("--black-frame", choices=["absent", "skip"], dest="black_frame",
                   help="a black frame counts as nobody there (absent) or is ignored (skip)")
    p.add_argument("--detector", choices=["haar", "yunet"],
                   help="face detector: haar (simple) or yunet (more accurate, downloads a small model)")
    p.add_argument("--presence", choices=["any", "owner"],
                   help="any face keeps you unlocked, or only your enrolled face (see --enroll)")
    p.add_argument("--match-threshold", type=float, dest="match_threshold",
                   help=f"how similar a face must be to count as you, 0-1 (default {DEFAULTS['match_threshold']})")
    p.add_argument("--detect-threshold", type=float, dest="detect_threshold",
                   help=f"how sure yunet must be it's a face, 0-1 (default {DEFAULTS['detect_threshold']})")
    p.add_argument("--enroll", action="store_true", help="record your face so --presence owner can recognise you")
    p.add_argument("--add-face", action="store_true", dest="add_face",
                   help="add more samples of your face (glasses, headphones, a hat) to what --enroll stored")
    p.add_argument("--forget-me", action="store_true", help="delete your stored face data")
    p.add_argument("--list-cameras", action="store_true", help="try every camera, show which look like IR, and exit")
    p.add_argument("--install-autostart", action="store_true", help="start awaylock when you log in")
    p.add_argument("--uninstall-autostart", action="store_true", help="stop starting awaylock at login")
    p.add_argument("--no-tray", action="store_true", help="don't show a tray icon")
    p.add_argument("--paused", action="store_true", help="start paused, resume from the tray")
    p.add_argument("--save", action="store_true", help="store the options you passed as new defaults")
    p.add_argument("--show-config", action="store_true", help="print the settings in use and exit")
    p.add_argument("-v", "--verbose", action="store_true", help="print more detail")
    return p.parse_args(argv)


def resolve_config(args):
    """Saved/default settings with command line options on top. Exits on nonsense values."""
    cfg = load_config()
    for key in DEFAULTS:
        value = getattr(args, key)
        if value is not None:
            cfg[key] = value
    if cfg["interval"] <= 0:
        sys.exit("interval must be above 0")
    if cfg["battery_interval"] < 0:
        sys.exit("battery-interval can't be negative")
    if cfg["grace"] < 0:
        sys.exit("grace can't be negative")
    if cfg["misses"] < 1:
        sys.exit("misses must be at least 1")
    if cfg["min_face"] < 1:
        sys.exit("min-face must be at least 1")
    if cfg["black_frame"] not in ("absent", "skip"):
        sys.exit("black-frame must be 'absent' or 'skip'")
    if cfg["detector"] not in ("haar", "yunet"):
        sys.exit("detector must be 'haar' or 'yunet'")
    if cfg["presence"] not in ("any", "owner"):
        sys.exit("presence must be 'any' or 'owner'")
    if not 0 < cfg["match_threshold"] <= 1:
        sys.exit("match-threshold must be above 0 and at most 1")
    if not 0 < cfg["detect_threshold"] <= 1:
        sys.exit("detect-threshold must be above 0 and at most 1")
    return cfg


# ---------- setup helpers ----------

def install_autostart():
    # Uses the python that's running us right now, so conda/venv installs keep working.
    # Run with --save first if you want your settings picked up at login.
    cmd = f'"{sys.executable}" "{Path(__file__).resolve()}"'
    AUTOSTART_PATH.parent.mkdir(parents=True, exist_ok=True)
    AUTOSTART_PATH.write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=awaylock\n"
        "Comment=Lock the screen when you walk away\n"
        f"Exec={cmd}\n"
        "Terminal=false\n"
        "X-GNOME-Autostart-enabled=true\n")
    print(f"Autostart enabled: {AUTOSTART_PATH}")


def uninstall_autostart():
    try:
        AUTOSTART_PATH.unlink()
        print("Autostart removed.")
    except FileNotFoundError:
        print("Autostart wasn't set up.")


def video_index(node):
    # "/dev/video4" -> 4, anything oddly named gets None
    digits = node.name[5:]
    return int(digits) if digits.isdigit() else None


def list_cameras():
    # Opening an IR camera may switch its emitter on, that's expected.
    nodes = [(video_index(n), n) for n in Path("/dev").glob("video*")]
    nodes = sorted((i, n) for i, n in nodes if i is not None)
    if not nodes:
        print("No /dev/video* devices found.")
    for index, node in nodes:
        cam = cv2.VideoCapture(index)
        frame = best_frame(cam) if cam.isOpened() else None
        cam.release()

        if frame is None:
            print(f"{node}: no picture (probably a metadata node, ignore)")
            continue
        h, w = frame.shape[:2]
        if frame.ndim == 2:
            grey = True
        else:
            b, g, r = cv2.split(frame)
            grey = cv2.absdiff(b, r).mean() < 1  # IR cams give equal color channels
        note = "looks like IR" if grey else "color, likely the normal webcam"
        if frame.mean() < BLACK_LEVEL:
            note += ", but the frame is black (wave a hand in front of it and retry)"
        print(f"{node}: {w}x{h}, {note}   -> --camera {index}")


def best_frame(cam, tries=8):
    """A usable frame from the camera, or None if it gives us nothing at all.

    The IR camera on the VivoBook strobes its emitter, so every second frame is
    pitch black even when everything is fine. We read a few frames and take the
    first lit one; only if they're all black do we hand back a black frame.
    """
    for _ in range(2):
        cam.grab()  # drop stale buffered frames, they get old with long intervals
    frame = None
    for _ in range(tries):
        ok, f = cam.read()
        if not ok:
            continue
        frame = f
        if f.mean() >= BLACK_LEVEL:
            break
    return frame


def acquire_single_instance():
    # The lock goes away on its own when the process dies, even after a crash.
    handle = open(LOCK_PATH, "w")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        sys.exit("awaylock is already running.")
    return handle  # keep a reference or the lock is released


def lock_screen():
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
    if "gnome" in desktop:
        cmd = ["dbus-send", "--type=method_call", "--dest=org.gnome.ScreenSaver",
               "/org/gnome/ScreenSaver", "org.gnome.ScreenSaver.Lock"]
    elif "kde" in desktop:
        cmd = ["qdbus", "org.freedesktop.ScreenSaver", "/ScreenSaver", "Lock"]
    else:
        # Works with most other setups as long as a locker is listening (i3lock, swaylock...)
        cmd = ["loginctl", "lock-session"]
    try:
        subprocess.run(cmd, check=False)
    except FileNotFoundError:
        log.error("Couldn't run %s, is it installed?", cmd[0])


def on_battery():
    """True when the laptop is running on its battery. False on AC, or when there's no battery."""
    for status in Path("/sys/class/power_supply").glob("BAT*/status"):
        try:
            if status.read_text().strip() == "Discharging":
                return True
        except OSError:
            pass
    return False


def notify(text, seconds=5):
    """Show a desktop popup and return its id so it can be closed early, or None.

    Purely a courtesy, so any failure is ignored. Urgent popups ignore the timeout
    on GNOME and stay until closed, which is why we keep the id.
    """
    base = ["notify-send", "--app-name=awaylock", "--urgency=critical",
            f"--expire-time={int(seconds * 1000)}"]
    try:
        # --print-id needs libnotify 0.8; older versions reject it, so retry without
        for extra in (["--print-id"], []):
            out = subprocess.run(base + extra + ["awaylock", text], capture_output=True,
                                 text=True, check=False, timeout=5)
            if out.returncode == 0:
                return int(out.stdout.strip()) if out.stdout.strip().isdigit() else None
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def close_notification(nid):
    if nid is None:
        return
    try:
        subprocess.run(["gdbus", "call", "--session", "--dest=org.freedesktop.Notifications",
                        "--object-path=/org/freedesktop/Notifications",
                        "--method=org.freedesktop.Notifications.CloseNotification", str(nid)],
                       capture_output=True, check=False, timeout=5)
    except (OSError, subprocess.SubprocessError):
        pass


def screen_locked():
    """True/False if the screen is locked, None when we can't tell."""
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
    if "gnome" in desktop:
        cmd = ["dbus-send", "--session", "--print-reply", "--dest=org.gnome.ScreenSaver",
               "/org/gnome/ScreenSaver", "org.gnome.ScreenSaver.GetActive"]
    elif "kde" in desktop:
        cmd = ["qdbus", "org.freedesktop.ScreenSaver", "/ScreenSaver", "GetActive"]
    else:
        cmd = ["loginctl", "show-session", os.environ.get("XDG_SESSION_ID", "auto"),
               "-p", "LockedHint", "--value"]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=5).stdout.strip().lower()
    except (OSError, subprocess.SubprocessError):
        return None
    if not out:
        return None
    return out.endswith("true") or out == "yes"


# ---------- face models ----------

def ensure_model(name, models=None, dest_dir=None):
    """Path to a model file, downloading it first if we don't have it yet."""
    filename, url, sha256 = (models or MODELS)[name]
    path = (dest_dir or MODELS_DIR) / filename
    if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == sha256:
        return path

    log.info("Downloading %s model (one time only)...", name)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".part")
    try:
        with urllib.request.urlopen(url, timeout=60) as resp:
            tmp.write_bytes(resp.read())
    except OSError as e:
        sys.exit(f"Couldn't download the {name} model: {e}\nCheck your connection and try again.")
    if hashlib.sha256(tmp.read_bytes()).hexdigest() != sha256:
        tmp.unlink()
        sys.exit(f"The downloaded {name} model doesn't match its expected hash, refusing to use it.")
    tmp.replace(path)
    return path


def cosine_similarity(feature, owner):
    """Best cosine similarity between one face feature and the stored owner features."""
    f = np.asarray(feature, dtype=np.float32).reshape(-1)
    o = np.asarray(owner, dtype=np.float32).reshape(len(owner), -1)
    f = f / (np.linalg.norm(f) + 1e-9)
    o = o / (np.linalg.norm(o, axis=1, keepdims=True) + 1e-9)
    return float((o @ f).max())


def load_owner():
    try:
        owner = np.load(OWNER_PATH)
    except (OSError, ValueError):
        return None
    return owner if owner.ndim == 2 and len(owner) else None


def save_owner(features):
    OWNER_PATH.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    np.save(OWNER_PATH, np.asarray(features, dtype=np.float32))
    os.chmod(OWNER_PATH, 0o600)  # only you should read your face data


def merge_owner(existing, new):
    """Stored samples plus new ones. With nothing stored yet it's just the new ones."""
    if existing is None:
        return np.asarray(new, dtype=np.float32)
    return np.vstack([existing, np.asarray(new, dtype=np.float32)])


def forget_owner():
    try:
        OWNER_PATH.unlink()
        print("Your face data is deleted.")
    except FileNotFoundError:
        print("There was no face data stored.")


# ---------- detectors ----------
# Each one answers a single question: is someone (or you) in this frame?

class HaarDetector:
    """Old-school and light. Fine for 'is there any face', weaker with turned heads and glasses."""

    def __init__(self, cfg):
        self.min_face = cfg["min_face"]
        self.cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml")

    def present(self, frame):
        gray = frame if frame.ndim == 2 else cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = self.cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5,
                                              minSize=(self.min_face, self.min_face))
        return len(faces) > 0


class YuNetDetector:
    """Neural network face finder, copes much better with angles, glasses and bad light."""

    def __init__(self, cfg, model_path=None):
        self.min_face = cfg["min_face"]
        path = model_path or ensure_model("yunet")
        self.net = cv2.FaceDetectorYN.create(str(path), "", (320, 320), cfg["detect_threshold"], 0.3, 5000)

    def faces(self, frame):
        """Rows of x, y, w, h, 5 landmark points and a score, one per face."""
        if frame.ndim == 2:
            frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)  # yunet wants 3 channels
        h, w = frame.shape[:2]
        self.net.setInputSize((w, h))
        _, found = self.net.detect(frame)
        if found is None:
            return []
        return [f for f in found if f[2] >= self.min_face and f[3] >= self.min_face]

    def present(self, frame):
        return len(self.faces(frame)) > 0


class OwnerDetector(YuNetDetector):
    """Only counts faces that match the face you enrolled."""

    def __init__(self, cfg, owner, model_path=None, recognizer_path=None):
        super().__init__(cfg, model_path)
        self.owner = owner
        self.threshold = cfg["match_threshold"]
        path = recognizer_path or ensure_model("sface")
        self.recognizer = cv2.FaceRecognizerSF.create(str(path), "")
        self.last_score = None

    def feature(self, frame, face):
        if frame.ndim == 2:
            frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
        return self.recognizer.feature(self.recognizer.alignCrop(frame, face))

    def present(self, frame):
        faces = self.faces(frame)
        self.last_score = None
        for face in faces:
            score = cosine_similarity(self.feature(frame, face), self.owner)
            self.last_score = max(score, self.last_score or score)
            if score >= self.threshold:
                log.debug("Face matches you (%.2f)", score)
                return True
        if faces:
            log.info("A face is there but it isn't you (best match %.2f, need %.2f)",
                     self.last_score, self.threshold)
        return False


def make_detector(cfg):
    if cfg["presence"] == "owner":
        owner = load_owner()
        if owner is None:
            sys.exit("No face data yet. Run: awaylock.py --enroll")
        return OwnerDetector(cfg, owner)
    if cfg["detector"] == "yunet":
        return YuNetDetector(cfg)
    return HaarDetector(cfg)


def enroll(cam, detector, samples=10, attempts=40, delay=0.7, say=print):
    """Collect face features of the one person in front of the camera. Returns them as an array."""
    say("Look at the camera and slowly turn your head a little left and right.")
    features = []
    for n in range(attempts):
        frame = best_frame(cam)
        if frame is not None and frame.mean() < BLACK_LEVEL:
            say("Frame is black, wave a hand in front of the IR sensor.")
        elif frame is not None:
            faces = detector.faces(frame)
            if len(faces) == 1:
                features.append(detector.feature(frame, faces[0]).reshape(-1))
                say(f"Got {len(features)}/{samples}")
            elif len(faces) > 1:
                say("More than one face visible, only you should be in view.")
            else:
                say("No face found, move a bit closer or face the camera.")
        if len(features) >= samples:
            return np.array(features, dtype=np.float32)
        time.sleep(delay)
    sys.exit("Couldn't get enough good frames. Check --list-cameras and the lighting, then try again.")


# ---------- the watcher ----------

class Watcher(threading.Thread):
    """Scans the camera in the background. Pausing also releases the camera."""

    def __init__(self, cfg, detector=None, start_paused=False):
        super().__init__(daemon=True)
        self.cfg = cfg
        self.detector = detector or HaarDetector(cfg)
        self.active = threading.Event()
        self.quit = threading.Event()
        self.misses = 0
        self.dark = False
        self.was_locked = False
        self.cam_released = False  # set when confirm_leaving closed the camera under run()
        self.last_seen = None      # result of the latest scan: True, False, or None for no picture
        self.last_score = None     # owner mode: how well the face matched, if there was one
        self.on_update = None      # the tray hooks in here to redraw after each scan
        if not start_paused:
            self.active.set()

    def toggle(self):
        if self.active.is_set():
            self.active.clear()
        else:
            self.active.set()

    def stop(self):
        self.quit.set()
        self.active.set()  # wake the loop up if it's waiting while paused

    def face_present(self, cam):
        """True/False for face seen or not, None when this scan tells us nothing."""
        frame = best_frame(cam)
        if frame is None:
            return None  # camera hiccup, don't count it as "gone"
        gray = frame if frame.ndim == 2 else cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        self.dark = gray.mean() < BLACK_LEVEL
        if self.dark and self.cfg["black_frame"] == "skip":
            log.info("Black frame, skipping this scan.")
            return None
        return self.detector.present(frame)

    def status_text(self):
        """One short line about the latest scan, for the tray."""
        if not self.active.is_set():
            return "Paused"
        if self.last_seen is None:
            return "Waiting for a scan" if self.misses == 0 else "No picture from the camera"
        if self.cfg["presence"] == "owner":
            need = self.cfg["match_threshold"]
            if self.last_score is not None:
                return f"Match {self.last_score:.2f} (need {need:.2f})"
            return "No face seen"
        return "Face seen" if self.last_seen else "No face seen"

    def interval(self):
        """Seconds to wait between scans, longer on battery if the user asked for that."""
        slow = self.cfg["battery_interval"]
        if slow > 0 and on_battery():
            return slow
        return self.cfg["interval"]

    def confirm_leaving(self, cam):
        """Warn, wait out the grace period and look once more. True means go ahead and lock."""
        grace = self.cfg["grace"]
        if grace <= 0:
            return True
        log.info("Nobody there, locking in %gs unless you show up.", grace)
        popup = notify(f"Locking in {grace:g}s. Move in front of the camera to cancel.", grace)
        # Let go of the camera while we wait. Left open and unread, its buffer fills with
        # old frames (a hand over the lens looks lit in IR), and the recheck would judge those.
        cam.release()
        self.cam_released = True
        self.quit.wait(grace)
        close_notification(popup)  # whatever happens next, the warning is out of date
        if self.quit.is_set() or not self.active.is_set() or screen_locked():
            return False  # quit, paused or already locked while we were waiting
        fresh = self.open_camera()
        if fresh is None:
            return False
        try:
            seen = self.face_present(fresh)
        finally:
            fresh.release()
        if seen is False:
            return True
        if seen is True:
            log.info("Welcome back, not locking.")
            self.misses = 0
        return False  # camera hiccup: don't lock on a guess, the next scan decides

    def scan_once(self, cam):
        """One scan: update the miss counter and lock when it's full. Returns True if we locked."""
        seen = self.face_present(cam)
        self.last_seen = seen
        self.last_score = getattr(self.detector, "last_score", None)
        if self.on_update:
            try:
                self.on_update()
            except Exception:  # a broken tray must never stop the scanning
                log.debug("Tray update failed", exc_info=True)
        if seen is True:
            log.debug("Someone is there.")
            self.misses = 0
        elif seen is False:
            self.misses += 1
            why = " - black frame, IR sensor may be asleep" if self.dark else ""
            log.info("No face (%d/%d)%s", self.misses, self.cfg["misses"], why)
            if self.misses >= self.cfg["misses"] and self.confirm_leaving(cam):
                log.info("Looks like you left, locking.")
                lock_screen()
                self.misses = 0
                return True
        return False

    def open_camera(self):
        cam = cv2.VideoCapture(self.cfg["camera"], cv2.CAP_V4L2)  # skips a slow fallback to other backends
        if not cam.isOpened():
            cam.release()
            return None
        for _ in range(WARMUP_FRAMES):
            cam.grab()
        return cam

    def run(self):
        cam = None
        while not self.quit.is_set():
            if not self.active.is_set():
                if cam:
                    cam.release()  # paused means camera off, light included
                    cam = None
                self.misses = 0
                self.active.wait()
                continue

            if screen_locked():
                # Nothing to guard while it's locked, so leave the camera alone until you're back.
                if cam:
                    cam.release()
                    cam = None
                if not self.was_locked:
                    log.info("Screen is locked, scanning paused until you unlock.")
                self.was_locked = True
                self.misses = 0
                self.quit.wait(self.interval())
                continue
            if self.was_locked:
                log.info("Unlocked, scanning again.")
                self.was_locked = False

            if cam is None:
                cam = self.open_camera()
                if cam is None:
                    log.error("Can't open camera %s, will retry. Try --list-cameras.", self.cfg["camera"])
                    self.quit.wait(self.interval())
                    continue

            self.scan_once(cam)
            if self.cam_released:
                cam = None
                self.cam_released = False
                continue  # next pass reopens the camera, no need to wait again
            wait = self.interval()
            if wait >= KEEP_OPEN_BELOW:
                cam.release()
                cam = None
            self.quit.wait(wait)

        if cam:
            cam.release()


def enroll_from_camera(cfg, add=False):
    """Open the camera, collect face samples and store them. With add=True they join the stored ones."""
    existing = load_owner() if add else None
    if add and existing is None:
        print("No face data yet, so this starts a fresh one.")
    elif add:
        print(f"Adding to your {len(existing)} stored samples. "
              "Put on the glasses, headphones or hat you want it to learn.")
    cam = cv2.VideoCapture(cfg["camera"])
    if not cam.isOpened():
        sys.exit(f"Can't open camera {cfg['camera']}. Try --list-cameras.")
    try:
        new = enroll(cam, OwnerDetector(cfg, owner=None))  # no owner yet, we're making one
    finally:
        cam.release()
    everything = merge_owner(existing, new)
    save_owner(everything)
    print(f"Face data saved ({len(everything)} samples).")


def first_run_enroll(cfg):
    """Owner mode is the default, so with no face stored yet we learn yours before starting."""
    if not (sys.stdin and sys.stdin.isatty()):
        # Started without a terminal (autostart), nobody is there to look at the camera.
        notify("awaylock needs to learn your face first. Open a terminal and run: awaylock --enroll", 15)
        sys.exit("No face data yet. Run: awaylock.py --enroll (or --presence any --save to skip owner mode).")
    print("Welcome. awaylock only keeps your screen unlocked for your own face, so it has to learn it first.")
    print("(It downloads two small face models once. Use --presence any --save to skip owner mode.)")
    try:
        input("Sit in front of the camera and press Enter... ")
    except EOFError:
        sys.exit("Cancelled.")
    enroll_from_camera(cfg)


def main(argv=None):
    args = parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    cfg = resolve_config(args)

    if args.save:
        save_config(cfg)
        print(f"Saved to {CONFIG_PATH}")
    if args.show_config:
        print(json.dumps(cfg, indent=2))
        return
    if args.list_cameras:
        list_cameras()
        return
    if args.forget_me:
        forget_owner()
        return
    if args.enroll or args.add_face:
        enroll_from_camera(cfg, add=args.add_face)
        return
    if args.install_autostart or args.uninstall_autostart:
        if args.install_autostart:
            install_autostart()
        if args.uninstall_autostart:
            uninstall_autostart()
        return

    lock_handle = acquire_single_instance()  # noqa: F841
    if cfg["presence"] == "owner" and load_owner() is None:
        first_run_enroll(cfg)
    watcher = Watcher(cfg, make_detector(cfg), start_paused=args.paused)
    watcher.start()
    log.info("Watching camera %s every %ss, locking after %s empty scans. Ctrl+C to stop.",
             cfg["camera"], cfg["interval"], cfg["misses"])

    try:
        if args.no_tray:
            watcher.join()
        else:
            from awaylock_tray import run_tray  # kept out of this file on purpose
            if not run_tray(watcher):
                watcher.join()
    except KeyboardInterrupt:
        pass
    finally:
        watcher.stop()
        watcher.join(timeout=5)


if __name__ == "__main__":
    main()
