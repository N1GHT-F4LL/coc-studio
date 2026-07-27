from .base_screen import BaseScreen
from core.vision import vision
from core.perception import detect_troop_bar, protected_centers
import logging
import math
import os
import random
import time
import cv2
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

BATTLE_TIMEOUT = 180
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

    def wait_for_end(self, timeout=BATTLE_TIMEOUT):
        """Wait for a Return Home button and return its location, or None on timeout."""
        return self._wait_until_any_appears(
            RETURN_HOME_TEMPLATES,
            timeout=timeout,
            use_orb_fallback=False,
        )

    def tap_return_home(self, loc):
        self.ui_manager.click(*loc)
        logger.info("Tapped Return Home.")

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
            loc = self.wait_for_end(timeout=20)
            if loc:
                self.tap_return_home(loc)
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
        bar_gray = None
        tap_interval = float(deploy_cfg.get("tap_interval", DEPLOY_TAP_INTERVAL))
        # Pause after selecting a troop on the bar before dropping it. Charged
        # once per node, so it dominates wall-clock on scenarios with many nodes.
        select_delay = float(deploy_cfg.get("select_delay", DEPLOY_SELECT_DELAY))
        bar_center_y = (by1 + by2) // 2
        any_deployed = False
        debug_clicks = []

        completed = set()
        pending = list(nodes)

        while pending:
            ready = [n for n in pending if all(dep in completed for dep in n.get("after", []))]
            if not ready:
                break  # cycle guard — stop cleanly

            for n in ready:
                d = float(n.get("delay", 0))
                if d > 0:
                    time.sleep(d)

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

                    if slot.get("strategy") == "delay" or slot.get("type") == "delay":
                        seconds = int(slot.get("seconds", 1))
                        logger.info(f"[DEPLOY] delay  {seconds}s")
                        self.ui_manager._poll_sleep(seconds)
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
                        drops = self.collect_drop_points(nodes)
                        logger.info("[DEPLOY] ensure_deployed -> dump leftover troops (%d drop spot(s))",
                                    len(drops))
                        self.dump_remaining(deploy_cfg, drop_points=drops or None)
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
                        if bar_gray is None:
                            bar_gray = cv2.cvtColor(bar_crop, cv2.COLOR_BGR2GRAY)
                        template = vision.cache.get(template_key)
                        if template is None:
                            logger.warning(f"[DEPLOY] SKIP  {name}: template not in asset cache")
                            continue

                        default_threshold = 0.40 if "siege" in template_key else 0.50
                        slot_threshold = float(slot.get("threshold", default_threshold))
                        score, scaled, result_map = vision._find_best_scale(
                            bar_gray, template, threshold=slot_threshold, scales=SLOT_ICON_SCALES,
                        )
                        if result_map is None or scaled is None:
                            logger.warning(f"[DEPLOY] MISS  {name}: conf={score:.2f} < thr={slot_threshold:.2f} — skipped")
                            continue

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
                    # Allow per-slot or global deploy_cfg override to use press-and-drag
                    strat = slot.get("strategy", "line")
                    drop_style = slot.get("drop_style") or deploy_cfg.get("drop_style")
                    if strat == "spline":
                        drop_style = "spline"
                    use_drag = drop_style in ("drag", "spline")
                    if use_drag:
                        # Perform drag-based drops directly from the bar slot to targets.
                        # Support multi-target simultaneous drags: slot['multi_targets'] = [ (x,y), ... ]
                        multi = slot.get("multi_targets")
                        if multi and isinstance(multi, (list, tuple)) and len(multi) > 1:
                            # Build pair list: start positions distributed around slot_cx
                            n = len(multi)
                            spacing = int(deploy_cfg.get("bar_multi_spacing", 48))
                            starts = []
                            # center the group on slot_cx
                            base = slot_cx
                            offset = -((n - 1) * spacing) // 2
                            for i in range(n):
                                starts.append((base + offset + i * spacing, (by1 + by2) // 2))
                            # If drop_style explicitly requests spline paths, build per-finger bezier curves
                            if drop_style == "spline":
                                paths = []
                                steps = int(deploy_cfg.get("spline_steps", 12))
                                for s, tgt in zip(starts, multi):
                                    # Use humanize.bezier_curve to produce a natural curve
                                    path = self.ui_manager.humanize.bezier_curve(s, (int(tgt[0]), int(tgt[1])), None, steps=steps)
                                    paths.append(path)
                                self.ui_manager.drag_multi(paths, duration_ms=int(tap_interval * 1000))
                            else:
                                pairs = []
                                for s, tgt in zip(starts, multi):
                                    pairs.append((s, (int(tgt[0]), int(tgt[1]))))
                                self.ui_manager.drag_multi(pairs, duration_ms=int(tap_interval * 1000))
                            any_deployed = True
                        elif strat == "points":
                            pts = slot.get("points", [])
                            if not pts:
                                logger.warning(f"[DEPLOY] strategy='points' but no points configured for '{slot.get('template', '?')}'")
                            else:
                                for i in range(configured_taps):
                                    if self.ui_manager._stopped():
                                        break
                                    pt = pts[i % len(pts)]
                                    if drop_style == "spline":
                                        path = self.ui_manager.humanize.adaptive_bezier((slot_cx, (by1 + by2) // 2), (int(pt[0]), int(pt[1])), None,
                                                                 min_steps=int(deploy_cfg.get("spline_min_steps", 6)),
                                                                 max_steps=int(deploy_cfg.get("spline_max_steps", 32)),
                                                                 px_per_step=float(deploy_cfg.get("spline_px_per_step", 40)))
                                        self.ui_manager.drag_multi([path], duration_ms=int(tap_interval*1000))
                                    else:
                                        self.ui_manager.drag(slot_cx, slot_cy, int(pt[0]), int(pt[1]), duration_ms=int(tap_interval*1000))
                                    any_deployed = True
                        else:
                            # line or default: use same per-tap logic but via drag
                            def_y = int(deploy_cfg.get("battlefield_y", 750))
                            x1 = int(slot.get("x1", slot.get("x_start", deploy_cfg.get("battlefield_x_start", 300))))
                            y1 = int(slot.get("y1", slot.get("y", def_y)))
                            x2 = int(slot.get("x2", slot.get("x_end",   deploy_cfg.get("battlefield_x_end",  1300))))
                            y2 = int(slot.get("y2", slot.get("y", def_y)))
                            # Spread taps along line
                            dx = x2 - x1
                            dy = y2 - y1
                            dist = (dx*dx + dy*dy) ** 0.5 or 1.0
                            for i in range(configured_taps):
                                t = i / max(1, configured_taps - 1) if configured_taps > 1 else 0.5
                                bx = int(round(x1 + dx * t))
                                by = int(round(y1 + dy * t))
                                if self.ui_manager._stopped():
                                    break
                                if drop_style == "spline":
                                    path = self.ui_manager.humanize.adaptive_bezier((slot_cx, (by1 + by2) // 2), (bx, by), None,
                                                                                     min_steps=int(deploy_cfg.get("spline_min_steps", 6)),
                                                                                     max_steps=int(deploy_cfg.get("spline_max_steps", 32)),
                                                                                     px_per_step=float(deploy_cfg.get("spline_px_per_step", 40)))
                                    self.ui_manager.drag_multi([path], duration_ms=int(tap_interval*1000))
                                else:
                                    self.ui_manager.drag(slot_cx, slot_cy, bx, by, duration_ms=int(tap_interval*1000))
                                any_deployed = True
                    else:
                        self.ui_manager.click(slot_cx, slot_cy)
                        self.ui_manager._poll_sleep(select_delay)
                        if configured_taps > 0:
                            self._execute_slot_strategy(slot, deploy_cfg, configured_taps, tap_interval)
                        any_deployed = True

            for n in ready:
                completed.add(n["id"])
                pending.remove(n)

        self._save_bar_debug(screen, bar_crop, by1, by2, bx1, bx2, debug_clicks)
        return any_deployed

    def collect_drop_points(self, nodes):
        """Drop spots reused by leftover/event troop dumping.

        Only troop/spell nodes are used. Siege/hero taps can be unsafe because
        selecting or tapping near them after deployment may trigger abilities.
        """
        drops = []
        for nn in nodes or []:
            if nn.get("type") in ("siege", "hero"):
                continue
            for p in nn.get("points") or []:
                if isinstance(p, (list, tuple)) and len(p) == 2:
                    drops.append((int(p[0]), int(p[1])))
            if all(nn.get(k) is not None for k in ("x1", "y1", "x2", "y2")):
                x1n, y1n, x2n, y2n = (int(nn["x1"]), int(nn["y1"]),
                                      int(nn["x2"]), int(nn["y2"]))
                drops += [(x1n, y1n), (x2n, y2n), ((x1n + x2n) // 2, (y1n + y2n) // 2)]
        return drops

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

    def _tap_line(self, x1, y1, x2, y2, taps, interval, humanize=True):
        """Drop `taps` units along the line (x1,y1)->(x2,y2).

        taps=1 → midpoint; taps>1 → endpoints included. With ``humanize`` each
        drop is nudged along the line (uneven spacing) and a little off it
        (perpendicular wander), and the inter-drop delay is jittered — so a line
        deploy doesn't look like a perfectly even, ruler-straight robot stamp.
        ``UIManager.click`` already adds its own small per-tap jitter on top.
        """
        if taps == 1:
            self.ui_manager.click((x1 + x2) // 2, (y1 + y2) // 2)
            self.ui_manager._poll_sleep(self._drop_delay(interval, humanize))
            return

        dx, dy = (x2 - x1), (y2 - y1)
        dist = math.hypot(dx, dy) or 1.0
        ux, uy = dx / dist, dy / dist        # along-line unit vector
        px, py = -uy, ux                     # perpendicular unit vector
        spacing = dist / (taps - 1)
        along_amp = spacing * 0.35           # up to ~1/3 of a gap of uneven spacing
        perp_amp = min(spacing * 0.5, 22.0)  # gentle off-line wander, capped
        for i in range(taps):
            t = i / (taps - 1)
            bx, by = x1 + dx * t, y1 + dy * t
            if humanize:
                a = random.uniform(-along_amp, along_amp)
                p = random.uniform(-perp_amp, perp_amp)
                bx += ux * a + px * p
                by += uy * a + py * p
            self.ui_manager.click(int(round(bx)), int(round(by)))
            self.ui_manager._poll_sleep(self._drop_delay(interval, humanize))

    def _execute_slot_strategy(self, slot_cfg, deploy_cfg, taps, tap_interval):
        strategy = slot_cfg.get("strategy", "line")
        humanize = bool(deploy_cfg.get("humanize", True))

        if strategy == "points":
            pts = slot_cfg.get("points", [])
            if not pts:
                logger.warning(f"[DEPLOY] strategy='points' but no points configured for '{slot_cfg.get('template', '?')}'")
            else:
                for i in range(taps):
                    pt = pts[i % len(pts)]
                    self.ui_manager.click(int(pt[0]), int(pt[1]))
                    self.ui_manager._poll_sleep(self._drop_delay(tap_interval, humanize))
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

    def _protected_bar_centers(self, gray_bar, bx1, by1, deploy_cfg):
        """Known hero/siege slots should not be swept as event troops."""
        if not bool(deploy_cfg.get("dump_skip_heroes_sieges", True)):
            return []
        screen = deploy_cfg.get("_dump_screen")
        settings = deploy_cfg.get("_perception_settings")
        if screen is not None and settings is not None:
            mode = deploy_cfg.get("dump_perception_mode", "auto")
            result = detect_troop_bar(
                screen, settings, mode=mode, region=[bx1, by1, deploy_cfg.get("_dump_bx2"), deploy_cfg.get("_dump_by2")])
            centers = protected_centers(result)
            if centers:
                logger.info("[DUMP] protected slots via %s=%s", result.get("source"), centers)
                return centers

        prefixes = tuple(deploy_cfg.get("dump_skip_prefixes") or ("units/heroes/", "units/siege/"))
        threshold = float(deploy_cfg.get("dump_protected_threshold", 0.52))
        min_dist = int(deploy_cfg.get("dump_protected_min_distance", 46))
        candidates = deploy_cfg.get("_dump_protected_templates")
        if candidates is None:
            candidates = [
                (key, tpl) for key, tpl in vision.cache.items()
                if isinstance(key, str) and key.startswith(prefixes) and tpl is not None
            ]
            deploy_cfg["_dump_protected_templates"] = candidates
        hits = []
        for key, tpl in candidates:
            score, scaled, rmap = vision._find_best_scale(
                gray_bar, tpl, threshold=threshold, scales=SLOT_ICON_SCALES)
            if rmap is None or scaled is None or score < threshold:
                continue
            _, _, _, max_loc = cv2.minMaxLoc(rmap)
            th, tw = scaled.shape[:2]
            hits.append({
                "key": key,
                "score": float(score),
                "x": int(max_loc[0] + tw // 2 + bx1),
                "y": int(max_loc[1] + th // 2 + by1),
            })
        selected = []
        for hit in sorted(hits, key=lambda d: d["score"], reverse=True):
            if any((hit["x"] - s["x"]) ** 2 + (hit["y"] - s["y"]) ** 2 < min_dist ** 2 for s in selected):
                continue
            selected.append(hit)
        if selected:
            logger.info("[DUMP] protected slots=%s", [
                f"{h['key'].rsplit('/', 1)[-1]}@{h['x']}:{h['score']:.2f}" for h in selected
            ])
        return [h["x"] for h in selected]

    def dump_remaining(self, deploy_cfg, drop_points=None, max_rounds=None, taps_per_slot=None):
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
        screen0 = self.ui_manager.get_screen()
        if self._battle_ended(screen0):
            logger.info("[DUMP] battle ended / no bar - skipping.")
            return False
        h0, w0 = screen0.shape[:2]
        bx1, by1, bx2, by2 = [int(v) for v in deploy_cfg.get("troop_bar_region", [200, 855, 1400, 910])]
        bx1 = max(0, min(w0 - 1, bx1)); bx2 = max(1, min(w0, bx2))
        by1 = max(0, min(h0 - 1, by1)); by2 = max(1, min(h0, by2))
        if bx2 <= bx1 or by2 <= by1:
            logger.warning("[DUMP] troop_bar_region invalid - skipping.")
            return False
        bar_cy = (by1 + by2) // 2
        pitch = max(8, int(deploy_cfg.get("bar_slot_pitch", 95)))
        n_slots = max(1, int(math.ceil((bx2 - bx1) / pitch)))
        max_rounds = max(1, int(max_rounds if max_rounds is not None else deploy_cfg.get("dump_max_rounds", 6)))
        taps_per_slot = max(1, int(taps_per_slot if taps_per_slot is not None else deploy_cfg.get("dump_taps_per_slot", 12)))

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
        for rnd in range(max_rounds):
            if self.ui_manager._stopped():
                break
            screen = self.ui_manager.get_screen()
            if self._battle_ended(screen):
                logger.info("[DUMP] battle ended / no bar — stopping.")
                break
            deploy_cfg["_dump_screen"] = screen
            deploy_cfg["_dump_bx2"] = bx2
            deploy_cfg["_dump_by2"] = by2
            hsv = cv2.cvtColor(screen, cv2.COLOR_BGR2HSV)
            gray_bar = cv2.cvtColor(screen[by1:by2, bx1:bx2], cv2.COLOR_BGR2GRAY)
            protected = self._protected_bar_centers(gray_bar, bx1, by1, deploy_cfg)
            h, w = hsv.shape[:2]

            slots = []
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
                    slots.append({
                        "i": i,
                        "x": (tx1 + tx2) // 2,
                        "frac": float(coloured.mean()),
                    })
            if not slots:
                break
            occupied = []
            skipped = []
            for s in slots:
                if s["frac"] < frac_thr:
                    continue
                if any(abs(s["x"] - px) <= pitch * 0.55 for px in protected):
                    skipped.append((s["i"], s["x"], s["frac"]))
                    continue
                occupied.append(s["x"])
            logger.info("[DUMP] colour-fraction=%s thr=%.2f -> %d available, %d protected skip",
                        [round(s["frac"], 2) for s in slots], frac_thr, len(occupied), len(skipped))
            if skipped:
                logger.info("[DUMP] skipped protected slot(s)=%s", [
                    f"#{i}@{x}:{frac:.2f}" for i, x, frac in skipped
                ])
            if not occupied:
                logger.info("[DUMP] no coloured (available) units left — done.")
                break

            logger.info("[DUMP] round %d/%d: %d occupied slot(s) — dumping %d tap(s)/slot (incl. event troops).",
                        rnd + 1, max_rounds, len(occupied), taps_per_slot)
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

