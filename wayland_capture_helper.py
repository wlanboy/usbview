#!/usr/bin/env python3
"""Grabs the Wayland desktop via xdg-desktop-portal ScreenCast + PipeWire.

Runs under the SYSTEM python3 (needs PyGObject and the GStreamer PipeWire
plugin), not the project's uv venv. Writes raw BGR frames of a fixed size
to stdout back-to-back, with no framing. Triggers an interactive
"Share your screen?" dialog on first start of a session.
"""

import argparse
import itertools
import sys

import gi

gi.require_version("Gst", "1.0")
from gi.repository import Gio, GLib, Gst

PORTAL_BUS_NAME = "org.freedesktop.portal.Desktop"
PORTAL_OBJECT_PATH = "/org/freedesktop/portal/desktop"
SCREENCAST_IFACE = "org.freedesktop.portal.ScreenCast"
REQUEST_IFACE = "org.freedesktop.portal.Request"

SOURCE_TYPE_MONITOR = 1
CURSOR_MODE_HIDDEN = 1

_token_counter = itertools.count()


def _next_token(prefix: str) -> str:
    return f"{prefix}{next(_token_counter)}"


class PortalError(RuntimeError):
    pass


class ScreenCastPortal:
    def __init__(self) -> None:
        self._bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        unique_name = self._bus.get_unique_name()
        self._sender_token = unique_name[1:].replace(".", "_")

    def _call_and_wait(
        self, method: str, args: tuple, arg_sig: str, extra_options: dict | None = None
    ) -> dict:
        token = _next_token("usbview")
        expected_path = f"{PORTAL_OBJECT_PATH}/request/{self._sender_token}/{token}"

        loop = GLib.MainLoop()
        outcome: dict = {}

        def on_response(_conn, _sender, _path, _iface, _signal, params, _data=None):
            code, results = params.unpack()
            outcome["code"] = code
            outcome["results"] = results
            loop.quit()

        sub_id = self._bus.signal_subscribe(
            PORTAL_BUS_NAME,
            REQUEST_IFACE,
            "Response",
            expected_path,
            None,
            Gio.DBusSignalFlags.NONE,
            on_response,
        )
        try:
            options = {"handle_token": GLib.Variant("s", token)}
            if extra_options:
                options.update(extra_options)
            self._bus.call_sync(
                PORTAL_BUS_NAME,
                PORTAL_OBJECT_PATH,
                SCREENCAST_IFACE,
                method,
                GLib.Variant(f"({arg_sig}a{{sv}})", (*args, options)),
                None,
                Gio.DBusCallFlags.NONE,
                -1,
                None,
            )
            loop.run()
        finally:
            self._bus.signal_unsubscribe(sub_id)

        if outcome.get("code") != 0:
            raise PortalError(f"{method} failed or was denied (response code {outcome.get('code')})")
        return outcome["results"]

    def create_session(self) -> str:
        session_token = _next_token("usbview_session")
        results = self._call_and_wait(
            "CreateSession",
            (),
            "",
            {"session_handle_token": GLib.Variant("s", session_token)},
        )
        return results["session_handle"]

    def select_sources(self, session_handle: str) -> None:
        self._call_and_wait(
            "SelectSources",
            (session_handle,),
            "o",
            {
                "types": GLib.Variant("u", SOURCE_TYPE_MONITOR),
                "multiple": GLib.Variant("b", False),
                "cursor_mode": GLib.Variant("u", CURSOR_MODE_HIDDEN),
            },
        )

    def start(self, session_handle: str) -> tuple[int, int | None, int | None]:
        results = self._call_and_wait("Start", (session_handle, ""), "os")
        streams = results["streams"]
        node_id, props = streams[0]
        size = props.get("size")
        width, height = (size[0], size[1]) if size else (None, None)
        return node_id, width, height

    def open_pipewire_remote(self, session_handle: str) -> int:
        variant, fd_list = self._bus.call_with_unix_fd_list_sync(
            PORTAL_BUS_NAME,
            PORTAL_OBJECT_PATH,
            SCREENCAST_IFACE,
            "OpenPipeWireRemote",
            GLib.Variant("(oa{sv})", (session_handle, {})),
            GLib.VariantType.new("(h)"),
            Gio.DBusCallFlags.NONE,
            -1,
            None,
        )
        (index,) = variant.unpack()
        return fd_list.get(index)


def stream_frames(pw_fd: int, node_id: int, width: int, height: int, fps: int) -> None:
    Gst.init(None)
    pipeline_desc = (
        f"pipewiresrc fd={pw_fd} path={node_id} ! videoconvert ! videoscale ! videorate ! "
        f"video/x-raw,format=BGR,width={width},height={height},framerate={fps}/1 ! "
        "appsink name=sink sync=false max-buffers=2 drop=true"
    )
    pipeline = Gst.parse_launch(pipeline_desc)
    sink = pipeline.get_by_name("sink")
    pipeline.set_state(Gst.State.PLAYING)
    out = sys.stdout.buffer
    try:
        while True:
            sample = sink.emit("pull-sample")
            if sample is None:
                break
            buf = sample.get_buffer()
            ok, mapinfo = buf.map(Gst.MapFlags.READ)
            if not ok:
                continue
            try:
                out.write(mapinfo.data)
                out.flush()
            finally:
                buf.unmap(mapinfo)
    finally:
        pipeline.set_state(Gst.State.NULL)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--width", type=int, required=True)
    parser.add_argument("--height", type=int, required=True)
    parser.add_argument("--fps", type=int, default=30)
    args = parser.parse_args()

    portal = ScreenCastPortal()
    try:
        session_handle = portal.create_session()
        portal.select_sources(session_handle)
        node_id, _stream_w, _stream_h = portal.start(session_handle)
        pw_fd = portal.open_pipewire_remote(session_handle)
    except PortalError as exc:
        print(f"wayland_capture_helper: {exc}", file=sys.stderr)
        return 1

    stream_frames(pw_fd, node_id, args.width, args.height, args.fps)
    return 0


if __name__ == "__main__":
    sys.exit(main())
