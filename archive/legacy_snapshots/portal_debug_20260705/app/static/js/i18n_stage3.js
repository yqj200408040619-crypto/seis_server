(function(){
  'use strict';
  const KEY='mseed.portal.lang';
  const zhToEn={
    '总览':'Overview','概览':'Overview','实时波形':'Live waveform','历史波形':'Historical waveform','数据质量':'Data quality','数据导出':'Data export','管理':'Admin','退出':'Log out','登录':'Log in',
    '数据导出':'Data export','单台设备导出':'Single-device export','批量导出':'Batch export','客户过滤':'Customer filter','全部可见设备':'All visible devices','导出方式':'Export mode','导出勾选设备':'Export selected devices','导出全部可见设备':'Export all visible devices','设备列表':'Device list','全选':'Select all','清空':'Clear','批量导出 ZIP':'Batch export ZIP','导出行为说明':'Export behavior','跳到最新数据':'Jump to latest data','预览范围':'Preview range','导出 miniSEED':'Export miniSEED','开始时间 UTC':'Start time UTC','结束时间 UTC':'End time UTC','分量':'Channels','设备':'Device','记录数':'Records','字节':'Bytes','首条时间':'First time','最后时间':'Last time','总记录数':'Total records','数据缺口':'Data gaps','缺口':'Gaps','重复包':'Duplicates','异常包':'Bad packets','最新数据':'Last data','最后接收':'Last received','离线':'offline','在线':'online','延迟':'delayed','未分组':'Unassigned','说明':'Notes','客户':'Customer','操作':'Actions','保存':'Save','同步设备':'Sync devices',
    '按设备、客户、三分量和 UTC 时间范围导出原始 miniSEED 数据。数据有中断时，导出仍会包含已有数据，并在批量导出的 gaps.csv 中列出缺口。':'Export raw miniSEED by device, customer, channels, and UTC time range. If data is interrupted, the export still contains available records and lists gaps in gaps.csv for batch exports.',
    '批量导出会生成 ZIP 文件，包含每台设备的 miniSEED 文件、manifest.csv 和 gaps.csv。':'Batch export generates a ZIP file containing miniSEED files, manifest.csv, and gaps.csv.',
    '如果数据中断，导出不会失败；文件只包含实际存在的记录，缺口会保存在 gaps.csv 供后续检查。':'If data is interrupted, export does not fail. Files contain only existing records and gaps are written to gaps.csv for review.',
    '导出的是数据库中保存的原始 raw_mseed 记录，不会重新采样或修改波形。':'Export uses raw_mseed records stored in the database. It does not resample or modify waveforms.',
    '如果所选时间段没有记录，系统会显示友好提示，而不是直接返回 JSON 错误。':'If no records exist in the selected range, the system shows a readable message instead of raw JSON.',
    '如果时间段内存在数据中断，miniSEED 文件仍然可用；ObsPy 等工具会识别为不连续数据段。':'If the selected range contains gaps, the miniSEED file is still valid; tools such as ObsPy will read it as discontinuous data segments.'
  };
  const enToZh={}; Object.entries(zhToEn).forEach(([zh,en])=>{ if(!enToZh[en]) enToZh[en]=zh; });
  Object.assign(enToZh, {'offline':'离线','online':'在线','delayed':'延迟','Last data':'最新数据','Duplicates':'重复包','Bad packets':'异常包','Data gaps':'数据缺口','Records':'记录数','Bytes':'字节','Unassigned':'未分组'});
  function lang(){return localStorage.getItem(KEY)||'en';}
  function tr(s){ if(!s) return s; const lead=(s.match(/^\s*/)||[''])[0], trail=(s.match(/\s*$/)||[''])[0]; let t=s.trim().replace(/\s+/g,' '); if(!t) return s; const d=lang()==='zh'?enToZh:zhToEn; if(d[t]) return lead+d[t]+trail; if(lang()==='zh'){ t=t.replace(/\boffline\b/g,'离线').replace(/\bonline\b/g,'在线').replace(/\bdelayed\b/g,'延迟').replace(/\bDuplicates\b/g,'重复包').replace(/\bLast data\b/g,'最新数据').replace(/\bBad packets\b/g,'异常包').replace(/\bUnassigned\b/g,'未分组'); } else { t=t.replace(/离线/g,'offline').replace(/在线/g,'online').replace(/延迟/g,'delayed').replace(/重复包/g,'Duplicates').replace(/最新数据/g,'Last data').replace(/异常包/g,'Bad packets').replace(/未分组/g,'Unassigned'); } return lead+t+trail; }
  function skip(el){return !el||['SCRIPT','STYLE','CODE','PRE','TEXTAREA','CANVAS','SVG'].includes(el.nodeName)||el.closest('[data-no-i18n]')||el.closest('.js-plotly-plot');}
  function apply(root=document.body){
    const w=document.createTreeWalker(root,NodeFilter.SHOW_TEXT,{acceptNode(n){return n.parentElement&&!skip(n.parentElement)&&n.nodeValue.trim()?NodeFilter.FILTER_ACCEPT:NodeFilter.FILTER_REJECT;}}); const ns=[]; while(w.nextNode()) ns.push(w.currentNode); ns.forEach(n=>{const x=tr(n.nodeValue); if(x!==n.nodeValue)n.nodeValue=x;});
    root.querySelectorAll('*').forEach(el=>{ if(skip(el)) return; ['placeholder','title','aria-label','value'].forEach(a=>{ if(!el.hasAttribute(a)) return; if(a==='value'&&!['button','submit','reset'].includes((el.getAttribute('type')||'').toLowerCase())) return; const v=el.getAttribute(a), x=tr(v); if(x!==v) el.setAttribute(a,x); }); });
  }
  document.addEventListener('DOMContentLoaded',()=>{apply(); const mo=new MutationObserver(()=>apply()); mo.observe(document.body,{childList:true,subtree:true,characterData:true});});
  window.addEventListener('storage',apply);
})();
