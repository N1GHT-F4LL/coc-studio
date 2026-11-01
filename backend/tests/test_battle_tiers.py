"""Unit tests for the 3-tier stall-handling design (spec 2026-11-01).

Run:  cd backend && ..\\.venv\\Scripts\\python.exe tests\\test_battle_tiers.py

Tầng 1 (restart): system popup -> boot_recovery ngay tại vòng chờ.
Tầng 2 (mềm): battle timeout -> dump fast + surrender, KHÔNG restart app.
Tầng 3 (dừng có kiểm soát): 3 chu kỳ bất thường liên tiếp -> stop_event;
     2 bất thường + 1 bình thường -> counter reset.
Kèm audit: không còn `while True` thiếu lối thoát trong luồng attack.
"""
import io
import logging
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import blocks  # noqa: F401,E402  -- populate REGISTRY
import popup_guard  # noqa: E402
import screens.battle_screen as bsm  # noqa: E402
from screens.battle_screen import BattleScreen  # noqa: E402
from engine.graph import Graph  # noqa: E402

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


class FakeUI:
    def __init__(self, frame):
        self._frame = frame
        self.clicks = []
        self.sleeps = []

    def get_screen(self):
        return self._frame

    def click(self, x, y):
        self.clicks.append((int(x), int(y)))

    def _stopped(self):
        return False

    def _poll_sleep(self, s):
        self.sleeps.append(s)


class Ctx:
    """Minimal RuntimeContext stub for ReturnHome.run."""

    def __init__(self):
        self.vars = {"match_found": True}
        self.logger = logging.getLogger("test_tiers")
        self.logger.setLevel(logging.INFO)
        self.ui_manager = None
        self.settings = {}
        self.stop_calls = []
        self.stop_event = self


def test_tier2_timeout_cleanup():
    print("[1] battle never ends -> timeout -> dump(fast) + surrender, NO app restart")
    real = (bsm.BATTLE_END_TIMEOUT, bsm.BATTLE_POLL_SLEEP)
    bsm.BATTLE_END_TIMEOUT = 2
    bsm.BATTLE_POLL_SLEEP = 0.1
    frame = np.zeros((900, 1600, 3), np.uint8)   # plain: no Return Home, no popup
    ui = FakeUI(frame)
    bs = BattleScreen(ui)
    calls = {"dump": [], "surrender": [], "boot": []}
    bs.dump_remaining = lambda cfg, max_rounds=4: calls["dump"].append(max_rounds)
    bs.surrender = lambda return_home=True: calls["surrender"].append(return_home)
    popup_guard.boot_recovery = lambda: calls["boot"].append(1)
    try:
        import time as _t
        t0 = _t.monotonic()
        loc = bs.wait_for_end()
        elapsed = _t.monotonic() - t0
    finally:
        bsm.BATTLE_END_TIMEOUT, bsm.BATTLE_POLL_SLEEP = real
    check("returns None after the timeout", loc is None)
    check("timeout honored (~2s, not 170s)", 1.5 <= elapsed < 6, f"{elapsed:.1f}s")
    check("dump-leftover ran ONCE with fast rounds", calls["dump"] == [2], str(calls["dump"]))
    check("surrender(return_home=True) ran", calls["surrender"] == [True])
    check("NO app restart in the tier-2 path", calls["boot"] == [], str(calls["boot"]))


def test_tier1_popup_restart():
    print("[2] popup mid-wait -> tier 1 boot_recovery immediately (no full-timeout wait)")
    real = bsm.BATTLE_END_TIMEOUT
    bsm.BATTLE_END_TIMEOUT = 60
    banner = cv2.imread(str(popup_guard.POPUP_TPL_DIR / "Connection_lost.png"))
    f = np.zeros((900, 1600, 3), np.uint8)
    bh, bw = banner.shape[:2]
    f[345:345 + bh, 300:300 + bw] = banner
    ui = FakeUI(f)
    bs = BattleScreen(ui)
    calls = {"boot": [], "dump": [], "surrender": []}
    popup_guard.boot_recovery = lambda: calls["boot"].append(1)
    bs.dump_remaining = lambda cfg, max_rounds=4: calls["dump"].append(max_rounds)
    bs.surrender = lambda return_home=True: calls["surrender"].append(return_home)
    try:
        import time as _t
        t0 = _t.monotonic()
        loc = bs.wait_for_end()
        elapsed = _t.monotonic() - t0
    finally:
        bsm.BATTLE_END_TIMEOUT = real
    check("returns None (wait aborted)", loc is None)
    check("boot_recovery fired at the wait loop (fast, not after timeout)",
          calls["boot"] == [1] and elapsed < 10, f"{elapsed:.1f}s")
    check("no tier-2 cleanup on the tier-1 path", calls["dump"] == [] and calls["surrender"] == [])


def test_tier1_rate_gate():
    print("[2b] rate exceeded -> popup aborts the wait WITHOUT relaunching")
    real = popup_guard.recovery_rate_exceeded
    popup_guard.recovery_rate_exceeded = lambda: True
    boot = []
    popup_guard.boot_recovery = lambda: boot.append(1)
    f = np.zeros((900, 1600, 3), np.uint8)
    ui = FakeUI(f)
    bs = BattleScreen(ui)
    try:
        loc = bs.wait_for_end(timeout=3)
        check("returns None, no relaunch under the rate limit",
              loc is None and boot == [], str(boot))
    finally:
        popup_guard.recovery_rate_exceeded = real


def test_guard_wiring():
    print("[3] popup guard wired before every attack sub-task (static audit)")
    import blocks.coc_blocks as cb
    import inspect
    for block in ("EnsureHome", "EnsureTroops", "CollectResources", "FindMatch",
                  "Deploy", "ReturnHome"):
        src = inspect.getsource(getattr(cb, block).run)
        check(f"{block}.run starts with the popup guard", "guard_and_recover" in src)
    src_wfe = inspect.getsource(BattleScreen.wait_for_end)
    check("wait_for_end checks the popup inside the wait loop",
          "popup_on_frame" in src_wfe)
    src_deploy = inspect.getsource(BattleScreen._slot_deploy)
    check("deploy loop has the in-loop popup check",
          "popup_on_frame" in src_deploy and "DEPLOY_POPUP_CHECK_EVERY" in src_deploy)


def test_guard_order_dynamic():
    print("[3b] dynamic order: the guard fires BEFORE the sub-task logic")
    import blocks.coc_blocks as cb
    order = []
    real_guard = popup_guard.guard_and_recover
    real_hs = cb.HomeScreen
    popup_guard.guard_and_recover = lambda *a, **k: order.append("guard") or False
    cb.HomeScreen = type("HS", (), {"__init__": lambda self, ui: None,
                                    "collect_resources": lambda self: order.append("collect")})
    ctx = type("C", (), {})()
    ctx.ui_manager = None
    ctx.logger = logging.getLogger("t")
    ctx.vars = {}
    ctx.stop_event = None
    try:
        cb.CollectResources().run(ctx, {})
    finally:
        popup_guard.guard_and_recover = real_guard
        cb.HomeScreen = real_hs
    check("guard before collect", order == ["guard", "collect"], str(order))


def test_noprogress_counter():
    print("[4] 3 abnormal cycles -> run stops; 2 abnormal + 1 normal -> reset")
    import blocks.coc_blocks as cb

    def make_ctx():
        ctx = type("C", (), {})()
        ctx.vars = {"match_found": True}
        ctx.logger = logging.getLogger("t")
        ctx.ui_manager = None
        ctx.settings = {}
        ctx.stop_calls = []

        class Ev:
            @staticmethod
            def set():
                ctx.stop_calls.append(1)

        ctx.stop_event = Ev()
        return ctx

    real_guard = popup_guard.guard_and_recover
    real_as = cb.AttackScreen
    real_hs = cb.HomeScreen
    popup_guard.guard_and_recover = lambda *a, **k: False
    cb.AttackScreen = type("AS", (), {
        "__init__": lambda self, ui, s: None,
        "return_home": lambda self: False})          # battle timeout -> abnormal
    cb.HomeScreen = type("HS", (), {
        "__init__": lambda self, ui: None,
        "is_current_screen": lambda self: True})
    try:
        rh = cb.ReturnHome()
        rh._ensure_back_home = lambda ctx: False
        ctx = make_ctx()
        for i in (1, 2):
            rh.run(ctx, {})
            check(f"abnormal cycle {i}: counter {i}, run continues",
                  ctx.vars["noprogress_runs"] == i and ctx.stop_calls == [],
                  str(ctx.vars))
        rh.run(ctx, {})
        check("3rd abnormal cycle -> stop_event set (run stops with the reason)",
              ctx.stop_calls == [1], str(ctx.stop_calls))

        # 2 abnormal + 1 normal -> counter reset, run continues
        ctx2 = make_ctx()
        calls2 = {"n": 0}

        def scripted_return_home():
            calls2["n"] += 1
            return calls2["n"] > 2     # cycles 1-2 abnormal, cycle 3 normal

        cb.AttackScreen = type("AS2", (), {
            "__init__": lambda self, ui, s: None,
            "return_home": lambda self: scripted_return_home()})
        rh2 = cb.ReturnHome()
        rh2._ensure_back_home = lambda ctx: True
        rh2.run(ctx2, {})
        rh2.run(ctx2, {})
        rh2.run(ctx2, {})
        check("2 abnormal cycles counted then reset by the normal cycle",
              ctx2.vars["noprogress_runs"] == 0, str(ctx2.vars))
        check("stop_event never fired (run continues)", ctx2.stop_calls == [])
    finally:
        popup_guard.guard_and_recover = real_guard
        cb.AttackScreen = real_as
        cb.HomeScreen = real_hs


def test_audit_wait_loops():
    print("[5] audit: no unbounded `while True` in the attack flow")
    import inspect
    for mod, name in ((bsm, "battle_screen"),):
        src = inspect.getsource(mod)
        check(f"{name}: no `while True`", "while True" not in src)
    import screens.attack_screen as atk
    src = inspect.getsource(atk)
    check("attack_screen: no `while True`", "while True" not in src)
    import popup_guard as pg
    src = inspect.getsource(pg)
    check("popup_guard: no `while True`", "while True" not in src)
    import blocks.coc_blocks as ccb
    src = inspect.getsource(ccb)
    check("coc_blocks: no `while True`", "while True" not in src)


if __name__ == "__main__":
    test_tier2_timeout_cleanup()
    test_tier1_popup_restart()
    test_tier1_rate_gate()
    test_guard_wiring()
    test_guard_order_dynamic()
    test_noprogress_counter()
    test_audit_wait_loops()
    print(f"\n=== {passed} passed, {failed} failed ===")
    sys.exit(1 if failed else 0)
