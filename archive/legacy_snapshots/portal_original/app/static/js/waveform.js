const state = {
  devices: [],
  components: [],
  paused: false,
  timer: null,
};

function fmtUnix(ts) {
  const d = new Date(Number(ts) * 1000);
  return d.toISOString().replace('T', ' ').replace('Z', ' UTC');
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

function plotTraces(targetId, traces, title) {
  const data = traces.map((tr, idx) => ({
    x: tr.points.map(p => new Date(p.t * 1000)),
    y: tr.points.map(p => p.y),
    mode: 'lines',
    type: 'scattergl',
    name: tr.stream_key || tr.component || `Trace ${idx + 1}`,
    line: { width: 1 },
  }));
  const layout = {
    paper_bgcolor: 'rgba(0,0,0,0)',
    plot_bgcolor: 'rgba(0,0,0,0)',
    font: { color: '#e9eefb' },
    legend: { orientation: 'h', y: 1.08, x: 0 },
    margin: { l: 60, r: 25, t: 35, b: 55 },
    xaxis: { title: 'UTC time', gridcolor: 'rgba(255,255,255,0.08)', zeroline: false },
    yaxis: { title: 'Counts', gridcolor: 'rgba(255,255,255,0.08)', zeroline: false },
    hovermode: 'x unified',
    title: { text: title || '', font: { size: 14 } },
  };
  Plotly.react(targetId, data, layout, { responsive: true, displaylogo: false, scrollZoom: true });
}

async function loadDevices() {
  const payload = await fetchJSON('/api/devices');
  state.devices = payload.devices || [];
  return state.devices;
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
    const id = `comp_${c.component}`;
    const wrap = document.createElement('label');
    wrap.className = 'component-badge';
    wrap.innerHTML = `<input class="form-check-input mt-0" type="checkbox" value="${c.component}" ${idx < 3 ? 'checked' : ''}> ${c.component}`;
    box.appendChild(wrap);
  });
}

function renderHistorySelect(components) {
  const sel = qs('componentSelect');
  if (!sel) return;
  sel.innerHTML = '';
  components.forEach(c => {
    const opt = document.createElement('option');
    opt.value = c.component;
    opt.textContent = `${c.component} / ${c.stream_key || ''}`;
    sel.appendChild(opt);
  });
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

function defaultHistoryTimes() {
  const now = new Date();
  const end = now.toISOString().replace('.000Z', 'Z');
  const startDate = new Date(now.getTime() - 5 * 60 * 1000);
  const start = startDate.toISOString().replace('.000Z', 'Z');
  if (qs('startInput') && !qs('startInput').value) qs('startInput').value = start;
  if (qs('endInput') && !qs('endInput').value) qs('endInput').value = end;
}

async function queryHistory() {
  const deviceId = qs('deviceSelect')?.value;
  const comp = qs('componentSelect')?.value;
  const start = qs('startInput')?.value;
  const end = qs('endInput')?.value;
  if (!deviceId || !comp || !start || !end) return;
  const payload = await fetchJSON(`/api/waveform?device_id=${encodeURIComponent(deviceId)}&component=${encodeURIComponent(comp)}&start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}&max_points=12000`);
  if (!payload.traces || payload.traces.length === 0) {
    plotEmpty('historyChart', '该时间段没有可绘制数据。');
  } else {
    plotTraces('historyChart', payload.traces, `${comp} history`);
  }
  const meta = qs('historyMeta');
  if (meta) meta.textContent = `records=${payload.packet_count} / points=${payload.point_count || 0} / ${fmtUnix(payload.start_unix)} → ${fmtUnix(payload.end_unix)}${payload.truncated_records ? ' / 查询达到记录上限' : ''}`;
}

async function initHistory() {
  const devSel = qs('deviceSelect');
  if (!devSel || !devSel.value) {
    plotEmpty('historyChart', '当前账号没有可用设备。');
    return;
  }
  defaultHistoryTimes();
  async function reloadComponents() {
    const comps = await loadComponents(devSel.value);
    renderHistorySelect(comps);
  }
  devSel.addEventListener('change', reloadComponents);
  qs('queryBtn')?.addEventListener('click', () => queryHistory().catch(err => alert(err.message)));
  await reloadComponents();
}

window.addEventListener('load', () => {
  if (window.portalMode === 'live') initLive().catch(console.error);
  if (window.portalMode === 'history') initHistory().catch(console.error);
});
