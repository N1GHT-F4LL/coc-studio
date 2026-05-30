"""Utility blocks — logging, popup handling, game restart, run flags."""
from engine.registry import BlockSpec, Param, Port, Kind, register
from screens.home_screen import HomeScreen
from device_manager import COC_PACKAGE


@register("log")
class Log(BlockSpec):
    label = "Log Message"
    category = "Util"
    inputs = [Param("message", Kind.Text, default="")]
    outputs = []

    def run(self, ctx, inputs):
        ctx.logger.info("[log] %s", inputs.get("message", ""))
        return {}


@register("close_popups")
class ClosePopups(BlockSpec):
    label = "Close Popups"
    category = "Util"
    inputs = []
    outputs = []

    def run(self, ctx, inputs):
        # BaseScreen.close_popups scans the known popup-close buttons.
        HomeScreen(ctx.ui_manager).close_popups()
        return {}


@register("restart_game")
class RestartGame(BlockSpec):
    label = "Restart Game"
    category = "Util"
    inputs = []
    outputs = [Port("ok", Kind.Bool)]

    def run(self, ctx, inputs):
        ok = bool(ctx.device.restart_game(COC_PACKAGE))
        return {"ok": ok}


@register("set_flag")
class SetFlag(BlockSpec):
    label = "Set Flag (var)"
    category = "Util"
    # Writes ctx.vars[name] = value — handy for loop_until's until_var.
    inputs = [Param("name", Kind.Text, default="flag"), Param("value", Kind.Bool, default=True)]
    outputs = []

    def run(self, ctx, inputs):
        name = (inputs.get("name") or "").strip()
        if name:
            ctx.vars[name] = bool(inputs.get("value"))
        return {}
