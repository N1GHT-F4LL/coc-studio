"""LIVE battle-end validation — step-by-step with a screenshot after every
step, so a wrong tap is visible immediately instead of a blind 90s timeout.
"""
import sys, time
sys.path.insert(0, r"C:\Users\antoinenguyen_09\Downloads\coc-studio\backend")
import cv2
import logging
logging.basicConfig(level=logging.INFO, format="%(message)s")

from device_manager import manager
from screens.battle_screen import BattleScreen, SURRENDER_BUTTONS
from screens.home_screen import HomeScreen

OUT = r"C:\Users\antoinenguyen_09\Downloads\coc-studio\calib"
log = logging.getLogger("live")


def shot(tag):
    f = manager.ui_manager.get_screen()
    if f is not None:
        cv2.imwrite(rf"{OUT}\step_{tag}.png", f)
    return f


def tap(x, y, settle=1.5):
    manager.ui_manager.device._run_adb(["shell", "input", "tap", str(x), str(y)])
    time.sleep(settle)
    shot(f"after_{tag}")


def main():
    ok, reason = manager.connect()
    log.info("connect: %s %s", ok, reason)
    ui = manager.ui_manager
    battle = BattleScreen(ui)

    # 0) leave the army screen if open (X close via back_home)
    f = shot("start")
    if f is not None and b"Train Troops" not in b"":
        pass
    # if the army screen is up (Attack! bottom-right visible), tap Attack!
    log.info("step 1: tap Attack! (army screen bottom-right)")
    tap(1490, 800, "attack")
    f = shot("attack_screen")
    log.info("step 2: tap Find a Match (attack screen)")
    tap(250, 665, "fam")
    log.info("step 3: wait for the battle (surrender button)...")
    deadline = time.time() + 90
    seen = None
    while time.time() < deadline:
        f = ui.get_screen()
        if f is None:
            time.sleep(1.0); continue
        cv2.imwrite(rf"{OUT}\step_wait.png", f)
        flag = ui.wait_until_appears(SURRENDER_BUTTONS[0], timeout=2, silent=True,
                                     use_orb_fallback=False)
        if flag:
            seen = flag
            log.info("surrender button visible at %s — battle is live.", flag)
            break
        time.sleep(1.0)
    if not seen:
        log.info("battle not detected in 90s — see calib/step_wait.png")
        return
    time.sleep(2.0)

    # 4) THE NEW PIPELINE: surrender -> battle-end variants -> tap per kind
    log.info("=== running surrender() (the new battle-end pipeline) ===")
    battle.surrender()

    # 5) home verification
    from screens.home_screen import HomeScreen
    time.sleep(2.0)
    log.info("home after flow: %s", HomeScreen(ui).is_current_screen())
    shot("final")


if __name__ == "__main__":
    main()
