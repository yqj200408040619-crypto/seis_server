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

[ -f "$TEMPLATES/base.html" ] && sudo cp "$TEMPLATES/base.html" "$TEMPLATES/base.html.bak_i18n_stage6_1_$TS" || true

# ---------------------------------------------------------------------------
# 1) Prevent Chinese flash in English mode.
#    When English is stored in localStorage, hide body before first paint.
#    The Stage6.1 script removes the lock after it finishes translating.
# ---------------------------------------------------------------------------
if [ -f "$TEMPLATES/base.html" ] && ! grep -q "STAGE6_1_I18N_NO_FLASH" "$TEMPLATES/base.html"; then
sudo python3 - <<'PY'
from pathlib import Path
p = Path("/opt/mseed-web-portal/app/templates/base.html")
s = p.read_text()
head_inject = r'''
<!-- STAGE6_1_I18N_NO_FLASH -->
<script>
(function(){
  try {
    var keys = ["portalLangMode","mseed_lang","portal_lang","lang","i18nextLng"];
    var lang = "";
    for (var i=0;i<keys.length;i++){
      var v = (localStorage.getItem(keys[i]) || "").toLowerCase();
      if (v.indexOf("en") === 0) { lang = "en"; break; }
    }
    if (lang === "en") {
      document.documentElement.classList.add("i18n-lock");
    }
    window.__mseedI18nUnlock = function(){
      document.documentElement.classList.remove("i18n-lock");
    };
    setTimeout(function(){
      document.documentElement.classList.remove("i18n-lock");
    }, 5000);
  } catch(e) {}
})();
</script>
<style>
html.i18n-lock body { visibility: hidden !important; }
html.i18n-lock::before {
  content: "Loading…";
  position: fixed;
  top: 20px;
  left: 20px;
  color: #e5e7eb;
  font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  z-index: 999999;
}
</style>
'''
if "</head>" in s:
    s = s.replace("</head>", head_inject + "\n</head>", 1)
else:
    s = head_inject + "\n" + s
p.write_text(s)
PY
fi

# ---------------------------------------------------------------------------
# 2) Stage6.1 cleanup layer.
#    It fixes mixed Chinese/English fragments that are produced by partial
#    translation, normalizes spacing, and audits visible Chinese in English mode.
# ---------------------------------------------------------------------------
sudo tee "$STATIC_JS/i18n_stage6_1_no_flash_cleanup.js" > /dev/null <<'JSCODE'
(function(){
  "use strict";

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
    var englishHits = (text.match(/Overview|Live waveform|Historical waveform|Data export|Alert center|System status|Admin/g) || []).length;
    var chineseHits = (text.match(/[\u4e00-\u9fff]/g) || []).length;
    return (englishHits >= 2 && chineseHits > 0) ? "en" : (chineseHits > 0 ? "zh" : "en");
  }

  function skipTextNode(n){
    if (!n || !n.parentElement) return true;
    var p = n.parentElement;
    if (p.closest("[data-no-i18n]")) return true;
    var tag = p.tagName;
    return tag === "SCRIPT" || tag === "STYLE" || tag === "CODE" || tag === "PRE";
  }

  function fixEnglishText(s){
    if (!s) return s;
    var out = s;

    // Full mixed alert sentence from the screenshot and likely variants.
    out = out.replace(/Device\s*offline\s*、?\s*Missing\s*channel\s*和\s*Data\s*interruption\s*会在这里汇总。?\s*后台检查默认\s*per\s*minute\s*运行一次。?/g,
      "Device offline, missing channels, and data interruptions are summarized here. The background check runs once per minute by default.");
    out = out.replace(/Device\s*offline\s*、?\s*Missing\s*channel\s*and\s*Data\s*interruption\s*会在这里汇总。?\s*后台检查默认\s*per\s*minute\s*运行一次。?/g,
      "Device offline, missing channels, and data interruptions are summarized here. The background check runs once per minute by default.");
    out = out.replace(/设备\s*offline\s*、?\s*通道缺失\s*和\s*数据断流\s*会在这里汇总。?\s*后台检查默认每分钟运行一次。?/g,
      "Device offline status, missing channels, and data interruptions are summarized here. The background check runs once per minute by default.");

    // Fragment-level cleanup.
    out = out.replace(/Deviceoffline/g, "Device offline");
    out = out.replace(/Current alerts\s*(\d+)/g, "Current alerts $1");
    out = out.replace(/\bcritical\s*(\d+)/g, "critical $1");
    out = out.replace(/\bwarning\s*(\d+)/g, "warning $1");
    out = out.replace(/\brecovered\s*(\d+)/g, "recovered $1");
    out = out.replace(/Missing\s*channel\s*和\s*Data\s*interruption/g, "missing channels, and data interruptions");
    out = out.replace(/会在这里汇总。?/g, "are summarized here.");
    out = out.replace(/后台检查默认\s*per\s*minute\s*运行一次。?/g, "The background check runs once per minute by default.");
    out = out.replace(/后台检查默认每分钟运行一次。?/g, "The background check runs once per minute by default.");
    out = out.replace(/运行一次。?/g, "runs once.");
    out = out.replace(/每分钟/g, "per minute");

    // Remaining common single Chinese connectors in mixed English sentences.
    if (/[A-Za-z]/.test(out)) {
      out = out.replace(/和/g, " and ");
      out = out.replace(/、/g, ", ");
      out = out.replace(/。/g, ".");
      out = out.replace(/，/g, ", ");
      out = out.replace(/：/g, ": ");
    }

    // Add spaces between words and numbers/concatenated tokens caused by partial replacement.
    out = out.replace(/([A-Za-z])(\d)/g, "$1 $2");
    out = out.replace(/(\d)([A-Za-z])/g, "$1 $2");
    out = out.replace(/\s{2,}/g, " ");

    return out;
  }

  function applyCleanup(){
    var lang = getLang();
    if (lang !== "en") {
      if (window.__mseedI18nUnlock) window.__mseedI18nUnlock();
      return;
    }

    // Run the broad Stage6 translator first if it exists.
    try {
      if (window.mseedI18N && typeof window.mseedI18N.applyTranslations === "function") {
        window.mseedI18N.applyTranslations();
      }
    } catch(e) {}

    var walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    var nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);

    nodes.forEach(function(n){
      if (skipTextNode(n)) return;
      var old = n.nodeValue || "";
      var neu = fixEnglishText(old);
      if (neu !== old) n.nodeValue = neu;
    });

    // Attribute cleanup.
    document.querySelectorAll("input,textarea,button,option,a,[title],[aria-label]").forEach(function(el){
      ["placeholder","title","aria-label","value"].forEach(function(attr){
        if (!el.hasAttribute || !el.hasAttribute(attr)) return;
        if (attr === "value" && !(el.tagName === "INPUT" && ["button","submit","reset"].includes((el.getAttribute("type")||"").toLowerCase()))) return;
        var old = el.getAttribute(attr);
        var neu = fixEnglishText(old);
        if (neu !== old) el.setAttribute(attr, neu);
      });
    });

    if (window.__mseedI18nUnlock) window.__mseedI18nUnlock();
  }

  function auditRemainingChinese(){
    var out = [];
    if (!document.body) return out;
    var walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
      var n = walker.currentNode;
      if (skipTextNode(n)) continue;
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
    timer = setTimeout(applyCleanup, 30);
  }

  document.addEventListener("DOMContentLoaded", function(){
    applyCleanup();
    setTimeout(applyCleanup, 80);
    setTimeout(applyCleanup, 250);
    setTimeout(applyCleanup, 800);

    var mo = new MutationObserver(schedule);
    mo.observe(document.body, {childList:true, subtree:true, characterData:true});
  });

  window.mseedI18NStage61 = {
    applyCleanup: applyCleanup,
    auditRemainingChinese: auditRemainingChinese
  };
})();
JSCODE

# Load cleanup script last.
if [ -f "$TEMPLATES/base.html" ] && ! grep -q "i18n_stage6_1_no_flash_cleanup.js" "$TEMPLATES/base.html"; then
  sudo sed -i 's#</body>#<script src="/static/js/i18n_stage6_1_no_flash_cleanup.js?v=stage6_1"></script>\n</body>#' "$TEMPLATES/base.html"
fi

if command -v systemctl >/dev/null 2>&1; then
  sudo systemctl restart mseed-web-portal || true
  sudo systemctl restart nginx || true
fi

echo "Stage6.1 i18n no-flash cleanup patch applied."
echo "Switch to English and press Ctrl+F5."
echo "Browser console audit: window.mseedI18NStage61.auditRemainingChinese()"
