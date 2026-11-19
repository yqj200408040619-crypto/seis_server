#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/mseed-web-portal"
PY="/opt/miniforge3/envs/mseed-web/bin/python"
JS="$APP_DIR/app/static/js/waveform.js"

if [ ! -f "$JS" ]; then
  echo "Cannot find $JS" >&2
  exit 1
fi

sudo cp "$JS" "$JS.bak_$(date +%Y%m%d_%H%M%S)"

sudo tee "$JS" > /dev/null <<'EOF'
const state = {
  devices: [],
  components: [],
  paused: false,
  timer: null,
  historyInitialRange: null,
};

const HISTORY_DEFAULT_OVERVIEW_SECONDS = 30 * 60;  // 历史页面默认加载最近 30 分钟
const HISTORY_DEFAULT_VIEW_SECONDS = 5 * 60;       // 主图默认显示最后 5 分钟，可用下方小窗口拖动

function fmtUnix(ts) {
  if (ts === null || ts === undefined || Number.isNaN(Number(ts))) return '-';
  const d = new Date(Number(ts) * 1000);
  return d.toISOString().replace('T', ' ').replace('Z', ' UTC');
}

function fmtIso(ts) {
  const d = new Date(Number(ts) * 1000);
  return d.toISOString().replace('.000Z', 'Z');
}

function qs(id) { return document.getElementById(id); }

async function fetchJSON(url) {
  const r = await fetch(url, { credentials: 'same-origin' });
  if (!r.ok) throw new Error(await r.text());
  return await r.json();
}

function plotEmpty(targetId, msg) {
  Plotly.react(targetId, [], {
    paper_bgcolor: 'rgba(0,0,0,0)',
    plot_bgcolor: 'rgba(0,0,0,0)',
    font: { color: '#e9eefb' },
    xaxis: { gridcolor: 'rgba(255,255,255,0.08)', zeroline: false },
    yaxis: { gridcolor: 'rgba(255,255,255,0.08)', zeroline: false },
    annotations: [{ text: msg, x: 0.5, y: 0.5, xref: 'paper', yref: 'paper', showarrow: false, font: { size: 16, color: '#9aa7bd' } }],
    margin: { l: 55, r: 25, t: 20, b: 45 },
  }, { responsive: true, displaylogo: false });
}

function plotTraces(targetId, traces, title, options = {}) {
  const data = traces.map((tr, idx) => ({
    x: tr.points.map(p => new Date(p.t * 1000)),
    y: tr.points.map(p => p.y),
    mode: 'lines',
    type: 'scattergl',
    name: tr.stream_key || tr.component || `Trace ${idx + 1}`,
    line: { width: 1 },
  }));

  const xaxis = {
    title: 'UTC time',
    gridcolor: 'rgba(255,255,255,0.08)',
    zeroline: false,
    type: 'date',
  };

  if (options.initialRange && options.initialRange.length === 2) {
    xaxis.range = options.initialRange;
  }

  if (options.rangeSlider) {
    xaxis.rangeslider = {
      visible: true,
      thickness: 0.16,
      bgcolor: 'rgba(255,255,255,0.04)',
      bordercolor: 'rgba(255,255,255,0.14)',
      borderwidth: 1,
    };
  }

  const layout = {
    paper_bgcolor: 'rgba(0,0,0,0)',
    plot_bgcolor: 'rgba(0,0,0,0)',
    font: { color: '#e9eefb' },
    legend: { orientation: 'h', y: 1.08, x: 0 },
    margin: { l: 60, r: 25, t: 35, b: options.rangeSlider ? 95 : 55 },
    xaxis,
    yaxis: { title: 'Counts', gridcolor: 'rgba(255,255,255,0.08)', zeroline: false },
    hovermode: 'x unified',
    dragmode: 'pan',
    title: { text: title || '', font: { size: 14 } },
  };

  Plotly.react(targetId, data, layout, {
    responsive: true,
    displaylogo: false,
    scrollZoom: true,
    modeBarButtonsToRemove: ['lasso2d', 'select2d'],
  });
}

async function loadDevices() {
  const payload = await fetchJSON('/api/devices');
  state.devices = payload.devices || [];
  return state.devices;
}

function selectedDeviceMeta(deviceId) {
  return state.devices.find(d => String(d.id) === String(deviceId)) || null;
}

async function loadComponents(deviceId) {
  const payload = await fetchJSON(`/api/components?device_id=${encodeURIComponent(deviceId)}`);
  state.components = payload.components || [];
  return state.components;
}

function renderLiveChecks(components) {
  const box = qs('componentChecks');
  if (!box) return;
  box.innerHTML = '';
  components.forEach((c, idx) => {
    const wrap = document.createElement('label');
    wrap.className = 'component-badge';
    wrap.innerHTML = `<input class="form-check-input mt-0" type="checkbox" value="${c.component}" ${idx < 3 ? 'checked' : ''}> ${c.component}`;
    box.appendChild(wrap);
  });
}

function renderHistorySelect(components) {
  const sel = qs('componentSelect');
  if (!sel) return;
  const oldValue = sel.value;
  sel.innerHTML = '';
  components.forEach(c => {
    const opt = document.createElement('option');
    opt.value = c.component;
    opt.textContent = `${c.component} / ${c.stream_key || ''}`;
    sel.appendChild(opt);
  });
  if (oldValue && components.some(c => c.component === oldValue)) {
    sel.value = oldValue;
  } else if (components.some(c => c.component === 'BHZ')) {
    sel.value = 'BHZ';
  }
}

function selectedComponents() {
  return Array.from(document.querySelectorAll('#componentChecks input:checked')).map(el => el.value);
}

async function updateLive() {
  if (state.paused) return;
  const deviceId = qs('deviceSelect')?.value;
  if (!deviceId) return;
  const comps = selectedComponents();
  if (comps.length === 0) {
    plotEmpty('liveChart', '请选择至少一个分量。');
    return;
  }
  const seconds = Number(qs('secondsInput')?.value || 120);
  const allTraces = [];
  let packetCount = 0;
  let startUnix = null;
  let endUnix = null;
  for (const comp of comps) {
    const payload = await fetchJSON(`/api/waveform?device_id=${encodeURIComponent(deviceId)}&component=${encodeURIComponent(comp)}&seconds=${encodeURIComponent(seconds)}`);
    packetCount += payload.packet_count || 0;
    startUnix = payload.start_unix;
    endUnix = payload.end_unix;
    if (payload.traces) allTraces.push(...payload.traces);
  }
  if (allTraces.length === 0) {
    plotEmpty('liveChart', '当前时间窗口内没有可绘制数据。');
  } else {
    plotTraces('liveChart', allTraces, `Last ${seconds}s`);
  }
  const meta = qs('liveMeta');
  if (meta) meta.textContent = `records=${packetCount} / window=${fmtUnix(startUnix)} → ${fmtUnix(endUnix)}`;
}

function scheduleLive() {
  if (state.timer) clearInterval(state.timer);
  const refresh = Math.max(1, Number(qs('refreshInput')?.value || 2));
  state.timer = setInterval(() => updateLive().catch(console.error), refresh * 1000);
}

async function initLive() {
  const devSel = qs('deviceSelect');
  if (!devSel || !devSel.value) {
    plotEmpty('liveChart', '当前账号没有可用设备。');
    return;
  }
  async function reloadComponents() {
    const comps = await loadComponents(devSel.value);
    renderLiveChecks(comps);
    await updateLive();
  }
  devSel.addEventListener('change', reloadComponents);
  qs('secondsInput')?.addEventListener('change', () => updateLive().catch(console.error));
  qs('refreshInput')?.addEventListener('change', scheduleLive);
  qs('componentChecks')?.addEventListener('change', () => updateLive().catch(console.error));
  qs('pauseBtn')?.addEventListener('click', () => {
    state.paused = !state.paused;
    qs('pauseBtn').textContent = state.paused ? '继续' : '暂停';
  });
  await reloadComponents();
  scheduleLive();
}

function setHistoryWindowToLatest(deviceId) {
  const dev = selectedDeviceMeta(deviceId);
  const latest = Number(dev?.summary?.last_start || 0);
  if (!latest) {
    const now = Date.now() / 1000;
    qs('startInput').value = fmtIso(now - HISTORY_DEFAULT_OVERVIEW_SECONDS);
    qs('endInput').value = fmtIso(now);
    state.historyInitialRange = [new Date((now - HISTORY_DEFAULT_VIEW_SECONDS) * 1000), new Date(now * 1000)];
    return;
  }

  // last_start 是数据库中最新 miniSEED record 的起始时间；向后多留 30 秒，确保最后一包进入查询范围。
  const endUnix = latest + 30;
  const startUnix = endUnix - HISTORY_DEFAULT_OVERVIEW_SECONDS;
  const viewStart = endUnix - HISTORY_DEFAULT_VIEW_SECONDS;

  qs('startInput').value = fmtIso(startUnix);
  qs('endInput').value = fmtIso(endUnix);
  state.historyInitialRange = [new Date(viewStart * 1000), new Date(endUnix * 1000)];
}

function currentHistoryRange() {
  const start = Date.parse(qs('startInput')?.value || '') / 1000;
  const end = Date.parse(qs('endInput')?.value || '') / 1000;
  if (Number.isFinite(start) && Number.isFinite(end) && end > start) return { start, end };
  return null;
}

function shiftHistoryWindow(direction) {
  const r = currentHistoryRange();
  if (!r) return;
  const span = r.end - r.start;
  const delta = direction * span * 0.8;
  const start = r.start + delta;
  const end = r.end + delta;
  qs('startInput').value = fmtIso(start);
  qs('endInput').value = fmtIso(end);
  state.historyInitialRange = [new Date((end - Math.min(HISTORY_DEFAULT_VIEW_SECONDS, span)) * 1000), new Date(end * 1000)];
}

async function queryHistory() {
  const deviceId = qs('deviceSelect')?.value;
  const comp = qs('componentSelect')?.value;
  const start = qs('startInput')?.value;
  const end = qs('endInput')?.value;
  if (!deviceId || !comp || !start || !end) return;

  const payload = await fetchJSON(`/api/waveform?device_id=${encodeURIComponent(deviceId)}&component=${encodeURIComponent(comp)}&start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}&max_points=20000`);
  if (!payload.traces || payload.traces.length === 0) {
    plotEmpty('historyChart', '该时间段没有可绘制数据。');
  } else {
    plotTraces('historyChart', payload.traces, `${comp} history`, {
      rangeSlider: true,
      initialRange: state.historyInitialRange,
    });
  }
  const meta = qs('historyMeta');
  if (meta) {
    meta.textContent = `records=${payload.packet_count} / points=${payload.point_count || 0} / ${fmtUnix(payload.start_unix)} → ${fmtUnix(payload.end_unix)} / 下方小窗口可拖拽浏览已加载时间段` + (payload.truncated_records ? ' / 查询达到记录上限' : '');
  }
}

async function initHistory() {
  const devSel = qs('deviceSelect');
  if (!devSel || !devSel.value) {
    plotEmpty('historyChart', '当前账号没有可用设备。');
    return;
  }

  await loadDevices();

  async function reloadComponentsAndQueryLatest() {
    const comps = await loadComponents(devSel.value);
    renderHistorySelect(comps);
    setHistoryWindowToLatest(devSel.value);
    await queryHistory();
  }

  devSel.addEventListener('change', () => reloadComponentsAndQueryLatest().catch(err => alert(err.message)));
  qs('componentSelect')?.addEventListener('change', () => queryHistory().catch(err => alert(err.message)));
  qs('queryBtn')?.addEventListener('click', () => {
    state.historyInitialRange = null;
    queryHistory().catch(err => alert(err.message));
  });

  const latestBtn = qs('latestBtn');
  if (latestBtn) latestBtn.addEventListener('click', () => {
    setHistoryWindowToLatest(devSel.value);
    queryHistory().catch(err => alert(err.message));
  });
  const prevBtn = qs('prevBtn');
  if (prevBtn) prevBtn.addEventListener('click', () => {
    shiftHistoryWindow(-1);
    queryHistory().catch(err => alert(err.message));
  });
  const nextBtn = qs('nextBtn');
  if (nextBtn) nextBtn.addEventListener('click', () => {
    shiftHistoryWindow(1);
    queryHistory().catch(err => alert(err.message));
  });

  await reloadComponentsAndQueryLatest();
}

window.addEventListener('load', () => {
  if (window.portalMode === 'live') initLive().catch(console.error);
  if (window.portalMode === 'history') initHistory().catch(console.error);
});
EOF

# Add optional navigation buttons to history.html if they are not present yet.
HIST="$APP_DIR/app/templates/history.html"
sudo cp "$HIST" "$HIST.bak_$(date +%Y%m%d_%H%M%S)"
if ! grep -q 'id="latestBtn"' "$HIST"; then
  sudo "$PY" - <<'PY'
from pathlib import Path
p = Path('/opt/mseed-web-portal/app/templates/history.html')
s = p.read_text()
old = '''    <div class="col-12 col-lg-1 d-grid">
      <button id="queryBtn" class="btn btn-primary">查询</button>
    </div>'''
new = '''    <div class="col-12 col-lg-1 d-grid">
      <button id="queryBtn" class="btn btn-primary">查询</button>
    </div>
    <div class="col-12 d-flex gap-2 flex-wrap">
      <button id="latestBtn" type="button" class="btn btn-sm btn-outline-light">跳到最近</button>
      <button id="prevBtn" type="button" class="btn btn-sm btn-outline-light">前移一屏</button>
      <button id="nextBtn" type="button" class="btn btn-sm btn-outline-light">后移一屏</button>
      <span class="small text-secondary align-self-center">默认加载最近 30 分钟，主图显示最后 5 分钟；图下方小窗口可拖拽浏览已加载时间段。</span>
    </div>'''
if old not in s:
    raise SystemExit('history.html target block not found')
p.write_text(s.replace(old, new))
print('patched history.html')
PY
fi

sudo systemctl restart mseed-web-portal
sudo systemctl status mseed-web-portal --no-pager

echo "Patch applied. Test: http://127.0.0.1/history"
