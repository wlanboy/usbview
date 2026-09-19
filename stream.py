import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import NamedTuple

import cv2
import mss
import mss.exception
import numpy as np

from v4l2 import is_screen_device, is_wayland_device

_HELPER_SCRIPT = Path(__file__).resolve().parent / "wayland_capture_helper.py"
_SYSTEM_PYTHON_CANDIDATES = ("/usr/bin/python3", "python3")

DEFAULT_WIDTH = 1280
DEFAULT_HEIGHT = 720
DEFAULT_FPS = 30


class CaptureSettings(NamedTuple):
    device: str
    width: int
    height: int
    fps: int


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


class _ScreenCapture:
    """cv2.VideoCapture-like wrapper that grabs the local desktop via mss."""

    def __init__(self, monitor_index: int, width: int, height: int, fps: int) -> None:
        self._sct = mss.MSS()
        monitors = self._sct.monitors
        self._monitor = monitors[monitor_index] if 0 < monitor_index < len(monitors) else monitors[1]
        self._width = width
        self._height = height
        self._interval = 1.0 / fps if fps > 0 else 0.0
        self._next_due = 0.0

    def read(self) -> tuple[bool, np.ndarray | None]:
        wait = self._next_due - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._next_due = time.monotonic() + self._interval
        try:
            shot = self._sct.grab(self._monitor)
        except mss.exception.ScreenShotError:
            return False, None
        frame = np.array(shot)[:, :, :3]  # BGRA -> BGR
        if (frame.shape[1], frame.shape[0]) != (self._width, self._height):
            frame = cv2.resize(frame, (self._width, self._height))
        return True, frame

    def release(self) -> None:
        self._sct.close()


def _find_system_python() -> str | None:
    """The uv venv has no PyGObject/GStreamer bindings; the Wayland portal
    capture needs the OS python3 that ships those (see wayland_capture_helper.py)."""
    for candidate in _SYSTEM_PYTHON_CANDIDATES:
        path = candidate if Path(candidate).is_absolute() else shutil.which(candidate)
        if not path or not Path(path).exists():
            continue
        check = subprocess.run(
            [path, "-c", "import gi; gi.require_version('Gst', '1.0'); from gi.repository import Gst"],
            capture_output=True,
            timeout=5,
            check=False,
        )
        if check.returncode == 0:
            return path
    return None


class _WaylandScreenCapture:
    """cv2.VideoCapture-like wrapper around the wayland_capture_helper.py subprocess."""

    def __init__(self, width: int, height: int, fps: int) -> None:
        python = _find_system_python()
        if not python:
            raise RuntimeError("no system python with PyGObject/GStreamer found for Wayland capture")
        self._width = width
        self._height = height
        self._frame_size = width * height * 3
        self._proc = subprocess.Popen(
            [python, str(_HELPER_SCRIPT), "--width", str(width), "--height", str(height), "--fps", str(fps)],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )

    def read(self) -> tuple[bool, np.ndarray | None]:
        assert self._proc.stdout is not None
        chunks = []
        remaining = self._frame_size
        while remaining > 0:
            chunk = self._proc.stdout.read(remaining)
            if not chunk:
                return False, None
            chunks.append(chunk)
            remaining -= len(chunk)
        frame = np.frombuffer(b"".join(chunks), dtype=np.uint8).reshape((self._height, self._width, 3))
        return True, frame

    def release(self) -> None:
        self._proc.terminate()
        try:
            self._proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self._proc.kill()


def _open_capture(settings: CaptureSettings) -> cv2.VideoCapture | _ScreenCapture | _WaylandScreenCapture:
    if is_wayland_device(settings.device):
        return _WaylandScreenCapture(settings.width, settings.height, settings.fps)
    if is_screen_device(settings.device):
        return _ScreenCapture(_device_index(settings.device), settings.width, settings.height, settings.fps)
    cap = cv2.VideoCapture(_device_index(settings.device), cv2.CAP_V4L2)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter.fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, settings.width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, settings.height)
    cap.set(cv2.CAP_PROP_FPS, settings.fps)
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
        self._settings: CaptureSettings | None = None

    def configure(self, settings: CaptureSettings) -> None:
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
                args=(settings, self._stop),
                daemon=True,
            )
            self._thread.start()

    def _loop(self, settings: CaptureSettings, stop: threading.Event) -> None:
        while not stop.is_set():
            try:
                cap = _open_capture(settings)
            except (mss.exception.ScreenShotError, RuntimeError, OSError):
                with self._frame_lock:
                    self._has_signal = False
                stop.wait(1.0)
                continue
            try:
                while not stop.is_set():
                    ok, frame = cap.read()
                    if not ok or frame is None:
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


def _multipart_chunk(frame: bytes) -> bytes:
    return b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"


def mjpeg_frames(settings: CaptureSettings):
    broadcaster.configure(settings)
    no_signal = _make_no_signal_frame(settings.width, settings.height)
    last: bytes | None = None
    while True:
        frame = broadcaster.latest()
        if frame is None:
            time.sleep(0.2)
            yield _multipart_chunk(no_signal)
        elif frame is not last:
            last = frame
            yield _multipart_chunk(frame)
        else:
            time.sleep(0.005)
