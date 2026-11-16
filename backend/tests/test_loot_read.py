"""Golden tests for the 2026-11-02 loot-reading rework (no device).

Fixtures are REAL scout frames captured from this device (passively, during a
live bot run) with the visually-verified loot values encoded in the filename:

  loot_scout_2077641_1941363_19894.png   — rich base (values match the bot's
                                           own log line for that base)
  loot_scout_846254_447633_7771.png      — mid base (dark digit verified at 4x)
  loot_scout_fade_gold_unreadable.png    — post-acceptance transition frame:
                                           the loot panel is fading, gold is
                                           unreadable (-> 0), elixir/dark still
                                           readable, no crash.

Run:  ../.venv/Scripts/python.exe -X utf8 -I tests/test_loot_read.py
"""
import inspect
import io
import json
import contextlib
import os
import sys
import time

import cv2

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
sys.path.insert(0, BACKEND)

from core.ocr import warmup_ocr  # noqa: E402
from screens.attack_screen import AttackScreen  # noqa: E402

FIXTURES = os.path.join(HERE, "fixtures")
passed = failed = 0


def check(name, cond, extra=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS {name}")
    else:
        failed += 1
        print(f"  FAIL {name} {extra}")


def main():
    print("[loot] golden frames + schema + latency for the ROI rework")
    with open(os.path.join(BACKEND, "data", "settings.json"), encoding="utf-8") as f:
        settings = json.load(f)
    warmup_ocr()
    screen_reader = AttackScreen(None, settings)

    golden = {
        "loot_scout_2077641_1941363_19894.png": (2077641, 1941363, 19894),
        "loot_scout_846254_447633_7771.png": (846254, 447633, 7771),
    }
    for name, expected in golden.items():
        frame = cv2.imread(os.path.join(FIXTURES, name))
        assert frame is not None, name
        t0 = time.perf_counter()
        loot, conf = screen_reader._read_loot(frame, settings["attack"])
        dt = time.perf_counter() - t0
        check(f"{name}: gold={expected[0]:,}", loot["gold"] == expected[0],
              str(loot))
        check(f"{name}: elixir={expected[1]:,}", loot["elixir"] == expected[1],
              str(loot))
        check(f"{name}: dark={expected[2]:,}", loot["dark_elixir"] == expected[2],
              str(loot))
        check(f"{name}: one _read_loot call <= 1.5s (took {dt:.2f}s)", dt <= 1.5)

    # fading loot panel: gold unreadable -> 0, others still read, no crash
    frame = cv2.imread(os.path.join(FIXTURES, "loot_scout_fade_gold_unreadable.png"))
    loot, conf = screen_reader._read_loot(frame, settings["attack"])
    check("fade frame: gold unreadable -> 0", loot["gold"] == 0, str(loot))
    check("fade frame: elixir still read", loot["elixir"] == 1941363, str(loot))
    check("fade frame: dark still read", loot["dark_elixir"] == 19894, str(loot))

    # missing loot_rois -> clear error path, zeros, no crash (acceptance #5)
    buf = io.StringIO()
    with contextlib.redirect_stdout(io.StringIO()):
        loot, conf = screen_reader._read_loot(frame, {"attack": {}})
    check("missing loot_rois -> zeros, no crash",
          loot == {"gold": 0, "elixir": 0, "dark_elixir": 0}, str(loot))

    # acceptance #2: no template matching / anchor scanning inside _read_loot
    src = inspect.getsource(AttackScreen._read_loot)
    check("_read_loot has no matchTemplate/scan_all/icon anchoring",
          all(s not in src for s in
              ("matchTemplate", "scan_all", "_regions_from_resource_icons",
               "_region_from_icon", "LOOT_ICON")),
          "")

    # ROI coordinates live in settings, never hardcoded in Python — walk the
    # function's AST constants (docstring excluded) and forbid the ROI numbers
    import ast
    fn = ast.parse(src.strip()).body[0]
    consts = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Constant):
            v = node.value
            if isinstance(v, str):
                consts.add(v)
            elif isinstance(v, (int, float)) and not isinstance(v, bool):
                consts.add(str(int(v)) if float(v).is_integer() else str(v))
    doc_node = (fn.body[0].value if fn.body and isinstance(fn.body[0], ast.Expr)
                and isinstance(fn.body[0].value, ast.Constant) else None)
    if doc_node is not None:
        consts.discard(doc_node.value)
    for literal in ("74", "110", "215", "160", "202", "262"):
        check(f"_read_loot has no hardcoded ROI literal {literal}",
              literal not in consts,
              f"found in constants: {sorted(consts)}")

    print(f"\n=== {passed} passed, {failed} failed ===")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
