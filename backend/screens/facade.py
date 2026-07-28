"""Screens facade — the only import surface the blocks layer should use.

Blocks (``blocks/coc_blocks.py``) previously imported concrete screen classes
(``HomeScreen``/``AttackScreen``/``BattleScreen``/``TrainScreen``) directly,
coupling the orchestration layer to the screens package's internal layout.
This module exposes a narrow factory API instead, so screens internals can be
split/moved (e.g. ``loot.py``, ``deploy.py``) without touching blocks.
"""
from .home_screen import HomeScreen
from .attack_screen import AttackScreen
from .battle_screen import BattleScreen
from .train_screen import TrainScreen
from .popups import dismiss_reconnect_popup

__all__ = [
    "home_screen",
    "attack_screen",
    "battle_screen",
    "train_screen",
    "dismiss_reconnect_popup",
]


def home_screen(ui_manager):
    return HomeScreen(ui_manager)


def attack_screen(ui_manager, settings):
    return AttackScreen(ui_manager, settings)


def battle_screen(ui_manager):
    return BattleScreen(ui_manager)


def train_screen(ui_manager):
    return TrainScreen(ui_manager)
