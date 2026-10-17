# awaylock

Walk-away lock for Linux laptops with an IR camera. Think Windows' "lock when I walk away",
for GNOME, KDE and friends.

awaylock looks through the camera every few seconds. When nobody has been in front of the
laptop for a while, it locks the screen. A tray icon lets you pause it, and an optional
owner mode only trusts *your* face, so someone else sitting down doesn't keep your session open.

Made and tested on an ASUS VivoBook (Sonix IR camera, Ubuntu, GNOME on Wayland).

## Contents

- [Quick start](#quick-start)
- [Install](#install)
- [Options](#options)
- [How it decides to lock](#how-it-decides-to-lock)
- [Owner mode](#owner-mode-only-lock-for-your-face)
- [Camera notes](#camera-notes)
- [Privacy](#privacy)
- [Status and limits](#status-and-limits)
- [Development](#development)
- [Changelog](CHANGELOG.md)
- [License](#license)

## Quick start

```bash
git clone git@github.com:Yodakole1/awaylock.git
cd awaylock
conda create -n awaylock python=3.12 pip       # or use a venv
conda activate awaylock
pip install -r requirements.txt

./awaylock.py --list-cameras                   # find your IR camera
./awaylock.py --camera 2 --interval 5 --save   # use it, scan every 5s, remember that
./awaylock.py                                  # run
./awaylock.py --install-autostart              # start at every login
```

## Install

Python 3.9+ and a webcam. IR cameras (the Windows Hello kind) work best because they see you
in the dark, but any camera works.

```bash
pip install -r requirements.txt
```

OpenCV 5 dropped the Haar face detector awaylock uses, so `requirements.txt` keeps OpenCV on 4.x.

### Tray icon on GNOME

GNOME only shows tray icons made through AppIndicator, which Python reaches via PyGObject.

```bash
# Ubuntu / Debian
sudo apt install gir1.2-ayatanaappindicator3-0.1
# in conda (venv users: install python3-gi from your distro instead)
conda install -c conda-forge pygobject
```

You also need the AppIndicator extension enabled (on Ubuntu it is by default).
conda and venv pythons don't look in the system's typelib folders, so awaylock points them there
itself before starting the tray.

Without the tray libraries awaylock still works. It prints a note and runs without an icon.

## Options

Every setting is a command line option. Add `--save` to keep what you passed as the new default
(stored in `~/.config/awaylock/config.json`).

| Option | What it does | Default |
|---|---|---|
| `--interval SECONDS` | Time between scans | 10 |
| `--misses N` | Empty scans in a row before locking | 3 |
| `--camera N` | Camera index, the N in `/dev/videoN` | 2 |
| `--detector haar\|yunet` | Face detector. YuNet is more accurate and downloads a small model once | haar |
| `--presence any\|owner` | Any face keeps you unlocked, or only your enrolled face | any |
| `--match-threshold X` | How similar a face must be to count as you, 0-1 | 0.363 |
| `--detect-threshold X` | How sure YuNet must be that something is a face | 0.8 |
| `--min-face PIXELS` | Smallest face to care about | 30 |
| `--black-frame absent\|skip` | Treat all-black frames as "nobody there", or ignore them | absent |
| `--paused` | Start paused, resume from the tray | off |
| `--no-tray` | Don't show a tray icon | off |
| `-v`, `--verbose` | Show more detail, including match scores | off |

One-shot commands that print something and exit:

| Command | What it does |
|---|---|
| `--list-cameras` | Opens each camera briefly and shows which look like IR |
| `--show-config` | Prints the settings in effect |
| `--install-autostart` / `--uninstall-autostart` | Start at login, or stop doing that |
| `--enroll` | Records your face for owner mode |
| `--forget-me` | Deletes your face data |

Click the tray icon to pause or resume. Pausing releases the camera completely.

## How it decides to lock

Each scan opens the camera, grabs a frame, runs the detector and closes the camera again,
so the camera light and the red IR flashing only happen while it is looking (about 1.7 seconds
per scan). With intervals under 5 seconds the camera stays open instead, because reopening
every time would just flicker.

One scan with no face counts as a miss, and a scan with a face resets the counter. After `--misses`
empty scans in a row the screen locks. Roughly:

```
time to lock  =  misses x (interval + about 2 seconds)
```

So `--interval 5 --misses 3` locks about 15 to 21 seconds after you leave.

Things it deliberately does not do:

- A camera hiccup (no frame) is not counted as "you left".
- While the screen is locked it stops scanning and releases the camera, then picks up again when you unlock.
- It refuses to start twice.

## Owner mode: only lock for your face

By default any face keeps the screen unlocked. If you'd rather it only trusts you:

```bash
./awaylock.py --enroll                    # look at the camera, turn your head a little
./awaylock.py --presence owner --save     # from now on only your face counts
./awaylock.py --match-threshold 0.45      # stricter matching (default 0.363)
./awaylock.py --forget-me                 # delete your face data
```

Someone else sitting at your laptop while you're away then counts as nobody there, and it locks.
Run with `-v` to see your match score on every scan, which is the easiest way to pick a threshold.

- Enrolling downloads two small face models once (YuNet and SFace from the
  [OpenCV model zoo](https://github.com/opencv/opencv_zoo)) and checks them against pinned hashes.
- Enroll with the camera you scan with. IR and color cameras see faces differently.
- Scores drop when you turn your head or sit at a different distance than when you enrolled.
  Enroll while moving a little, and keep `--misses` at 2 or more.
- **This is not authentication.** There is no liveness check, so a photo could fool it.
  It is for "lock when I leave", not for protecting a machine from someone determined.

## Camera notes

- The color camera is usually `/dev/video0` and the IR one `/dev/video2` or `/dev/video4`.
  `--list-cameras` tells you which is which.
- **IR cameras strobe.** On the VivoBook every second frame is pitch black because the emitter
  flashes. awaylock reads a few frames and uses the first lit one. Only if they are all black does
  it count as a black frame.
- **Black frames** can also mean the sensor went to sleep (some Sonix modules switch the emitter
  off when they see no motion). Waving a hand in front of it wakes it. `--black-frame absent`
  (default) treats those as nobody there, `skip` ignores them.
- **The camera LED can't be turned off from software.** It is tied to the sensor in hardware on
  purpose. A longer `--interval` means fewer flashes.

## Privacy

- Frames are analysed in memory and thrown away. Nothing is recorded, saved or sent anywhere.
- Owner mode stores a handful of numeric face "fingerprints" (not photos) in
  `~/.local/share/awaylock/owner.npy`, readable only by you. `--forget-me` deletes it.
- The only network access is the one-time download of the face models, checked against hashes.

## Status and limits

Tested on real hardware (ASUS VivoBook, Ubuntu, GNOME 50 on Wayland):
IR camera detection, scanning with Haar, YuNet and owner mode, enrollment, locking and unlocking,
pausing while locked, the tray icon, starting from the autostart entry at login, and owner mode turning away one other person (their scores
were 0.15-0.25 against 0.8-0.9 for the owner, with the default threshold of 0.363).

Covered by unit tests only, not yet tried on real hardware:

- KDE and the generic `loginctl` fallback for locking and lock detection.
- X11 sessions.

Other things to know:

- On GNOME, changing the tray icon can log `unable to update icon: ... Failed to recognize image format`
  in the journal. The icon still changes color correctly, so it is harmless noise for now.
- Haar occasionally misses a face in a single scan. That is what `--misses` is for, and YuNet is steadier.
- No liveness detection (see above).
- Linux only.

Reports from other hardware and desktops are very welcome, see below.

## Development

```bash
pip install -r requirements-dev.txt
python -m pytest
```

The tests never touch a camera or lock your screen. The camera, the lock call and the
neural nets are replaced with fakes.

Contributions are welcome, see [CONTRIBUTING.md](CONTRIBUTING.md). The most useful thing is trying it on
other laptops and desktops and reporting what happened (the issue template tells you what to include).
Other ideas: wake-on-approach, a warning before locking, and a battery mode.

## License

GPL-3.0-or-later. See [LICENSE](LICENSE). You are free to use, change and share it,
but modified versions you distribute must stay open source under the same license.
