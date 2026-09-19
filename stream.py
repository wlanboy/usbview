import re
import threading
import time
from typing import NamedTuple

import cv2
import mss
import mss.exception
import numpy as np

from v4l2 import is_screen_device

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


def _open_capture(settings: CaptureSettings) -> cv2.VideoCapture | _ScreenCapture:
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
            except mss.exception.ScreenShotError:
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
