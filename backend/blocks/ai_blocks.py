"""Experimental local-AI blocks.

These are opt-in probes for AI-assisted clicking. They do not replace the
existing deterministic template/screen code.
"""
from engine.registry import BlockSpec, Param, Port, Kind, register
from core.local_vlm import locate_point, save_debug
from core.troop_recognition import recognize_bar, save_debug as save_troop_debug


@register("vlm_tap")
class VLMTap(BlockSpec):
    label = "VLM Tap (experimental)"
    category = "AI"
    inputs = [
        Param("target", Kind.Text, default="Attack button"),
        Param("min_confidence", Kind.Number, default=0.75),
        Param("region", Kind.Region, default=None),
        Param("tap", Kind.Bool, default=True),
    ]
    outputs = [
        Port("coord", Kind.Coord),
        Port("found", Kind.Bool),
        Port("confidence", Kind.Number),
        Port("tapped", Kind.Bool),
    ]

    def run(self, ctx, inputs):
        target = str(inputs.get("target") or "").strip()
        if not target:
            raise ValueError("vlm_tap: target is required")
        screen = ctx.ui_manager.get_screen()
        point = locate_point(
            screen,
            target,
            ctx.settings,
            region=inputs.get("region"),
        )
        min_conf = float(inputs.get("min_confidence", 0.75))
        should_tap = bool(inputs.get("tap", True))
        tapped = False
        coord = None
        if point.found and point.x is not None and point.y is not None and point.confidence >= min_conf:
            coord = (int(point.x), int(point.y))
            if should_tap:
                ctx.ui_manager.click(
                    coord[0], coord[1],
                    label=f"vlm:{target}",
                    meta={"confidence": point.confidence, "reason": point.reason},
                )
                tapped = True
        debug_path = save_debug(screen, target, point, ctx.settings, tapped=tapped)
        if debug_path:
            ctx.emit({"type": "log", "level": "INFO", "name": "vlm_tap", "msg": f"debug: {debug_path}"})
        return {
            "coord": coord,
            "found": bool(point.found and point.confidence >= min_conf),
            "confidence": point.confidence,
            "tapped": tapped,
        }


@register("recognize_troop_bar")
class RecognizeTroopBar(BlockSpec):
    label = "Recognize Troop Bar"
    category = "AI"
    inputs = [
        Param("region", Kind.Region, default=None),
        Param("threshold", Kind.Number, default=0.48),
    ]
    outputs = [
        Port("detected", Kind.Bool),
        Port("count", Kind.Number),
        Port("json", Kind.Text),
    ]

    def run(self, ctx, inputs):
        screen = ctx.ui_manager.get_screen()
        result = recognize_bar(
            screen,
            ctx.settings,
            region=inputs.get("region"),
            threshold=float(inputs.get("threshold", 0.48)),
        )
        debug_path = save_troop_debug(screen, result, ctx.settings)
        detections = result.get("detections", [])
        if debug_path:
            ctx.emit({"type": "log", "level": "INFO", "name": "troop_recognition", "msg": f"debug: {debug_path}"})
        import json
        return {
            "detected": bool(detections),
            "count": len(detections),
            "json": json.dumps(detections, ensure_ascii=True),
        }
