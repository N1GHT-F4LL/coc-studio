"""Multi-Village — Supercell ID rotation on a single MEmu instance.

Design (2026-11-15/16): several Supercell ID accounts are signed in on one
device; the bot rotates farming between them on a time schedule.

FLAG_SECURE architecture: every screen past the blue swap button (Supercell ID
page, account list) cannot be captured via adb — screencap returns the frame
BENEATH the overlay. But the user's desktop DOES show those pages, so the
switch flow uses DESKTOP SELF-CAPTURES (mss on the MEmu window region) as its
eyes: the account row is located BY NAME via OCR on the self-capture, then
tapped at its live position — immune to scroll drift, list order changes, and
newly added accounts.

The desktop<->device mapping is DERIVED at the settings-panel checkpoint (an
adb-visible screen: the adb frame and the desktop capture show the same
content) by geometric verification on five known UI regions (Battle + Build
buttons + three resource icons) — GetWindowRect is NOT trusted (the window
moves; a stale rect was the mapping-failure cause).

Machine checkpoints: the Settings panel template (adb), the mapping (5/5
geometric), the post-switch home verification + the wrong-village identity
check (adb, after the overlay closes during the village load).

Rules:
  - coordinates live in data/multi_village.json (never hardcoded here);
  - never raise across the module boundary; never press BACK on home;
  - single-village mode (enabled=false) is untouched;
  - a village is a context: switching also applies that village's saved
    scenario + farm thresholds into the live run settings.
"""
import ctypes
import json
import logging
import os
import threading
import time

import app_paths
import popup_guard
from device_manager import manager

logger = logging.getLogger(__name__)

CONFIG_PATH = os.path.join(app_paths.DATA_DIR, "multi_village.json")
MV_DIR = os.path.join(app_paths.DATA_DIR, "multi_village")
SCID_DIR = os.path.join(app_paths.ASSETS_DIR, "scid")   # per-village SCID row faces (v<idx>.png)
STATS_DIR = app_paths.DATA_DIR
WAIT_HOME_TIMEOUT = 180          # account switch + full game reload
INTERVAL_OPTIONS = {"30 minutes": 30, "1 hour": 60, "1.5 hours": 90, "2 hours": 120}
SETTINGS_TAB_TEMPLATE = os.path.join(app_paths.ASSETS_DIR, "multi_village", "settings_tab.png")
SETTINGS_TAB_THRESHOLD = 0.8
SERIAL_FALLBACK = "127.0.0.1:21503"

# --- popup-coverage gate (2026-11-21 incident) ------------------------------
# Reward/welcome dialogs ("Welcome Back Chief!", "Raid Weekend Results", ...)
# cover the home screen right after a switch. A frame with one up is MEANINGLESS
# as an identity reference — the 2026-11-21 cascade: 7 of 9 home_v*.png
# references were popup-covered frames, so every genuinely-successful switch
# failed verify_village_identity ("WRONG VILLAGE") and the whole rotation died.
# Detector = template match (vision scale sweep) of the green Okay button
# (bottom band — these dialogs all sit their button there) OR the generic
# popup X. Measured on the 9 real references: covered frames score
# okay>=0.60 / close>=0.81; clean home frames <=0.42 / <=0.54.
POPUP_OKAY_KEY = "buttons/battle/okay"
POPUP_CLOSE_KEY = "buttons/popup/btn_close"
POPUP_OKAY_GATE = 0.52
POPUP_CLOSE_GATE = 0.65
POPUP_BAND_Y = 500          # okay buttons live in the bottom band (y >= this)
# Identity decision margin: the expected village's snapshot must beat the best
# other by at least this much (same-village re-visit noise is ~2-5; different
# villages sit 30+ apart on the 160x90 signature). 2026-11-23: relaxed 3.0 ->
# 1.5 — village 1's look drifted until its OWN reference scored ~32.8 while
# the next village sat at ~35.6, and the 3.0 margin rejected the CORRECT
# landing by 0.2 (the settle-retry saved it by luck). The argmin rule still
# rejects real wrong landings (their frame matches the WRONG village's ref
# closely, so expected >> best_other), and the avatar arbitration remains the
# second line for stale-reference ties.
IDENTITY_MARGIN = 1.5
# After the SCID row tap the switch must ACTUALLY start before wait_home may
# trust adb: while the FLAG_SECURE overlay is open, screencap shows the OLD
# village beneath it, so wait_home "verified home" instantly on every silently
# failed switch (2026-11-21). Evidence of a real switch = the adb frame changes
# decisively (overlay closes -> game loading screen).
SWITCH_START_TIMEOUT = 25.0
SWITCH_START_DIFF = 15.0

user32 = ctypes.windll.user32

_lock = threading.Lock()
_state = {
    "active_village_idx": None,   # the village the editor/session is pointed at
    "current_village_idx": None,  # the village the bot is actually farming
    "last_switch_ts": 0.0,
}
_state_loaded = False


def _load_runtime_state():
    """current_village_idx/last_switch_ts survive a backend restart via the
    config's runtime key — the game keeps the last account until a switch."""
    global _state_loaded
    if _state_loaded:
        return
    _state_loaded = True
    try:
        cfg = load_config()
        rt = cfg.get("runtime") or {}
        if rt.get("current_village_idx") is not None:
            _state["current_village_idx"] = rt["current_village_idx"]
            _state["last_switch_ts"] = float(rt.get("last_switch_ts", 0.0))
    except Exception as e:
        logger.warning("[MV] runtime state restore failed: %s", e)


def _persist_runtime_state():
    with _lock:
        cfg = load_config()
        cfg["runtime"] = {
            "current_village_idx": _state["current_village_idx"],
            "last_switch_ts": _state["last_switch_ts"],
        }
        save_config(cfg)


# --- config -----------------------------------------------------------

def load_config():
    """Tolerant read: missing file -> a fresh default skeleton."""
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {
            "enabled": False,
            "interval_option": "30 minutes", "interval_mins": 30,
            "villages": [], "coords": {},
        }


def save_config(cfg):
    os.makedirs(app_paths.DATA_DIR, exist_ok=True)
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    os.replace(tmp, CONFIG_PATH)


def village(cfg, idx):
    for v in cfg.get("villages", []):
        if v.get("idx") == idx:
            return v
    return None


def enabled_villages(cfg):
    """Rotation targets: enabled AND configured. `confirmed` (a verified
    one-time Apply switch) is NOT required — the user's flow saves configs
    without it (2026-11-16); every switch itself verifies the account via
    wait_home + the wrong-village identity check, and the first successful
    switch captures the village's home snapshot."""
    return [v for v in cfg.get("villages", [])
            if v.get("enabled") and v.get("config")]


def get_state():
    """Runtime state snapshot — lazily restores the persisted
    current_village_idx/last_switch_ts FIRST, so a fresh backend never
    "assumes" the first enabled village while the game is actually on
    another one (2026-11-21: the restart after the chest incident re-assumed
    village 3 over a persisted village 6; the settings-verify mismatch then
    burned a corrective switch every restart)."""
    _load_runtime_state()
    with _lock:
        return dict(_state)


def set_active_village_idx(idx):
    with _lock:
        _state["active_village_idx"] = idx


def config_exists(idx):
    v = village(load_config(), idx)
    return bool(v and isinstance(v.get("config"), dict))


def interval_seconds(cfg):
    mins = cfg.get("interval_mins")
    if not isinstance(mins, (int, float)) or mins <= 0:
        mins = INTERVAL_OPTIONS.get(cfg.get("interval_option"), 30)
    return float(mins) * 60.0


def due_for_switch(cfg=None, now=None):
    """True when multi-village is enabled, the village set is usable, and the
    interval has elapsed since the last switch."""
    _load_runtime_state()
    cfg = cfg or load_config()
    if not cfg.get("enabled"):
        return False
    if not enabled_villages(cfg):
        return False
    with _lock:
        last = _state["last_switch_ts"]
        current = _state["current_village_idx"]
    if current is None:
        return False                  # first cycle: bot stays on its startup village
    now = time.time() if now is None else now
    return (now - last) >= interval_seconds(cfg)


# --- stats ------------------------------------------------------------

def stats_path(idx):
    return os.path.join(STATS_DIR, f"stats_v{idx}.json")


def load_stats(idx):
    try:
        with open(stats_path(idx), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"cycles": 0, "switches": 0, "last_cycle_ts": 0.0}


def note_cycle(idx):
    """One farm cycle completed on village idx."""
    st = load_stats(idx)
    st["cycles"] = st.get("cycles", 0) + 1
    st["last_cycle_ts"] = time.time()
    with open(stats_path(idx), "w", encoding="utf-8") as f:
        json.dump(st, f, indent=2)


def note_switch(idx):
    st = load_stats(idx)
    st["switches"] = st.get("switches", 0) + 1
    with open(stats_path(idx), "w", encoding="utf-8") as f:
        json.dump(st, f, indent=2)


def reset_all_stats():
    import glob
    for p in glob.glob(os.path.join(STATS_DIR, "stats_v*.json")):
        try:
            os.remove(p)
        except OSError:
            pass


# --- device + desktop primitives (never raise) ------------------------

def _device():
    dev = manager.device
    if dev is None or not getattr(dev, "connected", False):
        return None
    return dev


def _tap(x, y):
    dev = _device()
    if dev is None:
        logger.warning("[MV] device not connected — tap (%s, %s) skipped", x, y)
        return False
    try:
        dev._run_adb(["shell", "input", "tap", str(int(x)), str(int(y))])
        return True
    except Exception as e:
        logger.warning("[MV] tap (%s, %s) failed: %s", x, y, e)
        return False


def _swipe(x, y1, y2, ms=400):
    """Scroll inside the SCID account list (adb swipe — input injection works
    on FLAG_SECURE pages; only screencap is blocked)."""
    dev = _device()
    if dev is None:
        logger.warning("[MV] device not connected — swipe skipped")
        return False
    try:
        dev._run_adb(["shell", "input", "swipe", str(int(x)), str(int(y1)),
                      str(int(x)), str(int(y2)), str(int(ms))])
        return True
    except Exception as e:
        logger.warning("[MV] swipe failed: %s", e)
        return False


def _screencap():
    """adb screencap via direct subprocess — dev._run_adb decodes stdout as
    text and CRASHES on the binary PNG stream (measured 2026-11-16)."""
    dev = _device()
    serial = getattr(dev, "serial", None) if dev else None
    if not serial:
        serial = SERIAL_FALLBACK
    try:
        import cv2
        import numpy as np
        import subprocess as sp
        p = sp.run(["adb", "-s", str(serial), "exec-out", "screencap", "-p"],
                   capture_output=True, stdin=sp.DEVNULL, timeout=30)
        if p.returncode != 0 or not p.stdout:
            return None
        return cv2.imdecode(np.frombuffer(p.stdout, np.uint8), cv2.IMREAD_COLOR)
    except Exception as e:
        logger.warning("[MV] screencap failed: %s", e)
        return None


def _sleep(seconds):
    time.sleep(seconds)


# --- desktop self-capture (the eyes for FLAG_SECURE pages) -------------

hwnd = None


def _find_memu_window():
    """hwnd + rect of the MEmu window (DPI-aware physical pixels)."""
    import ctypes.wintypes as wt
    global hwnd
    hwnd = None

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def cb(h, _):
        global hwnd
        if user32.IsWindowVisible(h):
            buf = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(h, buf, 256)
            if buf.value == 'MEmu':
                hwnd = h
        return True
    user32.EnumWindows(cb, 0)
    if hwnd is None:
        return None, None
    rect = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return hwnd, (rect.left, rect.top, rect.right, rect.bottom)


def _window_is_top(hwnd):
    """True when the point at the window's centre hits ``hwnd`` (or a child of
    it — the game renders in a child window). Read-only probe
    (WindowFromPoint — no input injection, no focus change)."""
    import ctypes.wintypes as wt
    try:
        rect = wt.RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return False
        cx = (rect.left + rect.right) // 2
        cy = (rect.top + rect.bottom) // 2
        top = user32.WindowFromPoint(wt.POINT(cx, cy))
        return bool(top) and (top == hwnd or user32.IsChild(hwnd, top))
    except Exception:
        return True   # cannot probe — keep the old lenient behaviour


def _covering_window(hwnd):
    """Root window of whatever covers ``hwnd`` at its centre (the one hiding
    the game view), or None when MEmu is already on top. Read-only probe
    (WindowFromPoint + GetAncestor GA_ROOT)."""
    import ctypes.wintypes as wt
    try:
        rect = wt.RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return None
        cx = (rect.left + rect.right) // 2
        cy = (rect.top + rect.bottom) // 2
        top = user32.WindowFromPoint(wt.POINT(cx, cy))
        if not top or top == hwnd or user32.IsChild(hwnd, top):
            return None
        return user32.GetAncestor(top, 2) or top   # 2 = GA_ROOT
    except Exception:
        return None


def _raise_window_visible(tries=1, spacing=15.0):
    """Make sure the MEmu window is UNCOVERED for the desktop self-capture —
    WITHOUT touching keyboard focus. HARD RULE since 2026-11-17: this module
    must never inject keys or steal the host foreground — the old ALT-key
    keybd_event trick + AttachThreadInput fallback wedged the host keyboard
    system-wide and the user had to restart Windows. The self-capture only
    needs the window on TOP (visible pixels), not FOCUSED: a TOPMOST bump
    raises it above everything with SWP_NOACTIVATE (focus stays wherever the
    user is typing), and the immediate NOTOPMOST returns it to the normal
    z-band so other windows can still cover it afterwards.

    Returns True when MEmu verifies UNCOVERED, False only when the game stays
    genuinely covered after ``tries`` attempts spaced ``spacing`` seconds
    apart. MEmu runs ELEVATED, so UIPI silently refuses our SetWindowPos on
    MEmu itself (the bump's return value alone is NEVER a failure signal —
    only the on-top probe decides). Two recoveries beyond the bump:
      - TRANSIENT covers (a console flash, a dragging window — 2026-11-23
        02:18 cost a whole 60-min window because one probe miss failed the
        window instantly) clear on their own: the caller may pass
        ``tries>1`` for a bounded re-probe loop.
      - PERSISTENT covers: the covering window (if non-elevated — a parked
        dashboard/browser) is LOWERED to the bottom of the z-order with
        SWP_NOACTIVATE (no focus move, same allowed z-order class as the
        bump). An elevated cover cannot be lowered — fail-fast with guidance.

    Callers treat False like the minimized case: fail the window fast with
    guidance instead of burning restarts."""
    SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE = 0x0001, 0x0002, 0x0010
    HWND_TOPMOST, HWND_NOTOPMOST, HWND_BOTTOM = -1, -2, 1
    flags = SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE
    lowered_cover = False
    for attempt in range(1, int(tries) + 1):
        hwnd, _rect = _find_memu_window()
        if hwnd is None:
            return False
        if user32.IsIconic(hwnd):
            # A minimized window has NO render surface to capture — it MUST be
            # restored, and Win32 has no reliable no-activation restore. This
            # moves the foreground ONCE (a focus move cannot corrupt the input
            # stack — the keyboard wedge came exclusively from keybd_event /
            # AttachThreadInput, which are banned from this module and fenced
            # by tests).
            logger.info("[MV] MEmu is minimized — restoring (activates the window "
                        "once; NO key injection involved).")
            user32.ShowWindow(hwnd, 9)   # SW_RESTORE
            deadline = time.time() + 5
            while user32.IsIconic(hwnd) and time.time() < deadline:
                time.sleep(0.3)
            time.sleep(1.0)              # let the restore animation settle
        if _window_is_top(hwnd):
            return True                  # already uncovered — no bump needed
        user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, flags)
        user32.SetWindowPos(hwnd, HWND_NOTOPMOST, 0, 0, 0, 0, flags)
        if _window_is_top(hwnd):
            return True                  # the bump raised it (non-elevated MEmu)
        cover = _covering_window(hwnd)
        if cover is not None:
            ok = bool(user32.SetWindowPos(cover, HWND_BOTTOM, 0, 0, 0, 0, flags))
            if ok and _window_is_top(hwnd):
                logger.warning("[MV] MEmu was covered by another window — lowered "
                               "it to the bottom of the z-order to uncover the "
                               "game view (no focus change).")
                return True
            if ok:
                lowered_cover = True   # lowered something but MEmu still covered
        if attempt < int(tries):
            _sleep(float(spacing))     # a transient cover may clear on its own
    logger.error(
        "[MV] MEmu window CANNOT be uncovered after %d attempt(s) (something is "
        "on top of the game view and SetWindowPos is refused - MEmu runs "
        "ELEVATED, UIPI silently blocks our raise%s). Move/un-cover the MEmu "
        "window, or de-elevate MEmu (tray Exit + shortcut uncheck 'Run as "
        "administrator'); the next rotation window retries.",
        int(tries),
        "; the covering window was lowered but something else still covers the "
        "game" if lowered_cover else "")
    return False


def _selfcap():
    """Desktop capture around the MEmu window region (mss) — sees through
    FLAG_SECURE overlays: the desktop compositor is not subject to the
    adb screencap block. The window is brought to the front first and the
    rect is re-read every call (a stale rect was the mapping-failure cause).
    The grab is EXPANDED by a margin (clamped to the virtual screen) so edge
    regions (Build button) keep matching headroom even when the game fills
    the window exactly — 2026-11-17 incident. Before grabbing, the rect must
    read the SAME twice in a row: a freshly restored/moved window is still
    animating and a capture mid-flight puts the content at a shifted rect
    (that dead-locked the first switch of every session)."""
    import mss
    import numpy as np
    _raise_window_visible()
    # Wait for a SANE + STABLE rect. A MINIMIZED window reports the classic
    # -32000 rect (grabbing it exploded into width=-25361); a freshly restored
    # window may still be animating (rect vs content shifted = mapping fail).
    prev = None
    rect = None
    deadline = time.time() + 8
    while time.time() < deadline:
        hwnd, rect = _find_memu_window()
        if hwnd is None or rect is None:
            logger.warning("[MV] MEmu window not found for self-capture.")
            return None
        l, t, r, b = rect
        sane = (r - l > 200 and b - t > 200 and l > -10000 and t > -10000)
        if sane and rect == prev:
            break
        prev = rect
        time.sleep(0.5)
    else:
        logger.warning("[MV] MEmu window rect never sane/stable (minimized or "
                       "moving?) — self-capture aborted.")
        return None
    l, t, r, b = rect
    MARGIN = 80
    vsx = user32.GetSystemMetrics(76)      # SM_XVIRTUALSCREEN
    vsy = user32.GetSystemMetrics(77)      # SM_YVIRTUALSCREEN
    vsw = user32.GetSystemMetrics(78)      # SM_CXVIRTUALSCREEN
    vsh = user32.GetSystemMetrics(79)      # SM_CYVIRTUALSCREEN
    l = max(vsx, l - MARGIN)
    t = max(vsy, t - MARGIN)
    r = min(vsx + vsw, r + MARGIN)
    b = min(vsy + vsh, b + MARGIN)
    if r - l <= 0 or b - t <= 0:
        logger.warning("[MV] expanded capture region is empty (rect %s) — aborted.", (rect,))
        return None
    mon = {'left': l, 'top': t, 'width': r - l, 'height': b - t}
    try:
        with mss.mss() as sct:
            img = np.array(sct.grab(mon))[:, :, :3]
        return img
    except Exception as e:
        logger.warning("[MV] self-capture grab failed (%s) — aborted.", e)
        return None


def _verify_region(cg, ag, ox, oy, s, rect, margin=(40, 30), min_visible=0.5):
    """Match one reference region at its PREDICTED position (centre-based
    window, clip-tolerant). Returns (conf, cx, cy) in capture coords or None.

    2026-11-17 incident fixes: the old window [px-40, px+40+tw] treated the
    predicted centre as a LEFT edge, so any template wider than 80 px (Build:
    200 px) could never verify; and a region touching the capture edge (the
    game filling the window exactly clips Build's right 2 px) was dropped as
    OOB -> 4/5 -> every switch failed. Now: centre-based window clipped to the
    capture; when the capture clips the region, the template is cropped to its
    visible part and matched there."""
    import cv2
    x1, y1, x2, y2 = rect
    tp_full = ag[y1:y2, x1:x2]
    th, tw = tp_full.shape[:2]
    dcx, dcy = (x1 + x2) / 2, (y1 + y2) / 2
    px = ox + s * dcx          # predicted centre in capture coords
    py = oy + s * dcy
    pw, ph = tw * s, th * s    # predicted size in capture px
    rx1, ry1 = px - pw / 2, py - ph / 2
    rx2, ry2 = px + pw / 2, py + ph / 2
    vx1, vy1 = max(rx1, 0.0), max(ry1, 0.0)
    vx2 = min(rx2, float(cg.shape[1]))
    vy2 = min(ry2, float(cg.shape[0]))
    if vx2 - vx1 < 8 or vy2 - vy1 < 8:
        return None
    if (vx2 - vx1) * (vy2 - vy1) < min_visible * pw * ph:
        return None             # more than half the region is off-capture
    # crop the template (adb px) to the visible span
    tx1 = int(round((vx1 - rx1) / s))
    ty1 = int(round((vy1 - ry1) / s))
    tx2 = tw - int(round((rx2 - vx2) / s))
    ty2 = th - int(round((ry2 - vy2) / s))
    tp = tp_full[ty1:ty2, tx1:tx2]
    if tp.shape[0] < 8 or tp.shape[1] < 8:
        return None
    mx, my = margin
    wx1 = int(max(0, vx1 - mx))
    wy1 = int(max(0, vy1 - my))
    wx2 = int(min(cg.shape[1], vx2 + mx))
    wy2 = int(min(cg.shape[0], vy2 + my))
    win = cg[wy1:wy2, wx1:wx2]
    if win.shape[0] < tp.shape[0] or win.shape[1] < tp.shape[1]:
        return None
    rr = cv2.matchTemplate(win, tp, cv2.TM_CCOEFF_NORMED)
    _, c2, _, ml2 = cv2.minMaxLoc(rr)
    if c2 < 0.6:
        return None
    return (c2, wx1 + ml2[0] + tp.shape[1] / 2, wy1 + ml2[1] + tp.shape[0] / 2)


def _derive_mapping(cap, adb):
    """Desktop capture + adb frame of the SAME adb-visible screen ->
    (scale, ox, oy) such that device(x, y) = (ox, oy) + scale * desktop(x, y).

    Geometric verification (the mv_map_tool method — robust where per-region
    best-match false-locks): the Battle button anchors a scale hypothesis; the
    other four regions (Build + 3 resource icons) must match at positions
    PREDICTED by that hypothesis. The mapping is trusted when the anchor AND
    >=3 of the other 4 regions verify (>=4/5 — 2026-11-17: the Build button is
    physically clipped by the capture edge when the game fills the window
    exactly, so the old hard 5/5 dead-locked EVERY switch). A stale
    GetWindowRect (the window moved) or a covered window still fails here.
    """
    import cv2
    cg = cv2.cvtColor(cap, cv2.COLOR_BGR2GRAY)
    ag = cv2.cvtColor(adb, cv2.COLOR_BGR2GRAY)
    refs = {
        'anchor_battle': (20, 730, 235, 900),   # Battle button bottom-left
        'build': (1400, 730, 1600, 900),        # Build button bottom-right
        'icon_gold': (1530, 25, 1595, 65),      # resource icons top-right
        'icon_elixir': (1530, 82, 1595, 120),
        'icon_dark': (1505, 130, 1570, 168),
    }
    ax1, ay1, ax2, ay2 = refs['anchor_battle']
    anchor_tpl = ag[ay1:ay2, ax1:ax2]
    anchor_dev = ((ax1 + ax2) / 2, (ay1 + ay2) / 2)

    best = None
    for i in range(101):
        s = round(0.50 + 0.008 * i, 3)
        t = cv2.resize(anchor_tpl, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
        th, tw = t.shape[:2]
        if th >= cg.shape[0] or tw >= cg.shape[1]:
            continue
        r = cv2.matchTemplate(cg, t, cv2.TM_CCOEFF_NORMED)
        _, c, _, ml = cv2.minMaxLoc(r)
        if c < 0.6:
            continue
        s_ox = (ml[0] + s * (ax2 - ax1) / 2) - s * anchor_dev[0]
        s_oy = (ml[1] + s * (ay2 - ay1) / 2) - s * anchor_dev[1]
        verified = {'anchor_battle': (c, ml[0] + s * (ax2 - ax1) / 2,
                                      ml[1] + s * (ay2 - ay1) / 2)}
        for key, rect in refs.items():
            if key == 'anchor_battle':
                continue
            res = _verify_region(cg, ag, s_ox, s_oy, s, rect)
            if res is not None:
                verified[key] = res
        cand = (len(verified), s, s_ox, s_oy, verified)
        score = (cand[0], sum(v[0] for v in cand[4].values()))
        if best is None or score > (best[0], sum(v[0] for v in best[4].values())):
            best = cand
    if best is None or best[0] < 4:
        logger.warning("[MV] mapping derivation failed — fewer than 4/5 regions "
                       "verified (the MEmu window may be moved/covered).")
        try:
            dbg = r'C:/Users/antoinenguyen_09/Downloads/coc-studio/calib'
            os.makedirs(dbg, exist_ok=True)
            cv2.imwrite(dbg + '/mv_mapfail_cap.png', cap)
            cv2.imwrite(dbg + '/mv_mapfail_adb.png', adb)
            logger.warning('[MV] failure frames saved to calib/mv_mapfail_*.png')
        except Exception:
            pass
        return None
    n_ok, scale, ox, oy, verified = best
    logger.info("[MV] mapping derived: %d/5 regions, scale %.3f offset (%.0f, %.0f)",
                n_ok, scale, ox, oy)
    return scale, ox, oy


def _sleep(seconds):
    time.sleep(seconds)


# --- the switch flow ---------------------------------------------------

def _verify_settings_panel():
    """The ONE adb-verifiable checkpoint of the prefix: the Settings tab is
    visible on the opened panel (template cut from a real frame of this
    device). Past the swap button everything is FLAG_SECURE."""
    import cv2
    tpl = cv2.imread(SETTINGS_TAB_TEMPLATE, cv2.IMREAD_GRAYSCALE)
    if tpl is None:
        logger.error("[MV] missing template %s — cut it from a real frame first "
                     "(see calib/mv_map_tool.py)", SETTINGS_TAB_TEMPLATE)
        return False
    frame = _screencap()
    if frame is None:
        logger.warning("[MV] no frame to verify the Settings panel")
        return False
    g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    import cv2 as _cv
    res = _cv.matchTemplate(g, tpl, _cv.TM_CCOEFF_NORMED)
    _, c, _, _ = _cv.minMaxLoc(res)
    ok = c >= SETTINGS_TAB_THRESHOLD
    logger.info("[MV] settings-tab check: %.3f (threshold %.2f) -> %s",
                c, SETTINGS_TAB_THRESHOLD, "panel open" if ok else "panel NOT open")
    return ok


def close_settings():
    """Close the Settings panel via the calibrated red X (never BACK — BACK on
    home opens the Confirm Exit dialog)."""
    cfg = load_config()
    x, y = cfg.get("coords", {}).get("settings_close_x", (1382, 68))
    logger.info("[MV] closing Settings panel via X (%s, %s)", x, y)
    _tap(x, y)
    _sleep(1.5)


def open_switcher():
    """The verified prefix to the Supercell ID account page:
    SCID hut -> Settings tab (adb template VERIFY) -> derive the desktop
    self-capture mapping at this adb-visible checkpoint -> swap button.

    Returns (True, mapping) with mapping = (scale, ox, oy) so the FLAG_SECURE
    pages beyond the swap can be read through desktop self-captures, or
    (False, None) on any failure (after closing the panel)."""
    cfg = load_config()
    c = cfg.get("coords", {})
    hut, tab, swap = c.get("scid_hut"), c.get("settings_tab"), c.get("swap_button")
    if not (hut and tab and swap):
        logger.error("[MV] scid_hut/settings_tab/swap_button not calibrated")
        return False, None
    logger.info("[MV] opening switcher: hut %s -> settings tab %s", hut, tab)
    # The chest overlay can pop between the previous cycle's checks and this
    # tap (late award animation) — clear it or every tap lands on the event.
    _clear_chest_overlay_if_up()
    if not _tap(*hut):
        return False, None
    _sleep(2.5)
    if not _tap(*tab):
        return False, None
    _sleep(1.5)
    if not _verify_settings_panel():
        # 2026-11-21 cascade: a leftover reward dialog from the PREVIOUS
        # switch blocked the hut tap and every later village was excluded
        # on the spot. Sweep (home-gated — a still-open FLAG_SECURE overlay
        # is never swept blindly) and retry the hut->tab prefix once.
        _sweep_popups_if_home()
        if not _tap(*hut):
            return False, None
        _sleep(2.5)
        if not _tap(*tab):
            return False, None
        _sleep(1.5)
        if not _verify_settings_panel():
            close_settings()
            return False, None
    # derive the desktop->device mapping HERE: the settings panel is
    # adb-visible, so the adb frame and the desktop self-capture show the
    # same screen — the mapping then holds for the FLAG_SECURE pages beyond.
    # ONE retry: the first capture after a restore/foreground switch can catch
    # the window mid-transition (2026-11-17) — a retry after a settle always
    # derives cleanly; a persistent failure (moved/covered window) fails both.
    cap = _selfcap()
    adb = _screencap()
    mapping = _derive_mapping(cap, adb) if (cap is not None and adb is not None) else None
    if mapping is None:
        logger.warning("[MV] mapping attempt 1 failed — one retry after a settle.")
        _sleep(2.0)
        cap = _selfcap()
        adb = _screencap()
        mapping = _derive_mapping(cap, adb) if (cap is not None and adb is not None) else None
    if mapping is None:
        close_settings()
        return False, None
    logger.info("[MV] Settings panel verified — tapping swap button %s", swap)
    if not _tap(*swap):
        return False, None
    _sleep(3.0)
    # Past this point the Supercell ID page is FLAG_SECURE: the derived
    # mapping + desktop self-captures are the only eyes.
    return True, mapping


def _norm_name(a):
    """Normalized account name for matching: lowercase, alphanumerics only."""
    import re as _re
    return _re.sub(r'[^a-z0-9]', '', str(a).lower())


def _name_similarity(a, b):
    """Fuzzy account-name match: normalization + exact-containment + ratio.
    OCR noise ('you nokw' for 'you know') must still match."""
    import difflib
    na = _norm_name(a)
    nb = _norm_name(b)
    if not na or not nb:
        return 0.0
    if na == nb or na in nb or nb in na:
        return 1.0
    return difflib.SequenceMatcher(None, na, nb).ratio()


def _ocr_scid_accounts(cap, mapping):
    """OCR the SCID account-list page from a desktop self-capture -> the
    visible account rows as [(device_x, device_y, display_name)] + whether
    the 'Log in to Supercell ID' terminator row is visible. Each account row
    shows BOTH its Supercell-assigned name and the user-set village name —
    both lines carry the row's tap position, so both are returned."""
    import cv2
    from core.ocr import _get_reader
    s, ox, oy = mapping
    cg = cv2.cvtColor(cap, cv2.COLOR_BGR2GRAY)
    rx1 = max(0, int(ox + s * 1000))
    rx2 = min(cap.shape[1], int(ox + s * 1600) + 30)
    ry1 = max(0, int(oy + s * 100))
    panel = cap[ry1:, rx1:rx2]
    items = _get_reader().readtext(cv2.cvtColor(panel, cv2.COLOR_BGR2RGB),
                                   detail=1, paragraph=False)
    rows = []
    terminator = False
    for b, t, cf in items:
        t = str(t).strip()
        if not t or float(cf) < 0.35 or len(b) < 2:
            continue
        try:
            xs = [pt[0] for pt in b]
            ys = [pt[1] for pt in b]
        except Exception:
            continue
        tl = t.lower()
        if 'log in to supercell' in tl:
            terminator = True
            continue
        if tl in ('id', 'other ids', 'switch id', 'supercell id', 'supercell',
                  'settings', 'inbox', 'my profile', 'my clan', 'clans',
                  'social', 'open'):
            continue   # panel chrome / game UI, not account rows
        # easyocr boxes are relative to the CROP — add the crop origin before
        # converting capture->device (2026-11-17: the missing offset made every
        # tap point land near the screen's left edge, ~1100 px off the row)
        dcx = ((min(xs) + max(xs)) / 2 + rx1 - ox) / s
        dcy = ((min(ys) + max(ys)) / 2 + ry1 - oy) / s
        rows.append((dcx, dcy, t))
    return rows, terminator


def scid_face_path(idx):
    return os.path.join(SCID_DIR, f"v{idx}.png")


def _ensure_scid_cached(idx):
    """Hot-load a village's SCID row face into vision.cache (mirrors
    train_screen._ensure_asset_cached — a face captured mid-run works without
    a backend restart). load_assets also picks it up at the next start."""
    from core.vision import vision
    key = f"scid/v{idx}"
    if key in vision.cache:
        return
    path = scid_face_path(idx)
    if not os.path.isfile(path):
        return
    import cv2
    img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    if img is not None:
        vision.cache[key] = img


def _open_settings_panel():
    """Village screen -> SCID hut -> Settings tab, verified by the
    settings_tab template (adb-visible). No swap — the caller inspects the
    panel then closes it via close_settings(). Returns True/False."""
    cfg = load_config()
    c = cfg.get("coords", {})
    hut, tab = c.get("scid_hut"), c.get("settings_tab")
    if not (hut and tab):
        logger.error("[MV] scid_hut/settings_tab not calibrated — cannot open Settings.")
        return False
    _tap(*hut)
    _sleep(2.5)
    _tap(*tab)
    _sleep(1.5)
    return _verify_settings_panel()


def settings_verify_face(idx):
    """Confirm the CURRENT logged-in account is village idx by opening the
    Settings panel and matching the village's avatar face
    (assets/scid/v<idx>.png, cropped by the user from the same panel) on the
    live frame (user 2026-11-19 — runs every rotation-enabled cycle BEFORE
    ensure_home detects home; a mismatch means the device sits on the WRONG
    account and the caller switches back).

    Returns "match" / "mismatch" / "skip" ("skip" = the state could not be
    determined — not on the village screen, panel did not open, no face
    captured — the caller logs and moves on; never restarts, never raises)."""
    from screens.home_screen import HomeScreen
    if manager.ui_manager is None:
        logger.info("[MV] settings verify skipped — no device session.")
        return "skip"
    if not HomeScreen(manager.ui_manager).is_current_screen():
        logger.info("[MV] settings verify skipped — the game is not on the village screen.")
        return "skip"
    if not _open_settings_panel():
        logger.warning("[MV] settings verify skipped — the Settings panel did not open.")
        return "skip"
    frame = _screencap()
    if frame is None:
        close_settings()
        logger.warning("[MV] settings verify skipped — no frame of the Settings panel.")
        return "skip"
    _ensure_scid_cached(idx)
    key = f"scid/v{idx}"
    matched = False
    try:
        import cv2
        from core.vision import vision as _v
        tpl = _v.cache.get(key)
        if tpl is not None:
            g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
            res = cv2.matchTemplate(g, tpl, cv2.TM_CCOEFF_NORMED)
            _, best, _, ml = cv2.minMaxLoc(res)
            matched = best >= 0.7
            logger.info("[MV] settings verify: village %s avatar conf %.2f at %s -> %s.",
                        idx, best, ml, "MATCH" if matched else "no match")
        else:
            logger.warning("[MV] settings verify: no avatar face assets/scid/v%d.png.", idx)
    except Exception as e:
        logger.warning("[MV] settings verify match failed (%s).", e)
    close_settings()
    return "match" if matched else "mismatch"


def _locate_scid_face(cap, idx, mapping, threshold=0.7):
    """Template-match village idx's captured SCID row face on a self-capture
    frame (user 2026-11-19 — the Train Army roster-face pattern: a pre-cropped
    image of the exact row beats OCR-by-name for a known account; the OCR
    path stays as the fallback for villages without a captured face).

    Returns the DEVICE tap point (x, y), or None. The match position is in
    SELF-CAPTURE coords (window rect + the +/-80 margin) — converted to device
    coords through the mapping, the same conversion the OCR path applies; a
    tap without this conversion lands off by the window's on-screen offset
    (2026-11-19 coordinate bug caught before it shipped). A match outside the
    SCID list column is a mapping/coordinate bug -> ignored, never tapped."""
    import cv2
    from core.vision import vision
    _ensure_scid_cached(idx)
    key = f"scid/v{idx}"
    tpl = vision.cache.get(key)
    if tpl is None:
        return None
    g = cv2.cvtColor(cap, cv2.COLOR_BGR2GRAY) if cap.ndim == 3 else cap
    res = cv2.matchTemplate(g, tpl, cv2.TM_CCOEFF_NORMED)
    _, best, _, ml = cv2.minMaxLoc(res)
    if best < threshold:
        return None
    th, tw = tpl.shape[:2]
    scale, ox, oy = mapping
    dx = (ml[0] + tw // 2 - ox) / scale
    dy = (ml[1] + th // 2 - oy) / scale
    if not (900 <= dx <= 1550 and 150 <= dy <= 880):
        # a match outside the row column is the SCID page's "current account"
        # banner (top-left) or a mapping/coordinate bug — never tapped. Keep
        # the frame for post-mortem instead of guessing blind.
        logger.warning("[MV] scid face for village %s matched at implausible device "
                       "point (%.0f, %.0f) — ignored (row column is x900-1550).", idx, dx, dy)
        try:
            os.makedirs(r'calib', exist_ok=True)
            cv2.imwrite(os.path.join('calib', f'mv_scid_reject_{idx}.png'), cap)
        except Exception:
            pass
        return None
    return (int(dx), int(dy))


def _locate_account_row(cap, target_name, mapping, min_sim=0.6, other_names=()):
    """Find the target account's tap point on a SCID page self-capture.
    Returns (device_x, device_y, matched_name, similarity) or None.

    2026-11-21: an EXACT normalized match wins immediately. The fuzzy
    fallback REFUSES a row whose name is (near-)exactly ANOTHER village's
    name — the old containment rule scored 'nghia' vs 'Nghiays' at 1.00 and
    tapped village 2's row when switching to village 5 (a real wrong-village
    switch). Refused rows make the caller scroll on / abort cleanly."""
    rows, _term = _ocr_scid_accounts(cap, mapping)
    tnorm = _norm_name(target_name)
    if not tnorm:
        return None
    for dx, dy, name in rows:
        if _norm_name(name) == tnorm:
            return dx, dy, name, 1.0
    best = None
    for dx, dy, name in rows:
        sim = _name_similarity(target_name, name)
        if best is None or sim > best[3]:
            best = (name, dx, dy, sim)
    if best is None or best[3] < min_sim:
        return None
    bnorm = _norm_name(best[0])
    for other in other_names:
        onorm = _norm_name(other)
        if not onorm or onorm == tnorm:
            continue
        if bnorm == onorm or _name_similarity(best[0], other) > best[3] + 0.05:
            logger.warning(
                "[MV] OCR row %r also matches village %r — ambiguous, not tapping.",
                best[0], other)
            return None
    return best[1], best[2], best[0], best[3]


def _frame_popup_scores(frame):
    """(okay_score, close_score) — template match of the green Okay button
    (searched in the bottom band where these dialogs sit it) and the generic
    popup X, using the vision scale sweep. (0.0, 0.0) when nothing can be
    matched. Never raises."""
    import cv2
    from core.vision import vision as _vision, DEFAULT_MATCH_SCALES
    if frame is None:
        return 0.0, 0.0
    try:
        g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
        out = []
        for key, band in ((POPUP_OKAY_KEY, POPUP_BAND_Y), (POPUP_CLOSE_KEY, 0)):
            tpl = _vision.cache.get(key)
            if tpl is None:
                out.append(0.0)
                continue
            g2 = g
            if band:
                g2 = g.copy()
                g2[:band, :] = 0   # confine the search to the bottom band
            best = 0.0
            for s in DEFAULT_MATCH_SCALES:
                nh, nw = int(tpl.shape[0] * s), int(tpl.shape[1] * s)
                if nh < 8 or nw < 8 or nh > g2.shape[0] or nw > g2.shape[1]:
                    continue
                t = tpl if s == 1.0 else cv2.resize(
                    tpl, (nw, nh), interpolation=cv2.INTER_AREA)
                res = cv2.matchTemplate(g2, t, cv2.TM_CCOEFF_NORMED)
                best = max(best, float(cv2.minMaxLoc(res)[1]))
            out.append(best)
        return out[0], out[1]
    except Exception:
        return 0.0, 0.0


def _frame_clean(frame):
    """True when NO reward/welcome dialog covers the frame (popup-coverage
    gate — thresholds calibrated on the 9 real references, see the constants)."""
    okay, close = _frame_popup_scores(frame)
    if okay >= POPUP_OKAY_GATE or close >= POPUP_CLOSE_GATE:
        logger.info("[MV] frame is popup-covered (okay %.2f >= %.2f or close %.2f >= %.2f).",
                    okay, POPUP_OKAY_GATE, close, POPUP_CLOSE_GATE)
        return False
    return True


def _home_detected():
    """Strict home-village check on a fresh adb frame (None when there is no
    device session)."""
    from screens.home_screen import HomeScreen
    ui = manager.ui_manager
    if ui is None:
        return False
    try:
        return HomeScreen(ui).is_current_screen()
    except Exception:
        return False


def _run_stopped():
    """Cooperative-stop probe for the switch-flow waits (no ui_manager -> not
    stopped; the caller proceeds and wait_home handles the rest)."""
    try:
        ui = manager.ui_manager
        return ui is not None and ui._stopped()
    except Exception:
        return False


def _clear_chest_overlay_if_up():
    """The full-screen treasure-chest event can pop AFTER return_home's own
    check (the chest-award animation finishes late) — landing right on top of
    the village just as the rotation starts. Every switcher tap then lands on
    the event screen and the whole rotation window dies on "panel NOT open"
    (2026-11-21 01:05: all four villages failed one window this way — the same
    root cause as the morning's village-6 instant exclusion).

    ONE smash pass clears exactly ONE chest: after its reward reveal the
    NEXT pending chest's overlay pops 1-3s later — the smash loop's 1s
    re-check catches the transition and reports "screen cleared" while more
    chests remain (2026-11-23 02:22: every switch attempt smashed one chest,
    hut-tapped the re-popped overlay and died; 0.331 settings-tab signature).
    So: smash, then keep re-checking until the Skip anchor has stayed gone
    for TWO consecutive checks (or the bounded budget runs out). No-op when
    the overlay is not up at all."""
    try:
        frame = _screencap()
        if frame is None or not popup_guard.treasure_chest_visible(frame):
            return False
        logger.warning("[MV] treasure-chest event screen up — smashing chests in "
                       "place before the switch (until the event stays gone).")
        popup_guard.smash_treasure_chests(logger)
        gone_streak = 0
        for _ in range(12):
            _sleep(3.0)
            frame = _screencap()
            if frame is not None and popup_guard.treasure_chest_visible(frame):
                gone_streak = 0
                popup_guard.smash_treasure_chests(logger)
            else:
                gone_streak += 1
                if gone_streak >= 2:
                    return True
        logger.warning("[MV] chest event did not stay gone after the budget — "
                       "the switch attempt proceeds anyway (open_switcher's "
                       "retry + tier-2 restart remain as backstops).")
        return True
    except Exception as e:
        logger.warning("[MV] chest-overlay pre-clear failed: %s", e)
        return False


def _sweep_popups_if_home():
    """Sweep blocking dialogs, but ONLY when the adb frame verifies as the home
    village. A still-open FLAG_SECURE overlay shows the old village beneath —
    sweeping then could tap THROUGH the overlay at template positions. The
    treasure-chest overlay is handled FIRST (its own Skip-anchor gate; the
    smash taps land on the event screen itself — safe)."""
    if _clear_chest_overlay_if_up():
        return True
    if _home_detected():
        _dismiss_welcome_popups()
        return True
    return False


def _capture_home_snapshot(idx):
    """Persist home_v{idx}.png once (the identity reference for later switches).

    2026-11-21: only a CLEAN frame is accepted — the old code wrote whatever
    was on screen, and the auto-pass first switch baked popup-covered frames
    ("Welcome Back Chief!" / "Raid Weekend Results") in as permanent identity
    references, which then failed every later switch."""
    os.makedirs(MV_DIR, exist_ok=True)
    path = os.path.join(MV_DIR, f"home_v{idx}.png")
    if os.path.isfile(path):
        return
    for _attempt in range(3):
        frame = _screencap()
        if frame is None:
            _sleep(1.0)
            continue
        if not _home_detected():
            logger.warning("[MV] home snapshot for village %s deferred — not on the "
                           "home village.", idx)
            return
        if not _frame_clean(frame):
            logger.warning("[MV] home snapshot for village %s blocked by a dialog — "
                           "sweeping and retrying.", idx)
            _dismiss_welcome_popups()
            continue
        import cv2
        cv2.imwrite(path, frame)
        logger.info("[MV] home snapshot saved: home_v%s.png", idx)
        return
    logger.warning("[MV] home snapshot for village %s NOT saved — the screen never "
                   "went clean within 3 attempts.", idx)


def _dismiss_welcome_popups(rounds=10):
    """After a switch, sequential reward/welcome dialogs cover the home screen
    ("Welcome Back Chief!", "Raid Weekend Results", ...). Each round taps the
    dialog's green Okay when found, else its X button; stops the moment a
    round finds neither (clean home).

    2026-11-21 incident fixes, both measured on the corrupted references:
      - the old loop tapped okay.png at threshold 0.7, but the welcome
        dialogs' Okay matches that asset at only ~0.62 (different size than
        the battle Okay) — it NEVER tapped them, and the popup-covered frame
        was then baked in as the village's identity reference;
      - "Raid Weekend Results" has NO Okay at all (Back/Next/X), so an
        okay-only sweep could never clear it;
      - 4 rounds were not enough for the sequential popup chains.
    The tap thresholds come from the reference calibration (clean home
    frames top out at 0.42 / 0.54 — a tap only fires on a real dialog)."""
    for _ in range(int(rounds)):
        frame = _screencap()
        if frame is None:
            _sleep(1.0)
            continue
        import cv2
        from core.vision import vision as _vision, DEFAULT_MATCH_SCALES
        g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame

        def _best(key, band):
            tpl = _vision.cache.get(key)
            if tpl is None:
                return 0.0, None
            g2 = g
            if band:
                g2 = g.copy()
                g2[:band, :] = 0
            best = (0.0, None)
            for s in DEFAULT_MATCH_SCALES:
                nh, nw = int(tpl.shape[0] * s), int(tpl.shape[1] * s)
                if nh < 8 or nw < 8 or nh > g2.shape[0] or nw > g2.shape[1]:
                    continue
                t = tpl if s == 1.0 else cv2.resize(
                    tpl, (nw, nh), interpolation=cv2.INTER_AREA)
                res = cv2.matchTemplate(g2, t, cv2.TM_CCOEFF_NORMED)
                _, mv_, _, ml = cv2.minMaxLoc(res)
                if mv_ > best[0]:
                    best = (float(mv_), (ml[0] + nw // 2, ml[1] + nh // 2))
            return best

        okay_score, okay_loc = _best(POPUP_OKAY_KEY, POPUP_BAND_Y)
        if okay_score >= POPUP_OKAY_GATE and okay_loc is not None:
            logger.info("[MV] dismissing Okay dialog at %s (conf %.2f)...",
                        okay_loc, okay_score)
            _tap(*okay_loc)
            _sleep(2.0)
            continue
        close_score, close_loc = _best(POPUP_CLOSE_KEY, 0)
        if close_score >= POPUP_CLOSE_GATE and close_loc is not None:
            logger.info("[MV] dismissing X-close popup at %s (conf %.2f)...",
                        close_loc, close_score)
            _tap(*close_loc)
            _sleep(1.5)
            continue
        return True   # a round found nothing dismissable — the screen is clean
    logger.warning("[MV] popup sweep exhausted %d rounds — dialogs may remain.", rounds)
    return False


def _switch_left_home(timeout=SWITCH_START_TIMEOUT):
    """Gate between the SCID row tap and wait_home: the switch must ACTUALLY
    start. While the FLAG_SECURE SCID overlay is open, adb screencap shows the
    OLD village beneath it — wait_home would instantly "verify home" on every
    silently-failed switch (row tap did nothing / a confirm dialog is up) and
    the identity check would then judge a stale frame (2026-11-21 incident).

    Evidence that the switch started = the adb frame CHANGES decisively
    (the overlay closes and the game shows its loading screen): signature
    diff >= SWITCH_START_DIFF vs the pre-tap frame, or the home anchors
    vanishing. Returns False (failed switch) when the frame stays unchanged
    home for ``timeout`` seconds. Unobservable (no session / no frame) ->
    True — wait_home keeps its old behaviour."""
    ui = manager.ui_manager
    if ui is None:
        return True
    base = _screencap()
    if base is None:
        return True
    import numpy as np
    base_sig = _village_signature(base)
    was_home = _home_detected()
    deadline = time.time() + float(timeout)
    while time.time() < deadline:
        if getattr(ui, "_stopped", lambda: False)():
            return False
        frame = _screencap()
        if frame is not None:
            diff = float(np.mean(np.abs(_village_signature(frame) - base_sig)))
            if diff >= SWITCH_START_DIFF:
                logger.info("[MV] switch started (frame changed, diff %.1f).", diff)
                return True
            if was_home and not _home_detected():
                return True
        _sleep(1.0)
    logger.error("[MV] switch did NOT start within %.0fs (SCID overlay still up "
                 "or the row tap did nothing) — treating as a failed switch.", timeout)
    return False


def _close_scid_page():
    """Best-effort close of an open SCID page after a failed locate / switch
    start: tap the calibrated close X (coords.scid_close_x). The overlay
    intercepts injected taps, so this works even though adb cannot SEE the
    page. Never raises; never presses BACK."""
    try:
        cx = load_config().get("coords", {}).get("scid_close_x")
        if not cx:
            logger.warning("[MV] scid_close_x not calibrated — cannot close the "
                           "SCID page; the next attempt's restart will clean up.")
            return
        logger.info("[MV] closing the SCID page via X %s.", tuple(cx))
        _tap(int(cx[0]), int(cx[1]))
        _sleep(1.5)
    except Exception as e:
        logger.warning("[MV] SCID page close failed: %s", e)


def _village_signature(frame):
    """Coarse grayscale signature of a home frame (160x90) — cheap and robust
    enough to tell two different villages apart (different building layouts)."""
    import cv2
    import numpy as np
    small = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (160, 90))
    return small.astype(np.float32)


def verify_village_identity(idx, frame=None):
    """Wrong-village safeguard: the post-switch home frame must resemble THIS
    village's home_v{idx}.png snapshot more than any OTHER village's snapshot.

    Popup-corrupted references (2026-11-21 incident: 7/9 references were
    "Welcome Back Chief!" / "Raid Weekend Results" frames, so every correct
    switch failed) are EXCLUDED from scoring; the expected village's corrupted
    reference is additionally renamed to *.corrupt_*.bak so the caller's
    _capture_home_snapshot writes a clean one on this very visit (self-heal —
    no manual file surgery needed). Popup-covered "other" references are only
    skipped, not renamed (each village heals on its own next visit).

    Returns (ok, best_other, scores). Missing/unusable snapshot for idx ->
    (True, None, scores) — the landing cannot be proven either way this visit.
    """
    import cv2
    import glob
    import numpy as np
    frame = frame if frame is not None else _screencap()
    if frame is None:
        logger.warning("[MV] identity check skipped (no frame).")
        return True, None, {}
    cur = _village_signature(frame)
    scores = {}
    for path in glob.glob(os.path.join(MV_DIR, "home_v*.png")):
        stem = os.path.splitext(os.path.basename(path))[0]   # home_v<idx>
        try:
            j = int(stem.split("v")[1])
        except ValueError:
            continue
        ref = cv2.imread(path)
        if ref is None:
            continue
        if not _frame_clean(ref):
            logger.warning("[MV] identity reference home_v%s.png is popup-covered "
                           "(corrupted 2026-11-21-style) — excluded from scoring.", j)
            if j == idx:
                backup = f"{path}.corrupt_{time.strftime('%Y%m%d_%H%M%S')}.bak"
                try:
                    os.replace(path, backup)
                    logger.warning("[MV] corrupted reference moved to %s — a clean one "
                                   "is captured right after this check (self-heal).", backup)
                except OSError as e:
                    logger.warning("[MV] could not move the corrupted reference: %s", e)
            continue
        scores[j] = float(np.mean(np.abs(cur - _village_signature(ref))))
    if idx not in scores and not scores:
        return True, None, scores
    expected = scores.get(idx)
    others = {j: s for j, s in scores.items() if j != idx}
    if expected is None:
        # no usable snapshot for the expected village (first visit, or the
        # corrupted reference was just healed) — cannot prove identity
        logger.info("[MV] identity check: no usable snapshot for village %s "
                    "(first visit or healed reference).", idx)
        return True, None, scores
    best_other = min(others.items(), key=lambda kv: kv[1]) if others else None
    if best_other is not None and expected > best_other[1] - IDENTITY_MARGIN:
        logger.error(
            "[MV] WRONG VILLAGE — landed on %s (other-score %.1f vs expected %.1f; "
            "all: %s).",
            best_other[0], best_other[1], expected,
            {j: round(s, 1) for j, s in sorted(scores.items())})
        return False, best_other, scores
    logger.info("[MV] identity check ok: village %s (diff %.1f vs other %.1f).",
                idx, expected, best_other[1] if best_other else -1.0)
    return True, best_other, scores


def wait_home(timeout=WAIT_HOME_TIMEOUT):
    """Poll the post-switch home verification (the only screencap-able screen)."""
    from screens.home_screen import HomeScreen
    ui = manager.ui_manager
    if ui is None:
        return False
    home = HomeScreen(ui)
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if home.is_current_screen():
                logger.info("[MV] home screen verified after switch.")
                return True
        except Exception as e:
            logger.warning("[MV] home check failed: %s", e)
        _sleep(3.0)
    logger.warning("[MV] home NOT verified within %ss.", timeout)
    return False


def _capture_ready():
    """True when the MEmu window can actually be captured (restored + sane
    rect). A minimized window has no render surface; and when MEmu runs
    ELEVATED, UIPI silently blocks our ShowWindow/SetWindowPos — Windows'
    security boundary, not a bug. The caller must abort with clear guidance
    instead of burning restarts on it (2026-11-17)."""
    hwnd, rect = _find_memu_window()
    if hwnd is None:
        return False
    if user32.IsIconic(hwnd):
        return False
    l, t, r, b = rect
    return (r - l > 200 and b - t > 200 and l > -10000 and t > -10000)


def switch_to_village(idx):
    """Switch the game to village idx via the Supercell ID account page.

    The account row is located BY NAME through desktop self-capture OCR
    (FLAG_SECURE pages are invisible to adb but visible on the user's
    screen) — immune to scroll drift, list order changes, and newly added
    accounts. There is NO confirmation dialog for already-authorized
    accounts: tapping the row starts the switch directly (measured
    2026-11-16 — the SUPERCELL splash appears immediately).

    Returns True only after the post-switch home verification + the
    wrong-village identity check. Never raises; never presses BACK on home
    (the Confirm Exit dialog's Cancel sits at exit_dialog_cancel if it ever
    appears).
    """
    try:
        cfg = load_config()
        c = cfg.get("coords", {})
        if c.get("scid_switch_id") is None:
            logger.error("[MV] scid_switch_id not calibrated — cannot switch.")
            return False
        raised = _raise_window_visible(tries=8)
        if not raised or not _capture_ready():
            # _raise_window_visible already logged its precise reason on False
            if raised:
                logger.error("[MV] switch aborted: the MEmu window cannot be captured "
                             "— it is minimized and Windows refuses our restore "
                             "(MEmu runs ELEVATED; UIPI blocks us). Un-minimize the "
                             "MEmu window, or run start.ps1 as administrator.")
            return False
        v = village(cfg, idx)
        target = (v or {}).get("name")
        if not target:
            logger.error("[MV] village %s has no account name — cannot switch.", idx)
            return False
        # every OTHER village's account name — the OCR fallback refuses a fuzzy
        # row that (near-)equals one of these (the 'nghia' vs 'Nghiays' incident)
        other_names = {
            str(o.get("name") or "").strip()
            for o in cfg.get("villages", [])
            if o.get("idx") != idx and o.get("name")
        }
        other_names.discard("")
        ok, mapping = open_switcher()
        if not ok:
            return False
        logger.info("[MV] locating account %r on the SCID list...", target)
        _tap(*c["scid_switch_id"])
        _sleep(3.0)
        tapped = False
        for scan_round in range(10):
            cap = _selfcap()
            if cap is None:
                _sleep(1.5)
                continue
            # 2026-11-19 (user): a captured SCID row face (assets/scid/v<idx>.png)
            # is matched FIRST — template matching beats OCR-by-name for a known
            # account (the Train Army roster-face lesson). No face captured or
            # no match yet -> the OCR-by-name path stays as the fallback.
            face_loc = _locate_scid_face(cap, idx, mapping)
            if face_loc is not None:
                logger.info("[MV] village %s SCID face matched at %s — tapping.",
                            idx, face_loc)
                _tap(*face_loc)
                tapped = True
                break
            hit = _locate_account_row(cap, target, mapping, other_names=other_names)
            if hit is None:
                _swipe(1300, 600, 350)   # reveal accounts further down
                _sleep(1.8)
                continue
            tx, ty, matched, sim = hit
            if not (900 <= tx <= 1550 and 150 <= ty <= 880):
                # the SCID list lives in the right panel — a locate outside that
                # window is a coordinate bug, not a row (guard against a silent
                # wrong-tap like the 2026-11-17 crop-offset incident)
                logger.warning("[MV] account %r matched at implausible point "
                               "(%d, %d) — ignored (row column is x900-1550).",
                               target, int(tx), int(ty))
                _swipe(1300, 600, 350)
                _sleep(1.8)
                continue
            logger.info("[MV] account %r found at (%d, %d) (match %r sim %.2f) — tapping.",
                        target, int(tx), int(ty), matched, sim)
            _tap(tx, ty)
            tapped = True
            break
        if not tapped:
            logger.error("[MV] account %r not found on the SCID list after "
                         "10 scans — switch aborted.", target)
            _close_scid_page()   # the list page is still open — close it
            return False
        _sleep(3.0)
        # 2026-11-21: prove the switch STARTED before trusting adb — beneath
        # the FLAG_SECURE overlay wait_home only sees the OLD village and
        # "verifies" instantly on a silently-failed switch.
        if not _switch_left_home():
            _close_scid_page()
            return False
        ok = wait_home()
        if not ok:
            logger.warning("[MV] switch to village %s FAILED (no verified home).", idx)
            return False
        _dismiss_welcome_popups()
        ident_ok, best_other, ident_scores = verify_village_identity(idx)
        if not ident_ok:
            # (a) 2026-11-23: wait_home can pass on a TRANSIENT frame while the
            # account is still loading (the rotation may fire right after a
            # backend restart / game relaunch) — the identity frame then matches
            # NO village (all scores inflate and tie, ~40-52) and every CORRECT
            # landing fails. Re-verify on a STABLE home frame (two consecutive
            # detections, bounded 30s) before declaring a wrong landing.
            stable = 0
            deadline = time.time() + 30.0
            while time.time() < deadline:
                if _run_stopped():
                    return False
                if _home_detected():
                    stable += 1
                else:
                    stable = 0
                if stable >= 2:
                    ident_ok, best_other, ident_scores = verify_village_identity(idx)
                    if ident_ok:
                        logger.info("[MV] identity re-verified for village %s on the "
                                    "settled home frame (the first check caught the "
                                    "account load in progress).", idx)
                        break
                    stable = 0
                _sleep(3.0)
        if not ident_ok:
            # (b) 2026-11-23: the references also go STALE when the game's look
            # changes (season/theme update — all scores inflate and tie). The
            # SCID avatar face is graphics-independent: verify it directly.
            # match = the landing IS this village -> regenerate the stale
            # reference and accept; mismatch/skip = a real wrong landing.
            status = settings_verify_face(idx)
            if status == "match":
                logger.warning(
                    "[MV] identity check failed for village %s but its SCID avatar "
                    "MATCHED — the references are stale (game look changed, e.g. a "
                    "season theme); regenerating them and accepting the switch.",
                    idx)
                try:
                    os.remove(os.path.join(MV_DIR, f"home_v{idx}.png"))
                except OSError:
                    pass
                _capture_home_snapshot(idx)
                cfg = load_config()
                v = village(cfg, idx)
                if v is not None and not v.get("confirmed"):
                    v["confirmed"] = True   # the avatar face verified the account
                    save_config(cfg)
                ident_ok = True
            else:
                logger.error("[MV] switch to village %s landed on the WRONG account "
                             "(identity check failed, avatar %s; looks like %s) — "
                             "treating as a failed switch.",
                             idx, status,
                             best_other[0] if best_other else "?")
                # 2026-11-21 cascade lesson: leave the dialogs up and the NEXT
                # village's switcher dies on them (its hut tap hits the popup).
                _dismiss_welcome_popups()
                return False
        _capture_home_snapshot(idx)
        if idx in ident_scores:
            # the identity check actually VERIFIED this landing (a healed
            # reference passes with a note instead — that visit cannot prove
            # identity, so it must not mark the village confirmed). This makes
            # a successful rotation switch count as verification, exactly like
            # the manual Apply does — otherwise the "not confirmed yet"
            # warning fires forever for villages the rotation itself verified
            # (2026-11-21: v3/v4/v6 were verified live but never marked).
            cfg = load_config()
            v = village(cfg, idx)
            if v is not None and not v.get("confirmed"):
                v["confirmed"] = True
                save_config(cfg)
                logger.info("[MV] village %s marked confirmed (identity verified "
                            "by the switch itself).", idx)
        return True
    except Exception as e:
        logger.warning("[MV] switch_to_village(%s) failed: %s", idx, e)
        return False


def apply_village_config(idx, ctx=None):
    """Copy village idx's saved config into the live run settings + reset
    per-village runtime state (army cache, chosen variant, counters)."""
    cfg = load_config()
    v = village(cfg, idx)
    if not v or not isinstance(v.get("config"), dict):
        logger.warning("[MV] village %s has no saved config to apply.", idx)
        return False
    config = v["config"]
    farm = config.get("farm")
    scenario = config.get("scenario")

    # live run settings (mutated in place so find_match/deploy see it now)
    if ctx is not None and getattr(ctx, "settings", None) is not None:
        if isinstance(farm, dict):
            ctx.settings["farm"] = dict(farm)
        deploy = ctx.settings.setdefault("attack", {}).setdefault("deploy", {})
        if scenario:
            deploy["active_scenario"] = scenario
        if hasattr(ctx, "vars") and ctx.vars is not None:
            ctx.vars["mv_scenario"] = scenario

    # persist so a later run/start keeps this village's thresholds
    try:
        from device_manager import load_settings, save_settings
        st = load_settings()
        if isinstance(farm, dict):
            st["farm"] = dict(farm)
        if scenario:
            st.setdefault("attack", {}).setdefault("deploy", {})["active_scenario"] = scenario
        save_settings(st)
    except Exception as e:
        logger.warning("[MV] persisting village config failed: %s", e)

    # reset per-village runtime state
    try:
        import scenario_store
        scenario_store.clear_army_cache()
        if ctx is not None and hasattr(ctx, "vars") and ctx.vars is not None:
            ctx.vars.pop("chosen_variant", None)
            ctx.vars["noprogress_runs"] = 0
    except Exception as e:
        logger.warning("[MV] runtime-state reset failed: %s", e)

    logger.info("[MV] applied village %s config: scenario=%s farm=%s",
                idx, scenario, farm)
    return True


def assume_village(idx, ctx=None):
    """Declare (without switching) that the game is currently on village idx —
    the fresh-backend assumption. Aligns the live settings with that village's
    saved config. Persisted runtime state makes this fire once per position."""
    _load_runtime_state()
    with _lock:
        _state["current_village_idx"] = idx
        _state["active_village_idx"] = idx
        _state["last_switch_ts"] = time.time()
    _persist_runtime_state()
    apply_village_config(idx, ctx)
    logger.info("[MV] assuming the game is on village %s (backend start).", idx)


# --- rotation ---------------------------------------------------------

def rotate_next(cfg=None, exclude=()):
    """Pick the next enabled village (wrapping after the current), skipping
    excluded ones. The rotation order is ASCENDING village idx among the
    ticked villages (user 2026-11-19: ticked {6, 7, 1} -> rotate 1 < 6 < 7).
    Returns (idx, village_dict) or (None, None)."""
    cfg = cfg or load_config()
    villages = sorted(
        (v for v in enabled_villages(cfg) if v.get("idx") not in exclude),
        key=lambda v: v.get("idx", 0),
    )
    if not villages:
        return None, None
    with _lock:
        current = _state["current_village_idx"]
    order = [v["idx"] for v in villages]
    if current is None or current not in order:
        return villages[0]["idx"], villages[0]
    pos = order.index(current)
    nxt = villages[(pos + 1) % len(villages)]
    return nxt["idx"], nxt


def do_rotation(ctx):
    """The farm-cycle rotation entry point (called by the mv_rotation block).

    Returns the switched-to village idx, 0 when no switch was due, or None on
    total failure (all villages exhausted — the caller escalates to the
    existing MAX_NO_PROGRESS_RUNS controlled stop).

    Recovery tiers per plan: switch fail -> one retry after a game restart ->
    mark the village failed for this window and move to the next -> all
    failed -> None. Never presses BACK. The restart budget is ONE per window
    (2026-11-17: per-village restarts multiplied into a restart storm when the
    failure was host-side — a mapping/capture problem restarts the game in
    vain; one restart tests a wedged GAME, after that just move on).
    """
    cfg = load_config()
    if not due_for_switch(cfg):
        return 0
    with _lock:
        _state["last_switch_ts"] = time.time()   # one attempt window per interval
    raised = _raise_window_visible(tries=8)
    if not raised or not _capture_ready():
        # host-side precondition — a game restart CANNOT fix a covered,
        # minimized, or UIPI-protected window. Fail the window fast, no
        # restart, no retry (the covered case logged its precise reason).
        if raised:
            logger.error("[MV] rotation aborted this window: the MEmu window cannot "
                         "be captured (minimized + MEmu runs elevated). Un-minimize "
                         "MEmu, or run start.ps1 as administrator.")
        return None
    enabled = enabled_villages(cfg)
    excluded = set()
    restarted = False

    def _commit():
        with _lock:
            _state["current_village_idx"] = idx
            _state["active_village_idx"] = idx
            _state["last_switch_ts"] = time.time()
        _persist_runtime_state()
        apply_village_config(idx, ctx)

    while len(excluded) < len(enabled):
        idx, v = rotate_next(cfg, excluded)
        if idx is None:
            logger.error("[MV] no enabled+confirmed village left to rotate to.")
            return None
        logger.info("[MV] rotating to village %s (%s)...", idx, v.get("name"))
        # User directive 2026-11-21: immediately after the rotation starts, the
        # game may sit on a battle-end 'Return Home' screen (a previous cycle's
        # wait/switch left it behind) — detect the button and tap it BEFORE the
        # switcher opens, or the hut tap lands on the battle-end screen. The
        # watch ends at once when the village screen is already up.
        popup_guard.return_home_watch_tap(logger, timeout=15.0)
        note_switch(idx)
        if switch_to_village(idx):
            _commit()
            return idx
        # tier 2: ONE full game restart per window, then retry once
        if not restarted:
            restarted = True
            logger.warning("[MV] switch to village %s failed — restarting game, "
                           "retrying once (the only restart this window).", idx)
            try:
                from device_manager import manager as _manager
                if _manager.device is not None:
                    _manager.device.restart_game("com.supercell.clashofclans")
                    _sleep(15)
            except Exception as e:
                logger.warning("[MV] restart during switch retry failed: %s", e)
            if switch_to_village(idx):
                _commit()
                return idx
        # tier 3: village unreachable this window — exclude it, move on
        logger.error("[MV] village %s unreachable after retry — excluded for this window.", idx)
        excluded.add(idx)
    logger.error("[MV] every enabled village failed to switch this window — "
                 "escalating to the run's no-progress handling.")
    return None
