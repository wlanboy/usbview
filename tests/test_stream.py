import time
from types import SimpleNamespace

import numpy as np
import pytest

import stream


@pytest.mark.parametrize(
    "device,expected",
    [
        ("/dev/video0", 0),
        ("/dev/video12", 12),
        ("screen:3", 3),
        ("wayland:screen", 0),
    ],
)
def test_device_index(device, expected):
    assert stream._device_index(device) == expected


def test_make_no_signal_frame_returns_valid_jpeg_bytes():
    frame = stream._make_no_signal_frame(64, 48)
    assert isinstance(frame, bytes)
    assert frame[:2] == b"\xff\xd8"  # JPEG SOI marker


def test_multipart_chunk_wraps_frame_in_boundary():
    chunk = stream._multipart_chunk(b"jpegdata")
    assert chunk.startswith(b"--frame\r\nContent-Type: image/jpeg\r\n\r\n")
    assert chunk.endswith(b"jpegdata\r\n")


class _FakeScreenCapture:
    def __init__(self, monitor_index, width, height, fps):
        self.args = (monitor_index, width, height, fps)


class _FakeWaylandScreenCapture:
    def __init__(self, width, height, fps):
        self.args = (width, height, fps)


def test_open_capture_dispatches_to_wayland_capture(monkeypatch):
    monkeypatch.setattr(stream, "_WaylandScreenCapture", _FakeWaylandScreenCapture)
    settings = stream.CaptureSettings("wayland:screen", 1280, 720, 30)
    cap = stream._open_capture(settings)
    assert isinstance(cap, _FakeWaylandScreenCapture)
    assert cap.args == (1280, 720, 30)


def test_open_capture_dispatches_to_screen_capture(monkeypatch):
    monkeypatch.setattr(stream, "_ScreenCapture", _FakeScreenCapture)
    settings = stream.CaptureSettings("screen:2", 1280, 720, 30)
    cap = stream._open_capture(settings)
    assert isinstance(cap, _FakeScreenCapture)
    assert cap.args == (2, 1280, 720, 30)


def test_find_system_python_prefers_first_working_candidate(monkeypatch):
    monkeypatch.setattr(stream.Path, "exists", lambda self: True)
    monkeypatch.setattr(stream.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0))
    assert stream._find_system_python() == "/usr/bin/python3"


def test_find_system_python_falls_back_to_which(monkeypatch):
    monkeypatch.setattr(stream.Path, "exists", lambda self: True)
    monkeypatch.setattr(
        stream.shutil, "which",
        lambda name: "/usr/local/bin/python3" if name == "python3" else None,
    )

    def fake_run(cmd, **kwargs):
        returncode = 0 if cmd[0] == "/usr/local/bin/python3" else 1
        return SimpleNamespace(returncode=returncode)

    monkeypatch.setattr(stream.subprocess, "run", fake_run)
    assert stream._find_system_python() == "/usr/local/bin/python3"


def test_find_system_python_returns_none_when_nothing_found(monkeypatch):
    monkeypatch.setattr(stream.Path, "exists", lambda self: False)
    monkeypatch.setattr(stream.shutil, "which", lambda name: None)
    assert stream._find_system_python() is None


class _FakeCapture:
    """Serves one real frame, then blocks briefly on every subsequent read."""

    def __init__(self, frame=None, keep_signal=True):
        self._served = False
        self._frame = frame if frame is not None else np.zeros((2, 2, 3), dtype=np.uint8)
        self._keep_signal = keep_signal
        self.released = False

    def read(self):
        if not self._served:
            self._served = True
            return True, self._frame
        time.sleep(0.02)
        if self._keep_signal:
            return True, self._frame
        return False, None

    def release(self):
        self.released = True


@pytest.fixture
def stop_broadcaster():
    broadcasters = []

    def register(broadcaster):
        broadcasters.append(broadcaster)
        return broadcaster

    yield register
    for b in broadcasters:
        b._stop.set()
        if b._thread:
            b._thread.join(timeout=2)


def _wait_until(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_frame_broadcaster_publishes_frames_from_capture(monkeypatch, stop_broadcaster):
    monkeypatch.setattr(stream, "_open_capture", lambda settings: _FakeCapture())
    broadcaster = stop_broadcaster(stream.FrameBroadcaster())
    settings = stream.CaptureSettings("/dev/video0", 2, 2, 30)

    broadcaster.configure(settings)

    assert _wait_until(lambda: broadcaster.latest() is not None)
    assert broadcaster.has_signal() is True


def test_frame_broadcaster_reports_no_signal_when_read_fails(monkeypatch, stop_broadcaster):
    monkeypatch.setattr(stream, "_open_capture", lambda settings: _FakeCapture(keep_signal=False))
    broadcaster = stop_broadcaster(stream.FrameBroadcaster())
    settings = stream.CaptureSettings("/dev/video0", 2, 2, 30)

    broadcaster.configure(settings)

    assert _wait_until(lambda: broadcaster.has_signal() is False and broadcaster.latest() is not None)


def test_frame_broadcaster_reconfigure_with_same_settings_is_noop(monkeypatch, stop_broadcaster):
    open_calls = []

    def fake_open_capture(settings):
        open_calls.append(settings)
        return _FakeCapture()

    monkeypatch.setattr(stream, "_open_capture", fake_open_capture)
    broadcaster = stop_broadcaster(stream.FrameBroadcaster())
    settings = stream.CaptureSettings("/dev/video0", 2, 2, 30)

    broadcaster.configure(settings)
    assert _wait_until(lambda: len(open_calls) == 1)
    first_thread = broadcaster._thread

    broadcaster.configure(settings)

    assert broadcaster._thread is first_thread
    assert len(open_calls) == 1


def test_frame_broadcaster_reconfigure_with_new_settings_restarts_capture(monkeypatch, stop_broadcaster):
    open_calls = []

    def fake_open_capture(settings):
        open_calls.append(settings)
        return _FakeCapture()

    monkeypatch.setattr(stream, "_open_capture", fake_open_capture)
    broadcaster = stop_broadcaster(stream.FrameBroadcaster())

    broadcaster.configure(stream.CaptureSettings("/dev/video0", 2, 2, 30))
    assert _wait_until(lambda: len(open_calls) == 1)

    broadcaster.configure(stream.CaptureSettings("/dev/video1", 2, 2, 30))
    assert _wait_until(lambda: len(open_calls) == 2)
    assert open_calls[1].device == "/dev/video1"


def test_mjpeg_frames_yields_no_signal_placeholder_before_first_frame(monkeypatch):
    monkeypatch.setattr(stream.broadcaster, "configure", lambda settings: None)
    monkeypatch.setattr(stream.broadcaster, "latest", lambda: None)
    settings = stream.CaptureSettings("/dev/video0", 16, 16, 30)

    gen = stream.mjpeg_frames(settings)
    chunk = next(gen)

    assert chunk.startswith(b"--frame\r\nContent-Type: image/jpeg\r\n\r\n")
    gen.close()


def test_mjpeg_frames_yields_frame_only_once_per_update(monkeypatch):
    frame_a = b"frame-a"
    frame_b = b"frame-b"
    # frame_a appears twice as the *same* object to exercise the "unchanged
    # frame" skip path (identity check), before a genuinely new frame_b.
    frames = [frame_a, frame_a, frame_b]

    monkeypatch.setattr(stream.broadcaster, "configure", lambda settings: None)
    monkeypatch.setattr(stream.broadcaster, "latest", lambda: frames.pop(0) if frames else frame_b)
    settings = stream.CaptureSettings("/dev/video0", 16, 16, 30)

    gen = stream.mjpeg_frames(settings)
    first = next(gen)
    second = next(gen)

    assert b"frame-a" in first
    assert b"frame-b" in second
    gen.close()
