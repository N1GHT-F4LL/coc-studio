"""coc-studio backend entrypoint.

Run:  python backend/main.py   (from repo root)
  or: python main.py           (from backend/)

Puts ``backend/`` on sys.path so the reused ``core`` / ``screens`` packages
resolve with their original top-level imports (``from core.vision import
vision``), exactly as they did under coc_bot/.
"""
import os
import sys
import logging
import threading
import webbrowser

# --- make backend/ importable as the package root (mirrors coc_bot/) --------
BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

# The reused screens/ log unicode (→, ×) in deploy messages. The Windows console
# defaults to cp1252 and the StreamHandler would raise UnicodeEncodeError, so
# force UTF-8 on stdout/stderr (no change to core/logging_utils).
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except Exception:
        pass

import uvicorn  # noqa: E402

from core.logging_utils import setup_logging  # noqa: E402
from api.app import create_app  # noqa: E402

HOST = "127.0.0.1"
PORT = 8000

app = create_app()


def _open_browser():
    webbrowser.open(f"http://{HOST}:{PORT}/")


def main():
    setup_logging(logging.INFO)
    logger = logging.getLogger(__name__)
    logger.info("Starting coc-studio backend on http://%s:%d", HOST, PORT)

    # Quieten the per-request HTTP access log (device-status/assets polling) and
    # the per-connection websockets chatter — they drown out the bot's own logs.
    # Keep uvicorn.error (startup + real errors) and our [INFO] bot logs.
    logging.getLogger("websockets").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

    # Open the browser shortly after the server is up (only when a built SPA
    # exists; during dev the user uses the Vite server on :5173). Set
    # COC_OPEN_BROWSER=0 to suppress (start.ps1 -Dev does this).
    static_dir = os.path.join(BACKEND_DIR, "static")
    if os.path.isdir(static_dir) and os.environ.get("COC_OPEN_BROWSER", "1") != "0":
        threading.Timer(1.0, _open_browser).start()

    # log_config=None: don't let uvicorn install its own loggers/format. Its
    # loggers then propagate to the root handler (our ColorFormatter), so
    # everything reads as one consistent "[INFO] ..." stream instead of mixing in
    # uvicorn's "INFO:" lines.
    uvicorn.run(app, host=HOST, port=PORT, log_level="info",
                access_log=False, log_config=None)


if __name__ == "__main__":
    main()
