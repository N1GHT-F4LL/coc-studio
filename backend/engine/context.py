"""RuntimeContext — the shared state handed to every block's ``run``.

Carries the already-bootstrapped singletons/objects (device, ui_manager,
vision, the OCR callable) plus per-run scratch state (``vars``) and the
cooperative ``stop_event``. Blocks read from here; they never bootstrap the
device or load assets themselves — the API layer does that once before a run.
"""
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass
class RuntimeContext:
    # Reused objects from core/ (bootstrapped by device_manager before a run).
    device: Any
    ui_manager: Any
    vision: Any
    ocr_read: Callable          # core.ocr.read_number_with_confidence

    settings: dict              # load_settings() — same settings.json contract
    logger: Any
    stop_event: Any             # threading.Event; cooperative stop (like ui_manager.stop_event)
    pause_event: Any = None     # threading.Event set while paused

    # Block-to-block shared memory for this run.
    vars: dict = field(default_factory=dict)

    # Push a run-event (dict) outward. M2 collects into a list; M4 streams to WS.
    emit: Callable[[dict], None] = lambda ev: None

    def stopped(self) -> bool:
        return self.stop_event is not None and self.stop_event.is_set()

    def wait_if_paused(self):
        while (
            self.pause_event is not None
            and self.pause_event.is_set()
            and not self.stopped()
        ):
            if self.stop_event is not None:
                self.stop_event.wait(0.2)
            else:
                import time
                time.sleep(0.2)
