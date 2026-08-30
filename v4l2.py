import re
import subprocess

DEFAULT_DEVICE = "/dev/video0"


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
