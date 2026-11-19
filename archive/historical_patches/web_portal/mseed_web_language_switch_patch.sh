#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/mseed-web-portal"
BASE_HTML="$APP_DIR/app/templates/base.html"
STATIC_JS_DIR="$APP_DIR/app/static/js"
STATIC_CSS="$APP_DIR/app/static/css/app.css"
I18N_JS="$STATIC_JS_DIR/i18n.js"

if [ ! -f "$BASE_HTML" ]; then
  echo "ERROR: $BASE_HTML not found"
  exit 1
fi

sudo mkdir -p "$STATIC_JS_DIR"

TS="$(date +%Y%m%d_%H%M%S)"
sudo cp "$BASE_HTML" "$BASE_HTML.bak_i18n_$TS"
[ -f "$STATIC_CSS" ] && sudo cp "$STATIC_CSS" "$STATIC_CSS.bak_i18n_$TS" || true

# Create frontend i18n script. This is intentionally frontend-only: no DB/API changes.
sudo tee "$I18N_JS" > /dev/null <<'JS'
(function () {
  const zhToEn = {
    "客户数据访问平台": "Customer Seismic Data Portal",
    "登录后查看授权地震仪的实时与历史波形。": "Log in to view authorized instruments, live waveforms, and historical waveforms.",
    "账号": "Username",
    "密码": "Password",
    "登录": "Log in",
    "退出": "Log out",

    "总览": "Overview",
    "实时波形": "Live waveform",
    "历史波形": "Historical waveform",
    "历史波形查询": "Historical waveform query",
    "管理": "Admin",
    "设备总览": "Device overview",
    "展示当前账号可访问的仪器、三分量和最新入库时间。": "Shows instruments accessible to the current account, three-component data, and the latest ingest time.",
    "刷新页面可更新统计": "Refresh the page to update statistics",
    "当前账号还没有分配设备。请联系管理员分配仪器权限。": "No devices have been assigned to this account. Contact the administrator for instrument access.",
    "总包数": "Total packets",
    "最新时间": "Latest time",
    "实时波形": "Live waveform",
    "历史查询": "History",
    "设备": "Device",
    "时间窗口 / 秒": "Time window / s",
    "刷新 / 秒": "Refresh / s",
    "分量": "Components",
    "三分量实时数据": "Three-component live data",
    "等待数据...": "Waiting for data...",
    "暂停": "Pause",
    "继续": "Resume",
    "按固定间隔拉取最近一段时间数据，适合现场监控。": "Fetches the latest data at a fixed interval for field monitoring.",

    "按设备、分量和 UTC 时间范围检索过往 miniSEED 数据。": "Query historical miniSEED data by device, component, and UTC time range.",
    "开始时间 UTC": "Start time UTC",
    "结束时间 UTC": "End time UTC",
    "查询": "Query",
    "请选择时间范围。": "Select a time range.",
    "跳到最近": "Go to latest",
    "前移一屏": "Previous window",
    "后移一屏": "Next window",
    "加载中...": "Loading...",
    "无数据": "No data",
    "没有数据": "No data",

    "账号与设备权限": "Accounts and device permissions",
    "同步接收端数据库，创建客户账号，并分配可访问设备。": "Sync receiver databases, create customer accounts, and assign device permissions.",
    "同步设备": "Sync devices",
    "创建 / 更新用户": "Create / update user",
    "显示名称": "Display name",
    "角色": "Role",
    "保存用户": "Save user",
    "设备列表": "Device list",
    "用户列表": "User list",
    "授权": "Grant",
    "取消授权": "Revoke",
    "设备权限": "Device access",
    "用户": "User",
    "保存": "Save",
    "操作": "Actions",
    "类型": "Type",
    "序号": "Serial",
    "状态": "Status",
    "路径": "Path",
    "最后同步": "Last synced",

    "未知": "Unknown",
    "未知 IP": "unknown IP"
  };

  // Add common short labels and variants.
  zhToEn["实时"] = "Live";
  zhToEn["历史"] = "History";
  zhToEn["最新"] = "Latest";
  zhToEn["包数"] = "Packets";
  zhToEn["正常"] = "Normal";
  zhToEn["离线"] = "Offline";
  zhToEn["在线"] = "Online";

  const enToZh = Object.fromEntries(Object.entries(zhToEn).map(([k, v]) => [v, k]));

  function getLang() {
    return localStorage.getItem("portalLang") || "zh";
  }

  function setLang(lang) {
    localStorage.setItem("portalLang", lang === "en" ? "en" : "zh");
  }

  function replaceExactText(text, lang) {
    const trimmed = text.trim();
    if (!trimmed) return text;
    const table = lang === "en" ? zhToEn : enToZh;
    const translated = table[trimmed];
    if (!translated) return text;
    return text.replace(trimmed, translated);
  }

  function shouldSkip(node) {
    if (!node || !node.parentElement) return true;
    const tag = node.parentElement.tagName;
    return ["SCRIPT", "STYLE", "TEXTAREA", "CODE", "PRE"].includes(tag);
  }

  function translateTextNodes(root, lang) {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode(node) {
        if (shouldSkip(node)) return NodeFilter.FILTER_REJECT;
        if (!node.nodeValue || !node.nodeValue.trim()) return NodeFilter.FILTER_REJECT;
        return NodeFilter.FILTER_ACCEPT;
      }
    });
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    for (const node of nodes) node.nodeValue = replaceExactText(node.nodeValue, lang);
  }

  function translateAttributes(root, lang) {
    const table = lang === "en" ? zhToEn : enToZh;
    const attrs = ["placeholder", "title", "aria-label", "value"];
    root.querySelectorAll("input, button, option, a, [title], [aria-label]").forEach(el => {
      for (const attr of attrs) {
        if (!el.hasAttribute(attr)) continue;
        const v = el.getAttribute(attr);
        if (table[v]) el.setAttribute(attr, table[v]);
      }
    });
  }

  function updateToggle(lang) {
    const btn = document.getElementById("langToggle");
    if (!btn) return;
    btn.textContent = lang === "en" ? "中文" : "English";
    btn.setAttribute("aria-label", lang === "en" ? "Switch to Chinese" : "Switch to English");
  }

  let applying = false;
  function applyLanguage(lang) {
    if (applying) return;
    applying = true;
    document.documentElement.lang = lang === "en" ? "en" : "zh-CN";
    document.body.dataset.lang = lang;
    translateTextNodes(document.body, lang);
    translateAttributes(document.body, lang);
    updateToggle(lang);
    applying = false;
  }

  function installToggle() {
    const btn = document.getElementById("langToggle");
    if (!btn) return;
    btn.addEventListener("click", function () {
      const next = getLang() === "en" ? "zh" : "en";
      setLang(next);
      applyLanguage(next);
    });
  }

  let observerTimer = null;
  function installObserver() {
    const obs = new MutationObserver(() => {
      if (applying) return;
      clearTimeout(observerTimer);
      observerTimer = setTimeout(() => applyLanguage(getLang()), 80);
    });
    obs.observe(document.body, { childList: true, subtree: true, characterData: true });
  }

  document.addEventListener("DOMContentLoaded", function () {
    const params = new URLSearchParams(window.location.search);
    const urlLang = params.get("lang");
    if (urlLang === "en" || urlLang === "zh") setLang(urlLang);
    installToggle();
    applyLanguage(getLang());
    installObserver();
  });
})();
JS

# Insert language toggle into base.html after the brand link if not already present.
sudo /opt/miniforge3/envs/mseed-web/bin/python - <<'PY'
from pathlib import Path
p = Path('/opt/mseed-web-portal/app/templates/base.html')
s = p.read_text()

if 'id="langToggle"' not in s:
    target = '<a class="navbar-brand fw-semibold" href="/dashboard">{{ brand }}</a>'
    replacement = target + '''
    <div class="ms-auto me-2 portal-lang-switch">
      <button id="langToggle" type="button" class="btn btn-sm btn-outline-light">English</button>
    </div>'''
    if target not in s:
        raise SystemExit('brand anchor not found in base.html')
    s = s.replace(target, replacement, 1)

if '/static/js/i18n.js' not in s:
    target = '<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>'
    replacement = '<script src="/static/js/i18n.js?v=20260701"></script>\n' + target
    if target not in s:
        raise SystemExit('bootstrap script anchor not found in base.html')
    s = s.replace(target, replacement, 1)

p.write_text(s)
print('patched base.html')
PY

# Add small style for language switch.
if [ -f "$STATIC_CSS" ] && ! sudo grep -q "portal-lang-switch" "$STATIC_CSS"; then
  sudo tee -a "$STATIC_CSS" > /dev/null <<'CSS'

.portal-lang-switch .btn {
  border-color: rgba(255,255,255,.28);
  color: rgba(255,255,255,.9);
  border-radius: 999px;
  padding: .28rem .7rem;
}
.portal-lang-switch .btn:hover {
  background: rgba(255,255,255,.12);
  color: #fff;
}
CSS
fi

sudo systemctl restart mseed-web-portal || true
sudo systemctl restart nginx || true

echo "OK: language switch patch installed. Open the site and press Ctrl+F5. Use the English/中文 button in the top bar."
