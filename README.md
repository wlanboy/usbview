# usbview – Browser‑basierter Live‑Viewer für USB‑HDMI‑Capture‑Cards

usbview ist ein browserbasierter Live‑Viewer für USB‑HDMI‑Capture‑Cards unter Linux.
Der Dienst stellt einen HTTP‑Stream bereit, über den das angeschlossene HDMI‑Gerät direkt im Browser betrachtet werden kann — ganz ohne zusätzliche Software.

Das Tool eignet sich besonders für Server‑Hardware ohne KVM‑Switch:
Capture‑Card einstecken, Server einschalten, Browser öffnen — und schon lassen sich BIOS‑ oder UEFI‑Einstellungen bequem aus der Ferne betrachten.

## Features
- MJPEG‑Livestream ohne Neukodierung  
Direkter Zugriff auf den MJPEG‑Stream der Capture‑Card für minimale Latenz.

- Auflösung und FPS dynamisch wählbar  
Dropdown‑Auswahl basierend auf den Live‑Capabilities von v4l2-ctl.

- Mehrere Capture‑Devices auswählbar  
Praktisch für Systeme mit mehreren angeschlossenen Karten.

- Vollbild‑Modus  
Per Button, F‑Taste oder Esc umschaltbar.

- Einzelner Capture‑Thread für alle Clients  
Mehrere Browser‑Tabs teilen sich denselben Stream — ressourcenschonend und stabil.

## Voraussetzungen

- Python 3.11+
- [uv](https://github.com/astral-sh/uv)
- `v4l2-utils` (enthält `v4l2-ctl`)

```bash
sudo apt install v4l2-utils
```

---

## Capture Card prüfen

### Angeschlossene Devices auflisten

```bash
v4l2-ctl --list-devices
```

Beispielausgabe:

```
USB3.0 capture: USB3.0 captur (usb-0000:04:00.4-2):
        /dev/video0
        /dev/video1
        /dev/media0
```

> `/dev/video0` ist das eigentliche Capture-Device, `/dev/video1` meist Metadaten, `/dev/media0` das Media-Controller-Interface.

### Unterstützte Formate und Auflösungen

```bash
v4l2-ctl --device=/dev/video0 --list-formats-ext
```

Beispielausgabe (gekürzt):

```
[0]: 'MJPG' (Motion-JPEG, compressed)
    Size: Discrete 1920x1080
        Interval: Discrete 0.017s (60.000 fps)
        Interval: Discrete 0.033s (30.000 fps)
    Size: Discrete 1280x720
        Interval: Discrete 0.017s (60.000 fps)
        Interval: Discrete 0.033s (30.000 fps)
        Interval: Discrete 0.050s (20.000 fps)
[1]: 'YUYV' (YUYV 4:2:2)
    Size: Discrete 1920x1080
        Interval: Discrete 0.100s (10.000 fps)
```

> usbview nutzt ausschließlich den MJPEG-Codec — optimale Performance bei minimaler CPU-Last.

### Aktuelle Einstellungen eines Devices abfragen

```bash
v4l2-ctl --device=/dev/video0 --all
```

### Kamerabild testweise mit ffplay anzeigen

```bash
ffplay -f v4l2 -input_format mjpeg -video_size 1280x720 -framerate 30 /dev/video0
```

---

## Installation & Start

### Lokal (mit uv)

```bash
uv sync
uv run python main.py
```

### Docker

Requirements-Datei aktualisieren (nach Abhängigkeitsänderungen):

```bash
uv pip compile pyproject.toml -o requirements.txt
```

Image bauen:

```bash
docker build -t usbview .
```

Container starten:

```bash
docker run --name usbview --rm --device=/dev/video0 -p 8080:8080 usbview
```

Bei mehreren Capture-Devices und als Daemon:

```bash
docker run --name usbview -d --device=/dev/video0 --device=/dev/video1 -p 8080:8080 usbview
```

Der Server lauscht auf `http://0.0.0.0:8080`.  
Im Browser öffnen: **http://localhost:8080**

### Aus dem Netzwerk erreichbar

Da der Server auf `0.0.0.0` bindet, ist er im lokalen Netz direkt erreichbar:

```
http://<ip-des-rechners>:8080
```

---

## Projektstruktur

```
usbview/
├── main.py          # FastAPI-App und HTTP-Routen
├── capture.py       # V4L2-Parsing, FrameBroadcaster, Stream-Generator
├── static/
│   ├── index.html   # Oberfläche
│   ├── style.css    # Styling
│   └── app.js       # Frontend-Logik (Dropdowns, Fullscreen)
└── pyproject.toml
```

## API

| Methode | Route | Beschreibung |
|---------|-------|--------------|
| `GET` | `/` | HTML-Oberfläche |
| `GET` | `/devices` | Liste aller `/dev/video*`-Devices mit Namen |
| `GET` | `/formats?device=/dev/video0` | MJPG-Auflösungen und FPS des Devices |
| `GET` | `/stream?device=...&width=...&height=...&fps=...` | MJPEG-Multipart-Stream |

## Tastenkürzel

| Taste | Funktion |
|-------|----------|
| `F` | Vollbild ein/aus |
| `Esc` | Vollbild beenden |
