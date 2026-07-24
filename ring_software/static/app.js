const state = {
  connected: false,
  imuPoints: [],
  busy: false,
};

const $ = (id) => document.getElementById(id);
const refs = {
  address: $("addressInput"),
  scan: $("scanBtn"),
  connect: $("connectBtn"),
  disconnect: $("disconnectBtn"),
  deviceList: $("deviceList"),
  connectionText: $("connectionText"),
  battery: $("batteryText"),
  storage: $("storageText"),
  firmware: $("firmwareText"),
  mode: $("modeText"),
  systemBtn: $("systemBtn"),
  systemInfo: $("systemInfo"),
  systemSubtitle: $("systemSubtitle"),
  audioCountBtn: $("audioCountBtn"),
  fileIndex: $("fileIndexInput"),
  download: $("downloadBtn"),
  receive: $("receiveBtn"),
  clear: $("clearBtn"),
  clearConfirm: $("clearConfirm"),
  progressBar: $("progressBar"),
  audioResult: $("audioResult"),
  imuStart: $("imuStartBtn"),
  imuStop: $("imuStopBtn"),
  imuSubtitle: $("imuSubtitle"),
  canvas: $("imuCanvas"),
  clearLog: $("clearLogBtn"),
  eventLog: $("eventLog"),
};

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const text = await response.text();
  const data = text ? JSON.parse(text) : null;
  if (!response.ok) {
    throw new Error(data?.detail || `请求失败：${response.status}`);
  }
  return data;
}

function setBusy(button, busy, label) {
  button.disabled = busy;
  if (label) button.querySelector("span").textContent = label;
}

function addLog(kind, detail) {
  const item = document.createElement("li");
  const time = new Date().toLocaleTimeString();
  item.innerHTML = `<span>${time}</span><strong>${kind}</strong><span>${detail}</span>`;
  refs.eventLog.prepend(item);
  while (refs.eventLog.children.length > 80) {
    refs.eventLog.lastElementChild.remove();
  }
}

function updateStatus(status) {
  state.connected = Boolean(status.connected);
  refs.connectionText.textContent = state.connected
    ? `已连接 ${status.address}`
    : "未连接";
  refs.mode.textContent = status.sensor_started ? "IMU 上报中" : state.connected ? "已连接" : "待机";
  refs.imuSubtitle.textContent = status.sensor_info
    ? `${status.sensor_info.sample_rate_hz}Hz / 加速度 ±${status.sensor_info.accel_range_g}g / 陀螺仪 ±${status.sensor_info.gyro_range_dps}dps`
    : "需要先把戒指切到手势模式";
}

function updateSystemInfo(info) {
  refs.battery.textContent = `${info.battery_percent}%`;
  refs.storage.textContent = formatBytes(info.audio_storage_available);
  refs.firmware.textContent = info.firmware_version || "--";
  refs.systemSubtitle.textContent = info.model ? `型号 ${info.model}` : "系统信息已刷新";

  const rows = [
    ["型号", info.model || "--"],
    ["SN", info.sn || "--"],
    ["CPUID", info.cpuid || "--"],
    ["系统时间", info.system_time_display?.local || "--"],
    ["充电状态", info.battery_charging ? "充电中" : "未充电"],
  ];
  refs.systemInfo.innerHTML = rows
    .map(([key, value]) => `<div><dt>${key}</dt><dd>${escapeHtml(value)}</dd></div>`)
    .join("");
}

function formatBytes(value) {
  const bytes = Number(value || 0);
  if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${bytes} B`;
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" }[char]
  ));
}

async function scanDevices() {
  setBusy(refs.scan, true, "扫描中");
  refs.deviceList.innerHTML = "";
  try {
    const devices = await api("/api/scan", {
      method: "POST",
      body: JSON.stringify({ address: refs.address.value.trim() || null, timeout_s: 8 }),
    });
    if (!devices.length) {
      refs.deviceList.innerHTML = `<div class="device-chip"><span>没有扫描到匹配设备</span></div>`;
      return;
    }
    refs.deviceList.innerHTML = devices.map((device) => `
      <button class="device-chip" data-address="${escapeHtml(device.address)}">
        <span>${escapeHtml(device.name || "未知设备")} · ${escapeHtml(device.address)}</span>
        <span>${device.rssi ?? "--"} dBm</span>
      </button>
    `).join("");
    refs.deviceList.querySelectorAll("[data-address]").forEach((button) => {
      button.addEventListener("click", () => {
        refs.address.value = button.dataset.address;
      });
    });
  } catch (error) {
    addLog("扫描失败", error.message);
  } finally {
    setBusy(refs.scan, false, "扫描");
  }
}

async function connectRing() {
  const address = refs.address.value.trim();
  if (!address) {
    addLog("连接失败", "请输入戒指 MAC 地址");
    return;
  }
  setBusy(refs.connect, true, "连接中");
  try {
    updateStatus(await api("/api/connect", {
      method: "POST",
      body: JSON.stringify({ address, auto_time_sync: true, command_timeout_s: 10 }),
    }));
    addLog("连接", address);
    await refreshSystem();
  } catch (error) {
    addLog("连接失败", error.message);
  } finally {
    setBusy(refs.connect, false, "连接");
  }
}

async function disconnectRing() {
  setBusy(refs.disconnect, true, "断开中");
  try {
    updateStatus(await api("/api/disconnect", { method: "POST" }));
    addLog("断开", "蓝牙会话已结束");
  } catch (error) {
    addLog("断开失败", error.message);
  } finally {
    setBusy(refs.disconnect, false, "断开");
  }
}

async function refreshSystem() {
  setBusy(refs.systemBtn, true, "刷新中");
  try {
    updateSystemInfo(await api("/api/system"));
  } catch (error) {
    addLog("系统信息失败", error.message);
  } finally {
    setBusy(refs.systemBtn, false, "刷新");
  }
}

async function getAudioCount() {
  setBusy(refs.audioCountBtn, true, "读取中");
  try {
    const data = await api("/api/audio/count");
    addLog("录音数量", `${data.count} 个文件`);
  } catch (error) {
    addLog("录音数量失败", error.message);
  } finally {
    setBusy(refs.audioCountBtn, false, "数量");
  }
}

async function downloadAudio() {
  setProgress(0);
  setBusy(refs.download, true, "下载中");
  try {
    const result = await api("/api/audio/download", {
      method: "POST",
      body: JSON.stringify({ file_index: Number(refs.fileIndex.value || 0), timeout_s: 45, quick: true }),
    });
    showAudio(result);
    addLog("录音保存", result.bundle.play_file_name);
  } catch (error) {
    addLog("下载失败", error.message);
  } finally {
    setBusy(refs.download, false, "下载");
  }
}

async function receiveAutoAudio() {
  setProgress(0);
  setBusy(refs.receive, true, "等待中");
  try {
    const result = await api("/api/audio/receive-auto", {
      method: "POST",
      body: JSON.stringify({ timeout_s: 90 }),
    });
    showAudio(result);
    addLog("新录音保存", result.bundle.play_file_name);
  } catch (error) {
    addLog("接收失败", error.message);
  } finally {
    setBusy(refs.receive, false, "等待新录音");
  }
}

async function clearAudio() {
  try {
    const confirm = refs.clearConfirm.checked;
    await api("/api/audio/clear", {
      method: "POST",
      body: JSON.stringify({ confirm }),
    });
    addLog("清空录音", "设备录音已删除");
  } catch (error) {
    addLog("清空失败", error.message);
  }
}

async function startImu() {
  setBusy(refs.imuStart, true, "启动中");
  try {
    updateStatus(await api("/api/imu/start", { method: "POST" }));
  } catch (error) {
    addLog("IMU 启动失败", error.message);
  } finally {
    setBusy(refs.imuStart, false, "开始");
  }
}

async function stopImu() {
  setBusy(refs.imuStop, true, "停止中");
  try {
    updateStatus(await api("/api/imu/stop", { method: "POST" }));
  } catch (error) {
    addLog("IMU 停止失败", error.message);
  } finally {
    setBusy(refs.imuStop, false, "停止");
  }
}

function showAudio(result) {
  const bundle = result.bundle;
  refs.audioResult.innerHTML = `
    <audio controls src="${bundle.play_url}"></audio>
    <div><a href="${bundle.play_url}" download>下载 WAV</a> · <a href="${bundle.raw_url}" download>下载 BIN</a></div>
    <div>${escapeHtml(bundle.play_file_name)} · ${formatBytes(bundle.play_size)}</div>
  `;
  setProgress(100);
}

function setProgress(percent) {
  refs.progressBar.style.width = `${Math.max(0, Math.min(100, percent))}%`;
}

function receiveRealtime(event) {
  if (event.event === "status") {
    updateStatus(event.data);
  } else if (event.event === "system_info") {
    updateSystemInfo(event.data);
  } else if (event.event === "audio_progress") {
    const total = Number(event.data.total || 0);
    setProgress(total ? (Number(event.data.current || 0) / total) * 100 : 0);
  } else if (event.event === "audio_saved") {
    showAudio(event.data);
  } else if (event.event === "ring_event") {
    const data = event.data;
    addLog(data.type, data.gesture_name || `timestamp ${data.timestamp_ms}`);
  } else if (event.event === "imu") {
    pushImu(event.data.samples || []);
  } else if (event.event === "error") {
    addLog(event.data.source || "错误", event.data.message || "未知错误");
  } else if (event.event === "audio_cleared") {
    addLog("清空录音", "设备录音已删除");
  }
}

function connectEvents() {
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(`${scheme}://${location.host}/ws/events`);
  socket.onmessage = (message) => receiveRealtime(JSON.parse(message.data));
  socket.onclose = () => setTimeout(connectEvents, 1500);
}

function pushImu(samples) {
  for (const sample of samples) {
    state.imuPoints.push({
      x: Number(sample.accel_x || 0),
      y: Number(sample.accel_y || 0),
      z: Number(sample.accel_z || 0),
    });
  }
  state.imuPoints = state.imuPoints.slice(-160);
  drawImu();
}

function drawImu() {
  const canvas = refs.canvas;
  const ctx = canvas.getContext("2d");
  const width = canvas.width;
  const height = canvas.height;
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#fbfcfb";
  ctx.fillRect(0, 0, width, height);
  ctx.strokeStyle = "#d9e1d8";
  ctx.lineWidth = 1;
  for (let i = 1; i < 5; i += 1) {
    const y = (height / 5) * i;
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(width, y);
    ctx.stroke();
  }
  const points = state.imuPoints;
  if (points.length < 2) return;
  const maxAbs = Math.max(1, ...points.flatMap((p) => [Math.abs(p.x), Math.abs(p.y), Math.abs(p.z)]));
  drawLine(ctx, points, "x", "#0f7c6c", maxAbs, width, height);
  drawLine(ctx, points, "y", "#385ad7", maxAbs, width, height);
  drawLine(ctx, points, "z", "#c8932d", maxAbs, width, height);
}

function drawLine(ctx, points, key, color, maxAbs, width, height) {
  ctx.strokeStyle = color;
  ctx.lineWidth = 2;
  ctx.beginPath();
  points.forEach((point, index) => {
    const x = (index / Math.max(1, points.length - 1)) * width;
    const y = height / 2 - (point[key] / maxAbs) * (height * 0.42);
    if (index === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();
}

async function init() {
  refs.scan.addEventListener("click", scanDevices);
  refs.connect.addEventListener("click", connectRing);
  refs.disconnect.addEventListener("click", disconnectRing);
  refs.systemBtn.addEventListener("click", refreshSystem);
  refs.audioCountBtn.addEventListener("click", getAudioCount);
  refs.download.addEventListener("click", downloadAudio);
  refs.receive.addEventListener("click", receiveAutoAudio);
  refs.clear.addEventListener("click", clearAudio);
  refs.imuStart.addEventListener("click", startImu);
  refs.imuStop.addEventListener("click", stopImu);
  refs.clearLog.addEventListener("click", () => { refs.eventLog.innerHTML = ""; });
  connectEvents();
  updateStatus(await api("/api/status"));
  drawImu();
  if (window.lucide) window.lucide.createIcons();
}

init().catch((error) => addLog("启动失败", error.message));
