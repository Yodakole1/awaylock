# Contributing to awaylock

Thanks for helping. This is a small, single-file tool, so contributing is easy.

## The most useful thing you can do

**Try it on your hardware and tell us what happened.** awaylock was built and tested on one
ASUS VivoBook with GNOME on Wayland. The README's "Status and limits" section lists what has
only been covered by unit tests: KDE, X11, the `loginctl` fallback, and other IR cameras.
A short report ("works on a Lenovo X1 with KDE" or "locks but the camera index was 4") is a real contribution.

When you open an issue, please include:

- the output of `./awaylock.py --list-cameras`
- your desktop and session: `echo $XDG_CURRENT_DESKTOP $XDG_SESSION_TYPE`
- a log from `./awaylock.py -v`
- your laptop model

## Setting up

```bash
git clone git@github.com:Yodakole1/awaylock.git
cd awaylock
conda create -n awaylock python=3.12 pip   # or python -m venv
conda activate awaylock
pip install -r requirements-dev.txt
python -m pytest
```

## Making a change

- Keep it simple. `awaylock.py` is one file on purpose, so people can read all of it.
- Write comments the way you'd explain it to a friend: why, not a line-by-line narration.
- Add a test for new behavior. The tests never use a real camera or lock a real screen; the camera,
  the lock call and the neural nets are replaced with fakes (see `tests/test_awaylock.py`).
- Run `python -m pytest` before opening a pull request.
- If your change affects what a user sees or types, update the README.
- Keep changes focused: one fix or feature per pull request.

## Ideas that would be great

- Wake-on-approach: waking the screen when you sit back down.
- A grace warning ("locking in 10s") before the lock.
- Battery mode with a longer interval.
- Support for more desktops and lockers, with real-hardware testing.
- A `pyproject.toml` so `pip install .` gives an `awaylock` command.

## License

By contributing you agree that your work is released under the project's license,
GPL-3.0-or-later.
