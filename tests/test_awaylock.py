"""Tests that never touch a real camera or lock a real screen."""

import json

import numpy as np
import pytest

import awaylock

real_screen_locked = awaylock.screen_locked  # the autouse fixture below replaces the module's copy


# ---------- helpers ----------

class FakeCam:
    """Stands in for cv2.VideoCapture and hands out the same frame every time."""

    def __init__(self, frame, ok=True):
        self.frame = frame
        self.ok = ok

    def grab(self):
        return self.ok

    def read(self):
        return self.ok, self.frame

    def release(self):
        pass


class FakeDetector:
    """Says a face is there whenever it was given some."""

    def __init__(self, faces):
        self.faces = faces

    def present(self, frame):
        return len(self.faces) > 0


BRIGHT = np.full((48, 64), 120, dtype=np.uint8)
BLACK = np.zeros((48, 64), dtype=np.uint8)
FACE = [(10, 10, 40, 40)]


@pytest.fixture
def locks(monkeypatch):
    """Replaces the real screen lock and counts how often it was called."""
    calls = []
    monkeypatch.setattr(awaylock, "lock_screen", lambda: calls.append(1))
    return calls


@pytest.fixture
def cfg():
    # most tests exercise scanning with fake detectors, so they use "any" rather than owner mode
    return dict(awaylock.DEFAULTS, misses=3, presence="any")


def make_watcher(cfg, faces):
    w = awaylock.Watcher(cfg, FakeDetector(faces))
    return w


@pytest.fixture(autouse=True)
def isolated_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(awaylock, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(awaylock, "AUTOSTART_PATH", tmp_path / "autostart" / "awaylock.desktop")
    monkeypatch.setattr(awaylock, "LOCK_PATH", tmp_path / "awaylock.lock")
    monkeypatch.setattr(awaylock, "OWNER_PATH", tmp_path / "data" / "owner.npy")
    monkeypatch.setattr(awaylock, "MODELS_DIR", tmp_path / "models")
    monkeypatch.setattr(awaylock, "screen_locked", lambda: False)  # never ask the real desktop
    monkeypatch.setattr(awaylock, "notify", lambda *a, **k: None)  # no real popups
    monkeypatch.setattr(awaylock, "close_notification", lambda nid: None)


# ---------- arguments and config ----------

def test_interval_flag_overrides_default():
    cfg = awaylock.resolve_config(awaylock.parse_args(["--interval", "20"]))
    assert cfg["interval"] == 20


def test_defaults_used_when_nothing_given():
    cfg = awaylock.resolve_config(awaylock.parse_args([]))
    assert cfg == awaylock.DEFAULTS


def test_saved_config_beats_defaults_and_flags_beat_saved():
    awaylock.save_config(dict(awaylock.DEFAULTS, interval=30, misses=7))
    cfg = awaylock.resolve_config(awaylock.parse_args(["--misses", "2"]))
    assert cfg["interval"] == 30
    assert cfg["misses"] == 2


def test_broken_config_file_is_ignored():
    awaylock.CONFIG_PATH.write_text("{ not json")
    assert awaylock.load_config() == awaylock.DEFAULTS


def test_config_with_wrong_shape_is_ignored():
    awaylock.CONFIG_PATH.write_text("[1, 2, 3]")
    assert awaylock.load_config() == awaylock.DEFAULTS


def test_unknown_keys_in_config_are_dropped():
    awaylock.CONFIG_PATH.write_text(json.dumps({"interval": 5, "bogus": 1}))
    cfg = awaylock.load_config()
    assert cfg["interval"] == 5
    assert "bogus" not in cfg


@pytest.mark.parametrize("flags", [
    ["--interval", "0"],
    ["--interval", "-3"],
    ["--misses", "0"],
    ["--min-face", "0"],
])
def test_nonsense_values_exit(flags):
    with pytest.raises(SystemExit):
        awaylock.resolve_config(awaylock.parse_args(flags))


def test_bad_black_frame_choice_rejected_by_parser():
    with pytest.raises(SystemExit):
        awaylock.parse_args(["--black-frame", "maybe"])


def test_save_writes_file(capsys):
    awaylock.main(["--interval", "20", "--save", "--show-config"])
    assert json.loads(awaylock.CONFIG_PATH.read_text())["interval"] == 20


# ---------- autostart ----------

def test_autostart_install_and_remove():
    awaylock.install_autostart()
    text = awaylock.AUTOSTART_PATH.read_text()
    assert "[Desktop Entry]" in text
    assert "awaylock.py" in text
    awaylock.uninstall_autostart()
    assert not awaylock.AUTOSTART_PATH.exists()


def test_autostart_remove_without_install_is_fine(capsys):
    awaylock.uninstall_autostart()
    assert "wasn't set up" in capsys.readouterr().out


# ---------- single instance ----------

def test_second_instance_refused():
    first = awaylock.acquire_single_instance()
    with pytest.raises(SystemExit):
        awaylock.acquire_single_instance()
    first.close()
    awaylock.acquire_single_instance().close()  # free again after release


# ---------- camera node names ----------

def test_video_index(tmp_path):
    assert awaylock.video_index(tmp_path / "video4") == 4
    assert awaylock.video_index(tmp_path / "video12") == 12
    assert awaylock.video_index(tmp_path / "videoX") is None


# ---------- scanning logic ----------

def test_locks_after_enough_empty_scans(cfg, locks):
    w = make_watcher(cfg, faces=[])
    cam = FakeCam(BRIGHT)
    assert [w.scan_once(cam) for _ in range(3)] == [False, False, True]
    assert len(locks) == 1
    assert w.misses == 0  # starts over after locking


def test_seeing_a_face_resets_the_counter(cfg, locks):
    w = make_watcher(cfg, faces=[])
    cam = FakeCam(BRIGHT)
    w.scan_once(cam)
    w.scan_once(cam)
    w.detector = FakeDetector(FACE)
    w.scan_once(cam)
    assert w.misses == 0
    w.detector = FakeDetector([])
    w.scan_once(cam)
    w.scan_once(cam)
    assert locks == []  # never reached 3 in a row


def test_camera_hiccup_does_not_count(cfg, locks):
    w = make_watcher(cfg, faces=[])
    for _ in range(10):
        w.scan_once(FakeCam(None, ok=False))
    assert w.misses == 0
    assert locks == []


def test_black_frame_counts_as_absent_by_default(cfg, locks):
    w = make_watcher(dict(cfg, black_frame="absent"), faces=[])
    cam = FakeCam(BLACK)
    for _ in range(3):
        w.scan_once(cam)
    assert len(locks) == 1
    assert w.dark


def test_black_frame_skipped_when_asked(cfg, locks):
    w = make_watcher(dict(cfg, black_frame="skip"), faces=[])
    cam = FakeCam(BLACK)
    for _ in range(10):
        w.scan_once(cam)
    assert locks == []
    assert w.misses == 0


def test_color_frames_work_too(cfg, locks):
    color = np.full((48, 64, 3), 120, dtype=np.uint8)
    w = make_watcher(cfg, faces=FACE)
    assert w.face_present(FakeCam(color)) is True


def test_real_cascade_finds_no_face_in_blank_image(cfg):
    w = awaylock.Watcher(cfg)  # real Haar model, no fake
    assert isinstance(w.detector, awaylock.HaarDetector)
    assert w.face_present(FakeCam(BRIGHT)) is False


# ---------- pause / resume ----------

def test_toggle_flips_active(cfg):
    w = awaylock.Watcher(cfg)
    assert w.active.is_set()
    w.toggle()
    assert not w.active.is_set()
    w.toggle()
    assert w.active.is_set()


def test_start_paused(cfg):
    assert not awaylock.Watcher(cfg, start_paused=True).active.is_set()


def test_stop_wakes_a_paused_watcher(cfg):
    w = awaylock.Watcher(cfg, start_paused=True)
    w.stop()
    assert w.quit.is_set()
    assert w.active.is_set()


def test_run_retries_when_camera_missing(cfg, monkeypatch):
    cfg = dict(cfg, interval=0.01)
    w = awaylock.Watcher(cfg)
    attempts = []

    def fail_open():
        attempts.append(1)
        if len(attempts) == 3:
            w.stop()
        return None

    monkeypatch.setattr(w, "open_camera", fail_open)
    w.run()  # returns once stop() is called, instead of crashing
    assert len(attempts) == 3


# ---------- face recognition ----------

def unit(*values):
    return np.array(values, dtype=np.float32)


def test_cosine_similarity_identical_and_opposite():
    owner = np.array([unit(1, 0, 0)])
    assert awaylock.cosine_similarity(unit(2, 0, 0), owner) == pytest.approx(1.0)
    assert awaylock.cosine_similarity(unit(-1, 0, 0), owner) == pytest.approx(-1.0)
    assert awaylock.cosine_similarity(unit(0, 1, 0), owner) == pytest.approx(0.0)


def test_cosine_similarity_picks_best_enrolled_sample():
    owner = np.array([unit(0, 1, 0), unit(1, 0, 0)])
    assert awaylock.cosine_similarity(unit(1, 0, 0), owner) == pytest.approx(1.0)


def test_owner_data_roundtrip_and_permissions():
    assert awaylock.load_owner() is None
    awaylock.save_owner([unit(1, 2, 3), unit(4, 5, 6)])
    assert awaylock.load_owner().shape == (2, 3)
    assert awaylock.OWNER_PATH.stat().st_mode & 0o777 == 0o600


def test_forget_owner_deletes_data(capsys):
    awaylock.save_owner([unit(1, 2, 3)])
    awaylock.forget_owner()
    assert awaylock.load_owner() is None
    awaylock.forget_owner()  # second time is harmless
    assert "no face data" in capsys.readouterr().out.lower()


def test_corrupt_owner_file_counts_as_missing():
    awaylock.OWNER_PATH.parent.mkdir(parents=True)
    awaylock.OWNER_PATH.write_bytes(b"garbage")
    assert awaylock.load_owner() is None


def test_owner_mode_without_enrollment_exits(cfg):
    with pytest.raises(SystemExit, match="enroll"):
        awaylock.make_detector(dict(cfg, presence="owner"))


def test_make_detector_defaults_to_haar(cfg):
    assert isinstance(awaylock.make_detector(cfg), awaylock.HaarDetector)


@pytest.mark.parametrize("flags", [
    ["--match-threshold", "0"],
    ["--match-threshold", "1.5"],
    ["--detect-threshold", "0"],
])
def test_bad_thresholds_exit(flags):
    with pytest.raises(SystemExit):
        awaylock.resolve_config(awaylock.parse_args(flags))


def test_new_flags_parse():
    cfg = awaylock.resolve_config(awaylock.parse_args(
        ["--detector", "yunet", "--presence", "owner", "--match-threshold", "0.5"]))
    assert (cfg["detector"], cfg["presence"], cfg["match_threshold"]) == ("yunet", "owner", 0.5)


# ---------- model download ----------

def fake_model(tmp_path, content=b"pretend model"):
    import hashlib
    src = tmp_path / "src.onnx"
    src.write_bytes(content)
    return {"m": ("m.onnx", src.as_uri(), hashlib.sha256(b"pretend model").hexdigest())}


def test_model_download_checks_hash_and_caches(tmp_path):
    models = fake_model(tmp_path)
    path = awaylock.ensure_model("m", models, tmp_path / "dl")
    assert path.read_bytes() == b"pretend model"
    # Second call must not need the source any more.
    (tmp_path / "src.onnx").unlink()
    assert awaylock.ensure_model("m", models, tmp_path / "dl") == path


def test_model_with_wrong_hash_is_rejected(tmp_path):
    models = fake_model(tmp_path, content=b"something else")
    with pytest.raises(SystemExit, match="hash"):
        awaylock.ensure_model("m", models, tmp_path / "dl")
    assert not (tmp_path / "dl" / "m.onnx").exists()


def test_model_download_failure_is_a_clean_exit(tmp_path):
    models = {"m": ("m.onnx", (tmp_path / "nope.onnx").as_uri(), "0" * 64)}
    with pytest.raises(SystemExit, match="download"):
        awaylock.ensure_model("m", models, tmp_path / "dl")


def test_pinned_model_hashes_look_sane():
    for filename, url, sha in awaylock.MODELS.values():
        assert url.startswith("https://") and len(sha) == 64


# ---------- owner matching ----------

def make_owner_detector(cfg, owner, faces, features):
    """OwnerDetector with the neural nets swapped for canned answers."""
    d = awaylock.OwnerDetector.__new__(awaylock.OwnerDetector)
    d.owner = np.array(owner)
    d.threshold = cfg["match_threshold"]
    d.last_score = None
    d.faces = lambda frame: faces
    d.feature = lambda frame, face: features[face]
    return d


def test_owner_recognised(cfg):
    d = make_owner_detector(cfg, [unit(1, 0)], faces=["me"], features={"me": unit(1, 0.1)})
    assert d.present(BRIGHT) is True


def test_stranger_alone_does_not_count(cfg):
    d = make_owner_detector(cfg, [unit(1, 0)], faces=["them"], features={"them": unit(0, 1)})
    assert d.present(BRIGHT) is False
    assert d.last_score < cfg["match_threshold"]


def test_owner_next_to_stranger_still_counts(cfg):
    d = make_owner_detector(cfg, [unit(1, 0)], faces=["them", "me"],
                            features={"them": unit(0, 1), "me": unit(1, 0)})
    assert d.present(BRIGHT) is True


def test_empty_room_is_absent(cfg):
    d = make_owner_detector(cfg, [unit(1, 0)], faces=[], features={})
    assert d.present(BRIGHT) is False


def test_stranger_alone_leads_to_lock(cfg, locks):
    d = make_owner_detector(cfg, [unit(1, 0)], faces=["them"], features={"them": unit(0, 1)})
    w = awaylock.Watcher(cfg, d)
    cam = FakeCam(BRIGHT)
    for _ in range(3):
        w.scan_once(cam)
    assert len(locks) == 1


# ---------- enrolling ----------

class EnrollDetector:
    """Hands out a scripted list of face counts, one per frame."""

    def __init__(self, counts):
        self.counts = iter(counts)

    def faces(self, frame):
        return ["face"] * next(self.counts)

    def feature(self, frame, face):
        return unit(1, 2, 3)


def test_enroll_collects_only_single_face_frames():
    said = []
    det = EnrollDetector([0, 2, 1, 1, 1])
    feats = awaylock.enroll(FakeCam(BRIGHT), det, samples=3, delay=0, say=said.append)
    assert feats.shape == (3, 3)
    assert any("More than one" in m for m in said)
    assert any("No face" in m for m in said)


def test_enroll_gives_up_with_a_helpful_message():
    det = EnrollDetector([0] * 5)
    with pytest.raises(SystemExit, match="enough good frames"):
        awaylock.enroll(FakeCam(BRIGHT), det, samples=3, attempts=5, delay=0, say=lambda m: None)


def test_enroll_warns_about_black_frames():
    said = []
    with pytest.raises(SystemExit):
        awaylock.enroll(FakeCam(BLACK), EnrollDetector([]), samples=1, attempts=2, delay=0, say=said.append)
    assert any("wave a hand" in m for m in said)


# ---------- strobing IR camera ----------

class StrobeCam:
    """Like the real IR camera: every other frame is black."""

    def __init__(self, lit_first=False):
        self.n = 0 if lit_first else 1

    def grab(self):
        self.n += 1
        return True

    def read(self):
        self.n += 1
        return True, (BRIGHT if self.n % 2 == 0 else BLACK)


@pytest.mark.parametrize("lit_first", [True, False])
def test_best_frame_skips_the_black_strobe_frames(lit_first):
    frame = awaylock.best_frame(StrobeCam(lit_first))
    assert frame.mean() > awaylock.BLACK_LEVEL


def test_best_frame_returns_black_when_everything_is_black():
    assert awaylock.best_frame(FakeCam(BLACK)).mean() == 0


def test_best_frame_none_when_camera_gives_nothing():
    assert awaylock.best_frame(FakeCam(None, ok=False)) is None


def test_strobe_does_not_cause_false_locks(cfg, locks):
    w = make_watcher(cfg, faces=FACE)
    cam = StrobeCam()
    for _ in range(20):
        w.scan_once(cam)
    assert locks == []
    assert not w.dark


# ---------- pausing while locked ----------

class Result:
    def __init__(self, stdout, returncode=0):
        self.stdout = stdout
        self.returncode = returncode


@pytest.mark.parametrize("desktop, output, expected", [
    ("ubuntu:GNOME", "method return time=1 sender=:1.5 -> destination=:1.9 serial=3 reply_serial=2\n   boolean true\n", True),
    ("ubuntu:GNOME", "method return time=1\n   boolean false\n", False),
    ("KDE", "true\n", True),
    ("KDE", "false\n", False),
    ("sway", "yes\n", True),
    ("sway", "no\n", False),
    ("sway", "", None),
])
def test_screen_locked_reads_each_desktop(monkeypatch, desktop, output, expected):
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", desktop)
    monkeypatch.setattr(awaylock.subprocess, "run", lambda *a, **k: Result(output))
    assert real_screen_locked() is expected


def test_screen_locked_unknown_when_tool_missing(monkeypatch):
    def boom(*a, **k):
        raise FileNotFoundError

    monkeypatch.setattr(awaylock.subprocess, "run", boom)
    assert real_screen_locked() is None


def test_no_scanning_or_camera_while_locked(cfg, monkeypatch):
    w = awaylock.Watcher(dict(cfg, interval=0.01), FakeDetector([]))
    checks = []

    def locked():
        checks.append(1)
        if len(checks) == 4:
            w.stop()
        return True

    monkeypatch.setattr(awaylock, "screen_locked", locked)
    monkeypatch.setattr(w, "open_camera", lambda: pytest.fail("camera opened while locked"))
    w.run()
    assert len(checks) == 4
    assert w.was_locked


def test_scanning_resumes_after_unlock(cfg, monkeypatch, locks):
    w = awaylock.Watcher(dict(cfg, interval=0.01, misses=1), FakeDetector([]))
    states = iter([True, True, False])
    monkeypatch.setattr(awaylock, "screen_locked", lambda: next(states))
    monkeypatch.setattr(w, "open_camera", lambda: FakeCam(BRIGHT))
    monkeypatch.setattr(awaylock, "lock_screen", lambda: (locks.append(1), w.stop()))
    w.run()
    assert len(locks) == 1  # locked once it was unlocked and nobody was there
    assert not w.was_locked


# ---------- camera only open while scanning ----------

class CountingCam(FakeCam):
    def __init__(self):
        super().__init__(BRIGHT)
        self.released = False

    def release(self):
        self.released = True


@pytest.mark.parametrize("interval, stays_open", [(10, False), (5, False), (2, True)])
def test_camera_closed_between_scans_only_for_long_intervals(cfg, monkeypatch, interval, stays_open):
    w = awaylock.Watcher(dict(cfg, interval=interval), FakeDetector(FACE))
    cams = []

    def open_camera():
        cams.append(CountingCam())
        return cams[-1]

    monkeypatch.setattr(w, "open_camera", open_camera)
    state_while_waiting = []

    def wait(t):  # runs between two scans, then we stop
        state_while_waiting.append(cams[0].released)
        w.quit.set()

    monkeypatch.setattr(w.quit, "wait", wait)
    w.run()
    assert state_while_waiting == [not stays_open]
    assert cams[0].released is True  # always released on the way out


def test_long_interval_reopens_camera_for_each_scan(cfg, monkeypatch):
    w = awaylock.Watcher(dict(cfg, interval=10), FakeDetector(FACE))
    cams = []
    monkeypatch.setattr(w, "open_camera", lambda: cams.append(CountingCam()) or cams[-1])
    count = []

    def wait(t):
        count.append(1)
        if len(count) == 3:
            w.quit.set()

    monkeypatch.setattr(w.quit, "wait", wait)
    w.run()
    assert len(cams) == 3
    assert all(c.released for c in cams)


# ---------- grace warning ----------

class ScriptedDetector:
    """Answers present() from a list, one answer per scan, repeating the last."""

    def __init__(self, *answers):
        self.answers = list(answers)

    def present(self, frame):
        return self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]


def grace_watcher(cfg, *answers, grace=0.01):
    cfg = dict(cfg, misses=1, grace=grace)
    w = awaylock.Watcher(cfg, ScriptedDetector(*answers))
    w.open_camera = lambda: FakeCam(BRIGHT)  # the recheck opens its own camera
    return w


def test_no_grace_locks_straight_away(cfg, locks, monkeypatch):
    warned = []
    monkeypatch.setattr(awaylock, "notify", lambda *a, **k: warned.append(a))
    w = grace_watcher(cfg, False, grace=0)
    assert w.scan_once(FakeCam(BRIGHT)) is True
    assert len(locks) == 1
    assert warned == []


def test_grace_warns_then_locks_when_still_nobody(cfg, locks, monkeypatch):
    warned = []
    monkeypatch.setattr(awaylock, "notify", lambda *a, **k: warned.append(a))
    w = grace_watcher(cfg, False)
    assert w.scan_once(FakeCam(BRIGHT)) is True
    assert len(locks) == 1
    assert len(warned) == 1 and "Locking in" in warned[0][0]


def test_grace_cancelled_when_you_come_back(cfg, locks):
    w = grace_watcher(cfg, False, True)  # empty at first, a face during the recheck
    assert w.scan_once(FakeCam(BRIGHT)) is False
    assert locks == []
    assert w.misses == 0


def test_grace_recheck_hiccup_does_not_lock(cfg, locks, monkeypatch):
    w = grace_watcher(cfg, False)
    cam = FakeCam(BRIGHT)
    calls = iter([BRIGHT, None])  # first scan fine, recheck gets no frame

    def flaky(c, tries=8):
        return next(calls)

    monkeypatch.setattr(awaylock, "best_frame", flaky)
    assert w.scan_once(cam) is False
    assert locks == []


def test_grace_skips_lock_if_paused_meanwhile(cfg, locks):
    w = grace_watcher(cfg, False, grace=0.01)
    w.active.clear()
    assert w.scan_once(FakeCam(BRIGHT)) is False
    assert locks == []


def test_grace_skips_lock_if_already_locked(cfg, locks, monkeypatch):
    monkeypatch.setattr(awaylock, "screen_locked", lambda: True)
    w = grace_watcher(cfg, False)
    assert w.scan_once(FakeCam(BRIGHT)) is False
    assert locks == []


# ---------- battery mode ----------

def fake_power(tmp_path, monkeypatch, status):
    bat = tmp_path / "power_supply" / "BAT0"
    bat.mkdir(parents=True)
    (bat / "status").write_text(status + "\n")
    real_path = awaylock.Path

    def fake(p):
        return tmp_path / "power_supply" if p == "/sys/class/power_supply" else real_path(p)

    monkeypatch.setattr(awaylock, "Path", fake)


@pytest.mark.parametrize("status,expected", [
    ("Discharging", True), ("Charging", False), ("Full", False), ("Not charging", False)])
def test_on_battery_reads_status(tmp_path, monkeypatch, status, expected):
    fake_power(tmp_path, monkeypatch, status)
    assert awaylock.on_battery() is expected


def test_on_battery_false_without_a_battery(tmp_path, monkeypatch):
    (tmp_path / "power_supply").mkdir()
    real_path = awaylock.Path
    monkeypatch.setattr(awaylock, "Path",
                        lambda p: tmp_path / "power_supply" if p == "/sys/class/power_supply" else real_path(p))
    assert awaylock.on_battery() is False


def test_battery_interval_used_only_on_battery(cfg, monkeypatch):
    w = awaylock.Watcher(dict(cfg, interval=10, battery_interval=30), FakeDetector(FACE))
    monkeypatch.setattr(awaylock, "on_battery", lambda: False)
    assert w.interval() == 10
    monkeypatch.setattr(awaylock, "on_battery", lambda: True)
    assert w.interval() == 30


def test_battery_interval_zero_means_same(cfg, monkeypatch):
    monkeypatch.setattr(awaylock, "on_battery", lambda: True)
    w = awaylock.Watcher(dict(cfg, interval=10, battery_interval=0), FakeDetector(FACE))
    assert w.interval() == 10


def test_new_flags_parse_and_validate():
    c = awaylock.resolve_config(awaylock.parse_args(["--grace", "10", "--battery-interval", "30"]))
    assert c["grace"] == 10 and c["battery_interval"] == 30


@pytest.mark.parametrize("flags", [["--grace", "-1"], ["--battery-interval", "-5"]])
def test_negative_grace_or_battery_interval_exit(flags):
    with pytest.raises(SystemExit):
        awaylock.resolve_config(awaylock.parse_args(flags))


def test_grace_recheck_uses_a_freshly_opened_camera(cfg, locks):
    released = []

    class Tracked(FakeCam):
        def release(self):
            released.append(self)

    old, fresh = Tracked(BRIGHT), Tracked(BRIGHT)
    w = grace_watcher(cfg, False)
    w.open_camera = lambda: fresh
    assert w.scan_once(old) is True
    assert old in released and fresh in released  # old closed for the wait, fresh closed after
    assert w.cam_released is True


def test_warning_popup_is_closed_after_the_wait(cfg, locks, monkeypatch):
    closed = []
    monkeypatch.setattr(awaylock, "notify", lambda *a, **k: 42)
    monkeypatch.setattr(awaylock, "close_notification", closed.append)
    w = grace_watcher(cfg, False, True)  # you come back
    w.scan_once(FakeCam(BRIGHT))
    assert closed == [42]


def test_notify_returns_id_and_falls_back_for_old_libnotify(monkeypatch):
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        if "--print-id" in cmd:
            return Result(stdout="", returncode=1)  # old notify-send rejects the flag
        return Result(stdout="", returncode=0)

    monkeypatch.undo()  # the autouse fakes would hide the real notify
    monkeypatch.setattr(awaylock.subprocess, "run", fake_run)
    assert awaylock.notify("hi", 3) is None
    assert len(calls) == 2 and "--print-id" not in calls[1]


# ---------- add-face ----------

def test_merge_owner_appends_and_handles_empty():
    old = np.ones((3, 4), dtype=np.float32)
    new = np.zeros((2, 4), dtype=np.float32)
    assert awaylock.merge_owner(old, new).shape == (5, 4)
    assert awaylock.merge_owner(None, new).shape == (2, 4)


def run_enroll_flag(monkeypatch, flag, new_samples):
    class Cam:
        def isOpened(self): return True
        def release(self): pass

    monkeypatch.setattr(awaylock.cv2, "VideoCapture", lambda *a, **k: Cam())
    monkeypatch.setattr(awaylock, "OwnerDetector", lambda cfg, owner=None: object())
    monkeypatch.setattr(awaylock, "enroll", lambda cam, det: new_samples)
    awaylock.main([flag])


def test_add_face_keeps_old_samples(monkeypatch):
    awaylock.save_owner(np.ones((4, 8), dtype=np.float32))
    run_enroll_flag(monkeypatch, "--add-face", np.zeros((3, 8), dtype=np.float32))
    assert awaylock.load_owner().shape == (7, 8)


def test_enroll_still_replaces_old_samples(monkeypatch):
    awaylock.save_owner(np.ones((4, 8), dtype=np.float32))
    run_enroll_flag(monkeypatch, "--enroll", np.zeros((3, 8), dtype=np.float32))
    assert awaylock.load_owner().shape == (3, 8)


def test_add_face_without_data_starts_fresh(monkeypatch, capsys):
    run_enroll_flag(monkeypatch, "--add-face", np.zeros((3, 8), dtype=np.float32))
    assert awaylock.load_owner().shape == (3, 8)
    assert "starts a fresh one" in capsys.readouterr().out


# ---------- tray status line ----------

def status_watcher(cfg, detector=None, **over):
    return awaylock.Watcher(dict(cfg, **over), detector or FakeDetector(FACE))


def test_status_before_first_scan_and_when_paused(cfg):
    w = status_watcher(cfg)
    assert w.status_text() == "Waiting for a scan"
    w.toggle()
    assert w.status_text() == "Paused"


def test_status_any_mode_follows_scans(cfg):
    w = status_watcher(cfg)
    w.scan_once(FakeCam(BRIGHT))
    assert w.status_text() == "Face seen"
    w.detector = FakeDetector([])
    w.scan_once(FakeCam(BRIGHT))
    assert w.status_text() == "No face seen"


def test_status_owner_mode_shows_score_and_threshold(cfg):
    det = FakeDetector(FACE)
    det.last_score = 0.823
    w = status_watcher(cfg, det, presence="owner", match_threshold=0.45)
    w.scan_once(FakeCam(BRIGHT))
    assert w.status_text() == "Match 0.82 (need 0.45)"


def test_status_owner_mode_without_a_face(cfg):
    det = FakeDetector([])
    det.last_score = None
    w = status_watcher(cfg, det, presence="owner")
    w.scan_once(FakeCam(BRIGHT))
    assert w.status_text() == "No face seen"


def test_on_update_called_after_each_scan_and_errors_dont_matter(cfg):
    w = status_watcher(cfg)
    calls = []
    w.on_update = lambda: calls.append(1)
    w.scan_once(FakeCam(BRIGHT))
    w.scan_once(FakeCam(BRIGHT))
    assert len(calls) == 2


def test_tray_module_imports_without_awaylock():
    import awaylock_tray
    assert callable(awaylock_tray.run_tray)


# ---------- owner mode is the default ----------

def test_owner_is_the_default_presence():
    assert awaylock.DEFAULTS["presence"] == "owner"


def test_presence_any_still_available():
    c = awaylock.resolve_config(awaylock.parse_args(["--presence", "any"]))
    assert c["presence"] == "any"


def test_first_run_without_terminal_explains_and_exits(cfg, monkeypatch):
    shown = []
    monkeypatch.setattr(awaylock, "notify", lambda *a, **k: shown.append(a))
    monkeypatch.setattr(awaylock.sys, "stdin", None)
    with pytest.raises(SystemExit, match="--enroll"):
        awaylock.first_run_enroll(dict(cfg, presence="owner"))
    assert shown  # the autostart case has no terminal, so the user gets a popup


def test_first_run_with_terminal_enrolls_then_continues(cfg, monkeypatch):
    class Tty:
        def isatty(self): return True

    enrolled = []
    monkeypatch.setattr(awaylock.sys, "stdin", Tty())
    monkeypatch.setattr("builtins.input", lambda prompt="": "")
    monkeypatch.setattr(awaylock, "enroll_from_camera", lambda c, add=False: enrolled.append(c))
    awaylock.first_run_enroll(dict(cfg, presence="owner"))
    assert len(enrolled) == 1


def test_start_in_owner_mode_without_face_data_goes_through_first_run(monkeypatch):
    called = []
    monkeypatch.setattr(awaylock, "first_run_enroll", lambda c: called.append(1) or (_ for _ in ()).throw(SystemExit))
    with pytest.raises(SystemExit):
        awaylock.main([])
    assert called == [1]


def test_start_in_any_mode_skips_first_run(monkeypatch):
    class Stop(Exception):
        pass

    monkeypatch.setattr(awaylock, "first_run_enroll", lambda c: pytest.fail("should not enroll"))
    monkeypatch.setattr(awaylock, "make_detector", lambda c: (_ for _ in ()).throw(Stop()))
    with pytest.raises(Stop):
        awaylock.main(["--presence", "any"])


# ---------- bad values ----------

@pytest.mark.parametrize("flags", [
    ["--interval", "nan"], ["--interval", "inf"], ["--grace", "inf"], ["--grace", "nan"],
    ["--battery-interval", "inf"], ["--camera", "-1"], ["--misses", "-2"]])
def test_nan_inf_and_negative_command_line_values_exit(flags):
    with pytest.raises(SystemExit):
        awaylock.resolve_config(awaylock.parse_args(flags))


def test_exit_message_names_the_setting():
    with pytest.raises(SystemExit, match="camera must be 0 or higher"):
        awaylock.resolve_config(awaylock.parse_args(["--camera", "-1"]))


@pytest.mark.parametrize("key,value", [
    ("interval", "abc"), ("interval", None), ("interval", True), ("interval", float("nan")),
    ("interval", -3), ("misses", 2.5), ("misses", "x"), ("camera", -1),
    ("presence", "nobody"), ("detector", 5), ("match_threshold", 7), ("grace", -1)])
def test_one_bad_saved_setting_falls_back_to_its_default(key, value, caplog):
    awaylock.CONFIG_PATH.write_text(json.dumps({"min_face": 77, key: value}))  # the bad one wins on a clash
    cfg = awaylock.load_config()
    assert cfg[key] == awaylock.DEFAULTS[key]
    assert key.replace("_", "-") in caplog.text  # and it says which one
    if key != "min_face":
        assert cfg["min_face"] == 77  # the rest of the file still counts


def test_saved_whole_number_written_as_float_is_accepted():
    awaylock.CONFIG_PATH.write_text(json.dumps({"misses": 5.0, "camera": 2.0}))
    cfg = awaylock.load_config()
    assert cfg["misses"] == 5 and isinstance(cfg["misses"], int)
    assert cfg["camera"] == 2


def test_hand_edited_config_with_text_does_not_crash_startup(capsys):
    awaylock.CONFIG_PATH.write_text('{"interval": "abc"}')
    cfg = awaylock.resolve_config(awaylock.parse_args([]))
    assert cfg["interval"] == awaylock.DEFAULTS["interval"]


# ---------- busy camera ----------

def test_busy_camera_is_reported_once_then_recovery_once(cfg, monkeypatch, caplog):
    import logging
    caplog.set_level(logging.INFO, logger="awaylock")
    w = awaylock.Watcher(dict(cfg, interval=0.01))
    attempts = []

    def open_cam():
        attempts.append(1)
        if len(attempts) <= 4:
            return None  # busy for four tries
        w.stop()
        return FakeCam(BRIGHT)

    monkeypatch.setattr(w, "open_camera", open_cam)
    w.run()
    text = caplog.text
    assert text.count("Can't open camera") == 1  # not once per try
    assert text.count("available again") == 1


def test_opencv_warnings_are_hidden_unless_verbose(monkeypatch):
    levels = []
    monkeypatch.setattr(awaylock.cv2.utils.logging, "setLogLevel", levels.append)
    awaylock.main(["--show-config"])
    assert levels == [awaylock.cv2.utils.logging.LOG_LEVEL_ERROR]
    levels.clear()
    awaylock.main(["--show-config", "-v"])
    assert levels == []
