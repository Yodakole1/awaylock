# Changelog

## Unreleased

First public version.

- Locks the screen when no face is seen for a configurable number of scans.
- Tray icon to pause and resume; pausing releases the camera.
- Everything is a command line option; `--save` remembers settings.
- `--list-cameras` finds the IR camera, `--install-autostart` starts it at login.
- Handles IR cameras that strobe their emitter (every other frame black).
- Skips scanning while the screen is locked.
- The camera is only open while scanning when the interval is 5 seconds or more.
- Optional YuNet detector and owner mode (`--enroll`, `--presence owner`) that only trusts your face.
- `--grace` warns before locking and looks once more; `--battery-interval` scans less often on battery.
- `--add-face` adds samples (glasses, headphones) to owner mode without replacing them.
- Tray menu and hover text show the latest scan and, in owner mode, the match score.
- Tray code moved to `awaylock_tray.py`.
- Single-instance lock, camera retry, pinned-hash model downloads.
- Tested on an ASUS VivoBook with Ubuntu and GNOME on Wayland.
