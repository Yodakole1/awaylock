# Contributing to awaylock

Thanks for helping. This is a small tool of two files, so contributing is easy.

## The most useful thing you can do

**Try it on your hardware and tell us what happened.** awaylock was built and tested on one
ASUS VivoBook with GNOME on Wayland. The README's "Status and limits" section lists what has
only been covered by unit tests: KDE, X11, the `loginctl` fallback, and other IR cameras.
A short report ("works on a Lenovo X1 with KDE" or "locks but the camera index was 4") is a real contribution.

When you open an issue, please include:

- the output of `./awaylock --list-cameras`
- your desktop and session: `echo $XDG_CURRENT_DESKTOP $XDG_SESSION_TYPE`
- a log from `./awaylock -v`
- your laptop model

## Setting up

```bash
git clone git@github.com:Yodakole1/awaylock.git
cd awaylock
git switch develop
python3 -m venv --system-site-packages .venv   # needs python3-venv and python3-gi, see the README
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest
```

## Branches

- `main` is the stable branch. It always works and is what people clone and install from.
  Releases are tagged on it. Nobody commits to it directly.
- `develop` is where work comes together. Pull requests target `develop`.
- Work on a short-lived branch cut from `develop`, named for what it does (`fix-black-frames`,
  `add-grace-warning`), and open the PR back into `develop`.
- When `develop` is tested and ready, the maintainer merges it into `main` and tags a release.
  A bad regression found on `main` can be fixed in a branch off `main` and merged into both.

```bash
git switch develop
git pull
git switch -c my-change
```

## Before you open a pull request

A pull request is a proposal, not a guarantee. It gets merged when it's correct, shown to work,
tested, reasonably small, and fits where the project is going. Something can be good and still not
be merged if it adds more upkeep than it's worth.

- **One topic per PR.** A bug fix, a new option and a refactor are three PRs.
- **Match the existing style.** Read the code around your change and write like it.
- **Don't break what already works.** New features must leave existing behavior, defaults and
  options alone unless the PR is specifically about changing them. If you change a default, say so loudly.
- **It has to run.** Install from `requirements.txt`, start the program, and run `.venv/bin/python -m pytest`
  before you ask for review. If something fails to import or build, include the log. GitHub runs the same
  tests on every pull request (Python 3.10, 3.12 and 3.14); a red check has to be fixed before a merge.
- **Say how you tested.** See the next section. "Untested" is an acceptable answer as long as it's honest.
- **Be sparing with logging.** A log line should help someone diagnose a real problem. Don't narrate
  every step.
- **Comments explain why.** Write down design decisions and non-obvious details, not what the next
  line obviously does.

## Testing, and saying so

Every PR description must say what was tested and how. Tick the boxes in the PR template that are
true and leave the rest unticked with a short note. Nobody will be annoyed by "I couldn't test this on KDE";
they will be annoyed by a claim that turns out not to be true.

There are two kinds of checking, and they cover different things:

1. **Automated tests** (`.venv/bin/python -m pytest`). They use fakes instead of a camera, a screen lock or the
   neural nets, so they run anywhere. New behavior should come with a test. They are the only part
   GitHub's check can run for you, so a green check says nothing about real hardware.
2. **Real hardware.** Anything touching the camera, the lock command, the tray or autostart should be
   tried for real, and the PR should say on what: laptop, camera (`--list-cameras` output),
   desktop and session type, and what you did and saw. If you changed how scanning works, paste a short
   `-v` log. If you couldn't try it on hardware, say that plainly. The maintainer may be able to.

## If AI helped you write it

That's allowed, with conditions. You own the change, not the tool.

- Write the PR description yourself, in your own words: what it does, why it's needed and what problem
  it solves. Don't paste a generated summary.
- Only submit code you understand well enough to explain and maintain. In review you'll be asked why it
  works this way, and "the AI wrote it" won't be accepted as an answer.
- Large generated changes that the author can't walk through will be turned down, even if they work.
- Skim the generated comments. Delete the ones that just restate the code.

## Making a change

- Keep it simple. `awaylock.py` (the logic) and `awaylock_tray.py` (everything visible) are meant to be readable in one sitting. Keep camera logic out of the tray file and drawing out of the logic file.
- Write comments the way you'd explain it to a friend: why, not a line-by-line narration.
- Add a test for new behavior. The tests never use a real camera or lock a real screen; the camera,
  the lock call and the neural nets are replaced with fakes (see `tests/test_awaylock.py`).
- If your change affects what a user sees or types, update the README and the changelog.

## Ideas that would be great

- Wake-on-approach: waking the screen when you sit back down.
- A grace warning ("locking in 10s") before the lock.
- Battery mode with a longer interval.
- Support for more desktops and lockers, with real-hardware testing.
- A `pyproject.toml` so `pip install .` gives an `awaylock` command.

## License

By contributing you agree that your work is released under the project's license,
GPL-3.0-or-later.
