import uvicorn
from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, StreamingResponse
from starlette.staticfiles import StaticFiles

from stream import (
    DEFAULT_FPS,
    DEFAULT_HEIGHT,
    DEFAULT_WIDTH,
    CaptureSettings,
    broadcaster,
    mjpeg_frames,
)
from v4l2 import (
    DEFAULT_DEVICE,
    is_screen_device,
    is_wayland_device,
    list_screen_devices,
    list_video_devices,
    list_wayland_devices,
    parse_v4l2_formats,
    screen_formats,
    wayland_formats,
)

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
async def index():
    return FileResponse("static/index.html")


@app.get("/devices")
async def devices():
    return list_video_devices() + list_screen_devices() + list_wayland_devices()


@app.get("/formats")
async def formats(device: str = Query(default=DEFAULT_DEVICE)):
    if is_wayland_device(device):
        return wayland_formats(device)
    if is_screen_device(device):
        return screen_formats(device)
    return parse_v4l2_formats(device)


@app.get("/status")
async def status():
    return {"signal": broadcaster.has_signal()}


@app.get("/stream")
async def stream(
    device: str = Query(default=DEFAULT_DEVICE),
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    fps: int = DEFAULT_FPS,
):
    settings = CaptureSettings(device, width, height, fps)
    return StreamingResponse(
        mjpeg_frames(settings),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)
