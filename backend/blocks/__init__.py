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
    "ensure_troops": "Train the army MANUALLY to match a scenario (e.g. Thrower → Thrower×16, Healer×6, Archer×12). Open Train Troops → CLEAR the army (the roster lights up) → match each troop's face and tap the required count (1 tap = +1 troop), scrolling the roster if hidden → return home. PUT THIS AT THE START of the cycle. Needs troop FACE templates at units/roster/<name> (capture with scripts/capture_face.py — do NOT use units/troops/* as those carry a badge). Readiness: capacity_region+target_capacity to OCR-wait until full, or wait_seconds.",
    "collect_resources": "Collect every full gold/elixir/dark mine on the village screen. Must be on home (place after ensure_home).",
    "find_match": "Tap Attack → Find a Match → read loot, then hold the first base whose loot meets the Min gold / elixir / dark elixir thresholds (tap Next to skip bases below them, up to a max, then bail). 0 = ignore that resource. These override settings.json 'farm'. Sets match_found. Must be on home.",
    "deploy": "Enter the battle and deploy troops. Leave 'scenario' empty = use the army in settings; enter a scenario name (e.g. 'Thrower') to deploy by that scenario. Tap interval = delay between drop taps; Select delay = pause after picking a unit on the bar — lower both to deploy faster (too low can drop taps). Humanize drops = jitter line spacing/timing so deploys aren't robotically even (off = exact even spacing). Only runs when match_found=true.",
    "return_home": "Wait for the battle to end → tap Return Home → close popups. Only runs when match_found=true.",
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
    "const_text": "A constant text string output. Pipe it into any block that expects a Text data port — template keys, variable names, log messages, etc.",
    "const_coord": "A fixed (x, y) screen coordinate output. Useful for hard-coding tap targets without a template scan — connect 'coord' into a Tap block.",
    "compare": "Compare: a (op) b → Bool. E.g. connect loot.gold into a, op='>=', b=500000. Connect 'result' into if.cond.",
    "logic_and": "AND two Bools → true when both are true.",
    "logic_or": "OR two Bools → true when at least one is true.",
    "logic_not": "NOT a Bool (invert true/false).",
    "log_message": "Emit a message to the run console at the chosen level (debug/info/warning/error). Connect a Text data port into 'message' to log a dynamic value, or type it directly.",
    "set_var": "Write a value into the run's variable store (ctx.vars) by name. Other blocks — Get Variable, Loop Until Var — can read it. Tip: set name='done', value='true' inside a sub-graph to break out of a loop_until.",
    "get_var": "Read a named variable from the run store and output it as Text plus an 'exists' Bool. If the variable is not set, value='' and exists=false.",
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
