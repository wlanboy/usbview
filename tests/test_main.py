import asyncio

from starlette.responses import FileResponse, StreamingResponse

import main


def run(coro):
    return asyncio.run(coro)


def test_index_serves_static_html():
    response = run(main.index())
    assert isinstance(response, FileResponse)
    assert response.path == "static/index.html"


def test_devices_combines_all_sources(monkeypatch):
    monkeypatch.setattr(main, "list_video_devices", lambda: [{"path": "/dev/video0", "name": "Cam"}])
    monkeypatch.setattr(main, "list_screen_devices", lambda: [{"path": "screen:1", "name": "Screen 1"}])
    monkeypatch.setattr(main, "list_wayland_devices", lambda: [{"path": "wayland:screen", "name": "Wayland"}])

    result = run(main.devices())

    assert result == [
        {"path": "/dev/video0", "name": "Cam"},
        {"path": "screen:1", "name": "Screen 1"},
        {"path": "wayland:screen", "name": "Wayland"},
    ]


def test_formats_routes_wayland_device(monkeypatch):
    monkeypatch.setattr(main, "is_wayland_device", lambda device: True)
    monkeypatch.setattr(main, "is_screen_device", lambda device: False)
    monkeypatch.setattr(main, "wayland_formats", lambda device: ["wayland-formats"])
    monkeypatch.setattr(main, "screen_formats", lambda device: ["screen-formats"])
    monkeypatch.setattr(main, "parse_v4l2_formats", lambda device: ["v4l2-formats"])

    assert run(main.formats(device="wayland:screen")) == ["wayland-formats"]


def test_formats_routes_screen_device(monkeypatch):
    monkeypatch.setattr(main, "is_wayland_device", lambda device: False)
    monkeypatch.setattr(main, "is_screen_device", lambda device: True)
    monkeypatch.setattr(main, "wayland_formats", lambda device: ["wayland-formats"])
    monkeypatch.setattr(main, "screen_formats", lambda device: ["screen-formats"])
    monkeypatch.setattr(main, "parse_v4l2_formats", lambda device: ["v4l2-formats"])

    assert run(main.formats(device="screen:1")) == ["screen-formats"]


def test_formats_routes_v4l2_device_by_default(monkeypatch):
    monkeypatch.setattr(main, "is_wayland_device", lambda device: False)
    monkeypatch.setattr(main, "is_screen_device", lambda device: False)
    monkeypatch.setattr(main, "wayland_formats", lambda device: ["wayland-formats"])
    monkeypatch.setattr(main, "screen_formats", lambda device: ["screen-formats"])
    monkeypatch.setattr(main, "parse_v4l2_formats", lambda device: ["v4l2-formats"])

    assert run(main.formats(device="/dev/video0")) == ["v4l2-formats"]


def test_formats_default_device_query_resolves_to_default_device():
    # main.formats's `device` param defaults to Query(default=DEFAULT_DEVICE);
    # FastAPI resolves that sentinel to a plain string at request time, but
    # calling the function directly (as these unit tests do) skips that
    # resolution, so assert on the underlying Query object's default instead.
    (device_param,) = main.formats.__defaults__
    assert device_param.default == main.DEFAULT_DEVICE


def test_status_reports_broadcaster_signal(monkeypatch):
    monkeypatch.setattr(main.broadcaster, "has_signal", lambda: True)
    assert run(main.status()) == {"signal": True}

    monkeypatch.setattr(main.broadcaster, "has_signal", lambda: False)
    assert run(main.status()) == {"signal": False}


def test_stream_builds_capture_settings_from_query_params(monkeypatch):
    seen = {}

    def fake_mjpeg_frames(settings):
        # Recorded eagerly: mjpeg_frames() itself is a generator function, so
        # a body that only runs on iteration would never fire in this test.
        seen["settings"] = settings
        return iter([b"chunk"])

    monkeypatch.setattr(main, "mjpeg_frames", fake_mjpeg_frames)

    response = run(main.stream(device="/dev/video1", width=640, height=480, fps=15))

    assert isinstance(response, StreamingResponse)
    assert response.media_type == "multipart/x-mixed-replace; boundary=frame"
    assert seen["settings"] == main.CaptureSettings("/dev/video1", 640, 480, 15)


def test_stream_uses_plain_defaults_for_width_height_fps_when_omitted(monkeypatch):
    # `device` defaults to a Query(...) sentinel that only FastAPI's request
    # handling resolves, so it is passed explicitly here; width/height/fps
    # are plain literals and resolve correctly even when called directly.
    seen = {}

    def fake_mjpeg_frames(settings):
        seen["settings"] = settings
        return iter([b"chunk"])

    monkeypatch.setattr(main, "mjpeg_frames", fake_mjpeg_frames)

    run(main.stream(device=main.DEFAULT_DEVICE))

    assert seen["settings"] == main.CaptureSettings(
        main.DEFAULT_DEVICE, main.DEFAULT_WIDTH, main.DEFAULT_HEIGHT, main.DEFAULT_FPS
    )
