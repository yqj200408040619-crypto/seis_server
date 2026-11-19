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

[ -f "$TEMPLATES/base.html" ] && sudo cp "$TEMPLATES/base.html" "$TEMPLATES/base.html.bak_stage10_1_textfix_$TS" || true

# A very small post-i18n cleanup. It only fixes ordinary HTML text outside Plotly.
sudo tee "$STATIC_JS/i18n_stage10_1_textfix.js" >/dev/null <<'JSCODE'
(function(){
  "use strict";

  const FIXES = [
    [/三分量\s*Historical waveform/g, "Three-component historical waveform"],
    [/三分量\s*history/g, "Three-component history"],
    [/三分量\s*Live waveform/g, "Three-component live waveform"],
    [/三分量\s*实时波形/g, "Three-component live waveform"],
    [/三分量\s*历史波形/g, "Three-component historical waveform"],
    [/三分量\s*Historical waveform query/g, "Three-component historical waveform query"],
  ];

  function isEnglishMode(){
    const keys = ["mseed.portal.lang","portalLangMode","mseed_lang","portal_lang","lang","i18nextLng"];
    for (const k of keys) {
      let v = "";
      try { v = (localStorage.getItem(k) || "").toLowerCase(); } catch(e) {}
      if (v === "en" || v.startsWith("en-")) return true;
      if (v === "zh" || v === "cn" || v.startsWith("zh")) return false;
    }
    const text = document.body ? document.body.innerText : "";
    return /Historical waveform|Data export|Overview|Admin/.test(text);
  }

  function skip(el){
    if (!el) return true;
    if (el.closest("[data-no-i18n]")) return true;
    if (el.closest(".js-plotly-plot,.plotly,.modebar,.rangeslider,.range-slider,.slider-container,.plot-container")) return true;
    if (el.closest("svg,canvas")) return true;
    return ["SCRIPT","STYLE","CODE","PRE","SVG","CANVAS"].includes(el.tagName);
  }

  function fixText(s){
    if (!s) return s;
    let out = s;
    for (const [re, repl] of FIXES) out = out.replace(re, repl);
    out = out.replace(/\s{2,}/g, " ");
    return out;
  }

  function apply(){
    if (!isEnglishMode() || !document.body) return;

    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);

    for (const n of nodes) {
      if (!n.parentElement || skip(n.parentElement)) continue;
      const old = n.nodeValue || "";
      const neu = fixText(old);
      if (neu !== old) n.nodeValue = neu;
    }
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

  window.mseedI18NStage101 = { apply };
})();
JSCODE

# Load after Stage10 / Stage9 i18n scripts.
if [ -f "$TEMPLATES/base.html" ] && ! grep -q "i18n_stage10_1_textfix.js" "$TEMPLATES/base.html"; then
  sudo sed -i 's#</body>#<script src="/static/js/i18n_stage10_1_textfix.js?v=stage10_1"></script>\n</body>#' "$TEMPLATES/base.html"
fi

if command -v systemctl >/dev/null 2>&1; then
  sudo systemctl restart mseed-web-portal || true
  sudo systemctl restart nginx || true
fi

echo "Stage10.1 text fix applied."
echo "Press Ctrl+F5 on the History page."
