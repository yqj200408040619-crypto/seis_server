(function(){
  const DICT = {
    zh: {
      'Overview':'总览','Live waveform':'实时波形','Historical waveform':'历史波形','Data quality':'数据质量','Data export':'数据导出','System':'系统','Admin':'管理','Alerts':'告警','Alert center':'告警中心','Log out':'退出登录','Device':'设备','Devices':'设备','Start time UTC':'开始时间 UTC','End time UTC':'结束时间 UTC','Channels':'分量','Channel':'分量','Query':'查询','Jump to latest':'跳到最新','Jump to latest data':'跳到最新数据','Previous window':'上一时间窗','Next window':'下一时间窗','Single-device export':'单台设备导出','Preview range':'预览范围','Export miniSEED':'导出 miniSEED','Customer':'客户','Customer group':'客户分组','Create / update user':'创建 / 更新用户','Save user':'保存用户','Save customer':'保存客户','Save':'保存','Grant access':'授权访问','Device access':'设备授权','User list and customer mapping':'用户列表与客户归属','Bulk customer device rules':'批量客户设备规则','Type':'类型','Start serial':'起始序号','End serial':'结束序号','Key prefix':'Key 前缀','Notes':'备注','Actions':'操作','Role':'角色','Username':'账号','Display name':'显示名称','Password':'密码','Contact':'联系人','Customer code':'客户代码','Critical':'严重','Warning':'警告','Recovered':'已恢复','Current alerts':'当前告警','Last seen':'最后出现','Status':'状态','Level':'级别','Details':'详情','Confirm':'确认','Live waveform':'实时波形','Historical waveform query':'历史波形查询','Historical waveform':'历史波形','Three-component history':'三分量历史波形','Three-component live data':'三分量实时数据','No plottable data in the current time window.':'当前时间窗口内没有可绘制数据。','No bulk rules yet.':'暂无批量规则。','Unassigned':'未分组','Range':'范围','Prefix':'前缀','Started':'开始时间','Files':'文件数','Size':'大小','Disk usage':'磁盘使用率','Disk free':'磁盘剩余','Receiver DB size':'接收数据库大小','Recent backup':'最近备份','Service status':'服务状态','Active':'运行中','offline':'离线','online':'在线','Duplicates':'重复包','Last data':'最后数据','Gap count':'缺口数','Abnormal packets':'异常包','Check now':'立即检查','Export by time segments':'按时间段批量导出','Segment minutes':'分段分钟数','Export segmented ZIP':'导出分段 ZIP','Select all':'全选','Clear':'清空','All visible devices':'全部可见设备','Selected devices':'勾选设备','Default window loads 30 minutes; the main chart shows the last 5 minutes; the mini panel below can drag to browse the loaded range.':'默认加载最近 30 分钟，主图显示最后 5 分钟；图下方小窗口可拖拽浏览已加载时间段。'
    },
    en: {
      '总览':'Overview','实时波形':'Live waveform','历史波形':'Historical waveform','数据质量':'Data quality','数据导出':'Data export','系统':'System','管理':'Admin','告警':'Alerts','告警中心':'Alert center','退出登录':'Log out','设备':'Device','开始时间 UTC':'Start time UTC','结束时间 UTC':'End time UTC','分量':'Channels','查询':'Query','跳到最新':'Jump to latest','跳到最新数据':'Jump to latest data','上一时间窗':'Previous window','下一时间窗':'Next window','单台设备导出':'Single-device export','预览范围':'Preview range','导出 miniSEED':'Export miniSEED','客户':'Customer','客户分组':'Customer group','创建 / 更新用户':'Create / update user','保存用户':'Save user','保存客户':'Save customer','保存':'Save','授权访问':'Grant access','设备授权':'Device access','用户列表与客户归属':'User list and customer mapping','批量客户设备规则':'Bulk customer device rules','类型':'Type','起始序号':'Start serial','结束序号':'End serial','Key 前缀':'Key prefix','备注':'Notes','操作':'Actions','账号':'Username','显示名称':'Display name','密码':'Password','联系人':'Contact','客户代码':'Customer code','严重':'Critical','警告':'Warning','已恢复':'Recovered','当前告警':'Current alerts','最后出现':'Last seen','状态':'Status','级别':'Level','详情':'Details','确认':'Confirm','历史波形查询':'Historical waveform query','三分量历史波形':'Three-component history','三分量实时数据':'Three-component live data','当前时间窗口内没有可绘制数据。':'No plottable data in the current time window.','暂无批量规则。':'No bulk rules yet.','未分组':'Unassigned','范围':'Range','前缀':'Prefix','开始时间':'Started','文件数':'Files','大小':'Size','磁盘使用率':'Disk usage','磁盘剩余':'Disk free','接收数据库大小':'Receiver DB size','最近备份':'Recent backup','服务状态':'Service status','运行中':'Active','离线':'offline','在线':'online','重复包':'Duplicates','最后数据':'Last data','缺口':'Gap count','异常包':'Abnormal packets','立即检查':'Check now','按时间段批量导出':'Export by time segments','分段分钟数':'Segment minutes','导出分段 ZIP':'Export segmented ZIP','全选':'Select all','清空':'Clear','全部可见设备':'All visible devices','勾选设备':'Selected devices','默认加载最近 30 分钟，主图显示最后 5 分钟；图下方小窗口可拖拽浏览已加载时间段。':'Default window loads 30 minutes; the main chart shows the last 5 minutes; the mini panel below can drag to browse the loaded range.',
      '按设备、UTC 时间范围检索过去 miniSEED 数据；BHZ / BHN / BHE 可同时显示。':'Query historical miniSEED data by device and UTC time range; BHZ / BHN / BHE can be displayed together.',
      '按固定间隔拉取最近一段时间数据，适合现场监控。':'Pull the most recent data at a fixed interval, suitable for live monitoring.',
      '设备 offline、通道缺失和数据断流会在这里汇总。后台检查默认每分钟运行一次。':'Device offline, missing channels, and data gaps are summarized here. Background checks run once per minute by default.',
      '仅管理员可见，用于检查服务、磁盘、备份和数据库体积。':'Visible to administrators only, used to inspect services, disk, backups, and database sizes.',
      '按设备、客户、分量和 UTC 时间范围导出原始 miniSEED 数据。数据有中断时，导出仍会包含已有数据，并在批量导出的 gaps.csv 中列出缺口。':'Export raw miniSEED data by device, customer, channels, and UTC time range. If data is interrupted, existing records are still exported and gaps are listed in gaps.csv for batch export.'
    }
  };

  function currentLang(){
    const txt = document.documentElement.innerText || '';
    const btn = document.querySelector('a[href*="lang"],button[data-lang],.lang-toggle');
    const tag = document.documentElement.getAttribute('data-lang') || '';
    if(tag) return tag;
    if(btn && /English|英文/.test(btn.textContent||'')) {
      return /English/.test(btn.textContent||'') ? 'zh' : 'en';
    }
    // fallback: if page contains lots of Chinese, assume zh mode currently.
    return /[\u4e00-\u9fff]/.test(txt) ? 'zh' : 'en';
  }
  function tr(text, lang){
    const t = (text||'').trim();
    if(!t) return text;
    if(DICT[lang] && DICT[lang][t]) return DICT[lang][t];
    return text;
  }
  function replaceTextNodes(root, lang){
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null);
    const todo=[];
    while(walker.nextNode()) todo.push(walker.currentNode);
    todo.forEach(n=>{
      const raw=n.nodeValue;
      const trimmed=(raw||'').trim();
      if(!trimmed) return;
      const val=tr(trimmed, lang);
      if(val!==trimmed) n.nodeValue = raw.replace(trimmed, val);
      else {
        // partial replacements for mixed strings
        let out = raw;
        Object.entries(DICT[lang]||{}).forEach(([k,v])=>{ if(k && out.includes(k)) out = out.split(k).join(v); });
        n.nodeValue = out;
      }
    });
  }
  function replaceAttrs(lang){
    document.querySelectorAll('input,textarea,button,option,select').forEach(el=>{
      if(el.placeholder) el.placeholder = tr(el.placeholder, lang);
      if(el.title) el.title = tr(el.title, lang);
      if(el instanceof HTMLOptionElement) el.text = tr(el.text, lang);
      if(el.tagName==='BUTTON' || el.type==='submit'){ const t=(el.textContent||'').trim(); const v=tr(t,lang); if(v!==t) el.textContent=v; }
    });
  }
  function fixMetrics(lang){
    document.querySelectorAll('*').forEach(el=>{
      if(!el.children.length){
        el.innerHTML = el.innerHTML
          .replace(/mseed-tcp-serveractive/g, lang==='en'?'mseed-tcp-server active':'mseed-tcp-server 运行中')
          .replace(/mseed-web-portalactive/g, lang==='en'?'mseed-web-portal active':'mseed-web-portal 运行中')
          .replace(/nginxactive/g, lang==='en'?'nginx active':'nginx 运行中')
          .replace(/mseed-alert-worker\.timeractive/g, lang==='en'?'mseed-alert-worker.timer active':'mseed-alert-worker.timer 运行中');
      }
    });
  }
  function apply(){
    const lang = document.documentElement.getAttribute('lang-mode') || localStorage.getItem('portalLangMode') || currentLang();
    replaceTextNodes(document.body, lang);
    replaceAttrs(lang);
    fixMetrics(lang);
  }
  document.addEventListener('DOMContentLoaded', ()=>setTimeout(apply, 50));
  window.stage4I18N = { apply };
})();
