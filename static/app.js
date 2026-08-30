let formats = [];
let devices  = [];

const devSelect  = document.getElementById("dev-select");
const resSelect  = document.getElementById("res-select");
const fpsSelect  = document.getElementById("fps-select");
const fsBtn      = document.getElementById("fs-btn");
const streamImg  = document.getElementById("stream");
const viewer     = document.getElementById("viewer");
const overlay    = document.getElementById("overlay");
const dot        = document.getElementById("dot");
const statusDev  = document.getElementById("status-dev");
const statusRes  = document.getElementById("status-res");

streamImg.onload  = () => { viewer.classList.remove("loading"); };
streamImg.onerror = () => { viewer.classList.add("loading"); dot.classList.remove("live"); };

function addOption(select, value, label, isSelected) {
  const opt = document.createElement("option");
  opt.value = value;
  opt.textContent = label;
  if (isSelected) opt.selected = true;
  select.appendChild(opt);
}

let _statusTimer = null;

function startStatusPolling() {
  if (_statusTimer) return;
  _statusTimer = setInterval(async () => {
    if (!streamImg.src) return;
    try {
      const s = await fetch("/status").then(r => r.json());
      dot.classList.toggle("live", s.signal);
    } catch (_) {}
  }, 2000);
}

async function loadFormats() {
  const device = devices[devSelect.value]?.path;
  if (!device) return;
  try {
    formats = await fetch(`/formats?device=${encodeURIComponent(device)}`).then(r => r.json());
  } catch (_) { return; }

  resSelect.innerHTML = "";
  formats.forEach((f, i) => {
    addOption(resSelect, i, `${f.width}×${f.height}`, f.width === 1280 && f.height === 720);
  });

  populateFps();
}

function populateFps() {
  const fmt = formats[resSelect.value];
  if (!fmt) return;
  fpsSelect.innerHTML = "";
  fmt.fps.forEach(fps => {
    addOption(fpsSelect, fps, fps + " fps", fps === 30);
  });
}

function applySettings() {
  const device = devices[devSelect.value]?.path;
  const fmt    = formats[resSelect.value];
  const fps    = fpsSelect.value;

  if (device) statusDev.textContent = device;

  if (!device) return;

  const width  = fmt?.width  ?? 1280;
  const height = fmt?.height ?? 720;
  const fpsVal = fmt ? fps : 30;

  viewer.classList.add("loading");
  viewer.classList.remove("no-signal");
  dot.classList.remove("live");
  overlay.textContent = "Verbinde mit Capture Card…";
  streamImg.src = `/stream?device=${encodeURIComponent(device)}&width=${width}&height=${height}&fps=${fpsVal}&_=${Date.now()}`;
  statusRes.textContent = fmt ? `${width}×${height} — ${fpsVal} fps` : "—";
  startStatusPolling();
}

devSelect.addEventListener("change", () => loadFormats().then(applySettings));
resSelect.addEventListener("change", () => { populateFps(); applySettings(); });
fpsSelect.addEventListener("change", applySettings);

function toggleFullscreen() {
  if (!document.fullscreenElement) {
    viewer.requestFullscreen();
  } else {
    document.exitFullscreen();
  }
}

document.addEventListener("fullscreenchange", () => {
  fsBtn.textContent = document.fullscreenElement ? "✕" : "⛶";
});

fsBtn.addEventListener("click", toggleFullscreen);
document.addEventListener("keydown", e => { if (e.key === "f") toggleFullscreen(); });

async function init() {
  try {
    devices = await fetch("/devices").then(r => r.json());
  } catch (_) { return; }

  devices.forEach((d, i) => {
    addOption(devSelect, i, `${d.path}  –  ${d.name}`, d.path === "/dev/video0");
  });

  await loadFormats();
  applySettings();
}

init();
