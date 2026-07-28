"""Reconnect-popup dismissal — single shared implementation.

CoC throws these popups when the session is interrupted. Both leave the
village drawn behind a dim overlay, so screen detection would falsely
succeed; we must tap their reload button to get a live session back.
``reload_game`` = "Anyone there? / disconnected due to inactivity" (RELOAD
GAME); ``reload_connection`` = "Connection lost / Another device is
connecting to this Village" (RELOAD). The latter fires mid-cycle when more
than one client reads the screen at once (e.g. the browser DeviceView
streaming while a run is in progress).

Moved here from ``blocks/coc_blocks.py`` so the blocks layer consumes it via
``screens.facade`` instead of owning screen-recovery logic itself.
"""
import logging

from core.vision import vision

logger = logging.getLogger(__name__)

RECONNECT_BUTTONS = ("icons/status/reload_game", "icons/status/reload_connection")


def dismiss_reconnect_popup(ui, log=None, settle=8.0):
    """Tap any visible reconnect popup's reload button. Returns True if it acted.

    Safe to call anywhere a stale session might surface (startup or mid-cycle):
    it's a no-op when no popup is present.
    """
    screen = ui.get_screen()
    if screen is None:
        return False
    for key in RECONNECT_BUTTONS:
        if key not in vision.cache:
            continue
        loc = vision.find_template(screen, key, threshold=0.8, use_orb_fallback=False)
        if loc:
            (log or logger).warning("[reconnect] %s popup — tapping reload.", key.rsplit("/", 1)[-1])
            ui.click(*loc)
            ui._poll_sleep(settle)
            return True
    return False
