(function () {
  'use strict';

  const STORAGE_KEY = 'mseed.portal.lang';
  const DEFAULT_LANG = 'en';

  // Canonical UI strings. Keys are Chinese strings or older mixed strings that may appear in templates.
  const ZH_TO_EN = {
    // Global navigation
    '概览': 'Overview',
    '总览': 'Overview',
    '实时波形': 'Live waveform',
    '历史波形': 'Historical waveform',
    '历史查询': 'Historical waveform',
    '数据质量': 'Data quality',
    '数据导出': 'Data export',
    '管理': 'Admin',
    '退出': 'Log out',
    '登出': 'Log out',
    '登录': 'Log in',
    '账号': 'Username',
    '密码': 'Password',
    '中文': '中文',
    'English': 'English',

    // Login
    '客户数据访问平台': 'Customer data portal',
    '登录后查看授权地震仪的实时与历史波形。': 'Log in to view authorized instruments, live waveforms, and historical data.',
    '用户名': 'Username',
    '请输入用户名': 'Enter username',
    '请输入密码': 'Enter password',
    '登录失败': 'Login failed',
    '账号或密码错误': 'Invalid username or password',

    // Dashboard / overview
    '设备总览': 'Device overview',
    '授权设备': 'Authorized devices',
    '在线': 'Online',
    '离线': 'Offline',
    '延迟': 'Delayed',
    '未知': 'Unknown',
    '总包数': 'Total packets',
    '最新时间': 'Latest time',
    '最后接收': 'Last received',
    '最后接收时间': 'Last received',
    '最近1小时': 'Last 1 hour',
    '最近 1 小时': 'Last 1 hour',
    '最近1小时包数': 'Packets in last hour',
    '最近 1 小时包数': 'Packets in last hour',
    '分量状态': 'Channel status',
    '查看实时': 'Live waveform',
    '实时': 'Live',
    '查看历史': 'History',
    '无授权设备': 'No authorized devices',
    '暂无设备': 'No devices',

    // Live/history common
    '选择设备': 'Select device',
    '设备': 'Device',
    '分量': 'Channels',
    '通道': 'Channel',
    '时间窗口': 'Time window',
    '刷新间隔': 'Refresh interval',
    '刷新': 'Refresh',
    '自动刷新': 'Auto refresh',
    '跟随最新': 'Follow latest',
    '开始时间': 'Start time',
    '结束时间': 'End time',
    '查询': 'Query',
    '开始查询': 'Query',
    '跳到最近': 'Jump to latest',
    '前移一屏': 'Previous window',
    '后移一屏': 'Next window',
    '最近 5 分钟': 'Last 5 minutes',
    '最近 30 分钟': 'Last 30 minutes',
    '最近 1 小时': 'Last 1 hour',
    '最近 6 小时': 'Last 6 hours',
    '今天': 'Today',
    '昨天': 'Yesterday',
    '自定义时间段': 'Custom range',
    '加载中': 'Loading',
    '加载中...': 'Loading...',
    '无数据': 'No data',
    '暂无数据': 'No data',
    '请选择设备': 'Select a device',
    '请选择分量': 'Select at least one channel',
    '波形': 'Waveform',
    '幅值': 'Amplitude',
    '时间': 'Time',

    // Quality
    '数据质量总览': 'Data quality overview',
    '质量总览': 'Quality overview',
    '数据完整性': 'Data completeness',
    '缺口': 'Gaps',
    '时间缺口': 'Time gaps',
    '重复包': 'Duplicate packets',
    '异常包': 'Bad packets',
    '错误包': 'Bad packets',
    '质量事件': 'Quality events',
    '最近质量事件': 'Recent quality events',
    '事件类型': 'Event type',
    '事件时间': 'Event time',
    '详情': 'Details',
    '无质量事件': 'No quality events',
    '覆盖率': 'Coverage',
    '正常': 'Normal',
    '警告': 'Warning',
    '严重': 'Critical',

    // Export
    '导出数据': 'Export data',
    '导出 miniSEED': 'Export miniSEED',
    '导出原始 miniSEED': 'Export raw miniSEED',
    '下载': 'Download',
    '下载文件': 'Download file',
    '选择时间段': 'Select time range',
    '导出范围': 'Export range',
    '导出': 'Export',
    '文件格式': 'File format',

    // Admin page
    '账号、客户与设备权限': 'Accounts, customers and device access',
    '同步接收端数据库，创建客户账号，维护客户分组、设备别名和设备权限。': 'Sync receiver databases, create customer accounts, maintain customer groups, device aliases, and access permissions.',
    'Create / update user': 'Create / update user',
    '创建 / 更新用户': 'Create / update user',
    'Display name': 'Display name',
    '显示名称': 'Display name',
    'Password': 'Password',
    'Role': 'Role',
    '角色': 'Role',
    'Save user': 'Save user',
    '保存用户': 'Save user',
    '创建 / 更新客户分组': 'Create / update customer group',
    '客户名称': 'Customer name',
    '客户': 'Customer',
    '客户分组': 'Customer group',
    '保存客户': 'Save customer',
    '设备别名与客户分组': 'Device aliases and customer groups',
    '设备别名': 'Device alias',
    '别名 / 站点': 'Alias / site',
    '站点': 'Site',
    '站点名称': 'Site name',
    '安装位置': 'Installation location',
    '安装位置说明': 'Installation location note',
    '安装日期': 'Installation date',
    '经度': 'Longitude',
    '纬度': 'Latitude',
    '未分组': 'Unassigned',
    '未授权': 'Unauthorized',
    '已授权': 'Authorized',
    '授权': 'Grant access',
    '取消授权': 'Revoke access',
    '权限': 'Access',
    '用户': 'User',
    '用户权限': 'User access',
    '设备权限': 'Device access',
    '同步设备': 'Sync devices',
    '保存': 'Save',
    '操作': 'Actions',
    'Actions': 'Actions',
    'ID': 'ID',
    'Device': 'Device',
    'Active': 'Active',
    'Inactive': 'Inactive',

    // Placeholders / form help
    '客户可读别名': 'Customer-facing alias',
    '站点名称': 'Site name',
    'Lat': 'Lat',
    'Lon': 'Lon',
    '备注': 'Notes',
    '请输入客户名称': 'Enter customer name',
    '请输入设备别名': 'Enter device alias',
    '请输入站点名称': 'Enter site name',
    '输入 UTC 时间': 'Enter UTC time',

    // Mixed strings seen after older patches
    'Overview 概览': 'Overview',
    'Live waveform 实时波形': 'Live waveform',
    'Historical waveform 历史波形': 'Historical waveform',
    '数据质量 Data quality': 'Data quality',
    '数据导出 Data export': 'Data export',
    'Admin 管理': 'Admin',
    '账号、客户与设备权限 Accounts, customers and device access': 'Accounts, customers and device access'
  };

  const EN_TO_ZH = {
    'Overview': '概览',
    'Live waveform': '实时波形',
    'Historical waveform': '历史波形',
    'Data quality': '数据质量',
    'Data export': '数据导出',
    'Admin': '管理',
    'Log out': '退出',
    'Log in': '登录',
    'Customer data portal': '客户数据访问平台',
    'Log in to view authorized instruments, live waveforms, and historical data.': '登录后查看授权地震仪的实时与历史波形。',
    'Username': '用户名',
    'Password': '密码',
    'Device overview': '设备总览',
    'Authorized devices': '授权设备',
    'Online': '在线',
    'Offline': '离线',
    'Delayed': '延迟',
    'Unknown': '未知',
    'Total packets': '总包数',
    'Latest time': '最新时间',
    'Last received': '最后接收',
    'Last 1 hour': '最近 1 小时',
    'Packets in last hour': '最近 1 小时包数',
    'Channel status': '分量状态',
    'Live': '实时',
    'History': '历史查询',
    'No authorized devices': '无授权设备',
    'No devices': '暂无设备',
    'Select device': '选择设备',
    'Device': '设备',
    'Channels': '分量',
    'Channel': '通道',
    'Time window': '时间窗口',
    'Refresh interval': '刷新间隔',
    'Refresh': '刷新',
    'Auto refresh': '自动刷新',
    'Follow latest': '跟随最新',
    'Start time': '开始时间',
    'End time': '结束时间',
    'Query': '查询',
    'Jump to latest': '跳到最近',
    'Previous window': '前移一屏',
    'Next window': '后移一屏',
    'Last 5 minutes': '最近 5 分钟',
    'Last 30 minutes': '最近 30 分钟',
    'Last 1 hour': '最近 1 小时',
    'Last 6 hours': '最近 6 小时',
    'Today': '今天',
    'Yesterday': '昨天',
    'Custom range': '自定义时间段',
    'Loading': '加载中',
    'Loading...': '加载中...',
    'No data': '无数据',
    'Select a device': '请选择设备',
    'Select at least one channel': '请选择分量',
    'Waveform': '波形',
    'Amplitude': '幅值',
    'Time': '时间',
    'Data quality overview': '数据质量总览',
    'Quality overview': '质量总览',
    'Data completeness': '数据完整性',
    'Gaps': '缺口',
    'Time gaps': '时间缺口',
    'Duplicate packets': '重复包',
    'Bad packets': '异常包',
    'Quality events': '质量事件',
    'Recent quality events': '最近质量事件',
    'Event type': '事件类型',
    'Event time': '事件时间',
    'Details': '详情',
    'No quality events': '无质量事件',
    'Coverage': '覆盖率',
    'Normal': '正常',
    'Warning': '警告',
    'Critical': '严重',
    'Export data': '导出数据',
    'Export miniSEED': '导出 miniSEED',
    'Export raw miniSEED': '导出原始 miniSEED',
    'Download': '下载',
    'Download file': '下载文件',
    'Select time range': '选择时间段',
    'Export range': '导出范围',
    'Export': '导出',
    'File format': '文件格式',
    'Accounts, customers and device access': '账号、客户与设备权限',
    'Sync receiver databases, create customer accounts, maintain customer groups, device aliases, and access permissions.': '同步接收端数据库，创建客户账号，维护客户分组、设备别名和设备权限。',
    'Create / update user': '创建 / 更新用户',
    'Display name': '显示名称',
    'Role': '角色',
    'Save user': '保存用户',
    'Create / update customer group': '创建 / 更新客户分组',
    'Customer name': '客户名称',
    'Customer': '客户',
    'Customer group': '客户分组',
    'Save customer': '保存客户',
    'Device aliases and customer groups': '设备别名与客户分组',
    'Device alias': '设备别名',
    'Alias / site': '别名 / 站点',
    'Site': '站点',
    'Site name': '站点名称',
    'Installation location': '安装位置',
    'Installation location note': '安装位置说明',
    'Installation date': '安装日期',
    'Longitude': '经度',
    'Latitude': '纬度',
    'Unassigned': '未分组',
    'Unauthorized': '未授权',
    'Authorized': '已授权',
    'Grant access': '授权',
    'Revoke access': '取消授权',
    'Access': '权限',
    'User': '用户',
    'User access': '用户权限',
    'Device access': '设备权限',
    'Sync devices': '同步设备',
    'Save': '保存',
    'Actions': '操作',
    'Active': '启用',
    'Inactive': '停用',
    'Customer-facing alias': '客户可读别名',
    'Notes': '备注',
    'Enter customer name': '请输入客户名称',
    'Enter device alias': '请输入设备别名',
    'Enter site name': '请输入站点名称',
    'Enter UTC time': '输入 UTC 时间'
  };

  // Collapse old mixed bilingual labels into one canonical string first.
  const MIXED_NORMALIZE = {
    'Overview 概览': { en: 'Overview', zh: '概览' },
    '概览 Overview': { en: 'Overview', zh: '概览' },
    'Live waveform 实时波形': { en: 'Live waveform', zh: '实时波形' },
    '实时波形 Live waveform': { en: 'Live waveform', zh: '实时波形' },
    'Historical waveform 历史波形': { en: 'Historical waveform', zh: '历史波形' },
    '历史波形 Historical waveform': { en: 'Historical waveform', zh: '历史波形' },
    '数据质量 Data quality': { en: 'Data quality', zh: '数据质量' },
    'Data quality 数据质量': { en: 'Data quality', zh: '数据质量' },
    '数据导出 Data export': { en: 'Data export', zh: '数据导出' },
    'Data export 数据导出': { en: 'Data export', zh: '数据导出' },
    'Admin 管理': { en: 'Admin', zh: '管理' },
    '管理 Admin': { en: 'Admin', zh: '管理' }
  };

  function getLang() {
    return localStorage.getItem(STORAGE_KEY) || document.documentElement.getAttribute('lang') || DEFAULT_LANG;
  }

  function setLang(lang) {
    localStorage.setItem(STORAGE_KEY, lang);
    document.documentElement.setAttribute('lang', lang === 'zh' ? 'zh-CN' : 'en');
    applyTranslations(lang);
  }

  function translateText(raw, lang) {
    if (!raw) return raw;
    const leading = raw.match(/^\s*/)[0];
    const trailing = raw.match(/\s*$/)[0];
    const text = raw.trim().replace(/\s+/g, ' ');
    if (!text) return raw;

    if (MIXED_NORMALIZE[text]) return leading + MIXED_NORMALIZE[text][lang] + trailing;
    const dict = lang === 'zh' ? EN_TO_ZH : ZH_TO_EN;
    if (dict[text]) return leading + dict[text] + trailing;
    return raw;
  }

  function shouldSkip(el) {
    if (!el) return true;
    const tag = el.nodeName;
    if (['SCRIPT', 'STYLE', 'CODE', 'PRE', 'TEXTAREA', 'CANVAS', 'SVG'].includes(tag)) return true;
    if (el.closest && el.closest('[data-no-i18n]')) return true;
    if (el.classList && (el.classList.contains('plotly') || el.classList.contains('js-plotly-plot'))) return true;
    return false;
  }

  function walkText(root, lang) {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode(node) {
        if (!node.parentElement || shouldSkip(node.parentElement)) return NodeFilter.FILTER_REJECT;
        if (!node.nodeValue.trim()) return NodeFilter.FILTER_REJECT;
        return NodeFilter.FILTER_ACCEPT;
      }
    });
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    for (const node of nodes) {
      const next = translateText(node.nodeValue, lang);
      if (next !== node.nodeValue) node.nodeValue = next;
    }
  }

  function translateAttributes(root, lang) {
    const attrs = ['placeholder', 'title', 'aria-label', 'value'];
    root.querySelectorAll('*').forEach(el => {
      if (shouldSkip(el)) return;
      attrs.forEach(attr => {
        if (!el.hasAttribute(attr)) return;
        // Avoid changing submitted values of hidden fields, device keys, timestamps, etc.
        if (attr === 'value') {
          const type = (el.getAttribute('type') || '').toLowerCase();
          if (!['button', 'submit', 'reset'].includes(type)) return;
        }
        const oldVal = el.getAttribute(attr);
        const newVal = translateText(oldVal, lang);
        if (newVal !== oldVal) el.setAttribute(attr, newVal);
      });
    });
  }

  function ensureLanguageToggle(lang) {
    let btn = document.getElementById('langToggle') || document.querySelector('[data-lang-toggle]');
    if (!btn) {
      btn = document.createElement('button');
      btn.id = 'langToggle';
      btn.type = 'button';
      btn.className = 'lang-toggle';
      btn.setAttribute('data-no-i18n', '1');
      btn.setAttribute('data-lang-toggle', '1');
      const nav = document.querySelector('nav') || document.querySelector('header') || document.body;
      if (nav.firstChild) nav.insertBefore(btn, nav.firstChild.nextSibling);
      else nav.appendChild(btn);
    }
    btn.setAttribute('data-no-i18n', '1');
    btn.textContent = lang === 'zh' ? 'English' : '中文';
    btn.onclick = function () { setLang(getLang() === 'zh' ? 'en' : 'zh'); };
  }

  function applyTranslations(lang) {
    document.documentElement.setAttribute('lang', lang === 'zh' ? 'zh-CN' : 'en');
    walkText(document.body, lang);
    translateAttributes(document.body, lang);
    ensureLanguageToggle(lang);
    document.body.setAttribute('data-lang', lang);
  }

  function init() {
    const lang = getLang();
    applyTranslations(lang);

    // Re-apply after dynamic content is inserted by dashboard/admin/live/history scripts.
    let timer = null;
    const observer = new MutationObserver(() => {
      clearTimeout(timer);
      timer = setTimeout(() => applyTranslations(getLang()), 80);
    });
    observer.observe(document.body, { childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ['placeholder', 'title', 'aria-label', 'value'] });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
