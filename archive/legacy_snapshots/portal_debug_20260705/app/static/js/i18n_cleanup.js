(function () {
  'use strict';

  const KEY = 'mseed.portal.lang';

  const zhToEn = {
    // nav and global
    '总览': 'Overview', '概览': 'Overview', '实时波形': 'Live waveform', '历史波形': 'Historical waveform',
    '数据质量': 'Data quality', '数据导出': 'Data export', '管理': 'Admin', '退出': 'Log out', '登录': 'Log in',
    '账号': 'Username', '用户名': 'Username', '密码': 'Password', '角色': 'Role', '显示名称': 'Display name',
    '保存': 'Save', '同步设备': 'Sync devices', '操作': 'Actions', '客户': 'Customer', '设备': 'Device',
    '分量': 'Channels', '通道': 'Channel', '开始时间': 'Start time', '结束时间': 'End time', '查询': 'Query',
    '下载': 'Download', '导出': 'Export', '在线': 'Online', '离线': 'Offline', '延迟': 'Delayed',
    '未分组': 'Unassigned', '缺口': 'Gaps', '重复包': 'Duplicates', '异常包': 'Bad packets',

    // admin page
    '账号、客户与设备权限': 'Accounts, customers and device access',
    '同步接收端数据库，创建客户账号，维护客户分组、设备别名和设备权限。': 'Sync receiver databases, create customer accounts, maintain customer groups, device aliases, and device access.',
    '创建 / 更新用户': 'Create / update user', '创建 / 更新客户分组': 'Create / update customer group',
    '客户名称': 'Customer name', '保存用户': 'Save user', '保存客户': 'Save customer',
    '设备别名与客户分组': 'Device aliases and customer groups', '设备别名': 'Device alias',
    '别名 / 站点': 'Alias / site', '客户可读别名': 'Customer-facing alias', '站点名称': 'Site name',
    '安装位置说明': 'Installation location note', '安装日期': 'Installation date', '经度': 'Longitude', '纬度': 'Latitude',
    '权限': 'Access', '用户权限': 'User access', '设备权限': 'Device access', '授权': 'Grant access', '取消授权': 'Revoke access',

    // quality/export/dashboard
    '查看设备断流、重复包、异常包和三分量完整性。': 'Review device gaps, duplicate packets, bad packets, and three-component completeness.',
    '最近质量事件': 'Recent quality events', '最新数据': 'Last data', '最后数据': 'Last data', '最后接收': 'Last received',
    '总包数': 'Total packets', '最新时间': 'Latest time', '数据完整性': 'Data completeness', '覆盖率': 'Coverage',
    '导出数据': 'Export data', '导出 miniSEED': 'Export miniSEED', '导出原始 miniSEED': 'Export raw miniSEED',
    '选择时间段': 'Select time range', '文件格式': 'File format'
  };

  const enToZh = {
    // nav and global
    'Overview': '总览', 'Live waveform': '实时波形', 'Historical waveform': '历史波形',
    'Data quality': '数据质量', 'Data export': '数据导出', 'Admin': '管理', 'Log out': '退出', 'Log in': '登录',
    'Username': '账号', 'Password': '密码', 'Role': '角色', 'Display name': '显示名称', 'Save': '保存',
    'Sync devices': '同步设备', 'Actions': '操作', 'Customer': '客户', 'Device': '设备', 'Channels': '分量',
    'Channel': '通道', 'Start time': '开始时间', 'End time': '结束时间', 'Query': '查询', 'Download': '下载',
    'Export': '导出', 'Online': '在线', 'Offline': '离线', 'offline': '离线', 'Delayed': '延迟', 'delayed': '延迟',
    'Unassigned': '未分组', 'Gaps': '缺口', 'Duplicates': '重复包', 'Duplicate packets': '重复包',
    'Bad packets': '异常包', 'Bad packet': '异常包',

    // admin page
    'Accounts, customers and device access': '账号、客户与设备权限',
    'Sync receiver databases, create customer accounts, maintain customer groups, device aliases, and access permissions.': '同步接收端数据库，创建客户账号，维护客户分组、设备别名和设备权限。',
    'Sync receiver databases, create customer accounts, maintain customer groups, device aliases, and device access.': '同步接收端数据库，创建客户账号，维护客户分组、设备别名和设备权限。',
    'Create / update user': '创建 / 更新用户', 'Create / update customer group': '创建 / 更新客户分组',
    'Customer name': '客户名称', 'Save user': '保存用户', 'Save customer': '保存客户',
    'Device aliases and customer groups': '设备别名与客户分组', 'Device alias': '设备别名',
    'Alias / site': '别名 / 站点', 'Customer-facing alias': '客户可读别名', 'Site name': '站点名称',
    'Installation location note': '安装位置说明', 'Installation date': '安装日期', 'Longitude': '经度', 'Latitude': '纬度',
    'Access': '权限', 'User access': '用户权限', 'Device access': '设备权限', 'Grant access': '授权', 'Revoke access': '取消授权',

    // quality/export/dashboard
    'Review device gaps, duplicate packets, bad packets, and three-component completeness.': '查看设备断流、重复包、异常包和三分量完整性。',
    'Recent quality events': '最近质量事件', 'Last data': '最新数据', 'Latest data': '最新数据', 'Last received': '最后接收',
    'Total packets': '总包数', 'Latest time': '最新时间', 'Data completeness': '数据完整性', 'Coverage': '覆盖率',
    'Export data': '导出数据', 'Export miniSEED': '导出 miniSEED', 'Export raw miniSEED': '导出原始 miniSEED',
    'Select time range': '选择时间段', 'File format': '文件格式'
  };

  const mixed = [
    [/^Overview\s+概览$|^概览\s+Overview$/, 'Overview', '总览'],
    [/^Live waveform\s+实时波形$|^实时波形\s+Live waveform$/, 'Live waveform', '实时波形'],
    [/^Historical waveform\s+历史波形$|^历史波形\s+Historical waveform$/, 'Historical waveform', '历史波形'],
    [/^Data quality\s+数据质量$|^数据质量\s+Data quality$/, 'Data quality', '数据质量'],
    [/^Data export\s+数据导出$|^数据导出\s+Data export$/, 'Data export', '数据导出'],
    [/^Admin\s+管理$|^管理\s+Admin$/, 'Admin', '管理']
  ];

  function currentLang() {
    const stored = localStorage.getItem(KEY);
    if (stored === 'zh' || stored === 'en') return stored;
    const html = document.documentElement.getAttribute('lang') || '';
    return html.toLowerCase().startsWith('zh') ? 'zh' : 'en';
  }

  function translate(raw, lang) {
    if (!raw) return raw;
    const leading = (raw.match(/^\s*/) || [''])[0];
    const trailing = (raw.match(/\s*$/) || [''])[0];
    let text = raw.trim().replace(/\s+/g, ' ');
    if (!text) return raw;

    for (const [re, en, zh] of mixed) {
      if (re.test(text)) return leading + (lang === 'zh' ? zh : en) + trailing;
    }

    const dict = lang === 'zh' ? enToZh : zhToEn;
    if (dict[text]) return leading + dict[text] + trailing;

    // Patch embedded status phrases like "BHZ offline" while preserving channel names.
    if (lang === 'zh') {
      text = text.replace(/\boffline\b/g, '离线')
                 .replace(/\bonline\b/g, '在线')
                 .replace(/\bdelayed\b/g, '延迟')
                 .replace(/\bDuplicates\b/g, '重复包')
                 .replace(/\bLast data\b/g, '最新数据')
                 .replace(/\bBad packets\b/g, '异常包');
      return leading + text + trailing;
    } else {
      text = text.replace(/离线/g, 'offline')
                 .replace(/在线/g, 'online')
                 .replace(/延迟/g, 'delayed')
                 .replace(/重复包/g, 'Duplicates')
                 .replace(/最新数据/g, 'Last data')
                 .replace(/异常包/g, 'Bad packets')
                 .replace(/未分组/g, 'Unassigned');
      return leading + text + trailing;
    }
  }

  function skip(el) {
    if (!el) return true;
    const tag = el.nodeName;
    if (['SCRIPT','STYLE','CODE','PRE','TEXTAREA','CANVAS','SVG'].includes(tag)) return true;
    if (el.closest && el.closest('[data-no-i18n]')) return true;
    if (el.classList && (el.classList.contains('js-plotly-plot') || el.classList.contains('plotly'))) return true;
    return false;
  }

  function translateTextNodes(root, lang) {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode(node) {
        if (!node.parentElement || skip(node.parentElement)) return NodeFilter.FILTER_REJECT;
        if (!node.nodeValue.trim()) return NodeFilter.FILTER_REJECT;
        return NodeFilter.FILTER_ACCEPT;
      }
    });
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    for (const node of nodes) {
      const next = translate(node.nodeValue, lang);
      if (next !== node.nodeValue) node.nodeValue = next;
    }
  }

  function translateAttrs(root, lang) {
    const attrs = ['placeholder','title','aria-label','value'];
    root.querySelectorAll('*').forEach(el => {
      if (skip(el)) return;
      attrs.forEach(attr => {
        if (!el.hasAttribute(attr)) return;
        if (attr === 'value') {
          const type = (el.getAttribute('type') || '').toLowerCase();
          if (!['button','submit','reset'].includes(type)) return;
        }
        const oldVal = el.getAttribute(attr);
        const newVal = translate(oldVal, lang);
        if (oldVal !== newVal) el.setAttribute(attr, newVal);
      });
    });
  }

  function cleanupUnassignedOptions(lang) {
    document.querySelectorAll('select').forEach(select => {
      let kept = null;
      Array.from(select.options).forEach(opt => {
        const norm = opt.textContent.trim().replace(/\s+/g, ' ');
        const isUnassigned = ['未分组','Unassigned'].includes(norm);
        if (!isUnassigned) return;
        if (!kept) {
          kept = opt;
          kept.textContent = lang === 'zh' ? '未分组' : 'Unassigned';
          return;
        }
        // Prefer keeping the built-in option value=0, otherwise keep the first one.
        if (kept.value !== '0' && opt.value === '0') {
          kept.remove();
          kept = opt;
          kept.textContent = lang === 'zh' ? '未分组' : 'Unassigned';
        } else {
          opt.remove();
        }
      });
    });
  }

  function setToggleLabel(lang) {
    const btn = document.getElementById('langToggle') || document.querySelector('[data-lang-toggle]');
    if (btn) {
      btn.setAttribute('data-no-i18n', '1');
      btn.textContent = lang === 'zh' ? 'English' : '中文';
    }
  }

  function apply() {
    const lang = currentLang();
    translateTextNodes(document.body, lang);
    translateAttrs(document.body, lang);
    cleanupUnassignedOptions(lang);
    setToggleLabel(lang);
  }

  function init() {
    apply();
    let timer = null;
    const mo = new MutationObserver(() => {
      clearTimeout(timer);
      timer = setTimeout(apply, 120);
    });
    mo.observe(document.body, {childList:true, subtree:true, characterData:true, attributes:true, attributeFilter:['placeholder','title','aria-label','value']});
    window.addEventListener('storage', apply);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
