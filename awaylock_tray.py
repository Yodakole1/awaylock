"""
The tray icon, kept apart from the camera logic in awaylock.py.

Everything you can see lives here, so a future graphical window can sit next to it
without touching the watcher. The only thing this file needs from awaylock is a
watcher object with:

    active          threading.Event, set while scanning
    toggle()        pause or resume
    stop()          shut down
    status_text()   one line about the latest scan, e.g. "Match 0.82 (need 0.45)"
    on_update       attribute we set to a function the watcher calls after every scan

Copyright (C) 2026 awaylock contributors
Licensed under the GNU General Public License v3.0 or later.
"""

import logging
import os

log = logging.getLogger("awaylock")


def expose_system_typelibs():
    """Let a conda/venv python find the system's AppIndicator library.

    GNOME only shows tray icons made through AppIndicator, which pystray reaches
    via PyGObject. Environments like conda don't look in the system's typelib
    folders, so we point them there. Has to happen before anything imports gi.
    """
    found = [d for d in ("/usr/lib/x86_64-linux-gnu/girepository-1.0",
                         "/usr/lib/aarch64-linux-gnu/girepository-1.0",
                         "/usr/lib64/girepository-1.0",
                         "/usr/lib/girepository-1.0") if os.path.isdir(d)]
    current = [d for d in os.environ.get("GI_TYPELIB_PATH", "").split(":") if d]
    os.environ["GI_TYPELIB_PATH"] = ":".join(current + [d for d in found if d not in current])


def run_tray(watcher):
    """Show the tray icon and block until it is quit. False if there is no tray support."""
    # Tray support is optional so the core still works on a bare install.
    expose_system_typelibs()
    try:
        import pystray
        from PIL import Image, ImageDraw
    except ImportError:
        log.warning("pystray/Pillow not installed, running without a tray icon.")
        return False

    def icon_image(on):
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.ellipse((4, 4, 60, 60), fill=(46, 160, 67, 255) if on else (130, 130, 130, 255))
        d.ellipse((22, 22, 42, 42), fill=(255, 255, 255, 255))
        return img

    def on_toggle(icon, item):
        watcher.toggle()
        icon.icon = icon_image(watcher.active.is_set())
        refresh()
        log.info("Resumed." if watcher.active.is_set() else "Paused, camera released.")

    def on_quit(icon, item):
        log.info("Quit from the tray.")
        watcher.stop()
        icon.stop()

    def refresh():
        # The hover text and the first menu line both show the latest scan.
        icon.title = "awaylock: " + watcher.status_text()
        try:
            icon.update_menu()
        except Exception:  # a menu that fails to redraw must never take the watcher down
            log.debug("Couldn't refresh the tray menu", exc_info=True)

    menu = pystray.Menu(
        pystray.MenuItem(lambda item: watcher.status_text(), None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(lambda item: "Pause" if watcher.active.is_set() else "Resume",
                         on_toggle, default=True),  # default = left click
        pystray.MenuItem("Quit", on_quit),
    )
    icon = pystray.Icon("awaylock", icon_image(watcher.active.is_set()), "awaylock", menu)
    watcher.on_update = refresh
    try:
        icon.run()
    finally:
        watcher.on_update = None
    return True
