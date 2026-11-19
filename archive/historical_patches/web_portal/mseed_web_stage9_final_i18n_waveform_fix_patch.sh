#!/usr/bin/env bash
set -euo pipefail

BASE="/opt/mseed-web-portal"
APP="$BASE/app"
TEMPLATES="$APP/templates"
STATIC_JS="$APP/static/js"
TS="$(date +%Y%m%d_%H%M%S)"

if [ ! -d "$APP" ]; then
  echo "ERROR: $APP not found" >&2
  exit 1
fi

sudo mkdir -p "$STATIC_JS"

for f in "$TEMPLATES/base.html" "$STATIC_JS/waveform.js"; do
  [ -f "$f" ] && sudo cp "$f" "$f.bak_stage9_final_i18n_plot_$TS" || true
done

sudo python3 - <<'PY'
from pathlib import Path
import re
p = Path('/opt/mseed-web-portal/app/templates/base.html')
s = p.read_text()
for marker in ['STAGE6_1_I18N_NO_FLASH','STAGE6_2_I18N_STRONG_NO_FLASH','STAGE7_SAFE_I18N_HEAD','STAGE9_I18N_HEAD']:
    s = re.sub(r"\n?<!-- " + re.escape(marker) + r" -->.*?</style>\s*", "\n", s, flags=re.S)
s = re.sub(r'\s*<script src="/static/js/i18n[^\"]*"></script>\s*', "\n", s)
s = re.sub(r'\s*<script src="/static/js/plotly_fix_stage8[^\"]*"></script>\s*', "\n", s)
s = re.sub(r'\s*<script src="/static/js/i18n_stage9_final[^\"]*"></script>\s*', "\n", s)
head = r'''
<!-- STAGE9_I18N_HEAD -->
<script>
(function(){
  try {
    var keys = ["mseed.portal.lang","portalLangMode","mseed_lang","portal_lang","lang","i18nextLng"];
    var isEn = false;
    for (var i = 0; i < keys.length; i++) {
      var v = (localStorage.getItem(keys[i]) || "").toLowerCase();
      if (v === "en" || v.indexOf("en-") === 0) { isEn = true; break; }
      if (v === "zh" || v === "cn" || v.indexOf("zh") === 0) { isEn = false; break; }
    }
    if (isEn) document.documentElement.classList.add("mseed-i18n-loading");
    window.__mseedI18nStage9Unlock = function(){ document.documentElement.classList.remove("mseed-i18n-loading"); };
    setTimeout(function(){ document.documentElement.classList.remove("mseed-i18n-loading"); }, 2500);
  } catch(e) {}
})();
</script>
<style>
html.mseed-i18n-loading body { opacity: 0 !important; }
</style>
'''
if '</head>' in s:
    s = s.replace('</head>', head + '\n</head>', 1)
else:
    s = head + '\n' + s
if '</body>' in s:
    s = s.replace('</body>', '<script src="/static/js/i18n_stage9_final.js?v=stage9"></script>\n</body>', 1)
else:
    s += '\n<script src="/static/js/i18n_stage9_final.js?v=stage9"></script>\n'
p.write_text(s)
print('base.html cleaned and stage9 i18n added')
PY

sudo tee "$STATIC_JS/i18n_stage9_final.js" >/dev/null <<'JSCODE'
(function(){
  "use strict";
  const LANG_KEYS = ["mseed.portal.lang","portalLangMode","mseed_lang","portal_lang","lang","i18nextLng"];
  const ZH_TO_EN_EXACT = new Map(Object.entries({
    "总览":"Overview","实时波形":"Live waveform","历史波形":"Historical waveform","历史波形查询":"Historical waveform query","数据质量":"Data quality","数据导出":"Data export","告警":"Alerts","告警中心":"Alert center","系统":"System","系统状态":"System status","管理":"Admin","退出":"Log out","登录":"Log in",
    "设备总览":"Device overview","三分量实时数据":"Three-component live data","三分量历史波形":"Three-component history","设备":"Device","时间窗口 / 秒":"Time window / seconds","刷新 / 秒":"Refresh / seconds","分量":"Channels","分量（三分量可同时选择）":"Channels (three channels can be selected together)","开始时间 UTC":"Start time UTC","结束时间 UTC":"End time UTC","查询":"Query","跳到最近":"Jump to latest","跳到最新":"Jump to latest","跳到最新数据":"Jump to latest data","前移一屏":"Previous window","后移一屏":"Next window","暂停":"Pause","继续":"Resume","等待数据...":"Waiting for data...","请选择时间范围。":"Select a time range.",
    "当前时间窗口内没有可绘制数据。":"No plottable data in the current time window.","该时间段没有可绘制数据。":"No plottable data in the selected time range.","请选择至少一个分量。":"Select at least one channel.","当前账号没有可用设备。":"No available devices for this account.","在线":"Online","离线":"Offline","延迟":"Delayed","总包数":"Total packets","最近 1 小时":"Last 1 hour","最新数据时间":"Last data time","最后接收时间":"Last received time","历史查询":"History","导出":"Export",
    "在线阈值：最近 5 分钟内收到数据":"Online threshold: data received within the latest 5 minutes","显示设备在线状态、最新数据时间、三分量状态和最近一小时入库量。":"Shows device online status, last data time, three-channel status, and records stored in the last 1 hour.","按固定间隔拉取最近一段时间数据，适合现场监控。":"Pull the most recent data at a fixed interval, suitable for live monitoring.","按设备、UTC 时间范围检索过往 miniSEED 数据；BHZ / BHN / BHE 可同时显示。":"Query historical miniSEED data by device and UTC time range; BHZ / BHN / BHE can be displayed together.","默认加载最近 30 分钟，主图显示最后 5 分钟；图下方小窗口可拖拽浏览已加载时间段。":"Default window loads 30 minutes; the main chart shows the last 5 minutes. The mini panel below can be dragged to browse the loaded range.",
    "单台设备导出":"Single-device export","预览范围":"Preview range","导出 miniSEED":"Export miniSEED","跳到Last data":"Jump to last data","保存用户":"Save user","保存客户":"Save customer","授权访问":"Grant access","授权新设备":"Grant new device","已授权设备":"Authorized devices","未分组":"Unassigned","批量客户设备规则":"Bulk customer device rules","暂无批量规则。":"No bulk rules yet.","立即检查":"Check now","确认":"Confirm"
  }));
  const MIXED_REGEX = [
    [/online\s*阈值[:：]\s*Latest\s*5\s*minutes\s*内收到数据/g,"Online threshold: data received within the latest 5 minutes"],
    [/Channels\s*[（(]\s*Three\s*channels\s*可同时\s*Select\s*[）)]/g,"Channels (three channels can be selected together)"],
    [/Time\s*窗口\s*\/\s*seconds/g,"Time window / seconds"],[/Last\s*data\s*Time/g,"Last data time"],[/Last\s*dataTime/g,"Last data time"],[/跳到\s*Last\s*data/g,"Jump to last data"],
    [/显示\s*Device\s*online\s*Status,\s*Last\s*data\s*Time,\s*Three\s*channels\s*Status\s*and\s*Latest\s*[一1]\s*hours\s*入库量[。.]?/gi,"Shows device online status, last data time, three-channel status, and records stored in the last 1 hour."],
    [/显示\s*DeviceonlineStatus,\s*Last\s*dataTime,\s*Three\s*channelsStatus\s*and\s*Latest\s*[一1]\s*hours\s*入库量[。.]?/gi,"Shows device online status, last data time, three-channel status, and records stored in the last 1 hour."],
    [/按\s*Device,\s*UTC\s*Time\s*range\s*检索过往\s*miniSEED\s*数据[；;]\s*BHZ\s*\/\s*BHN\s*\/\s*BHE\s*可同时显示[。.]?/g,"Query historical miniSEED data by device and UTC time range; BHZ / BHN / BHE can be displayed together."],
    [/默认加载最近\s*30\s*分钟，主图显示最后\s*5\s*分钟[；;]\s*图下方小窗口可拖拽浏览已加载时间段[。.]?/g,"Default window loads 30 minutes; the main chart shows the last 5 minutes. The mini panel below can be dragged to browse the loaded range."],
    [/下方\s*Mini\s*panel\s*可拖拽浏览已加载时间段/g,"The mini panel below can be dragged to browse the loaded range."],
    [/DeviceonlineStatus/g,"device online status"],[/Three\s*channelsStatus/g,"three-channel status"],[/Latest\s*[一1]\s*hours\s*入库量/g,"records stored in the last 1 hour"],[/检索过往\s*miniSEED\s*数据/g,"query historical miniSEED data"],[/可同时显示/g,"can be displayed together"],[/可同时\s*Select/g,"can be selected together"],[/图下方小窗口/g,"the mini panel below"],[/可拖拽浏览已加载时间段/g,"can be dragged to browse the loaded range"],[/窗口/g,"window"],[/阈值/g,"threshold"],[/内收到数据/g,"data received within"],[/入库量/g,"stored records"],[/暂停/g,"Pause"],[/继续/g,"Resume"],[/和/g," and "],[/、/g,", "],[/；/g,"; "],[/，/g,", "],[/：/g,": "],[/。/g,"."],[/一/g,"1"]
  ];
  function getLang(){ for(const k of LANG_KEYS){ let v=""; try{v=(localStorage.getItem(k)||"").toLowerCase();}catch(e){} if(v==="en"||v.startsWith("en-"))return"en"; if(v==="zh"||v==="cn"||v.startsWith("zh"))return"zh";} return "en"; }
  function setLang(lang){ if(lang!=="en"&&lang!=="zh")return; for(const k of LANG_KEYS){ try{localStorage.setItem(k,lang);}catch(e){} } location.reload(); }
  function skip(el){ if(!el)return true; if(el.closest("[data-no-i18n]"))return true; if(el.closest(".js-plotly-plot,.plotly,.modebar,.rangeslider,.range-slider,.slider-container,.plot-container"))return true; if(el.closest("svg,canvas"))return true; const tag=el.tagName; return ["SCRIPT","STYLE","CODE","PRE","SVG","CANVAS"].includes(tag); }
  function translateText(text){ if(!text)return text; const trimmed=text.trim(); if(ZH_TO_EN_EXACT.has(trimmed))return text.replace(trimmed,ZH_TO_EN_EXACT.get(trimmed)); let out=text; for(const [re,repl] of MIXED_REGEX)out=out.replace(re,repl); for(const [zh,en] of ZH_TO_EN_EXACT.entries()){ if(zh.length>=3&&out.includes(zh))out=out.split(zh).join(en); } if(/[A-Za-z]/.test(out)){ out=out.replace(/([A-Za-z])(\d)/g,"$1 $2").replace(/(\d)([A-Za-z])/g,"$1 $2"); out=out.replace(/\s{2,}/g," "); } return out; }
  function apply(){ const lang=getLang(); document.documentElement.setAttribute("lang",lang==="en"?"en":"zh-CN"); const btn=document.getElementById("langToggle"); if(btn){ btn.textContent=lang==="en"?"中文":"English"; btn.onclick=()=>setLang(lang==="en"?"zh":"en"); } if(lang!=="en"){ if(window.__mseedI18nStage9Unlock)window.__mseedI18nStage9Unlock(); return; } const walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT); const nodes=[]; while(walker.nextNode())nodes.push(walker.currentNode); for(const n of nodes){ if(!n.parentElement||skip(n.parentElement))continue; const old=n.nodeValue||""; const neu=translateText(old); if(neu!==old)n.nodeValue=neu; } document.querySelectorAll("input,textarea,button,option,a,[title],[aria-label]").forEach(el=>{ if(skip(el))return; ["placeholder","title","aria-label","value"].forEach(attr=>{ if(!el.hasAttribute(attr))return; if(attr==="value"&&!(el.tagName==="INPUT"&&["button","submit","reset"].includes((el.getAttribute("type")||"").toLowerCase())))return; const old=el.getAttribute(attr)||""; const neu=translateText(old); if(neu!==old)el.setAttribute(attr,neu); }); }); if(window.__mseedI18nStage9Unlock)window.__mseedI18nStage9Unlock(); }
  function audit(){ const out=[]; if(getLang()!=="en")return out; const walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT); while(walker.nextNode()){ const n=walker.currentNode; if(!n.parentElement||skip(n.parentElement))continue; const t=(n.nodeValue||"").trim(); if(/[\u4e00-\u9fff]/.test(t))out.push({text:t,tag:n.parentElement.tagName}); } return out; }
  let timer=null; function schedule(){clearTimeout(timer); timer=setTimeout(apply,50);} document.addEventListener("DOMContentLoaded",()=>{apply(); setTimeout(apply,100); setTimeout(apply,400); const mo=new MutationObserver(schedule); mo.observe(document.body,{childList:true,subtree:true,characterData:true});}); if(document.readyState!=="loading")setTimeout(apply,0); window.mseedI18NFinal={getLang,setLang,apply,audit,translateText};
})();
JSCODE

sudo python3 - <<'PY'
from pathlib import Path
import re
p = Path('/opt/mseed-web-portal/app/static/js/waveform.js')
s = p.read_text()
if 'function uiLang()' not in s:
    s = s.replace("function qs(id) { return document.getElementById(id); }\n", """function qs(id) { return document.getElementById(id); }

function uiLang() {
  const keys = ['mseed.portal.lang','portalLangMode','mseed_lang','portal_lang','lang','i18nextLng'];
  for (const k of keys) {
    const v = (localStorage.getItem(k) || '').toLowerCase();
    if (v === 'en' || v.startsWith('en-')) return 'en';
    if (v === 'zh' || v === 'cn' || v.startsWith('zh')) return 'zh';
  }
  return 'en';
}

function uiText(en, zh) {
  return uiLang() === 'en' ? en : zh;
}
""")
new_func = r'''function plotStackedComponents(targetId, traces, title, options = {}) {
  if (!traces || traces.length === 0) {
    plotEmpty(targetId, uiText('No plottable data in the selected time range.', '该时间段没有可绘制数据。'));
    return;
  }
  const grouped = new Map();
  for (const tr of traces) {
    const comp = String(tr.component || tr.stream_key || 'Trace').toUpperCase();
    if (!grouped.has(comp)) grouped.set(comp, []);
    grouped.get(comp).push(tr);
  }
  const componentNames = Array.from(grouped.keys()).sort((a, b) => componentOrderValue(a) - componentOrderValue(b));
  const n = componentNames.length;
  const gap = 0.045;
  const rowH = (1 - gap * Math.max(0, n - 1)) / n;
  const data = [];
  const height = Math.max(options.rangeSlider ? 640 : 520, n * 210 + (options.rangeSlider ? 120 : 80));
  const layout = {height, paper_bgcolor:'rgba(0,0,0,0)', plot_bgcolor:'rgba(0,0,0,0)', font:{color:'#e9eefb'}, legend:{orientation:'h', x:0, y:1.10, xanchor:'left', yanchor:'bottom'}, margin:{l:72,r:28,t:58,b:options.rangeSlider?105:62}, hovermode:'x unified', dragmode:'pan', title:{text:title||'',font:{size:14}}};
  componentNames.forEach((comp, rowIdx) => {
    const bottom = 1 - (rowIdx + 1) * rowH - rowIdx * gap;
    const top = bottom + rowH;
    const xaxisName = rowIdx === 0 ? 'xaxis' : `xaxis${rowIdx + 1}`;
    const yaxisName = rowIdx === 0 ? 'yaxis' : `yaxis${rowIdx + 1}`;
    const xRef = rowIdx === 0 ? 'x' : `x${rowIdx + 1}`;
    const yRef = rowIdx === 0 ? 'y' : `y${rowIdx + 1}`;
    const isBottom = rowIdx === n - 1;
    layout[xaxisName] = {domain:[0,1], anchor:yRef, type:'date', gridcolor:'rgba(255,255,255,0.08)', zeroline:false, showticklabels:isBottom, title:isBottom?{text:'UTC time'}:undefined, matches:rowIdx===0?undefined:'x'};
    if (rowIdx === 0 && options.initialRange && options.initialRange.length === 2) layout[xaxisName].range = options.initialRange;
    if (isBottom && options.rangeSlider) layout[xaxisName].rangeslider = {visible:true, thickness:0.09, bgcolor:'rgba(255,255,255,0.04)', bordercolor:'rgba(255,255,255,0.14)', borderwidth:1};
    layout[yaxisName] = {title:{text:comp}, domain:[Math.max(0,bottom), Math.min(1,top)], anchor:xRef, gridcolor:'rgba(255,255,255,0.08)', zeroline:false, automargin:true, fixedrange:false};
    const tracesInComp = grouped.get(comp) || [];
    tracesInComp.forEach((tr) => { data.push({x:tr.points.map(p=>new Date(p.t*1000)), y:tr.points.map(p=>p.y), mode:'lines', type:'scattergl', name:tr.stream_key||comp, xaxis:xRef, yaxis:yRef, line:{width:1}, showlegend:true}); });
  });
  Plotly.react(targetId, data, layout, {responsive:true, displaylogo:false, scrollZoom:true, modeBarButtonsToRemove:['lasso2d','select2d']}).then(() => {
    const gd = document.getElementById(targetId);
    if (gd) { setTimeout(() => Plotly.Plots.resize(gd), 50); setTimeout(() => Plotly.Plots.resize(gd), 250); }
  });
}'''
s2, n = re.subn(r"function plotStackedComponents\(targetId, traces, title, options = \{\}\) \{.*?\n\}\n\nasync function loadDevices\(\)", new_func + "\n\nasync function loadDevices()", s, flags=re.S)
if n != 1:
    raise SystemExit(f'Could not replace plotStackedComponents, replacements={n}')
s = s2
for old, new in {
    "'该时间段没有可绘制数据。'": "uiText('No plottable data in the selected time range.', '该时间段没有可绘制数据。')",
    "'当前时间窗口内没有可绘制数据。'": "uiText('No plottable data in the current time window.', '当前时间窗口内没有可绘制数据。')",
    "'请选择至少一个分量。'": "uiText('Select at least one channel.', '请选择至少一个分量。')",
    "'当前账号没有可用设备。'": "uiText('No available devices for this account.', '当前账号没有可用设备。')",
}.items():
    s = s.replace(old, new)
s = s.replace("qs('pauseBtn').textContent = state.paused ? '继续' : '暂停';", "qs('pauseBtn').textContent = state.paused ? uiText('Resume', '继续') : uiText('Pause', '暂停');")
s = s.replace("plotStackedComponents('liveChart', allTraces, `Last ${seconds}s`);", "plotStackedComponents('liveChart', allTraces, uiText(`Last ${seconds}s`, `最近 ${seconds} 秒`));")
old_meta = "`components=${comps.join(', ')} / records=${packetCount} / points=${pointCount || 0} / ${fmtUnix(queryStart)} → ${fmtUnix(queryEnd)} / 下方小窗口可拖拽浏览已加载时间段` + (truncated ? ' / 查询达到记录上限' : '')"
new_meta = "uiLang() === 'en' ? `components=${comps.join(', ')} / records=${packetCount} / points=${pointCount || 0} / ${fmtUnix(queryStart)} → ${fmtUnix(queryEnd)} / the mini panel below can be dragged to browse the loaded range` + (truncated ? ' / query record limit reached' : '') : `components=${comps.join(', ')} / records=${packetCount} / points=${pointCount || 0} / ${fmtUnix(queryStart)} → ${fmtUnix(queryEnd)} / 下方小窗口可拖拽浏览已加载时间段` + (truncated ? ' / 查询达到记录上限' : '')"
s = s.replace(old_meta, new_meta)
p.write_text(s)
print('waveform.js patched')
PY

if command -v systemctl >/dev/null 2>&1; then
  sudo systemctl restart mseed-web-portal || true
  sudo systemctl restart nginx || true
fi

echo "Stage9 final i18n + waveform plot patch applied."
echo "Open a private/incognito window or press Ctrl+F5."
echo "Browser console checks: window.mseedI18NFinal.audit()"
