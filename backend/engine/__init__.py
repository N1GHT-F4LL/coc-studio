"""Generic block-graph engine for coc-studio.

Generalizes the topo-order executor proven in ``screens/battle_screen.py``
(``_slot_deploy``) into a declarative block registry + graph runner. The engine
knows nothing about CoC; the CoC behaviour lives in ``blocks/`` which wrap the
reused ``core``/``screens`` code.
"""
