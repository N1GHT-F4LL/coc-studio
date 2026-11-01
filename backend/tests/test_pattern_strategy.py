"""Unit tests for the static pattern deploy (outer-border calibration design).

Run:  cd backend && ..\\.venv\\Scripts\\python.exe tests\\test_pattern_strategy.py

Covers the acceptance criteria of the "outer border = absolute safe zone" spec:
  1. strategy "pattern" tap rules: taps == len (all once), taps < len (first
     N points), taps > len (wrap around) — order fixed, never shuffled
  2. humanize jitter is outward-biased (never inward past the nominal point)
     and bounded
  3. full _slot_deploy pattern flow (mock device): 14 taps land on the
     calibrated points + outward jitter, pattern select delay honoured
  4. missing template -> "[TPL] <name> not found (score)" + skip, no crash
  5. dragon_balloon.json: all 4 variants on pattern, no troop line nodes,
     composition unchanged, engine still validates graphs
"""
import io
import json
import logging
import os
import random
import re
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import blocks  # noqa: F401,E402  -- populate REGISTRY (engine validate sanity)
from screens.battle_screen import (_pattern_sequence, _pattern_centre,  # noqa: E402
                                   _pattern_jitter, BattleScreen)
from engine.composition import required_composition  # noqa: E402
from engine.graph import Graph  # noqa: E402
from core.vision import vision  # noqa: E402

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


def make_line(n, x0=100, y0=500, dx=40, dy=-15):
    """Synthetic on-screen pattern line (never leaves 10..1590 x 40..700)."""
    return [[x0 + i * dx, y0 + i * dy] for i in range(n)]


def test_sequence_rules():
    print("[1] pattern tap rules: == len / < len / > len")
    pts = make_line(14)
    seq = _pattern_sequence([list(p) for p in pts], 14)
    check("taps == len -> every point once, in order",
          [list(s) for s in seq] == pts, str(seq[:2]))
    seq = _pattern_sequence([list(p) for p in pts], 5)
    check("taps < len -> first 5 points only",
          [list(s) for s in seq] == pts[:5])
    seq = _pattern_sequence([list(p) for p in pts], 20)
    check("taps > len -> wraps around",
          len(seq) == 20 and [list(s) for s in seq[:14]] == pts
          and list(seq[14]) == pts[0] and list(seq[19]) == pts[5])
    check("empty points -> empty sequence", _pattern_sequence([], 10) == [])
    check("zero taps -> empty sequence", _pattern_sequence(pts, 0) == [])


def test_jitter_outward():
    print("[2] jitter: outward-biased, bounded, clamped")
    random.seed(42)
    pts = make_line(14)
    centre = _pattern_centre(pts)
    ok_bias, ok_bound = True, True
    for p in pts:
        for _ in range(50):
            j = _pattern_jitter(p, centre)
            ux, uy = p[0] - centre[0], p[1] - centre[1]
            d = (ux * ux + uy * uy) ** 0.5 or 1.0
            ux, uy = ux / d, uy / d
            move = (j[0] - p[0], j[1] - p[1])
            # >= -1.0 tolerates the int() rounding of the jitter itself
            # (the outward term r_out >= 0 can only lose <= sqrt(2) px to it)
            if move[0] * ux + move[1] * uy < -1.0:
                ok_bias = False
            if (move[0] ** 2 + move[1] ** 2) ** 0.5 > 40.0 + 10.0 + 1.0:
                ok_bound = False
            if not (10 <= j[0] <= 1590 and 40 <= j[1] <= 700):
                ok_bound = False
    check("outward component >= 0 for every tap", ok_bias)
    check("move bounded by 40 outward + 10 tangential, on-screen", ok_bound)
    j = _pattern_jitter(centre, centre)
    check("point at centre -> still jittered on-screen",
          10 <= j[0] <= 1590 and 40 <= j[1] <= 700)


class FakeDevice:
    def __init__(self):
        self.adb_calls = []

    def _run_adb(self, args, text=True, _recovered=False):
        self.adb_calls.append(list(args))
        return type("R", (), {"returncode": 0})()


class FakeUI:
    def __init__(self, frame):
        self.frame = frame
        self.device = FakeDevice()
        self.clicks = []
        self.sleeps = []
        self.humanize = type("H", (), {
            "get_jittered_coords": staticmethod(lambda x, y: (x, y))})()

    def get_screen(self):
        return self.frame

    def click(self, x, y):
        self.clicks.append((int(x), int(y)))

    def _poll_sleep(self, s):
        self.sleeps.append(s)

    def _stopped(self):
        return False


def _collect_logs(fn):
    logs = io.StringIO()
    handler = logging.StreamHandler(logs)
    lg = logging.getLogger("screens.battle_screen")
    old_level = lg.level
    lg.setLevel(logging.INFO)
    lg.addHandler(handler)
    try:
        fn()
    finally:
        lg.removeHandler(handler)
        lg.setLevel(old_level)
    return logs.getvalue()


def test_slot_deploy_pattern_flow():
    print("[3] full _slot_deploy pattern flow on a mock screen")
    key = "units/troops/testpat"
    rng = np.random.default_rng(7)
    # textured background + a BRIGHT textured block: only the true scale
    # matches strongly (flat-on-flat TM_CCOEFF_NORMED is numerically unstable)
    frame = rng.integers(20, 60, size=(900, 1600, 3), dtype=np.uint8)
    frame[860:900, 300:340] = rng.integers(200, 255, size=(40, 40, 3), dtype=np.uint8)
    bar_crop = cv2.cvtColor(frame[855:910, 200:1400], cv2.COLOR_BGR2GRAY)
    tpl_color = frame[865:905, 310:350]            # 40x40 inside the block
    vision.cache[key] = cv2.cvtColor(tpl_color, cv2.COLOR_BGR2GRAY)
    pts = make_line(14)
    node = {"id": "9-12_balloon", "type": "troop", "template": key,
            "taps": 14, "strategy": "pattern", "points": pts}
    deploy_cfg = {"nodes": [node], "troop_bar_region": [200, 855, 1400, 910],
                  "tap_interval": 0.2, "select_delay": 0.05, "humanize": False,
                  "base_centre": [500, 400], "variant": "9-12"}
    ui = FakeUI(frame)
    bs = BattleScreen(ui)

    def run():
        bs.any_deployed = bs._slot_deploy(deploy_cfg)
    logs = _collect_logs(run)
    check("deploy reported", bs.any_deployed is True)
    check("tab selected near the icon block", len(ui.clicks) >= 1
          and abs(ui.clicks[0][0] - 330) <= 25 and abs(ui.clicks[0][1] - 880) <= 12,
          str(ui.clicks))
    check("pattern select delay 0.5s first", ui.sleeps[:1] == [0.5], str(ui.sleeps[:4]))
    taps = []
    for call in ui.device.adb_calls:
        if call and call[0] == "shell":
            for m in re.finditer(r"input tap (\d+) (\d+)", call[1]):
                taps.append((int(m.group(1)), int(m.group(2))))
    check("14 drop taps issued", len(taps) == 14, f"got {len(taps)}")
    ok_pts = all(abs(taps[i][0] - pts[i][0]) <= 42 and abs(taps[i][1] - pts[i][1]) <= 42
                 for i in range(14))
    check("each tap sits on its calibrated point + jitter", ok_pts,
          f"first={taps[0] if taps else None} want~{tuple(pts[0])}")
    check("[DEPLOY] pattern log line present",
          "pattern testpat: 14 tap(s) over 14 point(s)" in logs,
          logs[-300:])
    vision.cache.pop(key, None)


def test_missing_template_skip():
    print("[4] missing template -> [TPL] not found (score) + skip, no crash")
    frame = np.zeros((900, 1600, 3), np.uint8)
    node = {"id": "9-12_balloon", "type": "troop", "template": "units/troops/absent_tpl",
            "taps": 14, "strategy": "pattern", "points": make_line(14)}
    deploy_cfg = {"nodes": [node], "troop_bar_region": [200, 855, 1400, 910],
                  "tap_interval": 0.2, "humanize": False, "variant": "9-12"}
    ui = FakeUI(frame)
    bs = BattleScreen(ui)

    def run():
        bs.any_deployed = bs._slot_deploy(deploy_cfg)
    logs = _collect_logs(run)
    check("no crash, nothing deployed", bs.any_deployed is False)
    check("[TPL] not found (score ...) logged",
          "[TPL] absent_tpl not found (score 0.00" in logs, logs[-300:])
    check("no taps issued", ui.device.adb_calls == [] and ui.clicks == [])


def test_scenario_json():
    print("[5] dragon_balloon.json: pattern everywhere, composition unchanged")
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(here, "data", "scenarios", "dragon_balloon.json"),
              encoding="utf-8") as f:
        doc = json.load(f)
    check("calibration metadata present",
          doc.get("calibration", {}).get("resolution") == "1600x900"
          and doc["calibration"].get("bases_verified") == 0)
    expected_counts = {"troops": {"units/troops/balloon": 14, "units/troops/dragon": 14,
                                  "units/troops/minion": 1},
                       "spells": {"units/spells/rage": 4, "units/spells/freeze": 3},
                       "sieges": {"units/siege/stone_slammer": 3}}
    for v in doc["variants"]:
        off = [n["id"] for n in v["nodes"]
               if n.get("type") in ("troop", "siege", "hero")
               and (n.get("type") == "troop" and n.get("strategy") != "pattern"
                    or n.get("type") in ("siege", "hero")
                    and n.get("taps", 0) and n.get("strategy") != "pattern")]
        check(f"[{v['name']}] every dropping node is on-pattern", not off, str(off))
        empty = [n["id"] for n in v["nodes"]
                 if n.get("strategy") == "pattern" and not n.get("points")]
        check(f"[{v['name']}] every pattern node carries points", not empty, str(empty))
        comp = required_composition({"variants": [v]}).to_json()
        check(f"[{v['name']}] train counts unchanged",
              {k: comp[k] for k in expected_counts} == expected_counts, str(comp))
        check(f"[{v['name']}] calibrated centre present",
              len(v.get("calibration", {}).get("centre", [])) == 2)
    v0 = doc["variants"][0]
    spells = {n["id"]: n for n in v0["nodes"] if n.get("type") == "spell"}
    check("rage interval 1.0 / freeze 2.0 (data-driven rhythm)",
          spells["9-12_rage"].get("interval") == 1.0
          and spells["9-12_freeze"].get("interval") == 2.0)
    graph = Graph.from_dict({"name": "t", "nodes": [
        {"id": "a", "type": "delay", "params": {"seconds": 1}}]})
    check("engine still validates graphs (sanity)", graph.validate() == [])


def test_burst_rhythm():
    print("[9] burst rhythm: interval 0 -> zero sleeps; spells keep 1.0/2.0")

    def build_frame():
        rng = np.random.default_rng(11)
        f = rng.integers(20, 60, size=(900, 1600, 3), dtype=np.uint8)
        blocks = {}
        for name, x in (("b", 300), ("r", 500), ("f", 700)):
            blk = rng.integers(200, 255, size=(40, 40, 3), dtype=np.uint8)
            f[860:900, x:x + 40] = blk
            blocks[name] = (blk, x)
        return f, blocks

    frame, blocks = build_frame()
    key, kr, kf = "units/troops/testpat", "units/spells/testrage", "units/spells/testfreeze"
    vision.cache[key] = cv2.cvtColor(blocks["b"][0], cv2.COLOR_BGR2GRAY)
    vision.cache[kr] = cv2.cvtColor(blocks["r"][0], cv2.COLOR_BGR2GRAY)
    vision.cache[kf] = cv2.cvtColor(blocks["f"][0], cv2.COLOR_BGR2GRAY)
    nodes = [
        {"id": "b", "type": "troop", "template": key, "taps": 14,
         "strategy": "pattern", "points": make_line(14), "interval": 0, "after": []},
        {"id": "r", "type": "spell", "template": kr, "taps": 4,
         "strategy": "points",
         "points": [[500, 300], [510, 300], [520, 300], [530, 300]],
         "interval": 1.0, "after": ["b"]},
        {"id": "f", "type": "spell", "template": kf, "taps": 3,
         "strategy": "points", "points": [[700, 300]],
         "interval": 2.0, "after": ["r"]},
    ]
    deploy_cfg = {"nodes": nodes, "troop_bar_region": [200, 855, 1400, 910],
                  "tap_interval": 0, "select_delay": 0.05, "humanize": True,
                  "base_centre": [500, 400], "variant": "9-12"}
    ui = FakeUI(frame)
    bs = BattleScreen(ui)

    def run():
        bs.any_deployed = bs._slot_deploy(deploy_cfg)
    logs = _collect_logs(run)

    cmds = [c[1] for c in ui.device.adb_calls if c and c[0] == "shell"]
    by_taps = {}
    for cmd in cmds:
        taps = re.findall(r"input tap (\d+) (\d+)", cmd)
        sleeps = [float(v) for v in re.findall(r"sleep ([0-9.]+)", cmd)]
        by_taps[len(taps)] = (taps, sleeps)
    check("balloon burst: 14 taps in ONE command", 14 in by_taps, str(sorted(by_taps)))
    bt, bsleeps = by_taps[14]
    check("balloon: ZERO sleep between taps (interval 0)", len(bsleeps) == 0,
          str(bsleeps))
    check("rage rhythm: 4 taps + 3 on-device sleeps ~1.0s (humanized 0.55-1.5)",
          4 in by_taps and len(by_taps[4][1]) == 3
          and all(0.5 <= s <= 1.6 for s in by_taps[4][1]), str(by_taps.get(4)))
    check("freeze rhythm: 3 taps + 2 on-device sleeps ~2.0s (humanized 1.1-3.0)",
          3 in by_taps and len(by_taps[3][1]) == 2
          and all(1.05 <= s <= 3.05 for s in by_taps[3][1]), str(by_taps.get(3)))
    check("host sleeps: select pause + 7s diagnostic only (no tap sleeps)",
          ui.sleeps[:3] == [0.5, 7.0, 0.3] and set(ui.sleeps[3:]) <= {0.05},
          str(ui.sleeps[:6]))

    # fallback path (adb raises): _poll_sleep receives _drop_delay values —
    # interval 0 must yield exactly 0.0 (no artificial sleep), rage ~1.0
    class RaisingDevice(FakeDevice):
        def _run_adb(self, args, text=True, _recovered=False):
            raise RuntimeError("batch path unavailable")

    def fallback_run(node):
        ui2 = FakeUI(frame)
        ui2.device = RaisingDevice()
        bs2 = BattleScreen(ui2)

        def run2():
            bs2._slot_deploy({"nodes": [node],
                              "troop_bar_region": [200, 855, 1400, 910],
                              "tap_interval": 0, "select_delay": 0.05,
                              "humanize": True, "base_centre": [500, 400],
                              "variant": "9-12"})
        _collect_logs(run2)
        return ui2

    ui_b = fallback_run(dict(nodes[0], after=[]))
    zero = [s for s in ui_b.sleeps if s == 0.0]
    check("fallback: interval-0 node sleeps exactly 0.0 (x14)", len(zero) >= 14,
          str(ui_b.sleeps[:6]))
    check("fallback: every sleep accounted for (0 burst / 7 diag / 0.3+0.4 grabs / 0.5 select)",
          set(ui_b.sleeps) <= {0.0, 7.0, 0.3, 0.4, 0.5}, str(sorted(set(ui_b.sleeps))))
    ui_r = fallback_run(dict(nodes[1], after=[]))
    rage_s = [s for s in ui_r.sleeps if 0.5 <= s <= 1.6]
    check("fallback: rage sleeps ~1.0 via _poll_sleep", len(rage_s) >= 3,
          str(ui_r.sleeps[:6]))
    for k in (key, kr, kf):
        vision.cache.pop(k, None)


def test_glow_diag_one_shot():
    print("[7] glow-ring diagnostic: runs once, 7s delay, deploy continues")
    key = "units/troops/testpat"
    rng = np.random.default_rng(3)
    frame = rng.integers(20, 60, size=(900, 1600, 3), dtype=np.uint8)
    frame[860:900, 300:340] = rng.integers(200, 255, size=(40, 40, 3), dtype=np.uint8)
    vision.cache[key] = cv2.cvtColor(frame[865:905, 310:350], cv2.COLOR_BGR2GRAY)
    pts = make_line(14)
    node = {"id": "9-12_balloon", "type": "troop", "template": key,
            "taps": 14, "strategy": "pattern", "points": pts}
    deploy_cfg = {"nodes": [node], "troop_bar_region": [200, 855, 1400, 910],
                  "tap_interval": 0.2, "select_delay": 0.05, "humanize": False,
                  "base_centre": [500, 400], "variant": "9-12"}
    ui = FakeUI(frame)
    bs = BattleScreen(ui)

    def run():
        bs.any_deployed = bs._slot_deploy(deploy_cfg)
    logs = _collect_logs(run)
    check("7s diagnostic delay recorded once", ui.sleeps[0:2] == [0.5, 7.0]
          and ui.sleeps.count(7.0) == 1, str(ui.sleeps[:6]))
    check("probe tap at the calibrated base centre", (500, 400) in ui.clicks,
          str(ui.clicks))
    check("burst first grab 0.3s (early-exit ok when a ring measures)",
          ui.sleeps[2:3] == [0.3], str(ui.sleeps[:6]))
    check("[GLOW-DIAG] ring log line present",
          "[GLOW-DIAG] 9-12: ring" in logs, logs[-400:])
    taps = []
    for call in ui.device.adb_calls:
        if call and call[0] == "shell":
            taps += re.findall(r"input tap (\d+) (\d+)", call[1])
    check("deploy continues after the diagnostic (14 taps)", len(taps) == 14,
          f"got {len(taps)}")
    vision.cache.pop(key, None)


def test_middeploy_reboot_abort():
    print("[8] game relaunched mid-deploy -> remaining deploy aborts cleanly")
    import threading
    import time as _time
    import scenario_store
    key = "units/troops/testpat"
    rng = np.random.default_rng(5)
    frame = rng.integers(20, 60, size=(900, 1600, 3), dtype=np.uint8)
    frame[860:900, 300:340] = rng.integers(200, 255, size=(40, 40, 3), dtype=np.uint8)
    vision.cache[key] = cv2.cvtColor(frame[865:905, 310:350], cv2.COLOR_BGR2GRAY)
    nodes = [
        {"id": "wait1", "type": "delay", "seconds": 1, "after": []},
        {"id": "b", "type": "troop", "template": key, "taps": 6,
         "strategy": "pattern", "points": make_line(6), "after": ["wait1"]},
    ]
    deploy_cfg = {"nodes": nodes, "troop_bar_region": [200, 855, 1400, 910],
                  "tap_interval": 0.1, "select_delay": 0.05, "humanize": False,
                  "base_centre": [500, 400], "variant": "9-12"}
    class RebootUI(FakeUI):
        """The takeover watchdog relaunches the game during the FIRST poll
        sleep (i.e. during the delay node) — flag set right there."""

        def __init__(self, frame):
            super().__init__(frame)
            self._fired = False

        def _poll_sleep(self, s):
            self.sleeps.append(s)
            if not self._fired:
                self._fired = True
                scenario_store.set_session_flag("game_rebooted", _time.time())

    ui = RebootUI(frame)
    bs = BattleScreen(ui)
    scenario_store.set_session_flag("game_rebooted", None)  # clear

    def run():
        bs.any_deployed = bs._slot_deploy(deploy_cfg)
    logs = _collect_logs(run)
    scenario_store.set_session_flag("game_rebooted", None)
    taps = []
    for call in ui.device.adb_calls:
        if call and call[0] == "shell":
            taps += re.findall(r"input tap (\d+) (\d+)", call[1])
    check("remaining deploy aborted after the relaunch", len(taps) == 0, str(taps))
    check("abort logged",
          "game relaunched mid-deploy" in logs, logs[-300:])
    vision.cache.pop(key, None)


def test_cooperative_stop():
    print("[6] Stop cuts in-deploy delays (cooperative), caches announced in log")
    import inspect
    import threading
    import time as _time
    from core.ui_manager import UIManager

    src = inspect.getsource(BattleScreen._slot_deploy)
    check("no raw time.sleep(d) left in _slot_deploy", "time.sleep(d)" not in src)

    # the REAL cooperative poll sleep: a 6s wait must be cut by Stop in <2s
    ui = UIManager(type("H", (), {})(), type("D", (), {})())
    ui.stop_event = __import__("threading").Event()
    threading.Timer(0.5, ui.stop_event.set).start()
    t0 = _time.monotonic()
    ui._poll_sleep(6.0)
    elapsed = _time.monotonic() - t0
    check("Stop cuts a 6s poll sleep in <2s", elapsed < 2.0, f"took {elapsed:.1f}s")

    # and the scenario delay node routes through it (mock: sleeps are recorded,
    # so a delay node must NOT issue any raw time.sleep call)
    frame = np.zeros((900, 1600, 3), np.uint8)
    node = {"id": "endwait", "type": "delay", "seconds": 3}
    deploy_cfg = {"nodes": [node], "troop_bar_region": [200, 855, 1400, 910],
                  "humanize": False, "variant": "9-12"}
    ui2 = FakeUI(frame)
    bs = BattleScreen(ui2)
    t0 = _time.monotonic()
    bs._slot_deploy(deploy_cfg)
    check("delay node handled instantly through the cooperative hook",
          _time.monotonic() - t0 < 1.0 and ui2.sleeps == [3.0],
          f"sleeps={ui2.sleeps}")


if __name__ == "__main__":
    test_sequence_rules()
    test_jitter_outward()
    test_slot_deploy_pattern_flow()
    test_missing_template_skip()
    test_scenario_json()
    test_burst_rhythm()
    test_glow_diag_one_shot()
    test_middeploy_reboot_abort()
    test_cooperative_stop()
    print(f"\n=== {passed} passed, {failed} failed ===")
    sys.exit(1 if failed else 0)
