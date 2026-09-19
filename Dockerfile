FROM python:3.14-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        v4l-utils \
        libgl1 \
        libglib2.0-0 \
        libx11-6 \
        python3-gi \
        gir1.2-glib-2.0 \
        gir1.2-gstreamer-1.0 \
        gstreamer1.0-plugins-base \
        gstreamer1.0-pipewire \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir --only-binary=:all: -r requirements.txt

COPY main.py v4l2.py stream.py wayland_capture_helper.py ./
COPY static/ static/

EXPOSE 8080

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
