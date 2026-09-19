import re
import subprocess

import mss
import mss.exception

DEFAULT_DEVICE = "/dev/video0"
SCREEN_DEVICE_PREFIX = "screen:"


def list_video_devices() -> list[dict]:
    try:
        out = subprocess.check_output(
            ["v4l2-ctl", "--list-devices"],
            stderr=subprocess.DEVNULL, text=True,
        )
    except (subprocess.CalledProcessError, OSError):
        return [{"path": DEFAULT_DEVICE, "name": DEFAULT_DEVICE}]

    devices: list[dict] = []
    current_name = ""
    for line in out.splitlines():
        if not line.startswith("\t"):
            current_name = line.split("(")[0].strip().rstrip(":")
        else:
            path = line.strip()
            if re.match(r"^/dev/video\d+$", path):
                devices.append({"path": path, "name": current_name or path})
    return devices


def list_screen_devices() -> list[dict]:
    try:
        with mss.MSS() as sct:
            # index 0 is the virtual "all monitors combined" bounding box
            return [
                {"path": f"{SCREEN_DEVICE_PREFIX}{i}", "name": f"Bildschirm {i} ({m['width']}x{m['height']})"}
                for i, m in enumerate(sct.monitors[1:], start=1)
            ]
    except mss.exception.ScreenShotError:
        return []


def is_screen_device(device: str) -> bool:
    return device.startswith(SCREEN_DEVICE_PREFIX)


def screen_formats(device: str) -> list[dict]:
    try:
        index = int(device.removeprefix(SCREEN_DEVICE_PREFIX))
        with mss.MSS() as sct:
            monitors = sct.monitors
            monitor = monitors[index] if 0 < index < len(monitors) else monitors[1]
            return [{"width": monitor["width"], "height": monitor["height"], "fps": [5, 10, 15, 30]}]
    except (ValueError, mss.exception.ScreenShotError):
        return []


def parse_v4l2_formats(device: str) -> list[dict]:
    try:
        out = subprocess.check_output(
            ["v4l2-ctl", f"--device={device}", "--list-formats-ext"],
            stderr=subprocess.DEVNULL, text=True,
        )
    except (subprocess.CalledProcessError, OSError):
        return []

    results: list[dict] = []
    current: dict | None = None
    in_mjpg = False
    for line in out.splitlines():
        if "'MJPG'" in line:
            in_mjpg = True
        elif re.search(r"'\w{4}'", line):
            in_mjpg = False
        if not in_mjpg:
            continue
        m = re.search(r"Size: Discrete (\d+)x(\d+)", line)
        if m:
            current = {"width": int(m.group(1)), "height": int(m.group(2)), "fps": []}
            results.append(current)
            continue
        m = re.search(r"Interval: Discrete [\d.]+s \(([\d.]+) fps\)", line)
        if m and current is not None:
            val = float(m.group(1))
            current["fps"].append(int(val) if val == int(val) else val)
    return results
