(function(){
  function onReady(fn){ if(document.readyState !== 'loading') fn(); else document.addEventListener('DOMContentLoaded', fn); }
  onReady(async function(){
    if(!location.pathname.includes('/export')) { if(window.stage4I18N) setTimeout(()=>window.stage4I18N.apply(), 100); return; }
    if(window.stage4I18N) setTimeout(()=>window.stage4I18N.apply(), 100);

    const existing = document.getElementById('stage4SegmentPanel');
    if(existing) return;
    const forms = document.querySelectorAll('form');
    if(!forms.length) return;
    const host = forms[forms.length-1].closest('.control-panel,.device-card,.card,.panel') || document.body;
    const wrapper = document.createElement('div');
    wrapper.id = 'stage4SegmentPanel';
    wrapper.className = 'control-panel';
    wrapper.style.marginTop = '24px';
    wrapper.innerHTML = `
      <h2 class="h5 fw-bold mb-3">Export by time segments</h2>
      <div class="row g-3 align-items-end">
        <div class="col-12 col-md-6">
          <label class="form-label">Start time UTC</label>
          <input id="segStart" class="form-control" placeholder="2026-07-05T00:00:00Z">
        </div>
        <div class="col-12 col-md-6">
          <label class="form-label">End time UTC</label>
          <input id="segEnd" class="form-control" placeholder="2026-07-05T06:00:00Z">
        </div>
        <div class="col-12 col-md-4">
          <label class="form-label">Segment minutes</label>
          <input id="segmentMinutes" type="number" min="1" max="1440" value="30" class="form-control">
        </div>
        <div class="col-12">
          <label class="form-label">Selected devices</label>
          <div id="segDeviceList" class="batch-device-list" style="max-height:220px;overflow:auto;border:1px solid rgba(148,163,184,.22);border-radius:14px;padding:12px;background:rgba(15,23,42,.35)"></div>
        </div>
        <div class="col-12 d-flex flex-wrap gap-2">
          <button type="button" id="segSelectAll" class="btn btn-outline-light">Select all</button>
          <button type="button" id="segClearAll" class="btn btn-outline-light">Clear</button>
          <button type="button" id="segExportBtn" class="btn btn-primary">Export segmented ZIP</button>
        </div>
        <div class="col-12 small text-secondary">
          <div>Each device is exported into multiple miniSEED files split by time windows. Data gaps do not block export; missing intervals appear in gaps.csv and empty windows appear only in manifest.csv.</div>
        </div>
      </div>`;
    host.parentNode.insertBefore(wrapper, host.nextSibling);

    async function fetchDevices(){
      const r = await fetch('/api/export/devices3');
      if(!r.ok) throw new Error('Failed to load devices');
      return (await r.json()).devices || [];
    }
    function selectedChannels(){
      const out=[];
      document.querySelectorAll('input[type=checkbox]').forEach(cb=>{
        const txt=(cb.closest('label,div,span')?.innerText||'').toUpperCase();
        if(cb.checked && /(BHZ|BHN|BHE)/.test(txt)) out.push(txt.match(/BHZ|BHN|BHE/)[0]);
      });
      return [...new Set(out)];
    }
    function fillDefaults(){
      const s = document.querySelector('input[name=start],#startInput');
      const e = document.querySelector('input[name=end],#endInput');
      if(s) document.getElementById('segStart').value = s.value;
      if(e) document.getElementById('segEnd').value = e.value;
    }
    function renderDevices(devs){
      const box=document.getElementById('segDeviceList');
      box.innerHTML='';
      devs.forEach(d=>{
        const row=document.createElement('label');
        row.className='batch-device-row';
        row.style.display='flex'; row.style.gap='10px'; row.style.padding='8px'; row.style.borderBottom='1px solid rgba(148,163,184,.12)';
        row.innerHTML=`<input type="checkbox" value="${d.id}" checked> <span><strong>${d.alias||d.label||d.device_key}</strong> / ${d.device_key}</span>`;
        box.appendChild(row);
      });
    }
    function getSelectedIds(){ return [...document.querySelectorAll('#segDeviceList input[type=checkbox]:checked')].map(x=>x.value); }

    const devices = await fetchDevices().catch(()=>[]);
    renderDevices(devices); fillDefaults(); if(window.stage4I18N) window.stage4I18N.apply();
    document.getElementById('segSelectAll').onclick=()=>document.querySelectorAll('#segDeviceList input[type=checkbox]').forEach(x=>x.checked=true);
    document.getElementById('segClearAll').onclick=()=>document.querySelectorAll('#segDeviceList input[type=checkbox]').forEach(x=>x.checked=false);
    document.getElementById('segExportBtn').onclick=()=>{
      const ids = getSelectedIds();
      if(!ids.length){ alert('Select at least one device.'); return; }
      const start = document.getElementById('segStart').value.trim();
      const end = document.getElementById('segEnd').value.trim();
      const segment = document.getElementById('segmentMinutes').value || '30';
      const comps = selectedChannels().join(',');
      const qs = new URLSearchParams({ device_ids: ids.join(','), start, end, segment_minutes: segment, components: comps });
      window.location.href = '/export/batch-window4?' + qs.toString();
    };
  });
})();
