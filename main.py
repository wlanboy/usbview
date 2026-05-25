from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, StreamingResponse
from starlette.staticfiles import StaticFiles
import uvicorn

from capture import (
    DEFAULT_DEVICE,
    DEFAULT_WIDTH,
    DEFAULT_HEIGHT,
    DEFAULT_FPS,
    list_video_devices,
    parse_v4l2_formats,
    mjpeg_frames,
)

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
async def index():
    return FileResponse("static/index.html")


@app.get("/devices")
async def devices():
    return list_video_devices()


@app.get("/formats")
async def formats(device: str = Query(default=DEFAULT_DEVICE)):
    return parse_v4l2_formats(device)


@app.get("/stream")
async def stream(
    device: str = Query(default=DEFAULT_DEVICE),
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    fps: int = DEFAULT_FPS,
):
    return StreamingResponse(
        mjpeg_frames(device, width, height, fps),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)
