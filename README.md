# awaylock

[![tests](https://github.com/Yodakole1/awaylock/actions/workflows/tests.yml/badge.svg)](https://github.com/Yodakole1/awaylock/actions/workflows/tests.yml)

Walk-away lock for Linux laptops with an IR camera. Think Windows' "lock when I walk away",
for GNOME, KDE and friends.

awaylock looks through the camera every few seconds. When nobody has been in front of the
laptop for a while, it locks the screen. It only trusts *your* face (owner mode, the default), so someone
else sitting down doesn't keep your session open. A tray icon lets you pause it.

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

On Ubuntu, Debian, Pop!_OS or Mint. Copy and paste this whole block into a terminal. It asks for
your password once, for the `sudo apt` line.

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip python3-gi gir1.2-ayatanaappindicator3-0.1

git clone https://github.com/Yodakole1/awaylock.git
cd awaylock
python3 -m venv --system-site-packages .venv
.venv/bin/pip install -r requirements.txt
```

Then, from the `awaylock` folder:

```bash
./awaylock --list-cameras                   # shows your cameras, find the one marked "looks like IR"
./awaylock --camera 2 --interval 5 --save   # use it (change 2 to your number), scan every 5s, remember that
./awaylock                                  # first run: it learns your face, then a tray icon appears
./awaylock --install-autostart              # start it automatically at every login
```

The very first run asks you to sit in front of the camera and press Enter, then records a few samples
of your face. That needs internet once, to download the two small face models (about 40 MB, mostly
the recognition model). If you'd rather skip owner mode and let any face keep the screen unlocked,
run `./awaylock --presence any --save`.

Press `Ctrl+C` to stop it. To test it, cover the camera with your hand and wait. The screen
should lock after a few scans.

No IR camera? It works with a normal webcam too, which is usually camera `0`.

## Install

You need a Linux desktop, Python 3.9 or newer and a webcam. IR cameras (the Windows Hello kind)
work best because they see you in the dark, but any camera works.

What the packages in the quick start are for:

| Package | Why |
|---|---|
| `python3`, `python3-venv`, `python3-pip` | Python and a private place to install awaylock's libraries (`.venv`) |
| `git` | To download the project |
| `python3-gi`, `gir1.2-ayatanaappindicator3-0.1` | The tray icon on GNOME. Optional, awaylock runs without it |

`requirements.txt` installs OpenCV, Pillow and pystray into `.venv`. It keeps OpenCV on 4.x,
because OpenCV 5 dropped the Haar face detector awaylock uses.

`--system-site-packages` lets the private `.venv` see the system's `python3-gi`, which is the
easiest way to get the tray working. You can leave it out if you don't want a tray icon.

**Other distros** (package names are from memory and not tested, corrections welcome):

```bash
# Fedora
sudo dnf install git python3 python3-pip python3-gobject libayatana-appindicator-gtk3
# Arch
sudo pacman -S git python python-pip python-gobject libayatana-appindicator
```

then the same `git clone`, `python3 -m venv --system-site-packages .venv` and `pip install` lines.

**Updating:** `cd awaylock && git pull && .venv/bin/pip install -r requirements.txt`

**Uninstalling:** `./awaylock --uninstall-autostart`, then delete the `awaylock` folder. Your
settings live in `~/.config/awaylock/` and any face data in `~/.local/share/awaylock/`
(`./awaylock --forget-me` removes the face data).

### Tray icon on GNOME

GNOME only shows tray icons made through AppIndicator. Ubuntu has the AppIndicator extension
enabled by default, so the packages above are all you need. Without them awaylock still works, it just
prints a note and runs without an icon (use `--no-tray` to skip the note).

## Options

Every setting is a command line option. Add `--save` to keep what you passed as the new default
(stored in `~/.config/awaylock/config.json`).

| Option | What it does | Default |
|---|---|---|
| `--interval SECONDS` | Time between scans | 10 |
| `--grace SECONDS` | Show a "locking in N seconds" popup and look once more before locking. Showing up cancels the lock. 0 turns it off | 0 |
| `--battery-interval SECONDS` | Scan this far apart while on battery, to save power. 0 means same as `--interval` | 0 |
| `--misses N` | Empty scans in a row before locking | 3 |
| `--camera N` | Camera index, the N in `/dev/videoN` | 2 |
| `--detector haar\|yunet` | Face detector for `--presence any`. YuNet is more accurate and downloads a small model once. Owner mode always uses YuNet | haar |
| `--presence owner\|any` | Only your enrolled face keeps you unlocked, or any face does | owner |
| `--match-threshold X` | How similar a face must be to count as you, 0-1 | 0.45 |
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
| `--enroll` | Records your face for owner mode, replacing what was stored |
| `--add-face` | Adds more samples to your face data, for glasses, headphones or a hat |
| `--forget-me` | Deletes your face data |

Click the tray icon to pause or resume. Pausing releases the camera completely. The first line of the
tray menu (and the hover text, where your desktop shows one) tells you what the latest scan saw, and in
owner mode how well your face matched, like `Match 0.82 (need 0.45)`.

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

With `--grace 10`, the last miss doesn't lock right away. You get a popup, awaylock waits 10 seconds,
looks once more, and only locks if there is still nobody. The camera stays on during the wait.
The popup uses `notify-send` (package `libnotify-bin`, already there on Ubuntu); without it you
just don't see the warning.

`--battery-interval 30` makes it scan every 30 seconds while the laptop runs on battery and go back
to `--interval` on AC. The time to lock stretches accordingly, so pair it with fewer `--misses`.

Things it deliberately does not do:

- A camera hiccup (no frame) is not counted as "you left".
- While the screen is locked it stops scanning and releases the camera, then picks up again when you unlock.
- It refuses to start twice.

## Owner mode: only your face counts

This is the default. Someone else sitting at your laptop while you're away counts as nobody there, so
it locks. The first run walks you through learning your face; after that:

```bash
./awaylock --enroll                    # start over: replaces the stored face data
./awaylock --add-face                  # add more samples, keeps the old ones
./awaylock --presence any --save       # switch owner mode off, any face keeps you unlocked
./awaylock --match-threshold 0.55      # stricter matching (default 0.45)
./awaylock --add-face                  # teach it you with glasses, headphones, a hat...
./awaylock --forget-me                 # delete your face data
```

awaylock only ever *locks*. Getting back in still takes your password. Run with `-v` to see your match score on every scan, which is the easiest way to pick a threshold.

- Enrolling downloads two small face models once (YuNet and SFace from the
  [OpenCV model zoo](https://github.com/opencv/opencv_zoo)) and checks them against pinned hashes.
- `--enroll` replaces what was stored. `--add-face` keeps it and adds more samples, so run it once
  per look: put the glasses on, run it, take them off again. Scores for the new look then stop
  dropping below the threshold. Samples are one shared pool, so a second person (a partner, your dad)
  can be added the same way and any of you keeps the screen unlocked.
- Started from autostart with no face data, awaylock can't ask you anything, so it shows a popup telling you
  to run `./awaylock --enroll` and exits.
- Upgrading from the first version? Your saved settings still say `presence: any`. Switch with
  `./awaylock --presence owner --save` (and `--enroll` if you haven't yet).
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
were 0.11-0.27 over two sessions against 0.8-0.9 for the owner, against a threshold of 0.363; the default is now 0.45 for more margin).

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
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest
```

The tests never touch a camera or lock your screen. The camera, the lock call and the
neural nets are replaced with fakes.

The code is split in two files on purpose: `awaylock.py` does the watching, locking and
command line, and `awaylock_tray.py` holds everything you can see (the tray icon and its menu). A future
graphical window can go next to the tray file without touching the watcher. The watcher offers
`status_text()` and an `on_update` hook for any interface to use.

Contributions are welcome, see [CONTRIBUTING.md](CONTRIBUTING.md). The most useful thing is trying it on
other laptops and desktops and reporting what happened (the issue template tells you what to include).
Other ideas: wake-on-approach.

## License

GPL-3.0-or-later. See [LICENSE](LICENSE). You are free to use, change and share it,
but modified versions you distribute must stay open source under the same license.
