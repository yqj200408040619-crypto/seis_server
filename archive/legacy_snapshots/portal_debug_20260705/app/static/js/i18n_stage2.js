(function(){
  const dict = {
    zh: {
      "nav.alerts":"告警", "nav.system":"系统",
      "Alerts":"告警", "System":"系统", "Open alerts":"当前告警", "Critical":"严重", "Warning":"警告", "Resolved":"已恢复",
      "Status":"状态", "Severity":"级别", "Device":"设备", "Component":"分量", "Type":"类型", "Message":"详情", "Last seen":"最后出现", "Action":"操作",
      "Acknowledge":"确认", "Disk used":"磁盘使用率", "Disk free":"磁盘剩余", "Receiver DB size":"接收数据库大小", "Recent backups":"最近备份"
    },
    en: {
      "告警":"Alerts", "系统":"System", "告警中心":"Alert center", "立即检查":"Check now", "确认":"Acknowledge",
      "系统状态":"System status", "暂无备份记录。":"No backup records yet.", "当前没有告警。":"No alerts."
    }
  };
  function lang(){ return localStorage.getItem('portal_lang') || 'zh'; }
  function apply(){
    const d = dict[lang()] || dict.zh;
    document.querySelectorAll('[data-i18n]').forEach(el => { const k = el.getAttribute('data-i18n'); if (d[k]) el.textContent = d[k]; });
    document.querySelectorAll('body *').forEach(el => {
      if (el.children.length || !el.textContent) return;
      const t = el.textContent.trim();
      if (d[t]) el.textContent = el.textContent.replace(t, d[t]);
    });
  }
  document.addEventListener('DOMContentLoaded', apply);
  window.addEventListener('storage', apply);
})();
