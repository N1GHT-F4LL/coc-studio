from .base_screen import BaseScreen
from core.vision import vision
import popup_guard
import scenario_store
from glow_zone import detect_border_ring_segments, point_segment_dist
import logging
import math
import os
import random
import time
import cv2
import numpy as np
from datetime import datetime

logger = logging.getLogger(__name__)


def _draw_clicks(img, click_positions, colors, ox, oy, scale):
    for i, (key, cx, cy) in enumerate(click_positions or []):
        color = colors[i % len(colors)]
        label = key.split("/")[-1]
        px, py = int((cx - ox) * scale), int((cy - oy) * scale)
        cv2.circle(img, (px, py), 18, color, 3)
        cv2.putText(img, label, (px + 22, py + 6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2, cv2.LINE_AA)

BATTLE_END_TIMEOUT = 170    # tier-2 boundary (spec 2026-11-01; state-aware
                            # cleanup 2026-11-16): quá 170s -> dọn THEO MÀN HÌNH
                            # THỰC: battle UI -> dump+surrender; Return Home ->
                            # tap; đã về làng -> không làm gì; không nhận ra ->
                            # restart app (rate-limited)
BATTLE_POLL_SLEEP = 1.5     # wait_for_end tick
DUMP_FAST_ROUNDS = 2        # tier-2 cleanup: số vòng dump nhanh khi timeout
DEPLOY_POPUP_CHECK_EVERY = 5  # kiểm popup mỗi N slot trong deploy loop
DEPLOY_TAP_INTERVAL = 0.15   # delay between successive drop taps of one unit
DEPLOY_SELECT_DELAY = 0.3    # pause after tapping a unit on the bar, before dropping

# Anchors that appear at some point during the attack phase.
BATTLE_ANCHORS = (
    "buttons/battle/btn_end_battle",
    "buttons/battle/btn_surrender",
    "buttons/battle/btn_return_home",
)

RETURN_HOME_TEMPLATES = (
    "buttons/battle/btn_return_home",
)

# Battle-end screen variants (user 2026-11-18): the end screen shows EITHER
# btn_return_home OR claim_reward — both are checked on the SAME frame,
# never one-after-the-other across frames. Order = priority.
BATTLE_END_TEMPLATES = (
    ("return_home", "buttons/battle/btn_return_home"),
    ("claim_reward", "buttons/battle/claim_reward"),
)

# For bail/recovery paths: tap whichever exit button is reachable.
EXIT_BATTLE_TEMPLATES = (
    "buttons/battle/btn_return_home",
    "buttons/battle/btn_end_battle",
)

# The mid-battle bail button changes label by deploy state: a white-flag
# "Surrender" while troops are still being deployed, an "End Battle" once the
# whole army is down. They sit in the same spot and both quit the attack, so the
# surrender node accepts EITHER.
SURRENDER_BUTTONS = (
    "buttons/battle/btn_surrender",
    "buttons/battle/btn_end_battle",
)

# Confirm dialog after the bail button: an "are you sure you want to end the
# fight?" popup with Cancel + Okay. The clickable confirm is the green Okay
# button (``btn_surrender_confirm`` is a crop of the whole popup, not a button,
# so its centre lands on empty dialog space — don't tap that).
SURRENDER_CONFIRMS = (
    "buttons/battle/okay",
)

SLOT_ICON_SCALES = (0.50, 0.60, 0.70, 0.80, 0.90, 1.00, 1.10, 1.20)

# --- static pattern deploy (outer-border calibration) -------------------------
# Deploy NEVER analyses the enemy base at runtime (user design 2026-10-29,
# superseding the glow-border/red-diff detectors): the map's outer border is a
# game invariant — the red no-deploy zone always lies INSIDE it — so points
# calibrated along that border always deploy, on every base. All drop
# coordinates are static calibration data in the scenario JSON (per variant,
# in the post-pan view; see calib/build_pattern.py); this module only
# interprets the pattern. Randomness exists ONLY in the humanize layer and is
# biased OUTWARD (away from the base centre): error may only push a tap
# further into the safe band, never back inside.
#   strategy "pattern": points[] visited sequentially, one tap each;
#   taps == len(points) is the nominal case, taps < len takes the first
#   `taps` points, taps > len wraps around (points[i % len]).
PATTERN_SELECT_DELAY = 0.5    # settle after selecting a tab, before pattern taps
PATTERN_JITTER_MAX = 40.0     # outward jitter amplitude (px)
PATTERN_JITTER_SIDE = 10.0    # tangential wiggle amplitude (px)
# Diagnostic (user spec 2026-10-31): 7s after the attack starts, measure the
# white glow ring OUTSIDE the red zone — with obstacles hidden (RED_ZONE_
# ANALYSIS.md §7 noise source) — and score the static pattern points against
# it. Diagnostics only: it never moves a drop point.
PATTERN_DIAG_DELAY = 7.0


def _pattern_sequence(points, taps):
    """The three tap rules of strategy "pattern" (pure — unit-tested):
    taps == len(points) -> every point once; taps < len -> the FIRST `taps`
    points; taps > len -> wrap around. Order is fixed, never shuffled."""
    if not points:
        return []
    return [points[i % len(points)] for i in range(max(0, int(taps)))]


def _pattern_centre(points, fallback=None):
    """Centroid of the pattern — the 'toward base' reference for the outward
    jitter bias when the scenario carries no calibrated centre."""
    if not points:
        return fallback or (800, 450)
    return (sum(p[0] for p in points) / len(points),
            sum(p[1] for p in points) / len(points))


def _pattern_jitter(pt, centre, max_out=PATTERN_JITTER_MAX, side=PATTERN_JITTER_SIDE):
    """Outward-biased humanize jitter for one pattern tap: 0..max_out px along
    the away-from-centre axis (asymmetric — NEVER inward past the nominal
    point) plus ±side px tangentially. Clamped to the screen above the bar."""
    dx, dy = pt[0] - centre[0], pt[1] - centre[1]
    d = math.hypot(dx, dy)
    if d < 1e-6:
        ux, uy = 0.0, -1.0
    else:
        ux, uy = dx / d, dy / d
    r_out = random.uniform(0.0, max_out)
    r_side = random.uniform(-side, side)
    x = pt[0] + ux * r_out + (-uy) * r_side
    y = pt[1] + uy * r_out + ux * r_side
    return (int(round(max(10, min(1590, x)))), int(round(max(40, min(700, y)))))


def _hero_color_reject(frame_bgr, pos, scale, key, logger=None):
    """True when the card at ``pos`` clearly is NOT ``key``'s hero. Grayscale
    matching cannot separate same-family hero cards (a missing hero's template
    still cross-matches another card at 0.68-0.72), but their PALETTES differ:
    measured on a ground-truth frame, true cards sit at HSV distance 7-16 from
    their template while wrong cards sit at 49+. Reject beyond 40 (this also
    catches a template that was itself captured from the wrong card — e.g. a
    spell — which once slipped through as 'present')."""
    try:
        import app_paths
        if key not in _hero_color_reject.tpls:
            path = os.path.join(app_paths.ASSETS_DIR, *key.split("/")) + ".png"
            img = cv2.imread(path)  # colour
            if img is None:
                return False            # cannot verify — do not reject
            _hero_color_reject.tpls[key] = img
        tpl = _hero_color_reject.tpls[key]
        h, w = int(tpl.shape[0] * scale), int(tpl.shape[1] * scale)
        x, y = pos
        patch = frame_bgr[max(0, y - h // 2):y - h // 2 + h, max(0, x - w // 2):x - w // 2 + w]
        if patch.shape[0] != h or patch.shape[1] != w:
            patch = cv2.resize(patch, (w, h))
        a = cv2.cvtColor(tpl, cv2.COLOR_BGR2HSV).mean(axis=(0, 1))
        b = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV).mean(axis=(0, 1))
        dh = min(abs(a[0] - b[0]), 180 - abs(a[0] - b[0]))
        dist = float(np.sqrt((dh * 0.8) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2))
        if logger:
            logger.info("[DEPLOY] colour check %s: dist %.1f (reject > 40)", key, dist)
        return dist > 40
    except Exception:
        return False
_hero_color_reject.tpls = {}


def _zoom_ratio(prev, cur):
    """Content scale change between two frames (1.0 = no zoom happened)."""
    g1 = cv2.cvtColor(prev, cv2.COLOR_BGR2GRAY)
    g2 = cv2.cvtColor(cur, cv2.COLOR_BGR2GRAY)
    h, w = g1.shape
    patch = g1[h // 2 - 60:h // 2 + 60, w // 2 - 60:w // 2 + 60]
    if patch.size == 0:
        return 1.0
    best = (0.0, 1.0)
    for s in (0.70, 0.75, 0.80, 0.85, 0.90, 0.95, 1.0):
        t = cv2.resize(patch, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
        res = cv2.matchTemplate(g2, t, cv2.TM_CCOEFF_NORMED)
        _, mv, _, _ = cv2.minMaxLoc(res)
        if mv > best[0]:
            best = (mv, s)
    return best[1] if best[0] >= 0.60 else 1.0


def zoom_out_to_max_host(get_screen, logger=None, max_rounds=6, notches=3):
    """Zoom the game by scrolling the HOST mouse wheel over the Memu window:
    Memu converts wheel scrolls into real pinch gestures — the only zoom path
    that works on this emulator (the touch driver ignores injected
    multi-touch from the guest). Each round scrolls a few notches at the game
    view centre and verifies the content scale from frames; stops when the
    game clamps (scale ~1.0) and auto-corrects the direction once if the
    first round zoomed the wrong way. Moves and restores the host cursor."""
    try:
        import host_input
    except ImportError:
        if logger:
            logger.warning("[zoom] host_input unavailable (non-Windows host?) — no zoom")
        return 0
    hwnd = host_input.find_game_window("memu")
    if not hwnd:
        if logger:
            logger.warning("[zoom] Memu window not found — cannot host-zoom")
        return 0
    pt = host_input.game_view_point(hwnd)
    if not pt:
        if logger:
            logger.warning("[zoom] cannot resolve the Memu game-view point — no zoom")
        return 0
    # SAFETY: the wheel MUST land on the Memu window. On machines where
    # "scroll inactive windows" is off, the wheel follows the FOCUSED window
    # — scrolling with another window focused (e.g. a browser) would zoom
    # THAT window instead of the game. Bring Memu to the foreground, verify
    # it, and verify the window under the cursor before every scroll round;
    # abort otherwise (zooming the user's browser is unacceptable).
    if not host_input.force_foreground(hwnd):
        if logger:
            logger.warning("[zoom] could not bring Memu to the foreground — skipping zoom "
                           "(a wheel now would scroll the focused window instead)")
        return 0
    delta = -120   # wheel down = zoom out
    prev = get_screen()
    if prev is None:
        return 0
    rounds = 0
    old_pos = None
    for r in range(max_rounds):
        under = host_input.window_at(pt[0], pt[1])
        if not host_input.is_child_or_self(hwnd, under):
            if logger:
                logger.warning("[zoom] the cursor no longer sits on the Memu window — stopping zoom")
            break
        old_pos = host_input.wheel_scroll_at(pt[0], pt[1], notches, delta)
        rounds += 1
        time.sleep(1.0)
        cur = get_screen()
        if cur is None:
            break
        ratio = _zoom_ratio(prev, cur)
        if logger:
            logger.info("[zoom] host-wheel round %d: content scale %.2f", r + 1, ratio)
        if ratio > 1.05:
            delta = -delta   # zoomed the wrong way — flip once
        elif abs(ratio - 1.0) < 0.04:
            break
        prev = cur
    host_input.restore_cursor(old_pos)
    return rounds


def _content_shift(f_from, f_to):
    """Map-content displacement between two frames: p in f_from is at p+d in
    f_to. Median over central patches (margins fall off-screen after pans)."""
    g1 = cv2.cvtColor(f_from, cv2.COLOR_BGR2GRAY)
    g2 = cv2.cvtColor(f_to, cv2.COLOR_BGR2GRAY)
    half = 90
    results = []
    for sx, sy in ((800, 380), (650, 300), (950, 300), (650, 480), (950, 480), (800, 550)):
        patch = g1[sy - half:sy + half, sx - half:sx + half]
        if patch.shape != (2 * half, 2 * half):
            continue
        res = cv2.matchTemplate(g2, patch, cv2.TM_CCOEFF_NORMED)
        _, mv, _, ml = cv2.minMaxLoc(res)
        if mv > 0.75:
            results.append((ml[0] + half - sx, ml[1] + half - sy))
    if len(results) < 3:
        return None
    dx = sorted(p[0] for p in results)[len(results) // 2]
    dy = sorted(p[1] for p in results)[len(results) // 2]
    return (int(dx), int(dy))


class BattleScreen(BaseScreen):
    def is_current_screen(self):
        found = self.ui_manager.scan_all(
            self._existing_templates(BATTLE_ANCHORS),
            use_orb_fallback=False,
        )
        return bool(found)

    def wait_until_entered(self, timeout=15):
        """Poll until the battle UI is visible (replaces blind sleep before deploy)."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.is_current_screen():
                return True
            self.ui_manager._poll_sleep(0.5)
        return False

    def deploy_troops(self, deploy_cfg):
        if not self._slot_deploy(deploy_cfg):
            logger.warning("[DEPLOY] No troop slots matched — skipping deploy.")

    def wait_for_end(self, timeout=None):
        """Chờ battle kết thúc — chuẩn hoá 4 nhánh (design 2026-11-01, phân tầng
        3 mức: mọi điểm kẹt map vào đúng 1 tầng):

          1. popup hệ thống -> TẦNG restart: boot_recovery NGAY (force-stop ->
             relaunch -> dismiss, qua popup_guard có rate limit) rồi thoát
             vòng chờ. Popup hệ thống không tự hồi phục — chậm 1s là chậm.
          2. Return Home hiển thị -> battle kết thúc, trả về toạ độ.
          3. quá BATTLE_END_TIMEOUT -> TẦNG mềm: dọn dẹp THEO MÀN HÌNH THỰC
             (_cleanup_after_timeout, 2026-11-16): còn battle UI -> dump nhanh +
             surrender; Return Home -> tap; đã về làng -> không làm gì; màn
             không nhận ra -> restart app (user directive — thay quy tắc
             "không bao giờ restart" của thiết kế 2026-11-01: game có thể tự
             kết thúc trận và nhảy về làng giữa lúc chờ, dump mù khi đó = tap
             bậy vào các nút dưới đáy màn hình làng).
          4. chưa gì -> sleep ngắn, lặp lại.

        Trả về danh sách [(kind, toạ độ), ...] của các battle-end button khớp
        (nhánh 2 — thường đúng 1 biến thể) hoặc [] (nhánh 1/3).
        "return_home" hoặc "claim_reward") hoặc None (nhánh 1/3 — caller kết
        thúc chu kỳ, không bail thêm vì dọn dẹp đã chạy trong vòng chờ)."""
        if timeout is None:
            timeout = BATTLE_END_TIMEOUT
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.ui_manager._stopped():
                return []
            screen = self.ui_manager.get_screen()
            if screen is not None:
                # nhánh 1 — TẦNG restart: popup hệ thống không tự hồi phục
                if popup_guard.popup_on_frame(screen):
                    if popup_guard.recovery_rate_exceeded():
                        logger.warning("[BATTLE] system popup but the recovery rate "
                                       "limit is hit — the watchdog is stopping the run.")
                        return []
                    logger.warning("[BATTLE] system popup — tier 1: app restart now "
                                   "(force-stop -> relaunch -> dismiss).")
                    popup_guard.boot_recovery()
                    return []
                # nhánh 2 — battle kết thúc: CẢ HAI biến thể end-screen đều
                # được match mỗi frame (btn_return_home + claim_reward), biến
                # thể khớp quyết định tap + log (user 2026-11-19)
                buttons = self._battle_end_buttons(screen)
                if buttons:
                    return buttons
            # nhánh 4 — chưa gì xảy ra
            self.ui_manager._poll_sleep(BATTLE_POLL_SLEEP)
        # nhánh 3 — TẦNG mềm: timeout -> dọn dẹp thật THEO MÀN HÌNH THỰC, không
        # phó mặc cho chu kỳ sau (game có thể đã tự kết thúc trận + về làng).
        logger.warning(f"[BATTLE] timeout after {BATTLE_END_TIMEOUT:.0f}s — cleaning up "
                       "(state-aware: battle -> dump+surrender, Return Home -> tap, "
                       "home -> nothing, unknown -> app restart).")
        try:
            self._cleanup_after_timeout()
        except Exception as e:
            logger.warning(f"[BATTLE] tier-2 cleanup failed ({e}) — ending the cycle.")
        return []

    def _first_template_loc(self, screen, candidates, threshold=0.7):
        """Single-frame locator for the tier-2 cleanup — NO polling (wait_for_end
        already polled the full battle timeout before getting here). Returns
        None (NEVER []) when nothing matches: the cleanup branches gate on
        ``is not None`` — a falsy [] would still pass that check and fire the
        battle branch on garbage frames (2026-11-18 regression)."""
        for tpl in self._existing_templates(candidates):
            loc = vision.find_template(screen, tpl, threshold=threshold,
                                       use_orb_fallback=False)
            if loc:
                return loc
        return None

    def _on_home_village(self):
        """The `[ensure_home] home screen detected.` check — the same strict
        two-anchor HomeScreen detection the startup path uses."""
        from screens.home_screen import HomeScreen
        return HomeScreen(self.ui_manager).is_current_screen()

    def _await_home_after_cleanup(self, timeout=30):
        """Bounded post-cleanup settle: tap Return Home when it appears, stop at
        the home village. Never re-enters wait_for_end (the old
        surrender -> wait_for_end -> cleanup chain re-dumped on home forever) —
        the worst case hands the state to the next ensure_home, which restarts
        if needed."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.ui_manager._stopped():
                return
            screen = self.ui_manager.get_screen()
            if screen is not None:
                for kind, rh in self._battle_end_buttons(screen):
                    self.tap_return_home(rh, kind)
                    self.ui_manager._poll_sleep(2.0)
                if self._on_home_village():
                    logger.info("[BATTLE] cleanup: back on the home village.")
                    return
            self.ui_manager._poll_sleep(BATTLE_POLL_SLEEP)
        logger.warning("[BATTLE] cleanup: home village not confirmed within %ss — "
                       "ensure_home will take over.", timeout)

    def _cleanup_after_timeout(self):
        """Tier-2 (timeout) cleanup branched by what is ACTUALLY on screen
        (user spec 2026-11-16 — supersedes the blind dump+surrender):

          1. surrender/end-battle button -> real battle: dump leftover +
             surrender (return_home=False — never recurse into this cleanup),
             then tap Return Home when it appears.
          2. no battle button but Return Home visible -> battle already ended:
             tap it.
          3. neither, but the home village is detected -> nothing to clean (the
             game ended the battle by itself and jumped home mid-wait).
          4. none of the above -> unknown state: restart Clash of Clans right
             away (rate-limited like every boot_recovery); the next ensure_home
             re-lands and verifies home.
        """
        screen = self.ui_manager.get_screen()
        if screen is None:
            logger.warning("[BATTLE] cleanup: no frame — leaving recovery to ensure_home.")
            return
        if self._first_template_loc(screen, SURRENDER_BUTTONS) is not None:
            logger.info("[BATTLE] cleanup: battle UI still up — dump leftover + surrender.")
            self.dump_remaining({}, max_rounds=DUMP_FAST_ROUNDS)
            self.surrender(return_home=False)
            self._await_home_after_cleanup()
            return
        buttons = self._battle_end_buttons(screen)
        if buttons:
            for kind, rh in buttons:
                logger.info("[BATTLE] cleanup: battle already ended — tapping the "
                            "battle-end button (%s).", kind)
                self.tap_return_home(rh, kind)
            self.ui_manager._poll_sleep(2.0)
            self._await_home_after_cleanup()
            return
        if self._on_home_village():
            logger.info("[BATTLE] cleanup: already back on the home village — the game "
                        "ended the battle by itself; nothing to dump/surrender.")
            return
        # One re-check after a tick so a transition frame cannot trigger a restart.
        self.ui_manager._poll_sleep(BATTLE_POLL_SLEEP)
        screen = self.ui_manager.get_screen()
        if screen is not None and (
                self._first_template_loc(screen, SURRENDER_BUTTONS) is not None
                or self._battle_end_buttons(screen)
                or self._on_home_village()):
            logger.info("[BATTLE] cleanup: screen settled on re-check — rerunning the branch.")
            self._cleanup_after_timeout()
            return
        if popup_guard.recovery_rate_exceeded():
            logger.warning("[BATTLE] cleanup: unknown screen but the recovery rate limit "
                           "is hit — not restarting; the next ensure_home/noprogress "
                           "tier owns recovery.")
            return
        logger.warning("[BATTLE] cleanup: no battle UI, no Return Home, not home — "
                       "unknown state: restarting Clash of Clans now.")
        try:
            import os
            os.makedirs(os.path.join("data", "calib_debug"), exist_ok=True)
            if screen is not None:
                out = os.path.join("data", "calib_debug",
                                   f"unknown_state_{time.strftime('%m%d_%H%M%S')}.png")
                cv2.imwrite(out, screen)
                logger.info("[BATTLE] cleanup: unknown-state frame saved: %s", out)
        except Exception:
            pass
        popup_guard.boot_recovery()

    def tap_return_home(self, loc, kind="return_home"):
        self.ui_manager.click(*loc)
        if kind == "claim_reward":
            logger.info("Tapped Claim Reward.")
        else:
            logger.info("Tapped Return Home.")

    def _battle_end_buttons(self, screen, threshold=0.7):
        """Match BOTH battle-end variants on ONE frame — both checks ALWAYS
        run (no short-circuit, no priority; user 2026-11-19). The end screen
        shows one variant at a time (btn_return_home OR claim_reward);
        whichever matches determines the tap + the log line. Returns
        [(kind, loc), ...] for every matched template (normally 0 or 1)."""
        matches = []
        for kind, key in BATTLE_END_TEMPLATES:
            if key not in vision.cache:
                continue
            loc = vision.find_template(screen, key, threshold=threshold,
                                       use_orb_fallback=False)
            if loc:
                matches.append((kind, loc))
        return matches

    def surrender(self, return_home=True):
        """Give up the current attack: tap the surrender flag, confirm, then
        (optionally) return to the village once the loot screen appears.

        Backs the scenario ``surrender`` node — pair it with a ``delay`` node to
        deploy a few troops, wait, then bail out (e.g. quick resource raids).

        The bail button is a white-flag Surrender while troops are still being
        deployed and an End Battle once the army is fully down, so we accept
        either (``SURRENDER_BUTTONS``)."""
        flag = self._wait_until_any_appears(
            SURRENDER_BUTTONS, timeout=6, silent=True, use_orb_fallback=False)
        if not flag:
            logger.warning("[SURRENDER] no surrender/end-battle button found — battle may have already ended.")
        else:
            self.ui_manager.click(*flag)
            self.ui_manager._poll_sleep(0.6)
            # Both bail paths raise an "are you sure?" confirm (Surrender confirm
            # or the end-early Okay). Several confirm templates can partially
            # match the same dialog (both confirm buttons are green), so pick the
            # HIGHEST-confidence one rather than first-found — otherwise we tap the
            # wrong spot and the dialog stays up.
            confirm = self._wait_for_best_confirm(SURRENDER_CONFIRMS, timeout=4)
            if confirm:
                self.ui_manager.click(*confirm)
                logger.info("[SURRENDER] confirmed — tapped (%d,%d).", *confirm)
                self.ui_manager._poll_sleep(1.0)
            else:
                logger.info("[SURRENDER] no confirm dialog — continuing.")
        if return_home:
            for kind, loc in self.wait_for_end(timeout=20) or []:
                self.tap_return_home(loc, kind)
                self.ui_manager._poll_sleep(2)
            else:
                logger.warning("[SURRENDER] Return Home not seen after surrender.")
        return True

    def _wait_for_best_confirm(self, templates, timeout, threshold=0.7):
        """Poll for a confirm dialog and return the centre of the HIGHEST-
        confidence matching template.

        ``_wait_until_any_appears`` returns the first template that clears the
        threshold; when several confirm buttons look alike (two green buttons),
        a weak partial match can win and we tap the wrong spot. Scoring every
        candidate on each frame and taking the best makes the Okay button win on
        the End-Battle dialog and the Surrender confirm win on the white-flag
        dialog. Returns None if no candidate clears the threshold in time."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            screen = self.ui_manager.get_screen()
            if screen is not None:
                gray = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY) if screen.ndim == 3 else screen
                best = None  # (score, (cx, cy), key)
                for key in templates:
                    tpl = vision.cache.get(key)
                    if tpl is None:
                        continue
                    score, scaled, rmap = vision._find_best_scale(gray, tpl, threshold)
                    if rmap is None or scaled is None or score < threshold:
                        continue
                    _, _, _, max_loc = cv2.minMaxLoc(rmap)
                    bh, bw = scaled.shape[:2]
                    if best is None or score > best[0]:
                        best = (score, (int(max_loc[0] + bw // 2), int(max_loc[1] + bh // 2)), key)
                if best:
                    logger.info("[SURRENDER] confirm match %s conf=%.2f", best[2].rsplit("/", 1)[-1], best[0])
                    return best[1]
            self.ui_manager._poll_sleep(0.4)
        return None

    def bail(self):
        """Best-effort recovery: tap Return Home if visible, then close popups."""
        loc = self._wait_until_any_appears(
            EXIT_BATTLE_TEMPLATES,
            timeout=5,
            silent=True,
            use_orb_fallback=False,
        )
        if loc:
            self.ui_manager.click(*loc)
            logger.info("Return Home tapped (battle bail recovery).")
            self.ui_manager._poll_sleep(3)
        self.close_popups()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _slot_deploy(self, deploy_cfg):
        nodes = deploy_cfg.get("nodes")
        # Backward compat: old linear "slots" format
        if not nodes:
            slots = deploy_cfg.get("slots", [])
            nodes = [{"id": "n0", "after": [], "delay": 0, "slots": slots}]

        if not any(n.get("slots") or n.get("type") for n in nodes):
            return False

        screen = self.ui_manager.get_screen()
        if screen is None:
            return False

        bar_region = deploy_cfg.get("troop_bar_region", [200, 855, 1400, 910])
        bx1, by1, bx2, by2 = [int(v) for v in bar_region]
        h, w = screen.shape[:2]
        bx1 = max(0, min(w - 1, bx1))
        bx2 = max(1, min(w, bx2))
        by1 = max(0, min(h - 1, by1))
        by2 = max(1, min(h, by2))
        if bx2 <= bx1 or by2 <= by1:
            logger.warning("[DEPLOY] troop_bar_region invalid — skipping slot deploy.")
            return False

        bar_crop = screen[by1:by2, bx1:bx2]
        bar_gray = cv2.cvtColor(bar_crop, cv2.COLOR_BGR2GRAY)
        tap_interval = float(deploy_cfg.get("tap_interval", DEPLOY_TAP_INTERVAL))
        # Pause after selecting a troop on the bar before dropping it. Charged
        # once per node, so it dominates wall-clock on scenarios with many nodes.
        select_delay = float(deploy_cfg.get("select_delay", DEPLOY_SELECT_DELAY))
        bar_center_y = (by1 + by2) // 2
        any_deployed = False
        debug_clicks = []

        variant = deploy_cfg.get("variant") or (
            nodes[0]["id"].split("_")[0] if nodes and "_" in nodes[0]["id"] else "")
        glow_diag_done = False
        slot_count = 0
        # Takeover-popup recovery relaunches the game; a deploy caught mid-way
        # must abort instead of tapping into the loading screen (2026-10-31:
        # dragon/slammer/minion taps fired after the watchdog relaunch).
        boot_mark = scenario_store.get_session_flag("game_rebooted") or 0

        # --- battle-camera normalisation (user spec 2026-11-18) --------------
        # Entering a battle can reset the pinch zoom, and every plan point/pan
        # was calibrated at the fully zoomed-out view — so ALWAYS zoom out
        # before the hero-lineup scan. The deploy bar is fixed UI: the pinch
        # never moves it, so bar matching is unaffected.
        dev = getattr(self.ui_manager, "device", None)
        serial = getattr(dev, "serial", None)
        if serial:
            try:
                from zoom_out import multi_zoom_out
                logger.info("ZOOMING OUT . . .")
                if multi_zoom_out(serial):
                    logger.info("[DEPLOY] battle camera zoomed out (u2 pinch).")
                else:
                    logger.warning("[DEPLOY] battle zoom-out did not land — "
                                   "deploying at the current zoom.")
            except Exception as e:
                logger.warning(f"[DEPLOY] battle zoom-out skipped ({e})")

        # --- hero lineup: decide EVERY hero substitution up front ------------
        # Regenerating heroes don't appear on the battle bar at all, so one
        # scan of the untouched bar at deploy start is the ground truth for
        # who is available (the army screen can't tell: its hero panel art
        # doesn't match our templates and greyed-out portraits read the same
        # in grayscale). Each hero role resolves to its primary if present,
        # else its first listed fallback; ability nodes reuse the deploy
        # node's resolution so the ability tap hits the SAME hero.
        hero_choice = {}
        hero_nodes = [n for n in nodes if n.get("type") == "hero"]
        if hero_nodes:
            presence = {}
            HERO_PRESENCE_FLOOR = 0.62   # real cards score 0.66-0.76 on the
                                         # 1600x900 bar; cross-hero false
                                         # matches stay <=0.58

            def bar_conf(key):
                if key not in vision.cache:
                    return 0.0
                if key not in presence:
                    sc, scaled, rmap = vision._find_best_scale(
                        bar_gray, vision.cache[key], threshold=0.50,
                        scales=SLOT_ICON_SCALES)
                    conf = 0.0
                    if rmap is not None and scaled is not None:
                        _, _, _, ml = cv2.minMaxLoc(rmap)
                        th, tw = scaled.shape[:2]
                        pos = (ml[0] + tw // 2, ml[1] + th // 2 + by1)
                        scale = tw / max(1, vision.cache[key].shape[1])
                        if not _hero_color_reject(screen, pos, scale, key, logger):
                            conf = sc
                    presence[key] = conf
                return presence[key]

            roles = {}
            for nn in hero_nodes:
                nid = str(nn.get("id", ""))
                role = nid[len(variant) + 1:] if variant and nid.startswith(variant + "_") else nid
                base = role[:-3] if role.endswith("_ab") else role
                if base not in roles:
                    roles[base] = [c for c in ([nn.get("template")] +
                                               list(nn.get("fallbacks") or [])) if c]
            # Resolve with EXCLUSIVE claim, fallback-capable roles first: a
            # missing queen claims the king for herself, so the king's own
            # node (processed later) sees the king claimed and skips — its
            # ability is already covered by queen's ability node.
            claimed = set()
            order = [r for r in ("queen", "champ", "prince", "warden", "king", "duke")
                     if r in roles] + [r for r in roles if r not in
                                       ("queen", "champ", "prince", "warden", "king", "duke")]
            for base in order:
                # PRIMARY-FIRST: walk the chain in order and take the first
                # unclaimed hero that clears the floor. (An argmax here would
                # steal the fallback whenever IT self-matches stronger than
                # the primary — e.g. duke 0.70 vs champion 0.66 — and the
                # champion would never deploy.)
                chosen = None
                for cand in roles[base]:
                    if cand in claimed:
                        continue
                    if bar_conf(cand) >= HERO_PRESENCE_FLOOR:
                        chosen = cand
                        break
                if chosen:
                    hero_choice[base] = chosen
                    claimed.add(chosen)
                else:
                    hero_choice[base] = None
            logger.info("[DEPLOY] hero lineup for %s: %s (bar presence %s)",
                        variant or "?",
                        {k: (v.rsplit('/', 1)[-1] if v else None)
                         for k, v in hero_choice.items()},
                        {k.rsplit('/', 1)[-1]: round(v, 2) for k, v in presence.items()})

        completed = set()
        pending = list(nodes)

        while pending:
            if (scenario_store.get_session_flag("game_rebooted") or 0) != boot_mark:
                logger.warning("[DEPLOY] game relaunched mid-deploy (takeover popup "
                               "recovery) — aborting the remaining deploy; the next "
                               "cycle retrains and attacks fresh.")
                return any_deployed
            ready = [n for n in pending if all(dep in completed for dep in n.get("after", []))]
            if not ready:
                break  # cycle guard — stop cleanly

            for n in ready:
                d = float(n.get("delay", 0))
                if d > 0:
                    # Cooperative: Stop must cut the long endgame waits (e.g.
                    # the 30s tail) at once instead of sleeping straight
                    # through them — _poll_sleep wakes on the stop event.
                    self.ui_manager._poll_sleep(d)

            # Round-robin interleave: pop 1 slot from each ready node per pass
            # New-schema nodes (with "type") are themselves the single action.
            # Old-schema nodes have a "slots" list.
            def _node_to_queue(n):
                return [n] if "type" in n else list(n.get("slots", []))
            slot_queues = [_node_to_queue(n) for n in ready]
            while any(slot_queues):
                for q in slot_queues:
                    if not q:
                        continue
                    slot = q.pop(0)
                    # design B (2026-11-01): popup check BÊN TRONG deploy loop —
                    # mỗi DEPLOY_POPUP_CHECK_EVERY slot, không chỉ ở đầu block.
                    # Popup -> TẦNG restart (boot_recovery); cờ game_rebooted
                    # khiến vòng node kế tiếp abort deploy còn lại.
                    slot_count += 1
                    if (slot_count % DEPLOY_POPUP_CHECK_EVERY == 0
                            and not popup_guard.recent_recovery()
                            and not popup_guard.recovery_rate_exceeded()):
                        chk = self.ui_manager.get_screen()
                        if chk is not None and popup_guard.popup_on_frame(chk):
                            logger.warning("[BATTLE] system popup mid-deploy — tier 1: "
                                           "app restart now (deploy aborts via the "
                                           "reboot flag).")
                            popup_guard.boot_recovery()
                            return any_deployed

                    if slot.get("strategy") == "delay" or slot.get("type") == "delay":
                        seconds = int(slot.get("seconds", 1))
                        logger.info(f"[DEPLOY] delay  {seconds}s")
                        self.ui_manager._poll_sleep(seconds)
                        any_deployed = True
                        continue

                    if slot.get("type") == "pan":
                        # Camera pan of the battle map — THREE passes (user
                        # spec 2026-11-18): the extra swipes push the camera to
                        # the very edge of the map so the drop tiles sit as far
                        # from the base as the view allows, minimising red-zone
                        # contact. Each pass verifies the actual content shift
                        # (drags coast a little) and corrects the residual once.
                        x1, y1, x2, y2 = (int(slot.get(k) or 0) for k in ("x1", "y1", "x2", "y2"))
                        for pan_round in (1, 2, 3):
                            logger.info(f"[DEPLOY] pan map ({x1},{y1})->({x2},{y2})")
                            try:
                                f0 = self.ui_manager.get_screen()
                                self.ui_manager.device._run_adb(
                                    ['shell', 'input', 'swipe',
                                     str(x1), str(y1), str(x2), str(y2), '900'])
                                self.ui_manager._poll_sleep(1.0)
                                f1 = self.ui_manager.get_screen()
                                intended = (x2 - x1, y2 - y1)
                                measured = _content_shift(f0, f1) if f0 is not None and f1 is not None else None
                                if measured is None:
                                    logger.warning("[DEPLOY] pan shift not measurable — trusting the swipe")
                                else:
                                    res = (intended[0] - measured[0], intended[1] - measured[1])
                                    logger.info(f"[DEPLOY] pan shift measured {measured}, intended {intended}")
                                    if abs(res[0]) > 25 or abs(res[1]) > 25:
                                        logger.info(f"[DEPLOY] correcting pan residual {res}")
                                        self.ui_manager.device._run_adb(
                                            ['shell', 'input', 'swipe', '800', '450',
                                             str(800 + res[0]), str(450 + res[1]), '700'])
                                        self.ui_manager._poll_sleep(0.8)
                            except Exception as e:
                                logger.warning(f"[DEPLOY] pan verify skipped ({e})")
                                self.ui_manager.device.swipe([(x1, y1), (x2, y2)])
                            self.ui_manager._poll_sleep(0.6)
                        any_deployed = True
                        continue

                    if slot.get("type") == "surrender":
                        logger.info("[DEPLOY] surrender -> exit battle")
                        # Just end the fight + confirm; the graph's Return Home
                        # block handles getting back to the village.
                        self.surrender(return_home=False)
                        any_deployed = True
                        continue

                    if slot.get("type") == "ensure_deployed":
                        # Drop whatever is LEFT on the bar — including event troops
                        # that have no template (dump_remaining sweeps by slot
                        # position, not by known icon). Reuse the planned drop
                        # spots (points + line endpoints from the other nodes) so
                        # leftovers land on already-valid tiles, not a default
                        # line that may sit on the base.
                        # Gather drop spots from TROOP/SPELL nodes only. Skip
                        # siege/hero spots: tapping the field where a deployed siege
                        # is walking can trigger/​destroy it, and we don't want to
                        # dump leftovers onto that lane.
                        drops = []
                        for nn in nodes:
                            if nn.get("type") in ("siege", "hero"):
                                continue
                            for p in nn.get("points") or []:
                                if isinstance(p, (list, tuple)) and len(p) == 2:
                                    drops.append((int(p[0]), int(p[1])))
                            if all(nn.get(k) is not None for k in ("x1", "y1", "x2", "y2")):
                                x1n, y1n, x2n, y2n = (int(nn["x1"]), int(nn["y1"]),
                                                      int(nn["x2"]), int(nn["y2"]))
                                drops += [(x1n, y1n), (x2n, y2n),
                                          ((x1n + x2n) // 2, (y1n + y2n) // 2)]
                        logger.info("[DEPLOY] ensure_deployed -> dump leftover troops (%d drop spot(s))",
                                    len(drops))
                        self.dump_remaining(deploy_cfg, drop_points=drops or None)
                        self._tap_deploy_multiplier()
                        any_deployed = True
                        continue

                    template_key = slot.get("template", "")
                    name = template_key.split("/")[-1] if "/" in template_key else template_key
                    configured_taps = int(slot.get("taps", 5))
                    fixed_bar_x = slot.get("bar_x", 0)

                    if fixed_bar_x:
                        slot_cx = int(fixed_bar_x)
                        slot_cy = int(slot.get("bar_y", bar_center_y))
                        strat = slot.get("strategy", "line")
                        if strat == "points":
                            target = f"pts×{len(slot.get('points', []))}"
                        else:
                            target = f"({slot.get('x1','?')},{slot.get('y1','?')})→({slot.get('x2','?')},{slot.get('y2','?')})"
                        logger.info(f"[DEPLOY] {name:<22} ×{configured_taps}  bar=({slot_cx},{slot_cy}) [fixed]  → {target}")
                    else:
                        default_threshold = 0.40 if "siege" in template_key else 0.50
                        slot_threshold = float(slot.get("threshold", default_threshold))
                        # Hero nodes drop the lineup's resolved hero (decided
                        # once at deploy start); the node's own chain follows
                        # as a safety net.
                        candidates = [template_key] + list(slot.get("fallbacks") or [])
                        if slot.get("type") == "hero":
                            nid = str(slot.get("id", ""))
                            role = nid[len(variant) + 1:] if variant and nid.startswith(variant + "_") else nid
                            base = role[:-3] if role.endswith("_ab") else role
                            resolved = hero_choice.get(base)
                            if base in hero_choice and resolved is None:
                                logger.info(f"[DEPLOY] hero {base}: not on the bar / already "
                                            f"claimed by another hero — skipped")
                                continue
                            if resolved:
                                candidates = [resolved] + [c for c in candidates if c != resolved]
                        # Primary template first, then the node's declared
                        # fallbacks (hero substitution: e.g. queen -> barbarian
                        # king when the queen isn't on the deploy bar). The
                        # FIRST candidate that clears the threshold wins, so
                        # the ability node (same fallback chain) re-taps the
                        # same hero.
                        matched_key = None
                        matched = None
                        best_score = 0.0
                        for cand in candidates:
                            if not cand or cand not in vision.cache:
                                continue
                            cand_tpl = vision.cache[cand]
                            score, scaled, result_map = vision._find_best_scale(
                                bar_gray, cand_tpl, threshold=slot_threshold,
                                scales=SLOT_ICON_SCALES,
                            )
                            if result_map is not None and scaled is not None and score > best_score:
                                matched_key, matched, best_score = cand, (score, scaled, result_map), score
                                if score >= slot_threshold:
                                    break
                        if not matched or matched_key is None or best_score < slot_threshold:
                            logger.warning(
                                f"[TPL] {name} not found (score {best_score:.2f} < thr {slot_threshold:.2f})"
                                + (f" — tried {template_key} + fallbacks {slot.get('fallbacks')}"
                                   if slot.get("fallbacks") else "")
                                + " — skipped")
                            continue
                        template_key = matched_key
                        name = matched_key.split("/")[-1]
                        score, scaled, result_map = matched

                        _, _, _, max_loc = cv2.minMaxLoc(result_map)
                        th, tw = scaled.shape[:2]
                        slot_cx = int(max_loc[0] + tw // 2 + bx1)
                        slot_cy = int(max_loc[1] + th // 2 + by1)
                        strat = slot.get("strategy", "line")
                        if strat == "points":
                            pts = slot.get("points", [])
                            target = f"pts×{len(pts)}"
                        else:
                            target = f"({slot.get('x1','?')},{slot.get('y1','?')})→({slot.get('x2','?')},{slot.get('y2','?')})"
                        logger.info(f"[DEPLOY] {name:<22} ×{configured_taps}  bar=({slot_cx},{slot_cy}) conf={score:.2f}  → {target}")

                    debug_clicks.append((template_key, slot_cx, slot_cy))
                    self.ui_manager.click(slot_cx, slot_cy)
                    # Pattern nodes get a longer settle (spec: 0.5s after tab
                    # select) so the first pattern tap never lands on a
                    # still-animating selection.
                    self.ui_manager._poll_sleep(
                        PATTERN_SELECT_DELAY if slot.get("strategy") == "pattern"
                        else select_delay)
                    # One-shot glow-ring diagnostic (user spec 2026-10-31):
                    # 7s after the attack starts, measure the white border
                    # outside the red zone — obstacles hidden — and score the
                    # static pattern points against it. Diagnostics only: it
                    # never moves a drop point (static JSON stays the authority).
                    if slot.get("strategy") == "pattern" and not glow_diag_done:
                        glow_diag_done = True
                        self._glow_ring_diagnostic(deploy_cfg, nodes, variant)
                    if configured_taps > 0:
                        self._execute_slot_strategy(slot, deploy_cfg, configured_taps, tap_interval)
                    any_deployed = True

            for n in ready:
                completed.add(n["id"])
                pending.remove(n)

        self._save_bar_debug(screen, bar_crop, by1, by2, bx1, bx2, debug_clicks)
        return any_deployed

    def _glow_ring_diagnostic(self, deploy_cfg, nodes, variant):
        """One-shot per battle (user spec 2026-10-31): 7s after the attack
        starts, surface the red-zone border (a refused probe drop at the
        calibrated base centre consumes nothing) and measure the WHITE glow
        ring outside it — obstacles hidden per RED_ZONE_ANALYSIS.md §7 — then
        score every static pattern point against the measured ring.

        DIAGNOSTIC ONLY: the result never moves a drop point; the static JSON
        pattern stays the only deploy authority. Soft-fails into log lines."""
        try:
            static_pts = []
            for nn in nodes:
                if nn.get("strategy") == "pattern" and nn.get("points"):
                    role = str(nn.get("id", "")).rsplit("_", 1)[-1]
                    for p in nn["points"]:
                        static_pts.append((role, (int(p[0]), int(p[1]))))
            if not static_pts:
                return
            # 7s settle: battle-entry clouds/obstacle animations finish, so the
            # white ring measures clean (user-specified delay).
            self.ui_manager._poll_sleep(PATTERN_DIAG_DELAY)
            screen = self.ui_manager.get_screen()
            if screen is None:
                logger.warning("[GLOW-DIAG] %s: no frame — diagnostic skipped.", variant)
                return
            xs = [p[0] for _, p in static_pts]
            ys = [p[1] for _, p in static_pts]
            m = 60
            roi = (max(0, min(xs) - m), max(0, min(ys) - m),
                   min(1600, max(xs) + m), min(900, max(ys) + m))
            # the glow border only renders on a REFUSED drop attempt: tap the
            # calibrated base centre (deep inside the red zone — consumes
            # nothing) to surface fill + border, then grab a short burst.
            centre = deploy_cfg.get("base_centre") or _pattern_centre(
                [p for _, p in static_pts])
            self.ui_manager.click(int(centre[0]), int(centre[1]))
            segs, conf, best_frame = [], 0.0, None
            for grab in (0.3, 0.4, 0.5):
                self.ui_manager._poll_sleep(grab)
                frame = self.ui_manager.get_screen()
                if frame is None:
                    continue
                s, c = detect_border_ring_segments(frame, roi, hide_obstacles=True)
                if s and c >= conf:
                    segs, conf, best_frame = s, c, frame
                if segs:
                    break
            if not segs:
                logger.warning("[GLOW-DIAG] %s: no glow ring measured (fog/transition?) "
                               "— static pattern unchanged.", variant)
                return
            drifts = [(role, p, point_segment_dist(p[0], p[1], s2))
                      for role, p in static_pts
                      for s2 in [min(segs, key=lambda sg: point_segment_dist(p[0], p[1], sg))]]
            mean_d = sum(d for _, _, d in drifts) / len(drifts)
            worst = max(drifts, key=lambda t: t[2])
            logger.info("[GLOW-DIAG] %s: ring %d seg(s) conf=%.2f | static pts %d | "
                        "drift mean %.0fpx, max %.0fpx (%s @ %s)",
                        variant, len(segs), conf, len(drifts), mean_d,
                        worst[2], worst[0], worst[1])
            for role, p, d in drifts:
                if d > 60:
                    logger.warning("[GLOW-DIAG] %s point %s sits %.0fpx from the measured "
                                   "ring — recalibration candidate.", role, p, d)
            if os.environ.get("COC_GLOW_DEBUG") and best_frame is not None:
                dbg = best_frame.copy()
                for xa, ya, xb, yb in segs:
                    cv2.line(dbg, (xa, ya), (xb, yb), (0, 0, 255), 2)
                for role, p in static_pts:
                    cv2.circle(dbg, p, 6, (0, 255, 0), 2)
                    cv2.putText(dbg, role, (p[0] + 9, p[1] + 4),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 0), 1, cv2.LINE_AA)
                cv2.rectangle(dbg, (roi[0], roi[1]), (roi[2], roi[3]), (255, 0, 0), 2)
                os.makedirs(os.path.join("data", "calib_debug"), exist_ok=True)
                out = os.path.join("data", "calib_debug",
                                   f"glow_diag_{variant}_{time.strftime('%m%d_%H%M%S')}.png")
                cv2.imwrite(out, dbg)
                logger.info("[GLOW-DIAG] debug frame saved: %s", out)
        except Exception as e:
            logger.warning(f"[GLOW-DIAG] diagnostic failed ({e}) — deploy continues.")

    def _save_bar_debug(self, screen, bar_crop, by1, by2, bx1, bx2, click_positions=None):
        if not logger.isEnabledFor(logging.DEBUG):
            return
        try:
            out_dir = os.path.join("coc_bot", "logs", "debug")
            os.makedirs(out_dir, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            colors = [(0, 80, 255), (255, 80, 0), (0, 220, 220), (220, 0, 220)]

            canvas = screen.copy()
            cv2.rectangle(canvas, (bx1, by1), (bx2, by2), (0, 255, 0), 2)
            _draw_clicks(canvas, click_positions, colors, 0, 0, 1)
            cv2.imwrite(os.path.join(out_dir, f"bar_deploy_{ts}.png"), canvas)

            zoom = 3
            zoomed = cv2.resize(bar_crop, None, fx=zoom, fy=zoom, interpolation=cv2.INTER_NEAREST)
            _draw_clicks(zoomed, click_positions, colors, bx1, by1, zoom)
            cv2.imwrite(os.path.join(out_dir, f"bar_deploy_{ts}_zoom.png"), zoomed)
            logger.debug(f"[DEPLOY] Bar debug saved: {out_dir}/bar_deploy_{ts}*.png")
        except Exception as e:
            logger.debug(f"[DEPLOY] Bar debug save failed: {e}")

    def _drop_delay(self, interval, humanize):
        """Inter-drop pause. Humanized = jittered around ``interval`` (mean ≈ it)
        so taps aren't metronomic; otherwise the exact interval."""
        if humanize and interval > 0:
            return max(0.0, interval * random.uniform(0.55, 1.5))
        return interval

    def _tap_points(self, points, interval, humanize=True):
        """Fire a run of drop taps through ONE adb shell command
        (``input tap X Y && sleep <d> && input tap ...``). Each standalone
        ``input tap`` costs an adb process spawn (~0.2-0.4s on Windows), which
        is what made drop runs crawl; batching keeps the real cadence at
        ``interval``. Humanize still jitters each tap's position and the
        inter-tap sleeps. Falls back to slow per-tap clicks if batching fails.
        """
        pts = list(points)
        if not pts:
            return
        ui = self.ui_manager
        try:
            parts = []
            for i, (x, y) in enumerate(pts):
                if ui._stopped():
                    break
                if i:
                    d = self._drop_delay(interval, humanize)
                    if d > 0:
                        parts.append(f"sleep {d:.2f}")
                jx, jy = ui.humanize.get_jittered_coords(int(x), int(y)) if humanize \
                    else (int(x), int(y))
                parts.append(f"input tap {jx} {jy}")
            if parts:
                ui.device._run_adb(["shell", " && ".join(parts)])
        except Exception:
            for x, y in pts:
                if ui._stopped():
                    break
                ui.click(int(x), int(y))
                ui._poll_sleep(self._drop_delay(interval, humanize))

    def _tap_line(self, x1, y1, x2, y2, taps, interval, humanize=True):
        """Drop `taps` units along the line (x1,y1)->(x2,y2).

        taps=1 → midpoint; taps>1 → endpoints included. With ``humanize`` each
        drop is nudged along the line (uneven spacing) and a little off it
        (perpendicular wander), and the inter-drop delay is jittered — so a line
        deploy doesn't look like a perfectly even, ruler-straight robot stamp.
        ``UIManager.click`` already adds its own small per-tap jitter on top.
        """
        if taps == 1:
            self._tap_points([((x1 + x2) // 2, (y1 + y2) // 2)], interval, humanize)
            return

        dx, dy = (x2 - x1), (y2 - y1)
        dist = math.hypot(dx, dy) or 1.0
        ux, uy = dx / dist, dy / dist        # along-line unit vector
        px, py = -uy, ux                     # perpendicular unit vector
        spacing = dist / (taps - 1)
        along_amp = spacing * 0.35           # up to ~1/3 of a gap of uneven spacing
        perp_amp = min(spacing * 0.5, 22.0)  # gentle off-line wander, capped
        pts = []
        for i in range(taps):
            t = i / (taps - 1)
            bx, by = x1 + dx * t, y1 + dy * t
            if humanize:
                a = random.uniform(-along_amp, along_amp)
                p = random.uniform(-perp_amp, perp_amp)
                bx += ux * a + px * p
                by += uy * a + py * p
            pts.append((int(round(bx)), int(round(by))))
        self._tap_points(pts, interval, humanize)

    def _tap_deploy_multiplier(self):
        """Detect the 1x/4x deploy-multiplier button on the battle screen and
        tap it EXACTLY ONCE (user 2026-11-19: after the leftover dump, before
        the post-dump delay — one tap cycles the deploy rate 1x -> 2x -> 4x).
        No detect -> no tap."""
        screen = self.ui_manager.get_screen()
        if screen is None:
            logger.warning("[DEPLOY] 1x_to_4x: no frame — button not detected.")
            return
        loc = vision.find_template(screen, "buttons/battle/1x_to_4x",
                                   threshold=0.7, use_orb_fallback=False)
        if loc:
            self.ui_manager.click(*loc)
            logger.info(f"[DEPLOY] 1x_to_4x button detected at {loc} — tapped once.")
        else:
            logger.info("[DEPLOY] 1x_to_4x button not on screen.")

    def _execute_slot_strategy(self, slot_cfg, deploy_cfg, taps, tap_interval):
        strategy = slot_cfg.get("strategy", "line")
        humanize = bool(deploy_cfg.get("humanize", True))

        if strategy == "pattern":
            pts = slot_cfg.get("points", [])
            name = (slot_cfg.get("template") or "?").rsplit("/", 1)[-1]
            if not pts:
                logger.warning(f"[DEPLOY] strategy='pattern' but no points configured for '{name}'")
                return
            seq = _pattern_sequence([(int(p[0]), int(p[1])) for p in pts], taps)
            centre = deploy_cfg.get("base_centre") or _pattern_centre(
                [(int(p[0]), int(p[1])) for p in pts])
            # Humanize layer ONLY here, biased outward (never inward past the
            # nominal point) — the pattern coordinates themselves are exact.
            seq = [_pattern_jitter(p, centre) for p in seq]
            # Per-node rhythm override (data, not code): rage 1.0s, freeze 2.0s;
            # troop patterns inherit the deploy-level tap_interval.
            interval = float(slot_cfg.get("interval", tap_interval))
            logger.info(f"[DEPLOY] pattern {name}: {len(seq)} tap(s) over "
                        f"{len(pts)} point(s) interval={interval:.2f}s")
            if os.environ.get("COC_PATTERN_VERIFY"):
                # Calibration aid (diagnostics only — never steers the deploy):
                # on a REAL attack, save the frame with the nominal points (red)
                # and the jittered taps (yellow) so red-zone hits are visible.
                try:
                    vframe = self.ui_manager.get_screen()
                    if vframe is not None:
                        dbg = vframe.copy()
                        for p in pts:
                            cv2.circle(dbg, (int(p[0]), int(p[1])), 6, (0, 0, 255), -1)
                        for p in seq:
                            cv2.circle(dbg, p, 3, (0, 255, 255), -1)
                        os.makedirs(os.path.join("data", "calib_debug"), exist_ok=True)
                        out = os.path.join(
                            "data", "calib_debug",
                            f"verify_{deploy_cfg.get('variant', 'v')}_{name}_"
                            f"{time.strftime('%m%d_%H%M%S')}.png")
                        cv2.imwrite(out, dbg)
                        logger.info("[DEPLOY] pattern verify frame saved: %s", out)
                except Exception:
                    pass  # diagnostics must never break the deploy
            self._tap_points(seq, interval, humanize=False)
            return

        if strategy == "points":
            pts = slot_cfg.get("points", [])
            if not pts:
                logger.warning(f"[DEPLOY] strategy='points' but no points configured for '{slot_cfg.get('template', '?')}'")
            else:
                seq = [(int(pts[i % len(pts)][0]), int(pts[i % len(pts)][1]))
                       for i in range(taps)]
                interval = float(slot_cfg.get("interval", tap_interval))
                self._tap_points(seq, interval, humanize=humanize)
        else:
            # Support old {y, x_start, x_end} format as horizontal-line fallback.
            def_y = int(deploy_cfg.get("battlefield_y", 750))
            x1 = int(slot_cfg.get("x1", slot_cfg.get("x_start", deploy_cfg.get("battlefield_x_start", 300))))
            y1 = int(slot_cfg.get("y1", slot_cfg.get("y", def_y)))
            x2 = int(slot_cfg.get("x2", slot_cfg.get("x_end",   deploy_cfg.get("battlefield_x_end",  1300))))
            y2 = int(slot_cfg.get("y2", slot_cfg.get("y", def_y)))
            self._tap_line(x1, y1, x2, y2, taps, tap_interval, humanize=humanize)

    def _battle_ended(self, screen):
        """True once the deploy phase is over (Return Home shown / no screen)."""
        if screen is None:
            return True
        rh = RETURN_HOME_TEMPLATES[0]
        return rh in vision.cache and bool(
            vision.find_template(screen, rh, threshold=0.7, use_orb_fallback=False)
        )

    def dump_remaining(self, deploy_cfg, drop_points=None, max_rounds=4, taps_per_slot=6):
        """Deploy EVERYTHING still on the troop bar — including event/temporary
        troops that were never trained or planned, so they have NO template.

        Rather than matching known icons, sweep the bar by SLOT POSITION: split
        the bar into fixed-pitch tiles and treat a tile that is still in COLOUR
        (high mean saturation) as an available troop — a used-up slot greys out.
        For each occupied slot, select it and spam-drop along the front; re-scan
        each round and stop when no slot is colourful (bar done) or the battle
        ends. The
        Return Home button is re-checked before every drop, so once the fight is
        over (bar gone) we never tap the loot/result screen. Returns True if it
        dropped anything."""
        bx1, by1, bx2, by2 = [int(v) for v in deploy_cfg.get("troop_bar_region", [200, 855, 1400, 910])]
        bar_cy = (by1 + by2) // 2
        pitch = max(8, int(deploy_cfg.get("bar_slot_pitch", 95)))
        n_slots = max(1, (bx2 - bx1) // pitch)

        def_y = int(deploy_cfg.get("battlefield_y", 750))
        x1 = int(deploy_cfg.get("battlefield_x_start", 300))
        x2 = int(deploy_cfg.get("battlefield_x_end", 1300))
        tap_interval = float(deploy_cfg.get("tap_interval", DEPLOY_TAP_INTERVAL))
        select_delay = float(deploy_cfg.get("select_delay", DEPLOY_SELECT_DELAY))
        humanize = bool(deploy_cfg.get("humanize", True))
        # Occupancy by COLOUR-FRACTION: how much of the tile body is non-grey
        # (coloured) pixels. An available troop icon has lots of saturated pixels
        # even when the icon is dark (e.g. a dark-blue super minion); a used (x0)
        # slot or a spent/greyed hero is mostly grey -> few coloured pixels. This
        # separates better than mean saturation/brightness, where a dark-but-
        # colourful troop reads lower than a bright greyed hero. Tunable below.
        sat_min = float(deploy_cfg.get("dump_sat_min", 60.0))   # px S>=this = coloured
        val_min = float(deploy_cfg.get("dump_val_min", 50.0))   # ...and not near-black
        # Measured fractions: real available troop body >=0.43; spent hero
        # (pet+health) <=0.41; empty slot showing the map background ~0.21; a
        # used-up troop <=0.15. So the threshold sits at 0.42 — above heroes/
        # background, below the dimmest real troop. Calibrate from logged values.
        frac_thr = float(deploy_cfg.get("dump_color_frac", 0.42))   # >=this fraction = occupied

        dumped = False
        prev_occupied = None
        for rnd in range(max_rounds):
            if self.ui_manager._stopped():
                break
            screen = self.ui_manager.get_screen()
            if self._battle_ended(screen):
                logger.info("[DUMP] battle ended / no bar — stopping.")
                break
            hsv = cv2.cvtColor(screen, cv2.COLOR_BGR2HSV)
            h, w = hsv.shape[:2]

            fracs, centers = [], []
            for i in range(n_slots):
                tx1 = max(0, min(w, bx1 + i * pitch))
                tx2 = max(0, min(w, tx1 + pitch))
                ty1 = max(0, min(h, by1)); ty2 = max(0, min(h, by2))
                tw_, th_ = tx2 - tx1, ty2 - ty1
                if tw_ < 6 or th_ < 6:
                    continue
                # Sample only the lower-central BODY of the tile. The top strip
                # holds the level badge and — for a spent hero — its HEALTH BAR
                # (a bright green/red bar) which would otherwise add colour.
                sx1 = tx1 + int(tw_ * 0.20); sx2 = tx2 - int(tw_ * 0.20)
                sy1 = ty1 + int(th_ * 0.45); sy2 = ty2 - int(th_ * 0.05)
                if sx2 - sx1 < 4 or sy2 - sy1 < 4:
                    sx1, sy1, sx2, sy2 = tx1, ty1, tx2, ty2
                body = hsv[sy1:sy2, sx1:sx2]
                if body.size:
                    coloured = (body[:, :, 1] >= sat_min) & (body[:, :, 2] >= val_min)
                    fracs.append(float(coloured.mean()))   # fraction of non-grey px
                    centers.append((tx1 + tx2) // 2)
            if not fracs:
                break
            occupied = [c for c, f in zip(centers, fracs) if f >= frac_thr]
            logger.info("[DUMP] colour-fraction=%s thr=%.2f -> %d available",
                        [round(f, 2) for f in fracs], frac_thr, len(occupied))
            if not occupied:
                logger.info("[DUMP] no coloured (available) units left — done.")
                break

            # No progress: a dump round didn't reduce the colour slots, so the rest
            # won't deploy (heroes whose portrait stays colourful, or no valid drop
            # spot). Stop instead of re-tapping them every round.
            if prev_occupied is not None and len(occupied) >= prev_occupied:
                logger.info("[DUMP] %d slot(s) still colour after a round — stopping (heroes / undeployable here).",
                            len(occupied))
                break
            prev_occupied = len(occupied)

            logger.info("[DUMP] round %d: %d occupied slot(s) — dumping (incl. event troops).",
                        rnd + 1, len(occupied))
            for sx in occupied:
                if self.ui_manager._stopped():
                    return dumped
                if self._battle_ended(self.ui_manager.get_screen()):
                    logger.info("[DUMP] battle ended mid-dump — stopping.")
                    return dumped
                self.ui_manager.click(sx, bar_cy)        # select whatever sits in this slot
                self.ui_manager._poll_sleep(select_delay)
                # Drop onto the SAME spots the planned deploy used (already valid
                # for this base) if we were given them; else fall back to a line
                # across the front. A central default line can land on the base
                # (red zone) and silently fail to deploy.
                if drop_points:
                    for k in range(taps_per_slot):
                        px, py = drop_points[k % len(drop_points)]
                        self.ui_manager.click(int(px), int(py))
                        self.ui_manager._poll_sleep(self._drop_delay(tap_interval, humanize))
                else:
                    self._tap_line(x1, def_y, x2, def_y, taps_per_slot, tap_interval, humanize=humanize)
                dumped = True

        if dumped:
            logger.info("[DUMP] leftover troops dumped.")
        return dumped

