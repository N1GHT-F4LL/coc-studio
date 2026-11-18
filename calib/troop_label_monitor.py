"""PASSIVE troop-count-label monitor (screencap + OCR only — zero taps).

Waits (passively, alongside the live bot) for the next army-screen opening,
then OCRs every frame for ~5s and reports:
  - whether the N/M label parses in the calibrated region (700,190,855,232)
  - where the label ACTUALLY sits (bounding box of dark text in a wider band)
so the None/None failure is judged on the real frame sequence.
"""
import sys, time
sys.path.insert(0, r"C:\Users\antoinenguyen_09\Downloads\coc-studio\backend")
import cv2
import numpy as np
from core.ocr import _get_reader
from core.vision import vision
from device_manager import manager
from screens.train_screen import TrainScreen, DELETE_TROOP_TEMPLATE

REGION = (700, 190, 855, 232)
WIDE = (600, 150, 1000, 350)

manager.connect()
ui = manager.ui_manager
train = TrainScreen(ui)
reader = _get_reader()

def ocr_region(frame, box):
    x1, y1, x2, y2 = box
    crop = frame[y1:y2, x1:x2]
    up = cv2.resize(crop, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    rgb = cv2.cvtColor(up, cv2.COLOR_BGR2RGB)
    return " ".join(str(t) for _b, t, c in reader.readtext(rgb) if c > 0.3)

def label_bbox(frame):
    """Dark stylised text bbox inside the wide band."""
    x1, y1, x2, y2 = WIDE
    g = cv2.cvtColor(frame[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
    mask = cv2.inRange(g, 0, 90)
    ys, xs = np.where(mask > 0)
    if len(xs) < 300:
        return None
    return (int(xs.min()) + x1, int(ys.min()) + y1,
            int(xs.max()) + x1, int(ys.max()) + y1)

print("passive monitor: waiting for the next army-screen opening...")
armed = False
last_log = 0.0
frames = 0
while frames < 14:
    frame = ui.get_screen()
    if frame is None:
        time.sleep(0.3); continue
    on_army = bool(vision.find_all_matches(frame, DELETE_TROOP_TEMPLATE, threshold=0.7))
    if not on_army:
        armed = False
        time.sleep(0.3); continue
    if not armed:
        print("=== army screen detected — tracking the troop count label ===")
    armed = True
    frames += 1
    txt = ocr_region(frame, REGION)
    bbox = label_bbox(frame)
    print(f"  f{frames:02d}: region OCR={txt!r}  label_bbox={bbox}")
    cv2.imwrite(rf"C:\Users\antoinenguyen_09\Downloads\coc-studio\calib\troop_label_f{frames:02d}.png", frame)
    time.sleep(0.45)
print("done — frames saved to calib/troop_label_f*.png")
