"""Central filesystem paths for the backend.

Everything is resolved relative to this file so the server can be launched
from any working directory.
"""
import os

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))

CORE_DIR     = os.path.join(BACKEND_DIR, "core")
SCREENS_DIR  = os.path.join(BACKEND_DIR, "screens")
ASSETS_DIR   = os.path.join(BACKEND_DIR, "assets")
DATA_DIR     = os.path.join(BACKEND_DIR, "data")
GRAPHS_DIR   = os.path.join(DATA_DIR, "graphs")
SCENARIOS_DIR = os.path.join(DATA_DIR, "scenarios")
STATIC_DIR   = os.path.join(BACKEND_DIR, "static")

SETTINGS_PATH = os.path.join(DATA_DIR, "settings.json")
