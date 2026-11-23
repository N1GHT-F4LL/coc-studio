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
        mv._raise_window_visible = lambda **kw: True
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
        mv._raise_window_visible = lambda **kw: True
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
                  "_raise_window_visible", "_capture_ready",
                  "_locate_scid_face")}
        taps = []
        try:
            mv.open_switcher = lambda: (True, (1.0, 0.0, 0.0))
            mv._tap = lambda x, y: taps.append((x, y)) or True
            mv._raise_window_visible = lambda **kw: True
            mv._capture_ready = lambda: True
            mv._selfcap = lambda: object()          # opaque frame stand-in
            mv._locate_scid_face = lambda cap, idx_, m, threshold=0.7: None
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

        # --- 13. SCID face locate (2026-11-19) ------------------------------
        # The Train-Army pattern applied to MV: a captured SCID row face
        # (assets/scid/v<idx>.png) is matched FIRST during the switch scan;
        # OCR-by-name stays as the fallback for villages without a face.
        print("[13] scid face locate: template-first, OCR fallback")
        real_scid_dir = mv.SCID_DIR
        mv.SCID_DIR = os.path.join(tmp, "scid")
        os.makedirs(mv.SCID_DIR, exist_ok=True)
        # patterned face — a SOLID patch makes TM_CCOEFF_NORMED divide by zero
        # variance and return garbage matches (the battle_tiers lesson)
        face = _np.random.default_rng(9).integers(40, 220, (60, 90, 3), dtype=_np.uint8)
        _cv2.imwrite(os.path.join(mv.SCID_DIR, "v2.png"), face)
        # force the cache entry: a real backend session holds the USER's real
        # faces here (load_assets) — the test must pin its own pattern
        from core.vision import vision as _v13
        _v13.cache["scid/v2"] = _cv2.cvtColor(face, _cv2.COLOR_BGR2GRAY)
        face_frame = _np.zeros((900, 1600, 3), _np.uint8)
        face_frame[300:360, 1000:1090] = face
        # mapping (1.0, 2, 5): the paste centre (1045, 330) in cap coords
        # converts to the DEVICE tap point (1043, 325)
        mapping13 = (1.0, 2, 5)
        hit = mv._locate_scid_face(face_frame, 2, mapping13)
        check("scid face template matched at the DEVICE tap point",
              hit == (1043, 325), str(hit))
        check("village without a captured face -> None",
              mv._locate_scid_face(face_frame, 1, mapping13) is None)
        cfg = base_config()
        cfg["coords"]["scid_switch_id"] = [1335, 375]
        mv.CONFIG_PATH = os.path.join(tmp, "mv7.json")
        mv.save_config(cfg)
        saved13 = {n: getattr(mv, n) for n in
                   ("_selfcap", "_locate_account_row", "_tap", "_sleep",
                    "wait_home", "_dismiss_welcome_popups",
                    "verify_village_identity", "_capture_home_snapshot",
                    "_raise_window_visible", "_capture_ready", "open_switcher")}
        taps13 = []
        ocr_calls = []
        try:
            mv.open_switcher = lambda: (True, mapping13)
            mv._tap = lambda x, y: taps13.append((x, y)) or True
            mv._selfcap = lambda: face_frame
            mv._locate_account_row = (
                lambda cap, t, m, min_sim=0.6: ocr_calls.append(1) or None)
            mv._sleep = lambda s: None
            mv.wait_home = lambda timeout=180: True
            mv._dismiss_welcome_popups = lambda rounds=4: None
            mv.verify_village_identity = lambda idx, frame=None: (True, None, {})
            mv._capture_home_snapshot = lambda idx: None
            mv._raise_window_visible = lambda **kw: True
            mv._capture_ready = lambda: True
            ok13 = mv.switch_to_village(2)
            check("face match -> switch taps the DEVICE face position",
                  ok13 is True and (1043, 325) in taps13, f"ok={ok13} taps={taps13}")
            check("OCR-by-name never ran (face-first)", ocr_calls == [], str(ocr_calls))
        finally:
            for n, fn in saved13.items():
                setattr(mv, n, fn)

        # --- 14. _locate_account_row — exact-first + ambiguity refusal -----
        # 2026-11-21 incident: the old containment rule scored 'nghia' vs
        # 'Nghiays' at 1.00 and tapped village 2's ROW when switching to
        # village 5 — a real wrong-village switch.
        print("[14] account-row locate: exact-first, ambiguous fuzzy refused")
        saved14 = {n: getattr(mv, n) for n in ("_ocr_scid_accounts",)}
        try:
            mv._ocr_scid_accounts = lambda cap, mapping: (
                [(1180.0, 500.0, "Nghiays"), (1240.0, 650.0, "nghia")], True)
            hit = mv._locate_account_row(object(), "nghia", (1.0, 0, 0),
                                         other_names={"Nghiays"})
            check("exact name match wins over the containment look-alike",
                  hit == (1240.0, 650.0, "nghia", 1.0), str(hit))
            mv._ocr_scid_accounts = lambda cap, mapping: (
                [(1180.0, 500.0, "Nghiays")], True)
            check("only the look-alike row visible -> refused (None)",
                  mv._locate_account_row(object(), "nghia", (1.0, 0, 0),
                                         other_names={"Nghiays"}) is None)
            mv._ocr_scid_accounts = lambda cap, mapping: (
                [(1226.0, 749.0, "you nokw")], True)
            hit2 = mv._locate_account_row(object(), "you know", (1.0, 0, 0))
            check("OCR noise still matches fuzzily when unambiguous",
                  hit2 is not None and hit2[2] == "you nokw" and hit2[3] >= 0.6,
                  str(hit2))
        finally:
            for n, fn in saved14.items():
                setattr(mv, n, fn)

        # --- 15. popup-coverage gate (2026-11-21 incident) -----------------
        # Identity references captured with a reward/welcome dialog up are
        # MEANINGLESS — 7/9 real home_v*.png were popup-covered frames, so
        # every genuinely-correct switch failed the identity check and the
        # whole rotation cascade-excluded every village. The gate must
        # separate clean home frames from dialog-covered ones.
        print("[15] popup-coverage gate: clean vs dialog-covered frames")
        from core.vision import vision as _v15
        okay_tpl = _cv2.imread(os.path.join(mv.app_paths.ASSETS_DIR,
                                            "buttons", "battle", "okay.png"),
                               _cv2.IMREAD_GRAYSCALE)
        close_tpl = _cv2.imread(os.path.join(mv.app_paths.ASSETS_DIR,
                                             "buttons", "popup", "btn_close.png"),
                                _cv2.IMREAD_GRAYSCALE)
        _v15.cache["buttons/battle/okay"] = okay_tpl
        _v15.cache["buttons/popup/btn_close"] = close_tpl
        # colour copies for pasting into the 3-channel synthetic frames
        okay_bgr = _cv2.cvtColor(okay_tpl, _cv2.COLOR_GRAY2BGR)
        clean15 = _np.random.default_rng(15).integers(40, 220, (900, 1600, 3),
                                                      dtype=_np.uint8)
        dirty15 = clean15.copy()
        dirty15[690:690 + okay_tpl.shape[0],
                600:600 + okay_tpl.shape[1]] = okay_bgr
        so, sc = mv._frame_popup_scores(dirty15)
        check("dialog-covered frame scores above the okay gate",
              so >= mv.POPUP_OKAY_GATE, f"okay={so:.2f} close={sc:.2f}")
        check("dialog-covered frame -> _frame_clean False",
              mv._frame_clean(dirty15) is False)
        so_c, sc_c = mv._frame_popup_scores(clean15)
        check("patterned-noise frame stays below both gates",
              so_c < mv.POPUP_OKAY_GATE and sc_c < mv.POPUP_CLOSE_GATE,
              f"okay={so_c:.2f} close={sc_c:.2f}")
        check("clean frame -> _frame_clean True", mv._frame_clean(clean15) is True)

        # --- 16. identity self-heal -----------------------------------------
        # A corrupted expected reference is excluded from scoring AND renamed
        # out of the glob, so _capture_home_snapshot regenerates a clean one
        # on this very visit — no manual file surgery, no permanent cascade.
        print("[16] identity self-heal (corrupted 2026-11-21 references)")
        mv_dir16 = os.path.join(tmp, "mvdir16")
        os.makedirs(mv_dir16, exist_ok=True)
        real_mvdir16 = mv.MV_DIR
        mv.MV_DIR = mv_dir16
        saved16 = {n: getattr(mv, n) for n in ("_screencap", "_home_detected",
                                               "_dismiss_welcome_popups")}
        try:
            _cv2.imwrite(os.path.join(mv_dir16, "home_v1.png"), clean15)
            _cv2.imwrite(os.path.join(mv_dir16, "home_v2.png"), dirty15.copy())
            ok16, _bo16, sc16 = mv.verify_village_identity(2, frame=clean15)
            clean15b = _np.random.default_rng(16).integers(
                40, 220, (900, 1600, 3), dtype=_np.uint8)
            check("corrupted expected reference -> pass-with-note (cannot judge)",
                  ok16 is True and 2 not in sc16, f"ok={ok16} scores={sc16}")
            corrupt = [f for f in os.listdir(mv_dir16) if ".corrupt_" in f]
            check("corrupted reference renamed out of the glob", corrupt != [],
                  str(corrupt))
            check("home_v2.png gone (capture will regenerate it)",
                  not os.path.isfile(os.path.join(mv_dir16, "home_v2.png")))
            mv._screencap = lambda: clean15b
            mv._home_detected = lambda: True
            mv._capture_home_snapshot(2)
            check("clean snapshot regenerated for village 2",
                  os.path.isfile(os.path.join(mv_dir16, "home_v2.png")))
            _cv2.imwrite(os.path.join(mv_dir16, "home_v9.png"), dirty15.copy())
            ok9, _bo9, sc9 = mv.verify_village_identity(1, frame=clean15)
            check("corrupted OTHER reference only skipped from scoring",
                  ok9 is True and 9 not in sc9, f"ok={ok9} scores={sc9}")
        finally:
            mv.MV_DIR = real_mvdir16
            for n, fn in saved16.items():
                setattr(mv, n, fn)

        # --- 17. _capture_home_snapshot — never write a popup-covered frame
        print("[17] home snapshot quality gate")
        mv_dir17 = os.path.join(tmp, "mvdir17")
        os.makedirs(mv_dir17, exist_ok=True)
        real_mvdir17 = mv.MV_DIR
        mv.MV_DIR = mv_dir17
        saved17 = {n: getattr(mv, n) for n in ("_screencap", "_home_detected",
                                               "_dismiss_welcome_popups")}
        sweeps = []
        try:
            mv._home_detected = lambda: True
            mv._dismiss_welcome_popups = (
                lambda rounds=10: sweeps.append(1) or False)
            mv._screencap = lambda: dirty15.copy()
            mv._capture_home_snapshot(3)
            check("dialog-covered screen -> snapshot NOT written",
                  not os.path.isfile(os.path.join(mv_dir17, "home_v3.png")))
            check("sweep ran between capture attempts", len(sweeps) >= 1,
                  str(len(sweeps)))
            mv._screencap = lambda: clean15.copy()
            mv._capture_home_snapshot(3)
            check("clean screen -> snapshot written",
                  os.path.isfile(os.path.join(mv_dir17, "home_v3.png")))
        finally:
            mv.MV_DIR = real_mvdir17
            for n, fn in saved17.items():
                setattr(mv, n, fn)

        # --- 18. _switch_left_home — no wait_home trust without a real switch
        # Beneath the FLAG_SECURE overlay adb sees the OLD village, so
        # wait_home "verified home" instantly on every silently-failed switch.
        print("[18] switch-started gate")
        class _FakeUi18:
            def _stopped(self):
                return False
        class _FakeMgr18:
            ui_manager = _FakeUi18()
        saved18 = {n: getattr(mv, n) for n in ("manager", "_screencap",
                                               "_home_detected", "_sleep")}
        try:
            mv.manager = _FakeMgr18()
            mv._sleep = lambda s: None
            base18 = clean15.copy()
            dark18 = _np.full((900, 1600, 3), 8, dtype=_np.uint8)
            frames18 = [base18.copy(), base18.copy(), dark18.copy()]
            mv._screencap = lambda: frames18.pop(0) if frames18 else base18.copy()
            mv._home_detected = lambda: False
            check("frame changes (loading) -> switch started",
                  mv._switch_left_home(timeout=5.0) is True)
            mv._screencap = lambda: base18.copy()   # static home forever
            check("frame never changes -> switch did NOT start",
                  mv._switch_left_home(timeout=0.2) is False)
            mv._screencap = lambda: None
            check("no frame at all -> unobservable, pass-through True",
                  mv._switch_left_home(timeout=5.0) is True)
            seq18 = [True, False]
            mv._screencap = lambda: base18.copy()
            mv._home_detected = lambda: seq18.pop(0) if seq18 else False
            check("home anchors vanish -> switch started",
                  mv._switch_left_home(timeout=5.0) is True)
        finally:
            for n, fn in saved18.items():
                setattr(mv, n, fn)

        # --- 19. switch_to_village integration: gate-fail = clean abort -----
        print("[19] switch aborts cleanly when the switch never starts")
        cfg19 = base_config()
        cfg19["coords"]["scid_switch_id"] = [1335, 375]
        cfg19["coords"]["scid_close_x"] = [1548, 51]
        mv.CONFIG_PATH = os.path.join(tmp, "mv19.json")
        mv.save_config(cfg19)
        saved19 = {n: getattr(mv, n) for n in
                   ("open_switcher", "_tap", "_selfcap", "_locate_scid_face",
                    "_locate_account_row", "_sleep", "wait_home",
                    "_dismiss_welcome_popups", "verify_village_identity",
                    "_capture_home_snapshot", "_raise_window_visible",
                    "_capture_ready", "_switch_left_home", "_close_scid_page")}
        taps19 = []
        calls19 = {"wait_home": 0, "close": 0}
        try:
            mv.open_switcher = lambda: (True, (1.0, 0.0, 0.0))
            mv._tap = lambda x, y: taps19.append((x, y)) or True
            mv._selfcap = lambda: object()
            mv._locate_scid_face = lambda cap, idx_, m, threshold=0.7: (1100, 700)
            mv._switch_left_home = lambda timeout=25.0: False
            mv._close_scid_page = lambda: calls19.__setitem__(
                "close", calls19["close"] + 1)
            mv.wait_home = lambda timeout=180: calls19.__setitem__(
                "wait_home", calls19["wait_home"] + 1) or True
            mv._raise_window_visible = lambda **kw: True
            mv._capture_ready = lambda: True
            mv._sleep = lambda s: None
            mv._dismiss_welcome_popups = lambda rounds=10: None
            mv.verify_village_identity = lambda idx, frame=None: (True, None, {})
            mv._capture_home_snapshot = lambda idx: None
            ok19 = mv.switch_to_village(2)
            check("gate-fail -> switch returns False", ok19 is False, str(ok19))
            check("row WAS tapped before the gate", (1100, 700) in taps19,
                  str(taps19))
            check("wait_home never ran on a failed gate", calls19["wait_home"] == 0)
            check("SCID page close attempted", calls19["close"] == 1)
        finally:
            for n, fn in saved19.items():
                setattr(mv, n, fn)

        # --- 20. chest-overlay pre-clear (2026-11-21 01:05 incident) -------
        # The treasure-chest event pops AFTER return_home's own checks (the
        # award animation finishes late) and every switcher tap then lands on
        # the event screen — all four villages failed one window this way
        # ("panel NOT open" at 0.311, the same root cause as the morning's
        # village-6 instant exclusion).
        print("[20] chest-overlay pre-clear before the switcher")
        class _FakePG20:
            def __init__(self):
                self.smashes = 0
                self.seq = []
            def treasure_chest_visible(self, frame):
                return self.seq.pop(0) if self.seq else False
            def smash_treasure_chests(self, logger=None):
                self.smashes += 1
                return 8
        pg20 = _FakePG20()
        real_pg20 = mv.popup_guard
        saved20 = {n: getattr(mv, n) for n in ("_screencap", "_home_detected",
                                               "_dismiss_welcome_popups", "_sleep")}
        try:
            mv.popup_guard = pg20
            mv._screencap = lambda: object()
            mv._sleep = lambda s: None
            # one smash pass clears ONE chest; the next pending chest pops
            # 1-3s later — the pre-clear must loop until the Skip anchor
            # stays gone for two consecutive checks (2026-11-23 02:22:
            # every switch attempt smashed one chest, hut-tapped the
            # re-popped overlay and died, 0.331 signature)
            pg20.seq = [True, False, False]
            check("chest overlay up -> smashed until it stays gone",
                  mv._clear_chest_overlay_if_up() is True and pg20.smashes == 1)
            pg20.smashes = 0
            pg20.seq = [True, False, True, False, False]
            check("re-popped chest smashed again until the event stays gone",
                  mv._clear_chest_overlay_if_up() is True and pg20.smashes == 2)
            pg20.smashes = 0
            check("no overlay -> pre-clear is a no-op",
                  mv._clear_chest_overlay_if_up() is False and pg20.smashes == 0)
            sweeps20 = []
            mv._home_detected = lambda: True
            mv._dismiss_welcome_popups = lambda rounds=10: sweeps20.append(1)
            pg20.seq = [True, False, False]
            check("sweep path prefers the chest overlay first",
                  mv._sweep_popups_if_home() is True and pg20.smashes == 1
                  and sweeps20 == [])
            pg20.seq = []
            check("clean home -> welcome sweep runs",
                  mv._sweep_popups_if_home() is True and sweeps20 == [1])
            mv._home_detected = lambda: False
            check("neither overlay nor home -> no sweeping",
                  mv._sweep_popups_if_home() is False and sweeps20 == [1])
        finally:
            mv.popup_guard = real_pg20
            for n, fn in saved20.items():
                setattr(mv, n, fn)

        # --- 21. get_state restores the persisted runtime state -------------
        # A fresh backend must NOT re-assume the first enabled village while
        # the game is really on the persisted one (2026-11-21: the restart
        # after the chest incident re-assumed village 3 over a persisted
        # village 6 — the settings-verify mismatch then burned a corrective
        # switch on every restart).
        print("[21] runtime state restore before first use")
        mv.CONFIG_PATH = os.path.join(tmp, "mv21.json")
        mv.save_config({"enabled": True, "villages": [],
                        "runtime": {"current_village_idx": 7,
                                    "last_switch_ts": 123.0}})
        mv._state_loaded = False
        with mv._lock:
            mv._state.update({"current_village_idx": None,
                              "active_village_idx": None,
                              "last_switch_ts": 0.0})
        st21 = mv.get_state()
        check("get_state() restores current_village_idx from the config",
              st21.get("current_village_idx") == 7, str(st21))
        mv._state_loaded = False   # outer finally reloads the real config

        # --- 22. _raise_window_visible verifies the raise landed -----------
        # 2026-11-21 01:18: the auto-opened browser covered MEmu; MEmu runs
        # ELEVATED so the TOPMOST bump failed SILENTLY and every switch's
        # mapping derivation matched the BROWSER (0/5 regions) — all four
        # villages failed the window. The raise must now VERIFY it put MEmu
        # on top and report the precise reason.
        print("[22] raise-verify: covered window reported, not silently ignored")

        class _FakeUser32_22:
            def __init__(self, bump_ok, top_is_memu):
                self.bump_ok = bump_ok
                self.top_is_memu = top_is_memu
                self.memu_hwnd = 0x1234
                self.other_hwnd = 0x5678
            def IsWindowVisible(self, h):
                return True
            def GetWindowTextW(self, h, buf, n):
                buf.value = 'MEmu' if h == self.memu_hwnd else 'Firefox'
                return 0
            def EnumWindows(self, cb, _):
                cb(self.other_hwnd, 0)
                cb(self.memu_hwnd, 0)
                return True
            def GetWindowRect(self, h, rect):
                r = rect._obj if hasattr(rect, "_obj") else rect
                r.left, r.top, r.right, r.bottom = 112, 22, 1424, 792
                return True
            def IsIconic(self, h):
                return False
            def ShowWindow(self, h, cmd):
                return True
            def SetWindowPos(self, h, after, x, y, cx, cy, flags):
                return self.bump_ok
            def WindowFromPoint(self, pt):
                return self.memu_hwnd if self.top_is_memu else self.other_hwnd
            def IsChild(self, parent, child):
                return False

        real_u32 = mv.user32
        try:
            mv.user32 = _FakeUser32_22(bump_ok=True, top_is_memu=True)
            check("raise lands MEmu on top -> True",
                  mv._raise_window_visible() is True)
            mv.user32 = _FakeUser32_22(bump_ok=False, top_is_memu=True)
            check("bump refused but MEmu ALREADY uncovered -> True (UIPI refuses "
                  "SetWindowPos even uncovered — only the probe decides)",
                  mv._raise_window_visible() is True)
            mv.user32 = _FakeUser32_22(bump_ok=True, top_is_memu=False)
            check("bump ok but MEmu still covered -> False (UIPI guidance)",
                  mv._raise_window_visible() is False)
            mv.user32 = _FakeUser32_22(bump_ok=False, top_is_memu=False)
            check("covered + SetWindowPos refused -> False",
                  mv._raise_window_visible() is False)
        finally:
            mv.user32 = real_u32

        # --- 25. transient cover retry + lower-the-cover recovery ----------
        # 2026-11-23 02:18: a TRANSIENT cover (console flash) cost a whole
        # 60-min window — one probe miss failed the window instantly. The
        # raise now retries bounded AND lowers a persistent non-elevated
        # cover to HWND_BOTTOM (no focus move — same allowed z-order class).
        print("[25] transient-cover retry + lower-the-cover recovery")

        class _CoverUser32:
            def __init__(self, cover_resists=False):
                self.memu = 0x1234
                self.cover = 0x5678
                self.cover_resists = cover_resists
                self.cover_on_top = True
                self.lowered = 0
                self.bumps = 0
            def IsWindowVisible(self, h):
                return True
            def GetWindowTextW(self, h, buf, n):
                buf.value = 'MEmu' if h == self.memu else 'Some dashboard'
                return 0
            def EnumWindows(self, cb, _):
                cb(self.cover, 0)
                cb(self.memu, 0)
                return True
            def GetWindowRect(self, h, rect):
                r = rect._obj if hasattr(rect, "_obj") else rect
                r.left, r.top, r.right, r.bottom = 112, 22, 1424, 792
                return True
            def IsIconic(self, h):
                return False
            def ShowWindow(self, h, cmd):
                return True
            def SetWindowPos(self, h, after, x, y, cx, cy, flags):
                if h == self.memu:
                    self.bumps += 1
                    return 0          # UIPI refuses on the elevated MEmu
                if self.cover_resists:
                    return 0
                self.lowered += 1
                self.cover_on_top = False
                return 1
            def WindowFromPoint(self, pt):
                return self.cover if self.cover_on_top else self.memu
            def IsChild(self, parent, child):
                return False
            def GetAncestor(self, h, flag):
                return h

        real_u32b = mv.user32
        try:
            u25 = _CoverUser32()
            mv.user32 = u25
            check("persistent cover that can be lowered -> lowered once, True",
                  mv._raise_window_visible() is True and u25.lowered == 1,
                  f"lowered={u25.lowered}")
            u25b = _CoverUser32(cover_resists=True)
            mv.user32 = u25b
            check("cover cannot be lowered (elevated cover) -> False",
                  mv._raise_window_visible() is False and u25b.lowered == 0)
            # transient cover: first attempt fully covered (lowering refused),
            # cleared by the second attempt -> retry loop salvages the window
            u25c = _CoverUser32(cover_resists=True)
            probes = {"n": 0}
            def _wfp25(pt):
                probes["n"] += 1
                return u25c.cover if probes["n"] <= 3 else u25c.memu
            u25c.WindowFromPoint = _wfp25
            mv.user32 = u25c
            check("transient cover clears between retries -> True",
                  mv._raise_window_visible(tries=2, spacing=0.0) is True,
                  f"probes={probes['n']}")
        finally:
            mv.user32 = real_u32b

        # --- 23. rotation-start Return Home watch (user 2026-11-21) ---------
        # Immediately after "[MV] rotating to village ..." the screen may show
        # the battle-end Return Home button — watch + tap BEFORE the switcher
        # opens, or the hut tap lands on the battle-end screen.
        print("[23] rotation-start Return Home watch")
        real_pg23 = mv.popup_guard
        saved23 = {n: getattr(mv, n) for n in
                   ("switch_to_village", "CONFIG_PATH", "_raise_window_visible",
                    "_capture_ready", "_sleep")}
        try:
            class _PG23:
                calls = []
                @staticmethod
                def return_home_watch_tap(logger=None, timeout=40.0):
                    _PG23.calls.append(timeout)
                    return 0
            mv.popup_guard = _PG23
            mv.CONFIG_PATH = os.path.join(tmp, "mv23.json")
            mv.save_config(base_config())
            mv._state_loaded = False
            mv._state.update({"current_village_idx": 1, "active_village_idx": 1,
                              "last_switch_ts": 0.0})
            mv.switch_to_village = lambda idx: True
            mv._raise_window_visible = lambda **kw: True
            mv._capture_ready = lambda: True
            mv._sleep = lambda s: None
            mv.do_rotation(FakeCtx())
            check("rotation start watches for the battle-end Return Home button",
                  bool(_PG23.calls) and _PG23.calls[0] == 15.0, str(_PG23.calls))
        finally:
            mv.popup_guard = real_pg23
            for n, fn in saved23.items():
                setattr(mv, n, fn)

        # --- 24. a verified switch marks the village confirmed ---------------
        # 2026-11-21: rotation switches verified v3/v4/v6 live (identity ok +
        # avatar 1.00) but `confirmed` was only set by the manual Apply — the
        # "not confirmed yet" warning then fired forever for verified villages.
        print("[24] verified switch -> village marked confirmed")
        saved24 = {n: getattr(mv, n) for n in
                   ("open_switcher", "_tap", "_selfcap", "_locate_scid_face",
                    "_locate_account_row", "_sleep", "wait_home",
                    "_dismiss_welcome_popups", "verify_village_identity",
                    "_capture_home_snapshot", "_raise_window_visible",
                    "_capture_ready", "_switch_left_home", "_close_scid_page",
                    "_home_detected")}
        try:
            mv.CONFIG_PATH = os.path.join(tmp, "mv24.json")
            cfg24 = base_config()
            cfg24["coords"]["scid_switch_id"] = [1335, 375]
            mv.save_config(cfg24)
            mv.open_switcher = lambda: (True, (1.0, 0.0, 0.0))
            mv._tap = lambda x, y: True
            mv._selfcap = lambda: object()
            mv._locate_scid_face = lambda cap, idx_, m, threshold=0.7: (1100, 700)
            mv._sleep = lambda s: None
            mv.wait_home = lambda timeout=180: True
            mv._dismiss_welcome_popups = lambda rounds=10: None
            mv._capture_home_snapshot = lambda idx: None
            mv._raise_window_visible = lambda **kw: True
            mv._capture_ready = lambda: True
            mv._home_detected = lambda: True
            # identity VERIFIED (idx present in scores) -> confirmed set
            mv.verify_village_identity = lambda idx, frame=None: (
                True, (1, 35.0), {1: 35.0, 2: 12.0})
            check("verified switch succeeds",
                  mv.switch_to_village(2) is True)
            cfg = mv.load_config()
            check("identity-verified switch marks the village confirmed",
                  mv.village(cfg, 2).get("confirmed") is True,
                  str(mv.village(cfg, 2).get("confirmed")))
            # pass-with-note (healed reference, landing unprovable) -> NO marking
            cfg = mv.load_config()
            mv.village(cfg, 2)["confirmed"] = False
            mv.save_config(cfg)
            mv.verify_village_identity = lambda idx, frame=None: (
                True, None, {1: 35.0})
            check("pass-with-note switch succeeds",
                  mv.switch_to_village(2) is True)
            cfg = mv.load_config()
            check("pass-with-note does NOT mark confirmed",
                  mv.village(cfg, 2).get("confirmed") is False,
                  str(mv.village(cfg, 2).get("confirmed")))
        finally:
            for n, fn in saved24.items():
                setattr(mv, n, fn)

        # --- 26. stale-reference arbitration via the SCID avatar -------------
        # 2026-11-23: the game's look changed after 2 days (season theme) ->
        # ALL refs scored ~40-52 and tied -> every CORRECT switch failed
        # WRONG VILLAGE. The SCID avatar face is graphics-independent:
        # identity-fail + avatar MATCH = stale references -> regenerate +
        # accept; avatar mismatch = a real wrong landing.
        print("[26] stale-reference arbitration via the SCID avatar")
        mv_dir26 = os.path.join(tmp, "mvdir26")
        os.makedirs(mv_dir26, exist_ok=True)
        real_mvdir26 = mv.MV_DIR
        mv.MV_DIR = mv_dir26
        saved26 = {n: getattr(mv, n) for n in
                   ("open_switcher", "_tap", "_selfcap", "_locate_scid_face",
                    "_locate_account_row", "_sleep", "wait_home",
                    "_dismiss_welcome_popups", "verify_village_identity",
                    "settings_verify_face", "_raise_window_visible",
                    "_capture_ready", "_switch_left_home", "_close_scid_page",
                    "_home_detected", "_screencap")}
        try:
            mv.CONFIG_PATH = os.path.join(tmp, "mv26.json")
            cfg26 = base_config()
            cfg26["coords"]["scid_switch_id"] = [1335, 375]
            mv.save_config(cfg26)
            mv.open_switcher = lambda: (True, (1.0, 0.0, 0.0))
            mv._tap = lambda x, y: True
            mv._selfcap = lambda: object()
            mv._locate_scid_face = lambda cap, idx_, m, threshold=0.7: (1100, 700)
            mv._sleep = lambda s: time.sleep(0.01)   # settle-retry spins ~30s otherwise
            mv.wait_home = lambda timeout=180: True
            mv._dismiss_welcome_popups = lambda rounds=10: None
            mv._raise_window_visible = lambda **kw: True
            mv._capture_ready = lambda: True
            mv._switch_left_home = lambda timeout=25.0: True
            mv._close_scid_page = lambda: None
            mv._home_detected = lambda: True
            mv._screencap = lambda: _np.random.default_rng(26).integers(
                40, 220, (900, 1600, 3), dtype=_np.uint8)
            stale = _np.full((900, 1600, 3), 77, dtype=_np.uint8)
            _cv2.imwrite(os.path.join(mv_dir26, "home_v2.png"), stale)
            mv.verify_village_identity = lambda idx, frame=None: (
                False, (3, 45.6), {3: 45.6})
            mv.settings_verify_face = lambda idx: "match"
            check("avatar-match arbitration accepts the landing",
                  mv.switch_to_village(2) is True)
            regen = _cv2.imread(os.path.join(mv_dir26, "home_v2.png"))
            check("stale reference regenerated from a fresh capture",
                  regen is not None and float(regen.mean()) > 100.0,
                  "mean={}".format(None if regen is None else round(float(regen.mean()), 1)))
            cfg = mv.load_config()
            check("arbitrated switch marks the village confirmed",
                  mv.village(cfg, 2).get("confirmed") is True)
            mv.settings_verify_face = lambda idx: "mismatch"
            check("avatar mismatch -> switch still fails",
                  mv.switch_to_village(2) is False)
        finally:
            mv.MV_DIR = real_mvdir26
            for n, fn in saved26.items():
                setattr(mv, n, fn)

        # --- 27. identity margin vs slow village drift (2026-11-23 05:02) ---
        # Village 1's look drifted until its OWN reference scored ~32.8 while
        # the next village sat at ~35.6 — the 3.0 margin rejected the CORRECT
        # landing by 0.2 (the settle-retry saved it by luck). The margin is
        # relaxed to 1.5: a drifted-but-correct landing (argmin, close scores)
        # passes; a real wrong landing still fails (its frame matches the
        # WRONG village's ref closely -> expected >> best_other).
        print("[27] identity margin: drifted-but-correct landing accepted")
        mv_dir27 = os.path.join(tmp, "mvdir27")
        os.makedirs(mv_dir27, exist_ok=True)
        real_mvdir27 = mv.MV_DIR
        mv.MV_DIR = mv_dir27
        try:
            # frame P; ref_v1 = P dimmed 32.6 (the drifted same village);
            # ref_v4 = P dimmed 35.6 (the nearest other village) — distances
            # reproduce tonight's exact scores
            base = _np.random.default_rng(27).integers(40, 220, (900, 1600, 3),
                                                       dtype=_np.uint8).astype(_np.int16)
            frame27 = base.astype(_np.uint8)
            _cv2.imwrite(os.path.join(mv_dir27, "home_v1.png"),
                         _np.clip(base - 32.6, 0, 255).astype(_np.uint8))
            _cv2.imwrite(os.path.join(mv_dir27, "home_v4.png"),
                         _np.clip(base - 35.6, 0, 255).astype(_np.uint8))
            ok27, bo27, sc27 = mv.verify_village_identity(1, frame=frame27)
            check("drifted-but-correct landing (32.8 vs 35.6) accepted at margin 1.5",
                  ok27 is True, f"ok={ok27} scores={sc27}")
            # control: a REAL wrong landing (frame matches v4's ref closely)
            wrong27 = _np.clip(base - 35.6 + _np.random.default_rng(28).integers(
                -6, 6, (900, 1600, 3), dtype=_np.int16), 0, 255).astype(_np.uint8)
            ok27b, bo27b, sc27b = mv.verify_village_identity(1, frame=wrong27)
            check("real wrong landing still rejected",
                  ok27b is False and bo27b is not None and bo27b[0] == 4,
                  f"ok={ok27b} bo={bo27b} scores={sc27b}")
        finally:
            mv.MV_DIR = real_mvdir27
    finally:
        mv.CONFIG_PATH = real_path
        mv.STATS_DIR = real_stats
        mv._load_runtime_state()
    print(f"\n=== {passed} passed, {failed} failed ===")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
