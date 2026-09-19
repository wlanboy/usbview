import subprocess

import mss.exception
import pytest

import v4l2


class _FakeMSS:
    def __init__(self, monitors):
        self.monitors = monitors

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def close(self):
        pass


LIST_DEVICES_OUTPUT = """USB Capture HDMI (usb-0000:00:14.0-1):
\t/dev/video0
\t/dev/video1

Integrated Camera (usb-0000:00:14.0-2):
\t/dev/video2
"""

LIST_FORMATS_OUTPUT = """ioctl: VIDIOC_ENUM_FMT
\tType: Video Capture

\t[0]: 'MJPG' (Motion-JPEG, compressed)
\t\tSize: Discrete 1920x1080
\t\t\tInterval: Discrete 0.033s (30.000 fps)
\t\t\tInterval: Discrete 0.040s (25.000 fps)
\t\tSize: Discrete 1280x720
\t\t\tInterval: Discrete 0.033s (30.000 fps)
\t[1]: 'YUYV' (YUYV 4:2:2)
\t\tSize: Discrete 1920x1080
\t\t\tInterval: Discrete 0.033s (30.000 fps)
"""


def test_list_video_devices_parses_v4l2_ctl_output(monkeypatch):
    monkeypatch.setattr(
        subprocess, "check_output", lambda *a, **k: LIST_DEVICES_OUTPUT
    )
    assert v4l2.list_video_devices() == [
        {"path": "/dev/video0", "name": "USB Capture HDMI"},
        {"path": "/dev/video1", "name": "USB Capture HDMI"},
        {"path": "/dev/video2", "name": "Integrated Camera"},
    ]


@pytest.mark.parametrize(
    "error",
    [subprocess.CalledProcessError(1, "v4l2-ctl"), FileNotFoundError()],
)
def test_list_video_devices_falls_back_when_v4l2_ctl_unavailable(monkeypatch, error):
    def raise_error(*a, **k):
        raise error

    monkeypatch.setattr(subprocess, "check_output", raise_error)
    assert v4l2.list_video_devices() == [
        {"path": v4l2.DEFAULT_DEVICE, "name": v4l2.DEFAULT_DEVICE}
    ]


def test_list_screen_devices_skips_combined_monitor(monkeypatch):
    monitors = [
        {"width": 3200, "height": 1080},
        {"width": 1920, "height": 1080},
        {"width": 1280, "height": 720},
    ]
    monkeypatch.setattr(v4l2.mss, "MSS", lambda: _FakeMSS(monitors))
    assert v4l2.list_screen_devices() == [
        {"path": "screen:1", "name": "Bildschirm 1 (1920x1080)"},
        {"path": "screen:2", "name": "Bildschirm 2 (1280x720)"},
    ]


def test_list_screen_devices_returns_empty_without_display(monkeypatch):
    def raise_error():
        raise mss.exception.ScreenShotError("no display")

    monkeypatch.setattr(v4l2.mss, "MSS", raise_error)
    assert v4l2.list_screen_devices() == []


def test_is_screen_device():
    assert v4l2.is_screen_device("screen:1") is True
    assert v4l2.is_screen_device("/dev/video0") is False


def test_screen_formats_uses_selected_monitor(monkeypatch):
    monitors = [
        {"width": 3200, "height": 1080},
        {"width": 1920, "height": 1080},
        {"width": 1280, "height": 720},
    ]
    monkeypatch.setattr(v4l2.mss, "MSS", lambda: _FakeMSS(monitors))
    assert v4l2.screen_formats("screen:2") == [
        {"width": 1280, "height": 720, "fps": [5, 10, 15, 30]}
    ]


def test_screen_formats_falls_back_to_first_monitor_for_bad_index(monkeypatch):
    monitors = [{"width": 3200, "height": 1080}, {"width": 1920, "height": 1080}]
    monkeypatch.setattr(v4l2.mss, "MSS", lambda: _FakeMSS(monitors))
    assert v4l2.screen_formats("screen:99") == [
        {"width": 1920, "height": 1080, "fps": [5, 10, 15, 30]}
    ]


def test_screen_formats_returns_empty_for_non_numeric_index():
    assert v4l2.screen_formats("screen:not-a-number") == []


def test_is_wayland_session(monkeypatch):
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    assert v4l2.is_wayland_session() is False
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    assert v4l2.is_wayland_session() is True


def test_list_wayland_devices_requires_wayland_session(monkeypatch):
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    assert v4l2.list_wayland_devices() == []

    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    assert v4l2.list_wayland_devices() == [
        {"path": v4l2.WAYLAND_DEVICE, "name": "Bildschirm (Wayland – Freigabe-Dialog beim Start)"}
    ]


def test_is_wayland_device():
    assert v4l2.is_wayland_device(v4l2.WAYLAND_DEVICE) is True
    assert v4l2.is_wayland_device("/dev/video0") is False


def test_wayland_formats_offers_fixed_presets():
    presets = v4l2.wayland_formats(v4l2.WAYLAND_DEVICE)
    assert {"width": 1920, "height": 1080, "fps": [5, 10, 15, 30]} in presets
    assert all(p["fps"] == [5, 10, 15, 30] for p in presets)


def test_parse_v4l2_formats_only_reads_mjpg_section(monkeypatch):
    monkeypatch.setattr(
        subprocess, "check_output", lambda *a, **k: LIST_FORMATS_OUTPUT
    )
    assert v4l2.parse_v4l2_formats("/dev/video0") == [
        {"width": 1920, "height": 1080, "fps": [30, 25]},
        {"width": 1280, "height": 720, "fps": [30]},
    ]


def test_parse_v4l2_formats_returns_empty_when_v4l2_ctl_unavailable(monkeypatch):
    def raise_error(*a, **k):
        raise subprocess.CalledProcessError(1, "v4l2-ctl")

    monkeypatch.setattr(subprocess, "check_output", raise_error)
    assert v4l2.parse_v4l2_formats("/dev/video0") == []
