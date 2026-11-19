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

for f in "$TEMPLATES/base.html" "$STATIC_JS/waveform.js" "$TEMPLATES/history.html" "$TEMPLATES/live.html" "$TEMPLATES/dashboard.html" "$TEMPLATES/export.html"; do
  [ -f "$f" ] && sudo cp "$f" "$f.bak_stage8_clean_i18n_plot_$TS" || true
done

# ---------------------------------------------------------------------------
# 1) Remove all previous i18n runtime scanners and preload locks.
#    They caused mixed text and can interfere with Plotly layout.
# ---------------------------------------------------------------------------
if [ -f "$TEMPLATES/base.html" ]; then
sudo python3 - <<'PY'
from pathlib import Path
import re

p = Path("/opt/mseed-web-portal/app/templates/base.html")
s = p.read_text()

# Remove old no-flash / preload style blocks.
for marker in [
    "STAGE6_1_I18N_NO_FLASH",
    "STAGE6_2_I18N_STRONG_NO_FLASH",
    "STAGE7_SAFE_I18N_HEAD",
]:
    s = re.sub(r"\n?<!-- " + re.escape(marker) + r" -->.*?</style>\s*", "\n", s, flags=re.S)

# Remove all old i18n helper script includes. Keep non-i18n app scripts.
old_scripts = [
    "i18n_full_coverage_stage6.js",
    "i18n_stage6_1_no_flash_cleanup.js",
    "i18n_stage6_2_final_cleanup.js",
    "i18n_stage7_safe_final.js",
    "i18n_stage8_clean.js",
    "plotly_fix_stage8.js",
]
for name in old_scripts:
    s = re.sub(r'\s*<script src="/static/js/' + re.escape(name) + r'[^"]*"></script>\s*', "\n", s)

# Add one clean i18n script and one plot fix script at the very end.
if 'i18n_stage8_clean.js' not in s:
    s = s.replace("</body>", '<script src="/static/js/i18n_stage8_clean.js?v=stage8"></script>\n<script src="/static/js/plotly_fix_stage8.js?v=stage8"></script>\n</body>')

p.write_text(s)
print("base.html cleaned")
PY
fi

# ---------------------------------------------------------------------------
# 2) Clean deterministic i18n.
#    - Does not mutate Plotly/SVG/canvas.
#    - Avoids broad repeated partial translation loops that created mixed text.
#    - Fixes all mixed strings shown in the screenshots.
# ---------------------------------------------------------------------------
sudo tee "$STATIC_JS/i18n_stage8_clean.js" > /dev/null <<'JSCODE'
(function(){
  "use strict";

  const EXACT_EN = new Map(Object.entries({
    "online阈值: Latest 5 minutes内收到数据": "Online threshold: data received within the latest 5 minutes",
    "online阈值：Latest 5 minutes内收到数据": "Online threshold: data received within the latest 5 minutes",
    "Channels（Three channels可同时Select）": "Channels (three channels can be selected together)",
    "Channels (Three channels可同时Select)": "Channels (three channels can be selected together)",
    "Time窗口 / seconds": "Time window / seconds",
    "跳到Last data": "Jump to last data",
    "Last dataTime": "Last data time",
    "显示DeviceonlineStatus, Last dataTime, Three channelsStatus and Latest一hours入库量.": "Shows device online status, last data time, three-channel status, and records stored in the last 1 hour.",
    "显示DeviceonlineStatus, Last dataTime, Three channelsStatus and Latest1hours入库量.": "Shows device online status, last data time, three-channel status, and records stored in the last 1 hour.",
    "按Device, UTC Time range检索过往 miniSEED 数据；BHZ / BHN / BHE 可同时显示.": "Query historical miniSEED data by device and UTC time range; BHZ / BHN / BHE can be displayed together.",
    "按Device, UTC Time range检索过往 miniSEED 数据；BHZ / BHN / BHE 可同时显示。": "Query historical miniSEED data by device and UTC time range; BHZ / BHN / BHE can be displayed together.",
    "默认加载最近 30 分钟，主图显示最后 5 分钟；图下方小窗口可拖拽浏览已加载时间段。": "Default window loads 30 minutes; the main chart shows the last 5 minutes. The mini panel below can be dragged to browse the loaded range.",
    "默认加载最近 30 分钟，主图显示最后 5 分钟；图下方小窗口可拖拽浏览已加载时间段.": "Default window loads 30 minutes; the main chart shows the last 5 minutes. The mini panel below can be dragged to browse the loaded range.",
    "下方Mini panel可拖拽浏览已加载时间段": "The mini panel below can be dragged to browse the loaded range.",
    "暂停": "Pause",
    "继续": "Resume",

    "总览": "Overview",
    "实时波形": "Live waveform",
    "历史波形": "Historical waveform",
    "历史波形查询": "Historical waveform query",
    "数据质量": "Data quality",
    "数据导出": "Data export",
    "告警": "Alerts",
    "告警中心": "Alert center",
    "系统": "System",
    "系统状态": "System status",
    "管理": "Admin",
    "设备": "Device",
    "客户": "Customer",
    "用户": "User",
    "状态": "Status",
    "级别": "Level",
    "类型": "Type",
    "详情": "Details",
    "操作": "Actions",
    "开始时间 UTC": "Start time UTC",
    "结束时间 UTC": "End time UTC",
    "分量": "Channels",
    "查询": "Query",
    "跳到最新": "Jump to latest",
    "跳到最新数据": "Jump to latest data",
    "上一时间窗": "Previous window",
    "下一时间窗": "Next window",
    "预览范围": "Preview range",
    "导出 miniSEED": "Export miniSEED",
    "单台设备导出": "Single-device export",
    "批量导出": "Batch export",
    "批量导出 ZIP": "Batch export ZIP",
    "按时间段批量导出": "Export by time segments",
    "导出分段 ZIP": "Export segmented ZIP",
    "保存用户": "Save user",
    "保存客户": "Save customer",
    "保存并应用规则": "Save and apply rule",
    "授权访问": "Grant access",
    "授权新设备": "Grant new device",
    "已授权设备": "Authorized devices",
    "未分组": "Unassigned",
    "暂无批量规则。": "No bulk rules yet.",
    "立即检查": "Check now",
    "确认": "Confirm",
    "离线": "Offline",
    "在线": "Online",
    "最后数据": "Last data",
    "最新数据": "Latest data",
    "最新接收": "Last received",
    "重复包": "Duplicates",
    "异常包": "Bad packets",
    "缺口数": "Gap count",
    "磁盘使用率": "Disk usage",
    "磁盘剩余": "Disk free",
    "接收数据库大小": "Receiver DB size",
    "最近备份": "Recent backup"
  }));

  const REGEX_EN = [
    [/online\s*阈值[:：]\s*Latest\s*5\s*minutes\s*内收到数据/g, "Online threshold: data received within the latest 5 minutes"],
    [/Channels\s*[（(]\s*Three\s*channels\s*可同时\s*Select\s*[）)]/g, "Channels (three channels can be selected together)"],
    [/Time\s*窗口\s*\/\s*seconds/g, "Time window / seconds"],
    [/Last\s*data\s*Time/g, "Last data time"],
    [/Last\s*dataTime/g, "Last data time"],
    [/跳到\s*Last\s*data/g, "Jump to last data"],
    [/显示\s*Device\s*online\s*Status,\s*Last\s*data\s*Time,\s*Three\s*channels\s*Status\s*and\s*Latest\s*[一1]\s*hours\s*入库量[。.]?/gi,
      "Shows device online status, last data time, three-channel status, and records stored in the last 1 hour."],
    [/显示\s*DeviceonlineStatus,\s*Last\s*dataTime,\s*Three\s*channelsStatus\s*and\s*Latest\s*[一1]\s*hours\s*入库量[。.]?/gi,
      "Shows device online status, last data time, three-channel status, and records stored in the last 1 hour."],
    [/按\s*Device,\s*UTC\s*Time\s*range\s*检索过往\s*miniSEED\s*数据[；;]\s*BHZ\s*\/\s*BHN\s*\/\s*BHE\s*可同时显示[。.]?/g,
      "Query historical miniSEED data by device and UTC time range; BHZ / BHN / BHE can be displayed together."],
    [/默认加载最近\s*30\s*分钟，主图显示最后\s*5\s*分钟[；;]\s*图下方小窗口可拖拽浏览已加载时间段[。.]?/g,
      "Default window loads 30 minutes; the main chart shows the last 5 minutes. The mini panel below can be dragged to browse the loaded range."],
    [/下方\s*Mini\s*panel\s*可拖拽浏览已加载时间段/g, "The mini panel below can be dragged to browse the loaded range."],
    [/DeviceonlineStatus/g, "device online status"],
    [/Three\s*channelsStatus/g, "three-channel status"],
    [/Latest\s*[一1]\s*hours\s*入库量/g, "records stored in the last 1 hour"],
    [/检索过往\s*miniSEED\s*数据/g, "query historical miniSEED data"],
    [/可同时显示/g, "can be displayed together"],
    [/可同时\s*Select/g, "can be selected together"],
    [/图下方小窗口/g, "the mini panel below"],
    [/可拖拽浏览已加载时间段/g, "can be dragged to browse the loaded range"],
    [/窗口/g, "window"],
    [/阈值/g, "threshold"],
    [/内收到数据/g, "data received within"],
    [/入库量/g, "stored records"],
    [/暂停/g, "Pause"],
    [/继续/g, "Resume"],
    [/和/g, " and "],
    [/、/g, ", "],
    [/；/g, "; "],
    [/，/g, ", "],
    [/：/g, ": "],
    [/。/g, "."],
    [/一/g, "1"]
  ];

  function languageIsEnglish(){
    const keys = ["portalLangMode","mseed_lang","portal_lang","lang","i18nextLng"];
    for (const k of keys) {
      let v = "";
      try { v = (localStorage.getItem(k) || "").toLowerCase(); } catch(e) {}
      if (v === "en" || v.startsWith("en-")) return true;
      if (v === "zh" || v === "cn" || v.startsWith("zh")) return false;
    }
    const bodyText = document.body ? document.body.innerText : "";
    const en = (bodyText.match(/Overview|Live waveform|Historical waveform|Data export|Device overview|Alert center|Admin/g) || []).length;
    const zh = (bodyText.match(/[\u4e00-\u9fff]/g) || []).length;
    return en >= 2 || zh === 0;
  }

  function skip(el){
    if (!el) return true;
    if (el.closest("[data-no-i18n]")) return true;
    if (el.closest(".js-plotly-plot,.plotly,.modebar,.rangeslider,.range-slider,.slider-container,.plot-container")) return true;
    if (el.closest("svg,canvas")) return true;
    const tag = el.tagName;
    return ["SCRIPT","STYLE","CODE","PRE","SVG","CANVAS"].includes(tag);
  }

  function fix(s){
    if (!s) return s;
    const trimmed = s.trim();
    if (EXACT_EN.has(trimmed)) return s.replace(trimmed, EXACT_EN.get(trimmed));
    let out = s;
    for (const [re, repl] of REGEX_EN) out = out.replace(re, repl);
    if (/[A-Za-z]/.test(out)) {
      out = out.replace(/([A-Za-z])(\d)/g, "$1 $2").replace(/(\d)([A-Za-z])/g, "$1 $2");
      out = out.replace(/\s{2,}/g, " ");
    }
    return out;
  }

  function apply(){
    if (!languageIsEnglish()) return;
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    for (const n of nodes) {
      if (!n.parentElement || skip(n.parentElement)) continue;
      const old = n.nodeValue || "";
      const neu = fix(old);
      if (neu !== old) n.nodeValue = neu;
    }
    document.querySelectorAll("input,textarea,button,option,a,[title],[aria-label]").forEach(el => {
      if (skip(el)) return;
      ["placeholder","title","aria-label","value"].forEach(attr => {
        if (!el.hasAttribute(attr)) return;
        if (attr === "value" && !(el.tagName === "INPUT" && ["button","submit","reset"].includes((el.getAttribute("type")||"").toLowerCase()))) return;
        const old = el.getAttribute(attr) || "";
        const neu = fix(old);
        if (neu !== old) el.setAttribute(attr, neu);
      });
    });
  }

  function audit(){
    const out = [];
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
      const n = walker.currentNode;
      if (!n.parentElement || skip(n.parentElement)) continue;
      const t = (n.nodeValue || "").trim();
      if (/[\u4e00-\u9fff]/.test(t)) out.push({text:t, tag:n.parentElement.tagName});
    }
    return out;
  }

  let timer = null;
  function schedule(){
    clearTimeout(timer);
    timer = setTimeout(apply, 50);
  }

  document.addEventListener("DOMContentLoaded", () => {
    apply();
    setTimeout(apply, 100);
    setTimeout(apply, 400);
    const mo = new MutationObserver(schedule);
    mo.observe(document.body, {childList:true, subtree:true, characterData:true});
  });
  if (document.readyState !== "loading") setTimeout(apply, 0);

  window.mseedI18NStage8 = { apply, audit, fix };
})();
JSCODE

# ---------------------------------------------------------------------------
# 3) Plotly layout repair.
#    This does not translate chart DOM. It only forces sane height/domains and
#    re-renders/resizes the history/live chart after page load.
# ---------------------------------------------------------------------------
sudo tee "$STATIC_JS/plotly_fix_stage8.js" > /dev/null <<'JSCODE'
(function(){
  "use strict";

  function findPlots(){
    return Array.from(document.querySelectorAll(".js-plotly-plot"));
  }

  function isWaveformPlot(gd){
    const text = (gd.parentElement ? gd.parentElement.innerText : "") + " " + (document.body ? document.body.innerText : "");
    return /BHZ|BHN|BHE|waveform|history|records=|components=/.test(text);
  }

  function fixLayout(gd){
    if (!window.Plotly || !gd || !gd.layout) return;
    if (!isWaveformPlot(gd)) return;

    const hasBHN = gd.layout.yaxis2 || (gd.data || []).length >= 2;
    const hasBHE = gd.layout.yaxis3 || (gd.data || []).length >= 3;
    const height = hasBHN || hasBHE ? 640 : 420;

    const update = {
      height: height,
      margin: {l: 70, r: 25, t: 45, b: 95},
      showlegend: true,
      legend: {
        orientation: "h",
        x: 0.02,
        y: 1.08,
        xanchor: "left",
        yanchor: "bottom"
      },
      xaxis: {
        domain: [0, 1],
        rangeslider: {visible: true, thickness: 0.08},
        title: {text: "UTC time"}
      }
    };

    if (hasBHN || hasBHE) {
      update.yaxis = {domain: [0.68, 1.0], title: {text: "BHZ"}, automargin: true};
      update.yaxis2 = {domain: [0.34, 0.64], title: {text: "BHN"}, automargin: true};
      update.yaxis3 = {domain: [0.0, 0.30], title: {text: "BHE"}, automargin: true};
      update.xaxis2 = {matches: "x", showticklabels: false, domain: [0,1]};
      update.xaxis3 = {matches: "x", showticklabels: true, domain: [0,1]};
    }

    try {
      window.Plotly.relayout(gd, update).then(() => {
        try { window.Plotly.Plots.resize(gd); } catch(e) {}
      });
    } catch(e) {
      try { window.Plotly.Plots.resize(gd); } catch(_) {}
    }
  }

  function fixAll(){
    if (!window.Plotly) return;
    findPlots().forEach(fixLayout);
  }

  function schedule(){
    clearTimeout(window.__stage8PlotTimer);
    window.__stage8PlotTimer = setTimeout(fixAll, 120);
  }

  document.addEventListener("DOMContentLoaded", () => {
    setTimeout(fixAll, 300);
    setTimeout(fixAll, 900);
    setTimeout(fixAll, 1800);

    const mo = new MutationObserver(schedule);
    mo.observe(document.body, {childList:true, subtree:true});
  });
  window.addEventListener("resize", schedule);

  window.mseedPlotFixStage8 = { fixAll, fixLayout };
})();
JSCODE

if command -v systemctl >/dev/null 2>&1; then
  sudo systemctl restart mseed-web-portal || true
  sudo systemctl restart nginx || true
fi

echo "Stage8 clean i18n + Plotly repair patch applied."
echo "Open the site, press Ctrl+F5."
echo "Console checks:"
echo "  window.mseedI18NStage8.audit()"
echo "  window.mseedPlotFixStage8.fixAll()"
