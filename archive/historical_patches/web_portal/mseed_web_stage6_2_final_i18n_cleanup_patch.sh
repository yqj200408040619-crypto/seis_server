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

[ -f "$TEMPLATES/base.html" ] && sudo cp "$TEMPLATES/base.html" "$TEMPLATES/base.html.bak_i18n_stage6_2_$TS" || true

# ---------------------------------------------------------------------------
# 1) Strong no-flash mode.
#    The body is hidden before first paint. The Stage6.2 script unlocks it after
#    all translations and cleanup passes. This prevents Chinese from flashing
#    before English cleanup runs.
# ---------------------------------------------------------------------------
if [ -f "$TEMPLATES/base.html" ] && ! grep -q "STAGE6_2_I18N_STRONG_NO_FLASH" "$TEMPLATES/base.html"; then
sudo python3 - <<'PY'
from pathlib import Path
p = Path("/opt/mseed-web-portal/app/templates/base.html")
s = p.read_text()
inject = r'''
<!-- STAGE6_2_I18N_STRONG_NO_FLASH -->
<script>
(function(){
  try {
    document.documentElement.classList.add("mseed-i18n-preload");
    window.__mseedI18nUnlockStrong = function(){
      document.documentElement.classList.remove("mseed-i18n-preload");
      document.documentElement.classList.remove("i18n-lock");
    };
    setTimeout(function(){
      if (window.__mseedI18nUnlockStrong) window.__mseedI18nUnlockStrong();
    }, 6000);
  } catch(e) {}
})();
</script>
<style>
html.mseed-i18n-preload body {
  visibility: hidden !important;
}
html.mseed-i18n-preload::before {
  content: "Loading…";
  position: fixed;
  top: 18px;
  left: 18px;
  color: #e5e7eb;
  font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  font-size: 15px;
  z-index: 2147483647;
}
</style>
'''
if "</head>" in s:
    s = s.replace("</head>", inject + "\n</head>", 1)
else:
    s = inject + "\n" + s
p.write_text(s)
PY
fi

# ---------------------------------------------------------------------------
# 2) Stage6.2 final cleanup dictionary + mixed-text normalizer.
#    This runs after all previous i18n scripts and after dynamic DOM updates.
# ---------------------------------------------------------------------------
sudo tee "$STATIC_JS/i18n_stage6_2_final_cleanup.js" > /dev/null <<'JSCODE'
(function(){
  "use strict";

  var EXACT_ZH_EN = {
    "暂停": "Pause",
    "继续": "Resume",
    "显示DeviceonlineStatus, Last dataTime, Three channelsStatus and Latest一hours入库量.": "Shows device online status, last data time, three-channel status, and records stored in the last 1 hour.",
    "按Device, UTC Time range检索过往 miniSEED 数据；BHZ / BHN / BHE 可同时显示.": "Query historical miniSEED data by device and UTC time range; BHZ / BHN / BHE can be displayed together.",
    "按Device, UTC Time range检索过往 miniSEED 数据；BHZ / BHN / BHE 可同时显示。": "Query historical miniSEED data by device and UTC time range; BHZ / BHN / BHE can be displayed together.",
    "默认加载最近 30 分钟，主图显示最后 5 分钟；图下方小窗口可拖拽浏览已加载时间段.": "Default window loads 30 minutes; the main chart shows the last 5 minutes. The mini panel below can be dragged to browse the loaded range.",
    "默认加载最近 30 分钟，主图显示最后 5 分钟；图下方小窗口可拖拽浏览已加载时间段。": "Default window loads 30 minutes; the main chart shows the last 5 minutes. The mini panel below can be dragged to browse the loaded range.",
    "下方Mini panel可拖拽浏览已加载时间段": "the mini panel below can be dragged to browse the loaded range",
    "跳到Last data": "Jump to last data",
    "Time窗口 / seconds": "Time window / seconds",
    "Last dataTime": "Last data time"
  };

  var PARTS_ZH_EN = [
    [/显示\s*Device\s*online\s*Status,\s*Last\s*data\s*Time,\s*Three\s*channels\s*Status\s*and\s*Latest\s*[一1]\s*hours\s*入库量。?/gi,
      "Shows device online status, last data time, three-channel status, and records stored in the last 1 hour."],
    [/显示\s*DeviceonlineStatus,\s*Last\s*dataTime,\s*Three\s*channelsStatus\s*and\s*Latest\s*[一1]\s*hours\s*入库量。?/gi,
      "Shows device online status, last data time, three-channel status, and records stored in the last 1 hour."],
    [/按\s*Device,\s*UTC\s*Time\s*range\s*检索过往\s*miniSEED\s*数据[；;]\s*BHZ\s*\/\s*BHN\s*\/\s*BHE\s*可同时显示。?/gi,
      "Query historical miniSEED data by device and UTC time range; BHZ / BHN / BHE can be displayed together."],
    [/默认加载最近\s*30\s*分钟，主图显示最后\s*5\s*分钟[；;]\s*图下方小窗口可拖拽浏览已加载时间段。?/g,
      "Default window loads 30 minutes; the main chart shows the last 5 minutes. The mini panel below can be dragged to browse the loaded range."],
    [/下方\s*Mini\s*panel\s*可拖拽浏览已加载时间段/g,
      "the mini panel below can be dragged to browse the loaded range"],
    [/Time\s*窗口\s*\/\s*seconds/g, "Time window / seconds"],
    [/Time窗口\s*\/\s*seconds/g, "Time window / seconds"],
    [/Last\s*data\s*Time/g, "Last data time"],
    [/Last\s*dataTime/g, "Last data time"],
    [/Three\s*channels\s*Status/g, "Three-channel status"],
    [/Three\s*channelsStatus/g, "Three-channel status"],
    [/Device\s*online\s*Status/g, "Device online status"],
    [/DeviceonlineStatus/g, "Device online status"],
    [/Latest\s*[一1]\s*hours\s*入库量/g, "records stored in the last 1 hour"],
    [/跳到\s*Last\s*data/g, "Jump to last data"],
    [/暂停/g, "Pause"],
    [/继续/g, "Resume"],
    [/检索过往\s*miniSEED\s*数据/g, "query historical miniSEED data"],
    [/可同时显示/g, "can be displayed together"],
    [/主图显示最后/g, "the main chart shows the last"],
    [/图下方小窗口/g, "the mini panel below"],
    [/可拖拽浏览已加载时间段/g, "can be dragged to browse the loaded range"],
    [/入库量/g, "stored records"],
    [/时间窗口/g, "time window"],
    [/窗口/g, "window"],
    [/按\s*Device/g, "By device"],
    [/UTC\s*Time\s*range/g, "UTC time range"]
  ];

  function getLang(){
    var keys = ["portalLangMode","mseed_lang","portal_lang","lang","i18nextLng"];
    for (var i=0;i<keys.length;i++){
      var v = "";
      try { v = (localStorage.getItem(keys[i]) || "").toLowerCase(); } catch(e) {}
      if (v === "en" || v.indexOf("en-") === 0) return "en";
      if (v === "zh" || v === "cn" || v.indexOf("zh") === 0) return "zh";
    }
    var htmlLang = (document.documentElement.getAttribute("lang") || "").toLowerCase();
    if (htmlLang.indexOf("en") === 0) return "en";
    if (htmlLang.indexOf("zh") === 0) return "zh";

    var text = document.body ? document.body.innerText : "";
    var englishHits = (text.match(/Overview|Live waveform|Historical waveform|Data export|Alert center|System status|Admin|Device overview/g) || []).length;
    var chineseHits = (text.match(/[\u4e00-\u9fff]/g) || []).length;
    if (englishHits >= 2) return "en";
    return chineseHits > 0 ? "zh" : "en";
  }

  function skipNode(n){
    if (!n || !n.parentElement) return true;
    var p = n.parentElement;
    if (p.closest("[data-no-i18n]")) return true;
    var tag = p.tagName;
    return tag === "SCRIPT" || tag === "STYLE" || tag === "CODE" || tag === "PRE";
  }

  function cleanupEnglish(s){
    if (!s) return s;
    var out = s;
    var trimmed = out.trim();
    if (Object.prototype.hasOwnProperty.call(EXACT_ZH_EN, trimmed)) {
      return out.replace(trimmed, EXACT_ZH_EN[trimmed]);
    }

    PARTS_ZH_EN.forEach(function(pair){
      out = out.replace(pair[0], pair[1]);
    });

    // Fix leftover Chinese punctuation and connectors in mixed English strings.
    if (/[A-Za-z]/.test(out)) {
      out = out.replace(/、/g, ", ");
      out = out.replace(/；/g, "; ");
      out = out.replace(/，/g, ", ");
      out = out.replace(/：/g, ": ");
      out = out.replace(/。/g, ".");
      out = out.replace(/和/g, " and ");
      out = out.replace(/一/g, "1");
    }

    // Common concatenations caused by previous partial replacements.
    out = out
      .replace(/Deviceoffline/g, "Device offline")
      .replace(/Deviceonline/g, "Device online")
      .replace(/Current alerts\s*(\d+)/g, "Current alerts $1")
      .replace(/\bcritical\s*(\d+)/g, "critical $1")
      .replace(/\bwarning\s*(\d+)/g, "warning $1")
      .replace(/\brecovered\s*(\d+)/g, "recovered $1")
      .replace(/records=(\d+)/g, "records=$1")
      .replace(/components=/g, "components=");

    // Space between English words and numbers, but do not damage ISO timestamps.
    out = out.replace(/([A-Za-z])(\d)(?!\d{3}-)/g, "$1 $2");
    out = out.replace(/(\d)([A-Za-z])/g, "$1 $2");
    out = out.replace(/\s{2,}/g, " ");

    return out;
  }

  function processTextNodes(){
    if (!document.body) return;
    var walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    var nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    nodes.forEach(function(n){
      if (skipNode(n)) return;
      var old = n.nodeValue || "";
      var neu = cleanupEnglish(old);
      if (neu !== old) n.nodeValue = neu;
    });
  }

  function processAttributes(){
    document.querySelectorAll("input,textarea,button,option,a,[title],[aria-label]").forEach(function(el){
      ["placeholder","title","aria-label","value"].forEach(function(attr){
        if (!el.hasAttribute || !el.hasAttribute(attr)) return;
        if (attr === "value" && !(el.tagName === "INPUT" && ["button","submit","reset"].includes((el.getAttribute("type")||"").toLowerCase()))) return;
        var old = el.getAttribute(attr) || "";
        var neu = cleanupEnglish(old);
        if (neu !== old) el.setAttribute(attr, neu);
      });
    });
  }

  function unlock(){
    try {
      if (window.__mseedI18nUnlockStrong) window.__mseedI18nUnlockStrong();
      if (window.__mseedI18nUnlock) window.__mseedI18nUnlock();
      document.documentElement.classList.remove("mseed-i18n-preload");
      document.documentElement.classList.remove("i18n-lock");
    } catch(e) {}
  }

  function apply(){
    if (getLang() !== "en") {
      unlock();
      return;
    }

    try {
      if (window.mseedI18N && typeof window.mseedI18N.applyTranslations === "function") {
        window.mseedI18N.applyTranslations();
      }
    } catch(e) {}
    try {
      if (window.mseedI18NStage61 && typeof window.mseedI18NStage61.applyCleanup === "function") {
        window.mseedI18NStage61.applyCleanup();
      }
    } catch(e) {}

    processTextNodes();
    processAttributes();
    unlock();
  }

  function auditRemainingChinese(){
    var out = [];
    if (!document.body) return out;
    var walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
      var n = walker.currentNode;
      if (skipNode(n)) continue;
      var t = (n.nodeValue || "").trim();
      if (/[\u4e00-\u9fff]/.test(t)) {
        out.push({text:t, parent:n.parentElement ? n.parentElement.tagName : ""});
      }
    }
    return out;
  }

  var timer = null;
  function schedule(){
    clearTimeout(timer);
    timer = setTimeout(apply, 20);
  }

  document.addEventListener("DOMContentLoaded", function(){
    apply();
    setTimeout(apply, 60);
    setTimeout(apply, 180);
    setTimeout(apply, 500);
    setTimeout(apply, 1200);

    var mo = new MutationObserver(schedule);
    mo.observe(document.body, {childList:true, subtree:true, characterData:true, attributes:true, attributeFilter:["placeholder","title","aria-label","value"]});
  });

  // Also run immediately if the script is loaded after DOMContentLoaded.
  if (document.readyState !== "loading") {
    setTimeout(apply, 0);
  }

  window.mseedI18NStage62 = {
    apply: apply,
    auditRemainingChinese: auditRemainingChinese,
    cleanupEnglish: cleanupEnglish
  };
})();
JSCODE

# Load Stage6.2 after every previous i18n script.
if [ -f "$TEMPLATES/base.html" ] && ! grep -q "i18n_stage6_2_final_cleanup.js" "$TEMPLATES/base.html"; then
  sudo sed -i 's#</body>#<script src="/static/js/i18n_stage6_2_final_cleanup.js?v=stage6_2"></script>\n</body>#' "$TEMPLATES/base.html"
fi

if command -v systemctl >/dev/null 2>&1; then
  sudo systemctl restart mseed-web-portal || true
  sudo systemctl restart nginx || true
fi

echo "Stage6.2 final i18n cleanup patch applied."
echo "Press Ctrl+F5. Browser console audit: window.mseedI18NStage62.auditRemainingChinese()"
