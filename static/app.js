let formats = [];
let devices  = [];

const devSelect  = document.getElementById("dev-select");
const resSelect  = document.getElementById("res-select");
const fpsSelect  = document.getElementById("fps-select");
const fsBtn      = document.getElementById("fs-btn");
const streamImg  = document.getElementById("stream");
const viewer     = document.getElementById("viewer");
const dot        = document.getElementById("dot");
const statusDev  = document.getElementById("status-dev");
const statusRes  = document.getElementById("status-res");

streamImg.onload  = () => { viewer.classList.remove("loading"); dot.classList.add("live"); };
streamImg.onerror = () => { viewer.classList.add("loading");    dot.classList.remove("live"); };

async function loadFormats() {
  const device = devices[devSelect.value]?.path;
  if (!device) return;
  try {
    formats = await fetch(`/formats?device=${encodeURIComponent(device)}`).then(r => r.json());
  } catch (_) { return; }

  resSelect.innerHTML = "";
  formats.forEach((f, i) => {
    const opt = document.createElement("option");
    opt.value = i;
    opt.textContent = `${f.width}×${f.height}`;
    if (f.width === 1280 && f.height === 720) opt.selected = true;
    resSelect.appendChild(opt);
  });

  populateFps();
}

function populateFps() {
  const fmt = formats[resSelect.value];
  if (!fmt) return;
  fpsSelect.innerHTML = "";
  fmt.fps.forEach(fps => {
    const opt = document.createElement("option");
    opt.value = fps;
    opt.textContent = fps + " fps";
    if (fps === 30) opt.selected = true;
    fpsSelect.appendChild(opt);
  });
}

function applySettings() {
  const device = devices[devSelect.value]?.path;
  const fmt    = formats[resSelect.value];
  const fps    = fpsSelect.value;
  if (!device || !fmt) return;

  viewer.classList.add("loading");
  dot.classList.remove("live");
  streamImg.src = `/stream?device=${encodeURIComponent(device)}&width=${fmt.width}&height=${fmt.height}&fps=${fps}&_=${Date.now()}`;
  statusDev.textContent = device;
  statusRes.textContent = `${fmt.width}×${fmt.height} — ${fps} fps`;
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
    const opt = document.createElement("option");
    opt.value = i;
    opt.textContent = `${d.path}  –  ${d.name}`;
    if (d.path === "/dev/video0") opt.selected = true;
    devSelect.appendChild(opt);
  });

  await loadFormats();
  applySettings();
}

init();
