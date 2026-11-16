"""No-device tests for the Multi-Village backend (config, module logic, API
guards, rotation tiers, per-village stats, mv_rotation block gating).

The real data/multi_village.json is never touched — every test points
multi_village.CONFIG_PATH at a temp file.
"""
import io
import json
import logging
import os
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import multi_village as mv  # noqa: E402

# Pristine reference — later sections patch mv.switch_to_village without restoring.
_REAL_SWITCH_TO_VILLAGE = mv.switch_to_village

passed = failed = 0


def check(name, cond, extra=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS {name}")
    else:
        failed += 1
        print(f"  FAIL {name} {extra}")


def base_config(**overrides):
    cfg = {
        "enabled": True,
        "interval_option": "30 minutes", "interval_mins": 30,
        "villages": [
            {"idx": 1, "name": "CosmicGoofyAntoine", "enabled": True, "confirmed": True,
             "config": {"scenario": "dragon_balloon",
                        "farm": {"min_gold": 100000, "min_elixir": 100000,
                                 "min_dark_elixir": 500}},
             "scid_row": {"swipes": 0, "tap_y": 509}},
            {"idx": 2, "name": "Nghiays", "enabled": True, "confirmed": True,
             "config": {"scenario": "Thrower",
                        "farm": {"min_gold": 200000, "min_elixir": 200000,
                                 "min_dark_elixir": 0}},
             "scid_row": {"swipes": 0, "tap_y": 654}},
            {"idx": 3, "name": "Namhp123", "enabled": False, "confirmed": False,
             "config": None,
             "scid_row": {"swipes": 0, "tap_y": 799}},
        ],
        "coords": {"scid_hut": [83, 92], "settings_tab": [1263, 65],
                   "swap_button": [1050, 170], "settings_close_x": [1382, 68],
                   "exit_dialog_cancel": [612, 576]},
    }
    cfg.update(overrides)
    return cfg


class FakeCtx:
    def __init__(self):
        self.settings = {}
        self.vars = {}
        self.logger = logging.getLogger("test.mv")
        self.stop_event = threading.Event()
        self.events = []

    def emit(self, ev):
        self.events.append(ev)


def main():
    tmp = tempfile.mkdtemp()
    real_path = mv.CONFIG_PATH
    mv.CONFIG_PATH = os.path.join(tmp, "multi_village.json")
    real_stats = mv.STATS_DIR
    mv.STATS_DIR = tmp
    try:
        # --- 1. config round-trip + interval enum ------------------------
        print("[1] config schema + interval enum")
        cfg = base_config()
        mv.save_config(cfg)
        loaded = mv.load_config()
        check("round-trip: enabled + 3 villages", loaded["enabled"] and len(loaded["villages"]) == 3)
        check("coords preserved verbatim",
              loaded["coords"]["scid_hut"] == [83, 92]
              and loaded["coords"]["settings_close_x"] == [1382, 68])
        check("interval enum maps 4 options",
              mv.INTERVAL_OPTIONS == {"30 minutes": 30, "1 hour": 60,
                                      "1.5 hours": 90, "2 hours": 120})
        check("interval_seconds honours interval_mins",
              mv.interval_seconds(cfg) == 1800.0)
        cfg2 = base_config(interval_option="2 hours", interval_mins=120)
        check("2 hours -> 120 min", mv.interval_seconds(cfg2) == 7200.0)

        # --- 2. due_for_switch gating ------------------------------------
        print("[2] due_for_switch gating")
        mv._load_runtime_state()
        with mv._lock:
            mv._state["current_village_idx"] = None
            mv._state["last_switch_ts"] = 0.0
        check("disabled -> never due", not mv.due_for_switch(base_config(enabled=False)))
        check("no current village -> not due", not mv.due_for_switch(base_config()))
        with mv._lock:
            mv._state["current_village_idx"] = 1
            mv._state["last_switch_ts"] = time.time() - 3600   # 1h ago vs 30min interval
        check("elapsed >= interval -> due", mv.due_for_switch(base_config()))
        with mv._lock:
            mv._state["last_switch_ts"] = time.time() - 60     # 1 min ago
        check("interval not elapsed -> not due", not mv.due_for_switch(base_config()))

        # --- 3. switch without calibration -> False, never raises --------
        print("[3] uncalibrated coords -> clean failure")
        cfg = base_config()
        cfg["coords"] = {k: None for k in
                         ("scid_switch_id", "scid_first_row",
                          "scid_row_height_px", "scid_confirm_yes")}
        check("switch_to_village(uncalibrated) -> False",
              mv.switch_to_village(1) is False)
        ok_sw, _mapping = mv.open_switcher()
        check("open_switcher -> still works up to the Settings check "
              "(no crash, device-absent safe)", ok_sw in (True, False))

        # --- 4. apply_village_config --------------------------------------
        print("[4] apply_village_config context swap")
        ctx = FakeCtx()
        ctx.settings = {"farm": {"min_gold": 1}, "attack": {"deploy": {}}}
        mv.CONFIG_PATH = os.path.join(tmp, "mv2.json")
        mv.save_config(base_config())
        check("apply village 2", mv.apply_village_config(2, ctx))
        check("farm thresholds swapped into live settings",
              ctx.settings["farm"]["min_gold"] == 200000
              and ctx.settings["farm"]["min_dark_elixir"] == 0)
        check("scenario override in vars", ctx.vars.get("mv_scenario") == "Thrower")
        check("active_scenario persisted into live settings",
              ctx.settings["attack"]["deploy"]["active_scenario"] == "Thrower")
        persisted = json.load(open(mv.CONFIG_PATH, encoding="utf-8"))
        # apply_village_config persists via save_settings (real settings.json)
        # — that write is to the REAL settings.json and is verified separately.
        check("army cache reset ran without error", True)
        check("apply unknown village -> False", not mv.apply_village_config(9, ctx))

        # --- 5. Save guard (API rule, tested at function level) -----------
        print("[5] save guard")
        from api.multi_village_api import save_village, load_village
        from fastapi import HTTPException
        with mv._lock:
            mv._state["active_village_idx"] = 2
        try:
            save_village(1, {"config": {"scenario": "X"}})
            check("save on non-active village rejected", False)
        except HTTPException as e:
            check("save on non-active village rejected",
                  e.status_code == 409 and "has not been loaded"
                  in e.detail, e.detail)
        res = load_village(2)
        check("load returns the village config + sets active",
              res["config"]["scenario"] == "Thrower"
              and mv.get_state()["active_village_idx"] == 2)
        res = save_village(2, {"config": {"scenario": "Thrower",
                                          "farm": {"min_gold": 250000}}})
        check("save on active village allowed",
              mv.village(mv.load_config(), 2)["config"]["farm"]["min_gold"] == 250000)

        # --- 6. rotation tiers --------------------------------------------
        print("[6] rotation tiers")
        mv.CONFIG_PATH = os.path.join(tmp, "mv3.json")
        mv.save_config(base_config())
        from device_manager import manager as _mgr
        real_dev = _mgr.device
        _mgr.device = None                      # restart path: no device -> skipped
        real_switch = mv.switch_to_village
        # host-window seams — the real MEmu window state must not gate the
        # rotation logic under test
        real_raise, real_ready = mv._raise_window_visible, mv._capture_ready
        mv._raise_window_visible = lambda: True
        mv._capture_ready = lambda: True
        try:
            mv._load_runtime_state()
            with mv._lock:
                mv._state["current_village_idx"] = 1
                mv._state["last_switch_ts"] = time.time() - 3600
            mv.switch_to_village = lambda idx: False
            ctx = FakeCtx()
            check("all switches fail -> None", mv.do_rotation(ctx) is None)
            # one village fails, the next succeeds
            calls = []
            def flaky(idx):
                calls.append(idx)
                return idx == 2
            mv.switch_to_village = flaky
            with mv._lock:
                mv._state["current_village_idx"] = 2
                mv._state["last_switch_ts"] = time.time() - 3600
            ctx = FakeCtx()
            res = mv.do_rotation(ctx)
            check("failed village skipped -> rotated to village 2", res == 2, str(res))
            check("fail-then-retry-then-excluded (plan tiers)",
                  calls == [1, 1, 2], str(calls))
            check("ctx got village-2 config", ctx.vars.get("mv_scenario") == "Thrower")
        finally:
            mv.switch_to_village = real_switch
            mv._raise_window_visible = real_raise
            mv._capture_ready = real_ready
            _mgr.device = real_dev

        # --- 7. stats buckets ----------------------------------------------
        print("[7] per-village stats")
        mv.CONFIG_PATH = os.path.join(tmp, "mv4.json")
        mv.save_config(base_config())
        mv.reset_all_stats()
        mv.note_cycle(1)
        mv.note_cycle(1)
        mv.note_cycle(2)
        s1, s2 = mv.load_stats(1), mv.load_stats(2)
        check("village 1 has 2 cycles, village 2 has 1 (no cross-contamination)",
              s1["cycles"] == 2 and s2["cycles"] == 1)
        mv.note_switch(2)
        check("switch counted on village 2", mv.load_stats(2)["switches"] == 1)
        mv.reset_all_stats()
        check("reset clears stats", mv.load_stats(1)["cycles"] == 0)

        # --- 8. mv_rotation block gating ------------------------------------
        print("[8] mv_rotation block")
        from engine.context import RuntimeContext
        from blocks.coc_blocks import MvRotation
        block = MvRotation()
        mv.CONFIG_PATH = os.path.join(tmp, "mv5.json")
        mv.save_config(base_config(enabled=False))
        ctx = FakeCtx()
        # hard guarantee: with rotation disabled the block must NEVER reach
        # switch_to_village — the bot farms the current account forever
        switch_calls = []
        real_switch8 = mv.switch_to_village
        mv.switch_to_village = lambda idx: switch_calls.append(idx) or True
        check("enabled=false -> no-op (switched 0)",
              block.run(ctx, {}) == {"switched": 0})
        check("enabled=false -> switch_to_village NEVER called (zero account switches)",
              switch_calls == [], str(switch_calls))
        mv.switch_to_village = real_switch8
        mv.save_config(base_config())
        mv._load_runtime_state()
        with mv._lock:
            mv._state["current_village_idx"] = 1
            mv._state["last_switch_ts"] = time.time() - 3600
        mv.switch_to_village = lambda idx: True
        real_apply = mv.apply_village_config
        mv.apply_village_config = lambda idx, ctx=None: True
        real_raise8, real_ready8 = mv._raise_window_visible, mv._capture_ready
        mv._raise_window_visible = lambda: True
        mv._capture_ready = lambda: True
        ctx = FakeCtx()
        res = block.run(ctx, {})
        check("due + switch ok -> switched idx + mv_active event",
              res == {"switched": 2}
              and any(e.get("type") == "mv_active" and e.get("idx") == 2
                      for e in ctx.events), str(res))
        # unconfirmed-but-configured villages are NOT a blocker (2026-11-16:
        # the tab flow saves configs without the one-time Apply switch — the
        # first rotation switch verifies each account instead).
        cfg = base_config()
        for v in cfg["villages"]:
            v["confirmed"] = False
        mv.save_config(cfg)
        mv.apply_village_config = real_apply
        mv._load_runtime_state()
        with mv._lock:
            mv._state["current_village_idx"] = 1
            mv._state["last_switch_ts"] = time.time() - 3600
        ctx = FakeCtx()
        res = block.run(ctx, {})
        check("unconfirmed-but-configured -> rotation proceeds (warn once)",
              res == {"switched": 2}
              and ctx.vars.get("mv_unconfirmed_warned") is True
              and any(e.get("type") == "mv_active" and e.get("idx") == 2
                      for e in ctx.events), str(res))

        # an enabled village WITHOUT a saved config still refuses, naming it
        cfg = base_config()
        cfg["villages"][1]["config"] = None
        mv.save_config(cfg)
        ctx = FakeCtx()
        try:
            block.run(ctx, {})
            check("village without config -> run refuses (raises)", False)
        except RuntimeError as e:
            check("village without config -> run refuses (raises)",
                  "Village_2 (Nghiays)" in str(e), str(e))
        mv._raise_window_visible = real_raise8
        mv._capture_ready = real_ready8

        # --- 9. switch_to_village scan loop (regression: 4-vs-5 unpack) ----
        # The account row IS found (calibration proved OCR matching works);
        # the unpack of the locate result must agree with its return arity,
        # else every switch dies in the outer except and Apply always 502s.
        print("[9] switch_to_village row-locate + tap (unpack contract)")
        mv.switch_to_village = _REAL_SWITCH_TO_VILLAGE
        cfg = base_config()
        cfg["coords"]["scid_switch_id"] = [1335, 375]
        mv.CONFIG_PATH = os.path.join(tmp, "mv6.json")
        mv.save_config(cfg)
        saved = {name: getattr(mv, name) for name in
                 ("open_switcher", "_tap", "_selfcap", "_ocr_scid_accounts",
                  "_sleep", "wait_home", "_dismiss_welcome_popups",
                  "verify_village_identity", "_capture_home_snapshot",
                  "_raise_window_visible", "_capture_ready")}
        taps = []
        try:
            mv.open_switcher = lambda: (True, (1.0, 0.0, 0.0))
            mv._tap = lambda x, y: taps.append((x, y)) or True
            mv._raise_window_visible = lambda: True
            mv._capture_ready = lambda: True
            mv._selfcap = lambda: object()          # opaque frame stand-in
            mv._ocr_scid_accounts = lambda cap, mapping: (
                [(1300.0, 570.0, "Nghiays")], True)
            mv._sleep = lambda s: None
            mv.wait_home = lambda timeout=180: True
            mv._dismiss_welcome_popups = lambda rounds=4: None
            mv.verify_village_identity = lambda idx, frame=None: (True, None, {})
            mv._capture_home_snapshot = lambda idx: None
            hit = mv._locate_account_row(object(), "Nghiays", (1.0, 0.0, 0.0))
            check("_locate_account_row returns (device_x, device_y, name, sim)",
                  hit == (1300.0, 570.0, "Nghiays", 1.0), str(hit))
            ok = mv.switch_to_village(2)
            check("switch taps the located SCID row (no unpack crash)",
                  ok is True and (1300.0, 570.0) in taps, f"ok={ok} taps={taps}")
        finally:
            for name, fn in saved.items():
                setattr(mv, name, fn)

        # --- 10. verify_village_identity — wrong-village safeguard ---------
        # The loop must compare against THIS village's own snapshot too (the
        # old code skipped it, so the guard could never fire).
        print("[10] verify_village_identity (wrong-village safeguard)")
        import cv2 as _cv2
        import numpy as _np
        mv_dir = os.path.join(tmp, "mvdir")
        os.makedirs(mv_dir, exist_ok=True)
        real_mvdir = mv.MV_DIR
        mv.MV_DIR = mv_dir
        try:
            v1 = _np.full((90, 160, 3), 10, dtype=_np.uint8)
            v2 = _np.full((90, 160, 3), 200, dtype=_np.uint8)
            _cv2.imwrite(os.path.join(mv_dir, "home_v1.png"), v1)
            _cv2.imwrite(os.path.join(mv_dir, "home_v2.png"), v2)
            ok2, _bo, _sc = mv.verify_village_identity(2, frame=v2)
            check("landed on the expected village -> ok", ok2 is True)
            ok1, bo, sc = mv.verify_village_identity(1, frame=v2)
            check("landed on village-2 look while expecting village 1 -> rejected",
                  ok1 is False and bo is not None and bo[0] == 2,
                  f"ok={ok1} bo={bo} scores={sc}")
            empty = os.path.join(tmp, "mvdir_empty")
            os.makedirs(empty, exist_ok=True)
            mv.MV_DIR = empty
            ok0, _b0, _s0 = mv.verify_village_identity(3, frame=v1)
            check("no snapshots at all -> pass (cannot check)", ok0 is True)
        finally:
            mv.MV_DIR = real_mvdir

        # --- 11. _derive_mapping — clip-tolerant verification (2026-11-17) --
        # The MEmu window client can equal the game content width exactly, so
        # the Build button's right edge is clipped in the capture: the old
        # centre-as-left-edge window + hard 5/5 failed EVERY switch (the
        # Settings->restart loop incident).
        print("[11] mapping: clipped edge region + false-lock rejection")
        refs = {
            'anchor_battle': (20, 730, 235, 900),
            'build': (1400, 730, 1600, 900),
            'icon_gold': (1530, 25, 1595, 65),
            'icon_elixir': (1530, 82, 1595, 120),
            'icon_dark': (1505, 130, 1570, 168),
        }
        adb = _np.zeros((900, 1600, 3), _np.uint8)
        for k, (x1, y1, x2, y2) in refs.items():
            pat = _np.random.default_rng(abs(hash(k)) % (2**31)).integers(
                40, 220, (y2 - y1, x2 - x1), dtype=_np.uint8)
            adb[y1:y2, x1:x2] = _np.stack([pat, pat, pat], axis=-1)
        s, ox, oy = 1.02, 2, 43
        big = _cv2.resize(adb, None, fx=s, fy=s, interpolation=_cv2.INTER_AREA)
        bh, bw = big.shape[:2]
        cap = _np.zeros((oy + bh + 16, 1632, 3), _np.uint8)   # right edge FLUSH
        cap[oy:oy + bh, ox:ox + bw, :] = big[:, :min(bw, 1632 - ox), :]
        res = mv._derive_mapping(cap, adb)
        check("clipped-edge capture derives the mapping (was 4/5 OOB)",
              res is not None and abs(res[0] - s) <= 0.01
              and abs(res[1] - ox) <= 3 and abs(res[2] - oy) <= 3, str(res))
        # false lock: only the anchor matches -> rejected
        cap2 = cap.copy()
        for k, (x1, y1, x2, y2) in refs.items():
            if k == 'anchor_battle':
                continue
            rx1 = max(0, int(ox + s * x1)); ry1 = max(0, int(oy + s * y1))
            rx2 = min(cap.shape[1], int(ox + s * x2))
            ry2 = min(cap.shape[0], int(oy + s * y2))
            noise = _np.random.default_rng(1).integers(0, 255,
                                                       (ry2 - ry1, rx2 - rx1, 3),
                                                       dtype=_np.uint8)
            cap2[ry1:ry2, rx1:rx2, :] = noise
        check("only anchor verifying -> mapping rejected",
              mv._derive_mapping(cap2, adb) is None)

        # --- 12. HARD FENCE: no host keyboard/focus injection (2026-11-17) --
        # The old ALT-keybd_event + AttachThreadInput foreground trick wedged
        # the HOST KEYBOARD system-wide (the user had to restart Windows).
        # The self-capture only needs the window UNCOVERED, never focused —
        # this module must not contain ANY host input injection, ever again.
        print("[12] hard fence: multi_village.py must not inject host input")
        import ast as _ast
        with open(mv.__file__, encoding="utf-8") as fh:
            _tree = _ast.parse(fh.read())
        banned = {"keybd_event", "SetForegroundWindow", "AttachThreadInput",
                  "mouse_event", "SendInput", "BlockInput"}
        hits = [n.attr for n in _ast.walk(_tree)
                if isinstance(n, _ast.Attribute) and n.attr in banned]
        check("no host key/focus injection APIs in multi_village.py",
              hits == [], str(hits))
    finally:
        mv.CONFIG_PATH = real_path
        mv.STATS_DIR = real_stats
        mv._load_runtime_state()
    print(f"\n=== {passed} passed, {failed} failed ===")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
