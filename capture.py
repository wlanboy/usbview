import re
import subprocess
import threading
import time
import cv2
import numpy as np

DEFAULT_DEVICE = "/dev/video0"
DEFAULT_WIDTH = 1280
DEFAULT_HEIGHT = 720
DEFAULT_FPS = 30


def list_video_devices() -> list[dict]:
    try:
        out = subprocess.check_output(
            ["v4l2-ctl", "--list-devices"],
            stderr=subprocess.DEVNULL, text=True,
        )
    except Exception:
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
    except Exception:
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


def _make_no_signal_frame(width: int, height: int) -> bytes:
    img = np.full((height, width, 3), 12, dtype=np.uint8)
    text = "KEIN SIGNAL"
    font = cv2.FONT_HERSHEY_DUPLEX
    scale = max(1.5, width / 320)
    thickness = max(2, round(scale))
    color = (0, 159, 245)  # BGR: amber
    (tw, th), _ = cv2.getTextSize(text, font, scale, thickness)
    cv2.putText(img, text, ((width - tw) // 2, (height + th) // 2), font, scale, color, thickness, cv2.LINE_AA)
    _, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return buf.tobytes()


def _device_index(device: str) -> int:
    m = re.search(r"\d+$", device)
    return int(m.group()) if m else 0


def _open_capture(device: str, width: int, height: int, fps: int) -> cv2.VideoCapture:
    cap = cv2.VideoCapture(_device_index(device), cv2.CAP_V4L2)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter.fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    cap.set(cv2.CAP_PROP_FPS, fps)
    return cap


class FrameBroadcaster:
    """Single capture thread; all stream clients read the latest frame."""

    def __init__(self) -> None:
        self._frame_lock = threading.Lock()
        self._config_lock = threading.Lock()
        self._frame: bytes | None = None
        self._has_signal: bool = False
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._settings: tuple[str, int, int, int] | None = None

    def configure(self, device: str, width: int, height: int, fps: int) -> None:
        settings = (device, width, height, fps)
        with self._config_lock:
            if settings == self._settings and self._thread and self._thread.is_alive():
                return
            self._stop.set()
            if self._thread:
                self._thread.join(timeout=3)
            self._settings = settings
            self._stop = threading.Event()
            with self._frame_lock:
                self._frame = None
                self._has_signal = False
            self._thread = threading.Thread(
                target=self._loop,
                args=(device, width, height, fps, self._stop),
                daemon=True,
            )
            self._thread.start()

    def _loop(
        self, device: str, width: int, height: int, fps: int, stop: threading.Event
    ) -> None:
        while not stop.is_set():
            cap = _open_capture(device, width, height, fps)
            try:
                while not stop.is_set():
                    ok, frame = cap.read()
                    if not ok:
                        with self._frame_lock:
                            self._has_signal = False
                        break
                    _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                    with self._frame_lock:
                        self._frame = buf.tobytes()
                        self._has_signal = True
            finally:
                cap.release()
            stop.wait(1.0)

    def latest(self) -> bytes | None:
        with self._frame_lock:
            return self._frame

    def has_signal(self) -> bool:
        with self._frame_lock:
            return self._has_signal


broadcaster = FrameBroadcaster()


def mjpeg_frames(device: str, width: int, height: int, fps: int):
    broadcaster.configure(device, width, height, fps)
    no_signal = _make_no_signal_frame(width, height)
    last: bytes | None = None
    while True:
        frame = broadcaster.latest()
        if frame is None:
            time.sleep(0.2)
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n" + no_signal + b"\r\n"
            )
        elif frame is not last:
            last = frame
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
            )
        else:
            time.sleep(0.005)
