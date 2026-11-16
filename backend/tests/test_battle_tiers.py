"""Unit tests for the 3-tier stall-handling design (spec 2026-11-01).

Run:  cd backend && ..\\.venv\\Scripts\\python.exe tests\\test_battle_tiers.py

Tầng 1 (restart): system popup -> boot_recovery ngay tại vòng chờ.
Tầng 2 (mềm): battle timeout -> dọn THEO MÀN HÌNH THỰC (_cleanup_after_timeout,
     spec 2026-11-16): battle UI -> dump fast + surrender; Return Home -> tap;
     đã về làng -> không làm gì; màn không nhận ra -> restart app (rate-limited).
     (Thiết kế 2026-11-01 "blind dump+surrender, KHÔNG restart" đã bị thay thế:
     game có thể tự kết thúc trận + nhảy về làng giữa lúc chờ — dump mù khi đó
     tap bậy thanh dưới đáy màn hình làng trong vòng lặp vô hạn.)
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


def _inject_vision_tpl(key, img):
    """Temporarily put a template into vision.cache -> returns a restore fn."""
    from core.vision import vision
    had = key in vision.cache
    old = vision.cache.get(key)
    vision.cache[key] = img

    def restore():
        if had:
            vision.cache[key] = old
        else:
            vision.cache.pop(key, None)
    return restore


def _pattern_tpl(h=40, w=80, seed=7):
    """2-D grayscale patterned template — find_template matches the GRAY frame,
    and a uniform template makes TM_CCOEFF_NORMED divide by zero variance."""
    return np.random.default_rng(seed).integers(40, 220, (h, w), dtype=np.uint8)


def _paste_tpl(frame, tpl, y, x):
    """Paste the gray pattern into all 3 BGR channels (gray conversion of the
    frame then reproduces the pattern exactly)."""
    frame[y:y + tpl.shape[0], x:x + tpl.shape[1]] = np.stack([tpl, tpl, tpl], axis=-1)


def test_tier2_timeout_cleanup():
    print("[1] timeout via wait_for_end: battle UI up -> dump(fast) + "
          "surrender(return_home=False), NO restart")
    real = (bsm.BATTLE_END_TIMEOUT, bsm.BATTLE_POLL_SLEEP)
    bsm.BATTLE_END_TIMEOUT = 2
    bsm.BATTLE_POLL_SLEEP = 0.05
    boot = []
    popup_guard.boot_recovery = lambda: boot.append(1)
    tpl = _pattern_tpl(40, 80)
    restore = _inject_vision_tpl("buttons/battle/btn_surrender", tpl)
    try:
        frame = np.zeros((900, 1600, 3), np.uint8)
        _paste_tpl(frame, tpl, 400, 700)
        ui = FakeUI(frame)
        bs = BattleScreen(ui)
        calls = {"dump": [], "surrender": [], "await": 0}
        bs.dump_remaining = lambda cfg, max_rounds=4: calls["dump"].append(max_rounds)
        bs.surrender = lambda return_home=True: calls["surrender"].append(return_home)
        bs._await_home_after_cleanup = lambda timeout=30: calls.__setitem__(
            "await", calls["await"] + 1)
        import time as _t
        t0 = _t.monotonic()
        loc = bs.wait_for_end()
        elapsed = _t.monotonic() - t0
    finally:
        bsm.BATTLE_END_TIMEOUT, bsm.BATTLE_POLL_SLEEP = real
        restore()
    check("returns None after the timeout", loc is None)
    check("timeout honored (~2s, not 170s)", 1.5 <= elapsed < 6, f"{elapsed:.1f}s")
    check("dump-leftover ran ONCE with fast rounds", calls["dump"] == [2], str(calls["dump"]))
    check("surrender(return_home=False) — wait_for_end never recurses",
          calls["surrender"] == [False], str(calls))
    check("post-surrender settle ran once", calls["await"] == 1, str(calls))
    check("NO app restart while the battle UI is up", boot == [], str(boot))


def test_tier2_cleanup_return_home():
    print("[1b] timeout cleanup, Return Home visible -> tap it (no dump/surrender)")
    tpl = _pattern_tpl(40, 120, seed=11)
    restore = _inject_vision_tpl("buttons/battle/btn_return_home", tpl)
    boot = []
    popup_guard.boot_recovery = lambda: boot.append(1)
    try:
        frame = np.zeros((900, 1600, 3), np.uint8)
        _paste_tpl(frame, tpl, 500, 800)
        expected = (860, 520)   # pasted template centre
        ui = FakeUI(frame)
        ui.scan_all = lambda anchors, use_orb_fallback=False, threshold=None: {}
        bs = BattleScreen(ui)
        calls = {"dump": [], "surrender": [], "await": 0}
        bs.dump_remaining = lambda cfg, max_rounds=4: calls["dump"].append(max_rounds)
        bs.surrender = lambda return_home=True: calls["surrender"].append(return_home)
        bs._await_home_after_cleanup = lambda timeout=30: calls.__setitem__(
            "await", calls["await"] + 1)
        bs._cleanup_after_timeout()
        check("Return Home tapped at the template centre", expected in ui.clicks,
              str(ui.clicks))
        check("no dump / no surrender / no restart / settle ran",
              calls["dump"] == [] and calls["surrender"] == []
              and calls["await"] == 1 and boot == [], f"{calls} boot={boot}")
    finally:
        restore()


def test_tier2_cleanup_already_home():
    print("[1c] timeout cleanup, already back on the home village -> do NOTHING "
          "(the game ended the battle by itself)")
    boot = []
    popup_guard.boot_recovery = lambda: boot.append(1)
    ui = FakeUI(np.zeros((900, 1600, 3), np.uint8))
    ui.scan_all = lambda anchors, use_orb_fallback=False, threshold=None: {
        "buttons/home/btn_attack": (106, 848),
        "buttons/home/btn_build": (1425, 740),
    }
    bs = BattleScreen(ui)
    calls = {"dump": [], "surrender": []}
    bs.dump_remaining = lambda cfg, max_rounds=4: calls["dump"].append(max_rounds)
    bs.surrender = lambda return_home=True: calls["surrender"].append(return_home)
    bs._cleanup_after_timeout()
    check("home detected -> no dump / no surrender / no clicks / no restart",
          calls["dump"] == [] and calls["surrender"] == []
          and ui.clicks == [] and boot == [],
          f"{calls} clicks={ui.clicks} boot={boot}")


def test_tier2_cleanup_unknown_restarts():
    print("[1d] timeout cleanup, screen unrecognizable -> restart the app "
          "(rate-limited); NO bottom-bar taps")
    real_rate = popup_guard.recovery_rate_exceeded
    popup_guard.recovery_rate_exceeded = lambda: False
    boot = []
    popup_guard.boot_recovery = lambda: boot.append(1)
    ui = FakeUI(np.zeros((900, 1600, 3), np.uint8))
    ui.scan_all = lambda anchors, use_orb_fallback=False, threshold=None: {}
    bs = BattleScreen(ui)
    calls = {"dump": [], "surrender": []}
    bs.dump_remaining = lambda cfg, max_rounds=4: calls["dump"].append(max_rounds)
    bs.surrender = lambda return_home=True: calls["surrender"].append(return_home)
    try:
        bs._cleanup_after_timeout()
    finally:
        popup_guard.recovery_rate_exceeded = real_rate
    check("unknown screen -> app restarted", boot == [1], str(boot))
    check("NO dump / NO surrender / NO clicks on the unknown screen",
          calls["dump"] == [] and calls["surrender"] == [] and ui.clicks == [],
          f"{calls} clicks={ui.clicks}")

    boot2 = []
    popup_guard.boot_recovery = lambda: boot2.append(1)
    popup_guard.recovery_rate_exceeded = lambda: True
    try:
        ui2 = FakeUI(np.zeros((900, 1600, 3), np.uint8))
        ui2.scan_all = lambda anchors, use_orb_fallback=False, threshold=None: {}
        bs2 = BattleScreen(ui2)
        bs2._cleanup_after_timeout()
        check("rate limit hit -> no restart (watchdog/noprogress own recovery)",
              boot2 == [], str(boot2))
    finally:
        popup_guard.recovery_rate_exceeded = real_rate


def test_cleanup_await_home():
    print("[1e] post-cleanup settle: taps Return Home when it appears / stops at home")
    tpl = _pattern_tpl(40, 120, seed=11)
    restore = _inject_vision_tpl("buttons/battle/btn_return_home", tpl)
    try:
        frame = np.zeros((900, 1600, 3), np.uint8)
        _paste_tpl(frame, tpl, 500, 800)
        expected = (860, 520)
        ui = FakeUI(frame)
        ui.scan_all = lambda anchors, use_orb_fallback=False, threshold=None: {}
        bs = BattleScreen(ui)
        bs._await_home_after_cleanup(timeout=0.4)
        check("settle taps Return Home when it is up", expected in ui.clicks,
              str(ui.clicks[:5]))

        ui2 = FakeUI(np.zeros((900, 1600, 3), np.uint8))
        ui2.scan_all = lambda anchors, use_orb_fallback=False, threshold=None: {
            "buttons/home/btn_attack": (106, 848),
            "buttons/home/btn_build": (1425, 740),
        }
        bs2 = BattleScreen(ui2)
        bs2._await_home_after_cleanup(timeout=2)
        check("settle stops at the home village (no clicks)", ui2.clicks == [],
              str(ui2.clicks))
    finally:
        restore()


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
    test_tier2_cleanup_return_home()
    test_tier2_cleanup_already_home()
    test_tier2_cleanup_unknown_restarts()
    test_cleanup_await_home()
    test_tier1_popup_restart()
    test_tier1_rate_gate()
    test_guard_wiring()
    test_guard_order_dynamic()
    test_noprogress_counter()
    test_audit_wait_loops()
    print(f"\n=== {passed} passed, {failed} failed ===")
    sys.exit(1 if failed else 0)
