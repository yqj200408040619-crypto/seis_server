(function(){
  "use strict";

  const LANG_KEYS = ["mseed.portal.lang","portalLangMode","mseed_lang","portal_lang","lang","i18nextLng"];

  const EXACT = new Map(Object.entries({
    // Navigation and common
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
    "退出": "Log out",
    "登录": "Log in",
    "设备": "Device",
    "客户": "Customer",
    "用户": "User",
    "账号": "Username",
    "显示名称": "Display name",
    "密码": "Password",
    "角色": "Role",
    "状态": "Status",
    "级别": "Severity",
    "严重程度": "Severity",
    "类型": "Type",
    "组件": "Component",
    "分量": "Channels",
    "消息": "Message",
    "详情": "Details",
    "操作": "Actions",
    "备注": "Notes",
    "范围": "Range",
    "前缀": "Prefix",
    "类别": "Category",
    "大小": "Size",
    "文件数": "Files",
    "开始时间": "Started",
    "确认": "Confirm",
    "删除": "Delete",
    "保存": "Save",
    "同步设备": "Sync devices",
    "立即检查": "Check now",
    "未分组": "Unassigned",
    "暂无": "None",

    // Overview / live / history
    "设备总览": "Device overview",
    "在线阈值：最近 5 分钟内收到数据": "Online threshold: data received within the latest 5 minutes",
    "显示设备在线状态、最新数据时间、三分量状态和最近一小时入库量。": "Shows device online status, last data time, three-channel status, and records stored in the last 1 hour.",
    "按固定间隔拉取最近一段时间数据，适合现场监控。": "Pull the most recent data at a fixed interval, suitable for live monitoring.",
    "按设备、UTC 时间范围检索过往 miniSEED 数据；BHZ / BHN / BHE 可同时显示。": "Query historical miniSEED data by device and UTC time range; BHZ / BHN / BHE can be displayed together.",
    "默认加载最近 30 分钟，主图显示最后 5 分钟；图下方小窗口可拖拽浏览已加载时间段。": "Default window loads 30 minutes; the main chart shows the last 5 minutes. The mini panel below can be dragged to browse the loaded range.",
    "时间窗口 / 秒": "Time window / seconds",
    "刷新 / 秒": "Refresh / seconds",
    "分量（三分量可同时选择）": "Channels (three channels can be selected together)",
    "开始时间 UTC": "Start time UTC",
    "结束时间 UTC": "End time UTC",
    "查询": "Query",
    "跳到最近": "Jump to latest",
    "跳到最新": "Jump to latest",
    "跳到最新数据": "Jump to latest data",
    "前移一屏": "Previous window",
    "后移一屏": "Next window",
    "暂停": "Pause",
    "继续": "Resume",
    "最新数据时间": "Last data time",
    "最后接收时间": "Last received time",
    "总包数": "Total packets",
    "最近 1 小时": "Last 1 hour",
    "在线": "Online",
    "离线": "Offline",
    "延迟": "Delayed",
    "实时波形": "Live waveform",
    "历史查询": "History",
    "导出": "Export",

    // Data quality
    "查看设备断流、重复包、异常包和三分量完整性。": "Inspect device interruptions, duplicate packets, bad packets, and three-channel integrity.",
    "最近质量事件": "Recent quality events",
    "无质量事件。": "No quality events.",
    "缺口数": "Gap count",
    "重复包": "Duplicates",
    "异常包": "Bad packets",
    "最后数据": "Last data",
    "最新数据": "Latest data",
    "缺失": "missing",

    // Alerts
    "设备离线、通道缺失和数据断流会在这里汇总。后台检查默认每分钟运行一次。": "Device offline status, missing channels, and data interruptions are summarized here. The background check runs once per minute by default.",
    "当前没有告警。": "No alerts at the moment.",
    "当前告警": "Open alerts",
    "最后出现": "Last seen",
    "动作": "Action",

    // Export
    "按设备、客户、三分量和 UTC 时间范围导出原始 miniSEED 数据。数据有中断时，导出仍会包含已有数据，并在批量导出的 gaps.csv 中列出缺口。": "Export raw miniSEED data by device, customer, channels, and UTC time range. If data is interrupted, existing records are still exported and gaps are listed in gaps.csv for batch export.",
    "单台设备导出": "Single-device export",
    "预览范围": "Preview range",
    "导出 miniSEED": "Export miniSEED",
    "批量导出": "Batch export",
    "客户过滤": "Customer filter",
    "导出方式": "Export mode",
    "全部可见设备": "All visible devices",
    "导出勾选设备": "Export selected devices",
    "导出全部可见设备": "Export all visible devices",
    "设备列表": "Device list",
    "全选": "Select all",
    "清空": "Clear",
    "批量导出 ZIP": "Batch export ZIP",
    "按时间段批量导出": "Export by time segments",
    "分段分钟数": "Segment minutes",
    "导出分段 ZIP": "Export segmented ZIP",
    "导出行为说明": "Export behavior notes",
    "说明：": "Notes:",
    "说明": "Notes",
    "批量导出会生成 ZIP 文件，包含每台设备的 miniSEED 文件、manifest.csv 和 gaps.csv。": "Batch export generates a ZIP file containing each device's miniSEED files, manifest.csv, and gaps.csv.",
    "如果数据中断，导出不会失败；文件只包含实际存在的记录，缺口会保存在 gaps.csv 供后续检查。": "If data is interrupted, export will not fail. Files contain only existing records, and gaps are saved in gaps.csv for later inspection.",
    "导出的是数据库中保存的原始 raw_mseed 记录，不会重新采样或修改波形。": "The export uses the original raw_mseed records stored in the database. It does not resample or modify the waveform.",
    "如果所选时间段没有记录，系统会显示友好提示，而不是直接返回 JSON 错误。": "If the selected time range has no records, the system shows a readable message instead of returning a raw JSON error.",
    "如果时间段内存在数据中断，miniSEED 文件仍然可用；ObsPy 等工具会识别为不连续数据段。": "If the selected time range contains data gaps, the miniSEED file remains usable; tools such as ObsPy will recognize it as a discontinuous data segment.",
    "跳到Last data": "Jump to last data",

    // System
    "仅管理员可见，用于检查服务、磁盘、备份和数据库体积。": "Visible to administrators only. Used to inspect services, disk usage, backups, and database size.",
    "暂无备份记录。": "No backup records.",
    "磁盘使用率": "Disk usage",
    "磁盘剩余": "Disk free",
    "接收数据库大小": "Receiver DB size",
    "最近备份": "Recent backups",
    "已开始": "Started",

    // Admin
    "账号、客户与设备权限": "Accounts, customers, and device access",
    "同步接收端数据库，创建客户账号，维护客户分组、设备别名和设备权限。": "Synchronize receiver databases, create customer accounts, and manage customer groups, device aliases, and access permissions.",
    "创建 / 更新用户": "Create / update user",
    "创建 / 更新客户分组": "Create / update customer group",
    "客户名称": "Customer name",
    "客户代码": "Customer code",
    "联系人": "Contact",
    "保存用户": "Save user",
    "保存客户": "Save customer",
    "批量客户设备规则": "Bulk customer device rules",
    "例如 SS 01000–02000：当范围内的新设备被识别后，会自动归入所选客户；该客户下的用户会自动看到这些设备。": "Example: SS 01000–02000. Newly detected devices in this range will be assigned to the selected customer; users under that customer will automatically see these devices.",
    "起始序号": "Start serial",
    "结束序号": "End serial",
    "Key 前缀": "Key prefix",
    "保存并应用规则": "Save and apply rule",
    "暂无批量规则。": "No bulk rules yet.",
    "设备别名与客户分组": "Device aliases and customer groups",
    "别名 / 站点": "Alias / site",
    "显示标签": "Display label",
    "客户可读别名": "Customer-readable alias",
    "站点名称": "Site name",
    "安装位置说明": "Installation location note",
    "安装日期": "Installation date",
    "用户列表与客户归属": "User list and customer mapping",
    "客户分组": "Customer group",
    "设备权限": "Device access",
    "已授权设备": "Authorized devices",
    "授权新设备": "Grant new device",
    "授权": "Grant"
  }));

  const REGEX = [
    // Mixed strings created by earlier partial translations.
    [/查看设备断流[,，、]\s*重复包[,，、]\s*异常包\s*and\s*三分量完整性[。.]?/g, "Inspect device interruptions, duplicate packets, bad packets, and three-channel integrity."],
    [/设备离线[,，、]\s*通道缺失\s*and\s*数据断流会在这里汇总[。.]?\s*后台检查默认每分钟运行\s*1\s*次[。.]?/g, "Device offline status, missing channels, and data interruptions are summarized here. The background check runs once per minute by default."],
    [/设备离线[,，、]\s*通道缺失和数据断流会在这里汇总[。.]?\s*后台检查默认每分钟运行一次[。.]?/g, "Device offline status, missing channels, and data interruptions are summarized here. The background check runs once per minute by default."],
    [/按设备[,，、]\s*客户[,，、]\s*三分量\s*and\s*UTC\s*时间范围导出原始\s*miniSEED\s*数据[。.]?\s*数据有中断时[,，]\s*导出仍会包含已有数据[,，]\s*并在批量导出的\s*gaps\.csv\s*中列出缺口[。.]?/g, "Export raw miniSEED data by device, customer, channels, and UTC time range. If data is interrupted, existing records are still exported and gaps are listed in gaps.csv for batch export."],
    [/仅管理员可见[,，]\s*用于检查服务[,，]\s*磁盘[,，]\s*备份\s*and\s*数据库体积[。.]?/g, "Visible to administrators only. Used to inspect services, disk usage, backups, and database size."],
    [/mseed-tcp-server\s*active/g, "mseed-tcp-server active"],
    [/mseed-web-portal\s*active/g, "mseed-web-portal active"],
    [/mseed-backup\.timer\s*active/g, "mseed-backup.timer active"],
    [/mseed-alert-worker\.timer\s*active/g, "mseed-alert-worker.timer active"],
    [/nginx\s*active/g, "nginx active"],
    [/Disk used\s*(\d)/g, "Disk used $1"],
    [/Disk free\s*(\d)/g, "Disk free $1"],
    [/Open alerts\s*(\d)/g, "Open alerts $1"],
    [/Critical\s*(\d)/g, "Critical $1"],
    [/Warning\s*(\d)/g, "Warning $1"],
    [/Resolved\s*(\d)/g, "Resolved $1"],
    [/online\s*阈值[:：]\s*Latest\s*5\s*minutes\s*内收到数据/g, "Online threshold: data received within the latest 5 minutes"],
    [/Channels\s*[（(]\s*Three\s*channels\s*可同时\s*Select\s*[）)]/g, "Channels (three channels can be selected together)"],
    [/Time\s*窗口\s*\/\s*seconds/g, "Time window / seconds"],
    [/Last\s*data\s*Time/g, "Last data time"],
    [/Last\s*dataTime/g, "Last data time"],
    [/跳到\s*Last\s*data/g, "Jump to last data"],
    [/显示\s*DeviceonlineStatus,\s*Last\s*dataTime,\s*Three\s*channelsStatus\s*and\s*Latest\s*[一1]\s*hours\s*入库量[。.]?/gi, "Shows device online status, last data time, three-channel status, and records stored in the last 1 hour."],
    [/按\s*Device,\s*UTC\s*Time\s*range\s*检索过往\s*miniSEED\s*数据[；;]\s*BHZ\s*\/\s*BHN\s*\/\s*BHE\s*可同时显示[。.]?/g, "Query historical miniSEED data by device and UTC time range; BHZ / BHN / BHE can be displayed together."],
    [/默认加载最近\s*30\s*分钟，主图显示最后\s*5\s*分钟[；;]\s*图下方小窗口可拖拽浏览已加载时间段[。.]?/g, "Default window loads 30 minutes; the main chart shows the last 5 minutes. The mini panel below can be dragged to browse the loaded range."],
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
    [/入库量/g, "stored records"]
  ];

  function getLang(){
    for (const k of LANG_KEYS) {
      let v = "";
      try { v = (localStorage.getItem(k) || "").toLowerCase(); } catch(e) {}
      if (v === "en" || v.startsWith("en-")) return "en";
      if (v === "zh" || v === "cn" || v.startsWith("zh")) return "zh";
    }
    return "en";
  }

  function setLang(lang){
    if (lang !== "en" && lang !== "zh") return;
    for (const k of LANG_KEYS) {
      try { localStorage.setItem(k, lang); } catch(e) {}
    }
    location.reload();
  }

  function shouldSkip(el){
    if (!el) return true;
    if (el.closest("[data-no-i18n]")) return true;
    if (el.closest(".js-plotly-plot,.plotly,.modebar,.rangeslider,.range-slider,.slider-container,.plot-container")) return true;
    if (el.closest("svg,canvas")) return true;
    return ["SCRIPT","STYLE","CODE","PRE","SVG","CANVAS"].includes(el.tagName);
  }

  function translateText(text){
    if (!text) return text;
    const trimmed = text.trim();
    if (EXACT.has(trimmed)) return text.replace(trimmed, EXACT.get(trimmed));

    let out = text;
    for (const [re, repl] of REGEX) out = out.replace(re, repl);

    for (const [zh, en] of EXACT.entries()) {
      if (zh.length >= 3 && out.includes(zh)) out = out.split(zh).join(en);
    }

    if (/[A-Za-z]/.test(out)) {
      out = out.replace(/([A-Za-z])(\d)/g, "$1 $2").replace(/(\d)([A-Za-z])/g, "$1 $2");
      out = out.replace(/\s{2,}/g, " ");
    }
    return out;
  }
  function apply(){
    const lang = getLang();
    document.documentElement.setAttribute("lang", lang === "en" ? "en" : "zh-CN");

    document.querySelectorAll("[data-lang-toggle], #langToggle").forEach((btn) => {
      btn.textContent = lang === "en" ? "中文" : "English";
      btn.onclick = () => setLang(lang === "en" ? "zh" : "en");
    });

    if (lang !== "en") {
      return;
    }

    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    for (const n of nodes) {
      if (!n.parentElement || shouldSkip(n.parentElement)) continue;
      const old = n.nodeValue || "";
      const neu = translateText(old);
      if (neu !== old) n.nodeValue = neu;
    }

    document.querySelectorAll("input,textarea,button,option,a,[title],[aria-label]").forEach(el => {
      if (shouldSkip(el)) return;
      for (const attr of ["placeholder","title","aria-label","value"]) {
        if (!el.hasAttribute(attr)) continue;
        if (attr === "value" && !(el.tagName === "INPUT" && ["button","submit","reset"].includes((el.getAttribute("type") || "").toLowerCase()))) continue;
        const old = el.getAttribute(attr) || "";
        const neu = translateText(old);
        if (neu !== old) el.setAttribute(attr, neu);
      }
    });

    if (window.__mseedI18nStage10Unlock) window.__mseedI18nStage10Unlock();
  }

  function audit(){
    const out = [];
    if (getLang() !== "en") return out;
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
      const n = walker.currentNode;
      if (!n.parentElement || shouldSkip(n.parentElement)) continue;
      const t = (n.nodeValue || "").trim();
      if (/[\u4e00-\u9fff]/.test(t)) out.push({text:t, tag:n.parentElement.tagName});
    }
    return out;
  }

  let timer = null;
  function schedule(){ clearTimeout(timer); timer = setTimeout(apply, 50); }

  document.addEventListener("DOMContentLoaded", () => {
    apply();
    setTimeout(apply, 100);
    setTimeout(apply, 400);
    setTimeout(apply, 1000);
    const mo = new MutationObserver(schedule);
    mo.observe(document.body, {childList:true, subtree:true, characterData:true, attributes:true, attributeFilter:["placeholder","title","aria-label","value"]});
  });

  if (document.readyState !== "loading") setTimeout(apply, 0);
  window.mseedI18NStage10 = {getLang, setLang, apply, audit, translateText};
})();
