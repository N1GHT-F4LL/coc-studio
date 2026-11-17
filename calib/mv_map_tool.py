"""MV twin-screenshot mapper — derive the shot->device linear mapping from a
user screenshot of the MEmu window taken on an adb-visible screen.

device(x, y) = offset + scale * shot(x, y)

Two-phase:
  phase 1 — hypothesis from the shot/device width ratio (scale0 = W/1600,
            offset (0,0)); each reference region located by a LOCAL match
            around the predicted position (a generous margin absorbs window
            chrome);
  phase 2 — RANSAC-style refit: least-squares (uniform scale + offset) over
            the located centres, dropping the worst outlier per round while
            any residual exceeds 10 px, until >= 3 points remain. The mapping
            with the most inliers wins; per-region residuals are printed.

Validation landmarks: the three resource icons ((1562,44)/(1562,100)/(1539,149))
must map onto their positions in the shot (green crosses on the overlay).

Usage:
  ../.venv/Scripts/python.exe -X utf8 ../calib/mv_map_tool.py shot_home.png [live_frame.png]
  (no live frame -> one is screencapped now; the live frame must show the
   same home base as the screenshot)
"""
import json
import os
import subprocess
import sys

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = HERE


def screencap():
    p = subprocess.run(["adb", "-s", "127.0.0.1:21503", "exec-out", "screencap", "-p"],
                       capture_output=True, stdin=subprocess.DEVNULL, timeout=30)
    if p.returncode != 0 or not p.stdout:
        return None
    return cv2.imdecode(np.frombuffer(p.stdout, np.uint8), cv2.IMREAD_COLOR)


def refit(pts):
    """Least-squares uniform scale + offset over (dx, dy, fx, fy) points."""
    m = len(pts)
    sx = sum(p[0] for p in pts)
    sy = sum(p[1] for p in pts)
    fx = sum(p[2] for p in pts)
    fy = sum(p[3] for p in pts)
    s = (((m * sum(p[0] * p[2] for p in pts) - sx * fx)
          / max(m * sum(p[0] ** 2 for p in pts) - sx ** 2, 1e-6))
         + ((m * sum(p[1] * p[3] for p in pts) - sy * fy)
            / max(m * sum(p[1] ** 2 for p in pts) - sy ** 2, 1e-6))) / 2
    return s, (fx - s * sx) / m, (fy - s * sy) / m


def main():
    shot_path = sys.argv[1]
    shot = cv2.imread(shot_path)
    if shot is None:
        sys.exit(f"cannot read {shot_path}")
    live = cv2.imread(sys.argv[2]) if len(sys.argv) > 2 else screencap()
    if live is None:
        sys.exit("no live adb frame — is the device connected?")

    shot_gray = cv2.cvtColor(shot, cv2.COLOR_BGR2GRAY)
    live_gray = cv2.cvtColor(live, cv2.COLOR_BGR2GRAY)

    # Reference regions ON the device (1600x900) — distinctive, far apart.
    refs = {
        "battle": (20, 730, 235, 900),     # Battle button bottom-left
        "build": (1400, 730, 1600, 900),   # Build button bottom-right
        "icon_gold": (1530, 25, 1595, 65),   # resource icons top-right
        "icon_elixir": (1530, 82, 1595, 120),
        "icon_dark": (1505, 130, 1570, 168),
    }
    centres = {k: ((a[0] + a[2]) / 2, (a[1] + a[3]) / 2) for k, a in refs.items()}

    s0 = shot.shape[1] / 1600.0
    print(f"size-ratio hypothesis: scale {s0:.4f}, offset (0,0)")

    # phase 1 — locate each region locally around the ratio prediction
    found = []
    for key, (x1, y1, x2, y2) in refs.items():
        dcx, dcy = centres[key]
        px, py = s0 * dcx, s0 * dcy
        tpl = live_gray[y1:y2, x1:x2]
        t = cv2.resize(tpl, None, fx=s0, fy=s0, interpolation=cv2.INTER_CUBIC)
        th, tw = t.shape[:2]
        wx1 = max(0, int(px - 120 - tw))
        wy1 = max(0, int(py - 120 - th))
        wx2 = min(shot_gray.shape[1], int(px + 120 + tw))
        wy2 = min(shot_gray.shape[0], int(py + 120 + th))
        win = shot_gray[wy1:wy2, wx1:wx2]
        if win.shape[0] < th or win.shape[1] < tw:
            print(f"  {key}: window clipped — skipped")
            continue
        r = cv2.matchTemplate(win, t, cv2.TM_CCOEFF_NORMED)
        _, c, _, ml = cv2.minMaxLoc(r)
        if c < 0.5:
            print(f"  {key}: no local match (conf {c:.2f}) — skipped")
            continue
        fx = wx1 + ml[0] + tw / 2
        fy = wy1 + ml[1] + th / 2
        found.append((key, dcx, dcy, fx, fy, c))
        print(f"  {key}: conf {c:.3f} found shot ({fx:.0f},{fy:.0f}) "
              f"[ratio predicted ({px:.0f},{py:.0f})]")
    if len(found) < 4:
        sys.exit(f"phase 1 located only {len(found)}/5 regions — ABORT "
                 "(wrong screen / heavy occlusion?)")

    # phase 2 — RANSAC-style refit
    pts_all = [(dcx, dcy, fx, fy, key) for key, dcx, dcy, fx, fy, _ in found]
    best = None
    drop = set()
    for _ in range(len(pts_all) - 2):
        pts = [p for p in pts_all if p[4] not in drop]
        s, ox, oy = refit(pts)
        res = [(p[4], abs(ox + s * p[0] - p[2]), abs(oy + s * p[1] - p[3])) for p in pts]
        bad = [r for r in res if max(r[1], r[2]) > 10]
        inliers = len(res) - len(bad)
        if best is None or inliers > best[0]:
            best = (inliers, s, ox, oy, set(drop), res)
        if not bad or len(pts) <= 3:
            break
        worst = max(bad, key=lambda r: max(r[1], r[2]))
        print(f"  refit: {inliers}/{len(res)} inliers — dropping outlier "
              f"{worst[0]} (residual {worst[1]:.0f}/{worst[2]:.0f})")
        drop.add(worst[0])
    assert best is not None
    inliers, scale, ox, oy, dropped, res = best
    print(f"final mapping: scale {scale:.4f} offset ({ox:.1f}, {oy:.1f}) — "
          f"{inliers}/{len(pts_all)} inliers (dropped: {sorted(dropped) or 'none'})")
    for tag, rx, ry in res:
        print(f"  {tag}: residual {rx:.1f}/{ry:.1f} px")
    if inliers < 4:
        sys.exit("fewer than 4 inliers — ABORT (no mapping emitted)")

    # validation landmarks: the 3 resource icons (device coords, plan table)
    overlay = shot.copy()
    for name, (dx, dy) in (("gold", (1562, 44)), ("elixir", (1562, 100)),
                           ("dark", (1539, 149))):
        px = int(round(ox + scale * dx))
        py = int(round(oy + scale * dy))
        if 0 <= px < overlay.shape[1] and 0 <= py < overlay.shape[0]:
            cv2.drawMarker(overlay, (px, py), (0, 255, 0), cv2.MARKER_CROSS, 16, 2)
            cv2.putText(overlay, name, (px + 6, py + 4), cv2.FONT_HERSHEY_SIMPLEX,
                        0.4, (0, 255, 0), 1, cv2.LINE_AA)
    for gx in range(0, 1601, 100):
        px = int(round(ox + scale * gx))
        if 0 <= px < overlay.shape[1]:
            cv2.line(overlay, (px, 0), (px, overlay.shape[0]), (255, 255, 0), 1)
            if gx % 200 == 0:
                cv2.putText(overlay, str(gx), (px + 2, 14), cv2.FONT_HERSHEY_SIMPLEX,
                            0.4, (0, 255, 255), 1, cv2.LINE_AA)
    for gy in range(0, 901, 100):
        py = int(round(oy + scale * gy))
        if 0 <= py < overlay.shape[0]:
            cv2.line(overlay, (0, py), (overlay.shape[1], py), (255, 255, 0), 1)
            if gy % 200 == 0:
                cv2.putText(overlay, str(gy), (4, py + 14), cv2.FONT_HERSHEY_SIMPLEX,
                            0.4, (0, 255, 255), 1, cv2.LINE_AA)

    base = os.path.splitext(os.path.basename(shot_path))[0]
    out = os.path.join(OUT, f"mv_map_{base}.png")
    cv2.imwrite(out, overlay)
    mapping = {"offset": [round(ox, 2), round(oy, 2)], "scale": round(scale, 5),
               "shot": shot_path, "inliers": inliers}
    with open(os.path.join(OUT, f"mv_map_{base}.json"), "w") as f:
        json.dump(mapping, f, indent=2)
    print(f"\noverlay: {out}\nmapping json: mv_map_{base}.json")
    print("\n===== RESULT =====")
    print(json.dumps(mapping))
    print("=====")
    print("Eyeball: the yellow grid must align with the game UI and the green "
          "crosses must sit ON the three resource icons.")


if __name__ == "__main__":
    main()
