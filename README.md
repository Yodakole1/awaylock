# awaylock

Walk-away lock for Linux laptops with an IR camera (built with an ASUS VivoBook in mind).
It checks the camera every few seconds and locks your screen when no face has been seen for a while.
No face data is stored; frames are checked and thrown away.

## Install

The easy way, in a virtual environment (conda shown, venv works too):

```bash
conda create -n awaylock python=3.12 pip
conda activate awaylock
pip install -r requirements.txt
```

OpenCV 5 dropped the face detector awaylock uses, so requirements.txt keeps it on 4.x.

Or with your distro's packages:

```bash
# Debian / Ubuntu / Pop!_OS
sudo apt install python3-opencv python3-pil
pip install pystray        # optional, for the tray icon

# Arch
sudo pacman -S python-opencv python-pillow python-pystray

# Fedora
sudo dnf install python3-opencv python3-pillow
pip install pystray
```

On GNOME the tray icon needs the AppIndicator extension.

## Use

```bash
./awaylock.py                    # start with saved/default settings
./awaylock.py --interval 20      # scan every 20 seconds
./awaylock.py --misses 3         # lock after 3 empty scans in a row
./awaylock.py --camera 4         # use /dev/video4
./awaylock.py --interval 20 --save   # remember these settings
./awaylock.py --show-config      # see what's in effect
./awaylock.py --list-cameras     # find your IR camera (it opens each camera briefly)
./awaylock.py --black-frame skip # ignore black frames instead of treating them as "nobody there"
./awaylock.py --install-autostart    # start at login (--save first to keep your settings)
./awaylock.py --uninstall-autostart  # undo that
./awaylock.py --detector yunet   # more accurate detector (downloads a small model once)
./awaylock.py --paused           # start off, enable from the tray
./awaylock.py --no-tray          # no tray icon
./awaylock.py -v                 # more detail in the log
```

Time until lock is roughly `interval x misses`.
Settings are saved in `~/.config/awaylock/config.json`.

Click the tray icon to pause or resume. Pausing releases the camera completely.

## Only lock for *your* face (optional)

By default any face in front of the camera keeps the screen unlocked. If you'd rather it only trusts you:

```bash
./awaylock.py --enroll                    # look at the camera, turn your head a bit
./awaylock.py --presence owner --save     # from now on only your face counts
./awaylock.py --match-threshold 0.45      # stricter matching (default 0.363)
./awaylock.py --forget-me                 # delete your face data
```

Someone else sitting at your laptop while you're away then counts as nobody there, and it locks.

- Enrolling downloads two small face models once (YuNet and SFace from the OpenCV model zoo)
  and checks them against pinned hashes.
- What's stored is a set of numeric face "fingerprints" in `~/.local/share/awaylock/owner.npy`
  (readable only by you), not photos. Nothing leaves your machine.
- Enroll with the same camera you scan with. IR and color cameras see faces differently.
- **This is not authentication.** There's no liveness check, so a photo could fool it.
  It's for "lock when I leave", not for protecting a machine from someone determined.

## Tests

They never touch a camera or lock your screen.

```bash
pip install -r requirements-dev.txt
python -m pytest
```

## Camera tips

- The RGB camera is usually `/dev/video0`, the IR one `/dev/video2` or `/dev/video4`.
- Black frames on ASUS laptops (Sonix IR modules): the proximity sensor can switch the IR emitter off
  when it sees no motion. Wave a hand in front of the sensor to wake it.

## License

GPL-3.0-or-later. See [LICENSE](LICENSE). You're free to use, change and share it,
but modified versions you distribute must stay open source under the same license.
