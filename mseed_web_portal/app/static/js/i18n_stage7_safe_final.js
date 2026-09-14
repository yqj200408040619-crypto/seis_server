(function(){
  "use strict";

  var EXACT = {
    "暂停": "Pause",
    "继续": "Resume",
    "跳到Last data": "Jump to last data",
    "Time窗口 / seconds": "Time window / seconds",
    "Last dataTime": "Last data time",
    "online阈值: Latest 5 minutes内收到数据": "Online threshold: data received within the latest 5 minutes",
    "online阈值：Latest 5 minutes内收到数据": "Online threshold: data received within the latest 5 minutes",
    "Channels（Three channels可同时Select）": "Channels (three channels can be selected together)",
    "Channels (Three channels可同时Select)": "Channels (three channels can be selected together)",
    "按Device, UTC Time range检索过往 miniSEED 数据；BHZ / BHN / BHE 可同时显示.": "Query historical miniSEED data by device and UTC time range; BHZ / BHN / BHE can be displayed together.",
    "按Device, UTC Time range检索过往 miniSEED 数据；BHZ / BHN / BHE 可同时显示。": "Query historical miniSEED data by device and UTC time range; BHZ / BHN / BHE can be displayed together.",
    "显示DeviceonlineStatus, Last dataTime, Three channelsStatus and Latest一hours入库量.": "Shows device online status, last data time, three-channel status, and records stored in the last 1 hour.",
    "显示DeviceonlineStatus, Last dataTime, Three channelsStatus and Latest1hours入库量.": "Shows device online status, last data time, three-channel status, and records stored in the last 1 hour.",
    "默认加载最近 30 分钟，主图显示最后 5 分钟；图下方小窗口可拖拽浏览已加载时间段.": "Default window loads 30 minutes; the main chart shows the last 5 minutes. The mini panel below can be dragged to browse the loaded range.",
    "默认加载最近 30 分钟，主图显示最后 5 分钟；图下方小窗口可拖拽浏览已加载时间段。": "Default window loads 30 minutes; the main chart shows the last 5 minutes. The mini panel below can be dragged to browse the loaded range.",
    "下方Mini panel可拖拽浏览已加载时间段": "The mini panel below can be dragged to browse the loaded range"
  };

  var PHRASES = [
    [/online\s*阈值[:：]\s*Latest\s*5\s*minutes\s*内收到数据/g,
      "Online threshold: data received within the latest 5 minutes"],
    [/Channels\s*[（(]\s*Three\s*channels\s*可同时\s*Select\s*[）)]/g,
      "Channels (three channels can be selected together)"],
    [/Time\s*窗口\s*\/\s*seconds/g, "Time window / seconds"],
    [/Last\s*data\s*Time/g, "Last data time"],
    [/Last\s*dataTime/g, "Last data time"],
    [/跳到\s*Last\s*data/g, "Jump to last data"],
    [/暂停/g, "Pause"],
    [/继续/g, "Resume"],

    [/按\s*Device,\s*UTC\s*Time\s*range\s*检索过往\s*miniSEED\s*数据[；;]\s*BHZ\s*\/\s*BHN\s*\/\s*BHE\s*可同时显示[。.]?/g,
      "Query historical miniSEED data by device and UTC time range; BHZ / BHN / BHE can be displayed together."],
    [/显示\s*Device\s*online\s*Status,\s*Last\s*data\s*Time,\s*Three\s*channels\s*Status\s*and\s*Latest\s*[一1]\s*hours\s*入库量[。.]?/gi,
      "Shows device online status, last data time, three-channel status, and records stored in the last 1 hour."],
    [/显示\s*DeviceonlineStatus,\s*Last\s*dataTime,\s*Three\s*channelsStatus\s*and\s*Latest\s*[一1]\s*hours\s*入库量[。.]?/gi,
      "Shows device online status, last data time, three-channel status, and records stored in the last 1 hour."],
    [/默认加载最近\s*30\s*分钟，主图显示最后\s*5\s*分钟[；;]\s*图下方小窗口可拖拽浏览已加载时间段[。.]?/g,
      "Default window loads 30 minutes; the main chart shows the last 5 minutes. The mini panel below can be dragged to browse the loaded range."],
    [/下方\s*Mini\s*panel\s*可拖拽浏览已加载时间段/g,
      "The mini panel below can be dragged to browse the loaded range"],

    [/DeviceonlineStatus/g, "device online status"],
    [/Device\s*online\s*Status/g, "device online status"],
    [/Three\s*channelsStatus/g, "three-channel status"],
    [/Three\s*channels\s*Status/g, "three-channel status"],
    [/Latest\s*[一1]\s*hours\s*入库量/g, "records stored in the last 1 hour"],
    [/检索过往\s*miniSEED\s*数据/g, "query historical miniSEED data"],
    [/可同时显示/g, "can be displayed together"],
    [/主图显示最后\s*5\s*分钟/g, "the main chart shows the last 5 minutes"],
    [/图下方小窗口/g, "the mini panel below"],
    [/可拖拽浏览已加载时间段/g, "can be dragged to browse the loaded range"],
    [/入库量/g, "stored records"],
    [/窗口/g, "window"],
    [/阈值/g, "threshold"],
    [/内收到数据/g, "data received within"],
    [/可同时\s*Select/g, "can be selected together"],
    [/和/g, " and "],
    [/、/g, ", "],
    [/；/g, "; "],
    [/，/g, ", "],
    [/：/g, ": "],
    [/。/g, "."],
    [/一/g, "1"]
  ];

  function langIsEnglish(){
    var keys = ["portalLangMode","mseed_lang","portal_lang","lang","i18nextLng"];
    for (var i=0;i<keys.length;i++){
      var v = "";
      try { v = (localStorage.getItem(keys[i]) || "").toLowerCase(); } catch(e) {}
      if (v === "en" || v.indexOf("en-") === 0) return true;
      if (v === "zh" || v === "cn" || v.indexOf("zh") === 0) return false;
    }
    var htmlLang = (document.documentElement.getAttribute("lang") || "").toLowerCase();
    if (htmlLang.indexOf("en") === 0) return true;
    if (htmlLang.indexOf("zh") === 0) return false;
    var text = document.body ? document.body.innerText : "";
    var englishHits = (text.match(/Overview|Live waveform|Historical waveform|Data export|Device overview|Alert center|Admin/g) || []).length;
    var chineseHits = (text.match(/[\u4e00-\u9fff]/g) || []).length;
    return englishHits >= 2 || chineseHits === 0;
  }

  function unlock(){
    try {
      if (window.__mseedStage7Unlock) window.__mseedStage7Unlock();
      document.documentElement.classList.remove("mseed-i18n-pending");
      document.documentElement.classList.remove("i18n-lock");
      document.documentElement.classList.remove("mseed-i18n-preload");
    } catch(e) {}
  }

  function skipElement(el){
    if (!el) return true;
    if (el.closest("[data-no-i18n]")) return true;
    if (el.closest(".js-plotly-plot,.plotly,.plot-container,.modebar,.rangeslider,.slider-container")) return true;
    if (el.closest("svg,canvas")) return true;
    var tag = el.tagName;
    return tag === "SCRIPT" || tag === "STYLE" || tag === "CODE" || tag === "PRE" || tag === "SVG" || tag === "CANVAS";
  }

  function fixText(text){
    if (!text) return text;
    var out = text;
    var trimmed = out.trim();
    if (Object.prototype.hasOwnProperty.call(EXACT, trimmed)) {
      return out.replace(trimmed, EXACT[trimmed]);
    }
    PHRASES.forEach(function(pair){
      out = out.replace(pair[0], pair[1]);
    });
    if (/[A-Za-z]/.test(out)) {
      out = out.replace(/([A-Za-z])(\d)/g, "$1 $2");
      out = out.replace(/(\d)([A-Za-z])/g, "$1 $2");
      out = out.replace(/\s{2,}/g, " ");
      out = out.replace(/Current alerts\s+(\d+)/g, "Current alerts $1");
      out = out.replace(/\bcritical\s+(\d+)/g, "critical $1");
      out = out.replace(/\bwarning\s+(\d+)/g, "warning $1");
    }
    return out;
  }

  function translateNormalDom(){
    if (!document.body || !langIsEnglish()) {
      unlock();
      return;
    }

    // Text nodes outside Plotly only.
    var walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    var nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    nodes.forEach(function(n){
      if (!n.parentElement || skipElement(n.parentElement)) return;
      var old = n.nodeValue || "";
      var neu = fixText(old);
      if (neu !== old) n.nodeValue = neu;
    });

    // Attributes outside Plotly only.
    document.querySelectorAll("input,textarea,button,option,a,[title],[aria-label]").forEach(function(el){
      if (skipElement(el)) return;
      ["placeholder","title","aria-label","value"].forEach(function(attr){
        if (!el.hasAttribute || !el.hasAttribute(attr)) return;
        if (attr === "value" && !(el.tagName === "INPUT" && ["button","submit","reset"].includes((el.getAttribute("type")||"").toLowerCase()))) return;
        var old = el.getAttribute(attr) || "";
        var neu = fixText(old);
        if (neu !== old) el.setAttribute(attr, neu);
      });
    });

    unlock();
    resizePlots();
  }

  function resizePlots(){
    try {
      if (window.Plotly && window.Plotly.Plots) {
        document.querySelectorAll(".js-plotly-plot").forEach(function(gd){
          try { window.Plotly.Plots.resize(gd); } catch(e) {}
        });
      }
    } catch(e) {}
  }

  function auditRemainingChinese(){
    var out = [];
    if (!document.body) return out;
    var walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
      var n = walker.currentNode;
      if (!n.parentElement || skipElement(n.parentElement)) continue;
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
    timer = setTimeout(translateNormalDom, 40);
  }

  document.addEventListener("DOMContentLoaded", function(){
    translateNormalDom();
    setTimeout(translateNormalDom, 80);
    setTimeout(translateNormalDom, 250);
    setTimeout(translateNormalDom, 800);
    setTimeout(resizePlots, 1100);
    setTimeout(resizePlots, 2000);

    var mo = new MutationObserver(function(records){
      for (var i=0;i<records.length;i++){
        var target = records[i].target;
        if (target && target.nodeType === 1 && skipElement(target)) continue;
        schedule();
        break;
      }
    });
    mo.observe(document.body, {childList:true, subtree:true, characterData:true});
  });

  if (document.readyState !== "loading") {
    setTimeout(translateNormalDom, 0);
  }

  window.mseedI18NStage7 = {
    apply: translateNormalDom,
    resizePlots: resizePlots,
    auditRemainingChinese: auditRemainingChinese,
    fixText: fixText
  };
})();
