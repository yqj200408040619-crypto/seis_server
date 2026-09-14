(function(){
  function isAdminRole(role){ return String(role||'').toLowerCase() === 'admin'; }
  function hideAdminLinks(role){
    if(isAdminRole(role)) return;
    const adminPathRe = /^\/(admin|system)(\/|$)/i;
    document.querySelectorAll('a,button').forEach(el=>{
      const href = el.getAttribute('href') || '';
      const text = (el.textContent || '').trim().toLowerCase();
      if(adminPathRe.test(href) || text === 'admin' || text === '管理' || text === 'system' || text === '系统'){
        el.style.display = 'none';
        el.setAttribute('aria-hidden','true');
      }
    });
    // Remove nav separators or empty wrappers if the theme has them.
    document.querySelectorAll('nav, .navbar, .topbar').forEach(nav=>{
      nav.querySelectorAll('li').forEach(li=>{
        const visible = Array.from(li.children).some(c=>getComputedStyle(c).display !== 'none');
        if(!visible && /admin|管理|system|系统/i.test(li.textContent||'')) li.style.display='none';
      });
    });
  }
  async function loadRole(){
    const bodyRole = document.body ? document.body.getAttribute('data-user-role') : '';
    if(bodyRole) return bodyRole;
    try{
      const r = await fetch('/api/me', {credentials:'same-origin'});
      if(r.ok){ const j = await r.json(); return j.role || ''; }
    }catch(e){}
    return '';
  }
  document.addEventListener('DOMContentLoaded', async ()=>{
    const role = await loadRole();
    hideAdminLinks(role);
    // Repeat once after dynamic i18n/nav scripts finish.
    setTimeout(()=>hideAdminLinks(role), 300);
    setTimeout(()=>hideAdminLinks(role), 1200);
  });
})();
