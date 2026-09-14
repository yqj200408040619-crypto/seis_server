(function(){
  "use strict";

  const ZH_EN = {
    // Navigation and page names
    "总览": "Overview",
    "首页": "Overview",
    "实时波形": "Live waveform",
    "历史波形": "Historical waveform",
    "历史波形查询": "Historical waveform query",
    "三分量历史波形": "Three-component history",
    "三分量实时数据": "Three-component live data",
    "数据质量": "Data quality",
    "数据导出": "Data export",
    "告警中心": "Alert center",
    "告警": "Alerts",
    "系统状态": "System status",
    "系统": "System",
    "管理": "Admin",
    "管理员": "Admin",
    "退出登录": "Log out",
    "登出": "Log out",
    "登录": "Log in",

    // Common nouns
    "设备列表": "Device list",
    "设备": "Device",
    "仪器": "Instrument",
    "客户": "Customer",
    "客户分组": "Customer group",
    "客户过滤": "Customer filter",
    "客户代码": "Customer code",
    "联系人": "Contact",
    "用户": "User",
    "用户列表": "User list",
    "用户列表与客户归属": "User list and customer mapping",
    "用户归属": "User mapping",
    "账号": "Username",
    "用户名": "Username",
    "显示名称": "Display name",
    "密码": "Password",
    "角色": "Role",
    "状态": "Status",
    "操作": "Actions",
    "详情": "Details",
    "备注": "Notes",
    "类型": "Type",
    "范围": "Range",
    "前缀": "Prefix",
    "位置": "Location",
    "经度": "Longitude",
    "纬度": "Latitude",
    "安装位置": "Installation location",
    "安装日期": "Installation date",
    "站点名": "Site name",
    "别名": "Alias",
    "设备别名": "Device alias",

    // Status and metrics
    "在线": "online",
    "离线": "offline",
    "延迟": "delayed",
    "正常": "normal",
    "异常": "abnormal",
    "严重": "critical",
    "警告": "warning",
    "信息": "info",
    "恢复": "recovered",
    "已恢复": "recovered",
    "未确认": "unacknowledged",
    "已确认": "acknowledged",
    "未分组": "Unassigned",
    "未设置": "Not set",
    "无": "None",
    "暂无": "None",
    "无数据": "No data",
    "没有数据": "No data",
    "无记录": "No records",
    "无告警": "No alerts",
    "当前告警": "Current alerts",
    "历史告警": "Alert history",
    "级别": "Level",
    "最后出现": "Last seen",
    "最后数据": "Last data",
    "最新数据": "Latest data",
    "最新接收": "Last received",
    "最新接收时间": "Last received time",
    "数据包": "packets",
    "包数": "packets",
    "重复包": "Duplicates",
    "缺口": "Gap",
    "缺口数": "Gap count",
    "异常包": "Abnormal packets",
    "坏包": "Bad packets",
    "组件": "Components",
    "分量": "Channels",
    "三分量": "Three channels",
    "通道": "Channel",
    "通道缺失": "Missing channel",
    "数据断流": "Data interruption",
    "数据中断": "Data interruption",
    "数据完整性": "Data integrity",
    "质量事件": "Quality events",
    "最近质量事件": "Recent quality events",
    "服务状态": "Service status",
    "运行中": "active",
    "已停止": "stopped",
    "磁盘使用率": "Disk usage",
    "磁盘剩余": "Disk free",
    "接收数据库大小": "Receiver DB size",
    "最近备份": "Recent backup",
    "文件数": "Files",
    "大小": "Size",
    "开始时间": "Start time",
    "结束时间": "End time",
    "生成时间": "Generated at",

    // Forms and buttons
    "保存": "Save",
    "保存用户": "Save user",
    "保存客户": "Save customer",
    "创建": "Create",
    "更新": "Update",
    "创建 / 更新用户": "Create / update user",
    "创建/更新用户": "Create / update user",
    "创建客户": "Create customer",
    "新建客户": "Create customer",
    "授权访问": "Grant access",
    "设备授权": "Device access",
    "授权新设备": "Grant new device",
    "已授权设备": "Authorized devices",
    "取消授权": "Revoke",
    "同步设备": "Sync devices",
    "立即同步": "Sync now",
    "立即检查": "Check now",
    "确认": "Confirm",
    "取消": "Cancel",
    "删除": "Delete",
    "编辑": "Edit",
    "返回": "Back",
    "刷新": "Refresh",
    "查询": "Query",
    "开始": "Start",
    "停止": "Stop",
    "全选": "Select all",
    "清空": "Clear",
    "导出": "Export",
    "导出方式": "Export mode",
    "导出 miniSEED": "Export miniSEED",
    "批量导出": "Batch export",
    "批量导出 ZIP": "Batch export ZIP",
    "导出分段 ZIP": "Export segmented ZIP",
    "导出勾选设备": "Export selected devices",
    "导出全部可见设备": "Export all visible devices",
    "按时间段批量导出": "Export by time segments",
    "按固定时间段导出": "Export by fixed time windows",
    "单台设备导出": "Single-device export",
    "预览范围": "Preview range",
    "跳到最新": "Jump to latest",
    "跳到最新数据": "Jump to latest data",
    "上一时间窗": "Previous window",
    "下一时间窗": "Next window",
    "自动刷新": "Auto refresh",
    "刷新间隔": "Refresh interval",

    // Export terms
    "开始时间 UTC": "Start time UTC",
    "结束时间 UTC": "End time UTC",
    "分段分钟数": "Segment minutes",
    "时间段": "Time window",
    "时间范围": "Time range",
    "所选时间段": "Selected time range",
    "全部可见设备": "All visible devices",
    "勾选设备": "Selected devices",
    "已选设备": "Selected devices",
    "设备选择": "Device selection",
    "设备列表": "Device list",
    "客户过滤": "Customer filter",
    "全部设备": "All devices",
    "所有设备": "All devices",
    "全部分量": "All channels",
    "全部通道": "All channels",
    "原始 miniSEED 数据": "Raw miniSEED data",
    "原始数据": "Raw data",
    "导出文件": "Export file",
    "导出结果": "Export result",
    "清单": "manifest",
    "数据缺口": "Data gaps",

    // Admin stage terms
    "批量客户设备规则": "Bulk customer device rules",
    "起始序号": "Start serial",
    "结束序号": "End serial",
    "Key 前缀": "Key prefix",
    "暂无批量规则。": "No bulk rules yet.",
    "普通用户": "User",
    "活跃": "Active",
    "启用": "Enabled",
    "禁用": "Disabled",

    // Sentences / paragraphs seen in previous stages
    "按固定间隔拉取最近一段时间数据，适合现场监控。": "Pull the most recent data at a fixed interval, suitable for live monitoring.",
    "按设备、UTC 时间范围检索过去 miniSEED 数据；BHZ / BHN / BHE 可同时显示。": "Query historical miniSEED data by device and UTC time range; BHZ / BHN / BHE can be displayed together.",
    "默认加载最近 30 分钟，主图显示最后 5 分钟；图下方小窗口可拖拽浏览已加载时间段。": "Default window loads 30 minutes; the main chart shows the last 5 minutes. The mini panel below can be dragged to browse the loaded range.",
    "设备 offline、通道缺失和数据断流会在这里汇总。后台检查默认每分钟运行一次。": "Device offline status, missing channels, and data interruptions are summarized here. The background check runs once per minute by default.",
    "仅管理员可见，用于检查服务、磁盘、备份和数据库体积。": "Visible to administrators only. Used to inspect services, disk usage, backups, and database size.",
    "按设备、客户、分量和 UTC 时间范围导出原始 miniSEED 数据。数据有中断时，导出仍会包含已有数据，并在批量导出的 gaps.csv 中列出缺口。": "Export raw miniSEED data by device, customer, channels, and UTC time range. If data is interrupted, existing records are still exported and gaps are listed in gaps.csv for batch export.",
    "批量导出会生成 ZIP 文件，包含每台设备的 miniSEED 文件、manifest.csv 和 gaps.csv。": "Batch export generates a ZIP file containing each device's miniSEED files, manifest.csv, and gaps.csv.",
    "如果数据中断，导出不会失败；文件只包含实际存在的记录，缺口会保存在 gaps.csv 供后续检查。": "If data is interrupted, export will not fail. Files contain only existing records, and gaps are saved in gaps.csv for later inspection.",
    "导出的是数据库中保存的原始 raw_mseed 记录，不会重新采样或修改波形。": "The export uses the original raw_mseed records stored in the database. It does not resample or modify the waveform.",
    "如果所选时间段没有记录，系统会显示友好提示，而不是直接返回 JSON 错误。": "If the selected time range has no records, the system shows a readable message instead of returning a raw JSON error.",
    "如果时间段内存在数据中断，miniSEED 文件仍然可用；ObsPy 等工具会识别为不连续数据段。": "If the selected time range contains data gaps, the miniSEED file remains usable; tools such as ObsPy will recognize it as a discontinuous data segment.",
    "导出行为说明": "Export behavior notes",
    "说明": "Notes",
    "选择至少一台设备": "Select at least one device.",
    "当前时间窗口内没有可绘制数据。": "No plottable data in the current time window.",
    "没有可绘制数据": "No plottable data",
    "没有找到记录": "No records found",
    "没有找到数据": "No data found",
    "保存失败": "Save failed",
    "用户保存失败": "Save user failed",

    // Chart and table text
    "时间": "Time",
    "振幅": "Amplitude",
    "样本值": "Sample value",
    "原始计数": "Raw counts",
    "采样率": "Sampling rate",
    "记录数": "Records",
    "字节数": "Bytes",
    "首条时间": "First time",
    "最后时间": "Last time",
    "主图": "Main chart",
    "小窗口": "Mini panel",

    // Small words and units
    "最近": "Latest",
    "过去": "Past",
    "每分钟": "per minute",
    "分钟": "minutes",
    "秒": "seconds",
    "小时": "hours",
    "天": "days",
    "全部": "All",
    "所有": "All",
    "选择": "Select",
    "已选择": "Selected",
    "未选择": "Not selected",
    "可见": "visible",
    "不可见": "not visible"
  };

  const EN_ZH = {
    "Overview": "总览",
    "Live waveform": "实时波形",
    "Historical waveform": "历史波形",
    "Data quality": "数据质量",
    "Data export": "数据导出",
    "Alerts": "告警",
    "Alert center": "告警中心",
    "System": "系统",
    "Admin": "管理",
    "Log out": "退出登录",
    "Device": "设备",
    "Devices": "设备",
    "Customer": "客户",
    "User": "用户",
    "Username": "账号",
    "Password": "密码",
    "Role": "角色",
    "Status": "状态",
    "Actions": "操作",
    "Save user": "保存用户",
    "Save customer": "保存客户",
    "Create / update user": "创建 / 更新用户",
    "Grant access": "授权访问",
    "Device access": "设备授权",
    "Bulk customer device rules": "批量客户设备规则",
    "No bulk rules yet.": "暂无批量规则。",
    "Unassigned": "未分组",
    "online": "在线",
    "offline": "离线",
    "Latest data": "最新数据",
    "Last data": "最后数据",
    "Last received": "最新接收",
    "Duplicates": "重复包",
    "Bad packets": "异常包",
    "Gap count": "缺口数",
    "Disk usage": "磁盘使用率",
    "Disk free": "磁盘剩余",
    "Receiver DB size": "接收数据库大小",
    "Recent backup": "最近备份",
    "Service status": "服务状态",
    "Data gaps": "数据缺口",
    "Start time UTC": "开始时间 UTC",
    "End time UTC": "结束时间 UTC",
    "Channels": "分量",
    "Query": "查询",
    "Jump to latest data": "跳到最新数据",
    "Preview range": "预览范围",
    "Export miniSEED": "导出 miniSEED",
    "Batch export ZIP": "批量导出 ZIP",
    "Export segmented ZIP": "导出分段 ZIP",
    "Export by time segments": "按时间段批量导出",
    "Segment minutes": "分段分钟数",
    "Select all": "全选",
    "Clear": "清空"
  };

  function getStoredLang(){
    const keys = ["portalLangMode", "portal_lang", "mseed_lang", "lang", "i18nextLng"];
    for (const k of keys) {
      const v = (localStorage.getItem(k) || "").toLowerCase();
      if (v === "en" || v.startsWith("en-")) return "en";
      if (v === "zh" || v === "cn" || v.startsWith("zh")) return "zh";
    }
    return "";
  }

  function inferLang(){
    const htmlLang = (document.documentElement.getAttribute("lang") || "").toLowerCase();
    if (htmlLang.startsWith("en")) return "en";
    if (htmlLang.startsWith("zh")) return "zh";

    const stored = getStoredLang();
    if (stored) return stored;

    const bodyText = document.body ? document.body.innerText : "";
    // If the UI shows a "中文" switch, current mode is usually English.
    if (Array.from(document.querySelectorAll("a,button")).some(el => (el.textContent || "").trim() === "中文")) return "en";
    if (Array.from(document.querySelectorAll("a,button")).some(el => (el.textContent || "").trim().toLowerCase() === "english")) return "zh";

    // Mixed English UI with leftover Chinese: prefer English cleanup.
    const englishHits = (bodyText.match(/Overview|Live waveform|Data export|Admin|System|Alerts/g) || []).length;
    const chineseHits = (bodyText.match(/[\u4e00-\u9fff]/g) || []).length;
    if (englishHits >= 2 && chineseHits > 0) return "en";

    return chineseHits > 0 ? "zh" : "en";
  }

  function setLang(lang){
    if (lang !== "en" && lang !== "zh") return;
    localStorage.setItem("portalLangMode", lang);
    localStorage.setItem("mseed_lang", lang);
    document.documentElement.setAttribute("lang", lang === "en" ? "en" : "zh-CN");
    applyTranslations();
  }

  function dictionaryFor(lang){
    return lang === "en" ? ZH_EN : EN_ZH;
  }

  function replaceExactOrPartial(text, dict){
    if (!text) return text;
    const trimmed = text.trim();
    if (!trimmed) return text;

    if (Object.prototype.hasOwnProperty.call(dict, trimmed)) {
      return text.replace(trimmed, dict[trimmed]);
    }

    let out = text;
    const keys = Object.keys(dict).sort((a,b)=>b.length-a.length);
    for (const k of keys) {
      if (k && out.includes(k)) out = out.split(k).join(dict[k]);
    }

    // Regex cleanup for common dynamic mixed strings.
    out = out
      .replace(/最新数据\s*[:：]/g, "Latest data: ")
      .replace(/最后数据\s*[:：]/g, "Last data: ")
      .replace(/最新接收\s*[:：]/g, "Last received: ")
      .replace(/包数\s*[:：]/g, "Packets: ")
      .replace(/记录数\s*[:：]/g, "Records: ")
      .replace(/缺口数\s*[:：]/g, "Gap count: ")
      .replace(/分量\s*[:：]/g, "Channels: ")
      .replace(/状态\s*[:：]/g, "Status: ")
      .replace(/设备\s*[:：]/g, "Device: ")
      .replace(/客户\s*[:：]/g, "Customer: ");

    return out;
  }

  function shouldSkipNode(node){
    if (!node) return true;
    const p = node.parentElement;
    if (!p) return true;
    const tag = p.tagName;
    return tag === "SCRIPT" || tag === "STYLE" || tag === "CODE" || tag === "PRE" || p.closest("[data-no-i18n]");
  }

  function translateTextNodes(root, lang){
    const dict = dictionaryFor(lang);
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    for (const n of nodes) {
      if (shouldSkipNode(n)) continue;
      const v = n.nodeValue || "";
      const nv = replaceExactOrPartial(v, dict);
      if (nv !== v) n.nodeValue = nv;
    }
  }

  function translateAttributes(lang){
    const dict = dictionaryFor(lang);
    const attrs = ["placeholder", "title", "aria-label", "data-bs-title", "data-title", "value"];
    document.querySelectorAll("input,textarea,button,option,optgroup,a,select,[title],[aria-label]").forEach(el => {
      for (const a of attrs) {
        if (!el.hasAttribute || !el.hasAttribute(a)) continue;
        if (a === "value" && !(el.tagName === "INPUT" && ["button","submit","reset"].includes((el.getAttribute("type")||"").toLowerCase()))) continue;
        const old = el.getAttribute(a);
        const nv = replaceExactOrPartial(old, dict);
        if (nv !== old) el.setAttribute(a, nv);
      }
      if (el.tagName === "OPTION" || el.tagName === "BUTTON" || el.tagName === "A") {
        for (const n of Array.from(el.childNodes)) {
          if (n.nodeType === Node.TEXT_NODE) {
            const old = n.nodeValue || "";
            const nv = replaceExactOrPartial(old, dict);
            if (nv !== old) n.nodeValue = nv;
          }
        }
      }
    });
  }

  function fixLanguageButtons(lang){
    // Normalize language switch labels.
    document.querySelectorAll("a,button").forEach(el => {
      const t = (el.textContent || "").trim();
      if (/^(English|英语|英文)$/.test(t)) {
        el.addEventListener("click", () => setLang("en"), {capture:true});
      }
      if (/^(中文|Chinese|汉语)$/.test(t)) {
        el.addEventListener("click", () => setLang("zh"), {capture:true});
      }
    });
  }

  function auditRemainingChinese(){
    const out = [];
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
      const n = walker.currentNode;
      if (shouldSkipNode(n)) continue;
      const t = (n.nodeValue || "").trim();
      if (/[\u4e00-\u9fff]/.test(t)) {
        out.push({text:t, parent:n.parentElement ? n.parentElement.tagName : ""});
      }
    }
    return out;
  }

  let applying = false;
  function applyTranslations(){
    if (applying || !document.body) return;
    applying = true;
    try {
      const lang = inferLang();
      document.documentElement.setAttribute("data-i18n-effective-lang", lang);
      translateTextNodes(document.body, lang);
      translateAttributes(lang);
      fixLanguageButtons(lang);
      if (lang === "en") {
        const remaining = auditRemainingChinese();
        if (remaining.length) {
          console.warn("[i18n] Remaining Chinese text after translation:", remaining.slice(0, 50));
        }
      }
    } finally {
      applying = false;
    }
  }

  // Catch language switch clicks even when older i18n code uses different keys.
  document.addEventListener("click", function(e){
    const el = e.target.closest ? e.target.closest("a,button") : null;
    if (!el) return;
    const txt = (el.textContent || "").trim();
    if (/^(English|英语|英文)$/.test(txt)) setTimeout(()=>setLang("en"), 10);
    if (/^(中文|Chinese|汉语)$/.test(txt)) setTimeout(()=>setLang("zh"), 10);
  }, true);

  document.addEventListener("DOMContentLoaded", () => {
    applyTranslations();
    setTimeout(applyTranslations, 100);
    setTimeout(applyTranslations, 400);
    setTimeout(applyTranslations, 1200);

    const mo = new MutationObserver(() => {
      clearTimeout(window.__i18nStage6Timer);
      window.__i18nStage6Timer = setTimeout(applyTranslations, 60);
    });
    mo.observe(document.body, {childList:true, subtree:true, characterData:true});
  });

  window.mseedI18N = {
    setLang,
    applyTranslations,
    auditRemainingChinese,
    zhToEn: ZH_EN,
    enToZh: EN_ZH
  };
})();
