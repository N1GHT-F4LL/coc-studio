"""Unit tests for popup_guard.py — mock screenshots/templates, no device.

Run:  cd backend && ..\\.venv\\Scripts\\python.exe tests\\test_popup_guard.py

Covers the acceptance criteria of the popup-guard spec:
  1. templates/popups structure complete; setup check reports missing names
  2. Connection_lost frame >= threshold -> True + "[OK] Detected" print; plain -> False
  3. missing template -> "❌ Missing template: ..." then continue, no crash
  4. boot_recovery: no serial -> RuntimeError; with serial -> exactly 3 adb
     commands in order (force-stop -> monkey -> tap 146 487) with sleep(10)
  5. treasure_event: hammer in ROI -> 4x tap(273,643) @0.2s -> sleep(4) ->
     tap(788,751); no hammer -> zero taps
  6. coordinates/ROI/thresholds/template paths come from module config only
  7. near-miss scale sweep; star bonus; structural detector; title template
     (snow-base variant); wait_for_end popup bail
"""
import contextlib
import inspect
import io
import logging
import os
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import popup_guard

passed = 0
failed = 0


def check(name, cond, extra=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS {name}")
    else:
        failed += 1
        print(f"  FAIL {name} {extra}")


class FakeTime:
    """Stand-in for popup_guard.time — records sleeps (advancing a fake clock),
    no real waiting; .time() feeds the recovery timestamp."""

    def __init__(self):
        self.sleeps = []
        self._t = 1000.0

    def sleep(self, s):
        self.sleeps.append(s)
        self._t += s

    def time(self):
        return self._t


def make_frame(w=1600, h=900, gray=90):
    return np.full((h, w, 3), gray, np.uint8)


def paste_template(frame, template_path, x, y):
    tpl = cv2.imread(str(template_path), cv2.IMREAD_COLOR)
    assert tpl is not None, template_path
    th, tw = tpl.shape[:2]
    frame[y:y + th, x:x + tw] = tpl
    return frame


def write_frame(frame, path):
    ok, buf = cv2.imencode(".png", frame)
    assert ok
    buf.tofile(str(path))
    return str(path)


def test_templates_structure():
    print("[1] templates/popups structure + setup check")
    missing = popup_guard.ensure_templates()
    check("all 7 templates present in POPUP_TPL_DIR", missing == [],
          f"missing={missing}")
    check("POPUP_TPL_DIR is backend/assets/popups",
          popup_guard.POPUP_TPL_DIR == Path(popup_guard.app_paths.ASSETS_DIR) / "popups",
          str(popup_guard.POPUP_TPL_DIR))
    with tempfile.TemporaryDirectory() as tmp:
        real_dir = popup_guard.POPUP_TPL_DIR
        popup_guard.POPUP_TPL_DIR = Path(tmp)
        try:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                missing = popup_guard.ensure_templates()
            check("empty dir reports all 7 missing", len(missing) == 7)
            check("each missing file printed with its path",
                  buf.getvalue().count("❌ Missing template:") == 7)
        finally:
            popup_guard.POPUP_TPL_DIR = real_dir


def test_connection_popup_visible():
    print("[2] Connection_lost frame -> True + [OK] print; plain frame -> False")
    tpl_path = popup_guard.POPUP_TPL_DIR / "Connection_lost.png"
    hit = make_frame()
    paste_template(hit, tpl_path, 300, 250)
    shots = {"hit": write_frame(hit, Path(tempfile.gettempdir()) / "pg_hit.png"),
             "plain": write_frame(make_frame(),
                                  Path(tempfile.gettempdir()) / "pg_plain.png")}
    real_ts = popup_guard.take_screenshot
    try:
        popup_guard.take_screenshot = lambda tag: shots["hit"]
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ok = popup_guard.connection_popup_visible()
        check("popup frame detected", ok is True)
        check('[OK] Detected "Connection_lost.png" printed with score',
              '[OK] Detected "Connection_lost.png" (score=' in buf.getvalue(),
              buf.getvalue()[:120])
        popup_guard.take_screenshot = lambda tag: shots["plain"]
        ok = popup_guard.connection_popup_visible()
        check("plain frame not detected", ok is False)
    finally:
        popup_guard.take_screenshot = real_ts


def test_missing_template_continues():
    print("[3] missing template -> ❌ per file, continue, no crash")
    real_dir = popup_guard.POPUP_TPL_DIR
    popup_guard._template_cache.clear()
    popup_guard.POPUP_TPL_DIR = Path(tempfile.mkdtemp())
    real_ts = popup_guard.take_screenshot
    popup_guard.take_screenshot = lambda tag: write_frame(
        make_frame(), Path(tempfile.gettempdir()) / "pg_plain2.png")
    try:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ok = popup_guard.connection_popup_visible()
        check("returns False (nothing matched)", ok is False)
        check("one ❌ line per template file (4 system + 1 title)",
              buf.getvalue().count("❌ Missing template:") == 5,
              buf.getvalue()[:200])
        check("paths printed inside templates/popups",
              str(popup_guard.POPUP_TPL_DIR) in buf.getvalue())
    finally:
        popup_guard.POPUP_TPL_DIR = real_dir
        popup_guard._template_cache.clear()
        popup_guard.take_screenshot = real_ts


def test_boot_recovery():
    print("[4] boot_recovery: no serial raises; with serial -> 3 adb cmds + sleep(10)")
    real_serial, real_adb, real_time = (popup_guard.get_current_serial,
                                        popup_guard.run_adb, popup_guard.time)
    adb_calls = []
    try:
        popup_guard.get_current_serial = lambda: None
        try:
            popup_guard.boot_recovery()
            check("no serial -> RuntimeError", False, "did not raise")
        except RuntimeError as e:
            check("RuntimeError with exact message",
                  str(e) == "No emulator selected for boot_recovery()", str(e))

        popup_guard.get_current_serial = lambda: "127.0.0.1:21503"
        popup_guard.run_adb = lambda args: adb_calls.append(list(args)) or True
        ft = FakeTime()
        popup_guard.time = ft
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            popup_guard.boot_recovery()
        check("exactly 3 adb commands", len(adb_calls) == 3, str(adb_calls))
        check("1st = force-stop", adb_calls[0] == ["shell", "am", "force-stop",
                                                   popup_guard.COC_PACKAGE])
        check("2nd = monkey relaunch",
              adb_calls[1][:3] == ["shell", "monkey", "-p"]
              and adb_calls[1][3] == popup_guard.COC_PACKAGE
              and adb_calls[1][4] == "-c"
              and adb_calls[1][5] == "android.intent.category.LAUNCHER")
        check("3rd = tap(146,487)",
              adb_calls[2] == ["shell", "input", "tap", "146", "487"])
        check("sleep(10) between relaunch and dismiss tap", ft.sleeps == [10],
              str(ft.sleeps))
        check("recovery timestamp recorded", popup_guard.recent_recovery(seconds=60))
    finally:
        popup_guard.get_current_serial = real_serial
        popup_guard.run_adb = real_adb
        popup_guard.time = real_time
        popup_guard._last_recovery = 0.0
        popup_guard._RECOVERY_TIMES.clear()


def test_treasure_event():
    print("[5] treasure_event: hammer in ROI -> 4 taps + Return Home; none -> no taps")
    hammer = popup_guard.POPUP_TPL_DIR / "hammer.png"
    hit = make_frame()
    paste_template(hit, hammer, 700, 730)          # inside ROI (622,710)-(964,809)
    shots = {"hit": write_frame(hit, Path(tempfile.gettempdir()) / "pg_treasure.png"),
             "plain": write_frame(make_frame(),
                                  Path(tempfile.gettempdir()) / "pg_notreasure.png")}
    real_ts, real_tap, real_time = (popup_guard.take_screenshot, popup_guard.tap,
                                    popup_guard.time)
    taps = []
    try:
        popup_guard.tap = lambda x, y: taps.append((x, y))
        ft = FakeTime()
        popup_guard.time = ft
        popup_guard.take_screenshot = lambda tag: shots["hit"]
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            popup_guard.treasure_event()
        check("4 chest taps then Return Home",
              taps == [(273, 643)] * 4 + [(788, 751)], str(taps))
        check("tap sleeps 0.2 x4 then settle 4",
              ft.sleeps == [0.2] + [0.2] * 4 + [4], str(ft.sleeps))
        check("flow log lines present",
              "Treasure event detected." in buf.getvalue()
              and "Treasure open successfully." in buf.getvalue())
        taps.clear()
        ft.sleeps.clear()
        popup_guard.take_screenshot = lambda tag: shots["plain"]
        with contextlib.redirect_stdout(io.StringIO()):
            popup_guard.treasure_event()
        check("no hammer -> zero taps", taps == [], str(taps))
        check("no hammer -> only the pre-match settle sleep", ft.sleeps == [0.2],
              str(ft.sleeps))
    finally:
        popup_guard.take_screenshot = real_ts
        popup_guard.tap = real_tap
        popup_guard.time = real_time


def test_treasure_chest_screen():
    print("[5b] treasure chest screen: Skip anchor detect + bounded smash loop")
    skip_tpl = cv2.imread(str(popup_guard.TREASURE_CHEST_SKIP_TPL), cv2.IMREAD_COLOR)
    assert skip_tpl is not None, "treasure_chest_skip.png missing"
    chest = make_frame()
    x1, y1, x2, y2 = popup_guard.TREASURE_CHEST_SKIP_ROI
    ch, cw = skip_tpl.shape[:2]
    chest[y2 - ch:y2, x2 - cw:x2] = skip_tpl          # paste inside the ROI corner
    shots = {"chest": write_frame(chest, Path(tempfile.gettempdir()) / "pg_chest.png"),
             "home": write_frame(make_frame(), Path(tempfile.gettempdir()) / "pg_chesthome.png")}
    real_ts, real_tap, real_time = (popup_guard.take_screenshot, popup_guard.tap,
                                    popup_guard.time)
    real_counter = popup_guard.read_chest_counter
    taps = []
    try:
        popup_guard.tap = lambda x, y: taps.append((x, y))
        ft = FakeTime()
        popup_guard.time = ft
        popup_guard.read_chest_counter = lambda img: None   # no OCR in unit tests
        popup_guard.take_screenshot = lambda tag: shots["chest"]
        check("chest frame -> visible (Skip anchor)",
              popup_guard.treasure_chest_visible(cv2.imread(shots["chest"])))
        check("plain frame -> not visible",
              not popup_guard.treasure_chest_visible(cv2.imread(shots["home"])))
        check("None frame -> not visible", not popup_guard.treasure_chest_visible(None))

        # smash: 2 chest frames then a home frame -> two 4-tap chests + rewards
        seq = {"i": 0}

        def seq_shot(tag):
            seq["i"] += 1
            return shots["chest"] if seq["i"] <= 2 else shots["home"]

        popup_guard.take_screenshot = seq_shot
        with contextlib.redirect_stdout(io.StringIO()):
            n = popup_guard.smash_treasure_chests()
        one_chest = ([popup_guard.TREASURE_CHEST_TAP]
                     * popup_guard.TREASURE_CHEST_TAPS_PER_CHEST
                     + [popup_guard.TREASURE_CHEST_REWARD_TAP])
        one_sleep = ([popup_guard.TREASURE_CHEST_TAP_PAUSE]
                     * popup_guard.TREASURE_CHEST_TAPS_PER_CHEST
                     + [popup_guard.TREASURE_CHEST_REWARD_SETTLE, 1.0])
        check("smash: 4 rapid chest taps + Continue per chest, stops when gone",
              taps == one_chest * 2, str(taps))
        check("smash returns the delivered count", n == 10, str(n))
        check("smash rhythm: rapid taps + settle + Continue",
              ft.sleeps == one_sleep * 2, str(ft.sleeps))

        # bound: chest frames forever -> stops at the chest budget
        popup_guard.take_screenshot = lambda tag: shots["chest"]
        taps.clear()
        ft.sleeps.clear()
        with contextlib.redirect_stdout(io.StringIO()):
            n = popup_guard.smash_treasure_chests()
        check("smash bounded by TREASURE_CHEST_MAX_SMASH budget",
              n == (popup_guard.TREASURE_CHEST_MAX_SMASH
                    // popup_guard.TREASURE_CHEST_TAPS_PER_CHEST
                    * (popup_guard.TREASURE_CHEST_TAPS_PER_CHEST + 1))
              and len(taps) == n, str(n))

        # treasure_event prefers the chest-screen handler over the banner taps
        seq["i"] = 0

        def seq2_shot(tag):                     # treasure_event's shot + 1 smash
            seq["i"] += 1
            return shots["chest"] if seq["i"] <= 2 else shots["home"]

        popup_guard.take_screenshot = seq2_shot
        taps.clear()
        ft.sleeps.clear()
        with contextlib.redirect_stdout(io.StringIO()):
            popup_guard.treasure_event()
        check("treasure_event: chest screen -> smash, no banner taps",
              taps == one_chest
              and ft.sleeps == [0.2] + one_sleep, f"{taps} {ft.sleeps}")

        # reward reveal entry (Skip + green Continue visible): the blind
        # Continue tap at the fixed position ends the chest group
        reward = make_frame()
        reward[y2 - ch:y2, x2 - cw:x2] = skip_tpl
        cont_tpl = cv2.imread(str(popup_guard.TREASURE_CHEST_CONTINUE_TPL),
                              cv2.IMREAD_COLOR)
        assert cont_tpl is not None, "treasure_chest_continue.png missing"
        cch, ccw = cont_tpl.shape[:2]
        # paste at the button's REAL on-screen position (702,783) so the
        # measured centroid must equal TREASURE_CHEST_REWARD_TAP
        reward[783:783 + cch, 702:702 + ccw] = cont_tpl
        shots["reward"] = write_frame(reward,
                                      Path(tempfile.gettempdir()) / "pg_chestreward.png")
        seq["i"] = 0

        def seq3_shot(tag):                     # 1 reward frame then home
            seq["i"] += 1
            return shots["reward"] if seq["i"] <= 1 else shots["home"]

        popup_guard.take_screenshot = seq3_shot
        taps.clear()
        ft.sleeps.clear()
        with contextlib.redirect_stdout(io.StringIO()):
            n = popup_guard.smash_treasure_chests()
        check("reward screen -> fixed Continue position tapped",
              n == 5 and taps == one_chest
              and taps[-1] == popup_guard.TREASURE_CHEST_REWARD_TAP, str(taps))
        # measured: the fixed position IS the Continue centroid on real frames
        popup_guard.take_screenshot = lambda tag: shots["reward"]
        check("fixed Continue position matches the real button centroid",
              popup_guard.treasure_continue_centroid(cv2.imread(shots["reward"]))
              == tuple(popup_guard.TREASURE_CHEST_REWARD_TAP))

        # counter read: target reached but chests remain -> anchor takes over
        popup_guard.read_chest_counter = lambda img: 1
        popup_guard.take_screenshot = lambda tag: shots["chest"]
        taps.clear()
        ft.sleeps.clear()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            n = popup_guard.smash_treasure_chests()
        check("counter target logged",
              "counter reads 1 chest(s) to smash." in buf.getvalue())
        check("counted-out message", "all 1 counted chests smashed." in buf.getvalue())
        check("counter exhausted -> anchor-based continue",
              "counter exhausted but chests remain" in buf.getvalue())
        check("smash continued to the budget after counted-out",
              n == (popup_guard.TREASURE_CHEST_MAX_SMASH
                    // popup_guard.TREASURE_CHEST_TAPS_PER_CHEST
                    * (popup_guard.TREASURE_CHEST_TAPS_PER_CHEST + 1)),
              str(n))
    finally:
        popup_guard.take_screenshot = real_ts
        popup_guard.tap = real_tap
        popup_guard.time = real_time
        popup_guard.read_chest_counter = real_counter


def test_config_not_hardcoded():
    print("[6] coordinates/ROI/thresholds live in module config, not function bodies")
    src_boot = inspect.getsource(popup_guard.boot_recovery)
    src_treasure = inspect.getsource(popup_guard.treasure_event)
    src_frame = inspect.getsource(popup_guard.popup_on_frame)
    check("boot_recovery: no literal 146/487",
          "146" not in src_boot and "487" not in src_boot)
    check("treasure_event: no literal 273/643/788/751/622/710/964/809",
          all(s not in src_treasure for s in
              ("273", "643", "788", "751", "622", "710", "964", "809")))
    check("popup_on_frame: no literal 0.82/0.88 threshold",
          "0.82" not in src_frame and "0.88" not in src_frame
          and "THRESHOLD" in src_frame)
    check("popup_on_frame uses POPUP_TPL_DIR", "POPUP_TPL_DIR" in src_frame)


def test_scale_sweep():
    print("[7] near-miss scale sweep: a few-% off-scale popup is still detected")
    tpl_path = popup_guard.POPUP_TPL_DIR / "Connection_lost.png"
    tpl = cv2.imread(str(tpl_path), cv2.IMREAD_COLOR)
    th, tw = tpl.shape[:2]
    for scale in (0.97, 1.03):
        frame = make_frame()
        t = cv2.resize(tpl, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        frame[250:250 + t.shape[0], 300:300 + t.shape[1]] = t
        shots = write_frame(frame, Path(tempfile.gettempdir()) / f"pg_scaled_{scale}.png")
        real_ts = popup_guard.take_screenshot
        popup_guard.take_screenshot = lambda tag, s=shots: s
        try:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                ok = popup_guard.connection_popup_visible()
            check(f"off-scale popup ({scale}) detected via sweep", ok is True,
                  buf.getvalue()[:120])
        finally:
            popup_guard.take_screenshot = real_ts


def test_star_bonus():
    print("[8] Star Bonus popup -> taps the green Okay; clean frame -> no action")
    title = cv2.imread(str(popup_guard.POPUP_TPL_DIR / "Star_bonus.png"),
                       cv2.IMREAD_COLOR)
    okay = cv2.imread(str(popup_guard.OKAY_TPL), cv2.IMREAD_COLOR)

    def build(with_okay):
        f = make_frame()
        t = cv2.resize(title, None, fx=0.97, fy=0.97)   # off-scale on purpose
        f[40:40 + t.shape[0], 450:450 + t.shape[1]] = t
        if with_okay:
            f[739:739 + okay.shape[0], 549:549 + okay.shape[1]] = okay
        return f

    real_ts, real_tap, real_time = (popup_guard.take_screenshot, popup_guard.tap,
                                    popup_guard.time)
    taps = []
    try:
        popup_guard.tap = lambda x, y: taps.append((x, y))
        ft = FakeTime()
        popup_guard.time = ft
        popup_guard.take_screenshot = lambda tag: write_frame(
            build(True), Path(tempfile.gettempdir()) / "pg_starbonus.png")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ok = popup_guard.dismiss_star_bonus()
        check("popup + Okay -> dismissed (True)", ok is True)
        check("tapped the Okay button centre", len(taps) == 1
              and abs(taps[0][0] - 705) <= 3 and abs(taps[0][1] - 815) <= 3,
              str(taps))
        check("settle sleep 2.0 recorded", ft.sleeps == [2.0], str(ft.sleeps))
        check("[star_bonus] log line printed", "[star_bonus] popup detected" in buf.getvalue())

        # fallback path: title up but NO Okay art (e.g. changed button) ->
        # colour-blob fallback still taps the big button (colour = the REAL
        # Okay body colour measured from buttons/battle/okay.png: BGR
        # (130,175,182) = HSV H26 S72 V182 pale yellow-green)
        fb = make_frame()
        t = cv2.resize(title, None, fx=0.97, fy=0.97)
        fb[40:40 + t.shape[0], 450:450 + t.shape[1]] = t
        cv2.rectangle(fb, (580, 760), (820, 870), (130, 175, 182), -1)
        popup_guard.take_screenshot = lambda tag: write_frame(
            fb, Path(tempfile.gettempdir()) / "pg_starbonus_fb.png")
        taps.clear()
        ok = popup_guard.dismiss_star_bonus()
        check("green-blob fallback taps when Okay art is absent",
              ok is True and len(taps) == 1 and 680 <= taps[0][0] <= 720, str(taps))

        popup_guard.take_screenshot = lambda tag: write_frame(
            make_frame(), Path(tempfile.gettempdir()) / "pg_nostar.png")
        taps.clear()
        ok = popup_guard.dismiss_star_bonus()
        check("clean frame -> no action", ok is False and taps == [], str(taps))
    finally:
        popup_guard.take_screenshot = real_ts
        popup_guard.tap = real_tap
        popup_guard.time = real_time


def test_structural_detector():
    print("[9] structural banner detector: geometry beats any capture pipeline")
    banner = cv2.imread(str(popup_guard.POPUP_TPL_DIR / "Connection_lost.png"))
    # paste the game-scale banner onto a green field -> structural must fire
    f = make_frame()
    bh, bw = banner.shape[:2]
    f[345:345 + bh, 300:300 + bw] = banner
    check("banner frame -> structural fires", popup_guard._banner_structure_present(f))
    check("popup_on_frame (template OR structure) fires", popup_guard.popup_on_frame(f))
    # a flat full-screen gray-60 region: fails the aspect/position checks
    f2 = np.full((900, 1600, 3), 60, np.uint8)
    check("full-screen flat gray -> NOT a popup (aspect reject)",
          not popup_guard._banner_structure_present(f2))
    check("plain frame -> silent", not popup_guard.popup_on_frame(make_frame()))
    # the real live frame (no popup) stays silent
    conn = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "data", "popup_shots", "conn.png")
    if os.path.exists(conn):
        img = cv2.imread(conn)
        check("live conn.png (no popup) -> silent", not popup_guard.popup_on_frame(img))
    # THE 2026-10-31 regression: the out-of-map darkness on a panned battle
    # view (sparse mid-gray, touches the screen top) must NOT fire
    fp = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "_calib", "false_positive_frame_1031.png")
    if os.path.exists(fp):
        img = cv2.imread(fp)
        check("false-positive battle frame -> structural silent",
              not popup_guard._banner_structure_present(img))
        check("false-positive frame -> full guard silent",
              not popup_guard.popup_on_frame(img))
    else:
        print("  (skip — _calib/false_positive_frame_1031.png not present)")


class FakeUI:
    """Minimal ui_manager stub for BattleScreen.wait_for_end."""

    def __init__(self, frame):
        self._frame = frame
        self.sleeps = []

    def get_screen(self):
        return self._frame

    def _stopped(self):
        return False

    def _poll_sleep(self, s):
        self.sleeps.append(s)


def test_title_template_snow_variant():
    print("[11] title-text template: the snow-base popup variant (window-stretched) fires")
    fp = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "_calib", "snowbase_frame_1101.png")
    if not os.path.exists(fp):
        print("  (skip — _calib/snowbase_frame_1101.png not present)")
        return
    img = cv2.imread(fp)
    check("title template fires on the stretched snow-base variant",
          popup_guard.popup_on_frame(img) is True)
    check("plain frame stays silent", not popup_guard.popup_on_frame(make_frame()))


def test_recovery_rate_limiter():
    print("[12] recovery rate limiter: 5 relaunches/15min then clean-stop signal")
    real_serial, real_adb, real_time = (popup_guard.get_current_serial,
                                        popup_guard.run_adb, popup_guard.time)
    try:
        popup_guard.get_current_serial = lambda: "127.0.0.1:21503"
        popup_guard.run_adb = lambda args: True
        ft = FakeTime()
        popup_guard.time = ft
        popup_guard._RECOVERY_TIMES.clear()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            for _ in range(5):
                popup_guard.boot_recovery()
        check("rate exceeded after RECOVERY_MAX relaunches",
              popup_guard.recovery_rate_exceeded() is True)
        # an old relaunch outside the window does not count
        ft._t += popup_guard.RECOVERY_WINDOW + 1
        check("rate clears after the window passes",
              popup_guard.recovery_rate_exceeded() is False)
        ft._t = 1000.0
        popup_guard._RECOVERY_TIMES.clear()

        # guard_and_recover with the rate exceeded: aborts (True) but must NOT
        # boot_recovery again (no relaunch storm from N call sites)
        boot_calls = []
        popup_guard.boot_recovery = lambda: boot_calls.append(1) or True
        popup_guard.take_screenshot = lambda tag: write_frame(
            make_frame(), Path(tempfile.gettempdir()) / "pg_rate.png")
        popup_guard._RECOVERY_TIMES.append(ft.time() - 1)   # 1 recent relaunch
        # make the rate look exceeded: 5 entries within the window
        popup_guard._RECOVERY_TIMES.extend(ft.time() - 2 for _ in range(4))
        ok = popup_guard.guard_and_recover(None)
        check("rate-exceeded guard aborts without relaunching",
              ok is True and boot_calls == [], str(boot_calls))
        popup_guard._RECOVERY_TIMES.clear()
    finally:
        popup_guard.get_current_serial = real_serial
        popup_guard.run_adb = real_adb
        popup_guard.time = real_time
        popup_guard._RECOVERY_TIMES.clear()
        popup_guard._last_recovery = 0.0


def test_wait_for_end_popup_bail():
    print("[10] wait_for_end bails in seconds when a popup freezes the battle")
    from screens.battle_screen import BattleScreen
    banner = cv2.imread(str(popup_guard.POPUP_TPL_DIR / "Connection_lost.png"))
    f = make_frame()
    bh, bw = banner.shape[:2]
    f[345:345 + bh, 300:300 + bw] = banner
    ui = FakeUI(f)
    bs = BattleScreen(ui)
    logs = io.StringIO()
    handler = logging.StreamHandler(logs)
    lg = logging.getLogger("screens.battle_screen")
    old = lg.level
    lg.setLevel(logging.INFO)
    lg.addHandler(handler)
    import time as _time
    try:
        t0 = _time.monotonic()
        loc = bs.wait_for_end(timeout=180)
        elapsed = _time.monotonic() - t0
    finally:
        lg.removeHandler(handler)
        lg.setLevel(old)
    check("returns None fast instead of waiting 180s", loc is None and elapsed < 5.0,
          f"elapsed={elapsed:.1f}s")
    check("bail reason logged", "[BATTLE] system popup — tier 1: app restart now" in logs.getvalue())


if __name__ == "__main__":
    test_templates_structure()
    test_connection_popup_visible()
    test_missing_template_continues()
    test_boot_recovery()
    test_treasure_event()
    test_treasure_chest_screen()
    test_config_not_hardcoded()
    test_scale_sweep()
    test_star_bonus()
    test_structural_detector()
    test_title_template_snow_variant()
    test_recovery_rate_limiter()
    test_wait_for_end_popup_bail()
    print(f"\n=== {passed} passed, {failed} failed ===")
    sys.exit(1 if failed else 0)
