"""Popup guard — Simplicity bot mechanism rebuilt 1:1 (POPUP_HANDLING_ANALYSIS.md).

Three layers, replacing the old template-tap reconnect handling which could not
actually clear the popups it matched:

  1. DETECT   ``connection_popup_visible()`` — the four SYSTEM popups (Another
              device / Connection lost / Client error! / rate-the-game) matched
              at a deliberately strict 0.88: a false positive costs a full game
              relaunch, a miss costs one guard interval and a relaunch anyway.
  2. RECOVER  ``boot_recovery()`` — RELAUNCH, not button taps: system popups
              cannot be dismissed inside the game (no live session behind
              them), so force-stop + monkey-relaunch is the only certain exit.
  3. DELIBERATE TAP  ``treasure_event()`` — the ONE in-game popup we act on:
              match the hammer icon on the bottom event banner, tap the chest
              4x, then Return Home.

Guard pattern (Simplicity bot_loop / one_cycle): the loop head recovers and
continues; every sub-task checks and ABORTS half-done work so the next cycle
redoes it cleanly — see ``guard_and_recover``. ``continue.png`` is intentionally
NOT here: in the original bot it is a dead local that no code ever loads or taps
(verified in the disassembly) — do not be fooled by the filename.

All hardcoded coordinates were captured on a 1600x900 screen. A different
emulator resolution needs BOTH re-captured templates in POPUP_TPL_DIR AND
converted values in the table below — nothing here auto-scales.
"""
import threading
import time
from pathlib import Path

import cv2
import numpy as np

import app_paths

# The ONE template-dir variable (project convention: backend/assets is the
# template root; popups live in their own subfolder, separate from the
# feature templates).
POPUP_TPL_DIR = Path(app_paths.ASSETS_DIR) / "popups"

TEMPLATE_FILES = ["Another_device.png", "Connection_lost.png",
                  "Client_error!.png", "rate_coc.png"]
THRESHOLD = 0.82   # measured: clean frames <= 0.32; the 2026-10-31 snow-base
                   # popup variant scored 0.839 against the banner template
                   # (semi-transparent banner blends with the background) —
                   # 0.82 catches it with a 2.5x clean-frame margin.
# Title-text templates (WHITE OPAQUE text — pixel-invariant across background
# blends, unlike the translucent banner body). Same popup family, different
# capture backgrounds; threshold 0.80 on a small text crop is still far above
# the clean-frame ceiling.
TITLE_TEMPLATES = {"Connection_lost_title.png": 0.80}

# Fixed-scale matching breaks when a template is a few % off the on-screen
# scale (a desktop-snip capture easily is — measured: the same popup scores
# ~0.6 at a 2% scale error). Fast path stays scale 1.0; only a NEAR miss pays
# for the small sweep, so the common no-popup tick costs exactly one match
# per template. Trigger 0.35 is safe by measurement: real clean frames top
# out at 0.13 against these templates. A template that does not even FIT the
# frame/crop also sweeps — down-scaling is exactly the remedy there.
_MATCH_SCALES = (1.0, 0.97, 1.03, 0.94, 1.06)
_SWEEP_TRIGGER = 0.35

# --- coordinate table (all captured on 1600x900; convert per resolution) -----
BOOT_DISMISS_TAP = (146, 487)         # load-screen popup dismiss button
POST_RECOVERY_HOME_TAP = (140, 606)   # guard pattern: back into the home base
TREASURE_TAP = (273, 643)             # treasure event banner / chest
TREASURE_HOME_TAP = (788, 751)        # Return Home button after opening
TREASURE_HAMMER_ROI = (622, 710, 964, 809)   # bottom banner strip (x1,y1,x2,y2)
TREASURE_HAMMER_THRESHOLD = 0.8

# Full-screen treasure-chest event (Skip bottom-right, "Tap!" over a locked
# chest): appears BY ITSELF right after a game restart when chests are pending
# and covers the village. Anchor = the constant Skip button, cropped from a
# real device frame (2026-11-01); measured: chest frames >= 0.96 (self 1.00),
# clean home fixtures <= 0.56.
TREASURE_CHEST_SKIP_TPL = POPUP_TPL_DIR / "treasure_chest_skip.png"
TREASURE_CHEST_SKIP_ROI = (1350, 750, 1600, 900)
TREASURE_CHEST_SKIP_THRESHOLD = 0.75
# Reward reveal between chests ("Builder Star Jar" etc.): does NOT advance on
# a chest tap — its green Continue button must be pressed. Template cropped
# from a real reward frame (2026-11-01): self-match 1.00 at (812,814), chest
# screen max 0.37.
TREASURE_CHEST_CONTINUE_TPL = POPUP_TPL_DIR / "treasure_chest_continue.png"
TREASURE_CHEST_CONTINUE_ROI = (620, 750, 1000, 880)
TREASURE_CHEST_CONTINUE_THRESHOLD = 0.75
TREASURE_CHEST_TAP = (795, 500)       # chest body under the "Tap!" hint
TREASURE_CHEST_TAPS_PER_CHEST = 4     # measured: 4 hammer taps open one chest
TREASURE_CHEST_TAP_PAUSE = 0.25       # rapid consecutive taps (user spec: liên tục)
TREASURE_CHEST_REWARD_TAP = (812, 814)  # green Continue, fixed position (measured)
TREASURE_CHEST_REWARD_SETTLE = 1.2    # break animation before the Continue tap
TREASURE_CHEST_MAX_SMASH = 60         # chest-tap budget (= 15 chests per attempt)
# Chest-count badge (bottom-left, cream digit on a dark pill): the digit reads
# 1.00 confidence at 4x upscale; reward screens have no badge (empty read).
TREASURE_CHEST_COUNTER_REGION = (20, 795, 75, 855)

COC_PACKAGE = "com.supercell.clashofclans"

# Recovery coordination: the run watchdog thread and the in-block guards both
# may fire; a relaunch takes ~15s, so whoever recovery just happened for must
# stand down while the game reboots.
_RECOVERY_LOCK = threading.Lock()
_last_recovery = 0.0
# RATE limiter (replaces the old hard 3-per-run cap): genuine connection drops
# over a long loop self-heal up to RECOVERY_MAX per window; beyond it the
# watchdog stops the run CLEANLY (a connection dying every cycle is beyond
# in-run recovery — no amount of relaunching fixes a dead network).
RECOVERY_WINDOW = 900.0   # 15 min
RECOVERY_MAX = 5          # max boot_recoveries within the window
_RECOVERY_TIMES = []      # timestamps of completed boot_recoveries


def clear_recovery_history():
    """Fresh recovery budget for a new Run (RunHub begin/stop)."""
    with _RECOVERY_LOCK:
        _RECOVERY_TIMES.clear()


def recovery_rate_exceeded():
    """True when RECOVERY_MAX boot_recoveries happened within RECOVERY_WINDOW —
    the connection drops persistently; in-run recovery is exhausted."""
    now = time.time()
    with _RECOVERY_LOCK:
        recent = [t for t in _RECOVERY_TIMES if now - t < RECOVERY_WINDOW]
    return len(recent) >= RECOVERY_MAX


def imread_unicode(path, flags=cv2.IMREAD_COLOR):
    """cv2.imread fails on non-ASCII Windows paths — decode the bytes instead."""
    try:
        data = np.fromfile(str(path), dtype=np.uint8)
        if data.size == 0:
            return None
        return cv2.imdecode(data, flags)
    except Exception:
        return None


def get_current_serial():
    """The connected device serial, else the configured one, else None."""
    try:
        from device_manager import manager
        dev = manager.device
        if dev is not None and getattr(dev, "serial", None):
            return dev.serial
    except Exception:
        pass
    try:
        from device_manager import load_settings
        return (load_settings().get("device", {}) or {}).get("serial") or None
    except Exception:
        return None


def run_adb(args):
    """One adb command (FULL arg list including ``shell``) through the project's
    connected Device — keeps the core failover/transport-recovery behaviour.
    Never raises; returns True when the command ran."""
    try:
        from device_manager import manager
        dev = manager.device
        if dev is None:
            return False
        res = dev._run_adb(list(args))
        return res is not None
    except Exception:
        return False


def tap(x, y):
    """Plain adb input tap (no humanize) — these are fixed UI buttons."""
    run_adb(["shell", "input", "tap", str(int(x)), str(int(y))])


def take_screenshot(tag):
    """Grab one frame through the project's device (adb screencap) and persist
    it under data/popup_shots/<tag>.png as a debug trail. One retry on a black
    frame (screencap occasionally returns one mid-transition). Returns the
    path, or None on any failure."""
    try:
        from device_manager import manager
        out_dir = Path(app_paths.DATA_DIR) / "popup_shots"
        for _ in range(2):
            frame = manager.capture_bgr()
            if frame is None:
                time.sleep(0.4)
                continue
            if float(frame.mean()) < 2.0:   # black frame — grab once more
                time.sleep(0.4)
                continue
            out_dir.mkdir(parents=True, exist_ok=True)
            name = tag if str(tag).endswith(".png") else f"{tag}.png"
            path = out_dir / name
            ok, buf = cv2.imencode(".png", frame)
            if not ok:
                return None
            buf.tofile(str(path))           # unicode-safe file write
            return str(path)
        return None
    except Exception:
        return None


def ensure_templates():
    """Setup check: every required template must exist in POPUP_TPL_DIR.
    Prints a clear ❌ line per missing file and returns the missing list —
    a non-empty result means the setup is incomplete and the caller stops."""
    missing = []
    for name in sorted(set(TEMPLATE_FILES) | set(TITLE_TEMPLATES)
                       | {"hammer.png", "rolling_pin.png", "Star_bonus.png"}):
        if not (POPUP_TPL_DIR / name).is_file():
            print(f"❌ Missing template: {POPUP_TPL_DIR / name}")
            missing.append(name)
    return missing


def _best_match_score(img_gray, tpl_gray, threshold, sweep_trigger=_SWEEP_TRIGGER):
    """Best TM_CCOEFF_NORMED score of a (grayscale) template over ``img_gray``,
    scale 1.0 first; a NEAR miss (sweep_trigger..threshold) triggers the small
    ``_MATCH_SCALES`` sweep. Never raises; template-bigger-than-image = 0.0."""
    try:
        def score_at(t):
            if t.shape[0] > img_gray.shape[0] or t.shape[1] > img_gray.shape[1]:
                return 0.0
            res = cv2.matchTemplate(img_gray, t, cv2.TM_CCOEFF_NORMED)
            return float(cv2.minMaxLoc(res)[1])

        fits = (tpl_gray.shape[0] <= img_gray.shape[0]
                and tpl_gray.shape[1] <= img_gray.shape[1])
        best = score_at(tpl_gray) if fits else 0.0
        if best >= threshold or (fits and best < sweep_trigger):
            return best
        # Sweep: near-miss, or the template does not fit as-is (only a smaller
        # scale can match it — e.g. a popup crop smaller than the template).
        for s in _MATCH_SCALES[1:]:
            t = cv2.resize(tpl_gray, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
            best = max(best, score_at(t))
            if best >= threshold:
                break
        return best
    except Exception:
        return 0.0


def _banner_structure_present(frame_bgr):
    """Structural backup detector, independent of ANY capture pipeline: the
    system banner is a HUGE flat mid-gray neutral panel (~995x277 at screen
    centre). Measured separation on real frames: the banner's flat-gray
    component is ~250k px while the largest such component on clean battle/
    village frames is ~53k px (and fails the position/aspect checks) — the
    120k px gate has a >2x margin on both sides. Pixel templates can miss
    when the capture pipeline differs (snip vs adb framebuffer — the 2026-10-30
    incident); geometry cannot."""
    try:
        g = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        h, w = g.shape
        b = frame_bgr[:, :, 0].astype(np.int16)
        gg = frame_bgr[:, :, 1].astype(np.int16)
        r = frame_bgr[:, :, 2].astype(np.int16)
        mask = ((g > 48) & (g < 80)
                & (np.abs(b - gg) < 14) & (np.abs(gg - r) < 14) & (np.abs(b - r) < 14)
                ).astype(np.uint8) * 255
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
        cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for c in cnts:
            x, y, cw, ch = cv2.boundingRect(c)
            if cv2.contourArea(c) < 120000 or cw < 700 or ch < 180:
                continue
            aspect = cw / max(1, ch)
            if not (2.4 <= aspect <= 4.6):
                continue
            # SOLID-panel check (tuned on the 2026-10-31 false positive): the
            # real banner fills ~70-82% of its bounding rect, while the
            # out-of-map darkness on panned battle views forms a huge SPARSE
            # mid-gray component (fill ~0.20, e.g. 143k px in a 1355x525 rect)
            # that previously fooled this detector.
            fill = cv2.contourArea(c) / max(1, cw * ch)
            if fill < 0.45:
                continue
            # a real banner floats clear of the screen edges; the out-of-map
            # darkness touches the top of the frame (y=0)
            if y <= 0.06 * h or y + ch >= 0.94 * h:
                continue
            if not (0.10 * w <= x + cw / 2 <= 0.90 * w
                    and 0.18 * h <= y + ch / 2 <= 0.82 * h):
                continue
            return True
        return False
    except Exception:
        return False


def popup_on_frame(frame_bgr, threshold=THRESHOLD):
    """Guard check on an ALREADY-CAPTURED frame (no extra screencap) — used by
    wait loops that hold a frame. Full-banner templates OR title-text templates
    OR the structural signature."""
    if frame_bgr is None:
        return False
    g = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY) if frame_bgr.ndim == 3 else frame_bgr
    for tmpl_name in TEMPLATE_FILES:
        tpl = imread_template(POPUP_TPL_DIR / tmpl_name, cv2.IMREAD_GRAYSCALE)
        if tpl is None:
            print(f"❌ Missing template: {POPUP_TPL_DIR / tmpl_name}")
            continue
        score = _best_match_score(g, tpl, threshold)
        if score >= threshold:
            print(f'[OK] Detected "{tmpl_name}" (score={score:.2f})')
            return True
    for tmpl_name, thr in TITLE_TEMPLATES.items():
        tpl = imread_template(POPUP_TPL_DIR / tmpl_name, cv2.IMREAD_GRAYSCALE)
        if tpl is None:
            print(f"❌ Missing template: {POPUP_TPL_DIR / tmpl_name}")
            continue
        score = _best_match_score(g, tpl, thr)
        if score >= thr:
            print(f'[OK] Detected "{tmpl_name}" (score={score:.2f})')
            return True
    return _banner_structure_present(frame_bgr)


def connection_popup_visible() -> bool:
    """Layer 1 — is one of the four SYSTEM popups on screen? First strict
    match wins; missing templates are reported and skipped, never fatal."""
    shot_path = take_screenshot("conn.png")
    if not shot_path:
        return False
    img = imread_unicode(shot_path, cv2.IMREAD_COLOR)
    if img is None:
        return False
    return popup_on_frame(img)


def imread_template(path, flags=cv2.IMREAD_COLOR):
    """Template loader with a tiny cache — the same PNGs are re-read on every
    guard tick otherwise. Missing/unreadable files yield None (caller warns)."""
    cached = _template_cache.get(str(path))
    if cached is not None:
        return cached
    img = imread_unicode(path, flags)
    if img is not None:
        _template_cache[str(path)] = img
    return img


_template_cache = {}


def boot_recovery():
    """Layer 2 — the ONLY recovery for the four system popups: relaunch.
    System popups have no live game session behind them, so no in-game button
    can clear them; force-stop + relaunch is certain (costs ~15s)."""
    host = get_current_serial()
    if not host:
        raise RuntimeError("No emulator selected for boot_recovery()")
    # Mark the reboot BEFORE force-stopping: an in-flight deploy checks this
    # flag per node and aborts instead of tapping into the loading screen.
    try:
        import scenario_store
        scenario_store.set_session_flag("game_rebooted", time.time())
    except Exception:
        pass
    print("🔁 Restarting Clash of Clans...")
    run_adb(["shell", "am", "force-stop", COC_PACKAGE])
    run_adb(["shell", "monkey", "-p", COC_PACKAGE,
             "-c", "android.intent.category.LAUNCHER", "1"])   # relaunch
    print("⏳ Waiting 10 seconds for game to load...")
    time.sleep(10)
    print("👆 Dismissing pop-ups…")
    tap(*BOOT_DISMISS_TAP)   # press the load-screen popup dismiss button
    global _last_recovery
    with _RECOVERY_LOCK:
        _last_recovery = time.time()
        _RECOVERY_TIMES.append(_last_recovery)
        del _RECOVERY_TIMES[:-20]   # bound the list


def recent_recovery(seconds=45):
    """True while a boot_recovery from ANY thread is still settling — guards
    and the watchdog stand down so two recoveries never interleave."""
    return (time.time() - _last_recovery) < seconds


def guard_and_recover(logger=None, abort_log="[WARN] Connection lost → recovering"):
    """One-call guard for the coc-studio loop (Simplicity guard pattern).

    Returns True when the caller must ABORT its sub-task: a system popup was
    detected and boot_recovery() ran (game is rebooting — half-done work is
    redone by the next cycle), or a recovery just happened on another thread.
    Returns False when the screen is clean."""
    if recent_recovery():
        return True
    if not connection_popup_visible():
        return False
    if logger is not None:
        logger.warning(abort_log)
    else:
        print(abort_log)
    if recovery_rate_exceeded():
        # the watchdog stops the run when the rate is hit; the guard only
        # aborts its sub-task — no relaunch storm from N call sites
        if logger is not None:
            logger.warning("[WARN] recovery rate limit hit — no more relaunches "
                           "this window; the run is being stopped.")
        return True
    boot_recovery()   # RuntimeError (no serial) intentionally propagates
    return True


def _match_template(img, tpl_path, region=None, threshold=0.8):
    """Best score of ``tpl_path`` inside ``region`` (x1,y1,x2,y2, None = whole
    frame), with the same near-miss scale sweep as the system-popup detector;
    0.0 on any failure (missing template prints a ❌ line — never raises)."""
    tpl = imread_template(tpl_path, cv2.IMREAD_GRAYSCALE)
    if tpl is None:
        print(f"❌ Missing template: {tpl_path}")
        return 0.0
    try:
        crop = img
        if region is not None:
            x1, y1, x2, y2 = region
            crop = img[y1:y2, x1:x2]
        crop_g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
        return _best_match_score(crop_g, tpl, threshold)
    except Exception:
        return 0.0


def treasure_chest_visible(frame):
    """True when the full-screen treasure-chest event overlay is up — identified
    by its constant Skip button (bottom-right corner). This screen shows by
    itself right after a game restart when chests are pending, and covers the
    home village (ensure_home used to pay a full force-stop/launch for it)."""
    if frame is None:
        return False
    return _match_template(frame, TREASURE_CHEST_SKIP_TPL,
                           region=TREASURE_CHEST_SKIP_ROI,
                           threshold=TREASURE_CHEST_SKIP_THRESHOLD) \
        >= TREASURE_CHEST_SKIP_THRESHOLD


def treasure_continue_centroid(frame):
    """Centre of the green Continue button on a reward-reveal screen, or None.
    Checked INSIDE its bottom-centre ROI — the wooden floor shares the button's
    colour family, so a colour blob search alone misfires (measured)."""
    if frame is None:
        return None
    score = _match_template(frame, TREASURE_CHEST_CONTINUE_TPL,
                            region=TREASURE_CHEST_CONTINUE_ROI,
                            threshold=TREASURE_CHEST_CONTINUE_THRESHOLD)
    if score < TREASURE_CHEST_CONTINUE_THRESHOLD:
        return None
    x1, y1, x2, y2 = TREASURE_CHEST_CONTINUE_ROI
    crop = cv2.cvtColor(frame[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
    tpl = imread_template(str(TREASURE_CHEST_CONTINUE_TPL), cv2.IMREAD_GRAYSCALE)
    if tpl is None:
        return None
    res = cv2.matchTemplate(crop, tpl, cv2.TM_CCOEFF_NORMED)
    _, _, _, ml = cv2.minMaxLoc(res)
    return (x1 + ml[0] + tpl.shape[1] // 2, y1 + ml[1] + tpl.shape[0] // 2)


def read_chest_counter(frame):
    """OCR the chest-count badge (bottom-left of the chest screen) -> int or
    None. Digit tokens below 0.5 confidence are junk-filtered; reward screens
    have no badge and read empty -> None."""
    if frame is None:
        return None
    try:
        from core.ocr import _get_reader
        x1, y1, x2, y2 = TREASURE_CHEST_COUNTER_REGION
        crop = frame[y1:y2, x1:x2]
        up = cv2.resize(crop, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
        rgb = cv2.cvtColor(up, cv2.COLOR_BGR2RGB)
        digits = ""
        for _box, text, conf in _get_reader().readtext(rgb):
            text = str(text).strip()
            if text.isdigit() and float(conf) >= 0.5:
                digits += text
        return int(digits) if digits else None
    except Exception:
        return None


def smash_treasure_chests(logger=None):
    """Open every pending chest on the full-screen chest event: tap the chest,
    wait out the smash animation, re-check — until the screen is gone or the
    bounded budget runs out. Returns the number of chest taps delivered.
    Never raises (same policy as the rest of this module)."""
    delivered = 0
    expected = None
    chests_done = 0
    try:
        # One iteration = one chest: 4 RAPID taps (no re-verification between
        # them — user spec), then the fixed Continue position for the reward
        # reveal. One screenshot per chest keeps the pace; the loop stops the
        # moment the event screen is gone (home reachable).
        for _ in range(TREASURE_CHEST_MAX_SMASH // TREASURE_CHEST_TAPS_PER_CHEST):
            shot = take_screenshot("treasure_smash")
            img = imread_unicode(shot) if shot else None
            if not treasure_chest_visible(img):
                break
            if not chests_done:
                expected = read_chest_counter(img)
                msg = (f"[treasure] counter reads {expected} chest(s) to smash."
                       if expected is not None else
                       "[treasure] counter unreadable — smashing until the screen is gone.")
                if logger is not None:
                    logger.info(msg)
                else:
                    print(msg)
            for _ in range(TREASURE_CHEST_TAPS_PER_CHEST):
                delivered += 1
                tap(*TREASURE_CHEST_TAP)
                time.sleep(TREASURE_CHEST_TAP_PAUSE)
            time.sleep(TREASURE_CHEST_REWARD_SETTLE)
            delivered += 1
            tap(*TREASURE_CHEST_REWARD_TAP)   # Continue — no-op if not on a reward
            time.sleep(1.0)
            chests_done += 1
            msg = (f"[treasure] chest {chests_done}"
                   f"{f'/{expected}' if expected is not None else ''}: "
                   f"4 taps + Continue ({delivered} taps total). . .")
            if logger is not None:
                logger.info(msg)
            else:
                print(msg)
            if expected is not None and chests_done >= expected:
                done = (f"[treasure] all {expected} counted chests smashed.")
                if logger is not None:
                    logger.info(done)
                else:
                    print(done)
                shot = take_screenshot("treasure_smash")
                img2 = imread_unicode(shot) if shot else None
                if not treasure_chest_visible(img2):
                    break                    # counter matched — event really done
                # counter stale/OCR-wrong — chests remain: fall back to the
                # anchor as the only stop condition
                msg = "[treasure] counter exhausted but chests remain — continuing until gone."
                if logger is not None:
                    logger.info(msg)
                else:
                    print(msg)
                expected = None
        done = f"[treasure] chest screen cleared after {delivered} tap(s), {chests_done} chest(s)."
        if logger is not None:
            logger.info(done)
        else:
            print(done)
    except Exception:
        pass
    return delivered


def _treasure_tool(img):
    """Which event-banner tool is shown on the bottom banner strip right now:
    (tool_name, confidence) — the STRONGER of the two known variants
    (hammer.png / rolling_pin.png; the event alternates the banner art).
    2026-11-18: hammer-only detection missed the rolling-pin variant."""
    scores = {tool: _match_template(img, POPUP_TPL_DIR / f"{tool}.png",
                                    region=TREASURE_HAMMER_ROI)
              for tool in ("hammer", "rolling_pin")}
    return max(scores.items(), key=lambda kv: kv[1])


def treasure_event():
    """Layer 3 — the one in-game popup we act on: the Treasure event banner.
    The banner tool alternates between the hammer and the rolling pin — either
    variant activates the check → tap the chest 4x, wait for the reward, then
    Return Home. Neither tool on the banner → return immediately, touching
    nothing."""
    print("Checking if treasure event is active. . .")
    shot_path = take_screenshot("treasure_event")
    if not shot_path:
        return
    time.sleep(0.2)
    img = imread_unicode(shot_path)
    if img is None:
        return
    # The full-screen chest event puts hammer art inside the banner ROI (the
    # hammer bar), which used to false-positive the banner check — check the
    # chest screen FIRST and open the chests in place instead of blind-tapping
    # the old banner coordinates.
    if treasure_chest_visible(img):
        print("Treasure chest event screen detected — smashing chests. . .")
        smash_treasure_chests()
        return
    tool, score = _treasure_tool(img)
    if score >= TREASURE_HAMMER_THRESHOLD:
        print(f"Treasure event detected ({tool} icon, conf {score:.2f}).")
        print("tapping. . . ")
        for _ in range(4):
            time.sleep(0.2)
            tap(*TREASURE_TAP)          # touch the event banner / chest
        time.sleep(4)
        print("Treasure open successfully.")
        print("Going home. . .")
        tap(*TREASURE_HOME_TAP)         # Return Home — NOT a Continue button
    # no match → return immediately, doing nothing


# --- Layer 3b: "Star Bonus received!" popup (tap the green Okay) --------------

# Gate: the popup title cropped from the user's real popup snip and rescaled
# to game scale by calibrating the snip against the REAL-scale Okay asset
# (the snip is the game rendered at 0.90; self-check 0.998). Cross-capture
# templates are unreliable at 0.88 (see the Connection_lost lesson), so the
# gate threshold is lenient — it only decides "is this popup up"; the tap
# target is verified separately. Measured clean-frame max: 0.32.
STAR_BONUS_TITLE_TPL = POPUP_TPL_DIR / "Star_bonus.png"
STAR_BONUS_TITLE_THRESHOLD = 0.62
# The tap target is the SAME green Okay button the surrender confirm uses —
# buttons/battle/okay.png is a real 1600x900 frame capture (battle-tested),
# with a colour-blob fallback in case the art ever changes.
OKAY_TPL = Path(app_paths.ASSETS_DIR) / "buttons" / "battle" / "okay.png"
STAR_BONUS_OKAY_THRESHOLD = 0.62


def _green_button_centroid(frame_bgr):
    """Fallback tap target: the largest button-green blob in the bottom band
    of the frame (the Okay button, wherever it sits) — scale-invariant,
    immune to button-art changes. The colour window is MEASURED from the real
    buttons/battle/okay.png body (H~26, S~72, V~182 — a pale yellow-green,
    NOT the saturated pure green one would guess); the window is widened a
    little around it. None when nothing big enough is found."""
    try:
        h, w = frame_bgr.shape[:2]
        band_y = int(h * 0.6)
        band = frame_bgr[band_y:, :]
        hsv = cv2.cvtColor(band, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, (15, 50, 120), (45, 255, 255))
        cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not cnts:
            return None
        c = max(cnts, key=cv2.contourArea)
        if cv2.contourArea(c) < 3000:
            return None
        m = cv2.moments(c)
        if m["m00"] == 0:
            return None
        return (int(m["m10"] / m["m00"]), int(m["m01"] / m["m00"]) + band_y)
    except Exception:
        return None


def star_bonus_visible(frame=None):
    """Layer 3 gate — is the 'Star Bonus received!' popup on screen?"""
    if frame is None:
        p = take_screenshot("star_bonus")
        if not p:
            return False
        frame = imread_unicode(p)
    if frame is None:
        return False
    g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
    title = imread_template(STAR_BONUS_TITLE_TPL, cv2.IMREAD_GRAYSCALE)
    if title is None:
        print(f"❌ Missing template: {STAR_BONUS_TITLE_TPL}")
        return False
    return _best_match_score(g, title, STAR_BONUS_TITLE_THRESHOLD) >= STAR_BONUS_TITLE_THRESHOLD


def dismiss_star_bonus(logger=None):
    """Tap the green Okay button when the 'Star Bonus received!' popup is up.
    The popup is harmless (it only blocks the screen), so this is tap-and-go —
    never a relaunch. Returns True when it tapped."""
    p = take_screenshot("star_bonus")
    if not p:
        return False
    frame = imread_unicode(p)
    if frame is None:
        return False
    g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
    title = imread_template(STAR_BONUS_TITLE_TPL, cv2.IMREAD_GRAYSCALE)
    if title is None:
        return False
    if _best_match_score(g, title, STAR_BONUS_TITLE_THRESHOLD) < STAR_BONUS_TITLE_THRESHOLD:
        return False
    msg = "[star_bonus] popup detected — tapping Okay."
    if logger is not None:
        logger.warning(msg)
    else:
        print(msg)
    loc = None
    okay = imread_template(OKAY_TPL, cv2.IMREAD_GRAYSCALE)
    if okay is not None:
        best = (0.0, None)
        for s in _MATCH_SCALES:
            t = cv2.resize(okay, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
            if t.shape[0] > g.shape[0] or t.shape[1] > g.shape[1]:
                continue
            res = cv2.matchTemplate(g, t, cv2.TM_CCOEFF_NORMED)
            _, mv, _, ml = cv2.minMaxLoc(res)
            if mv > best[0]:
                best = (float(mv), (ml, s, t.shape))
        if best[0] >= STAR_BONUS_OKAY_THRESHOLD:
            (x, y), s, (th_, tw_) = best[1]
            loc = (int(x + tw_ * s / 2), int(y + th_ * s / 2))
    if loc is None:
        loc = _green_button_centroid(frame)
    if loc is None:
        return False
    tap(*loc)
    time.sleep(2.0)
    return True
