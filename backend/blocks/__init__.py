"""Importing this package registers every block into engine.registry.REGISTRY.

The submodules are imported for their @register side effects. Import this
package (``import blocks``) once at startup before serving /api/blocks or
running a graph.

DESCRIPTIONS holds the human "how to use" text for each block (shown in the GUI
palette tooltip + parameter panel). Kept here so all copy lives in one place.
"""
from engine.registry import REGISTRY

from . import coc_blocks      # noqa: F401
from . import vision_blocks   # noqa: F401
from . import input_blocks    # noqa: F401
from . import ocr_blocks      # noqa: F401
from . import control_blocks  # noqa: F401
from . import logic_blocks    # noqa: F401
from . import util_blocks     # noqa: F401

DESCRIPTIONS = {
    # CoC
    "ensure_home": "Bring Clash of Clans to the foreground, wait for the home/village screen, close startup popups and zoom out; restart the game if the screen is lost. PUT THIS AT THE START of every farm graph.",
    "ensure_troops": "Train the army MANUALLY to match a scenario (e.g. dragon_balloon → 14 dragon + 14 balloon + 1 minion). Open the army (tap Attack on the village, then Train Troops) → VERIFY each section by count label + unit cards: if it matches the cached army for this Run, keep it. If the account's camp is smaller/larger than the plan's designed_capacity, dragon/balloon counts are auto-scaled (keeping ~50:50) and leftover housing is filled with archers until full. The scaled army is cached for this Run session only (Stop/Start clears it). Variant selection: 'random' = weighted random, 'rotate' = cycle the variants in their listed order (1,2,3,4,1,...); the deploy block reuses the variant trained here. PUT THIS AT THE START of the cycle. Needs troop FACE templates at units/roster/<name>.",
    "collect_resources": "Collect every full gold/elixir/dark mine on the village screen. Must be on home (place after ensure_home).",
    "find_match": "GUARANTEES the village is zoomed all the way out first (uiautomator2 pinch, every cycle — skipped when the camera is already maxed), THEN taps Attack → Find a Match → reads loot, and holds the first base whose loot meets the Min gold / elixir / dark elixir thresholds (tap Next to skip bases below them, up to a max, then bail). 0 = ignore that resource. These override settings.json 'farm'. Sets match_found. Must be on home.",
    "deploy": "Enter the battle, zoom out fully (centered), then deploy troops. Leave 'scenario' empty = use the army in settings; enter a scenario name (e.g. 'Thrower') to deploy by that scenario. Variant selection: 'random' = weighted random, 'rotate' = cycle the variants in their listed order (1,2,3,4,1,... persisted across restarts). If ensure_troops ran, the variant it trained is reused regardless. Zoom out = pinch to max zoom-out from screen centre before dropping (plan coordinates assume the fully zoomed-out view). Tap interval = delay between drop taps; Select delay = pause after picking a unit on the bar — lower both to deploy faster (too low can drop taps). Humanize drops = jitter line spacing/timing so deploys aren't robotically even (off = exact even spacing). Only runs when match_found=true.",
    "return_home": "Wait for the battle to end → tap Return Home → close popups, then CONFIRM the village screen is showing. If home is not confirmed (battle-end timeout, stuck popup...), the game is restarted immediately and home is re-verified. Only runs when match_found=true; sets vars['home'] and outputs 'home' (Bool).",
    "treasure_event": "If the Treasure event banner is active (hammer icon on the bottom banner strip), tap the chest open (4 taps), wait for the reward, then press Return Home. Silent no-op when the event is not running. Place after return_home.",
    "request_clan_troops": "Request troops from the Clan Castle on the attack-prep screen (if the button is shown).",
    # Control
    "delay": "Pause for 'seconds' seconds. Interruptible the moment Stop is pressed.",
    "if": "Branch: connect a Bool (e.g. from 'compare') into 'cond'. cond=true runs the 'then' branch, false runs 'else'. Connect the next block to the then/else port.",
    "loop_n": "Re-run ONE saved graph ('graph_ref') 'times' times. Continuous farming: loop_n(graph_ref=farm_cycle, times=50). Press Stop to stop.",
    "loop_until": "Run a saved graph until the variable 'until_var' = true (use the set_flag block to set it) or 'max_iters' is reached.",
    # Vision
    "wait_template": "Wait for a template (asset) to appear within 'timeout' seconds. Returns coord + found. Use it to wait for a button/screen before tapping.",
    "is_screen": "Check whether multiple anchors (several templates, comma-separated) all appear together → matched. Use it for screen detection.",
    "find_template": "Find one template on the current screen → coord + found. Connect 'coord' into a Tap block to tap exactly where it was found.",
    "is_home": "Returns true if on the village (home) screen. Connect into if to branch.",
    "is_attack": "Returns true if on the attack / find-a-match screen.",
    "is_battle": "Returns true if currently in a battle.",
    # Input
    "tap": "Tap once at 'coord'. Connect coord from find_template, or type the coordinates in directly.",
    "tap_template": "Find a template then tap straight on it (combines find_template + tap). Handy when you just need to press a button.",
    "swipe_line": "Swipe from 'start' to 'end' (two coordinates).",
    "pinch": "Pinch zoom in/out. E.g. direction='out' to zoom out and see the whole village.",
    # OCR
    "read_number": "Read one integer inside 'region' [x1,y1,x2,y2] via OCR.",
    "read_loot": "Read the enemy loot (gold/elixir/dark) on the scout screen. Connect the numbers into compare/if to decide whether to attack or skip.",
    "loot_ge": "Read the number in 'region' and compare it ≥ 'threshold' → Bool (ok).",
    # Logic
    "const_number": "A constant number, used as a data-edge source — e.g. a loot threshold to compare against.",
    "const_bool": "A constant true/false, used as a data-edge source.",
    "compare": "Compare: a (op) b → Bool. E.g. connect loot.gold into a, op='>=', b=500000. Connect 'result' into if.cond.",
    "logic_and": "AND two Bools → true when both are true.",
    "logic_or": "OR two Bools → true when at least one is true.",
    "logic_not": "NOT a Bool (invert true/false).",
    # Util
    "log": "Write one 'message' line to the Run console — for debugging a graph.",
    "close_popups": "Scan for and close any open popups (Close/OK buttons).",
    "restart_game": "Restart Clash of Clans (used to recover when the bot gets stuck).",
    "set_flag": "Set the ctx variable 'name' = 'value'. Use it as a stop condition for loop_until.",
}

# Attach descriptions to the registered block classes (single source of copy).
for _type, _desc in DESCRIPTIONS.items():
    if _type in REGISTRY:
        REGISTRY[_type].description = _desc
