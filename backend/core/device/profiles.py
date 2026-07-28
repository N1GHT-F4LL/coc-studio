"""Emulator profile constants.

Known ADB endpoints, executable paths, and process names per emulator
profile, plus the CoC main activity used as a launch-component fallback.
Moved verbatim out of the former ``core/device.py`` god-module.
"""

PROFILE_ENDPOINTS = {
    "android_emulator": ["127.0.0.1:5555", "127.0.0.1:5554"],
    "ldplayer": ["127.0.0.1:5555", "127.0.0.1:16384"],
    "bluestacks": ["127.0.0.1:5555", "127.0.0.1:21503"],
    "nox": ["127.0.0.1:62001"],
    "mumu": ["127.0.0.1:7555"],
}

PROFILE_EXECUTABLES = {
    "ldplayer": [
        r"C:\LDPlayer\LDPlayer9\dnplayer.exe",
        r"C:\Program Files\LDPlayer\LDPlayer9\dnplayer.exe",
    ],
    "bluestacks": [
        r"C:\Program Files\BlueStacks_nxt\HD-Player.exe",
        r"C:\Program Files\BlueStacks\HD-Player.exe",
    ],
    "nox": [
        r"C:\Program Files\Nox\bin\Nox.exe",
        r"C:\Program Files (x86)\Nox\bin\Nox.exe",
    ],
    "mumu": [
        r"C:\Program Files\Netease\MuMuPlayer-12.0\shell\MuMuPlayer.exe",
        r"C:\Program Files\Netease\MuMuPlayerGlobal-12.0\shell\MuMuPlayerGlobal.exe",
    ],
    "android_emulator": [
        r"C:\Users\Public\Android\Sdk\emulator\emulator.exe",
    ],
}

PROFILE_PROCESS_NAMES = {
    "ldplayer": ["dnplayer.exe"],
    "bluestacks": ["HD-Player.exe"],
    "nox": ["Nox.exe"],
    "mumu": ["MuMuPlayer.exe", "MuMuPlayerGlobal.exe"],
    "android_emulator": ["emulator.exe"],
}


COC_MAIN_ACTIVITY = "com.supercell.titan.GameApp"
