"""Scan the Windows LiveKernelReports WATCHDOG dump for driver-name evidence.

Read-only: walks the first 300MB of the kernel live dump and counts every
`*.sys` name it can find. GPU/emulator-related drivers are reported separately
from the overall frequency table — the driver tied to a graphics TDR is
usually among the most-referenced modules in the dump.
"""
import os
import re
import sys

DUMP = r"C:\WINDOWS\LiveKernelReports\WATCHDOG\WATCHDOG-20261028-2334.dmp"
LIMIT = 300 * 1024 * 1024
GPU_KEYS = ("nvlddmkm", "amdkmdag", "amdkmdap", "igdkm", "nvapi", "nvlddmkm",
            "memu", "gyro", "mvgkx", "hgdb", "vk_swiftshader", "nvwgf", "nvcap")


def main():
    if not os.path.exists(DUMP):
        print("dump not found:", DUMP)
        return
    size = os.path.getsize(DUMP)
    print(f"dump size: {size / 1e6:.0f} MB — scanning first {min(size, LIMIT) / 1e6:.0f} MB...")
    names = {}
    pat = re.compile(rb"[A-Za-z0-9_\\.-]{3,60}\.sys")
    with open(DUMP, "rb") as f:
        pos, tail = 0, b""
        while pos < min(size, LIMIT):
            f.seek(pos)
            buf = tail + f.read(8 * 1024 * 1024)
            for m in pat.finditer(buf):
                n = m.group(0).decode("ascii", "ignore").lstrip("\\").lower()
                names[n] = names.get(n, 0) + 1
            tail = buf[-64:]
            pos += 8 * 1024 * 1024
    gpu_like = sorted(n for n in names if any(k in n for k in GPU_KEYS))
    print("GPU/emulator drivers present in dump:")
    for n in gpu_like:
        print("  ", n, "x", names[n])
    print("top-12 .sys by frequency:")
    for n, c in sorted(names.items(), key=lambda kv: -kv[1])[:12]:
        print(f"   {n} x{c}")


if __name__ == "__main__":
    main()
