"""Standalone validation of the new roster faces (balloon/freeze/stone_slammer):
run the REAL EnsureTroops block against the live device and confirm the three
units actually train (x N) instead of 'not found in roster'.
"""
import logging
import sys
import threading

sys.path.insert(0, r"C:\Users\antoinenguyen_09\Downloads\coc-studio\backend")

logging.basicConfig(level=logging.INFO, format="%(message)s")

from device_manager import manager, load_settings
from engine.context import RuntimeContext
from core.vision import vision
import blocks  # noqa: F401  -- register blocks
from blocks.coc_blocks import EnsureTroops

ok, reason = manager.connect()
print("connect:", ok, reason)
if not ok:
    sys.exit(1)
manager.ensure_ocr()

events = []
ctx = RuntimeContext(
    device=manager.device,
    ui_manager=manager.ui_manager,
    vision=vision,
    ocr_read=None,
    settings=load_settings(),
    logger=logging.getLogger("validate"),
    stop_event=threading.Event(),
    pause_event=None,
    vars={"mv_scenario": "dragon_balloon"},
    emit=events.append,
)

res = EnsureTroops().run(ctx, {})
print("\nRESULT:", res)
print("troops_ready var:", ctx.vars.get("troops_ready"))
