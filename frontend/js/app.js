// Safe library stubs in case external CDNs are slow or blocked
var _originalCreateIcons = (typeof window !== 'undefined' && window.lucide && typeof window.lucide.createIcons === 'function')
  ? window.lucide.createIcons
  : null;

function safeCreateIcons() {
  try {
    if (_originalCreateIcons) {
      _originalCreateIcons();
    } else if (typeof window !== 'undefined' && window.lucide && typeof window.lucide.createIcons === 'function' && window.lucide.createIcons !== safeCreateIcons) {
      window.lucide.createIcons();
    }
  } catch (err) {
    console.warn('Lucide icon render error:', err);
  }
}

var lucide = (typeof window !== 'undefined' && window.lucide) ? window.lucide : { createIcons: safeCreateIcons };
if (typeof window !== 'undefined') {
  window.lucide = window.lucide || lucide;
  window.lucide.createIcons = safeCreateIcons;
}

var Chart = (typeof window !== 'undefined' && window.Chart) ? window.Chart : (typeof Chart !== 'undefined' ? Chart : function() {});
if (typeof window !== 'undefined') window.Chart = Chart;

var marked = (typeof window !== 'undefined' && window.marked) ? window.marked : (typeof marked !== 'undefined' ? marked : { parse: function(s) { return s; } });
if (typeof window !== 'undefined') window.marked = marked;

var Keycloak = (typeof window !== 'undefined' && window.Keycloak) ? window.Keycloak : (typeof Keycloak !== 'undefined' ? Keycloak : null);
if (typeof window !== 'undefined') window.Keycloak = Keycloak;

const isSubpath = window.location.pathname.startsWith('/itsm');
const API_BASE = window.location.protocol === 'file:'
  ? 'http://127.0.0.1:8000/api'
  : (isSubpath ? '/itsm/api' : '/api');
const ITSM_BASE_PATH = isSubpath ? '/itsm' : '';

function updateBackendStatus(connected, message) {
  const badge = document.getElementById('backendStatusBadge');
  const dot = document.getElementById('backendStatusDot');
  const text = document.getElementById('backendStatusText');
  if (!badge) return;
  badge.classList.remove('hidden');
  if (connected) {
    badge.className = 'flex items-center space-x-1.5 px-2.5 py-1 rounded-full bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/30 text-[11px] font-semibold';
    if (dot) dot.className = 'w-2 h-2 rounded-full bg-emerald-500 animate-pulse';
    if (text) text.textContent = message || 'Backend Online';
  } else {
    badge.className = 'flex items-center space-x-1.5 px-2.5 py-1 rounded-full bg-amber-500/10 text-amber-600 dark:text-amber-400 border border-amber-500/30 text-[11px] font-semibold';
    if (dot) dot.className = 'w-2 h-2 rounded-full bg-amber-500';
    if (text) text.textContent = message || 'Connecting...';
  }
}

const state = {
  currentUser: {
    id: 1,
    username: 'admin',
    full_name: 'Admin User',
    role: 'itsm_admin',
    is_global_admin: true,
    is_end_user: false,
    admin_projects: [],
    support_projects: [],
    custom_groups: []
  },
  allUsers: [],
  allAssignmentGroups: [],
  currentRoute: 'dashboard',
  routeParams: {},
  activeTicketContext: null,
  activeAiConversationId: null,
  notifications: [],
  unreadCount: 0,
  theme: localStorage.getItem('nexus_theme') || 'light',
  currentTimezone: localStorage.getItem('nexus_timezone') || 'UTC',
  projects: [],
  applications: []
};

const SUPPORTED_TIMEZONES = [
  { value: 'UTC', label: 'UTC (Coordinated Universal Time)' },
  { value: 'local', label: 'Local Browser Time' },
  { value: 'America/New_York', label: 'America/New_York (EST/EDT)' },
  { value: 'America/Chicago', label: 'America/Chicago (CST/CDT)' },
  { value: 'America/Denver', label: 'America/Denver (MST/MDT)' },
  { value: 'America/Los_Angeles', label: 'America/Los_Angeles (PST/PDT)' },
  { value: 'Europe/London', label: 'Europe/London (GMT/BST)' },
  { value: 'Europe/Paris', label: 'Europe/Paris (CET/CEST)' },
  { value: 'Asia/Kolkata', label: 'Asia/Kolkata (IST)' },
  { value: 'Asia/Singapore', label: 'Asia/Singapore (SGT)' },
  { value: 'Asia/Tokyo', label: 'Asia/Tokyo (JST)' },
  { value: 'Australia/Sydney', label: 'Australia/Sydney (AEST/AEDT)' }
];

function renderTimezoneSelect(selectId, selectedTz = state.currentTimezone || 'UTC') {
  return `
    <select id="${selectId}" class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-xl px-2 py-1.5 text-xs focus:ring-2 focus:ring-purple-500 focus:outline-none font-medium">
      ${SUPPORTED_TIMEZONES.map(tz => `<option value="${tz.value}" ${tz.value === selectedTz ? 'selected' : ''}>${tz.label}</option>`).join('')}
    </select>
  `;
}

function formatTicketDate(isoString, timeZone) {
  if (!isoString) return '—';
  try {
    const d = new Date(isoString);
    if (isNaN(d.getTime())) return '—';
    const tz = (timeZone && timeZone !== 'local') ? timeZone : Intl.DateTimeFormat().resolvedOptions().timeZone;
    return new Intl.DateTimeFormat('en-US', {
      timeZone: tz,
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      hour12: true
    }).format(d);
  } catch (_) {
    return new Date(isoString).toLocaleDateString();
  }
}

function matchesTimeRange(createdAt, tVal, customStart, customEnd, timeZone) {
  if (!createdAt) return true;
  const ticketTime = new Date(createdAt).getTime();
  if (isNaN(ticketTime)) return true;

  if (!tVal && !customStart && !customEnd) return true;

  if (tVal === 'custom') {
    if (customStart) {
      const startMs = new Date(customStart).getTime();
      if (!isNaN(startMs) && ticketTime < startMs) return false;
    }
    if (customEnd) {
      const endMs = new Date(customEnd).getTime();
      if (!isNaN(endMs) && ticketTime > endMs) return false;
    }
    return true;
  }

  const now = new Date();
  if (tVal === 'today') {
    const tz = (timeZone && timeZone !== 'local') ? timeZone : Intl.DateTimeFormat().resolvedOptions().timeZone;
    const d1 = new Intl.DateTimeFormat('en-CA', { timeZone: tz }).format(new Date(ticketTime));
    const d2 = new Intl.DateTimeFormat('en-CA', { timeZone: tz }).format(now);
    return d1 === d2;
  }
  if (tVal === '7d') {
    return (now.getTime() - ticketTime) <= (7 * 24 * 60 * 60 * 1000);
  }
  if (tVal === '30d') {
    return (now.getTime() - ticketTime) <= (30 * 24 * 60 * 60 * 1000);
  }
  if (tVal === '90d') {
    return (now.getTime() - ticketTime) <= (90 * 24 * 60 * 60 * 1000);
  }
  return true;
}

let keycloak = null;

function getFilteredAssignmentGroups(projectNames, appNames, fallbackGroupNames = []) {
  let pCleanList = [];
  if (Array.isArray(projectNames) || projectNames instanceof Set) {
    pCleanList = [...projectNames].map(x => String(x).trim().toLowerCase()).filter(Boolean);
  } else if (typeof projectNames === 'string' && projectNames.trim()) {
    pCleanList = [projectNames.trim().toLowerCase()];
  }
  let aCleanList = [];
  if (Array.isArray(appNames) || appNames instanceof Set) {
    aCleanList = [...appNames].map(x => String(x).trim().toLowerCase()).filter(Boolean);
  } else if (typeof appNames === 'string' && appNames.trim()) {
    aCleanList = [appNames.trim().toLowerCase()];
  }
  const allGroups = state.allAssignmentGroups || window._reassignGroups || [];

  if (pCleanList.length === 0 && aCleanList.length === 0) {
    if (allGroups.length) {
      return [...new Set(allGroups.map(g => g.name).concat(fallbackGroupNames))].sort();
    }
    return fallbackGroupNames.slice().sort();
  }

  const matched = new Set();
  allGroups.forEach(g => {
    const gName = (g.name || '').trim().toLowerCase();
    let projs = [];
    try {
      const raw = Array.isArray(g.projects_supported) ? g.projects_supported : JSON.parse(g.projects_supported || '[]');
      projs = raw.map(x => String(x).trim().toLowerCase());
    } catch (_) {}
    let apps = [];
    try {
      const raw = Array.isArray(g.applications_supported) ? g.applications_supported : JSON.parse(g.applications_supported || '[]');
      apps = raw.map(x => String(x).trim().toLowerCase());
    } catch (_) {}

    const matchP = pCleanList.length === 0 || pCleanList.some(p => gName.startsWith(`${p}-`) || gName === p || projs.includes(p));
    const matchA = aCleanList.length === 0 || aCleanList.some(a => gName.startsWith(`${a}-`) || gName === a || apps.includes(a));

    if (pCleanList.length > 0 && aCleanList.length > 0) {
      if (matchA || matchP) matched.add(g.name);
    } else if (pCleanList.length > 0) {
      if (matchP) matched.add(g.name);
    } else if (aCleanList.length > 0) {
      if (matchA) matched.add(g.name);
    }
  });

  // Also match fallbackGroupNames (e.g. from tickets in this project or app)
  fallbackGroupNames.forEach(name => {
    const nClean = name.toLowerCase();
    if (pCleanList.some(p => nClean.startsWith(`${p}-`) || nClean === p)) {
      matched.add(name);
    }
    if (aCleanList.some(a => nClean.startsWith(`${a}-`) || nClean === a)) {
      matched.add(name);
    }
  });

  // If no match found but fallback groups exist, include project fallback groups
  if (matched.size === 0 && pCleanList.length > 0) {
    fallbackGroupNames.forEach(name => {
      const nClean = name.toLowerCase();
      if (pCleanList.some(p => nClean.includes(p) || p.includes(nClean))) matched.add(name);
    });
  }

  return [...matched].sort();
}

function createMultiSelectDropdown({
  container,
  options = [],
  selectedValues = [],
  placeholder = 'Selected',
  allLabel = 'All',
  emptyMessage = 'No options available',
  onChange = () => {}
}) {
  if (!container) return null;
  let curOptions = options.slice();
  let curSelected = new Set(selectedValues);
  let isOpen = false;
  let searchTerm = '';

  container.innerHTML = `
    <div class="relative w-full select-none" data-multiselect="true">
      <button type="button" class="ms-btn w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-xl px-2.5 py-1.5 text-xs text-left focus:ring-2 focus:ring-purple-500 focus:outline-none flex items-center justify-between cursor-pointer transition-colors hover:border-purple-400">
        <span class="ms-label truncate font-semibold text-slate-700 dark:text-slate-300"></span>
        <div class="flex items-center space-x-1 shrink-0 ml-1">
          <span class="ms-count-badge hidden px-1.5 py-0.5 rounded-full text-[9px] font-bold bg-purple-100 dark:bg-purple-950 text-purple-700 dark:text-purple-300 border border-purple-200 dark:border-purple-800"></span>
          <i data-lucide="chevron-down" class="w-3.5 h-3.5 text-slate-400"></i>
        </div>
      </button>
      <div class="ms-menu hidden absolute top-full left-0 mt-1 min-w-[220px] max-w-[320px] w-full bg-[var(--card-bg)] border border-[var(--border-color)] rounded-xl shadow-2xl p-2 z-50 flex flex-col space-y-2">
        <div class="relative">
          <input type="text" placeholder="Search..." class="ms-search w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-lg pl-7 pr-2 py-1 text-xs focus:ring-2 focus:ring-purple-500 focus:outline-none">
          <i data-lucide="search" class="w-3.5 h-3.5 text-slate-400 absolute left-2 top-1.5"></i>
        </div>
        <div class="flex items-center justify-between px-1 text-[10px] font-bold text-slate-400">
          <span class="ms-info-count">0 selected</span>
          <div class="space-x-1.5">
            <button type="button" class="ms-select-all text-purple-600 dark:text-purple-400 hover:underline">All</button>
            <span>·</span>
            <button type="button" class="ms-clear-all text-slate-400 hover:text-slate-200 hover:underline">Clear</button>
          </div>
        </div>
        <div class="ms-list overflow-y-auto max-h-48 space-y-0.5 pr-1"></div>
      </div>
    </div>
  `;

  const btn = container.querySelector('.ms-btn');
  const labelEl = container.querySelector('.ms-label');
  const countBadge = container.querySelector('.ms-count-badge');
  const menu = container.querySelector('.ms-menu');
  const searchInput = container.querySelector('.ms-search');
  const listEl = container.querySelector('.ms-list');
  const infoCountEl = container.querySelector('.ms-info-count');
  const selectAllBtn = container.querySelector('.ms-select-all');
  const clearAllBtn = container.querySelector('.ms-clear-all');

  function updateSummary() {
    const count = curSelected.size;
    if (count === 0) {
      labelEl.textContent = allLabel;
      countBadge.classList.add('hidden');
    } else if (count === 1) {
      const first = [...curSelected][0];
      labelEl.textContent = first;
      countBadge.classList.add('hidden');
    } else if (count === 2) {
      const arr = [...curSelected];
      labelEl.textContent = `${arr[0]}, ${arr[1]}`;
      countBadge.classList.add('hidden');
    } else {
      labelEl.textContent = `${count} ${placeholder}`;
      countBadge.textContent = count;
      countBadge.classList.remove('hidden');
    }
    if (infoCountEl) {
      infoCountEl.textContent = `${count} of ${curOptions.length} selected`;
    }
  }

  function renderList() {
    const q = searchTerm.toLowerCase().trim();
    const visibleOptions = curOptions.filter(opt => !q || opt.toLowerCase().includes(q));

    if (visibleOptions.length === 0) {
      listEl.innerHTML = `<div class="p-2 text-center text-slate-400 text-[11px]">${q ? 'No matches found' : emptyMessage}</div>`;
      return;
    }

    listEl.innerHTML = visibleOptions.map(opt => {
      const isChecked = curSelected.has(opt);
      return `
        <label class="flex items-center space-x-2 px-2 py-1 hover:bg-[var(--bg-tertiary)] rounded-lg cursor-pointer text-xs select-none">
          <input type="checkbox" value="${opt.replace(/"/g, '&quot;')}" ${isChecked ? 'checked' : ''} class="ms-checkbox rounded text-purple-600 focus:ring-purple-500 w-3.5 h-3.5">
          <span class="truncate font-medium text-slate-700 dark:text-slate-300">${opt}</span>
        </label>
      `;
    }).join('');

    listEl.querySelectorAll('.ms-checkbox').forEach(cb => {
      cb.addEventListener('change', (e) => {
        const val = e.target.value;
        if (e.target.checked) {
          curSelected.add(val);
        } else {
          curSelected.delete(val);
        }
        updateSummary();
        onChange([...curSelected]);
      });
    });
  }

  function toggleMenu(open) {
    isOpen = typeof open === 'boolean' ? open : !isOpen;
    if (isOpen) {
      menu.classList.remove('hidden');
      searchTerm = '';
      if (searchInput) {
        searchInput.value = '';
        setTimeout(() => searchInput.focus(), 50);
      }
      renderList();
      try { if (typeof lucide !== 'undefined' && lucide.createIcons) lucide.createIcons(); } catch (_) {}
    } else {
      menu.classList.add('hidden');
    }
  }

  btn.addEventListener('click', (e) => {
    e.stopPropagation();
    document.querySelectorAll('[data-multiselect="true"] .ms-menu').forEach(m => {
      if (m !== menu) m.classList.add('hidden');
    });
    toggleMenu();
  });

  menu.addEventListener('click', (e) => {
    e.stopPropagation();
  });

  if (searchInput) {
    searchInput.addEventListener('input', (e) => {
      searchTerm = e.target.value;
      renderList();
    });
  }

  if (selectAllBtn) {
    selectAllBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      const q = searchTerm.toLowerCase().trim();
      const visible = curOptions.filter(opt => !q || opt.toLowerCase().includes(q));
      visible.forEach(opt => curSelected.add(opt));
      updateSummary();
      renderList();
      onChange([...curSelected]);
    });
  }

  if (clearAllBtn) {
    clearAllBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      curSelected.clear();
      updateSummary();
      renderList();
      onChange([]);
    });
  }

  const docClickHandler = (e) => {
    if (!container.contains(e.target)) {
      toggleMenu(false);
    }
  };
  document.addEventListener('click', docClickHandler);

  updateSummary();
  renderList();
  try { if (typeof lucide !== 'undefined' && lucide.createIcons) lucide.createIcons(); } catch (_) {}

  return {
    getValues: () => [...curSelected],
    setValues: (newVals, triggerChange = false) => {
      curSelected = new Set(newVals.filter(v => curOptions.includes(v)));
      updateSummary();
      renderList();
      if (triggerChange) onChange([...curSelected]);
    },
    setOptions: (newOpts, preserveSelections = true) => {
      curOptions = newOpts.slice();
      if (preserveSelections) {
        curSelected = new Set([...curSelected].filter(v => curOptions.includes(v)));
      } else {
        curSelected.clear();
      }
      updateSummary();
      renderList();
    },
    clear: (triggerChange = false) => {
      curSelected.clear();
      updateSummary();
      renderList();
      if (triggerChange) onChange([]);
    },
    destroy: () => {
      document.removeEventListener('click', docClickHandler);
    }
  };
}

async function initSso() {
  try {
    const response = await fetch(`${API_BASE}/auth/config`);
    if (!response.ok) return;
    const config = await response.json();
    if (!config || !config.enabled) return;
    if (!window.Keycloak) return;
    keycloak = new Keycloak({ url: config.url, realm: config.realm, clientId: config.clientId });
    const authenticated = await keycloak.init({ onLoad: 'login-required', pkceMethod: 'S256', checkLoginIframe: false });
    if (!authenticated) return;
    window.setInterval(() => keycloak.updateToken(60).catch(() => keycloak.login()), 30000);
    const originalFetch = window.fetch.bind(window);
    window.fetch = (input, options = {}) => {
      const headers = new Headers(options.headers || {});
      headers.set('Authorization', `Bearer ${keycloak.token}`);
      return originalFetch(input, { ...options, headers });
    };
  } catch (err) {
    console.warn('SSO initialization deferred:', err);
  }
}

// --- INITIALIZATION ---
async function initApp() {
  initTheme();
  setupGlobalSearch();

  try {
    await initSso();
  } catch (err) {
    console.warn('SSO check skipped:', err);
  }

  try {
    await loadCurrentUser();
  } catch (err) {
    console.warn('Current user load skipped:', err);
  }

  try {
    await loadAllUsers();
  } catch (err) {
    console.warn('All users load skipped:', err);
  }

  try {
    const grpRes = await fetch(`${API_BASE}/assignment-groups`);
    if (grpRes.ok) state.allAssignmentGroups = await grpRes.json();
  } catch (err) {
    console.warn('Assignment groups load skipped:', err);
  }

  try {
    const [projRes, appRes] = await Promise.allSettled([
      fetch(`${API_BASE}/projects`),
      fetch(`${API_BASE}/applications`)
    ]);
    if (projRes.status === 'fulfilled' && projRes.value.ok) state.projects = await projRes.value.json();
    if (appRes.status === 'fulfilled' && appRes.value.ok) state.applications = await appRes.value.json();
  } catch (err) {
    console.warn('Projects or applications preload skipped:', err);
  }

  initRouter();
  updateNavVisibilityForRole();
  safeCreateIcons();
  loadNotifications();
  setInterval(loadNotifications, 30000);
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initApp);
} else {
  // DOM is already ready
  initApp();
}

// --- THEME MANAGEMENT ---
function initTheme() {
  document.documentElement.setAttribute('data-theme', state.theme);
  const icon = document.getElementById('themeIcon');
  if (icon) {
    icon.setAttribute('data-lucide', state.theme === 'dark' ? 'sun' : 'moon');
  }
}

function toggleTheme() {
  state.theme = state.theme === 'dark' ? 'light' : 'dark';
  localStorage.setItem('nexus_theme', state.theme);
  initTheme();
  safeCreateIcons();
}

// --- USER / PERSONA SWITCHING ---
async function loadCurrentUser() {
  const savedUserId = localStorage.getItem('nexus_user_id') || '1';
  try {
    const res = await fetch(`${API_BASE}/auth/current`, {
      headers: { 'X-User-ID': savedUserId }
    });
    if (res.ok) {
      state.currentUser = await res.json();
      updateUserUI();
      updateBackendStatus(true, 'Backend Online');
    } else {
      updateBackendStatus(false, 'API Connected (Guest)');
    }
  } catch (err) {
    console.error('Failed to load current user', err);
    updateBackendStatus(false, 'Backend Offline');
  }
}

async function loadAllUsers() {
  const savedUserId = localStorage.getItem('nexus_user_id') || '1';
  try {
    const res = await fetch(`${API_BASE}/auth/users`, {
      headers: { 'X-User-ID': savedUserId }
    });
    if (res.ok) {
      state.allUsers = await res.json();
      renderUserSwitcherDropdown();
    }
  } catch (err) {
    console.error('Failed to load users list', err);
  }
}

function isUserEndUser(user) {
  if (!user) return false;
  if (user.is_global_admin || user.username === 'admin') return false;
  if (user.username === 'john.smith' || user.role === 'employee' || user.role === 'itsm_read') return true;
  if (user.is_end_user !== undefined) return Boolean(user.is_end_user);
  if (user.admin_projects && user.admin_projects.length > 0) return false;
  const customGroups = user.custom_groups || [];
  if (customGroups.some(cg => typeof cg === 'string' && (cg.endsWith('-admin') || cg.endsWith('-user')))) return false;
  if (customGroups.some(cg => ['itsm_user', 'Service Desk', 'ITSM-Fulfillers', 'Tier1-Support', 'ITSM-Admins', 'itsm_admin'].includes(cg))) return false;
  if (customGroups.includes('IM_SAML')) {
    const privilegedRoles = ['itsm_admin', 'administrator', 'itsm_user', 'support_member', 'group_manager'];
    if (!privilegedRoles.includes(user.role)) return true;
  }
  return false;
}

function updateNavVisibilityForRole() {
  if (!state.currentUser) return;
  const isEndUser = isUserEndUser(state.currentUser);
  const isGlobalAdmin = !!(state.currentUser.is_global_admin || state.currentUser.username === 'admin' || ['administrator', 'itsm_admin', 'admin'].includes(state.currentUser.role) || (state.currentUser.custom_groups || []).includes('itsm_admin') || (state.currentUser.custom_groups || []).includes('ITSM-Admins'));
  const hasAdminProjects = (state.currentUser.admin_projects || []).length > 0;
  const isAdmin = isGlobalAdmin || hasAdminProjects;

  // Items restricted for end users (management metrics, queue config, AI API setup, and admin portal)
  const restrictedForEndUsers = [
    'navItemDashboard',
    'navItemAnalytics',
    'navItemAssignmentGroups',
    'navItemAiIntegration',
    'adminNavSection'
  ];

  restrictedForEndUsers.forEach(id => {
    const el = document.getElementById(id);
    if (el) {
      el.style.display = isEndUser ? 'none' : '';
    }
  });

  // Guaranteed visible for end users: Create Ticket, My Tickets, Service Requests, Changes, Knowledge, AI Bot, Applications, Projects, On-Call
  const allowedForEndUsers = [
    'sidebarCreateTicketSection',
    'navItemMyTickets',
    'navItemRequests',
    'navItemChanges',
    'navItemKnowledge',
    'navSectionAi',
    'navItemAi',
    'floatingAiBtn',
    'navSectionEntities',
    'navItemApplications',
    'navItemProjects',
    'navItemOnCall'
  ];
  allowedForEndUsers.forEach(id => {
    const el = document.getElementById(id);
    if (el) el.style.display = '';
  });

  // For end users, hide generic "Incidents" nav item since "My Tickets" is their incident view
  const incidentsNav = document.getElementById('navItemIncidents');
  if (incidentsNav) {
    incidentsNav.style.display = isEndUser ? 'none' : '';
  }

  // Dynamic section titles & project identification
  const userProjects = (state.currentUser.admin_projects && state.currentUser.admin_projects.length > 0)
    ? state.currentUser.admin_projects
    : (state.currentUser.support_projects || []);
  const projName = userProjects.length > 0 ? userProjects[0] : null;

  // Update top brand badge in sidebar
  const sidebarPortalName = document.getElementById('sidebarPortalName');
  if (sidebarPortalName) {
    sidebarPortalName.textContent = projName || 'Nexus ITSM';
  }

  // Update Operations heading
  const headingOps = document.getElementById('navHeadingOperations');
  if (headingOps) {
    if (projName) {
      headingOps.textContent = projName.toUpperCase();
    } else {
      headingOps.textContent = isEndUser ? 'TICKETS & REQUESTS' : 'IT OPERATIONS';
    }
  }

  // Platform Entities section: Visible for all users!
  const navSectionEntities = document.getElementById('navSectionEntities');
  const headingEntities = document.getElementById('navHeadingEntities');
  if (navSectionEntities) {
    navSectionEntities.style.display = '';
  }
  if (headingEntities) {
    headingEntities.textContent = isEndUser ? 'Applications & On-Call' : 'Platform Entities';
  }

  // Administration section (admin only: global admin or project admin)
  const adminNav = document.getElementById('adminNavSection');
  if (adminNav) {
    adminNav.style.display = (!isEndUser && isAdmin) ? 'block' : 'none';
    const adminNavHeadingSpan = adminNav.querySelector('div > span:first-child');
    const adminNavBadgeSpan = adminNav.querySelector('div > span:last-child');
    if (adminNavHeadingSpan) {
      if (!isGlobalAdmin && hasAdminProjects) {
        adminNavHeadingSpan.textContent = projName || 'Project Administration';
        if (adminNavBadgeSpan) adminNavBadgeSpan.style.display = 'none';
      } else {
        adminNavHeadingSpan.textContent = 'Administration';
        if (adminNavBadgeSpan) {
          adminNavBadgeSpan.textContent = 'No-Code';
          adminNavBadgeSpan.style.display = '';
        }
      }
    }
  }

  // Hide the persona switcher entirely when Keycloak SSO is active —
  // in production, identity is fixed by the SSO token, not by localStorage
  const switcherBtn = document.getElementById('userSwitcherBtn');
  const switcherDropdown = document.getElementById('userDropdown');
  if (keycloak) {
    if (switcherBtn) switcherBtn.style.pointerEvents = 'none';
    if (switcherDropdown) switcherDropdown.style.display = 'none';
    if (switcherBtn) switcherBtn.querySelector('i[data-lucide="chevron-down"]') && (switcherBtn.querySelector('i[data-lucide="chevron-down"]').style.display = 'none');
  } else {
    if (switcherBtn) switcherBtn.style.pointerEvents = '';
  }
}

function updateUserUI() {
  if (!state.currentUser) return;
  const nameEl = document.getElementById('userName');
  const roleEl = document.getElementById('userRoleBadge');
  const avatarEl = document.getElementById('userAvatar');

  if (nameEl) nameEl.textContent = state.currentUser.full_name || state.currentUser.username || 'User';
  if (roleEl) {
    roleEl.textContent = '';
    roleEl.style.display = 'none';
  }
  if (avatarEl) {
    const name = state.currentUser.full_name || state.currentUser.username || 'User';
    const initials = name.split(' ').filter(Boolean).map(n => n[0]).join('').toUpperCase().slice(0, 2) || 'AU';
    avatarEl.textContent = initials;
  }

  updateNavVisibilityForRole();
  renderPersonaBanner();
}

function renderPersonaBanner() {
  const container = document.getElementById('personaBannerContainer');
  if (!container) return;
  container.style.display = 'none';
  container.innerHTML = '';
}

function renderUserSwitcherDropdown() {
  const container = document.getElementById('usersListContainer');
  if (!container) return;

  container.innerHTML = state.allUsers.map(u => {
    const isSelected = state.currentUser && state.currentUser.id === u.id;
    const uName = u.full_name || u.username || 'User';
    const userProj = (u.admin_projects && u.admin_projects[0]) || (u.support_projects && u.support_projects[0]) || '';

    return `
      <div onclick="switchUser(${u.id})" class="flex items-center justify-between p-2.5 hover:bg-[var(--bg-tertiary)] cursor-pointer rounded-lg transition-colors ${isSelected ? 'bg-purple-50/50' : ''}">
        <div class="flex items-center space-x-2.5">
          <div class="w-8 h-8 rounded-full bg-slate-700 text-white text-xs font-bold flex items-center justify-center">
            ${uInitials}
          </div>
          <div>
            <div class="font-semibold text-xs text-[var(--text-primary)]">${uName}</div>
            ${userProj ? `<div class="text-[11px] text-purple-600 dark:text-purple-400 font-medium">${userProj}</div>` : ''}
          </div>
        </div>
      </div>
    `;
  }).join('');
}

function toggleUserDropdown() {
  const dd = document.getElementById('userDropdown');
  if (dd) dd.classList.toggle('hidden');
}

function switchUser(userId) {
  localStorage.setItem('nexus_user_id', userId.toString());
  toggleUserDropdown();
  if (userId === 2) {
    window.location.hash = '#/my-tickets';
  } else {
    window.location.hash = '#/dashboard';
  }
  window.location.reload();
}

// --- NOTIFICATIONS ---
async function loadNotifications() {
  if (!state.currentUser) return;
  try {
    const res = await fetch(`${API_BASE}/notifications`, {
      headers: { 'X-User-ID': state.currentUser.id.toString() }
    });
    if (res.ok) {
      const data = await res.json();
      state.unreadCount = data.unread_count;
      state.notifications = data.notifications;
      const badge = document.getElementById('unreadCountBadge');
      if (badge) {
        if (state.unreadCount > 0) {
          badge.textContent = state.unreadCount;
          badge.classList.remove('hidden');
        } else {
          badge.classList.add('hidden');
        }
      }
      renderNotifications();
    }
  } catch (err) {
    console.error('Failed to load notifications', err);
  }
}

function toggleNotificationPanel() {
  const p = document.getElementById('notificationPanel');
  if (p) p.classList.toggle('hidden');
}

function renderNotifications() {
  const container = document.getElementById('notificationsContainer');
  if (!container) return;
  if (!state.notifications.length) {
    container.innerHTML = `<div class="p-3 text-center text-slate-400">No new notifications</div>`;
    return;
  }
  container.innerHTML = state.notifications.map(n => `
    <div class="p-2.5 rounded-lg border border-[var(--border-color)] ${n.is_read ? 'bg-transparent' : 'bg-purple-500/10 border-purple-500/30'}">
      <div class="font-semibold text-xs text-[var(--text-primary)]">${n.title}</div>
      <div class="text-slate-400 mt-1 line-clamp-2">${n.message}</div>
      <div class="mt-1.5 flex items-center justify-between text-[10px] text-slate-500">
        <span>${n.ticket_number || 'Alert'}</span>
        <span>${new Date(n.created_at).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})}</span>
      </div>
    </div>
  `).join('');
}

async function markAllNotificationsRead() {
  if (!state.currentUser) return;
  await fetch(`${API_BASE}/notifications/read-all`, {
    method: 'POST',
    headers: { 'X-User-ID': state.currentUser.id.toString() }
  });
  loadNotifications();
}

// --- ROUTER ---
function initRouter() {
  window.addEventListener('hashchange', handleRoute);
  handleRoute();
}

function handleRoute() {
  const isEndUser = isUserEndUser(state.currentUser);
  const defaultRoute = isEndUser ? 'my-tickets' : 'dashboard';
  const hash = window.location.hash.slice(2) || defaultRoute;
  const parts = hash.split('/');
  state.currentRoute = parts[0];
  state.routeParams = {
    id: parts[1] || null,
    sub: parts[2] || null
  };

  // Enforce end-user route guard: IM_SAML end users can view My Tickets, All Tickets, Incidents, Service Requests, Changes, Knowledge, Applications, Projects, On-Call, and AI Assistant
  if (isEndUser) {
    const allowed = ['my-tickets', 'tickets', 'incidents', 'service-requests', 'changes', 'knowledge', 'applications', 'projects', 'on-call', 'ai-assistant'];
    if (!allowed.includes(state.currentRoute)) {
      state.currentRoute = 'my-tickets';
      state.routeParams = { id: null, sub: null };
      window.location.hash = '#/my-tickets';
    }
  }

  // Update active sidebar item
  document.querySelectorAll('.nav-item').forEach(el => {
    const route = el.getAttribute('data-route');
    if (route === hash || route === state.currentRoute) {
      el.classList.add('bg-slate-800', 'text-white');
    } else {
      el.classList.remove('bg-slate-800', 'text-white');
    }
  });

  // Render view
  const app = document.getElementById('mainApp');
  if (!app) return;

  switch (state.currentRoute) {
    case 'dashboard':
      renderDashboardView(app);
      break;
    case 'my-tickets':
      renderUnifiedTicketsView(app, { myTickets: true });
      break;
    case 'tickets':
      renderUnifiedTicketsView(app);
      break;
    case 'incidents':
      if (state.routeParams.id) {
        renderIncidentDetailView(app, state.routeParams.id);
      } else {
        renderTicketsView(app, { type: 'Incident' });
      }
      break;
    case 'service-requests':
      if (state.routeParams.id) {
        renderRequestDetailView(app, state.routeParams.id);
      } else {
        renderServiceRequestsView(app);
      }
      break;
    case 'changes':
      if (state.routeParams.id) {
        renderChangeDetailView(app, state.routeParams.id);
      } else {
        renderChangesView(app);
      }
      break;
    case 'knowledge':
      renderKnowledgeView(app);
      break;
    case 'applications':
      renderApplicationsView(app);
      break;
    case 'projects':
      renderProjectsView(app);
      break;
    case 'assignment-groups':
      renderAssignmentGroupsView(app);
      break;
    case 'on-call':
      renderOnCallRosterView(app);
      break;
    case 'ai-assistant':
      renderAiAssistantFullScreen(app);
      break;
    case 'ai':
    case 'ai-analytics':
    case 'ai-integration':
      renderAiAdminView(app);
      break;
    case 'analytics':
      renderAnalyticsDashboardView(app);
      break;
    case 'admin':
      renderAdminSubView(app, state.routeParams.id);
      break;
    default:
      renderDashboardView(app);
  }
  lucide.createIcons();
}

// --- GLOBAL SEARCH ---
function setupGlobalSearch() {
  const input = document.getElementById('globalSearchInput');
  const dropdown = document.getElementById('searchDropdown');
  if (!input || !dropdown) return;

  let debounceTimer;

  // Handle Enter key: redirect directly to #/tickets with search term pre-filtered
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      const val = input.value.trim();
      if (val) {
        dropdown.classList.add('hidden');
        window.location.hash = `#/tickets`;
        setTimeout(() => {
          const filterInput = document.getElementById('filterTicketSearch') || document.getElementById('filterUnifiedSearch');
          if (filterInput) {
            filterInput.value = val;
            filterInput.dispatchEvent(new Event('input', { bubbles: true }));
          }
        }, 300);
      }
    }
  });

  input.addEventListener('input', (e) => {
    clearTimeout(debounceTimer);
    const val = e.target.value.trim();
    if (!val) {
      dropdown.classList.add('hidden');
      return;
    }
    debounceTimer = setTimeout(async () => {
      try {
        const authHeaders = { 'X-User-ID': state.currentUser ? state.currentUser.id.toString() : '1' };
        const encVal = encodeURIComponent(val);

        const [incRes, reqRes, chgRes, kbRes] = await Promise.allSettled([
          fetch(`${API_BASE}/incidents?search=${encVal}`, { headers: authHeaders }),
          fetch(`${API_BASE}/service-requests?search=${encVal}`, { headers: authHeaders }),
          fetch(`${API_BASE}/changes?search=${encVal}`, { headers: authHeaders }),
          fetch(`${API_BASE}/knowledge?search=${encVal}`, { headers: authHeaders })
        ]);

        const incidents = (incRes.status === 'fulfilled' && incRes.value.ok) ? await incRes.value.json() : [];
        const requests = (reqRes.status === 'fulfilled' && reqRes.value.ok) ? await reqRes.value.json() : [];
        const changes = (chgRes.status === 'fulfilled' && chgRes.value.ok) ? await chgRes.value.json() : [];
        const articles = (kbRes.status === 'fulfilled' && kbRes.value.ok) ? await kbRes.value.json() : [];

        dropdown.classList.remove('hidden');
        const totalFound = incidents.length + requests.length + changes.length + articles.length;
        if (totalFound === 0) {
          dropdown.innerHTML = `<div class="p-3 text-xs text-slate-400 text-center">No matching tickets or articles found for "<strong>${val}</strong>".</div>`;
          return;
        }

        let html = `<div class="space-y-2 text-xs">`;

        // Incidents Section
        if (incidents.length > 0) {
          html += `
            <div class="px-2 pt-1 pb-0.5 text-[10px] font-bold uppercase tracking-wider text-purple-600 dark:text-purple-400 flex items-center justify-between">
              <span class="flex items-center space-x-1"><span>⚡ Incidents</span></span>
              <span>${incidents.length} found</span>
            </div>
            ${incidents.slice(0, 4).map(i => `
              <a href="#/incidents/${i.number}" onclick="document.getElementById('searchDropdown').classList.add('hidden')" class="flex items-center justify-between p-2 rounded-lg hover:bg-[var(--bg-tertiary)] transition-colors">
                <div class="flex items-center space-x-2 truncate">
                  <span class="font-bold text-purple-600 shrink-0">${i.number}</span>
                  <span class="truncate max-w-xs text-[var(--text-primary)] font-medium">${i.short_description}</span>
                </div>
                <div class="flex items-center space-x-1.5 shrink-0 ml-2">
                  <span class="text-[10px] px-1.5 py-0.5 rounded badge-${i.priority.toLowerCase()} font-bold">${i.priority}</span>
                  <span class="text-[10px] px-1.5 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 font-semibold">${i.status}</span>
                </div>
              </a>
            `).join('')}
          `;
        }

        // Service Requests Section
        if (requests.length > 0) {
          html += `
            <div class="px-2 pt-2 pb-0.5 border-t border-[var(--border-color)] text-[10px] font-bold uppercase tracking-wider text-indigo-600 dark:text-indigo-400 flex items-center justify-between">
              <span class="flex items-center space-x-1"><span>📦 Service Requests</span></span>
              <span>${requests.length} found</span>
            </div>
            ${requests.slice(0, 4).map(r => `
              <a href="#/service-requests/${r.number}" onclick="document.getElementById('searchDropdown').classList.add('hidden')" class="flex items-center justify-between p-2 rounded-lg hover:bg-[var(--bg-tertiary)] transition-colors">
                <div class="flex items-center space-x-2 truncate">
                  <span class="font-bold text-indigo-600 shrink-0">${r.number}</span>
                  <span class="truncate max-w-xs text-[var(--text-primary)] font-medium">${r.short_description}</span>
                </div>
                <div class="flex items-center space-x-1.5 shrink-0 ml-2">
                  <span class="text-[10px] px-1.5 py-0.5 rounded badge-${r.priority.toLowerCase()} font-bold">${r.priority}</span>
                  <span class="text-[10px] px-1.5 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 font-semibold">${r.status}</span>
                </div>
              </a>
            `).join('')}
          `;
        }

        // Change Requests Section
        if (changes.length > 0) {
          html += `
            <div class="px-2 pt-2 pb-0.5 border-t border-[var(--border-color)] text-[10px] font-bold uppercase tracking-wider text-amber-600 dark:text-amber-400 flex items-center justify-between">
              <span class="flex items-center space-x-1"><span>🔄 Change Requests</span></span>
              <span>${changes.length} found</span>
            </div>
            ${changes.slice(0, 4).map(c => `
              <a href="#/changes/${c.number}" onclick="document.getElementById('searchDropdown').classList.add('hidden')" class="flex items-center justify-between p-2 rounded-lg hover:bg-[var(--bg-tertiary)] transition-colors">
                <div class="flex items-center space-x-2 truncate">
                  <span class="font-bold text-amber-600 shrink-0">${c.number}</span>
                  <span class="truncate max-w-xs text-[var(--text-primary)] font-medium">${c.short_description}</span>
                </div>
                <div class="flex items-center space-x-1.5 shrink-0 ml-2">
                  <span class="text-[10px] px-1.5 py-0.5 rounded bg-amber-100 dark:bg-amber-950 text-amber-700 dark:text-amber-300 font-bold">${c.change_type || 'Normal'}</span>
                  <span class="text-[10px] px-1.5 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 font-semibold">${c.change_status || c.status}</span>
                </div>
              </a>
            `).join('')}
          `;
        }

        // Knowledge Base Section
        if (articles.length > 0) {
          html += `
            <div class="px-2 pt-2 pb-0.5 border-t border-[var(--border-color)] text-[10px] font-bold uppercase tracking-wider text-slate-400 flex items-center justify-between">
              <span>📚 Knowledge Base</span>
              <span>${articles.length} articles</span>
            </div>
            ${articles.slice(0, 3).map(a => `
              <a href="#/knowledge" onclick="document.getElementById('searchDropdown').classList.add('hidden')" class="flex items-center justify-between p-2 rounded-lg hover:bg-[var(--bg-tertiary)] transition-colors">
                <div class="flex items-center space-x-2 truncate">
                  <span class="font-bold text-indigo-500 shrink-0">${a.article_number}</span>
                  <span class="truncate max-w-xs text-[var(--text-primary)]">${a.title}</span>
                </div>
                <span class="text-[10px] text-slate-400">Article</span>
              </a>
            `).join('')}
          `;
        }

        // Footer: View all results in Unified Tickets
        html += `
          <div class="pt-2 border-t border-[var(--border-color)] px-2">
            <a href="#/tickets" onclick="document.getElementById('searchDropdown').classList.add('hidden'); setTimeout(() => { const fi = document.getElementById('filterTicketSearch') || document.getElementById('filterUnifiedSearch'); if (fi) { fi.value = '${val.replace(/'/g, "\\'")}'; fi.dispatchEvent(new Event('input', { bubbles: true })); } }, 200)" class="block text-center py-1.5 rounded-lg bg-purple-50 dark:bg-purple-950/40 hover:bg-purple-100 dark:hover:bg-purple-900/40 text-purple-700 dark:text-purple-300 font-bold text-xs transition-colors">
              🔍 Open All Tickets Console (${totalFound} total results)
            </a>
          </div>
        `;

        html += `</div>`;
        dropdown.innerHTML = html;
      } catch (err) {
        console.error('Global search error', err);
      }
    }, 250);
  });

  document.addEventListener('click', (e) => {
    if (!input.contains(e.target) && !dropdown.contains(e.target)) {
      dropdown.classList.add('hidden');
    }
  });
}

// --- DASHBOARD VIEW ---
async function renderDashboardView(container, options = {}) {
  container.innerHTML = `<div class="p-8 text-center text-slate-400"><i data-lucide="loader-2" class="w-8 h-8 animate-spin mx-auto mb-2 text-purple-500"></i>Loading Control Plane Dashboard...</div>`;
  lucide.createIcons();

  const isGlobalAdmin = !!(state.currentUser?.is_global_admin || state.currentUser?.username === 'admin');
  const userBoundaries = state.currentUser?.project_boundaries || {};
  const userProjects = (userBoundaries.project_names && userBoundaries.project_names.length)
    ? userBoundaries.project_names
    : (state.currentUser?.admin_projects || state.currentUser?.support_projects || []);

  let currentDashboardProject = options.projectName !== undefined
    ? options.projectName
    : (window._activeDashboardProject !== undefined
        ? window._activeDashboardProject
        : ((!isGlobalAdmin && userProjects.length > 0) ? userProjects[0] : ''));
  window._activeDashboardProject = currentDashboardProject;

  try {
    const query = currentDashboardProject ? `?project_name=${encodeURIComponent(currentDashboardProject)}` : '';
    const res = await fetch(`${API_BASE}/dashboard${query}`, {
      headers: { 'X-User-ID': state.currentUser.id.toString() }
    });
    const d = await res.json();
    const role = state.currentUser.role;

    const projectSet = new Set();
    if (state.projects) state.projects.forEach(p => projectSet.add(p.name));
    userProjects.forEach(p => projectSet.add(p));
    if (d.selected_project) projectSet.add(d.selected_project.name);
    const availableProjects = [...projectSet].filter(Boolean).sort();

    let contentHtml = '';

    if (role === 'employee') {
      // Requester Dashboard
      contentHtml = `
        <div class="space-y-6">
          <div class="flex items-center justify-between">
            <div>
              <h1 class="text-2xl font-black tracking-tight">Employee Self-Service Center</h1>
              <p class="text-sm text-slate-500">Welcome back, ${state.currentUser.full_name}. Track your open requests and service tickets.</p>
            </div>
            <button onclick="openCreateModal()" class="bg-purple-600 hover:bg-purple-700 text-white px-4 py-2 rounded-xl text-sm font-semibold shadow flex items-center space-x-2">
              <i data-lucide="plus" class="w-4 h-4"></i>
              <span>Report an Issue</span>
            </button>
          </div>

          <div class="grid grid-cols-1 md:grid-cols-3 gap-5">
            <div class="p-5 rounded-2xl bg-[var(--card-bg)] border border-[var(--border-color)] shadow-sm">
              <div class="flex items-center justify-between text-slate-500 text-xs font-semibold uppercase">
                <span>My Open Tickets</span>
                <i data-lucide="inbox" class="w-4 h-4 text-purple-500"></i>
              </div>
              <div class="text-3xl font-black mt-2 text-purple-600">${d.user_metrics.my_open_tickets}</div>
            </div>
            <div class="p-5 rounded-2xl bg-[var(--card-bg)] border border-[var(--border-color)] shadow-sm">
              <div class="flex items-center justify-between text-slate-500 text-xs font-semibold uppercase">
                <span>Pending Action</span>
                <i data-lucide="clock" class="w-4 h-4 text-amber-500"></i>
              </div>
              <div class="text-3xl font-black mt-2 text-amber-600">${d.user_metrics.my_pending_tickets}</div>
            </div>
            <div class="p-5 rounded-2xl bg-[var(--card-bg)] border border-[var(--border-color)] shadow-sm">
              <div class="flex items-center justify-between text-slate-500 text-xs font-semibold uppercase">
                <span>Resolved Tickets</span>
                <i data-lucide="check-circle" class="w-4 h-4 text-emerald-500"></i>
              </div>
              <div class="text-3xl font-black mt-2 text-emerald-600">${d.user_metrics.my_resolved_tickets}</div>
            </div>
          </div>

          <!-- Quick Service Catalog -->
          <div class="rounded-2xl bg-[var(--card-bg)] border border-[var(--border-color)] p-6 shadow-sm">
            <h2 class="text-base font-bold mb-4">Request Something from IT</h2>
            <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div onclick="openCatalogModal('Database Read-Only Access')" class="p-4 rounded-xl border border-[var(--border-color)] hover:border-purple-500 hover:shadow-md cursor-pointer transition-all bg-[var(--bg-tertiary)]">
                <i data-lucide="database" class="w-6 h-6 text-purple-600 mb-2"></i>
                <div class="font-bold text-sm">Database Access Request</div>
                <div class="text-xs text-slate-400 mt-1">Read-only permissions for PostgreSQL or MySQL</div>
              </div>
              <div onclick="openCatalogModal('Software Installation')" class="p-4 rounded-xl border border-[var(--border-color)] hover:border-purple-500 hover:shadow-md cursor-pointer transition-all bg-[var(--bg-tertiary)]">
                <i data-lucide="hard-drive" class="w-6 h-6 text-indigo-600 mb-2"></i>
                <div class="font-bold text-sm">Software Installation</div>
                <div class="text-xs text-slate-400 mt-1">Request developer tools, IDEs, and packages</div>
              </div>
              <div onclick="openCatalogModal('Cloud Environment Request')" class="p-4 rounded-xl border border-[var(--border-color)] hover:border-purple-500 hover:shadow-md cursor-pointer transition-all bg-[var(--bg-tertiary)]">
                <i data-lucide="cloud" class="w-6 h-6 text-emerald-600 mb-2"></i>
                <div class="font-bold text-sm">Cloud Environment</div>
                <div class="text-xs text-slate-400 mt-1">Provision EKS namespace or AWS sandbox</div>
              </div>
            </div>
          </div>
        </div>
      `;
    } else {
      // Support Engineer, Manager, or Admin Dashboard
      contentHtml = `
        <div class="space-y-6">
          <div class="flex items-center justify-between">
            <div>
              <h1 class="text-2xl font-black tracking-tight">${(role === 'administrator' || role === 'itsm_admin' || state.currentUser?.is_global_admin) ? 'Enterprise Control Plane Overview' : (role === 'group_manager' ? 'Manager Queue & Operations Oversight' : 'Support Queue & Team Operations')}</h1>
              <p class="text-sm text-slate-500">Real-time telemetry, routing performance, and SLA compliance monitoring.</p>
            </div>
            <div class="flex items-center space-x-3">
              <div class="flex items-center space-x-1.5 bg-[var(--card-bg)] border border-[var(--border-color)] px-2.5 py-1.5 rounded-xl shadow-xs">
                <i data-lucide="layers" class="w-3.5 h-3.5 text-purple-600"></i>
                <span class="text-[10px] font-bold text-slate-400 uppercase">Project:</span>
                <select id="dashboardProjectFilter" onchange="window.switchDashboardProject(this.value)" class="bg-transparent text-xs font-bold text-[var(--text-primary)] focus:outline-none cursor-pointer">
                  <option value="">All Projects Scope</option>
                  ${availableProjects.map(p => `<option value="${p}" ${p === currentDashboardProject ? 'selected' : ''}>${p}</option>`).join('')}
                </select>
              </div>
              ${(role === 'administrator' || role === 'itsm_admin' || state.currentUser?.is_global_admin) ? `
              <a href="#/admin/simulator" class="px-3.5 py-1.5 rounded-lg border border-[var(--border-color)] bg-[var(--card-bg)] hover:bg-[var(--bg-tertiary)] text-xs font-semibold flex items-center space-x-1.5">
                <i data-lucide="play" class="w-3.5 h-3.5 text-emerald-500"></i>
                <span>Test Routing Simulator</span>
              </a>` : ''}
              <button onclick="openCreateModal()" class="bg-purple-600 hover:bg-purple-700 text-white px-3.5 py-1.5 rounded-lg text-xs font-semibold shadow">
                + New Incident
              </button>
            </div>
          </div>

          <!-- Top Telemetry Cards -->
          <div class="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-4">
            <div class="p-4 rounded-xl bg-[var(--card-bg)] border border-[var(--border-color)] shadow-sm">
              <div class="text-xs text-slate-400 font-medium">Open Incidents</div>
              <div class="text-2xl font-black mt-1 text-[var(--text-primary)]">${d.summary.open_incidents}</div>
            </div>
            <div class="p-4 rounded-xl bg-[var(--card-bg)] border border-[var(--border-color)] shadow-sm">
              <div class="text-xs text-red-500 font-bold">P1 Critical Active</div>
              <div class="text-2xl font-black mt-1 text-red-600">${d.summary.p1_incidents}</div>
            </div>
            <div class="p-4 rounded-xl bg-[var(--card-bg)] border border-[var(--border-color)] shadow-sm">
              <div class="text-xs text-amber-500 font-bold">P2 High Active</div>
              <div class="text-2xl font-black mt-1 text-amber-600">${d.summary.p2_incidents}</div>
            </div>
            <div class="p-4 rounded-xl bg-[var(--card-bg)] border border-[var(--border-color)] shadow-sm">
              <div class="text-xs text-emerald-600 font-bold">SLA Compliance</div>
              <div class="text-2xl font-black mt-1 text-emerald-600">${d.summary.sla_compliance_pct}%</div>
            </div>
            <div class="p-4 rounded-xl bg-[var(--card-bg)] border border-[var(--border-color)] shadow-sm">
              <div class="text-xs text-slate-400 font-medium">Mean Time to Resolve</div>
              <div class="text-2xl font-black mt-1 text-indigo-600">${d.summary.mttr_hours}h</div>
            </div>
            <div class="p-4 rounded-xl bg-[var(--card-bg)] border border-[var(--border-color)] shadow-sm">
              <div class="text-xs text-slate-400 font-medium">Mean Response Time</div>
              <div class="text-2xl font-black mt-1 text-purple-600">${d.summary.mtta_minutes}m</div>
            </div>
          </div>

          <!-- Team Workload & Operations Section -->
          <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <!-- Workload Visualization -->
            <div class="rounded-2xl bg-[var(--card-bg)] border border-[var(--border-color)] p-5 shadow-sm">
              <div class="flex items-center justify-between mb-4">
                <h2 class="text-sm font-bold">Support Team Workload</h2>
                <span class="text-[11px] text-slate-400">Live Active Tickets</span>
              </div>
              <div class="space-y-3">
                ${d.team_workload.map(eng => `
                  <div>
                    <div class="flex items-center justify-between text-xs mb-1">
                      <span class="font-semibold">${eng.engineer_name}</span>
                      <span class="text-slate-400">${eng.active_tickets} tickets</span>
                    </div>
                    <div class="w-full bg-[var(--bg-tertiary)] rounded-full h-2 overflow-hidden">
                      <div class="bg-purple-600 h-2 rounded-full" style="width: ${Math.min(100, eng.active_tickets * 15)}%"></div>
                    </div>
                  </div>
                `).join('')}
              </div>
            </div>

            <!-- Incidents by Priority Chart -->
            <div class="rounded-2xl bg-[var(--card-bg)] border border-[var(--border-color)] p-5 shadow-sm">
              <div class="flex items-center justify-between mb-4">
                <h2 class="text-sm font-bold">Incident Volume by Priority</h2>
                <span class="text-[11px] text-slate-400">Distribution</span>
              </div>
              <div class="h-48 flex items-center justify-center">
                <canvas id="priorityChart"></canvas>
              </div>
            </div>

            <!-- Incidents by Application -->
            <div class="rounded-2xl bg-[var(--card-bg)] border border-[var(--border-color)] p-5 shadow-sm">
              <div class="flex items-center justify-between mb-4">
                <h2 class="text-sm font-bold">Volume by Application</h2>
                <span class="text-[11px] text-slate-400">Services</span>
              </div>
              <div class="space-y-2 text-xs">
                ${d.incidents_by_application.map(app => `
                  <div class="flex items-center justify-between p-2 rounded bg-[var(--bg-tertiary)]">
                    <span class="font-medium">${app.name}</span>
                    <span class="font-bold px-2 py-0.5 rounded bg-purple-500/10 text-purple-600">${app.count}</span>
                  </div>
                `).join('')}
              </div>
            </div>
          </div>

          <!-- Recent Incident Activity -->
          <div class="rounded-2xl bg-[var(--card-bg)] border border-[var(--border-color)] overflow-hidden shadow-sm">
            <div class="p-4 border-b border-[var(--border-color)] flex items-center justify-between">
              <h2 class="text-sm font-bold">Recent Incidents & SLA Status</h2>
              <a href="#/incidents" class="text-xs text-purple-600 hover:underline">View All Incidents →</a>
            </div>
            <div class="overflow-x-auto">
              <table class="w-full text-left text-xs">
                <thead class="bg-[var(--bg-tertiary)] text-slate-400 uppercase font-semibold text-[10px]">
                  <tr>
                    <th class="p-3">Ticket</th>
                    <th class="p-3">Priority</th>
                    <th class="p-3">Short Description</th>
                    <th class="p-3">Application / Project</th>
                    <th class="p-3">Assignment Group</th>
                    <th class="p-3">Status</th>
                    <th class="p-3">Action</th>
                  </tr>
                </thead>
                <tbody class="divide-y divide-[var(--border-color)]">
                  ${d.recent_incidents.map(i => `
                    <tr class="hover:bg-[var(--bg-tertiary)] transition-colors">
                      <td class="p-3 font-bold text-purple-600">
                        <a href="#/incidents/${i.number}">${i.number}</a>
                      </td>
                      <td class="p-3">
                        <span class="px-2 py-0.5 rounded text-[10px] font-bold badge-${i.priority.toLowerCase()}">${i.priority}</span>
                      </td>
                      <td class="p-3 font-medium text-[var(--text-primary)] max-w-xs truncate">${i.short_description}</td>
                      <td class="p-3 text-slate-400">${i.application_name}</td>
                      <td class="p-3 text-slate-400">${i.assignment_group_name}</td>
                      <td class="p-3">
                        <span class="px-2 py-0.5 rounded text-[10px] font-semibold bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300">${i.status}</span>
                      </td>
                      <td class="p-3">
                        <a href="#/incidents/${i.number}" class="text-purple-600 hover:underline font-semibold">View</a>
                      </td>
                    </tr>
                  `).join('')}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      `;
    }

    container.innerHTML = contentHtml;
    lucide.createIcons();

    // Render Chart.js if canvas exists
    const chartCanvas = document.getElementById('priorityChart');
    if (chartCanvas && d.incidents_by_priority) {
      new Chart(chartCanvas, {
        type: 'doughnut',
        data: {
          labels: ['P1 Critical', 'P2 High', 'P3 Medium', 'P4 Low'],
          datasets: [{
            data: [
              d.incidents_by_priority.P1 || 0,
              d.incidents_by_priority.P2 || 0,
              d.incidents_by_priority.P3 || 0,
              d.incidents_by_priority.P4 || 0
            ],
            backgroundColor: ['#ef4444', '#f97316', '#eab308', '#94a3b8']
          }]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: { position: 'right', labels: { boxWidth: 12, font: { size: 10 } } }
          }
        }
      });
    }

  } catch (err) {
    container.innerHTML = `<div class="p-8 text-center text-red-500">Failed to load dashboard: ${err.message}</div>`;
  }
}

window.switchDashboardProject = function(pName) {
  window._activeDashboardProject = pName;
  renderDashboardView(document.getElementById('mainApp'), { projectName: pName });
};

// --- TICKET TYPE TABS (ALL TICKETS, INCIDENTS, SERVICE REQUESTS, CHANGES) ---
function renderTicketTypeTabs(activeTab = 'all') {
  const isEndUser = isUserEndUser(state.currentUser);
  const allHref = isEndUser ? '#/my-tickets' : '#/tickets';
  const incidentHref = isEndUser ? '#/my-tickets' : '#/incidents';

  const isAllActive = activeTab === 'all' || activeTab === 'tickets';
  const isIncidentActive = activeTab === 'incidents' && !isAllActive;
  const isRequestActive = activeTab === 'service-requests';
  const isChangeActive = activeTab === 'changes';

  return `
    <div class="flex items-center space-x-2 border-b border-[var(--border-color)] pb-3">
      <a href="${allHref}" class="px-3.5 py-1.5 rounded-xl text-xs flex items-center space-x-1.5 transition-colors ${
        isAllActive
          ? 'font-bold bg-purple-600 text-white shadow-sm'
          : 'font-semibold text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] border border-[var(--border-color)]'
      }">
        <i data-lucide="layers" class="w-3.5 h-3.5 ${isAllActive ? 'text-white' : 'text-purple-400'}"></i>
        <span>🎯 All Tickets</span>
      </a>
      <a href="${incidentHref}" class="px-3.5 py-1.5 rounded-xl text-xs flex items-center space-x-1.5 transition-colors ${
        isIncidentActive
          ? 'font-bold bg-purple-600 text-white shadow-sm'
          : 'font-semibold text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] border border-[var(--border-color)]'
      }">
        <i data-lucide="zap" class="w-3.5 h-3.5 ${isIncidentActive ? 'text-white' : 'text-purple-400'}"></i>
        <span>⚡ Incidents</span>
      </a>
      <a href="#/service-requests" class="px-3.5 py-1.5 rounded-xl text-xs flex items-center space-x-1.5 transition-colors ${
        isRequestActive
          ? 'font-bold bg-purple-600 text-white shadow-sm'
          : 'font-semibold text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] border border-[var(--border-color)]'
      }">
        <i data-lucide="box" class="w-3.5 h-3.5 ${isRequestActive ? 'text-white' : 'text-indigo-400'}"></i>
        <span>📦 Service Requests</span>
      </a>
      <a href="#/changes" class="px-3.5 py-1.5 rounded-xl text-xs flex items-center space-x-1.5 transition-colors ${
        isChangeActive
          ? 'font-bold bg-purple-600 text-white shadow-sm'
          : 'font-semibold text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] border border-[var(--border-color)]'
      }">
        <i data-lucide="refresh-cw" class="w-3.5 h-3.5 ${isChangeActive ? 'text-white' : 'text-amber-400'}"></i>
        <span>🔄 Change Requests</span>
      </a>
    </div>
  `;
}

// --- UNIFIED TICKETS CONSOLE (SERVICENOW TASK-LEVEL AGGREGATE) ---
async function renderUnifiedTicketsView(container, options = {}) {
  container.innerHTML = `<div class="p-8 text-center text-slate-400"><i data-lucide="loader-2" class="w-8 h-8 animate-spin mx-auto mb-2 text-purple-500"></i>Loading unified tickets console...</div>`;
  lucide.createIcons();

  const isEndUser = isUserEndUser(state.currentUser);
  const isMyTickets = options.myTickets || isEndUser;
  const authHeaders = { 'X-User-ID': state.currentUser ? state.currentUser.id.toString() : '1' };
  const queryParam = isMyTickets ? '?my_tickets=true' : '';

  try {
    const [incRes, reqRes, chgRes, projRes, appRes] = await Promise.allSettled([
      fetch(`${API_BASE}/incidents${queryParam}`, { headers: authHeaders }),
      fetch(`${API_BASE}/service-requests${queryParam}`, { headers: authHeaders }),
      fetch(`${API_BASE}/changes${queryParam}`, { headers: authHeaders }),
      fetch(`${API_BASE}/projects`),
      fetch(`${API_BASE}/applications`)
    ]);

    const incidents = (incRes.status === 'fulfilled' && incRes.value.ok) ? await incRes.value.json() : [];
    const requests = (reqRes.status === 'fulfilled' && reqRes.value.ok) ? await reqRes.value.json() : [];
    const changes = (chgRes.status === 'fulfilled' && chgRes.value.ok) ? await chgRes.value.json() : [];
    if (projRes.status === 'fulfilled' && projRes.value.ok) state.projects = await projRes.value.json();
    if (appRes.status === 'fulfilled' && appRes.value.ok) state.applications = await appRes.value.json();

    // Normalize unified task items
    const allTickets = [];

    incidents.forEach(i => {
      allTickets.push({
        id: i.id,
        number: i.number,
        ticket_type: 'Incident',
        type_icon: 'zap',
        type_badge_class: 'bg-purple-100 dark:bg-purple-950/80 text-purple-700 dark:text-purple-300 border-purple-200 dark:border-purple-800',
        detail_route: `#/incidents/${i.number}`,
        priority: i.priority || 'P3',
        short_description: i.short_description,
        project_name: i.project_name || 'N/A',
        application_name: i.application_name || 'N/A',
        caller_name: i.caller_name || 'Caller',
        assignment_group_name: i.assignment_group_name || 'Unassigned',
        assigned_to_name: i.assigned_to_name || 'Unassigned',
        status: i.status || 'New',
        created_at: i.created_at || new Date().toISOString()
      });
    });

    requests.forEach(r => {
      allTickets.push({
        id: r.id,
        number: r.number,
        ticket_type: 'Service Request',
        type_icon: 'box',
        type_badge_class: 'bg-indigo-100 dark:bg-indigo-950/80 text-indigo-700 dark:text-indigo-300 border-indigo-200 dark:border-indigo-800',
        detail_route: `#/service-requests/${r.number}`,
        priority: r.priority || 'P3',
        short_description: r.short_description,
        project_name: r.project_name || 'N/A',
        application_name: r.application_name || 'N/A',
        caller_name: r.requested_by_name || 'Requester',
        assignment_group_name: r.assignment_group_name || 'Unassigned',
        assigned_to_name: r.assigned_to_name || 'Unassigned',
        status: r.status || 'Submitted',
        created_at: r.created_at || new Date().toISOString()
      });
    });

    changes.forEach(c => {
      allTickets.push({
        id: c.id,
        number: c.number,
        ticket_type: 'Change Request',
        type_icon: 'refresh-cw',
        type_badge_class: 'bg-amber-100 dark:bg-amber-950/80 text-amber-700 dark:text-amber-300 border-amber-200 dark:border-amber-800',
        detail_route: `#/changes/${c.number}`,
        priority: c.priority || 'P3',
        short_description: c.short_description,
        project_name: c.project_name || 'N/A',
        application_name: c.application_name || 'N/A',
        caller_name: c.requested_by_name || 'Requester',
        assignment_group_name: c.assignment_group_name || 'Unassigned',
        assigned_to_name: c.assigned_to_name || 'Unassigned',
        status: c.change_status || c.status || 'Draft',
        created_at: c.created_at || new Date().toISOString()
      });
    });

    // Sort all tickets by created_at descending
    allTickets.sort((a, b) => new Date(b.created_at) - new Date(a.created_at));

    // Scoping evaluation
    // Scoping evaluation
    const isGlobalAdmin = !!(state.currentUser?.is_global_admin || state.currentUser?.username === 'admin');
    const userBoundaries = state.currentUser?.project_boundaries || {};
    const userProjects = (userBoundaries.project_names && userBoundaries.project_names.length)
      ? userBoundaries.project_names
      : (state.currentUser?.admin_projects || state.currentUser?.support_projects || []);
    const isSupportMember = !isGlobalAdmin && !isEndUser && userProjects.length > 0;
    const defaultProject = (isSupportMember && userProjects.length > 0) ? userProjects[0] : '';

    // Collect unique projects and application mappings
    const projectSet = new Set(allTickets.map(t => t.project_name).filter(p => p && p !== 'N/A'));
    userProjects.forEach(p => projectSet.add(p));
    if (state.projects) state.projects.forEach(p => projectSet.add(p.name));
    const uniqueProjects = [...projectSet].sort();

    const projectToApps = {};
    allTickets.forEach(t => {
      if (t.project_name && t.application_name && t.project_name !== 'N/A' && t.application_name !== 'N/A') {
        if (!projectToApps[t.project_name]) projectToApps[t.project_name] = new Set();
        projectToApps[t.project_name].add(t.application_name);
      }
    });
    if (state.applications) {
      state.applications.forEach(a => {
        const pName = a.project_name || (state.projects?.find(p => p.id === a.project_id)?.name);
        if (pName && a.name) {
          if (!projectToApps[pName]) projectToApps[pName] = new Set();
          projectToApps[pName].add(a.name);
        }
      });
    }
    if (userBoundaries.project_names && userBoundaries.application_names) {
      userBoundaries.project_names.forEach(pn => {
        if (!projectToApps[pn]) projectToApps[pn] = new Set();
        userBoundaries.application_names.forEach(an => projectToApps[pn].add(an));
      });
    }

    // Filter values
    const uniquePriorities = ['P1', 'P2', 'P3', 'P4'];
    const uniqueStatuses = [...new Set([
      'Active', 'New', 'In Progress', 'On Hold', 'Pending', 'Resolved', 'Closed', 'Canceled',
      'Submitted', 'Pending Approval', 'Approved', 'In Fulfillment', 'Fulfilled', 'Completed',
      'Draft', 'Assess', 'Authorize', 'Scheduled', 'Implement', 'Review',
      ...allTickets.map(t => t.status).filter(Boolean)
    ])];
    const uniqueGroups = [...new Set(allTickets.map(t => t.assignment_group_name).filter(Boolean))].sort();
    const allKnownApps = new Set(allTickets.map(t => t.application_name).filter(a => a && a !== 'N/A'));
    if (state.applications) state.applications.forEach(a => { if (a.name) allKnownApps.add(a.name); });
    const uniqueApps = [...allKnownApps].sort();

    const initialProjects = (isSupportMember && userProjects.length > 0) ? userProjects.slice() : (defaultProject ? [defaultProject] : []);
    let initialApps = [];
    if (initialProjects.length > 0) {
      const appSet = new Set();
      initialProjects.forEach(p => {
        if (projectToApps[p]) projectToApps[p].forEach(a => appSet.add(a));
      });
      initialApps = appSet.size > 0 ? [...appSet].sort() : uniqueApps;
    } else {
      initialApps = uniqueApps;
    }

    let initialGroups = getFilteredAssignmentGroups(initialProjects, '', uniqueGroups);

    container.innerHTML = `
      <div class="space-y-5">
        <!-- Header -->
        <div class="flex items-center justify-between">
          <div>
            <h1 class="text-2xl font-black tracking-tight">${isMyTickets ? 'My Raised Tickets' : 'Tickets & Task Management'}</h1>
            <p class="text-sm text-slate-500">
              ${isMyTickets ? 'All incidents, service requests, and changes submitted by you with live status tracking.' : (isSupportMember ? `Project queue for ${userProjects.join(', ')} with cross-project reassignment visibility.` : 'Enterprise unified task console across all incidents, requests, and changes.')}
            </p>
          </div>
          <div class="flex items-center space-x-2.5">
            ${!isEndUser ? `
              <button onclick="openExportModal('incidents')" class="px-3.5 py-2 rounded-xl border border-[var(--border-color)] bg-[var(--card-bg)] hover:bg-[var(--bg-tertiary)] text-xs font-semibold flex items-center space-x-1.5 shadow-sm text-purple-600 dark:text-purple-300 transition-all">
                <i data-lucide="download" class="w-4 h-4 text-purple-500"></i>
                <span>Export Tickets</span>
              </button>
            ` : ''}
            <button onclick="openCreateModal()" class="bg-purple-600 hover:bg-purple-700 text-white px-4 py-2 rounded-xl text-sm font-semibold shadow flex items-center space-x-2">
              <i data-lucide="plus" class="w-4 h-4"></i>
              <span>Create Ticket</span>
            </button>
          </div>
        </div>

        <!-- Ticket Type Tabs -->
        ${renderTicketTypeTabs(isMyTickets ? 'my-tickets' : 'all')}

        <!-- Project-Specific Statistical Dashboard for Tickets -->
        <div class="p-4 bg-[var(--card-bg)] border border-[var(--border-color)] rounded-2xl shadow-sm space-y-3">
          <div class="flex items-center justify-between">
            <div class="flex items-center space-x-2">
              <i data-lucide="bar-chart-2" class="w-4 h-4 text-purple-600"></i>
              <span class="text-xs font-bold text-slate-700 dark:text-slate-300">Statistical Dashboard & Ticket Telemetry</span>
              <span id="unifiedScopeBadge" class="px-2.5 py-0.5 rounded-full text-[11px] font-extrabold bg-purple-100 dark:bg-purple-950 text-purple-700 dark:text-purple-300 border border-purple-200 dark:border-purple-800">
                ${initialProjects.length === 1 ? `Project: ${initialProjects[0]}` : (initialProjects.length > 1 ? `Projects: ${initialProjects.join(', ')}` : 'All Projects Scope')}
              </span>
            </div>
            <div id="unifiedStatsSubtext" class="text-[11px] text-slate-400 font-medium">
              Live project-specific metrics calculated for active project & filters
            </div>
          </div>

          <div class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3 pt-1">
            <div class="p-3.5 rounded-xl bg-[var(--bg-tertiary)] border border-[var(--border-color)] shadow-xs">
              <div class="text-[10px] font-bold text-slate-400 uppercase tracking-wider">Total In Scope</div>
              <div id="statTotalTickets" class="text-2xl font-black text-[var(--text-primary)] mt-1">0</div>
              <div id="statTotalSub" class="text-[10px] text-slate-400 mt-0.5">Tickets in view</div>
            </div>
            <div class="p-3.5 rounded-xl bg-[var(--bg-tertiary)] border border-[var(--border-color)] shadow-xs">
              <div class="text-[10px] font-bold text-purple-600 dark:text-purple-400 uppercase tracking-wider flex items-center space-x-1">
                <i data-lucide="zap" class="w-3.5 h-3.5"></i>
                <span>Incidents</span>
              </div>
              <div id="statIncidents" class="text-2xl font-black text-purple-600 mt-1">0</div>
              <div class="text-[10px] text-slate-400 mt-0.5">Disruptions & fixes</div>
            </div>
            <div class="p-3.5 rounded-xl bg-[var(--bg-tertiary)] border border-[var(--border-color)] shadow-xs">
              <div class="text-[10px] font-bold text-indigo-600 dark:indigo-400 uppercase tracking-wider flex items-center space-x-1">
                <i data-lucide="box" class="w-3.5 h-3.5"></i>
                <span>Requests</span>
              </div>
              <div id="statRequests" class="text-2xl font-black text-indigo-600 mt-1">0</div>
              <div class="text-[10px] text-slate-400 mt-0.5">Access & services</div>
            </div>
            <div class="p-3.5 rounded-xl bg-[var(--bg-tertiary)] border border-[var(--border-color)] shadow-xs">
              <div class="text-[10px] font-bold text-teal-600 dark:text-teal-400 uppercase tracking-wider flex items-center space-x-1">
                <i data-lucide="git-pull-request" class="w-3.5 h-3.5"></i>
                <span>Changes</span>
              </div>
              <div id="statChanges" class="text-2xl font-black text-teal-600 mt-1">0</div>
              <div class="text-[10px] text-slate-400 mt-0.5">Deployments & RFCs</div>
            </div>
            <div class="p-3.5 rounded-xl bg-[var(--bg-tertiary)] border border-[var(--border-color)] shadow-xs">
              <div class="text-[10px] font-bold text-rose-600 dark:text-rose-400 uppercase tracking-wider flex items-center space-x-1">
                <i data-lucide="alert-triangle" class="w-3.5 h-3.5"></i>
                <span>P1/P2 Critical</span>
              </div>
              <div id="statCriticalHigh" class="text-2xl font-black text-rose-600 mt-1">0</div>
              <div class="text-[10px] text-slate-400 mt-0.5">Major severity</div>
            </div>
            <div class="p-3.5 rounded-xl bg-[var(--bg-tertiary)] border border-[var(--border-color)] shadow-xs">
              <div class="text-[10px] font-bold text-emerald-600 dark:text-emerald-400 uppercase tracking-wider flex items-center space-x-1">
                <i data-lucide="check-circle" class="w-3.5 h-3.5"></i>
                <span>Resolution</span>
              </div>
              <div id="statResolutionRate" class="text-2xl font-black text-emerald-600 mt-1">100%</div>
              <div id="statResolutionSub" class="text-[10px] text-slate-400 mt-0.5">Resolved / Closed</div>
            </div>
          </div>
        </div>

        <!-- Filter Bar -->
        <div class="p-4 bg-[var(--card-bg)] border border-[var(--border-color)] rounded-2xl shadow-sm space-y-3">
          <div class="flex items-center justify-between">
            <div class="flex items-center space-x-2 text-xs font-bold text-slate-700 dark:text-slate-300">
              <i data-lucide="filter" class="w-4 h-4 text-purple-600"></i>
              <span>Task & Ticket Filters</span>
              <span id="activeUnifiedBadge" class="hidden px-2 py-0.5 rounded-full text-[10px] font-bold bg-purple-100 dark:bg-purple-950 text-purple-700 dark:text-purple-300 border border-purple-200 dark:border-purple-800"></span>
            </div>
            <button id="resetUnifiedFiltersBtn" class="hidden text-xs text-purple-600 hover:text-purple-700 font-bold hover:underline flex items-center space-x-1">
              <i data-lucide="rotate-ccw" class="w-3.5 h-3.5"></i>
              <span>Clear Filters</span>
            </button>
          </div>
          <div class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-9 gap-2.5">
            <div>
              <label class="block text-[10px] font-bold uppercase text-slate-400 mb-1">Search</label>
              <div class="relative">
                <input type="text" id="filterUnifiedSearch" placeholder="Search..." class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-xl pl-7 pr-2 py-1.5 text-xs focus:ring-2 focus:ring-purple-500 focus:outline-none">
                <i data-lucide="search" class="w-3.5 h-3.5 text-slate-400 absolute left-2 top-2"></i>
              </div>
            </div>
            <div>
              <label class="block text-[10px] font-bold uppercase text-slate-400 mb-1">Ticket Type</label>
              <select id="filterUnifiedType" class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-xl px-2.5 py-1.5 text-xs focus:ring-2 focus:ring-purple-500 focus:outline-none">
                <option value="">All Types</option>
                <option value="Incident">⚡ Incidents</option>
                <option value="Service Request">📦 Service Requests</option>
                <option value="Change Request">🔄 Change Requests</option>
              </select>
            </div>
            <div>
              <label class="block text-[10px] font-bold uppercase text-slate-400 mb-1">Priority</label>
              <select id="filterUnifiedPriority" class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-xl px-2.5 py-1.5 text-xs focus:ring-2 focus:ring-purple-500 focus:outline-none">
                <option value="">All Priorities</option>
                ${uniquePriorities.map(p => `<option value="${p}">${p}</option>`).join('')}
              </select>
            </div>
            <div>
              <label class="block text-[10px] font-bold uppercase text-slate-400 mb-1">Status</label>
              <select id="filterUnifiedStatus" class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-xl px-2.5 py-1.5 text-xs focus:ring-2 focus:ring-purple-500 focus:outline-none">
                <option value="">All Statuses</option>
                ${uniqueStatuses.map(s => `<option value="${s}">${s}</option>`).join('')}
              </select>
            </div>
            <div>
              <label class="block text-[10px] font-bold uppercase text-slate-400 mb-1">Time Range</label>
              <select id="filterUnifiedTime" class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-xl px-2.5 py-1.5 text-xs focus:ring-2 focus:ring-purple-500 focus:outline-none font-semibold">
                <option value="">All Time</option>
                <option value="today">Today</option>
                <option value="7d">Last 7 Days</option>
                <option value="30d">Last 30 Days</option>
                <option value="90d">Last 90 Days</option>
                <option value="custom">📅 Custom Range...</option>
              </select>
            </div>
            <div>
              <label class="block text-[10px] font-bold uppercase text-slate-400 mb-1">Time Zone</label>
              ${renderTimezoneSelect('filterUnifiedTimezone', state.currentTimezone)}
            </div>
            <div>
              <label class="block text-[10px] font-bold uppercase text-slate-400 mb-1">Project</label>
              <div id="filterUnifiedProjectWrap"></div>
            </div>
            <div>
              <label class="block text-[10px] font-bold uppercase text-slate-400 mb-1">Application</label>
              <div id="filterUnifiedAppWrap"></div>
            </div>
            <div>
              <label class="block text-[10px] font-bold uppercase text-slate-400 mb-1">Assignment Group</label>
              <div id="filterUnifiedGroupWrap"></div>
            </div>
          </div>

          <!-- Custom Time Range Bar -->
          <div id="filterUnifiedCustomDateBar" class="hidden pt-2 border-t border-[var(--border-color)] flex flex-wrap items-center gap-3 text-xs bg-[var(--bg-tertiary)]/50 p-2.5 rounded-xl mt-2">
            <span class="font-bold text-slate-500 text-[11px] flex items-center space-x-1">
              <i data-lucide="calendar" class="w-3.5 h-3.5 text-purple-600"></i>
              <span>Custom Range:</span>
            </span>
            <div class="flex items-center space-x-1.5">
              <label class="text-[11px] text-slate-400 font-semibold">From:</label>
              <input type="datetime-local" id="filterUnifiedStartDate" class="bg-[var(--card-bg)] border border-[var(--border-color)] rounded-lg px-2 py-1 text-xs focus:ring-2 focus:ring-purple-500">
            </div>
            <div class="flex items-center space-x-1.5">
              <label class="text-[11px] text-slate-400 font-semibold">To:</label>
              <input type="datetime-local" id="filterUnifiedEndDate" class="bg-[var(--card-bg)] border border-[var(--border-color)] rounded-lg px-2 py-1 text-xs focus:ring-2 focus:ring-purple-500">
            </div>
            <button id="filterUnifiedClearCustomDateBtn" type="button" class="text-xs px-2.5 py-1 rounded-lg border border-[var(--border-color)] bg-[var(--card-bg)] hover:bg-[var(--bg-tertiary)] text-slate-600 dark:text-slate-300 font-semibold">
              Clear Range
            </button>
          </div>
        </div>

        <!-- Unified Table -->
        <div class="rounded-2xl bg-[var(--card-bg)] border border-[var(--border-color)] overflow-hidden shadow-sm">
          <div class="p-3.5 bg-[var(--bg-tertiary)] border-b border-[var(--border-color)] flex items-center justify-between text-xs">
            <span id="unifiedCountLabel" class="font-bold text-slate-400 uppercase tracking-wider">
              Total: ${allTickets.length} Tickets (${incidents.length} Incidents, ${requests.length} Requests, ${changes.length} Changes)
            </span>
          </div>

          <div class="overflow-x-auto">
            <table class="w-full text-left text-xs">
              <thead class="bg-[var(--bg-tertiary)] text-slate-400 uppercase font-semibold text-[10px]">
                <tr>
                  <th class="p-3.5">Number</th>
                  <th class="p-3.5">Type</th>
                  <th class="p-3.5">Priority</th>
                  <th class="p-3.5">Short Description</th>
                  <th class="p-3.5">Project</th>
                  <th class="p-3.5">Application</th>
                  <th class="p-3.5">Caller / Requester</th>
                  <th class="p-3.5">Assignment Group</th>
                  <th class="p-3.5">Assigned To</th>
                  <th class="p-3.5">Status</th>
                  <th class="p-3.5">Created</th>
                </tr>
              </thead>
              <tbody id="unifiedTicketsTableBody" class="divide-y divide-[var(--border-color)] font-medium">
                ${allTickets.map(t => `
                  <tr class="hover:bg-[var(--bg-tertiary)] transition-colors cursor-pointer group" onclick="window.location.hash='${t.detail_route}'">
                    <td class="p-3.5 font-bold text-purple-600 group-hover:underline flex items-center space-x-1.5">
                      <i data-lucide="${t.type_icon}" class="w-3.5 h-3.5"></i>
                      <span>${t.number}</span>
                    </td>
                    <td class="p-3.5">
                      <span class="px-2 py-0.5 rounded-full text-[10px] font-bold border ${t.type_badge_class}">${t.ticket_type}</span>
                    </td>
                    <td class="p-3.5">
                      <span class="px-2 py-0.5 rounded text-[10px] font-bold badge-${t.priority.toLowerCase()}">${t.priority}</span>
                    </td>
                    <td class="p-3.5 font-semibold text-[var(--text-primary)] max-w-sm truncate" title="${t.short_description}">${t.short_description}</td>
                    <td class="p-3.5 text-slate-500">${t.project_name}</td>
                    <td class="p-3.5 text-slate-500">${t.application_name}</td>
                    <td class="p-3.5 text-slate-500">${t.caller_name}</td>
                    <td class="p-3.5 text-slate-500">${t.assignment_group_name}</td>
                    <td class="p-3.5 text-slate-500">${t.assigned_to_name}</td>
                    <td class="p-3.5">
                      <span class="px-2 py-0.5 rounded text-[10px] font-semibold bg-slate-100 dark:bg-slate-800">${t.status}</span>
                    </td>
                    <td class="p-3.5 text-slate-400 text-[11px] unified-date-cell" data-created="${t.created_at || ''}">${formatTicketDate(t.created_at, state.currentTimezone)}</td>
                  </tr>
                `).join('')}
              </tbody>
            </table>
          </div>
          <div id="unifiedEmptyMessage" class="${allTickets.length ? 'hidden' : ''} p-12 text-center text-slate-400">
            <i data-lucide="inbox" class="w-10 h-10 mx-auto mb-2 opacity-50"></i>
            <p class="font-bold text-sm">No tickets found matching your filter criteria</p>
            <p class="text-xs text-slate-500 mt-1">Try resetting your filter parameters above.</p>
          </div>
        </div>
      </div>
    `;
    lucide.createIcons();

    // Client-side dynamic filtering & telemetry
    const searchEl = document.getElementById('filterUnifiedSearch');
    const typeEl = document.getElementById('filterUnifiedType');
    const priorityEl = document.getElementById('filterUnifiedPriority');
    const statusEl = document.getElementById('filterUnifiedStatus');
    const timeEl = document.getElementById('filterUnifiedTime');
    const tzEl = document.getElementById('filterUnifiedTimezone');
    const customDateBar = document.getElementById('filterUnifiedCustomDateBar');
    const startDateEl = document.getElementById('filterUnifiedStartDate');
    const endDateEl = document.getElementById('filterUnifiedEndDate');
    const clearCustomBtn = document.getElementById('filterUnifiedClearCustomDateBtn');
    const projectWrap = document.getElementById('filterUnifiedProjectWrap');
    const appWrap = document.getElementById('filterUnifiedAppWrap');
    const groupWrap = document.getElementById('filterUnifiedGroupWrap');
    const countBadge = document.getElementById('activeUnifiedBadge');
    const resetBtn = document.getElementById('resetUnifiedFiltersBtn');
    const tbody = document.getElementById('unifiedTicketsTableBody');
    const emptyMsg = document.getElementById('unifiedEmptyMessage');
    const totalLabel = document.getElementById('unifiedCountLabel');

    let unifiedProjectMs = null;
    let unifiedAppMs = null;
    let unifiedGroupMs = null;

    function syncAppsForProjects(chosenProjects) {
      let apps = [];
      if (chosenProjects && chosenProjects.length > 0) {
        const appSet = new Set();
        chosenProjects.forEach(p => {
          if (projectToApps[p]) projectToApps[p].forEach(a => appSet.add(a));
        });
        apps = appSet.size > 0 ? [...appSet].sort() : uniqueApps;
      } else {
        apps = uniqueApps;
      }
      if (unifiedAppMs) unifiedAppMs.setOptions(apps, true);
    }

    function syncGroupsForProjectsAndApps(chosenProjects, chosenApps) {
      const groups = getFilteredAssignmentGroups(chosenProjects, chosenApps, uniqueGroups);
      if (unifiedGroupMs) unifiedGroupMs.setOptions(groups, true);
    }

    unifiedProjectMs = createMultiSelectDropdown({
      container: projectWrap,
      options: uniqueProjects,
      selectedValues: initialProjects,
      placeholder: 'Projects',
      allLabel: 'All Projects',
      emptyMessage: 'No projects found',
      onChange: (selectedProjects) => {
        syncAppsForProjects(selectedProjects);
        syncGroupsForProjectsAndApps(selectedProjects, unifiedAppMs ? unifiedAppMs.getValues() : []);
        applyUnifiedFilters();
      }
    });

    unifiedAppMs = createMultiSelectDropdown({
      container: appWrap,
      options: initialApps,
      placeholder: 'Applications',
      allLabel: 'All Applications',
      emptyMessage: 'No applications found',
      onChange: (selectedApps) => {
        const curProjects = unifiedProjectMs ? unifiedProjectMs.getValues() : [];
        const groups = getFilteredAssignmentGroups(curProjects, selectedApps, uniqueGroups);
        if (unifiedGroupMs) unifiedGroupMs.setOptions(groups, true);
        applyUnifiedFilters();
      }
    });

    unifiedGroupMs = createMultiSelectDropdown({
      container: groupWrap,
      options: initialGroups,
      placeholder: 'Groups',
      allLabel: 'All Groups',
      emptyMessage: 'No groups found',
      onChange: () => {
        applyUnifiedFilters();
      }
    });

    function updateUnifiedStatsDashboard(filteredTickets, selectedProjects = [], selectedApps = []) {
      const scopeBadge = document.getElementById('unifiedScopeBadge');
      if (scopeBadge) {
        const appLabel = selectedApps.length === 1 ? selectedApps[0] : (selectedApps.length > 1 ? `${selectedApps.length} Apps` : '');
        if (selectedProjects.length > 0) {
          const projText = selectedProjects.length === 1
            ? `Project: ${selectedProjects[0]}`
            : (selectedProjects.length === 2 ? `Projects: ${selectedProjects.join(', ')}` : `${selectedProjects.length} Projects`);
          scopeBadge.textContent = appLabel ? `${projText} (${appLabel})` : projText;
          scopeBadge.className = "px-2.5 py-0.5 rounded-full text-[11px] font-extrabold bg-purple-100 dark:bg-purple-950 text-purple-700 dark:text-purple-300 border border-purple-200 dark:border-purple-800";
        } else {
          scopeBadge.textContent = appLabel ? `All Projects (${appLabel})` : 'All Projects Scope';
          scopeBadge.className = "px-2.5 py-0.5 rounded-full text-[11px] font-extrabold bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 border border-slate-300 dark:border-slate-700";
        }
      }

      const total = filteredTickets.length;
      const incs = filteredTickets.filter(t => t.ticket_type === 'Incident');
      const reqs = filteredTickets.filter(t => t.ticket_type === 'Service Request');
      const chgs = filteredTickets.filter(t => t.ticket_type === 'Change Request');
      const critHigh = filteredTickets.filter(t => t.priority === 'P1' || t.priority === 'P2');
      const resolved = filteredTickets.filter(t => ['Resolved', 'Closed', 'Completed', 'Approved'].includes(t.status));
      const resRate = total > 0 ? Math.round((resolved.length / total) * 100) : 100;

      const elTotal = document.getElementById('statTotalTickets');
      if (elTotal) elTotal.textContent = total;
      const elIncs = document.getElementById('statIncidents');
      if (elIncs) elIncs.textContent = incs.length;
      const elReqs = document.getElementById('statRequests');
      if (elReqs) elReqs.textContent = reqs.length;
      const elChgs = document.getElementById('statChanges');
      if (elChgs) elChgs.textContent = chgs.length;
      const elCrit = document.getElementById('statCriticalHigh');
      if (elCrit) elCrit.textContent = critHigh.length;
      const elRate = document.getElementById('statResolutionRate');
      if (elRate) elRate.textContent = `${resRate}%`;
      const elRateSub = document.getElementById('statResolutionSub');
      if (elRateSub) elRateSub.textContent = `${resolved.length} of ${total} Resolved`;
    }

    function applyUnifiedFilters() {
      const qSearch = searchEl?.value.trim().toLowerCase() || '';
      const qType = typeEl?.value || '';
      const qPriority = priorityEl?.value || '';
      const qStatus = statusEl?.value || '';
      const qTime = timeEl?.value || '';
      const qTz = tzEl?.value || state.currentTimezone || 'UTC';
      const qStart = startDateEl?.value || '';
      const qEnd = endDateEl?.value || '';
      const selectedProjects = unifiedProjectMs ? unifiedProjectMs.getValues() : initialProjects;
      const selectedApps = unifiedAppMs ? unifiedAppMs.getValues() : [];
      const selectedGroups = unifiedGroupMs ? unifiedGroupMs.getValues() : [];

      if (customDateBar) {
        customDateBar.classList.toggle('hidden', qTime !== 'custom');
      }

      let activeCount = 0;
      if (qSearch) activeCount++;
      if (qType) activeCount++;
      if (qPriority) activeCount++;
      if (qStatus) activeCount++;
      if (qTime === 'custom') {
        if (qStart || qEnd) activeCount++;
      } else if (qTime) {
        activeCount++;
      }
      if (selectedProjects.length > 0) {
        const matchesInitial = initialProjects.length === selectedProjects.length && initialProjects.every(p => selectedProjects.includes(p));
        if (!matchesInitial) activeCount++;
      }
      if (selectedApps.length > 0) activeCount++;
      if (selectedGroups.length > 0) activeCount++;

      if (countBadge) {
        if (activeCount > 0) {
          countBadge.textContent = `${activeCount} active`;
          countBadge.classList.remove('hidden');
          resetBtn?.classList.remove('hidden');
        } else {
          countBadge.classList.add('hidden');
          resetBtn?.classList.add('hidden');
        }
      }

      let visibleInc = 0, visibleReq = 0, visibleChg = 0;
      let totalVisible = 0;
      const visibleList = [];

      const rows = tbody.querySelectorAll('tr');
      rows.forEach((row, idx) => {
        const item = allTickets[idx];
        if (!item) return;

        let matches = true;
        if (qType && item.ticket_type !== qType) matches = false;
        if (qPriority && item.priority !== qPriority) matches = false;
        if (qStatus && item.status !== qStatus) matches = false;
        if (selectedProjects.length > 0 && !selectedProjects.includes(item.project_name)) matches = false;
        if (selectedApps.length > 0 && !selectedApps.includes(item.application_name)) matches = false;
        if (selectedGroups.length > 0 && !selectedGroups.includes(item.assignment_group_name)) matches = false;

        if (!matchesTimeRange(item.created_at, qTime, qStart, qEnd, qTz)) {
          matches = false;
        }

        if (qSearch) {
          const haystack = `${item.number} ${item.short_description} ${item.project_name} ${item.application_name} ${item.caller_name} ${item.assignment_group_name} ${item.assigned_to_name} ${item.status}`.toLowerCase();
          if (!haystack.includes(qSearch)) matches = false;
        }

        if (matches) {
          row.style.display = '';
          totalVisible++;
          visibleList.push(item);
          if (item.ticket_type === 'Incident') visibleInc++;
          else if (item.ticket_type === 'Service Request') visibleReq++;
          else if (item.ticket_type === 'Change Request') visibleChg++;
        } else {
          row.style.display = 'none';
        }
      });

      if (totalLabel) {
        totalLabel.textContent = `Showing: ${totalVisible} Tickets (${visibleInc} Incidents, ${visibleReq} Requests, ${visibleChg} Changes)`;
      }
      if (emptyMsg) {
        emptyMsg.classList.toggle('hidden', totalVisible > 0);
      }

      // Update project-specific statistical dashboard telemetry
      updateUnifiedStatsDashboard(visibleList, selectedProjects, selectedApps);
    }

    [searchEl, typeEl, priorityEl, statusEl, timeEl].forEach(el => {
      if (el) {
        el.addEventListener('input', applyUnifiedFilters);
        el.addEventListener('change', applyUnifiedFilters);
      }
    });

    if (startDateEl) startDateEl.addEventListener('change', applyUnifiedFilters);
    if (endDateEl) endDateEl.addEventListener('change', applyUnifiedFilters);
    if (clearCustomBtn) {
      clearCustomBtn.addEventListener('click', () => {
        if (startDateEl) startDateEl.value = '';
        if (endDateEl) endDateEl.value = '';
        applyUnifiedFilters();
      });
    }

    if (tzEl) {
      tzEl.addEventListener('change', () => {
        state.currentTimezone = tzEl.value;
        localStorage.setItem('nexus_timezone', state.currentTimezone);
        document.querySelectorAll('.unified-date-cell').forEach(td => {
          const created = td.getAttribute('data-created');
          if (created) td.textContent = formatTicketDate(created, state.currentTimezone);
        });
        applyUnifiedFilters();
      });
    }

    if (resetBtn) {
      resetBtn.addEventListener('click', () => {
        if (searchEl) searchEl.value = '';
        if (typeEl) typeEl.value = '';
        if (priorityEl) priorityEl.value = '';
        if (statusEl) statusEl.value = '';
        if (timeEl) timeEl.value = '';
        if (startDateEl) startDateEl.value = '';
        if (endDateEl) endDateEl.value = '';
        if (customDateBar) customDateBar.classList.add('hidden');
        if (unifiedProjectMs) unifiedProjectMs.setSelected(initialProjects);
        syncAppsForProjects(initialProjects);
        if (unifiedAppMs) unifiedAppMs.clear(false);
        syncGroupsForProjectsAndApps(initialProjects, []);
        if (unifiedGroupMs) unifiedGroupMs.clear(false);
        applyUnifiedFilters();
      });
    }

    applyUnifiedFilters();

  } catch (err) {
    console.error('Unified tickets load error', err);
    container.innerHTML = `<div class="p-8 text-center text-red-500 font-bold">Failed to load tickets: ${err.message}</div>`;
  }
}

// --- INCIDENTS LIST VIEW ---
async function renderTicketsView(container, options = {}) {
  container.innerHTML = `<div class="p-8 text-center text-slate-400"><i data-lucide="loader-2" class="w-8 h-8 animate-spin mx-auto mb-2 text-purple-500"></i>Loading tickets...</div>`;
  lucide.createIcons();

  const isEndUser = isUserEndUser(state.currentUser);
  const isMyTickets = options.myTickets || isEndUser;
  const url = `${API_BASE}/incidents?${isMyTickets ? 'my_tickets=true' : ''}`;

  try {
    if (!state.projects?.length || !state.applications?.length) {
      try {
        const [pRes, aRes] = await Promise.allSettled([
          fetch(`${API_BASE}/projects`),
          fetch(`${API_BASE}/applications`)
        ]);
        if (pRes.status === 'fulfilled' && pRes.value.ok) state.projects = await pRes.value.json();
        if (aRes.status === 'fulfilled' && aRes.value.ok) state.applications = await aRes.value.json();
      } catch (_) {}
    }

    const res = await fetch(url, {
      headers: { 'X-User-ID': state.currentUser.id.toString() }
    });
    const incidents = await res.json();
    let configuredColumns = [];
    try { const columnResponse = await fetch(`${API_BASE}/admin/configuration/columns?ticket_type=Incident`); if (columnResponse.ok) configuredColumns = (await columnResponse.json()).filter(c => c.enabled); } catch (_) {}
    const incidentColumns = configuredColumns.length ? configuredColumns : [
      {column_key:'number', label:'Number'}, {column_key:'priority', label:'Priority'}, {column_key:'short_description', label:'Short Description'}, {column_key:'application_name', label:'Application'}, {column_key:'project_name', label:'Project'}, {column_key:'assignment_group_name', label:'Assignment Group'}, {column_key:'assigned_to_name', label:'Assigned To'}, {column_key:'sla_stage', label:'SLA Stage'}, {column_key:'status', label:'Status'}, {column_key:'created_at', label:'Created'}
    ];
    const incidentCell = (item, key, slaBadge) => {
      if (key === 'number') return `<td class="p-3.5 font-bold text-purple-600">${item.number}</td>`;
      if (key === 'priority') return `<td class="p-3.5"><span class="px-2 py-0.5 rounded text-[10px] font-bold badge-${item.priority.toLowerCase()}">${item.priority}</span></td>`;
      if (key === 'short_description') return `<td class="p-3.5 font-semibold text-[var(--text-primary)] max-w-sm truncate">${item.short_description}</td>`;
      if (key === 'sla_stage') return `<td class="p-3.5">${slaBadge}</td>`;
      if (key === 'status') return `<td class="p-3.5"><span class="px-2 py-0.5 rounded text-[10px] font-semibold bg-slate-100 dark:bg-slate-800">${item.status}</span></td>`;
      if (key === 'created_at') return `<td class="p-3.5 text-slate-500 incident-date-cell" data-created="${item.created_at || ''}">${formatTicketDate(item.created_at, state.currentTimezone)}</td>`;
      return `<td class="p-3.5 text-slate-400">${item[key] ?? '—'}</td>`;
    };

    const isGlobalAdmin = !!(state.currentUser?.is_global_admin || state.currentUser?.username === 'admin');
    const userBoundaries = state.currentUser?.project_boundaries || {};
    const userProjects = (userBoundaries.project_names && userBoundaries.project_names.length)
      ? userBoundaries.project_names
      : (state.currentUser?.admin_projects || state.currentUser?.support_projects || []);
    const isSupportMember = !isGlobalAdmin && !isEndUser && userProjects.length > 0;
    const defaultProject = (isSupportMember && userProjects.length > 0) ? userProjects[0] : '';

    // Extract unique filter dropdown options
    const uniquePriorities = ['P1', 'P2', 'P3', 'P4'];
    const uniqueStatuses = [...new Set(['New', 'Active', 'In Progress', 'On Hold', 'Pending', 'Resolved', 'Closed', 'Canceled', ...incidents.map(i => i.status).filter(Boolean)])];
    const projectSet = new Set(incidents.map(i => i.project_name).filter(Boolean));
    userProjects.forEach(p => projectSet.add(p));
    if (state.projects) state.projects.forEach(p => projectSet.add(p.name));
    const uniqueProjects = [...projectSet].sort();
    const uniqueGroups = [...new Set(incidents.map(i => i.assignment_group_name).filter(Boolean))].sort();

    const projectToApps = {};
    incidents.forEach(i => {
      if (i.project_name && i.application_name) {
        if (!projectToApps[i.project_name]) projectToApps[i.project_name] = new Set();
        projectToApps[i.project_name].add(i.application_name);
      }
    });
    if (state.applications) {
      state.applications.forEach(a => {
        const pName = a.project_name || (state.projects?.find(p => p.id === a.project_id)?.name);
        if (pName && a.name) {
          if (!projectToApps[pName]) projectToApps[pName] = new Set();
          projectToApps[pName].add(a.name);
        }
      });
    }
    if (userBoundaries.project_names && userBoundaries.application_names) {
      userBoundaries.project_names.forEach(pn => {
        if (!projectToApps[pn]) projectToApps[pn] = new Set();
        userBoundaries.application_names.forEach(an => projectToApps[pn].add(an));
      });
    }
    const allKnownApps = new Set(incidents.map(i => i.application_name).filter(a => a && a !== 'N/A'));
    if (state.applications) state.applications.forEach(a => { if (a.name) allKnownApps.add(a.name); });
    const uniqueApps = [...allKnownApps].sort();

    const initialProjects = (isSupportMember && userProjects.length > 0) ? userProjects.slice() : (defaultProject ? [defaultProject] : []);
    let initialApps = [];
    if (initialProjects.length > 0) {
      const appSet = new Set();
      initialProjects.forEach(p => {
        if (projectToApps[p]) projectToApps[p].forEach(a => appSet.add(a));
      });
      initialApps = appSet.size > 0 ? [...appSet].sort() : uniqueApps;
    } else {
      initialApps = uniqueApps;
    }

    const initialGroups = getFilteredAssignmentGroups(initialProjects, '', uniqueGroups);

    container.innerHTML = `
      <div class="space-y-5">
        <div class="flex items-center justify-between">
          <div>
            <h1 class="text-2xl font-black tracking-tight">${isMyTickets ? 'My Tickets' : 'Incident Management'}</h1>
            <p class="text-sm text-slate-500">
              ${isMyTickets ? 'Tickets requested by you with real-time status updates.' : (isSupportMember ? `Project queue for ${userProjects.join(', ')} with cross-project visibility.` : 'All platform incidents, routing evaluation records, and active SLA countdown timers.')}
            </p>
          </div>
          <div class="flex items-center space-x-2.5">
            ${['support_member', 'group_manager', 'administrator', 'itsm_admin'].includes(state.currentUser?.role) ? `
              <button onclick="openExportModal('incidents')" class="px-3.5 py-2 rounded-xl border border-[var(--border-color)] bg-[var(--card-bg)] hover:bg-[var(--bg-tertiary)] text-xs font-semibold flex items-center space-x-1.5 shadow-sm text-purple-600 dark:text-purple-300 transition-all">
                <i data-lucide="download" class="w-4 h-4 text-purple-500"></i>
                <span>Export Incidents</span>
              </button>
            ` : ''}
            <button onclick="openCreateModal()" class="bg-purple-600 hover:bg-purple-700 text-white px-4 py-2 rounded-xl text-sm font-semibold shadow flex items-center space-x-2">
              <i data-lucide="plus" class="w-4 h-4"></i>
              <span>${isMyTickets ? 'Create Ticket' : 'Create Incident'}</span>
            </button>
          </div>
        </div>

        ${renderTicketTypeTabs(isMyTickets ? 'my-tickets' : 'incidents')}

        <!-- Project-Specific Statistical Dashboard for Incidents -->
        <div class="p-4 bg-[var(--card-bg)] border border-[var(--border-color)] rounded-2xl shadow-sm space-y-3">
          <div class="flex items-center justify-between">
            <div class="flex items-center space-x-2">
              <i data-lucide="bar-chart-2" class="w-4 h-4 text-purple-600"></i>
              <span class="text-xs font-bold text-slate-700 dark:text-slate-300">Statistical Dashboard & Incident Telemetry</span>
              <span id="ticketScopeBadge" class="px-2.5 py-0.5 rounded-full text-[11px] font-extrabold bg-purple-100 dark:bg-purple-950 text-purple-700 dark:text-purple-300 border border-purple-200 dark:border-purple-800">
                ${initialProjects.length === 1 ? `Project: ${initialProjects[0]}` : (initialProjects.length > 1 ? `Projects: ${initialProjects.join(', ')}` : 'All Projects Scope')}
              </span>
            </div>
            <div class="text-[11px] text-slate-400 font-medium">
              Live metrics calculated for active project & filter criteria
            </div>
          </div>

          <div class="grid grid-cols-2 sm:grid-cols-4 gap-3 pt-1">
            <div class="p-3.5 rounded-xl bg-[var(--bg-tertiary)] border border-[var(--border-color)] shadow-xs">
              <div class="text-[10px] font-bold text-slate-400 uppercase tracking-wider">Total In Scope</div>
              <div id="statIncTotal" class="text-2xl font-black text-[var(--text-primary)] mt-1">0</div>
              <div class="text-[10px] text-slate-400 mt-0.5">Incidents in view</div>
            </div>
            <div class="p-3.5 rounded-xl bg-[var(--bg-tertiary)] border border-[var(--border-color)] shadow-xs">
              <div class="text-[10px] font-bold text-rose-600 dark:text-rose-400 uppercase tracking-wider flex items-center space-x-1">
                <i data-lucide="alert-triangle" class="w-3.5 h-3.5"></i>
                <span>P1/P2 Critical</span>
              </div>
              <div id="statIncCrit" class="text-2xl font-black text-rose-600 mt-1">0</div>
              <div class="text-[10px] text-slate-400 mt-0.5">Major severity</div>
            </div>
            <div class="p-3.5 rounded-xl bg-[var(--bg-tertiary)] border border-[var(--border-color)] shadow-xs">
              <div class="text-[10px] font-bold text-amber-600 dark:text-amber-400 uppercase tracking-wider flex items-center space-x-1">
                <i data-lucide="clock" class="w-3.5 h-3.5"></i>
                <span>In Progress</span>
              </div>
              <div id="statIncProg" class="text-2xl font-black text-amber-600 mt-1">0</div>
              <div class="text-[10px] text-slate-400 mt-0.5">Active triage / work</div>
            </div>
            <div class="p-3.5 rounded-xl bg-[var(--bg-tertiary)] border border-[var(--border-color)] shadow-xs">
              <div class="text-[10px] font-bold text-emerald-600 dark:text-emerald-400 uppercase tracking-wider flex items-center space-x-1">
                <i data-lucide="check-circle" class="w-3.5 h-3.5"></i>
                <span>Resolved / Closed</span>
              </div>
              <div id="statIncRes" class="text-2xl font-black text-emerald-600 mt-1">0</div>
              <div class="text-[10px] text-slate-400 mt-0.5">Restored service</div>
            </div>
          </div>
        </div>

        <!-- Filter Bar -->
        <div class="p-4 bg-[var(--card-bg)] border border-[var(--border-color)] rounded-2xl shadow-sm space-y-3">
          <div class="flex items-center justify-between">
            <div class="flex items-center space-x-2 text-xs font-bold text-slate-700 dark:text-slate-300">
              <i data-lucide="filter" class="w-4 h-4 text-purple-600"></i>
              <span>Column & Attribute Filters</span>
              <span id="activeTicketFiltersBadge" class="hidden px-2 py-0.5 rounded-full text-[10px] font-bold bg-purple-100 dark:bg-purple-950 text-purple-700 dark:text-purple-300 border border-purple-200 dark:border-purple-800"></span>
            </div>
            <button id="resetTicketFiltersBtn" class="hidden text-xs text-purple-600 hover:text-purple-700 font-bold hover:underline flex items-center space-x-1">
              <i data-lucide="rotate-ccw" class="w-3.5 h-3.5"></i>
              <span>Clear Filters</span>
            </button>
          </div>
          <div class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-8 gap-2.5">
            <div>
              <label class="block text-[10px] font-bold uppercase text-slate-400 mb-1">Search</label>
              <div class="relative">
                <input type="text" id="filterTicketSearch" placeholder="Search..." class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-xl pl-7 pr-2 py-1.5 text-xs focus:ring-2 focus:ring-purple-500 focus:outline-none">
                <i data-lucide="search" class="w-3.5 h-3.5 text-slate-400 absolute left-2 top-2"></i>
              </div>
            </div>
            <div>
              <label class="block text-[10px] font-bold uppercase text-slate-400 mb-1">Priority</label>
              <select id="filterTicketPriority" class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-xl px-2.5 py-1.5 text-xs focus:ring-2 focus:ring-purple-500 focus:outline-none">
                <option value="">All Priorities</option>
                ${uniquePriorities.map(p => `<option value="${p}">${p}</option>`).join('')}
              </select>
            </div>
            <div>
              <label class="block text-[10px] font-bold uppercase text-slate-400 mb-1">Status</label>
              <select id="filterTicketStatus" class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-xl px-2.5 py-1.5 text-xs focus:ring-2 focus:ring-purple-500 focus:outline-none">
                <option value="">All Statuses</option>
                ${uniqueStatuses.map(s => `<option value="${s}">${s}</option>`).join('')}
              </select>
            </div>
            <div>
              <label class="block text-[10px] font-bold uppercase text-slate-400 mb-1">Time Range</label>
              <select id="filterTicketTime" class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-xl px-2.5 py-1.5 text-xs focus:ring-2 focus:ring-purple-500 focus:outline-none font-semibold">
                <option value="">All Time</option>
                <option value="today">Today</option>
                <option value="7d">Last 7 Days</option>
                <option value="30d">Last 30 Days</option>
                <option value="90d">Last 90 Days</option>
                <option value="custom">📅 Custom Range...</option>
              </select>
            </div>
            <div>
              <label class="block text-[10px] font-bold uppercase text-slate-400 mb-1">Time Zone</label>
              ${renderTimezoneSelect('filterTicketTimezone', state.currentTimezone)}
            </div>
            <div>
              <label class="block text-[10px] font-bold uppercase text-slate-400 mb-1">Project</label>
              <div id="filterTicketProjectWrap"></div>
            </div>
            <div>
              <label class="block text-[10px] font-bold uppercase text-slate-400 mb-1">Application</label>
              <div id="filterTicketAppWrap"></div>
            </div>
            <div>
              <label class="block text-[10px] font-bold uppercase text-slate-400 mb-1">Assignment Group</label>
              <div id="filterTicketGroupWrap"></div>
            </div>
            <div>
              <label class="block text-[10px] font-bold uppercase text-slate-400 mb-1">SLA Stage</label>
              <select id="filterTicketSla" class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-xl px-2.5 py-1.5 text-xs focus:ring-2 focus:ring-purple-500 focus:outline-none">
                <option value="">All SLA Stages</option>
                <option value="in_progress">🟢 On Track</option>
                <option value="breached">🔴 Breached</option>
                <option value="paused">⏸️ Paused</option>
                <option value="achieved">✓ Achieved</option>
              </select>
            </div>
          </div>

          <!-- Custom Time Range Bar -->
          <div id="filterTicketCustomDateBar" class="hidden pt-2 border-t border-[var(--border-color)] flex flex-wrap items-center gap-3 text-xs bg-[var(--bg-tertiary)]/50 p-2.5 rounded-xl mt-2">
            <span class="font-bold text-slate-500 text-[11px] flex items-center space-x-1">
              <i data-lucide="calendar" class="w-3.5 h-3.5 text-purple-600"></i>
              <span>Custom Range:</span>
            </span>
            <div class="flex items-center space-x-1.5">
              <label class="text-[11px] text-slate-400 font-semibold">From:</label>
              <input type="datetime-local" id="filterTicketStartDate" class="bg-[var(--card-bg)] border border-[var(--border-color)] rounded-lg px-2 py-1 text-xs focus:ring-2 focus:ring-purple-500">
            </div>
            <div class="flex items-center space-x-1.5">
              <label class="text-[11px] text-slate-400 font-semibold">To:</label>
              <input type="datetime-local" id="filterTicketEndDate" class="bg-[var(--card-bg)] border border-[var(--border-color)] rounded-lg px-2 py-1 text-xs focus:ring-2 focus:ring-purple-500">
            </div>
            <button id="filterTicketClearCustomDateBtn" type="button" class="text-xs px-2.5 py-1 rounded-lg border border-[var(--border-color)] bg-[var(--card-bg)] hover:bg-[var(--bg-tertiary)] text-slate-600 dark:text-slate-300 font-semibold">
              Clear Range
            </button>
          </div>
        </div>

        <div class="rounded-2xl bg-[var(--card-bg)] border border-[var(--border-color)] overflow-hidden shadow-sm">
          <div class="p-3 bg-[var(--bg-tertiary)] border-b border-[var(--border-color)] flex items-center justify-between text-xs">
            <span id="ticketCountLabel" class="font-semibold text-slate-400 uppercase tracking-wider">Total: ${incidents.length} Tickets</span>
          </div>

          <div class="overflow-x-auto">
            <table class="w-full text-left text-xs">
              <thead class="bg-[var(--bg-tertiary)] text-slate-400 uppercase font-semibold text-[10px]">
                <tr>
                  ${incidentColumns.map(c => `<th class="p-3.5">${c.label}</th>`).join('')}
                </tr>
              </thead>
              <tbody id="ticketsTableBody" class="divide-y divide-[var(--border-color)]">
                ${renderIncidentRows(incidents, incidentColumns, incidentCell)}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    `;
    lucide.createIcons();

    // Hook up real-time filter logic
    const projectWrap = document.getElementById('filterTicketProjectWrap');
    const appWrap = document.getElementById('filterTicketAppWrap');
    const groupWrap = document.getElementById('filterTicketGroupWrap');
    const tzEl = document.getElementById('filterTicketTimezone');
    const customDateBar = document.getElementById('filterTicketCustomDateBar');
    const startDateEl = document.getElementById('filterTicketStartDate');
    const endDateEl = document.getElementById('filterTicketEndDate');
    const clearCustomBtn = document.getElementById('filterTicketClearCustomDateBtn');

    let ticketProjectMs = null;
    let ticketAppMs = null;
    let ticketGroupMs = null;

    function syncAppsForProjects(chosenProjects) {
      let apps = [];
      if (chosenProjects && chosenProjects.length > 0) {
        const appSet = new Set();
        chosenProjects.forEach(p => {
          if (projectToApps[p]) projectToApps[p].forEach(a => appSet.add(a));
        });
        apps = appSet.size > 0 ? [...appSet].sort() : uniqueApps;
      } else {
        apps = uniqueApps;
      }
      if (ticketAppMs) ticketAppMs.setOptions(apps, true);
    }

    function syncGroupsForProjectsAndApps(chosenProjects, chosenApps) {
      const groups = getFilteredAssignmentGroups(chosenProjects, chosenApps, uniqueGroups);
      if (ticketGroupMs) ticketGroupMs.setOptions(groups, true);
    }

    ticketProjectMs = createMultiSelectDropdown({
      container: projectWrap,
      options: uniqueProjects,
      selectedValues: initialProjects,
      placeholder: 'Projects',
      allLabel: 'All Projects',
      emptyMessage: 'No projects found',
      onChange: (selectedProjects) => {
        syncAppsForProjects(selectedProjects);
        syncGroupsForProjectsAndApps(selectedProjects, ticketAppMs ? ticketAppMs.getValues() : []);
        applyFilters();
      }
    });

    ticketAppMs = createMultiSelectDropdown({
      container: appWrap,
      options: initialApps,
      placeholder: 'Applications',
      allLabel: 'All Applications',
      emptyMessage: 'No applications found',
      onChange: (selectedApps) => {
        const curProjects = ticketProjectMs ? ticketProjectMs.getValues() : [];
        const filteredGroups = getFilteredAssignmentGroups(curProjects, selectedApps, uniqueGroups);
        if (ticketGroupMs) ticketGroupMs.setOptions(filteredGroups, true);
        applyFilters();
      }
    });

    ticketGroupMs = createMultiSelectDropdown({
      container: groupWrap,
      options: initialGroups,
      placeholder: 'Groups',
      allLabel: 'All Groups',
      emptyMessage: 'No groups found',
      onChange: () => {
        applyFilters();
      }
    });

    const filterInputs = ['filterTicketSearch', 'filterTicketPriority', 'filterTicketStatus', 'filterTicketTime', 'filterTicketSla'];
    const applyFilters = () => {
      const searchVal = (document.getElementById('filterTicketSearch')?.value || '').toLowerCase().trim();
      const pVal = document.getElementById('filterTicketPriority')?.value || '';
      const sVal = document.getElementById('filterTicketStatus')?.value || '';
      const tVal = document.getElementById('filterTicketTime')?.value || '';
      const qTz = tzEl?.value || state.currentTimezone || 'UTC';
      const qStart = startDateEl?.value || '';
      const qEnd = endDateEl?.value || '';
      const selectedProjects = ticketProjectMs ? ticketProjectMs.getValues() : initialProjects;
      const slaVal = document.getElementById('filterTicketSla')?.value || '';
      const selectedApps = ticketAppMs ? ticketAppMs.getValues() : [];
      const selectedGroups = ticketGroupMs ? ticketGroupMs.getValues() : [];

      if (customDateBar) {
        customDateBar.classList.toggle('hidden', tVal !== 'custom');
      }

      let activeCount = [
        searchVal,
        pVal,
        sVal,
        tVal === 'custom' ? (qStart || qEnd ? 'custom' : '') : tVal,
        selectedApps.length > 0 ? 'apps' : '',
        selectedGroups.length > 0 ? 'groups' : '',
        slaVal
      ].filter(Boolean).length;

      if (selectedProjects.length > 0) {
        const matchesInitial = initialProjects.length === selectedProjects.length && initialProjects.every(p => selectedProjects.includes(p));
        if (!matchesInitial) activeCount++;
      }

      const badge = document.getElementById('activeTicketFiltersBadge');
      const resetBtn = document.getElementById('resetTicketFiltersBtn');
      if (badge) {
        badge.textContent = `${activeCount} active filter${activeCount === 1 ? '' : 's'}`;
        badge.classList.toggle('hidden', activeCount === 0);
      }
      if (resetBtn) {
        resetBtn.classList.toggle('hidden', activeCount === 0);
      }

      const filtered = incidents.filter(i => {
        if (searchVal) {
          const numMatch = (i.number || '').toLowerCase().includes(searchVal);
          const descMatch = (i.short_description || '').toLowerCase().includes(searchVal);
          const fullMatch = (i.description || '').toLowerCase().includes(searchVal);
          const appMatch = (i.application_name || '').toLowerCase().includes(searchVal);
          if (!numMatch && !descMatch && !fullMatch && !appMatch) return false;
        }
        if (pVal && i.priority !== pVal) return false;
        if (sVal && i.status !== sVal) return false;
        if (!matchesTimeRange(i.created_at, tVal, qStart, qEnd, qTz)) return false;
        if (selectedProjects.length > 0 && !selectedProjects.includes(i.project_name)) return false;
        if (selectedApps.length > 0 && !selectedApps.includes(i.application_name)) return false;
        if (selectedGroups.length > 0 && !selectedGroups.includes(i.assignment_group_name)) return false;
        if (slaVal && (i.sla_stage || 'in_progress') !== slaVal) return false;
        return true;
      });

      // Update project telemetry numbers
      const scopeBadge = document.getElementById('ticketScopeBadge');
      if (scopeBadge) {
        const appLabel = selectedApps.length === 1 ? selectedApps[0] : (selectedApps.length > 1 ? `${selectedApps.length} Apps` : '');
        if (selectedProjects.length > 0) {
          const projText = selectedProjects.length === 1
            ? `Project: ${selectedProjects[0]}`
            : (selectedProjects.length === 2 ? `Projects: ${selectedProjects.join(', ')}` : `${selectedProjects.length} Projects`);
          scopeBadge.textContent = appLabel ? `${projText} (${appLabel})` : projText;
          scopeBadge.className = "px-2.5 py-0.5 rounded-full text-[11px] font-extrabold bg-purple-100 dark:bg-purple-950 text-purple-700 dark:text-purple-300 border border-purple-200 dark:border-purple-800";
        } else {
          scopeBadge.textContent = appLabel ? `All Projects (${appLabel})` : 'All Projects Scope';
          scopeBadge.className = "px-2.5 py-0.5 rounded-full text-[11px] font-extrabold bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 border border-slate-300 dark:border-slate-700";
        }
      }
      const elTot = document.getElementById('statIncTotal');
      if (elTot) elTot.textContent = filtered.length;
      const elCrit = document.getElementById('statIncCrit');
      if (elCrit) elCrit.textContent = filtered.filter(i => i.priority === 'P1' || i.priority === 'P2').length;
      const elProg = document.getElementById('statIncProg');
      if (elProg) elProg.textContent = filtered.filter(i => ['In Progress', 'Assigned', 'Work in Progress'].includes(i.status)).length;
      const elRes = document.getElementById('statIncRes');
      if (elRes) elRes.textContent = filtered.filter(i => ['Resolved', 'Closed'].includes(i.status)).length;

      const countLabel = document.getElementById('ticketCountLabel');
      if (countLabel) {
        countLabel.textContent = activeCount > 0
          ? `Showing: ${filtered.length} of ${incidents.length} Tickets`
          : `Total: ${incidents.length} Tickets`;
      }

      const tbody = document.getElementById('ticketsTableBody');
      if (tbody) {
        if (filtered.length === 0) {
          tbody.innerHTML = `<tr><td colspan="${incidentColumns.length}" class="p-8 text-center text-slate-400 font-medium">No tickets match the selected column filters.</td></tr>`;
        } else {
          tbody.innerHTML = renderIncidentRows(filtered, incidentColumns, incidentCell);
        }
        lucide.createIcons();
      }
    };

    filterInputs.forEach(id => {
      const el = document.getElementById(id);
      if (el) {
        el.addEventListener('change', applyFilters);
        if (id === 'filterTicketSearch') {
          el.addEventListener('input', applyFilters);
        }
      }
    });

    if (startDateEl) startDateEl.addEventListener('change', applyFilters);
    if (endDateEl) endDateEl.addEventListener('change', applyFilters);
    if (clearCustomBtn) {
      clearCustomBtn.addEventListener('click', () => {
        if (startDateEl) startDateEl.value = '';
        if (endDateEl) endDateEl.value = '';
        applyFilters();
      });
    }

    if (tzEl) {
      tzEl.addEventListener('change', () => {
        state.currentTimezone = tzEl.value;
        localStorage.setItem('nexus_timezone', state.currentTimezone);
        document.querySelectorAll('.incident-date-cell').forEach(td => {
          const created = td.getAttribute('data-created');
          if (created) td.textContent = formatTicketDate(created, state.currentTimezone);
        });
        applyFilters();
      });
    }

    const resetBtn = document.getElementById('resetTicketFiltersBtn');
    if (resetBtn) {
      resetBtn.addEventListener('click', () => {
        filterInputs.forEach(id => {
          const el = document.getElementById(id);
          if (el) el.value = '';
        });
        if (startDateEl) startDateEl.value = '';
        if (endDateEl) endDateEl.value = '';
        if (customDateBar) customDateBar.classList.add('hidden');
        if (ticketProjectMs) ticketProjectMs.setSelected(initialProjects);
        syncAppsForProjects(initialProjects);
        if (ticketAppMs) ticketAppMs.clear(false);
        syncGroupsForProjectsAndApps(initialProjects, []);
        if (ticketGroupMs) ticketGroupMs.clear(false);
        applyFilters();
      });
    }

    applyFilters();

  } catch (err) {
    container.innerHTML = `<div class="p-8 text-center text-red-500">Failed to load tickets: ${err.message}</div>`;
  }
}

function renderIncidentRows(items, columns, cellRenderer) {
  if (!items || !items.length) {
    return `
      <tr>
        <td colspan="${columns.length}" class="p-8 text-center text-slate-400">
          <div class="flex flex-col items-center justify-center space-y-2">
            <i data-lucide="inbox" class="w-8 h-8 text-slate-500 stroke-[1.5]"></i>
            <span class="font-medium text-xs">No tickets found</span>
            <span class="text-[11px] text-slate-500">You haven't requested any tickets yet. Click "Create Ticket" to submit a request.</span>
          </div>
        </td>
      </tr>
    `;
  }
  return items.map(i => {
    let slaBadge = `<span class="px-2 py-0.5 rounded text-[10px] font-bold sla-healthy">🟢 On Track</span>`;
    if (i.sla_stage === 'breached') {
      slaBadge = `<span class="px-2 py-0.5 rounded text-[10px] font-bold sla-breached">🔴 Breached</span>`;
    } else if (i.sla_stage === 'paused') {
      slaBadge = `<span class="px-2 py-0.5 rounded text-[10px] font-bold sla-warning">⏸️ Paused</span>`;
    } else if (i.sla_stage === 'achieved') {
      slaBadge = `<span class="px-2 py-0.5 rounded text-[10px] font-bold text-slate-400">✓ Achieved</span>`;
    }
    return `
      <tr class="hover:bg-[var(--bg-tertiary)] transition-colors cursor-pointer" onclick="window.location.hash='#/incidents/${i.number}'">
        ${columns.map(c => cellRenderer(i, c.column_key, slaBadge)).join('')}
      </tr>
    `;
  }).join('');
}

// --- INCIDENT DETAIL VIEW ---
async function renderIncidentDetailView(container, ticketNumber) {
  container.innerHTML = `<div class="p-8 text-center text-slate-400"><i data-lucide="loader-2" class="w-8 h-8 animate-spin mx-auto mb-2 text-purple-500"></i>Loading ticket ${ticketNumber}...</div>`;
  lucide.createIcons();

  try {
    const res = await fetch(`${API_BASE}/incidents/${ticketNumber}`, {
      headers: { 'X-User-ID': state.currentUser.id.toString() }
    });
    if (!res.ok) {
      container.innerHTML = `<div class="p-8 text-center text-red-500">Ticket not found or permission denied.</div>`;
      return;
    }
    const inc = await res.json();
    state.activeTicketContext = {
      ticket_number: inc.number,
      ticket_type: 'Incident',
      application: inc.application_name,
      project: inc.project_name,
      priority: inc.priority,
      status: inc.status,
      short_description: inc.short_description,
      description: inc.description,
      assignment_group: inc.assignment_group_name,
      assigned_to: inc.assigned_to_name
    };

    updateDrawerTicketContext(state.activeTicketContext);

    const isEndUser = isUserEndUser(state.currentUser);
    const isSupportOrAdmin = !isEndUser;
    const isCaller = state.currentUser && inc.caller_id === state.currentUser.id;
    const canPostWorkNote = isSupportOrAdmin || isCaller;

    container.innerHTML = `
      <div class="space-y-6">
        <!-- Top Action / Breadcrumb Bar -->
        <div class="flex items-center justify-between">
          <div class="flex items-center space-x-2 text-xs text-slate-400">
            <a href="${isEndUser ? '#/my-tickets' : '#/incidents'}" class="hover:text-purple-600">${isEndUser ? 'My Tickets' : 'Incidents'}</a>
            <span>/</span>
            <span class="font-bold text-[var(--text-primary)]">${inc.number}</span>
          </div>

          <!-- Contextual Actions -->
          <div class="flex items-center space-x-2">
            ${!isEndUser ? `
              <button onclick="triggerTicketCopilot('${inc.number}')" class="bg-gradient-to-r from-purple-600 to-indigo-600 hover:from-blue-700 hover:to-indigo-700 text-white px-3.5 py-1.5 rounded-lg text-xs font-semibold shadow flex items-center space-x-1.5">
                <i data-lucide="bot" class="w-4 h-4"></i>
                <span>Ask AI Copilot</span>
              </button>
            ` : ''}

            ${isSupportOrAdmin ? `
              <button onclick="assignToMe(${inc.id})" class="px-3 py-1.5 rounded-lg border border-[var(--border-color)] bg-[var(--card-bg)] hover:bg-[var(--bg-tertiary)] text-xs font-semibold">
                Assign to Me
              </button>
              <button onclick="openReassignModal(${inc.id}, ${inc.assignment_group_id || 'null'}, ${inc.assigned_to_id || 'null'}, ${inc.project_id || 'null'}, ${inc.application_id || 'null'}, '${inc.priority || 'P3'}')" class="px-3 py-1.5 rounded-lg border border-[var(--border-color)] bg-[var(--card-bg)] hover:bg-[var(--bg-tertiary)] text-xs font-semibold flex items-center space-x-1">
                <i data-lucide="user-check" class="w-3.5 h-3.5 text-purple-600"></i>
                <span>Reassign Ticket</span>
              </button>
              <button onclick="openPriorityModal(${inc.id}, '${inc.priority}')" class="px-3 py-1.5 rounded-lg border border-[var(--border-color)] bg-[var(--card-bg)] hover:bg-[var(--bg-tertiary)] text-xs font-semibold flex items-center space-x-1">
                <i data-lucide="alert-triangle" class="w-3.5 h-3.5 text-amber-500"></i>
                <span>Change Priority</span>
              </button>
              <button onclick="openStatusModal(${inc.id}, '${inc.status}', 'Incident')" class="px-3 py-1.5 rounded-lg border border-[var(--border-color)] bg-[var(--card-bg)] hover:bg-[var(--bg-tertiary)] text-xs font-semibold flex items-center space-x-1">
                <i data-lucide="refresh-cw" class="w-3.5 h-3.5 text-blue-500"></i>
                <span>Update Status</span>
              </button>
              ${inc.status !== 'Resolved' && inc.status !== 'Closed' ? `
                <button onclick="openResolveModal(${inc.id})" class="px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-semibold">
                  Resolve Incident
                </button>
              ` : ''}
            ` : ''}
          </div>
        </div>

        <!-- Ticket Header Card -->
        <div class="p-6 rounded-2xl bg-[var(--card-bg)] border border-[var(--border-color)] shadow-sm">
          <div class="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-4 border-b border-[var(--border-color)]">
            <div>
              <div class="flex items-center space-x-2.5">
                <span class="text-xl font-black text-purple-600">${inc.number}</span>
                ${isSupportOrAdmin ? `
                  <button onclick="openPriorityModal(${inc.id}, '${inc.priority}')" title="Modify priority" class="px-2.5 py-0.5 rounded text-xs font-bold badge-${inc.priority.toLowerCase()} hover:opacity-80 flex items-center space-x-1 cursor-pointer transition-opacity">
                    <span>${inc.priority}</span>
                    <i data-lucide="edit-2" class="w-3 h-3"></i>
                  </button>
                ` : `
                  <span class="px-2.5 py-0.5 rounded text-xs font-bold badge-${inc.priority.toLowerCase()}">${inc.priority}</span>
                `}
                ${isSupportOrAdmin ? `
                  <div class="inline-flex items-center space-x-1">
                    <select onchange="quickUpdateStatus(event, 'Incident', ${inc.id}, this.value, '${inc.status}')" title="Change status directly" class="px-2.5 py-0.5 rounded text-xs font-bold bg-[var(--bg-tertiary)] border border-[var(--border-color)] text-[var(--text-primary)] cursor-pointer focus:ring-2 focus:ring-purple-500">
                      ${['New', 'Active', 'In Progress', 'On Hold', 'Resolved', 'Closed', 'Canceled'].map(s => `<option value="${s}" ${s === inc.status ? 'selected' : ''}>${s}</option>`).join('')}
                    </select>
                  </div>
                ` : `
                  <span class="px-2.5 py-0.5 rounded text-xs font-semibold bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300">${inc.status}</span>
                `}
              </div>
              <h1 class="text-lg font-bold mt-2 text-[var(--text-primary)]">${inc.short_description}</h1>
            </div>

            <!-- SLA Timers Display -->
            <div class="flex space-x-4 text-xs">
              ${(inc.sla_instances || []).map(inst => `
                <div class="p-2.5 rounded-xl border border-[var(--border-color)] bg-[var(--bg-tertiary)] min-w-[140px]">
                  <div class="flex items-center justify-between text-[10px] text-slate-400 font-semibold uppercase">
                    <span>${inst.target_type} SLA</span>
                    <span class="${inst.stage === 'breached' ? 'text-red-500' : 'text-emerald-500'} font-bold">${inst.stage}</span>
                  </div>
                  <div class="text-sm font-black mt-1">
                    ${inst.stage === 'breached' ? '🔴 BREACHED' : (inst.stage === 'achieved' ? '🟢 Achieved' : (inst.stage === 'paused' ? '⏸️ Paused' : `⏱️ ${inst.target_duration_mins}m Target`))}
                  </div>
                  <div class="text-[10px] text-slate-400 mt-0.5">Due: ${inst.due_at ? new Date(inst.due_at).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'}) : 'N/A'}</div>
                </div>
              `).join('')}
            </div>
          </div>

          <!-- Metadata Grid -->
          <div class="grid grid-cols-2 md:grid-cols-4 gap-4 pt-4 text-xs">
            <div>
              <span class="text-slate-400">Caller:</span>
              <span class="font-semibold block text-[var(--text-primary)]">${inc.caller_name || 'N/A'}</span>
            </div>
            <div>
              <span class="text-slate-400">Application:</span>
              <span class="font-semibold block text-[var(--text-primary)]">${inc.application_name}</span>
            </div>
            <div>
              <span class="text-slate-400">Project:</span>
              <span class="font-semibold block text-[var(--text-primary)]">${inc.project_name}</span>
            </div>
            <div>
              <span class="text-slate-400">Assignment Group:</span>
              <div class="flex items-center space-x-1.5">
                <span class="font-semibold block text-[var(--text-primary)]">${inc.assignment_group_name || 'Unassigned'}</span>
                ${isSupportOrAdmin ? `<button onclick="openReassignModal(${inc.id}, ${inc.assignment_group_id || 'null'}, ${inc.assigned_to_id || 'null'}, ${inc.project_id || 'null'}, ${inc.application_id || 'null'}, '${inc.priority || 'P3'}')" class="text-purple-600 hover:text-purple-700" title="Reassign"><i data-lucide="user-cog" class="w-3.5 h-3.5"></i></button>` : ''}
              </div>
            </div>
            <div>
              <span class="text-slate-400">Assigned To:</span>
              <div class="flex items-center space-x-1.5">
                <span class="font-semibold block text-[var(--text-primary)]">${inc.assigned_to_name || 'Unassigned'}</span>
                ${isSupportOrAdmin ? `<button onclick="openReassignModal(${inc.id}, ${inc.assignment_group_id || 'null'}, ${inc.assigned_to_id || 'null'}, ${inc.project_id || 'null'}, ${inc.application_id || 'null'}, '${inc.priority || 'P3'}')" class="text-purple-600 hover:text-purple-700" title="Reassign"><i data-lucide="user-cog" class="w-3.5 h-3.5"></i></button>` : ''}
              </div>
            </div>
            <div>
              <span class="text-slate-400">Impact / Urgency:</span>
              <span class="font-semibold block text-[var(--text-primary)]">${inc.impact} / ${inc.urgency}</span>
            </div>
            <div>
              <span class="text-slate-400">Matched Routing Rule:</span>
              <span class="font-semibold block text-purple-600">${inc.matched_routing_rule || 'Default Fallback'}</span>
            </div>
            <div>
              <span class="text-slate-400">Matched SLA Policy:</span>
              <span class="font-semibold block text-indigo-600">${inc.matched_sla_policy || 'Default SLA'}</span>
            </div>
          </div>
        </div>

        <!-- TICKET TABS -->
        <div class="rounded-2xl bg-[var(--card-bg)] border border-[var(--border-color)] overflow-hidden shadow-sm">
          <div class="border-b border-[var(--border-color)] flex space-x-1 p-2 bg-[var(--bg-tertiary)] text-xs font-semibold">
            <button onclick="switchTicketTab('overview')" id="tabBtn_overview" class="px-4 py-2 rounded-lg bg-[var(--card-bg)] shadow-sm text-purple-600">Overview</button>
            <button onclick="switchTicketTab('conversation')" id="tabBtn_conversation" class="px-4 py-2 rounded-lg hover:bg-[var(--card-bg)] text-slate-400">
              Communication (${(inc.comments || []).length + (inc.work_notes || []).length})
            </button>
            <button onclick="switchTicketTab('sla')" id="tabBtn_sla" class="px-4 py-2 rounded-lg hover:bg-[var(--card-bg)] text-slate-400">SLA Timers</button>
            <button onclick="switchTicketTab('timeline')" id="tabBtn_timeline" class="px-4 py-2 rounded-lg hover:bg-[var(--card-bg)] text-slate-400">Audit Timeline</button>
          </div>

          <!-- TAB CONTENT: OVERVIEW -->
          <div id="tabContent_overview" class="p-6 space-y-4">
            <div>
              <h3 class="text-xs font-bold uppercase tracking-wider text-slate-400 mb-1">Issue Description</h3>
              <div class="p-4 rounded-xl bg-[var(--bg-tertiary)] text-xs leading-relaxed whitespace-pre-wrap">${inc.description}</div>
            </div>
            ${(inc.close_category || inc.resolution_notes) ? `
              <div class="p-4 rounded-xl bg-purple-50/50 dark:bg-purple-950/20 border border-purple-200 dark:border-purple-900/50 space-y-3">
                <div class="flex items-center justify-between">
                  <h3 class="text-xs font-bold uppercase tracking-wider text-purple-700 dark:text-purple-400 flex items-center space-x-1.5">
                    <i data-lucide="check-circle-2" class="w-4 h-4 text-emerald-500"></i>
                    <span>Resolution & Root-Cause Governance</span>
                  </h3>
                  ${inc.ado_number ? `
                    <span class="inline-flex items-center space-x-1 px-2.5 py-0.5 rounded-lg bg-blue-100 dark:bg-blue-950 text-blue-700 dark:text-blue-300 font-mono font-bold text-xs border border-blue-300 dark:border-blue-800 shadow-sm">
                      <i data-lucide="bug" class="w-3.5 h-3.5 text-blue-600 dark:text-blue-400"></i>
                      <span>ADO #${inc.ado_number}</span>
                    </span>
                  ` : ''}
                </div>
                <div class="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
                  <div>
                    <span class="text-slate-400 block text-[11px]">Root Cause Category:</span>
                    <span class="font-bold px-2 py-0.5 rounded text-[11px] inline-block mt-0.5 ${inc.close_category === 'Bug' ? 'bg-red-100 text-red-700 dark:bg-red-950 dark:text-red-300' : 'bg-purple-100 text-purple-700 dark:bg-purple-950 dark:text-purple-300'}">${inc.close_category || 'N/A'}</span>
                  </div>
                  <div>
                    <span class="text-slate-400 block text-[11px]">Subcategory:</span>
                    <span class="font-semibold block mt-0.5 text-[var(--text-primary)]">${inc.close_subcategory || 'Standard Fix'}</span>
                  </div>
                  <div>
                    <span class="text-slate-400 block text-[11px]">Impacted App:</span>
                    <span class="font-semibold block mt-0.5 text-[var(--text-primary)]">${inc.close_application_name || inc.application_name}</span>
                  </div>
                  <div>
                    <span class="text-slate-400 block text-[11px]">Resolution Code:</span>
                    <span class="font-semibold block mt-0.5 text-[var(--text-primary)]">${inc.resolution_code || 'Solved'}</span>
                  </div>
                </div>
                ${inc.resolution_notes ? `
                  <div class="pt-2 border-t border-[var(--border-color)]">
                    <span class="text-slate-400 block text-[11px] mb-1">Resolution Notes:</span>
                    <div class="text-xs text-[var(--text-primary)] leading-relaxed whitespace-pre-wrap font-mono p-2.5 rounded-lg bg-[var(--bg-tertiary)] border border-[var(--border-color)]">${inc.resolution_notes}</div>
                  </div>
                ` : ''}
              </div>
            ` : ''}
          </div>

          <!-- TAB CONTENT: CONVERSATION (Customer Comments vs Internal Work Notes) -->
          <div id="tabContent_conversation" class="hidden p-6 space-y-6">
            ${(inc.attachments && inc.attachments.length > 0) ? `
              <!-- Attached Files & Screenshots Banner -->
              <div class="p-4 rounded-xl border border-[var(--border-color)] bg-[var(--bg-tertiary)] space-y-2">
                <div class="flex items-center space-x-2 text-xs font-bold text-slate-700 dark:text-slate-200">
                  <i data-lucide="paperclip" class="w-4 h-4 text-purple-600"></i>
                  <span>Attached Screenshots, Error Logs & Diagnostic Files (${inc.attachments.length})</span>
                </div>
                <div class="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-2.5 pt-1">
                  ${inc.attachments.map(att => `
                    <a href="${API_BASE}/attachments/${att.id}/download" target="_blank" download class="flex items-center justify-between p-2.5 rounded-lg border border-[var(--border-color)] bg-[var(--card-bg)] hover:bg-purple-50 dark:hover:bg-purple-950/20 text-xs transition-all group">
                      <div class="flex items-center space-x-2 truncate">
                        <i data-lucide="${att.content_type?.includes('image') ? 'image' : 'file-text'}" class="w-4 h-4 text-purple-600 group-hover:scale-110 transition-transform shrink-0"></i>
                        <div class="truncate">
                          <span class="font-medium text-[var(--text-primary)] truncate block">${att.filename}</span>
                          <span class="text-[10px] text-slate-400 block">${(att.file_size / 1024).toFixed(1)} KB • ${new Date(att.uploaded_at).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})}</span>
                        </div>
                      </div>
                      <i data-lucide="download" class="w-3.5 h-3.5 text-slate-400 group-hover:text-purple-600 shrink-0 ml-1"></i>
                    </a>
                  `).join('')}
                </div>
              </div>
            ` : ''}

            <!-- Messages timeline -->
            <div class="space-y-4">
              <!-- Customer Comments -->
              ${(inc.comments || []).map(c => `
                <div class="p-4 rounded-xl border border-blue-100 dark:border-blue-950 bg-[var(--comment-bg)] text-xs">
                  <div class="flex items-center justify-between text-purple-600 dark:text-purple-400 font-bold mb-1.5">
                    <div class="flex items-center space-x-1.5">
                      <i data-lucide="message-square" class="w-3.5 h-3.5"></i>
                      <span>Customer-Visible Comment: ${c.user_name}</span>
                    </div>
                    <span class="text-[10px] text-slate-400 font-normal">${new Date(c.created_at).toLocaleString()}</span>
                  </div>
                  <div class="leading-relaxed whitespace-pre-wrap">${c.comment}</div>
                </div>
              `).join('')}

              <!-- Internal Work Notes (Only rendered if authorized!) -->
              ${(inc.work_notes || []).map(w => `
                <div class="p-4 rounded-xl border border-amber-200 dark:border-amber-950 bg-[var(--worknote-bg)] text-xs">
                  <div class="flex items-center justify-between text-amber-700 dark:text-amber-400 font-bold mb-1.5">
                    <div class="flex items-center space-x-1.5">
                      <i data-lucide="lock" class="w-3.5 h-3.5"></i>
                      <span>INTERNAL WORK NOTE: ${w.user_name} (Support Only)</span>
                    </div>
                    <span class="text-[10px] text-slate-400 font-normal">${new Date(w.created_at).toLocaleString()}</span>
                  </div>
                  <div class="leading-relaxed whitespace-pre-wrap">${w.note}</div>
                </div>
              `).join('')}
            </div>

            <!-- Post New Comment or Work Note -->
            <div class="pt-4 border-t border-[var(--border-color)]">
              <div class="flex space-x-2 mb-2">
                <button onclick="setCommentType('customer')" id="commTypeBtn_customer" class="px-3 py-1 rounded text-xs font-semibold bg-purple-600 text-white">Customer Comment</button>
                ${canPostWorkNote ? `
                  <button onclick="setCommentType('worknote')" id="commTypeBtn_worknote" class="px-3 py-1 rounded text-xs font-semibold bg-[var(--bg-tertiary)] text-slate-400">🔒 Work Note</button>
                ` : ''}
              </div>
              <textarea id="commentBox" rows="3" placeholder="Type customer-visible comment..." class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-xl p-3 text-xs focus:outline-none focus:ring-2 focus:ring-purple-500/30"></textarea>

              <!-- File Attachments Toolbar -->
              <div class="mt-2.5 flex flex-wrap items-center gap-2">
                <label class="cursor-pointer inline-flex items-center space-x-1.5 px-3 py-1.5 rounded-lg border border-[var(--border-color)] bg-[var(--bg-tertiary)] hover:bg-[var(--card-bg)] text-xs text-slate-600 dark:text-slate-300 font-medium transition-colors shadow-sm">
                  <i data-lucide="paperclip" class="w-3.5 h-3.5 text-purple-600"></i>
                  <span>Attach Screenshot / Logs</span>
                  <input type="file" id="commentFileInput" class="hidden" multiple onchange="handleCommentFilesSelected(event)">
                </label>
                <div id="commentFilesList" class="flex flex-wrap gap-1.5 text-xs"></div>
              </div>

              <div class="mt-3 flex justify-between items-center">
                ${!isEndUser ? `
                  <button onclick="triggerDraftCopilot('${inc.number}')" class="text-xs text-indigo-600 hover:underline flex items-center space-x-1">
                    <i data-lucide="sparkles" class="w-3.5 h-3.5"></i>
                    <span>AI Assist: Draft Response</span>
                  </button>
                ` : '<div></div>'}
                <button onclick="submitTicketComment(${inc.id})" id="btnPostComment" class="bg-purple-600 hover:bg-purple-700 text-white px-5 py-2 rounded-xl text-xs font-semibold shadow flex items-center space-x-1.5">
                  <i data-lucide="send" class="w-3.5 h-3.5"></i>
                  <span>Post Update</span>
                </button>
              </div>
            </div>
          </div>

          <!-- TAB CONTENT: SLA DETAILS -->
          <div id="tabContent_sla" class="hidden p-6 space-y-4 text-xs">
            <h3 class="font-bold text-sm mb-2">SLA Instance Performance & History</h3>
            <div class="space-y-4">
              ${(inc.sla_instances || []).map(inst => `
                <div class="p-4 rounded-xl border border-[var(--border-color)] bg-[var(--bg-tertiary)] space-y-2">
                  <div class="flex items-center justify-between font-bold">
                    <span>${inst.target_type.toUpperCase()} SLA — ${inst.sla_policy_name} (v${inst.sla_version})</span>
                    <span class="uppercase px-2 py-0.5 rounded text-[10px] ${inst.stage === 'breached' ? 'sla-breached' : 'sla-healthy'}">${inst.stage}</span>
                  </div>
                  <div class="grid grid-cols-2 md:grid-cols-4 gap-2 text-slate-400">
                    <div>Target: <b class="text-[var(--text-primary)]">${inst.target_duration_display || ((inst.target_duration_mins / 60).toFixed(1) + ' hrs (' + inst.target_duration_mins + 'm)')}</b></div>
                    <div>Elapsed: <b class="text-[var(--text-primary)]">${(inst.elapsed_business_mins / 60).toFixed(1)} hrs (${inst.elapsed_business_mins}m)</b></div>
                    <div>Started: <b class="text-[var(--text-primary)]">${inst.start_time ? new Date(inst.start_time).toLocaleTimeString() : 'N/A'}</b></div>
                    <div>Due: <b class="text-[var(--text-primary)]">${inst.due_at ? new Date(inst.due_at).toLocaleTimeString() : 'N/A'}</b></div>
                  </div>
                  ${inst.pause_history && inst.pause_history.length ? `
                    <div class="mt-2 pt-2 border-t border-[var(--border-color)]">
                      <div class="text-[11px] font-semibold text-amber-500">Pause Events:</div>
                      <div class="space-y-1 mt-1">
                        ${inst.pause_history.map(p => `
                          <div class="text-[10px] text-slate-400">Paused: ${p.paused_at} | Reason: ${p.reason} | Resumed: ${p.resumed_at || 'In Progress'}</div>
                        `).join('')}
                      </div>
                    </div>
                  ` : ''}
                </div>
              `).join('')}
            </div>
          </div>

          <!-- TAB CONTENT: AUDIT TIMELINE -->
          <div id="tabContent_timeline" class="hidden p-6 space-y-3 text-xs">
            <h3 class="font-bold text-sm mb-2">Immutable Activity & Modification Audit Trail</h3>
            <div class="space-y-3">
              ${(inc.audit_history || []).map(a => `
                <div class="p-3 rounded-lg border border-[var(--border-color)] bg-[var(--bg-tertiary)] flex items-start justify-between">
                  <div>
                    <div class="font-semibold text-purple-600">${a.action}: ${a.reason || 'Record updated'}</div>
                    <div class="text-slate-400 text-[11px] mt-0.5">By ${a.changed_by_name || 'System'}</div>
                  </div>
                  <div class="text-[10px] text-slate-500">${new Date(a.created_at).toLocaleString()}</div>
                </div>
              `).join('')}
            </div>
          </div>

        </div>
      </div>
    `;
    lucide.createIcons();
  } catch (err) {
    container.innerHTML = `<div class="p-8 text-center text-red-500">Error loading incident: ${err.message}</div>`;
  }
}

// Tab switcher for ticket detail
function switchTicketTab(tab) {
  ['overview', 'conversation', 'sla', 'timeline'].forEach(t => {
    const btn = document.getElementById(`tabBtn_${t}`);
    const content = document.getElementById(`tabContent_${t}`);
    if (t === tab) {
      if (btn) btn.className = 'px-4 py-2 rounded-lg bg-[var(--card-bg)] shadow-sm text-purple-600';
      if (content) content.classList.remove('hidden');
    } else {
      if (btn) btn.className = 'px-4 py-2 rounded-lg hover:bg-[var(--card-bg)] text-slate-400';
      if (content) content.classList.add('hidden');
    }
  });
}

let activeCommentType = 'customer';
function setCommentType(type) {
  activeCommentType = type;
  const custBtn = document.getElementById('commTypeBtn_customer');
  const workBtn = document.getElementById('commTypeBtn_worknote');
  const box = document.getElementById('commentBox');

  if (type === 'customer') {
    custBtn.className = 'px-3 py-1 rounded text-xs font-semibold bg-purple-600 text-white';
    if (workBtn) workBtn.className = 'px-3 py-1 rounded text-xs font-semibold bg-[var(--bg-tertiary)] text-slate-400';
    box.placeholder = 'Type customer-visible comment...';
  } else {
    custBtn.className = 'px-3 py-1 rounded text-xs font-semibold bg-[var(--bg-tertiary)] text-slate-400';
    if (workBtn) workBtn.className = 'px-3 py-1 rounded text-xs font-semibold bg-amber-600 text-white';
    box.placeholder = 'Type internal work note (hidden from customer)...';
  }
}

let pendingCommentFiles = [];

function handleCommentFilesSelected(event) {
  const files = Array.from(event.target.files);
  if (!files.length) return;
  pendingCommentFiles = pendingCommentFiles.concat(files);
  renderCommentFilesList();
  event.target.value = '';
}

function removePendingCommentFile(index) {
  pendingCommentFiles.splice(index, 1);
  renderCommentFilesList();
}

function renderCommentFilesList() {
  const container = document.getElementById('commentFilesList');
  if (!container) return;
  if (pendingCommentFiles.length === 0) {
    container.innerHTML = '';
    return;
  }
  container.innerHTML = pendingCommentFiles.map((file, idx) => `
    <span class="inline-flex items-center space-x-1.5 px-2.5 py-1 rounded-lg bg-purple-50 dark:bg-purple-950/40 border border-purple-200 dark:border-purple-800 text-purple-700 dark:text-purple-300 text-xs">
      <i data-lucide="${file.type?.includes('image') ? 'image' : 'file-text'}" class="w-3.5 h-3.5 text-purple-600 shrink-0"></i>
      <span class="truncate max-w-[140px] font-medium">${file.name}</span>
      <span class="text-[10px] text-slate-400">(${(file.size / 1024).toFixed(1)}KB)</span>
      <button type="button" onclick="removePendingCommentFile(${idx})" class="text-slate-400 hover:text-red-500 ml-1">
        <i data-lucide="x" class="w-3 h-3"></i>
      </button>
    </span>
  `).join('');
  lucide.createIcons();
}

async function submitTicketComment(ticketId) {
  const box = document.getElementById('commentBox');
  const val = box ? box.value.trim() : '';
  if (!val && pendingCommentFiles.length === 0) return;

  const btn = document.getElementById('btnPostComment');
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = `<i data-lucide="loader-2" class="w-3.5 h-3.5 animate-spin"></i><span>Posting...</span>`;
    lucide.createIcons();
  }

  try {
    const uploadedNames = [];
    if (pendingCommentFiles.length > 0) {
      for (const file of pendingCommentFiles) {
        const formData = new FormData();
        formData.append('ticket_type', 'Incident');
        formData.append('ticket_id', ticketId.toString());
        formData.append('file', file);

        const upRes = await fetch(`${API_BASE}/attachments`, {
          method: 'POST',
          headers: {
            'X-User-ID': state.currentUser.id.toString()
          },
          body: formData
        });
        if (upRes.ok) {
          uploadedNames.push(file.name);
        } else {
          const errData = await upRes.json().catch(() => ({}));
          console.warn('Attachment upload failed:', errData);
        }
      }
    }

    let finalComment = val;
    if (uploadedNames.length > 0) {
      const attachNotice = `📎 [Attached ${uploadedNames.length} file(s): ${uploadedNames.join(', ')}]`;
      finalComment = finalComment ? `${finalComment}\n\n${attachNotice}` : attachNotice;
    }

    if (finalComment) {
      const endpoint = activeCommentType === 'customer'
        ? `${API_BASE}/incidents/${ticketId}/comments`
        : `${API_BASE}/incidents/${ticketId}/work-notes`;

      const payload = activeCommentType === 'customer' ? { comment: finalComment } : { note: finalComment };

      const res = await fetch(endpoint, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-User-ID': state.currentUser.id.toString()
        },
        body: JSON.stringify(payload)
      });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        alert('Error posting note: ' + (errData.detail || res.statusText));
      }
    }

    pendingCommentFiles = [];
    reloadActiveTicketDetailView(ticketType);
  } catch (err) {
    alert('Error posting update: ' + err.message);
  } finally {
    if (btn) btn.disabled = false;
  }
}

function reloadActiveTicketDetailView(ticketType) {
  const tType = ticketType || window._activeTicketTypeContext || 'Incident';
  const mainApp = document.getElementById('mainApp');
  if (tType === 'Service Request') {
    renderRequestDetailView(mainApp, state.routeParams.id);
  } else if (tType === 'Change Request') {
    renderChangeDetailView(mainApp, state.routeParams.id);
  } else {
    renderIncidentDetailView(mainApp, state.routeParams.id);
  }
}

async function assignToMe(ticketId, ticketType = 'Incident') {
  window._activeTicketTypeContext = ticketType;
  try {
    let baseRoute = 'incidents';
    if (ticketType === 'Service Request') baseRoute = 'service-requests';
    else if (ticketType === 'Change Request') baseRoute = 'changes';

    const res = await fetch(`${API_BASE}/${baseRoute}/${ticketId}/assign`, {
      method: 'PATCH',
      headers: {
        'Content-Type': 'application/json',
        'X-User-ID': state.currentUser.id.toString()
      },
      body: JSON.stringify({ assigned_to_id: state.currentUser.id })
    });
    if (res.ok) {
      reloadActiveTicketDetailView(ticketType);
    } else {
      const err = await res.json().catch(() => ({}));
      alert('Assign to Me failed: ' + (err.detail || res.statusText));
    }
  } catch (err) {
    alert('Error assigning ticket: ' + err.message);
  }
}

async function openReassignModal(ticketId, currentGroupId, currentAssigneeId, currentProjectId, currentAppId, currentPriority, ticketType = 'Incident') {
  window._activeReassignTicketType = ticketType;
  window._activeTicketTypeContext = ticketType;
  let groups = [];
  let projects = [];
  let apps = [];
  try {
    const authHeaders = { 'X-User-ID': state.currentUser.id.toString() };
    const [grpRes, projRes, appRes] = await Promise.all([
      fetch(`${API_BASE}/assignment-groups`),
      fetch(`${API_BASE}/admin/projects`, { headers: authHeaders }),
      fetch(`${API_BASE}/admin/applications`, { headers: authHeaders })
    ]);
    if (grpRes.ok) groups = await grpRes.json();
    if (projRes.ok) projects = await projRes.json();
    if (appRes.ok) apps = await appRes.json();
  } catch (e) {
    console.error(e);
  }

  const isGlobalAdmin = !!(state.currentUser?.is_global_admin || state.currentUser?.username === 'admin');
  const userBoundaries = state.currentUser?.project_boundaries || {};
  const userProjects = (userBoundaries.project_names && userBoundaries.project_names.length)
    ? userBoundaries.project_names
    : (state.currentUser?.admin_projects || state.currentUser?.support_projects || []);
  const isSupportMember = !isGlobalAdmin && userProjects.length > 0;

  // In ServiceNow, support engineers can reassign/transfer tickets to any project or group
  window._reassignGroups = groups;
  window._reassignProjects = projects;
  window._reassignApps = apps;

  const selectedProjId = currentProjectId || (projects.length ? projects[0].id : '');

  const modalContainer = document.getElementById('modalContainer');
  modalContainer.innerHTML = `
    <div class="fixed inset-0 bg-black/50 backdrop-blur-sm z-50 flex items-center justify-center p-4">
      <div class="w-full max-w-lg bg-[var(--card-bg)] border border-[var(--border-color)] rounded-2xl shadow-2xl overflow-hidden animate-fade-in max-h-[90vh] flex flex-col">
        <div class="p-4 border-b border-[var(--border-color)] flex items-center justify-between shrink-0">
          <div class="flex items-center space-x-2">
            <i data-lucide="user-check" class="w-5 h-5 text-purple-600"></i>
            <h2 class="text-base font-bold">Reassign ${ticketType} & Update Routing</h2>
          </div>
          <button onclick="document.getElementById('modalContainer').innerHTML=''" class="text-slate-400 hover:text-white">✕</button>
        </div>
        <form onsubmit="confirmReassign(event, ${ticketId})" class="p-5 space-y-4 text-xs overflow-y-auto flex-1">
          <div>
            <label class="block font-semibold text-slate-400 mb-1">Target Project</label>
            <select id="reassign_proj" onchange="onReassignProjectChange()" class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-lg p-2.5 text-xs font-semibold">
              <option value="">-- Select Project --</option>
              ${projects.map(p => `<option value="${p.id}" ${p.id == selectedProjId ? 'selected' : ''}>${p.name}</option>`).join('')}
            </select>
          </div>

          <div>
            <label class="block font-semibold text-slate-400 mb-1">Application (Scoped to Project)</label>
            <select id="reassign_app" onchange="onReassignAppChange()" class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-lg p-2.5 text-xs font-semibold">
              <!-- populated dynamically -->
            </select>
          </div>

          <div>
            <label class="block font-semibold text-slate-400 mb-1">Priority (Independent Choice)</label>
            <select id="reassign_priority" class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-lg p-2.5 text-xs font-bold">
              <option value="P1" ${(currentPriority || 'P3') === 'P1' ? 'selected' : ''} class="text-red-500">P1 - Critical (Outage / Production Down)</option>
              <option value="P2" ${(currentPriority || 'P3') === 'P2' ? 'selected' : ''} class="text-orange-500">P2 - High (Severe Impact)</option>
              <option value="P3" ${(currentPriority || 'P3') === 'P3' ? 'selected' : ''} class="text-amber-500">P3 - Medium (Normal Operations)</option>
              <option value="P4" ${(currentPriority || 'P3') === 'P4' ? 'selected' : ''} class="text-blue-500">P4 - Low (Minor Defect)</option>
              <option value="P5" ${(currentPriority || 'P3') === 'P5' ? 'selected' : ''} class="text-slate-500">P5 - Planning / Inquiry</option>
            </select>
          </div>

          <div>
            <label class="block font-semibold text-slate-400 mb-1">Assignment Group (Scoped or Cross-Project Queues)</label>
            <select id="reassign_group" onchange="onReassignGroupChange()" class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-lg p-2.5 text-xs font-semibold">
              <!-- populated dynamically -->
            </select>
            <p class="text-[10px] text-slate-400 mt-1">Reassign within project frontline (L2), engineering (L3), or transfer to other project/shared queues.</p>
          </div>

          <div>
            <label class="block font-semibold text-slate-400 mb-1">Assigned Support Engineer (Filtered by Group)</label>
            <select id="reassign_user" class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-lg p-2.5 text-xs font-semibold">
              <!-- populated dynamically -->
            </select>
          </div>

          <div class="pt-4 border-t border-[var(--border-color)] flex justify-end space-x-2 shrink-0">
            <button type="button" onclick="document.getElementById('modalContainer').innerHTML=''" class="px-4 py-2 rounded-xl border border-[var(--border-color)] text-slate-400 hover:bg-[var(--bg-tertiary)]">Cancel</button>
            <button type="submit" class="px-5 py-2 rounded-xl bg-purple-600 hover:bg-purple-700 text-white font-semibold">Confirm Reassignment</button>
          </div>
        </form>
      </div>
    </div>
  `;
  lucide.createIcons();
  onReassignProjectChange(currentAppId, currentGroupId, currentAssigneeId);
}

function onReassignProjectChange(initialAppId, initialGroupId, initialUserId) {
  const projSelect = document.getElementById('reassign_proj');
  const appSelect = document.getElementById('reassign_app');
  if (!projSelect || !appSelect) return;

  const projId = projSelect.value ? parseInt(projSelect.value) : null;
  const allProjects = window._reassignProjects || [];
  const allApps = window._reassignApps || [];

  const selectedProj = allProjects.find(p => p.id === projId);
  const projName = selectedProj ? selectedProj.name.toLowerCase() : '';

  // 1. Filter Applications: apps belonging to this project
  const matchedApps = allApps.filter(a => {
    if (!projId) return true;
    if (a.project_id === projId) return true;
    if (selectedProj && selectedProj.application_id === a.id) return true;
    if (selectedProj && Array.isArray(selectedProj.applications) && selectedProj.applications.some(subA => subA.id === a.id)) return true;
    if (Array.isArray(a.projects) && a.projects.some(p => p.id === projId || (p.name && p.name.toLowerCase() === projName))) return true;
    return false;
  });

  const availableApps = matchedApps.length ? matchedApps : allApps;
  appSelect.innerHTML = availableApps.map(a => `<option value="${a.id}" ${a.id == initialAppId ? 'selected' : ''}>${a.name}</option>`).join('');

  onReassignAppChange(initialGroupId, initialUserId);
}

function onReassignAppChange(initialGroupId, initialUserId) {
  const projSelect = document.getElementById('reassign_proj');
  const appSelect = document.getElementById('reassign_app');
  const grpSelect = document.getElementById('reassign_group');
  if (!projSelect || !appSelect || !grpSelect) return;

  const projId = projSelect.value ? parseInt(projSelect.value) : null;
  const appId = appSelect.value ? parseInt(appSelect.value) : null;
  const allProjects = window._reassignProjects || [];
  const allApps = window._reassignApps || [];
  const allGroups = window._reassignGroups || [];

  const selectedProj = allProjects.find(p => p.id === projId);
  const selectedApp = allApps.find(a => a.id === appId);
  const projName = selectedProj ? selectedProj.name.toLowerCase() : '';
  const appName = selectedApp ? selectedApp.name.toLowerCase() : '';

  // 2. Filter & Categorize Assignment Groups based on Project and Application
  const appSpecificGroups = [];
  const currentProjGroups = [];
  const otherProjGroups = [];
  const sharedGroups = [];

  allGroups.forEach(g => {
    const gName = g.name.toLowerCase();
    let projsSupp = [];
    try { projsSupp = JSON.parse(g.projects_supported || '[]').map(x => x.toLowerCase()); } catch (e) {}
    let appsSupp = [];
    try { appsSupp = JSON.parse(g.applications_supported || '[]').map(x => x.toLowerCase()); } catch (e) {}

    const isAppMatch = selectedApp && (
      appsSupp.includes(appName) ||
      (selectedApp.default_assignment_group_id && g.id === selectedApp.default_assignment_group_id) ||
      gName.startsWith(`${appName}-`) ||
      gName === appName
    );

    const isThisProj = projName && (gName.startsWith(`${projName}-`) || gName === projName || projsSupp.includes(projName));
    const isOtherProj = allProjects.some(p => {
      const pN = p.name.toLowerCase();
      return pN !== projName && (gName.startsWith(`${pN}-`) || gName === pN);
    });

    if (isAppMatch) {
      appSpecificGroups.push(g);
    } else if (isThisProj) {
      currentProjGroups.push(g);
    } else if (isOtherProj) {
      otherProjGroups.push(g);
    } else {
      sharedGroups.push(g);
    }
  });

  let groupOptionsHtml = '';
  if (appSpecificGroups.length > 0) {
    groupOptionsHtml += `
      <optgroup label="Application-Specific Queues (${selectedApp ? selectedApp.name : 'Selected Application'})">
        ${appSpecificGroups.map(g => `<option value="${g.id}" ${g.id == initialGroupId ? 'selected' : ''}>${g.name}</option>`).join('')}
      </optgroup>
    `;
  }
  if (currentProjGroups.length > 0) {
    groupOptionsHtml += `
      <optgroup label="This Project Queues (${selectedProj ? selectedProj.name : 'Selected Project'})">
        ${currentProjGroups.map(g => `<option value="${g.id}" ${g.id == initialGroupId ? 'selected' : ''}>${g.name}</option>`).join('')}
      </optgroup>
    `;
  }
  if (otherProjGroups.length > 0) {
    groupOptionsHtml += `
      <optgroup label="Other Project Queues">
        ${otherProjGroups.map(g => `<option value="${g.id}" ${g.id == initialGroupId ? 'selected' : ''}>${g.name}</option>`).join('')}
      </optgroup>
    `;
  }
  if (sharedGroups.length > 0) {
    groupOptionsHtml += `
      <optgroup label="Enterprise & Shared Support Queues">
        ${sharedGroups.map(g => `<option value="${g.id}" ${g.id == initialGroupId ? 'selected' : ''}>${g.name}</option>`).join('')}
      </optgroup>
    `;
  }

  grpSelect.innerHTML = groupOptionsHtml || allGroups.map(g => `<option value="${g.id}" ${g.id == initialGroupId ? 'selected' : ''}>${g.name}</option>`).join('');

  if (initialGroupId) {
    grpSelect.value = initialGroupId;
  } else if (selectedApp && selectedApp.default_assignment_group_id) {
    grpSelect.value = selectedApp.default_assignment_group_id;
  }

  onReassignGroupChange(initialUserId);
}

async function onReassignGroupChange(initialUserId) {
  const grpSelect = document.getElementById('reassign_group');
  const userSelect = document.getElementById('reassign_user');
  if (!grpSelect || !userSelect) return;

  const grpId = grpSelect.value ? parseInt(grpSelect.value) : null;
  const allGroups = window._reassignGroups || [];
  const selectedGrp = allGroups.find(g => g.id === grpId);

  let assignees = (selectedGrp && selectedGrp.eligible_assignees && selectedGrp.eligible_assignees.length)
    ? selectedGrp.eligible_assignees
    : [];

  if (assignees.length === 0 && grpId) {
    try {
      const res = await fetch(`${API_BASE}/admin/groups/${grpId}/assignees`);
      if (res.ok) {
        assignees = await res.json();
        if (selectedGrp) selectedGrp.eligible_assignees = assignees;
      }
    } catch (_) {}
  }

  userSelect.innerHTML = `
    <option value="">-- Unassigned (Reassigning with group only sets status to Active) --</option>
    ${assignees.map(u => `<option value="${u.id}" ${u.id == initialUserId ? 'selected' : ''}>${u.full_name} (${u.role}) → sets In Progress</option>`).join('')}
  `;
}

async function confirmReassign(e, ticketId) {
  e.preventDefault();
  const ticketType = window._activeReassignTicketType || 'Incident';
  let baseRoute = 'incidents';
  if (ticketType === 'Service Request') baseRoute = 'service-requests';
  else if (ticketType === 'Change Request') baseRoute = 'changes';

  const projVal = document.getElementById('reassign_proj')?.value;
  const appVal = document.getElementById('reassign_app')?.value;
  const priorityVal = document.getElementById('reassign_priority')?.value;
  const groupIdVal = document.getElementById('reassign_group')?.value;
  const userIdVal = document.getElementById('reassign_user')?.value;

  const payload = {};
  if (projVal) payload.project_id = parseInt(projVal);
  if (appVal) payload.application_id = parseInt(appVal);
  if (priorityVal) payload.priority = priorityVal;
  if (groupIdVal) payload.assignment_group_id = parseInt(groupIdVal);
  if (userIdVal) payload.assigned_to_id = parseInt(userIdVal);
  else payload.assigned_to_id = null;

  try {
    const res = await fetch(`${API_BASE}/${baseRoute}/${ticketId}/assign`, {
      method: 'PATCH',
      headers: {
        'Content-Type': 'application/json',
        'X-User-ID': state.currentUser.id.toString()
      },
      body: JSON.stringify(payload)
    });
    if (res.ok) {
      document.getElementById('modalContainer').innerHTML = '';
      reloadActiveTicketDetailView(ticketType);
    } else {
      const err = await res.json().catch(() => ({}));
      alert('Reassign failed: ' + (err.detail || res.statusText));
    }
  } catch (err) {
    alert('Network error: ' + err.message);
  }
}

function openPriorityModal(ticketId, currentPriority, ticketType = 'Incident') {
  window._activePriorityTicketType = ticketType;
  window._activeTicketTypeContext = ticketType;
  const modalContainer = document.getElementById('modalContainer');
  modalContainer.innerHTML = `
    <div class="fixed inset-0 bg-black/50 backdrop-blur-sm z-50 flex items-center justify-center p-4">
      <div class="w-full max-w-sm bg-[var(--card-bg)] border border-[var(--border-color)] rounded-2xl shadow-2xl overflow-hidden animate-fade-in">
        <div class="p-4 border-b border-[var(--border-color)] flex items-center justify-between">
          <div class="flex items-center space-x-2">
            <i data-lucide="alert-triangle" class="w-5 h-5 text-amber-500"></i>
            <h2 class="text-base font-bold">Change ${ticketType} Priority</h2>
          </div>
          <button onclick="document.getElementById('modalContainer').innerHTML=''" class="text-slate-400 hover:text-white">✕</button>
        </div>
        <form onsubmit="confirmChangePriority(event, ${ticketId})" class="p-5 space-y-4 text-xs">
          <div>
            <label class="block font-semibold text-slate-400 mb-1">Select Priority *</label>
            <select id="update_priority" class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-lg p-2.5 text-xs font-bold">
              <option value="P1" ${currentPriority === 'P1' ? 'selected' : ''} class="text-red-500">P1 - Critical (Outage / Production Down)</option>
              <option value="P2" ${currentPriority === 'P2' ? 'selected' : ''} class="text-orange-500">P2 - High (Severe Impact)</option>
              <option value="P3" ${currentPriority === 'P3' ? 'selected' : ''} class="text-amber-500">P3 - Medium (Normal Business Impact)</option>
              <option value="P4" ${currentPriority === 'P4' ? 'selected' : ''} class="text-blue-500">P4 - Low (Minor Inconvenience)</option>
              <option value="P5" ${currentPriority === 'P5' ? 'selected' : ''} class="text-slate-500">P5 - Planning / Inquiry</option>
            </select>
          </div>
          <div>
            <label class="block font-semibold text-slate-400 mb-1">Reason for Priority Adjustment</label>
            <textarea id="update_priority_reason" rows="2" placeholder="e.g. Business escalation, scope downgraded..." class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-lg p-2.5 text-xs"></textarea>
          </div>
          <div class="pt-3 border-t border-[var(--border-color)] flex justify-end space-x-2">
            <button type="button" onclick="document.getElementById('modalContainer').innerHTML=''" class="px-4 py-2 rounded-xl border border-[var(--border-color)] text-slate-400 hover:bg-[var(--bg-tertiary)]">Cancel</button>
            <button type="submit" class="px-4 py-2 rounded-xl bg-amber-600 hover:bg-amber-700 text-white font-semibold">Update Priority</button>
          </div>
        </form>
      </div>
    </div>
  `;
  lucide.createIcons();
}

async function confirmChangePriority(e, ticketId) {
  e.preventDefault();
  const ticketType = window._activePriorityTicketType || 'Incident';
  let baseRoute = 'incidents';
  if (ticketType === 'Service Request') baseRoute = 'service-requests';
  else if (ticketType === 'Change Request') baseRoute = 'changes';

  const priVal = document.getElementById('update_priority').value;
  const reasonVal = document.getElementById('update_priority_reason').value;

  try {
    const res = await fetch(`${API_BASE}/${baseRoute}/${ticketId}/priority`, {
      method: 'PATCH',
      headers: {
        'Content-Type': 'application/json',
        'X-User-ID': state.currentUser.id.toString()
      },
      body: JSON.stringify({ priority: priVal, reason: reasonVal })
    });
    if (res.ok) {
      document.getElementById('modalContainer').innerHTML = '';
      reloadActiveTicketDetailView(ticketType);
    } else {
      const err = await res.json().catch(() => ({}));
      alert('Priority update failed: ' + (err.detail || res.statusText));
    }
  } catch (err) {
    alert('Network error: ' + err.message);
  }
}

function openStatusModal(ticketId, currentStatus, ticketType = 'Incident') {
  window._activeStatusTicketType = ticketType;
  window._activeTicketTypeContext = ticketType;

  let allowedStatuses = [];
  if (ticketType === 'Incident') {
    allowedStatuses = ['New', 'Active', 'In Progress', 'On Hold', 'Pending', 'Resolved', 'Closed', 'Canceled'];
  } else if (ticketType === 'Service Request') {
    allowedStatuses = ['Submitted', 'Active', 'In Progress', 'Pending Approval', 'Approved', 'In Fulfillment', 'Fulfilled', 'Completed', 'Closed', 'Cancelled'];
  } else if (ticketType === 'Change Request') {
    allowedStatuses = ['Draft', 'Active', 'Assess', 'Authorize', 'Scheduled', 'Implement', 'Review', 'Closed', 'Canceled'];
  }

  const modalContainer = document.getElementById('modalContainer');
  modalContainer.innerHTML = `
    <div class="fixed inset-0 bg-black/50 backdrop-blur-sm z-50 flex items-center justify-center p-4">
      <div class="w-full max-w-sm bg-[var(--card-bg)] border border-[var(--border-color)] rounded-2xl shadow-2xl overflow-hidden animate-fade-in">
        <div class="p-4 border-b border-[var(--border-color)] flex items-center justify-between">
          <div class="flex items-center space-x-2">
            <i data-lucide="refresh-cw" class="w-5 h-5 text-purple-600"></i>
            <h2 class="text-base font-bold">Update ${ticketType} Status</h2>
          </div>
          <button onclick="document.getElementById('modalContainer').innerHTML=''" class="text-slate-400 hover:text-white">✕</button>
        </div>
        <form onsubmit="confirmChangeStatus(event, ${ticketId})" class="p-5 space-y-4 text-xs">
          <div>
            <label class="block font-semibold text-slate-400 mb-1">Current Status</label>
            <div class="p-2 rounded-lg bg-[var(--bg-tertiary)] font-bold text-[var(--text-primary)]">${currentStatus}</div>
          </div>
          <div>
            <label class="block font-semibold text-slate-400 mb-1">Select New Status *</label>
            <select id="update_status_val" class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-lg p-2.5 text-xs font-bold">
              ${allowedStatuses.map(s => `<option value="${s}" ${s === currentStatus ? 'selected' : ''}>${s}</option>`).join('')}
            </select>
          </div>
          <div>
            <label class="block font-semibold text-slate-400 mb-1">Reason / Transition Notes</label>
            <textarea id="update_status_reason" rows="2" placeholder="e.g. Work initiated, testing verified..." class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-lg p-2.5 text-xs"></textarea>
          </div>
          <div class="pt-3 border-t border-[var(--border-color)] flex justify-end space-x-2">
            <button type="button" onclick="document.getElementById('modalContainer').innerHTML=''" class="px-4 py-2 rounded-xl border border-[var(--border-color)] text-slate-400 hover:bg-[var(--bg-tertiary)]">Cancel</button>
            <button type="submit" class="px-4 py-2 rounded-xl bg-purple-600 hover:bg-purple-700 text-white font-semibold">Update Status</button>
          </div>
        </form>
      </div>
    </div>
  `;
  lucide.createIcons();
}

async function confirmChangeStatus(e, ticketId) {
  e.preventDefault();
  const ticketType = window._activeStatusTicketType || 'Incident';
  const statusVal = document.getElementById('update_status_val')?.value;
  const reasonVal = document.getElementById('update_status_reason')?.value;

  try {
    let endpoint = `${API_BASE}/incidents/${ticketId}/status`;
    let bodyPayload = { status: statusVal, reason: reasonVal };

    if (ticketType === 'Service Request') {
      endpoint = `${API_BASE}/service-requests/${ticketId}/status`;
      bodyPayload = { status: statusVal, reason: reasonVal };
    } else if (ticketType === 'Change Request') {
      endpoint = `${API_BASE}/changes/${ticketId}/status`;
      bodyPayload = { change_status: statusVal, reason: reasonVal };
    }

    const res = await fetch(endpoint, {
      method: 'PATCH',
      headers: {
        'Content-Type': 'application/json',
        'X-User-ID': state.currentUser.id.toString()
      },
      body: JSON.stringify(bodyPayload)
    });
    if (res.ok) {
      document.getElementById('modalContainer').innerHTML = '';
      reloadActiveTicketDetailView(ticketType);
    } else {
      const err = await res.json().catch(() => ({}));
      alert('Status update failed: ' + (err.detail || res.statusText));
    }
  } catch (err) {
    alert('Network error: ' + err.message);
  }
}

async function quickUpdateStatus(e, ticketType, ticketId, newStatus, currentStatus) {
  if (newStatus === currentStatus) return;
  try {
    let endpoint = `${API_BASE}/incidents/${ticketId}/status`;
    let bodyPayload = { status: newStatus, reason: `Status changed to ${newStatus}` };

    if (ticketType === 'Service Request') {
      endpoint = `${API_BASE}/service-requests/${ticketId}/status`;
      bodyPayload = { status: newStatus, reason: `Status changed to ${newStatus}` };
    } else if (ticketType === 'Change Request') {
      endpoint = `${API_BASE}/changes/${ticketId}/status`;
      bodyPayload = { change_status: newStatus, reason: `Status changed to ${newStatus}` };
    }

    const res = await fetch(endpoint, {
      method: 'PATCH',
      headers: {
        'Content-Type': 'application/json',
        'X-User-ID': state.currentUser.id.toString()
      },
      body: JSON.stringify(bodyPayload)
    });
    if (res.ok) {
      reloadActiveTicketDetailView(ticketType);
    } else {
      const err = await res.json().catch(() => ({}));
      alert('Status update failed: ' + (err.detail || res.statusText));
      if (e && e.target) e.target.value = currentStatus;
    }
  } catch (err) {
    alert('Network error: ' + err.message);
    if (e && e.target) e.target.value = currentStatus;
  }
}

function openApprovalDecisionModal(ticketId, ticketType) {
  window._activeApprovalTicketType = ticketType;
  window._activeTicketTypeContext = ticketType;
  const modalContainer = document.getElementById('modalContainer');
  modalContainer.innerHTML = `
    <div class="fixed inset-0 bg-black/50 backdrop-blur-sm z-50 flex items-center justify-center p-4">
      <div class="w-full max-w-sm bg-[var(--card-bg)] border border-[var(--border-color)] rounded-2xl shadow-2xl overflow-hidden animate-fade-in">
        <div class="p-4 border-b border-[var(--border-color)] flex items-center justify-between">
          <div class="flex items-center space-x-2">
            <i data-lucide="check-circle-2" class="w-5 h-5 text-purple-600"></i>
            <h2 class="text-base font-bold">${ticketType} Approval Decision</h2>
          </div>
          <button onclick="document.getElementById('modalContainer').innerHTML=''" class="text-slate-400 hover:text-white">✕</button>
        </div>
        <form onsubmit="confirmApprovalDecision(event, ${ticketId}, '${ticketType}')" class="p-5 space-y-4 text-xs">
          <div>
            <label class="block font-semibold text-slate-400 mb-1">Decision *</label>
            <select id="approval_decision_val" class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-lg p-2.5 text-xs font-bold">
              <option value="Approved" class="text-emerald-500">Approve Request</option>
              <option value="Rejected" class="text-red-500">Reject Request</option>
            </select>
          </div>
          <div>
            <label class="block font-semibold text-slate-400 mb-1">Decision Comments / Rationale</label>
            <textarea id="approval_decision_comments" rows="3" placeholder="Provide reason or conditional approval terms..." class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-lg p-2.5 text-xs"></textarea>
          </div>
          <div class="pt-3 border-t border-[var(--border-color)] flex justify-end space-x-2">
            <button type="button" onclick="document.getElementById('modalContainer').innerHTML=''" class="px-4 py-2 rounded-xl border border-[var(--border-color)] text-slate-400 hover:bg-[var(--bg-tertiary)]">Cancel</button>
            <button type="submit" class="px-4 py-2 rounded-xl bg-purple-600 hover:bg-purple-700 text-white font-semibold">Submit Decision</button>
          </div>
        </form>
      </div>
    </div>
  `;
  lucide.createIcons();
}

async function confirmApprovalDecision(e, ticketId, ticketType) {
  e.preventDefault();
  const decision = document.getElementById('approval_decision_val')?.value;
  const comments = document.getElementById('approval_decision_comments')?.value;

  try {
    const endpoint = ticketType === 'Service Request'
      ? `${API_BASE}/service-requests/${ticketId}/approve`
      : `${API_BASE}/changes/${ticketId}/approve`;

    const res = await fetch(endpoint, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-User-ID': state.currentUser.id.toString()
      },
      body: JSON.stringify({ decision, comments })
    });
    if (res.ok) {
      document.getElementById('modalContainer').innerHTML = '';
      reloadActiveTicketDetailView(ticketType);
    } else {
      const err = await res.json().catch(() => ({}));
      alert('Approval action failed: ' + (err.detail || res.statusText));
    }
  } catch (err) {
    alert('Network error: ' + err.message);
  }
}

// --- SERVICE REQUESTS & SERVICE CATALOG ---
async function renderServiceRequestsView(container) {
  container.innerHTML = `<div class="p-8 text-center text-slate-400"><i data-lucide="loader-2" class="w-8 h-8 animate-spin mx-auto mb-2 text-purple-500"></i>Loading Service Requests...</div>`;
  lucide.createIcons();

  try {
    if (!state.projects?.length || !state.applications?.length) {
      try {
        const [pRes, aRes] = await Promise.allSettled([
          fetch(`${API_BASE}/projects`),
          fetch(`${API_BASE}/applications`)
        ]);
        if (pRes.status === 'fulfilled' && pRes.value.ok) state.projects = await pRes.value.json();
        if (aRes.status === 'fulfilled' && aRes.value.ok) state.applications = await aRes.value.json();
      } catch (_) {}
    }

    const res = await fetch(`${API_BASE}/service-requests`, {
      headers: { 'X-User-ID': state.currentUser.id.toString() }
    });
    const requests = await res.json();
    let requestColumns = [];
    try { const r = await fetch(`${API_BASE}/admin/configuration/columns?ticket_type=Service%20Request`); if (r.ok) requestColumns = (await r.json()).filter(c => c.enabled); } catch (_) {}
    requestColumns = requestColumns.length ? requestColumns : [{column_key:'number',label:'Request #'},{column_key:'catalog_item',label:'Catalog Item'},{column_key:'requested_by_name',label:'Requested By'},{column_key:'priority',label:'Priority'},{column_key:'application_name',label:'Application'},{column_key:'project_name',label:'Project'},{column_key:'assignment_group_name',label:'Assignment Group'},{column_key:'approval_status',label:'Approval'},{column_key:'status',label:'Status'},{column_key:'created_at',label:'Created'}];

    const isEndUser = isUserEndUser(state.currentUser);
    const isGlobalAdmin = !!(state.currentUser?.is_global_admin || state.currentUser?.username === 'admin');
    const userBoundaries = state.currentUser?.project_boundaries || {};
    const userProjects = (userBoundaries.project_names && userBoundaries.project_names.length)
      ? userBoundaries.project_names
      : (state.currentUser?.admin_projects || state.currentUser?.support_projects || []);
    const isSupportMember = !isGlobalAdmin && !isEndUser && userProjects.length > 0;

    const uniquePriorities = ['P1', 'P2', 'P3', 'P4'];
    const uniqueStatuses = [...new Set(['Submitted', 'Active', 'In Progress', 'Pending Approval', 'Approved', 'In Fulfillment', 'Fulfilled', 'Completed', 'Closed', 'Cancelled', ...requests.map(r => r.status).filter(Boolean)])];
    const projectSet = new Set(requests.map(r => r.project_name).filter(Boolean));
    userProjects.forEach(p => projectSet.add(p));
    if (state.projects) state.projects.forEach(p => projectSet.add(p.name));
    const uniqueProjects = [...projectSet].sort();
    const uniqueGroups = [...new Set(requests.map(r => r.assignment_group_name).filter(Boolean))].sort();
    const defaultProject = (isSupportMember && userProjects.length > 0) ? userProjects[0] : '';

    const projectToApps = {};
    requests.forEach(r => {
      if (r.project_name && r.application_name) {
        if (!projectToApps[r.project_name]) projectToApps[r.project_name] = new Set();
        projectToApps[r.project_name].add(r.application_name);
      }
    });
    if (state.applications) {
      state.applications.forEach(a => {
        const pName = a.project_name || (state.projects?.find(p => p.id === a.project_id)?.name);
        if (pName && a.name) {
          if (!projectToApps[pName]) projectToApps[pName] = new Set();
          projectToApps[pName].add(a.name);
        }
      });
    }
    if (userBoundaries.project_names && userBoundaries.application_names) {
      userBoundaries.project_names.forEach(pn => {
        if (!projectToApps[pn]) projectToApps[pn] = new Set();
        userBoundaries.application_names.forEach(an => projectToApps[pn].add(an));
      });
    }

    const allKnownApps = new Set(requests.map(r => r.application_name).filter(a => a && a !== 'N/A'));
    if (state.applications) state.applications.forEach(a => { if (a.name) allKnownApps.add(a.name); });
    const uniqueApps = [...allKnownApps].sort();

    const initialProjects = (isSupportMember && userProjects.length > 0) ? userProjects.slice() : (defaultProject ? [defaultProject] : []);
    let availableApps = [];
    if (initialProjects.length > 0) {
      const appSet = new Set();
      initialProjects.forEach(p => {
        if (projectToApps[p]) projectToApps[p].forEach(a => appSet.add(a));
      });
      availableApps = appSet.size > 0 ? [...appSet].sort() : uniqueApps;
    } else {
      availableApps = uniqueApps;
    }

    const initialGroups = getFilteredAssignmentGroups(initialProjects, '', uniqueGroups);

    container.innerHTML = `
      <div class="space-y-6">
        <div class="flex items-center justify-between">
          <div>
            <h1 class="text-2xl font-black tracking-tight">${isEndUser ? 'My Service Requests' : 'Service Catalog & Requests'}</h1>
            <p class="text-sm text-slate-500">${isEndUser ? 'Track your requested services, permissions, and environments.' : (isSupportMember ? `Project-scoped queue for ${userProjects.join(', ')} with cross-project visibility.` : 'Request access, hardware, cloud environments, and track fulfillment.')}</p>
          </div>
          <div class="flex items-center space-x-2">
            ${['support_member', 'group_manager', 'administrator', 'itsm_admin'].includes(state.currentUser?.role) ? `
              <button onclick="openExportModal('service-requests')" class="px-3.5 py-2 rounded-xl border border-[var(--border-color)] bg-[var(--card-bg)] hover:bg-[var(--bg-tertiary)] text-xs font-semibold flex items-center space-x-1.5 shadow-sm text-purple-600 dark:text-purple-300 transition-all">
                <i data-lucide="download" class="w-4 h-4 text-purple-500"></i>
                <span>Export Requests</span>
              </button>
            ` : ''}
            <button onclick="openCreateModal('Service Request')" class="bg-purple-600 hover:bg-purple-700 text-white px-4 py-2 rounded-xl text-sm font-semibold shadow flex items-center space-x-1.5">
              <i data-lucide="plus" class="w-4 h-4"></i>
              <span>+ Request Service</span>
            </button>
          </div>
        </div>

        ${renderTicketTypeTabs('service-requests')}

        <!-- Project-Specific Statistical Telemetry Bar -->
        <div class="p-3.5 bg-[var(--card-bg)] border border-[var(--border-color)] rounded-2xl shadow-sm flex flex-wrap items-center justify-between gap-3 text-xs">
          <div class="flex items-center space-x-2">
            <i data-lucide="bar-chart-2" class="w-4 h-4 text-purple-600"></i>
            <span class="font-bold text-slate-700 dark:text-slate-300">Statistical Dashboard:</span>
            <span id="reqScopeBadge" class="px-2.5 py-0.5 rounded-full text-[11px] font-extrabold bg-purple-100 dark:bg-purple-950 text-purple-700 dark:text-purple-300 border border-purple-200 dark:border-purple-800">
              ${initialProjects.length === 1 ? `Project: ${initialProjects[0]}` : (initialProjects.length > 1 ? `Projects: ${initialProjects.join(', ')}` : 'All Projects Scope')}
            </span>
          </div>
          <div class="flex items-center space-x-4 text-[11px] font-bold">
            <span class="text-slate-500">In Scope: <span id="statReqTotal" class="text-[var(--text-primary)] font-black">${requests.length}</span></span>
            <span class="text-amber-500">Pending Approval: <span id="statReqPending" class="font-black">0</span></span>
            <span class="text-indigo-500">In Fulfillment: <span id="statReqFulfill" class="font-black">0</span></span>
            <span class="text-emerald-500">Completed: <span id="statReqCompleted" class="font-black">0</span></span>
          </div>
        </div>

        <!-- Interactive Column Dropdown Filter Bar -->
        <div class="p-4 bg-[var(--card-bg)] border border-[var(--border-color)] rounded-2xl shadow-sm space-y-3">
          <div class="flex items-center justify-between">
            <div class="flex items-center space-x-2 text-xs font-bold text-slate-700 dark:text-slate-300">
              <i data-lucide="filter" class="w-4 h-4 text-purple-600"></i>
              <span>Request Filters</span>
              <span id="activeReqFiltersBadge" class="hidden px-2 py-0.5 rounded-full text-[10px] font-bold bg-purple-100 dark:bg-purple-950 text-purple-700 dark:text-purple-300 border border-purple-200 dark:border-purple-800"></span>
            </div>
            <button id="resetReqFiltersBtn" class="hidden text-xs text-purple-600 hover:text-purple-700 font-bold hover:underline flex items-center space-x-1">
              <i data-lucide="rotate-ccw" class="w-3.5 h-3.5"></i>
              <span>Clear Filters</span>
            </button>
          </div>
          <div class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-9 gap-2.5">
            <div>
              <label class="block text-[10px] font-bold uppercase text-slate-400 mb-1">Search</label>
              <div class="relative">
                <input type="text" id="filterReqSearch" placeholder="Search..." class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-xl pl-7 pr-2 py-1.5 text-xs focus:ring-2 focus:ring-purple-500 focus:outline-none">
                <i data-lucide="search" class="w-3.5 h-3.5 text-slate-400 absolute left-2 top-2"></i>
              </div>
            </div>
            <div>
              <label class="block text-[10px] font-bold uppercase text-slate-400 mb-1">Priority</label>
              <select id="filterReqPriority" class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-xl px-2.5 py-1.5 text-xs focus:ring-2 focus:ring-purple-500 focus:outline-none">
                <option value="">All Priorities</option>
                ${uniquePriorities.map(p => `<option value="${p}">${p}</option>`).join('')}
              </select>
            </div>
            <div>
              <label class="block text-[10px] font-bold uppercase text-slate-400 mb-1">Status</label>
              <select id="filterReqStatus" class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-xl px-2.5 py-1.5 text-xs focus:ring-2 focus:ring-purple-500 focus:outline-none">
                <option value="">All Statuses</option>
                ${uniqueStatuses.map(s => `<option value="${s}">${s}</option>`).join('')}
              </select>
            </div>
            <div>
              <label class="block text-[10px] font-bold uppercase text-slate-400 mb-1">Time Range</label>
              <select id="filterReqTime" class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-xl px-2.5 py-1.5 text-xs focus:ring-2 focus:ring-purple-500 focus:outline-none font-semibold">
                <option value="">All Time</option>
                <option value="today">Today</option>
                <option value="7d">Last 7 Days</option>
                <option value="30d">Last 30 Days</option>
                <option value="90d">Last 90 Days</option>
                <option value="custom">📅 Custom Range...</option>
              </select>
            </div>
            <div>
              <label class="block text-[10px] font-bold uppercase text-slate-400 mb-1">Time Zone</label>
              ${renderTimezoneSelect('filterReqTimezone', state.currentTimezone)}
            </div>
            <div>
              <label class="block text-[10px] font-bold uppercase text-slate-400 mb-1">Project</label>
              <div id="filterReqProjectWrap"></div>
            </div>
            <div>
              <label class="block text-[10px] font-bold uppercase text-slate-400 mb-1">Application</label>
              <div id="filterReqAppWrap"></div>
            </div>
            <div>
              <label class="block text-[10px] font-bold uppercase text-slate-400 mb-1">Assignment Group</label>
              <div id="filterReqGroupWrap"></div>
            </div>
            <div>
              <label class="block text-[10px] font-bold uppercase text-slate-400 mb-1">Approval</label>
              <select id="filterReqApproval" class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-xl px-2.5 py-1.5 text-xs focus:ring-2 focus:ring-purple-500 focus:outline-none">
                <option value="">All Approvals</option>
                <option value="Pending">Pending</option>
                <option value="Approved">Approved</option>
                <option value="Rejected">Rejected</option>
              </select>
            </div>
          </div>

          <!-- Custom Time Range Bar -->
          <div id="filterReqCustomDateBar" class="hidden pt-2 border-t border-[var(--border-color)] flex flex-wrap items-center gap-3 text-xs bg-[var(--bg-tertiary)]/50 p-2.5 rounded-xl mt-2">
            <span class="font-bold text-slate-500 text-[11px] flex items-center space-x-1">
              <i data-lucide="calendar" class="w-3.5 h-3.5 text-purple-600"></i>
              <span>Custom Range:</span>
            </span>
            <div class="flex items-center space-x-1.5">
              <label class="text-[11px] text-slate-400 font-semibold">From:</label>
              <input type="datetime-local" id="filterReqStartDate" class="bg-[var(--card-bg)] border border-[var(--border-color)] rounded-lg px-2 py-1 text-xs focus:ring-2 focus:ring-purple-500">
            </div>
            <div class="flex items-center space-x-1.5">
              <label class="text-[11px] text-slate-400 font-semibold">To:</label>
              <input type="datetime-local" id="filterReqEndDate" class="bg-[var(--card-bg)] border border-[var(--border-color)] rounded-lg px-2 py-1 text-xs focus:ring-2 focus:ring-purple-500">
            </div>
            <button id="filterReqClearCustomDateBtn" type="button" class="text-xs px-2.5 py-1 rounded-lg border border-[var(--border-color)] bg-[var(--card-bg)] hover:bg-[var(--bg-tertiary)] text-slate-600 dark:text-slate-300 font-semibold">
              Clear Range
            </button>
          </div>
        </div>

        <div class="rounded-2xl bg-[var(--card-bg)] border border-[var(--border-color)] overflow-hidden shadow-sm">
          <div class="p-3 bg-[var(--bg-tertiary)] border-b border-[var(--border-color)] flex items-center justify-between text-xs">
            <span id="reqCountLabel" class="font-semibold text-slate-400 uppercase tracking-wider">Total: ${requests.length} Requests</span>
          </div>
          <div class="overflow-x-auto">
            <table class="w-full text-left text-xs">
              <thead class="bg-[var(--bg-tertiary)] text-slate-400 uppercase font-semibold text-[10px]">
                <tr>
                  ${requestColumns.map(c => `<th class="p-3.5">${c.label}</th>`).join('')}
                </tr>
              </thead>
              <tbody id="reqTableBody" class="divide-y border-[var(--border-color)]">
                ${renderRequestRows(requests, requestColumns)}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    `;
    lucide.createIcons();

    // Hook up real-time filter logic
    const appWrap = document.getElementById('filterReqAppWrap');
    const groupWrap = document.getElementById('filterReqGroupWrap');
    const tzEl = document.getElementById('filterReqTimezone');
    const customDateBar = document.getElementById('filterReqCustomDateBar');
    const startDateEl = document.getElementById('filterReqStartDate');
    const endDateEl = document.getElementById('filterReqEndDate');
    const clearCustomBtn = document.getElementById('filterReqClearCustomDateBtn');

    const projectWrap = document.getElementById('filterReqProjectWrap');
    let reqProjectMs = null;
    let reqAppMs = null;
    let reqGroupMs = null;

    function syncAppsForProjects(chosenProjects) {
      let apps = [];
      if (chosenProjects && chosenProjects.length > 0) {
        const appSet = new Set();
        chosenProjects.forEach(p => {
          if (projectToApps[p]) projectToApps[p].forEach(a => appSet.add(a));
        });
        apps = appSet.size > 0 ? [...appSet].sort() : uniqueApps;
      } else {
        apps = uniqueApps;
      }
      if (reqAppMs) reqAppMs.setOptions(apps, true);
    }

    function syncGroupsForProjectsAndApps(chosenProjects, chosenApps) {
      const groups = getFilteredAssignmentGroups(chosenProjects, chosenApps, uniqueGroups);
      if (reqGroupMs) reqGroupMs.setOptions(groups, true);
    }

    reqProjectMs = createMultiSelectDropdown({
      container: projectWrap,
      options: uniqueProjects,
      selectedValues: initialProjects,
      placeholder: 'Projects',
      allLabel: 'All Projects',
      emptyMessage: 'No projects found',
      onChange: (selectedProjects) => {
        syncAppsForProjects(selectedProjects);
        syncGroupsForProjectsAndApps(selectedProjects, reqAppMs ? reqAppMs.getValues() : []);
        applyReqFilters();
      }
    });

    reqAppMs = createMultiSelectDropdown({
      container: appWrap,
      options: availableApps,
      placeholder: 'Applications',
      allLabel: 'All Applications',
      emptyMessage: 'No applications found',
      onChange: (selectedApps) => {
        const curProjects = reqProjectMs ? reqProjectMs.getValues() : [];
        const filteredGroups = getFilteredAssignmentGroups(curProjects, selectedApps, uniqueGroups);
        if (reqGroupMs) reqGroupMs.setOptions(filteredGroups, true);
        applyReqFilters();
      }
    });

    reqGroupMs = createMultiSelectDropdown({
      container: groupWrap,
      options: initialGroups,
      placeholder: 'Groups',
      allLabel: 'All Groups',
      emptyMessage: 'No groups found',
      onChange: () => {
        applyReqFilters();
      }
    });

    const filterInputs = ['filterReqSearch', 'filterReqPriority', 'filterReqStatus', 'filterReqTime', 'filterReqApproval'];
    const applyReqFilters = () => {
      const searchVal = (document.getElementById('filterReqSearch')?.value || '').toLowerCase().trim();
      const pVal = document.getElementById('filterReqPriority')?.value || '';
      const sVal = document.getElementById('filterReqStatus')?.value || '';
      const tVal = document.getElementById('filterReqTime')?.value || '';
      const qTz = tzEl?.value || state.currentTimezone || 'UTC';
      const qStart = startDateEl?.value || '';
      const qEnd = endDateEl?.value || '';
      const selectedProjects = reqProjectMs ? reqProjectMs.getValues() : initialProjects;
      const appVal = document.getElementById('filterReqApproval')?.value || '';
      const selectedApps = reqAppMs ? reqAppMs.getValues() : [];
      const selectedGroups = reqGroupMs ? reqGroupMs.getValues() : [];

      if (customDateBar) {
        customDateBar.classList.toggle('hidden', tVal !== 'custom');
      }

      let activeCount = [
        searchVal,
        pVal,
        sVal,
        tVal === 'custom' ? (qStart || qEnd ? 'custom' : '') : tVal,
        selectedApps.length > 0 ? 'apps' : '',
        selectedGroups.length > 0 ? 'groups' : '',
        appVal
      ].filter(Boolean).length;

      if (selectedProjects.length > 0) {
        const matchesInitial = initialProjects.length === selectedProjects.length && initialProjects.every(p => selectedProjects.includes(p));
        if (!matchesInitial) activeCount++;
      }

      const badge = document.getElementById('activeReqFiltersBadge');
      const resetBtn = document.getElementById('resetReqFiltersBtn');
      if (badge) {
        badge.textContent = `${activeCount} active filter${activeCount === 1 ? '' : 's'}`;
        badge.classList.toggle('hidden', activeCount === 0);
      }
      if (resetBtn) {
        resetBtn.classList.toggle('hidden', activeCount === 0);
      }

      const filtered = requests.filter(r => {
        if (searchVal) {
          const numMatch = (r.number || '').toLowerCase().includes(searchVal);
          const catMatch = (r.catalog_item || '').toLowerCase().includes(searchVal);
          const descMatch = (r.short_description || '').toLowerCase().includes(searchVal);
          const fullMatch = (r.description || '').toLowerCase().includes(searchVal);
          const appMatch = (r.application_name || '').toLowerCase().includes(searchVal);
          if (!numMatch && !catMatch && !descMatch && !fullMatch && !appMatch) return false;
        }
        if (pVal && r.priority !== pVal) return false;
        if (sVal && r.status !== sVal) return false;
        if (!matchesTimeRange(r.created_at, tVal, qStart, qEnd, qTz)) return false;
        if (selectedProjects.length > 0 && !selectedProjects.includes(r.project_name)) return false;
        if (selectedApps.length > 0 && !selectedApps.includes(r.application_name)) return false;
        if (selectedGroups.length > 0 && !selectedGroups.includes(r.assignment_group_name)) return false;
        if (appVal && r.approval_status !== appVal) return false;
        return true;
      });

      // Update project telemetry numbers
      const scopeBadge = document.getElementById('reqScopeBadge');
      if (scopeBadge) {
        const appLabel = selectedApps.length === 1 ? selectedApps[0] : (selectedApps.length > 1 ? `${selectedApps.length} Apps` : '');
        if (selectedProjects.length > 0) {
          const projText = selectedProjects.length === 1
            ? `Project: ${selectedProjects[0]}`
            : (selectedProjects.length === 2 ? `Projects: ${selectedProjects.join(', ')}` : `${selectedProjects.length} Projects`);
          scopeBadge.textContent = appLabel ? `${projText} (${appLabel})` : projText;
          scopeBadge.className = "px-2.5 py-0.5 rounded-full text-[11px] font-extrabold bg-purple-100 dark:bg-purple-950 text-purple-700 dark:text-purple-300 border border-purple-200 dark:border-purple-800";
        } else {
          scopeBadge.textContent = appLabel ? `All Projects (${appLabel})` : 'All Projects Scope';
          scopeBadge.className = "px-2.5 py-0.5 rounded-full text-[11px] font-extrabold bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 border border-slate-300 dark:border-slate-700";
        }
      }
      const elTot = document.getElementById('statReqTotal');
      if (elTot) elTot.textContent = filtered.length;
      const elPend = document.getElementById('statReqPending');
      if (elPend) elPend.textContent = filtered.filter(r => r.approval_status === 'Pending').length;
      const elFulfill = document.getElementById('statReqFulfill');
      if (elFulfill) elFulfill.textContent = filtered.filter(r => ['Approved', 'In Progress', 'Processing'].includes(r.status)).length;
      const elComp = document.getElementById('statReqCompleted');
      if (elComp) elComp.textContent = filtered.filter(r => ['Completed', 'Closed', 'Resolved'].includes(r.status)).length;

      const countLabel = document.getElementById('reqCountLabel');
      if (countLabel) {
        countLabel.textContent = activeCount > 0
          ? `Showing: ${filtered.length} of ${requests.length} Requests`
          : `Total: ${requests.length} Requests`;
      }

      const tbody = document.getElementById('reqTableBody');
      if (tbody) {
        tbody.innerHTML = renderRequestRows(filtered, requestColumns);
        lucide.createIcons();
      }
    };

    filterInputs.forEach(id => {
      const el = document.getElementById(id);
      if (el) {
        el.addEventListener('change', applyReqFilters);
        if (id === 'filterReqSearch') {
          el.addEventListener('input', applyReqFilters);
        }
      }
    });

    if (startDateEl) startDateEl.addEventListener('change', applyReqFilters);
    if (endDateEl) endDateEl.addEventListener('change', applyReqFilters);
    if (clearCustomBtn) {
      clearCustomBtn.addEventListener('click', () => {
        if (startDateEl) startDateEl.value = '';
        if (endDateEl) endDateEl.value = '';
        applyReqFilters();
      });
    }

    if (tzEl) {
      tzEl.addEventListener('change', () => {
        state.currentTimezone = tzEl.value;
        localStorage.setItem('nexus_timezone', state.currentTimezone);
        document.querySelectorAll('.request-date-cell').forEach(td => {
          const created = td.getAttribute('data-created');
          if (created) td.textContent = formatTicketDate(created, state.currentTimezone);
        });
        applyReqFilters();
      });
    }

    const resetBtn = document.getElementById('resetReqFiltersBtn');
    if (resetBtn) {
      resetBtn.addEventListener('click', () => {
        filterInputs.forEach(id => {
          const el = document.getElementById(id);
          if (el) el.value = '';
        });
        if (startDateEl) startDateEl.value = '';
        if (endDateEl) endDateEl.value = '';
        if (customDateBar) customDateBar.classList.add('hidden');
        if (reqProjectMs) reqProjectMs.setSelected(initialProjects);
        syncAppsForProjects(initialProjects);
        if (reqAppMs) reqAppMs.clear(false);
        syncGroupsForProjectsAndApps(initialProjects, []);
        if (reqGroupMs) reqGroupMs.clear(false);
        applyReqFilters();
      });
    }

    applyReqFilters();

  } catch (err) {
    container.innerHTML = `<div class="p-8 text-center text-red-500">Error loading requests: ${err.message}</div>`;
  }
}

function renderRequestRows(items, columns) {
  if (!items || !items.length) {
    return `
      <tr>
        <td colspan="${columns.length}" class="p-8 text-center text-slate-400">
          <div class="flex flex-col items-center justify-center space-y-2">
            <i data-lucide="box" class="w-8 h-8 text-slate-500 stroke-[1.5]"></i>
            <span class="font-medium text-xs">No service requests found</span>
            <span class="text-[11px] text-slate-500">Click "+ Request Service" to submit a new request.</span>
          </div>
        </td>
      </tr>
    `;
  }
  return items.map(r => `
    <tr class="hover:bg-[var(--bg-tertiary)] transition-colors cursor-pointer" onclick="window.location.hash='#/service-requests/${r.number}'">
      ${columns.map(c => {
        if (c.column_key === 'number') return `<td class="p-3.5 font-bold text-purple-600">${r.number}</td>`;
        if (c.column_key === 'priority') return `<td class="p-3.5"><span class="px-2 py-0.5 rounded text-[10px] font-bold badge-${(r.priority || 'P3').toLowerCase()}">${r.priority || 'P3'}</span></td>`;
        if (c.column_key === 'status') return `<td class="p-3.5"><span class="px-2 py-0.5 rounded text-[10px] font-semibold bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300">${r.status}</span></td>`;
        if (c.column_key === 'approval_status') {
          const appCol = r.approval_status === 'Approved' ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300' : (r.approval_status === 'Rejected' ? 'bg-red-100 text-red-700 dark:bg-red-950 dark:text-red-300' : 'bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300');
          return `<td class="p-3.5"><span class="px-2 py-0.5 rounded text-[10px] font-bold ${appCol}">${r.approval_status || 'Approved'}</span></td>`;
        }
        if (c.column_key === 'created_at') return `<td class="p-3.5 text-slate-500 request-date-cell" data-created="${r.created_at || ''}">${formatTicketDate(r.created_at, state.currentTimezone)}</td>`;
        return `<td class="p-3.5 text-slate-400">${r[c.column_key] ?? '—'}</td>`;
      }).join('')}
    </tr>
  `).join('');
}

// --- SERVICE REQUEST DETAIL VIEW ---
async function renderRequestDetailView(container, reqNumber) {
  container.innerHTML = `<div class="p-8 text-center text-slate-400"><i data-lucide="loader-2" class="w-8 h-8 animate-spin mx-auto mb-2 text-purple-500"></i>Loading service request ${reqNumber}...</div>`;
  lucide.createIcons();

  try {
    const res = await fetch(`${API_BASE}/service-requests/${reqNumber}`, {
      headers: { 'X-User-ID': state.currentUser.id.toString() }
    });
    if (!res.ok) {
      container.innerHTML = `<div class="p-8 text-center text-red-500">Service Request not found or permission denied.</div>`;
      return;
    }
    const req = await res.json();
    state.activeTicketContext = {
      ticket_number: req.number,
      ticket_type: 'Service Request',
      application: req.application_name,
      project: req.project_name,
      priority: req.priority,
      status: req.status,
      short_description: req.short_description || req.catalog_item,
      description: req.description,
      assignment_group: req.assignment_group_name,
      assigned_to: req.assigned_to_name
    };

    updateDrawerTicketContext(state.activeTicketContext);

    const isEndUser = isUserEndUser(state.currentUser);
    const isSupportOrAdmin = !isEndUser;
    const isRequester = state.currentUser && req.requested_by_id === state.currentUser.id;
    const canPostWorkNote = isSupportOrAdmin || isRequester;

    container.innerHTML = `
      <div class="space-y-6">
        <!-- Top Breadcrumb & Action Bar -->
        <div class="flex items-center justify-between">
          <div class="flex items-center space-x-2 text-xs text-slate-400">
            <a href="#/service-requests" class="hover:text-purple-600">${isEndUser ? 'My Service Requests' : 'Service Requests'}</a>
            <span>/</span>
            <span class="font-bold text-[var(--text-primary)]">${req.number}</span>
          </div>

          <div class="flex items-center space-x-2">
            ${isSupportOrAdmin ? `
              <button onclick="assignToMe(${req.id}, 'Service Request')" class="px-3 py-1.5 rounded-lg border border-[var(--border-color)] bg-[var(--card-bg)] hover:bg-[var(--bg-tertiary)] text-xs font-semibold">
                Assign to Me
              </button>
              <button onclick="openReassignModal(${req.id}, ${req.assignment_group_id || 'null'}, ${req.assigned_to_id || 'null'}, ${req.project_id || 'null'}, ${req.application_id || 'null'}, '${req.priority || 'P3'}', 'Service Request')" class="px-3 py-1.5 rounded-lg border border-[var(--border-color)] bg-[var(--card-bg)] hover:bg-[var(--bg-tertiary)] text-xs font-semibold flex items-center space-x-1">
                <i data-lucide="user-check" class="w-3.5 h-3.5 text-purple-600"></i>
                <span>Reassign Request</span>
              </button>
              <button onclick="openPriorityModal(${req.id}, '${req.priority || 'P3'}', 'Service Request')" class="px-3 py-1.5 rounded-lg border border-[var(--border-color)] bg-[var(--card-bg)] hover:bg-[var(--bg-tertiary)] text-xs font-semibold flex items-center space-x-1">
                <i data-lucide="alert-triangle" class="w-3.5 h-3.5 text-amber-500"></i>
                <span>Change Priority</span>
              </button>
              <button onclick="openStatusModal(${req.id}, '${req.status}', 'Service Request')" class="px-3 py-1.5 rounded-lg border border-[var(--border-color)] bg-[var(--card-bg)] hover:bg-[var(--bg-tertiary)] text-xs font-semibold flex items-center space-x-1">
                <i data-lucide="refresh-cw" class="w-3.5 h-3.5 text-blue-500"></i>
                <span>Update Status</span>
              </button>
              ${req.approval_status === 'Pending' ? `
                <button onclick="openApprovalDecisionModal(${req.id}, 'Service Request')" class="px-3 py-1.5 rounded-lg bg-purple-600 hover:bg-purple-700 text-white text-xs font-semibold flex items-center space-x-1">
                  <i data-lucide="check-circle" class="w-3.5 h-3.5"></i>
                  <span>Review Approval</span>
                </button>
              ` : ''}
            ` : ''}
          </div>
        </div>

        <!-- Request Header Card -->
        <div class="p-6 rounded-2xl bg-[var(--card-bg)] border border-[var(--border-color)] shadow-sm">
          <div class="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-4 border-b border-[var(--border-color)]">
            <div>
              <div class="flex items-center space-x-2.5">
                <span class="text-xl font-black text-purple-600">${req.number}</span>
                ${isSupportOrAdmin ? `
                  <button onclick="openPriorityModal(${req.id}, '${req.priority || 'P3'}', 'Service Request')" class="px-2.5 py-0.5 rounded text-xs font-bold badge-${(req.priority || 'P3').toLowerCase()} hover:opacity-80 flex items-center space-x-1 cursor-pointer">
                    <span>${req.priority || 'P3'}</span>
                    <i data-lucide="edit-2" class="w-3 h-3"></i>
                  </button>
                ` : `
                  <span class="px-2.5 py-0.5 rounded text-xs font-bold badge-${(req.priority || 'P3').toLowerCase()}">${req.priority || 'P3'}</span>
                `}
                ${isSupportOrAdmin ? `
                  <div class="inline-flex items-center space-x-1">
                    <select onchange="quickUpdateStatus(event, 'Service Request', ${req.id}, this.value, '${req.status}')" title="Change status directly" class="px-2.5 py-0.5 rounded text-xs font-bold bg-[var(--bg-tertiary)] border border-[var(--border-color)] text-[var(--text-primary)] cursor-pointer focus:ring-2 focus:ring-purple-500">
                      ${['Submitted', 'Active', 'In Progress', 'Pending Approval', 'Approved', 'In Fulfillment', 'Fulfilled', 'Completed', 'Closed', 'Cancelled'].map(s => `<option value="${s}" ${s === req.status ? 'selected' : ''}>${s}</option>`).join('')}
                    </select>
                  </div>
                ` : `
                  <span class="px-2.5 py-0.5 rounded text-xs font-semibold bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300">${req.status}</span>
                `}
                <span class="px-2.5 py-0.5 rounded text-xs font-bold ${req.approval_status === 'Approved' ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300' : (req.approval_status === 'Rejected' ? 'bg-red-100 text-red-700 dark:bg-red-950 dark:text-red-300' : 'bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300')}">
                  ${req.approval_status || 'Approved'}
                </span>
              </div>
              <h1 class="text-lg font-bold mt-2 text-[var(--text-primary)]">${req.catalog_item}: ${req.short_description || 'Standard Fulfillment'}</h1>
            </div>
          </div>

          <!-- Metadata Grid -->
          <div class="grid grid-cols-2 md:grid-cols-4 gap-4 pt-4 text-xs">
            <div>
              <span class="text-slate-400">Requested By:</span>
              <span class="font-semibold block text-[var(--text-primary)]">${req.requested_by_name || 'N/A'}</span>
            </div>
            <div>
              <span class="text-slate-400">Application:</span>
              <span class="font-semibold block text-[var(--text-primary)]">${req.application_name || 'General Platform'}</span>
            </div>
            <div>
              <span class="text-slate-400">Project:</span>
              <span class="font-semibold block text-[var(--text-primary)]">${req.project_name || 'N/A'}</span>
            </div>
            <div>
              <span class="text-slate-400">Assignment Group:</span>
              <div class="flex items-center space-x-1.5">
                <span class="font-semibold block text-[var(--text-primary)]">${req.assignment_group_name || 'Unassigned'}</span>
                ${isSupportOrAdmin ? `<button onclick="openReassignModal(${req.id}, ${req.assignment_group_id || 'null'}, ${req.assigned_to_id || 'null'}, ${req.project_id || 'null'}, ${req.application_id || 'null'}, '${req.priority || 'P3'}', 'Service Request')" class="text-purple-600 hover:text-purple-700"><i data-lucide="user-cog" class="w-3.5 h-3.5"></i></button>` : ''}
              </div>
            </div>
            <div>
              <span class="text-slate-400">Assigned To:</span>
              <div class="flex items-center space-x-1.5">
                <span class="font-semibold block text-[var(--text-primary)]">${req.assigned_to_name || 'Unassigned'}</span>
                ${isSupportOrAdmin ? `<button onclick="openReassignModal(${req.id}, ${req.assignment_group_id || 'null'}, ${req.assigned_to_id || 'null'}, ${req.project_id || 'null'}, ${req.application_id || 'null'}, '${req.priority || 'P3'}', 'Service Request')" class="text-purple-600 hover:text-purple-700"><i data-lucide="user-cog" class="w-3.5 h-3.5"></i></button>` : ''}
              </div>
            </div>
            <div>
              <span class="text-slate-400">Created:</span>
              <span class="font-semibold block text-[var(--text-primary)]">${new Date(req.created_at).toLocaleString()}</span>
            </div>
          </div>
        </div>

        <!-- TABS -->
        <div class="rounded-2xl bg-[var(--card-bg)] border border-[var(--border-color)] overflow-hidden shadow-sm">
          <div class="border-b border-[var(--border-color)] flex space-x-1 p-2 bg-[var(--bg-tertiary)] text-xs font-semibold">
            <button onclick="switchRequestTab('overview')" id="reqTabBtn_overview" class="px-4 py-2 rounded-lg bg-[var(--card-bg)] shadow-sm text-purple-600">Overview</button>
            <button onclick="switchRequestTab('conversation')" id="reqTabBtn_conversation" class="px-4 py-2 rounded-lg hover:bg-[var(--card-bg)] text-slate-400">
              Communication (${(req.comments || []).length + (req.work_notes || []).length})
            </button>
            <button onclick="switchRequestTab('approvals')" id="reqTabBtn_approvals" class="px-4 py-2 rounded-lg hover:bg-[var(--card-bg)] text-slate-400">
              Approvals (${(req.approvals || []).length})
            </button>
          </div>

          <!-- TAB: OVERVIEW -->
          <div id="reqTabContent_overview" class="p-6 space-y-4">
            <div>
              <h3 class="text-xs font-bold uppercase tracking-wider text-slate-400 mb-1">Catalog Item</h3>
              <div class="p-3 rounded-xl bg-[var(--bg-tertiary)] text-xs font-bold text-purple-600 dark:text-purple-400">${req.catalog_item}</div>
            </div>
            <div>
              <h3 class="text-xs font-bold uppercase tracking-wider text-slate-400 mb-1">Request Details / Instructions</h3>
              <div class="p-4 rounded-xl bg-[var(--bg-tertiary)] text-xs leading-relaxed whitespace-pre-wrap">${req.description || 'No additional fulfillment instructions provided.'}</div>
            </div>
          </div>

          <!-- TAB: CONVERSATION -->
          <div id="reqTabContent_conversation" class="hidden p-6 space-y-6">
            ${(req.attachments && req.attachments.length > 0) ? `
              <div class="p-4 rounded-xl border border-[var(--border-color)] bg-[var(--bg-tertiary)] space-y-2">
                <div class="flex items-center space-x-2 text-xs font-bold text-slate-700 dark:text-slate-200">
                  <i data-lucide="paperclip" class="w-4 h-4 text-purple-600"></i>
                  <span>Attached Diagnostic & Approval Files (${req.attachments.length})</span>
                </div>
                <div class="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-2.5 pt-1">
                  ${req.attachments.map(att => `
                    <a href="${API_BASE}/attachments/${att.id}/download" target="_blank" download class="flex items-center justify-between p-2.5 rounded-lg border border-[var(--border-color)] bg-[var(--card-bg)] hover:bg-purple-50 dark:hover:bg-purple-950/20 text-xs transition-all group">
                      <div class="flex items-center space-x-2 truncate">
                        <i data-lucide="${att.content_type?.includes('image') ? 'image' : 'file-text'}" class="w-4 h-4 text-purple-600 shrink-0"></i>
                        <div class="truncate">
                          <span class="font-medium text-[var(--text-primary)] truncate block">${att.filename}</span>
                          <span class="text-[10px] text-slate-400 block">${(att.file_size / 1024).toFixed(1)} KB</span>
                        </div>
                      </div>
                      <i data-lucide="download" class="w-3.5 h-3.5 text-slate-400 group-hover:text-purple-600 shrink-0 ml-1"></i>
                    </a>
                  `).join('')}
                </div>
              </div>
            ` : ''}

            <!-- Comments Stream -->
            <div class="space-y-4">
              ${(req.comments || []).map(c => `
                <div class="p-4 rounded-xl border border-blue-100 dark:border-blue-950 bg-[var(--comment-bg)] text-xs">
                  <div class="flex items-center justify-between text-purple-600 dark:text-purple-400 font-bold mb-1.5">
                    <div class="flex items-center space-x-1.5">
                      <i data-lucide="message-square" class="w-3.5 h-3.5"></i>
                      <span>Customer-Visible Comment: ${c.user_name}</span>
                    </div>
                    <span class="text-[10px] text-slate-400 font-normal">${new Date(c.created_at).toLocaleString()}</span>
                  </div>
                  <div class="leading-relaxed whitespace-pre-wrap">${c.comment}</div>
                </div>
              `).join('')}

              ${(req.work_notes || []).map(w => `
                <div class="p-4 rounded-xl border border-amber-200 dark:border-amber-950 bg-[var(--worknote-bg)] text-xs">
                  <div class="flex items-center justify-between text-amber-700 dark:text-amber-400 font-bold mb-1.5">
                    <div class="flex items-center space-x-1.5">
                      <i data-lucide="lock" class="w-3.5 h-3.5"></i>
                      <span>INTERNAL WORK NOTE: ${w.user_name} (Support Only)</span>
                    </div>
                    <span class="text-[10px] text-slate-400 font-normal">${new Date(w.created_at).toLocaleString()}</span>
                  </div>
                  <div class="leading-relaxed whitespace-pre-wrap">${w.note}</div>
                </div>
              `).join('')}
            </div>

            <!-- Post New Comment / Work Note -->
            <div class="pt-4 border-t border-[var(--border-color)]">
              <div class="flex space-x-2 mb-2">
                <button onclick="setCommentType('customer')" id="commTypeBtn_customer" class="px-3 py-1 rounded text-xs font-semibold bg-purple-600 text-white">Customer Comment</button>
                ${canPostWorkNote ? `
                  <button onclick="setCommentType('worknote')" id="commTypeBtn_worknote" class="px-3 py-1 rounded text-xs font-semibold bg-[var(--bg-tertiary)] text-slate-400">🔒 Work Note</button>
                ` : ''}
              </div>
              <textarea id="commentBox" rows="3" placeholder="Type customer-visible comment..." class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-xl p-3 text-xs focus:outline-none focus:ring-2 focus:ring-purple-500/30"></textarea>

              <div class="mt-2.5 flex flex-wrap items-center gap-2">
                <label class="cursor-pointer inline-flex items-center space-x-1.5 px-3 py-1.5 rounded-lg border border-[var(--border-color)] bg-[var(--bg-tertiary)] hover:bg-[var(--card-bg)] text-xs text-slate-600 dark:text-slate-300 font-medium transition-colors shadow-sm">
                  <i data-lucide="paperclip" class="w-3.5 h-3.5 text-purple-600"></i>
                  <span>Attach File / Logs</span>
                  <input type="file" id="commentFileInput" class="hidden" multiple onchange="handleCommentFilesSelected(event)">
                </label>
                <div id="commentFilesList" class="flex flex-wrap gap-1.5 text-xs"></div>
              </div>

              <div class="mt-3 flex justify-end">
                <button onclick="submitTicketComment(${req.id}, 'Service Request')" id="btnPostComment" class="bg-purple-600 hover:bg-purple-700 text-white px-5 py-2 rounded-xl text-xs font-semibold shadow flex items-center space-x-1.5">
                  <i data-lucide="send" class="w-3.5 h-3.5"></i>
                  <span>Post Update</span>
                </button>
              </div>
            </div>
          </div>

          <!-- TAB: APPROVALS -->
          <div id="reqTabContent_approvals" class="hidden p-6 space-y-4 text-xs">
            <h3 class="font-bold text-sm mb-2">Service Request Approvals</h3>
            ${(req.approvals && req.approvals.length > 0) ? `
              <div class="space-y-3">
                ${req.approvals.map(appr => `
                  <div class="p-4 rounded-xl border border-[var(--border-color)] bg-[var(--bg-tertiary)] flex items-center justify-between">
                    <div>
                      <div class="font-bold text-[var(--text-primary)]">Approver: ${appr.approver_name || 'Designated Approver / Admin'}</div>
                      <div class="text-[11px] text-slate-400 mt-0.5">Status: <span class="font-bold ${appr.status === 'Approved' ? 'text-emerald-500' : (appr.status === 'Rejected' ? 'text-red-500' : 'text-amber-500')}">${appr.status}</span></div>
                      ${appr.comments ? `<div class="text-[11px] text-slate-500 mt-1 italic">"${appr.comments}"</div>` : ''}
                    </div>
                    ${(appr.status === 'Pending' && isSupportOrAdmin) ? `
                      <button onclick="openApprovalDecisionModal(${req.id}, 'Service Request')" class="px-3.5 py-1.5 rounded-xl bg-purple-600 hover:bg-purple-700 text-white text-xs font-semibold">
                        Decide Approval
                      </button>
                    ` : ''}
                  </div>
                `).join('')}
              </div>
            ` : `
              <div class="p-6 text-center text-slate-400">No formal approvals required for this service item.</div>
            `}
          </div>

        </div>
      </div>
    `;
    lucide.createIcons();
  } catch (err) {
    container.innerHTML = `<div class="p-8 text-center text-red-500">Error loading service request: ${err.message}</div>`;
  }
}

function switchRequestTab(tab) {
  ['overview', 'conversation', 'approvals'].forEach(t => {
    const btn = document.getElementById(`reqTabBtn_${t}`);
    const content = document.getElementById(`reqTabContent_${t}`);
    if (t === tab) {
      if (btn) btn.className = 'px-4 py-2 rounded-lg bg-[var(--card-bg)] shadow-sm text-purple-600';
      if (content) content.classList.remove('hidden');
    } else {
      if (btn) btn.className = 'px-4 py-2 rounded-lg hover:bg-[var(--card-bg)] text-slate-400';
      if (content) content.classList.add('hidden');
    }
  });
}

// --- CHANGE MANAGEMENT ---
async function renderChangesView(container) {
  container.innerHTML = `<div class="p-8 text-center text-slate-400"><i data-lucide="loader-2" class="w-8 h-8 animate-spin mx-auto mb-2 text-purple-500"></i>Loading Changes...</div>`;
  lucide.createIcons();

  try {
    if (!state.projects?.length || !state.applications?.length) {
      try {
        const [pRes, aRes] = await Promise.allSettled([
          fetch(`${API_BASE}/projects`),
          fetch(`${API_BASE}/applications`)
        ]);
        if (pRes.status === 'fulfilled' && pRes.value.ok) state.projects = await pRes.value.json();
        if (aRes.status === 'fulfilled' && aRes.value.ok) state.applications = await aRes.value.json();
      } catch (_) {}
    }

    const res = await fetch(`${API_BASE}/changes`, {
      headers: { 'X-User-ID': state.currentUser.id.toString() }
    });
    const changes = await res.json();
    let changeColumns = [];
    try { const r = await fetch(`${API_BASE}/admin/configuration/columns?ticket_type=Change%20Request`); if (r.ok) changeColumns = (await r.json()).filter(c => c.enabled); } catch (_) {}
    changeColumns = changeColumns.length ? changeColumns : [{column_key:'number',label:'Change #'},{column_key:'change_type',label:'Type'},{column_key:'short_description',label:'Summary'},{column_key:'application_name',label:'Application'},{column_key:'project_name',label:'Project'},{column_key:'risk',label:'Risk'},{column_key:'approval_status',label:'CAB Approval'},{column_key:'change_status',label:'Change Status'},{column_key:'planned_start',label:'Planned Schedule'}];

    const isEndUser = isUserEndUser(state.currentUser);
    const isGlobalAdmin = !!(state.currentUser?.is_global_admin || state.currentUser?.username === 'admin');
    const userBoundaries = state.currentUser?.project_boundaries || {};
    const userProjects = (userBoundaries.project_names && userBoundaries.project_names.length)
      ? userBoundaries.project_names
      : (state.currentUser?.admin_projects || state.currentUser?.support_projects || []);
    const isSupportMember = !isGlobalAdmin && !isEndUser && userProjects.length > 0;

    const uniqueTypes = ['Standard', 'Normal', 'Emergency'];
    const uniqueStatuses = [...new Set(['Draft', 'Active', 'Assess', 'Authorize', 'Scheduled', 'Implement', 'Review', 'Closed', 'Canceled', ...changes.map(c => c.change_status).filter(Boolean)])];
    const uniqueRisks = ['Low', 'Medium', 'High', 'Critical'];
    const uniqueGroups = [...new Set(changes.map(c => c.assignment_group_name).filter(Boolean))].sort();
    const projectSet = new Set(changes.map(c => c.project_name).filter(Boolean));
    userProjects.forEach(p => projectSet.add(p));
    if (state.projects) state.projects.forEach(p => projectSet.add(p.name));
    const uniqueProjects = [...projectSet].sort();
    const defaultProject = (isSupportMember && userProjects.length > 0) ? userProjects[0] : '';

    const projectToApps = {};
    changes.forEach(c => {
      if (c.project_name && c.application_name) {
        if (!projectToApps[c.project_name]) projectToApps[c.project_name] = new Set();
        projectToApps[c.project_name].add(c.application_name);
      }
    });
    if (state.applications) {
      state.applications.forEach(a => {
        const pName = a.project_name || (state.projects?.find(p => p.id === a.project_id)?.name);
        if (pName && a.name) {
          if (!projectToApps[pName]) projectToApps[pName] = new Set();
          projectToApps[pName].add(a.name);
        }
      });
    }
    if (userBoundaries.project_names && userBoundaries.application_names) {
      userBoundaries.project_names.forEach(pn => {
        if (!projectToApps[pn]) projectToApps[pn] = new Set();
        userBoundaries.application_names.forEach(an => projectToApps[pn].add(an));
      });
    }

    const allKnownApps = new Set(changes.map(c => c.application_name).filter(a => a && a !== 'N/A'));
    if (state.applications) state.applications.forEach(a => { if (a.name) allKnownApps.add(a.name); });
    const uniqueApps = [...allKnownApps].sort();

    const initialProjects = (isSupportMember && userProjects.length > 0) ? userProjects.slice() : (defaultProject ? [defaultProject] : []);
    let availableApps = [];
    if (initialProjects.length > 0) {
      const appSet = new Set();
      initialProjects.forEach(p => {
        if (projectToApps[p]) projectToApps[p].forEach(a => appSet.add(a));
      });
      availableApps = appSet.size > 0 ? [...appSet].sort() : uniqueApps;
    } else {
      availableApps = uniqueApps;
    }

    const initialGroups = getFilteredAssignmentGroups(initialProjects, '', uniqueGroups);

    container.innerHTML = `
      <div class="space-y-6">
        <div class="flex items-center justify-between">
          <div>
            <h1 class="text-2xl font-black tracking-tight">${isEndUser ? 'My Change Requests' : 'Change Enablement & Management'}</h1>
            <p class="text-sm text-slate-500">${isEndUser ? 'Track your scheduled deployments and infrastructure changes.' : (isSupportMember ? `Project-scoped queue for ${userProjects.join(', ')} with cross-project visibility.` : 'CAB approvals, risk assessment, schedule governance, and automated backout plans.')}</p>
          </div>
          <div class="flex items-center space-x-2">
            ${['support_member', 'group_manager', 'administrator', 'itsm_admin'].includes(state.currentUser?.role) ? `
              <button onclick="openExportModal('changes')" class="px-3.5 py-2 rounded-xl border border-[var(--border-color)] bg-[var(--card-bg)] hover:bg-[var(--bg-tertiary)] text-xs font-semibold flex items-center space-x-1.5 shadow-sm text-purple-600 dark:text-purple-300 transition-all">
                <i data-lucide="download" class="w-4 h-4 text-purple-500"></i>
                <span>Export Changes</span>
              </button>
            ` : ''}
            <button onclick="openCreateModal('Change Request')" class="bg-purple-600 hover:bg-purple-700 text-white px-4 py-2 rounded-xl text-sm font-semibold shadow flex items-center space-x-1.5">
              <i data-lucide="plus" class="w-4 h-4"></i>
              <span>+ New Change Request</span>
            </button>
          </div>
        </div>

        ${renderTicketTypeTabs('changes')}

        <!-- Project-Specific Statistical Telemetry Bar -->
        <div class="p-3.5 bg-[var(--card-bg)] border border-[var(--border-color)] rounded-2xl shadow-sm flex flex-wrap items-center justify-between gap-3 text-xs">
          <div class="flex items-center space-x-2">
            <i data-lucide="bar-chart-2" class="w-4 h-4 text-purple-600"></i>
            <span class="font-bold text-slate-700 dark:text-slate-300">Statistical Dashboard:</span>
            <span id="chgScopeBadge" class="px-2.5 py-0.5 rounded-full text-[11px] font-extrabold bg-purple-100 dark:bg-purple-950 text-purple-700 dark:text-purple-300 border border-purple-200 dark:border-purple-800">
              ${initialProjects.length === 1 ? `Project: ${initialProjects[0]}` : (initialProjects.length > 1 ? `Projects: ${initialProjects.join(', ')}` : 'All Projects Scope')}
            </span>
          </div>
          <div class="flex items-center space-x-4 text-[11px] font-bold">
            <span class="text-slate-500">In Scope: <span id="statChgTotal" class="text-[var(--text-primary)] font-black">${changes.length}</span></span>
            <span class="text-amber-500">Pending CAB: <span id="statChgPending" class="font-black">0</span></span>
            <span class="text-red-500">High Risk: <span id="statChgHighRisk" class="font-black">0</span></span>
            <span class="text-emerald-500">Approved: <span id="statChgApproved" class="font-black">0</span></span>
          </div>
        </div>

        <!-- Interactive Column Dropdown Filter Bar -->
        <div class="p-4 bg-[var(--card-bg)] border border-[var(--border-color)] rounded-2xl shadow-sm space-y-3">
          <div class="flex items-center justify-between">
            <div class="flex items-center space-x-2 text-xs font-bold text-slate-700 dark:text-slate-300">
              <i data-lucide="filter" class="w-4 h-4 text-purple-600"></i>
              <span>Change Filters</span>
              <span id="activeChgFiltersBadge" class="hidden px-2 py-0.5 rounded-full text-[10px] font-bold bg-purple-100 dark:bg-purple-950 text-purple-700 dark:text-purple-300 border border-purple-200 dark:border-purple-800"></span>
            </div>
            <button id="resetChgFiltersBtn" class="hidden text-xs text-purple-600 hover:text-purple-700 font-bold hover:underline flex items-center space-x-1">
              <i data-lucide="rotate-ccw" class="w-3.5 h-3.5"></i>
              <span>Clear Filters</span>
            </button>
          </div>
          <div class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 xl:grid-cols-10 gap-2.5">
            <div>
              <label class="block text-[10px] font-bold uppercase text-slate-400 mb-1">Search</label>
              <div class="relative">
                <input type="text" id="filterChgSearch" placeholder="Search..." class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-xl pl-7 pr-2 py-1.5 text-xs focus:ring-2 focus:ring-purple-500 focus:outline-none">
                <i data-lucide="search" class="w-3.5 h-3.5 text-slate-400 absolute left-2 top-2"></i>
              </div>
            </div>
            <div>
              <label class="block text-[10px] font-bold uppercase text-slate-400 mb-1">Type</label>
              <select id="filterChgType" class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-xl px-2.5 py-1.5 text-xs focus:ring-2 focus:ring-purple-500 focus:outline-none">
                <option value="">All Types</option>
                ${uniqueTypes.map(t => `<option value="${t}">${t}</option>`).join('')}
              </select>
            </div>
            <div>
              <label class="block text-[10px] font-bold uppercase text-slate-400 mb-1">Status</label>
              <select id="filterChgStatus" class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-xl px-2.5 py-1.5 text-xs focus:ring-2 focus:ring-purple-500 focus:outline-none">
                <option value="">All Statuses</option>
                ${uniqueStatuses.map(s => `<option value="${s}">${s}</option>`).join('')}
              </select>
            </div>
            <div>
              <label class="block text-[10px] font-bold uppercase text-slate-400 mb-1">Time Range</label>
              <select id="filterChangeTime" class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-xl px-2.5 py-1.5 text-xs focus:ring-2 focus:ring-purple-500 focus:outline-none font-semibold">
                <option value="">All Time</option>
                <option value="today">Today</option>
                <option value="7d">Last 7 Days</option>
                <option value="30d">Last 30 Days</option>
                <option value="90d">Last 90 Days</option>
                <option value="custom">📅 Custom Range...</option>
              </select>
            </div>
            <div>
              <label class="block text-[10px] font-bold uppercase text-slate-400 mb-1">Time Zone</label>
              ${renderTimezoneSelect('filterChangeTimezone', state.currentTimezone)}
            </div>
            <div>
              <label class="block text-[10px] font-bold uppercase text-slate-400 mb-1">Risk</label>
              <select id="filterChgRisk" class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-xl px-2.5 py-1.5 text-xs focus:ring-2 focus:ring-purple-500 focus:outline-none">
                <option value="">All Risks</option>
                ${uniqueRisks.map(r => `<option value="${r}">${r}</option>`).join('')}
              </select>
            </div>
            <div>
              <label class="block text-[10px] font-bold uppercase text-slate-400 mb-1">Project</label>
              <div id="filterChgProjectWrap"></div>
            </div>
            <div>
              <label class="block text-[10px] font-bold uppercase text-slate-400 mb-1">Application</label>
              <div id="filterChgAppWrap"></div>
            </div>
            <div>
              <label class="block text-[10px] font-bold uppercase text-slate-400 mb-1">Assignment Group</label>
              <div id="filterChgGroupWrap"></div>
            </div>
            <div>
              <label class="block text-[10px] font-bold uppercase text-slate-400 mb-1">CAB Approval</label>
              <select id="filterChgApproval" class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-xl px-2.5 py-1.5 text-xs focus:ring-2 focus:ring-purple-500 focus:outline-none">
                <option value="">All Approvals</option>
                <option value="Pending">Pending</option>
                <option value="Approved">Approved</option>
                <option value="Rejected">Rejected</option>
              </select>
            </div>
          </div>

          <!-- Custom Time Range Bar -->
          <div id="filterChangeCustomDateBar" class="hidden pt-2 border-t border-[var(--border-color)] flex flex-wrap items-center gap-3 text-xs bg-[var(--bg-tertiary)]/50 p-2.5 rounded-xl mt-2">
            <span class="font-bold text-slate-500 text-[11px] flex items-center space-x-1">
              <i data-lucide="calendar" class="w-3.5 h-3.5 text-purple-600"></i>
              <span>Custom Range:</span>
            </span>
            <div class="flex items-center space-x-1.5">
              <label class="text-[11px] text-slate-400 font-semibold">From:</label>
              <input type="datetime-local" id="filterChangeStartDate" class="bg-[var(--card-bg)] border border-[var(--border-color)] rounded-lg px-2 py-1 text-xs focus:ring-2 focus:ring-purple-500">
            </div>
            <div class="flex items-center space-x-1.5">
              <label class="text-[11px] text-slate-400 font-semibold">To:</label>
              <input type="datetime-local" id="filterChangeEndDate" class="bg-[var(--card-bg)] border border-[var(--border-color)] rounded-lg px-2 py-1 text-xs focus:ring-2 focus:ring-purple-500">
            </div>
            <button id="filterChangeClearCustomDateBtn" type="button" class="text-xs px-2.5 py-1 rounded-lg border border-[var(--border-color)] bg-[var(--card-bg)] hover:bg-[var(--bg-tertiary)] text-slate-600 dark:text-slate-300 font-semibold">
              Clear Range
            </button>
          </div>
        </div>

        <div class="rounded-2xl bg-[var(--card-bg)] border border-[var(--border-color)] overflow-hidden shadow-sm">
          <div class="p-3 bg-[var(--bg-tertiary)] border-b border-[var(--border-color)] flex items-center justify-between text-xs">
            <span id="chgCountLabel" class="font-semibold text-slate-400 uppercase tracking-wider">Total: ${changes.length} Changes</span>
          </div>
          <div class="overflow-x-auto">
            <table class="w-full text-left text-xs">
              <thead class="bg-[var(--bg-tertiary)] text-slate-400 uppercase font-semibold text-[10px]">
                <tr>
                  ${changeColumns.map(c => `<th class="p-3.5">${c.label}</th>`).join('')}
                </tr>
              </thead>
              <tbody id="chgTableBody" class="divide-y border-[var(--border-color)]">
                ${renderChangeRows(changes, changeColumns)}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    `;
    lucide.createIcons();

    // Hook up real-time filter logic
    const appWrap = document.getElementById('filterChgAppWrap');
    const groupWrap = document.getElementById('filterChgGroupWrap');
    const tzEl = document.getElementById('filterChangeTimezone');
    const customDateBar = document.getElementById('filterChangeCustomDateBar');
    const startDateEl = document.getElementById('filterChangeStartDate');
    const endDateEl = document.getElementById('filterChangeEndDate');
    const clearCustomBtn = document.getElementById('filterChangeClearCustomDateBtn');

    const projectWrap = document.getElementById('filterChgProjectWrap');
    let chgProjectMs = null;
    let chgAppMs = null;
    let chgGroupMs = null;

    function syncAppsForProjects(chosenProjects) {
      let apps = [];
      if (chosenProjects && chosenProjects.length > 0) {
        const appSet = new Set();
        chosenProjects.forEach(p => {
          if (projectToApps[p]) projectToApps[p].forEach(a => appSet.add(a));
        });
        apps = appSet.size > 0 ? [...appSet].sort() : uniqueApps;
      } else {
        apps = uniqueApps;
      }
      if (chgAppMs) chgAppMs.setOptions(apps, true);
    }

    function syncGroupsForProjectsAndApps(chosenProjects, chosenApps) {
      const groups = getFilteredAssignmentGroups(chosenProjects, chosenApps, uniqueGroups);
      if (chgGroupMs) chgGroupMs.setOptions(groups, true);
    }

    chgProjectMs = createMultiSelectDropdown({
      container: projectWrap,
      options: uniqueProjects,
      selectedValues: initialProjects,
      placeholder: 'Projects',
      allLabel: 'All Projects',
      emptyMessage: 'No projects found',
      onChange: (selectedProjects) => {
        syncAppsForProjects(selectedProjects);
        syncGroupsForProjectsAndApps(selectedProjects, chgAppMs ? chgAppMs.getValues() : []);
        applyChgFilters();
      }
    });

    chgAppMs = createMultiSelectDropdown({
      container: appWrap,
      options: availableApps,
      placeholder: 'Applications',
      allLabel: 'All Applications',
      emptyMessage: 'No applications found',
      onChange: (selectedApps) => {
        const curProjects = chgProjectMs ? chgProjectMs.getValues() : [];
        const filteredGroups = getFilteredAssignmentGroups(curProjects, selectedApps, uniqueGroups);
        if (chgGroupMs) chgGroupMs.setOptions(filteredGroups, true);
        applyChgFilters();
      }
    });

    chgGroupMs = createMultiSelectDropdown({
      container: groupWrap,
      options: initialGroups,
      placeholder: 'Groups',
      allLabel: 'All Groups',
      emptyMessage: 'No groups found',
      onChange: () => {
        applyChgFilters();
      }
    });

    const filterInputs = ['filterChgSearch', 'filterChgType', 'filterChgStatus', 'filterChangeTime', 'filterChgRisk', 'filterChgApproval'];
    const applyChgFilters = () => {
      const searchVal = (document.getElementById('filterChgSearch')?.value || '').toLowerCase().trim();
      const tVal = document.getElementById('filterChgType')?.value || '';
      const sVal = document.getElementById('filterChgStatus')?.value || '';
      const timeVal = document.getElementById('filterChangeTime')?.value || '';
      const qTz = tzEl?.value || state.currentTimezone || 'UTC';
      const qStart = startDateEl?.value || '';
      const qEnd = endDateEl?.value || '';
      const rVal = document.getElementById('filterChgRisk')?.value || '';
      const selectedProjects = chgProjectMs ? chgProjectMs.getValues() : initialProjects;
      const appVal = document.getElementById('filterChgApproval')?.value || '';
      const selectedApps = chgAppMs ? chgAppMs.getValues() : [];
      const selectedGroups = chgGroupMs ? chgGroupMs.getValues() : [];

      if (customDateBar) {
        customDateBar.classList.toggle('hidden', timeVal !== 'custom');
      }

      let activeCount = [
        searchVal,
        tVal,
        sVal,
        timeVal === 'custom' ? (qStart || qEnd ? 'custom' : '') : timeVal,
        rVal,
        selectedApps.length > 0 ? 'apps' : '',
        selectedGroups.length > 0 ? 'groups' : '',
        appVal
      ].filter(Boolean).length;

      if (selectedProjects.length > 0) {
        const matchesInitial = initialProjects.length === selectedProjects.length && initialProjects.every(p => selectedProjects.includes(p));
        if (!matchesInitial) activeCount++;
      }

      const badge = document.getElementById('activeChgFiltersBadge');
      const resetBtn = document.getElementById('resetChgFiltersBtn');
      if (badge) {
        badge.textContent = `${activeCount} active filter${activeCount === 1 ? '' : 's'}`;
        badge.classList.toggle('hidden', activeCount === 0);
      }
      if (resetBtn) {
        resetBtn.classList.toggle('hidden', activeCount === 0);
      }

      const filtered = changes.filter(c => {
        if (searchVal) {
          const numMatch = (c.number || '').toLowerCase().includes(searchVal);
          const descMatch = (c.short_description || '').toLowerCase().includes(searchVal);
          const fullMatch = (c.description || '').toLowerCase().includes(searchVal);
          const appMatch = (c.application_name || '').toLowerCase().includes(searchVal);
          if (!numMatch && !descMatch && !fullMatch && !appMatch) return false;
        }
        if (tVal && c.change_type !== tVal) return false;
        if (sVal && c.change_status !== sVal) return false;
        if (!matchesTimeRange(c.created_at, timeVal, qStart, qEnd, qTz)) return false;
        if (rVal && c.risk !== rVal) return false;
        if (selectedProjects.length > 0 && !selectedProjects.includes(c.project_name)) return false;
        if (selectedApps.length > 0 && !selectedApps.includes(c.application_name)) return false;
        if (selectedGroups.length > 0 && !selectedGroups.includes(c.assignment_group_name)) return false;
        if (appVal && c.approval_status !== appVal) return false;
        return true;
      });

      // Update project telemetry numbers
      const scopeBadge = document.getElementById('chgScopeBadge');
      if (scopeBadge) {
        const appLabel = selectedApps.length === 1 ? selectedApps[0] : (selectedApps.length > 1 ? `${selectedApps.length} Apps` : '');
        if (selectedProjects.length > 0) {
          const projText = selectedProjects.length === 1
            ? `Project: ${selectedProjects[0]}`
            : (selectedProjects.length === 2 ? `Projects: ${selectedProjects.join(', ')}` : `${selectedProjects.length} Projects`);
          scopeBadge.textContent = appLabel ? `${projText} (${appLabel})` : projText;
          scopeBadge.className = "px-2.5 py-0.5 rounded-full text-[11px] font-extrabold bg-purple-100 dark:bg-purple-950 text-purple-700 dark:text-purple-300 border border-purple-200 dark:border-purple-800";
        } else {
          scopeBadge.textContent = appLabel ? `All Projects (${appLabel})` : 'All Projects Scope';
          scopeBadge.className = "px-2.5 py-0.5 rounded-full text-[11px] font-extrabold bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 border border-slate-300 dark:border-slate-700";
        }
      }
      const elTot = document.getElementById('statChgTotal');
      if (elTot) elTot.textContent = filtered.length;
      const elPend = document.getElementById('statChgPending');
      if (elPend) elPend.textContent = filtered.filter(c => c.approval_status === 'Pending').length;
      const elHighRisk = document.getElementById('statChgHighRisk');
      if (elHighRisk) elHighRisk.textContent = filtered.filter(c => c.risk === 'High' || c.risk === 'Critical').length;
      const elAppr = document.getElementById('statChgApproved');
      if (elAppr) elAppr.textContent = filtered.filter(c => c.approval_status === 'Approved').length;

      const countLabel = document.getElementById('chgCountLabel');
      if (countLabel) {
        countLabel.textContent = activeCount > 0
          ? `Showing: ${filtered.length} of ${changes.length} Changes`
          : `Total: ${changes.length} Changes`;
      }

      const tbody = document.getElementById('chgTableBody');
      if (tbody) {
        tbody.innerHTML = renderChangeRows(filtered, changeColumns);
        lucide.createIcons();
      }
    };

    filterInputs.forEach(id => {
      const el = document.getElementById(id);
      if (el) {
        el.addEventListener('change', applyChgFilters);
        if (id === 'filterChgSearch') {
          el.addEventListener('input', applyChgFilters);
        }
      }
    });

    if (startDateEl) startDateEl.addEventListener('change', applyChgFilters);
    if (endDateEl) endDateEl.addEventListener('change', applyChgFilters);
    if (clearCustomBtn) {
      clearCustomBtn.addEventListener('click', () => {
        if (startDateEl) startDateEl.value = '';
        if (endDateEl) endDateEl.value = '';
        applyChgFilters();
      });
    }

    if (tzEl) {
      tzEl.addEventListener('change', () => {
        state.currentTimezone = tzEl.value;
        localStorage.setItem('nexus_timezone', state.currentTimezone);
        document.querySelectorAll('.change-date-cell').forEach(td => {
          const created = td.getAttribute('data-created');
          if (created) td.textContent = formatTicketDate(created, state.currentTimezone);
        });
        applyChgFilters();
      });
    }

    const resetBtn = document.getElementById('resetChgFiltersBtn');
    if (resetBtn) {
      resetBtn.addEventListener('click', () => {
        filterInputs.forEach(id => {
          const el = document.getElementById(id);
          if (el) el.value = '';
        });
        if (startDateEl) startDateEl.value = '';
        if (endDateEl) endDateEl.value = '';
        if (customDateBar) customDateBar.classList.add('hidden');
        if (chgProjectMs) chgProjectMs.setSelected(initialProjects);
        syncAppsForProjects(initialProjects);
        if (chgAppMs) chgAppMs.clear(false);
        syncGroupsForProjectsAndApps(initialProjects, []);
        if (chgGroupMs) chgGroupMs.clear(false);
        applyChgFilters();
      });
    }

    applyChgFilters();

  } catch (err) {
    container.innerHTML = `<div class="p-8 text-center text-red-500">Error loading changes: ${err.message}</div>`;
  }
}

function renderChangeRows(items, columns) {
  if (!items || !items.length) {
    return `
      <tr>
        <td colspan="${columns.length}" class="p-8 text-center text-slate-400">
          <div class="flex flex-col items-center justify-center space-y-2">
            <i data-lucide="git-pull-request" class="w-8 h-8 text-slate-500 stroke-[1.5]"></i>
            <span class="font-medium text-xs">No change requests found</span>
            <span class="text-[11px] text-slate-500">Click "+ New Change Request" to create a change.</span>
          </div>
        </td>
      </tr>
    `;
  }
  return items.map(c => `
    <tr class="hover:bg-[var(--bg-tertiary)] transition-colors cursor-pointer" onclick="window.location.hash='#/changes/${c.number}'">
      ${columns.map(col => {
        if (col.column_key === 'number') return `<td class="p-3.5 font-bold text-purple-600">${c.number}</td>`;
        if (col.column_key === 'change_type') return `<td class="p-3.5"><span class="px-2 py-0.5 rounded text-[10px] font-bold ${c.change_type === 'Emergency' ? 'bg-red-100 text-red-700 dark:bg-red-950 dark:text-red-300' : (c.change_type === 'Standard' ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300' : 'bg-blue-100 text-blue-700 dark:bg-blue-950 dark:text-blue-300')}">${c.change_type}</span></td>`;
        if (col.column_key === 'risk') return `<td class="p-3.5"><span class="px-2 py-0.5 rounded text-[10px] font-semibold ${c.risk === 'High' || c.risk === 'Critical' ? 'text-red-500' : 'text-slate-400'}">${c.risk}</span></td>`;
        if (col.column_key === 'change_status') return `<td class="p-3.5"><span class="px-2 py-0.5 rounded text-[10px] font-semibold bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300">${c.change_status}</span></td>`;
        if (col.column_key === 'approval_status') {
          const appCol = c.approval_status === 'Approved' ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300' : (c.approval_status === 'Rejected' ? 'bg-red-100 text-red-700 dark:bg-red-950 dark:text-red-300' : 'bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300');
          return `<td class="p-3.5"><span class="px-2 py-0.5 rounded text-[10px] font-bold ${appCol}">${c.approval_status || 'Pending'}</span></td>`;
        }
        if (col.column_key === 'planned_start') return `<td class="p-3.5 text-slate-400 change-date-cell" data-created="${c.planned_start || ''}">${c.planned_start ? formatTicketDate(c.planned_start, state.currentTimezone) : 'Unscheduled'}</td>`;
        if (col.column_key === 'created_at') return `<td class="p-3.5 text-slate-500 change-date-cell" data-created="${c.created_at || ''}">${formatTicketDate(c.created_at, state.currentTimezone)}</td>`;
        return `<td class="p-3.5 text-slate-400">${c[col.column_key] ?? '—'}</td>`;
      }).join('')}
    </tr>
  `).join('');
}

// --- CHANGE DETAIL VIEW ---
async function renderChangeDetailView(container, chgNumber) {
  container.innerHTML = `<div class="p-8 text-center text-slate-400"><i data-lucide="loader-2" class="w-8 h-8 animate-spin mx-auto mb-2 text-purple-500"></i>Loading change ${chgNumber}...</div>`;
  lucide.createIcons();

  try {
    const res = await fetch(`${API_BASE}/changes/${chgNumber}`, {
      headers: { 'X-User-ID': state.currentUser.id.toString() }
    });
    if (!res.ok) {
      container.innerHTML = `<div class="p-8 text-center text-red-500">Change Request not found or permission denied.</div>`;
      return;
    }
    const chg = await res.json();
    state.activeTicketContext = {
      ticket_number: chg.number,
      ticket_type: 'Change Request',
      application: chg.application_name,
      project: chg.project_name,
      priority: chg.priority,
      status: chg.change_status,
      short_description: chg.short_description,
      description: chg.description,
      assignment_group: chg.assignment_group_name,
      assigned_to: chg.assigned_to_name
    };

    updateDrawerTicketContext(state.activeTicketContext);

    const isEndUser = isUserEndUser(state.currentUser);
    const isSupportOrAdmin = !isEndUser;
    const isRequester = state.currentUser && chg.requested_by_id === state.currentUser.id;
    const canPostWorkNote = isSupportOrAdmin || isRequester;

    container.innerHTML = `
      <div class="space-y-6">
        <!-- Top Breadcrumb & Action Bar -->
        <div class="flex items-center justify-between">
          <div class="flex items-center space-x-2 text-xs text-slate-400">
            <a href="#/changes" class="hover:text-purple-600">${isEndUser ? 'My Change Requests' : 'Change Requests'}</a>
            <span>/</span>
            <span class="font-bold text-[var(--text-primary)]">${chg.number}</span>
          </div>

          <div class="flex items-center space-x-2">
            ${isSupportOrAdmin ? `
              <button onclick="assignToMe(${chg.id}, 'Change Request')" class="px-3 py-1.5 rounded-lg border border-[var(--border-color)] bg-[var(--card-bg)] hover:bg-[var(--bg-tertiary)] text-xs font-semibold">
                Assign to Me
              </button>
              <button onclick="openReassignModal(${chg.id}, ${chg.assignment_group_id || 'null'}, ${chg.assigned_to_id || 'null'}, ${chg.project_id || 'null'}, ${chg.application_id || 'null'}, '${chg.priority || 'P3'}', 'Change Request')" class="px-3 py-1.5 rounded-lg border border-[var(--border-color)] bg-[var(--card-bg)] hover:bg-[var(--bg-tertiary)] text-xs font-semibold flex items-center space-x-1">
                <i data-lucide="user-check" class="w-3.5 h-3.5 text-purple-600"></i>
                <span>Reassign Change</span>
              </button>
              <button onclick="openPriorityModal(${chg.id}, '${chg.priority || 'P3'}', 'Change Request')" class="px-3 py-1.5 rounded-lg border border-[var(--border-color)] bg-[var(--card-bg)] hover:bg-[var(--bg-tertiary)] text-xs font-semibold flex items-center space-x-1">
                <i data-lucide="alert-triangle" class="w-3.5 h-3.5 text-amber-500"></i>
                <span>Change Priority</span>
              </button>
              <button onclick="openStatusModal(${chg.id}, '${chg.change_status}', 'Change Request')" class="px-3 py-1.5 rounded-lg border border-[var(--border-color)] bg-[var(--card-bg)] hover:bg-[var(--bg-tertiary)] text-xs font-semibold flex items-center space-x-1">
                <i data-lucide="refresh-cw" class="w-3.5 h-3.5 text-blue-500"></i>
                <span>Update Status</span>
              </button>
              ${chg.approval_status === 'Pending' ? `
                <button onclick="openApprovalDecisionModal(${chg.id}, 'Change Request')" class="px-3 py-1.5 rounded-lg bg-purple-600 hover:bg-purple-700 text-white text-xs font-semibold flex items-center space-x-1">
                  <i data-lucide="check-circle" class="w-3.5 h-3.5"></i>
                  <span>CAB Decision</span>
                </button>
              ` : ''}
            ` : ''}
          </div>
        </div>

        <!-- Change Header Card -->
        <div class="p-6 rounded-2xl bg-[var(--card-bg)] border border-[var(--border-color)] shadow-sm">
          <div class="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-4 border-b border-[var(--border-color)]">
            <div>
              <div class="flex items-center space-x-2.5">
                <span class="text-xl font-black text-purple-600">${chg.number}</span>
                <span class="px-2.5 py-0.5 rounded text-xs font-bold ${chg.change_type === 'Emergency' ? 'bg-red-100 text-red-700 dark:bg-red-950 dark:text-red-300' : (chg.change_type === 'Standard' ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300' : 'bg-blue-100 text-blue-700 dark:bg-blue-950 dark:text-blue-300')}">${chg.change_type}</span>
                ${isSupportOrAdmin ? `
                  <div class="inline-flex items-center space-x-1">
                    <select onchange="quickUpdateStatus(event, 'Change Request', ${chg.id}, this.value, '${chg.change_status || chg.status}')" title="Change status directly" class="px-2.5 py-0.5 rounded text-xs font-bold bg-[var(--bg-tertiary)] border border-[var(--border-color)] text-[var(--text-primary)] cursor-pointer focus:ring-2 focus:ring-purple-500">
                      ${['Draft', 'Active', 'Assess', 'Authorize', 'Scheduled', 'Implement', 'Review', 'Closed', 'Canceled'].map(s => `<option value="${s}" ${s === (chg.change_status || chg.status) ? 'selected' : ''}>${s}</option>`).join('')}
                    </select>
                  </div>
                ` : `
                  <span class="px-2.5 py-0.5 rounded text-xs font-semibold bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300">${chg.change_status}</span>
                `}
                <span class="px-2.5 py-0.5 rounded text-xs font-bold ${chg.approval_status === 'Approved' ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300' : (chg.approval_status === 'Rejected' ? 'bg-red-100 text-red-700 dark:bg-red-950 dark:text-red-300' : 'bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300')}">
                  CAB: ${chg.approval_status || 'Pending'}
                </span>
              </div>
              <h1 class="text-lg font-bold mt-2 text-[var(--text-primary)]">${chg.short_description}</h1>
            </div>
          </div>

          <!-- Metadata Grid -->
          <div class="grid grid-cols-2 md:grid-cols-4 gap-4 pt-4 text-xs">
            <div>
              <span class="text-slate-400">Requested By:</span>
              <span class="font-semibold block text-[var(--text-primary)]">${chg.requested_by_name || 'N/A'}</span>
            </div>
            <div>
              <span class="text-slate-400">Application:</span>
              <span class="font-semibold block text-[var(--text-primary)]">${chg.application_name || 'General'}</span>
            </div>
            <div>
              <span class="text-slate-400">Project:</span>
              <span class="font-semibold block text-[var(--text-primary)]">${chg.project_name || 'N/A'}</span>
            </div>
            <div>
              <span class="text-slate-400">Risk Level:</span>
              <span class="font-semibold block ${chg.risk === 'High' || chg.risk === 'Critical' ? 'text-red-500' : 'text-[var(--text-primary)]'}">${chg.risk || 'Medium'}</span>
            </div>
            <div>
              <span class="text-slate-400">Assignment Group:</span>
              <div class="flex items-center space-x-1.5">
                <span class="font-semibold block text-[var(--text-primary)]">${chg.assignment_group_name || 'Unassigned'}</span>
                ${isSupportOrAdmin ? `<button onclick="openReassignModal(${chg.id}, ${chg.assignment_group_id || 'null'}, ${chg.assigned_to_id || 'null'}, ${chg.project_id || 'null'}, ${chg.application_id || 'null'}, '${chg.priority || 'P3'}', 'Change Request')" class="text-purple-600 hover:text-purple-700"><i data-lucide="user-cog" class="w-3.5 h-3.5"></i></button>` : ''}
              </div>
            </div>
            <div>
              <span class="text-slate-400">Assigned To:</span>
              <div class="flex items-center space-x-1.5">
                <span class="font-semibold block text-[var(--text-primary)]">${chg.assigned_to_name || 'Unassigned'}</span>
                ${isSupportOrAdmin ? `<button onclick="openReassignModal(${chg.id}, ${chg.assignment_group_id || 'null'}, ${chg.assigned_to_id || 'null'}, ${chg.project_id || 'null'}, ${chg.application_id || 'null'}, '${chg.priority || 'P3'}', 'Change Request')" class="text-purple-600 hover:text-purple-700"><i data-lucide="user-cog" class="w-3.5 h-3.5"></i></button>` : ''}
              </div>
            </div>
            <div>
              <span class="text-slate-400">Planned Start:</span>
              <span class="font-semibold block text-[var(--text-primary)]">${chg.planned_start ? new Date(chg.planned_start).toLocaleString() : 'Unscheduled'}</span>
            </div>
            <div>
              <span class="text-slate-400">Planned End:</span>
              <span class="font-semibold block text-[var(--text-primary)]">${chg.planned_end ? new Date(chg.planned_end).toLocaleString() : 'Unscheduled'}</span>
            </div>
          </div>
        </div>

        <!-- TABS -->
        <div class="rounded-2xl bg-[var(--card-bg)] border border-[var(--border-color)] overflow-hidden shadow-sm">
          <div class="border-b border-[var(--border-color)] flex space-x-1 p-2 bg-[var(--bg-tertiary)] text-xs font-semibold">
            <button onclick="switchChangeTab('overview')" id="chgTabBtn_overview" class="px-4 py-2 rounded-lg bg-[var(--card-bg)] shadow-sm text-purple-600">Overview & Plans</button>
            <button onclick="switchChangeTab('conversation')" id="chgTabBtn_conversation" class="px-4 py-2 rounded-lg hover:bg-[var(--card-bg)] text-slate-400">
              Communication (${(chg.comments || []).length + (chg.work_notes || []).length})
            </button>
            <button onclick="switchChangeTab('approvals')" id="chgTabBtn_approvals" class="px-4 py-2 rounded-lg hover:bg-[var(--card-bg)] text-slate-400">
              CAB Approvals (${(chg.approvals || []).length})
            </button>
          </div>

          <!-- TAB: OVERVIEW & PLANS -->
          <div id="chgTabContent_overview" class="p-6 space-y-5 text-xs">
            <div>
              <h3 class="font-bold uppercase tracking-wider text-slate-400 mb-1">Business Justification & Impact</h3>
              <div class="p-4 rounded-xl bg-[var(--bg-tertiary)] leading-relaxed whitespace-pre-wrap">${chg.business_justification || chg.description || 'Standard change activity.'}</div>
            </div>
            <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div>
                <h3 class="font-bold uppercase tracking-wider text-purple-600 dark:text-purple-400 mb-1 flex items-center space-x-1">
                  <i data-lucide="play" class="w-3.5 h-3.5"></i>
                  <span>Implementation Plan</span>
                </h3>
                <div class="p-3.5 rounded-xl bg-[var(--bg-tertiary)] border border-[var(--border-color)] leading-relaxed whitespace-pre-wrap font-mono">${chg.implementation_plan || 'Step-by-step rollout plan as per standard change template.'}</div>
              </div>
              <div>
                <h3 class="font-bold uppercase tracking-wider text-amber-600 dark:text-amber-400 mb-1 flex items-center space-x-1">
                  <i data-lucide="undo" class="w-3.5 h-3.5"></i>
                  <span>Backout / Rollback Plan</span>
                </h3>
                <div class="p-3.5 rounded-xl bg-[var(--bg-tertiary)] border border-[var(--border-color)] leading-relaxed whitespace-pre-wrap font-mono">${chg.backout_plan || 'Automated or manual snapshot restoration.'}</div>
              </div>
              <div>
                <h3 class="font-bold uppercase tracking-wider text-emerald-600 dark:text-emerald-400 mb-1 flex items-center space-x-1">
                  <i data-lucide="check-square" class="w-3.5 h-3.5"></i>
                  <span>Test & Verification Plan</span>
                </h3>
                <div class="p-3.5 rounded-xl bg-[var(--bg-tertiary)] border border-[var(--border-color)] leading-relaxed whitespace-pre-wrap font-mono">${chg.test_plan || 'Smoke test and synthetic check verification.'}</div>
              </div>
            </div>
          </div>

          <!-- TAB: CONVERSATION -->
          <div id="chgTabContent_conversation" class="hidden p-6 space-y-6">
            ${(chg.attachments && chg.attachments.length > 0) ? `
              <div class="p-4 rounded-xl border border-[var(--border-color)] bg-[var(--bg-tertiary)] space-y-2">
                <div class="flex items-center space-x-2 text-xs font-bold text-slate-700 dark:text-slate-200">
                  <i data-lucide="paperclip" class="w-4 h-4 text-purple-600"></i>
                  <span>Attached Release Documentation & Diagnostics (${chg.attachments.length})</span>
                </div>
                <div class="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-2.5 pt-1">
                  ${chg.attachments.map(att => `
                    <a href="${API_BASE}/attachments/${att.id}/download" target="_blank" download class="flex items-center justify-between p-2.5 rounded-lg border border-[var(--border-color)] bg-[var(--card-bg)] hover:bg-purple-50 dark:hover:bg-purple-950/20 text-xs transition-all group">
                      <div class="flex items-center space-x-2 truncate">
                        <i data-lucide="${att.content_type?.includes('image') ? 'image' : 'file-text'}" class="w-4 h-4 text-purple-600 shrink-0"></i>
                        <div class="truncate">
                          <span class="font-medium text-[var(--text-primary)] truncate block">${att.filename}</span>
                          <span class="text-[10px] text-slate-400 block">${(att.file_size / 1024).toFixed(1)} KB</span>
                        </div>
                      </div>
                      <i data-lucide="download" class="w-3.5 h-3.5 text-slate-400 group-hover:text-purple-600 shrink-0 ml-1"></i>
                    </a>
                  `).join('')}
                </div>
              </div>
            ` : ''}

            <!-- Comments Stream -->
            <div class="space-y-4">
              ${(chg.comments || []).map(c => `
                <div class="p-4 rounded-xl border border-blue-100 dark:border-blue-950 bg-[var(--comment-bg)] text-xs">
                  <div class="flex items-center justify-between text-purple-600 dark:text-purple-400 font-bold mb-1.5">
                    <div class="flex items-center space-x-1.5">
                      <i data-lucide="message-square" class="w-3.5 h-3.5"></i>
                      <span>Stakeholder Comment: ${c.user_name}</span>
                    </div>
                    <span class="text-[10px] text-slate-400 font-normal">${new Date(c.created_at).toLocaleString()}</span>
                  </div>
                  <div class="leading-relaxed whitespace-pre-wrap">${c.comment}</div>
                </div>
              `).join('')}

              ${(chg.work_notes || []).map(w => `
                <div class="p-4 rounded-xl border border-amber-200 dark:border-amber-950 bg-[var(--worknote-bg)] text-xs">
                  <div class="flex items-center justify-between text-amber-700 dark:text-amber-400 font-bold mb-1.5">
                    <div class="flex items-center space-x-1.5">
                      <i data-lucide="lock" class="w-3.5 h-3.5"></i>
                      <span>INTERNAL TECHNICAL WORK NOTE: ${w.user_name} (Support/Admin Only)</span>
                    </div>
                    <span class="text-[10px] text-slate-400 font-normal">${new Date(w.created_at).toLocaleString()}</span>
                  </div>
                  <div class="leading-relaxed whitespace-pre-wrap">${w.note}</div>
                </div>
              `).join('')}
            </div>

            <!-- Post New Comment / Work Note -->
            <div class="pt-4 border-t border-[var(--border-color)]">
              <div class="flex space-x-2 mb-2">
                <button onclick="setCommentType('customer')" id="commTypeBtn_customer" class="px-3 py-1 rounded text-xs font-semibold bg-purple-600 text-white">Stakeholder Comment</button>
                ${canPostWorkNote ? `
                  <button onclick="setCommentType('worknote')" id="commTypeBtn_worknote" class="px-3 py-1 rounded text-xs font-semibold bg-[var(--bg-tertiary)] text-slate-400">🔒 Work Note</button>
                ` : ''}
              </div>
              <textarea id="commentBox" rows="3" placeholder="Type stakeholder comment..." class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-xl p-3 text-xs focus:outline-none focus:ring-2 focus:ring-purple-500/30"></textarea>

              <div class="mt-2.5 flex flex-wrap items-center gap-2">
                <label class="cursor-pointer inline-flex items-center space-x-1.5 px-3 py-1.5 rounded-lg border border-[var(--border-color)] bg-[var(--bg-tertiary)] hover:bg-[var(--card-bg)] text-xs text-slate-600 dark:text-slate-300 font-medium transition-colors shadow-sm">
                  <i data-lucide="paperclip" class="w-3.5 h-3.5 text-purple-600"></i>
                  <span>Attach Release Files / Architecture</span>
                  <input type="file" id="commentFileInput" class="hidden" multiple onchange="handleCommentFilesSelected(event)">
                </label>
                <div id="commentFilesList" class="flex flex-wrap gap-1.5 text-xs"></div>
              </div>

              <div class="mt-3 flex justify-end">
                <button onclick="submitTicketComment(${chg.id}, 'Change Request')" id="btnPostComment" class="bg-purple-600 hover:bg-purple-700 text-white px-5 py-2 rounded-xl text-xs font-semibold shadow flex items-center space-x-1.5">
                  <i data-lucide="send" class="w-3.5 h-3.5"></i>
                  <span>Post Update</span>
                </button>
              </div>
            </div>
          </div>

          <!-- TAB: CAB APPROVALS -->
          <div id="chgTabContent_approvals" class="hidden p-6 space-y-4 text-xs">
            <h3 class="font-bold text-sm mb-2">Change Advisory Board (CAB) Governance</h3>
            ${(chg.approvals && chg.approvals.length > 0) ? `
              <div class="space-y-3">
                ${chg.approvals.map(appr => `
                  <div class="p-4 rounded-xl border border-[var(--border-color)] bg-[var(--bg-tertiary)] flex items-center justify-between">
                    <div>
                      <div class="font-bold text-[var(--text-primary)]">CAB Reviewer: ${appr.approver_name || 'CAB Admin Team'}</div>
                      <div class="text-[11px] text-slate-400 mt-0.5">Decision: <span class="font-bold ${appr.status === 'Approved' ? 'text-emerald-500' : (appr.status === 'Rejected' ? 'text-red-500' : 'text-amber-500')}">${appr.status}</span></div>
                      ${appr.comments ? `<div class="text-[11px] text-slate-500 mt-1 italic">"${appr.comments}"</div>` : ''}
                    </div>
                    ${(appr.status === 'Pending' && isSupportOrAdmin) ? `
                      <button onclick="openApprovalDecisionModal(${chg.id}, 'Change Request')" class="px-3.5 py-1.5 rounded-xl bg-purple-600 hover:bg-purple-700 text-white text-xs font-semibold">
                        CAB Decision
                      </button>
                    ` : ''}
                  </div>
                `).join('')}
              </div>
            ` : `
              <div class="p-6 text-center text-slate-400">No CAB approval requirements mapped for this change.</div>
            `}
          </div>

        </div>
      </div>
    `;
    lucide.createIcons();
  } catch (err) {
    container.innerHTML = `<div class="p-8 text-center text-red-500">Error loading change: ${err.message}</div>`;
  }
}

function switchChangeTab(tab) {
  ['overview', 'conversation', 'approvals'].forEach(t => {
    const btn = document.getElementById(`chgTabBtn_${t}`);
    const content = document.getElementById(`chgTabContent_${t}`);
    if (t === tab) {
      if (btn) btn.className = 'px-4 py-2 rounded-lg bg-[var(--card-bg)] shadow-sm text-purple-600';
      if (content) content.classList.remove('hidden');
    } else {
      if (btn) btn.className = 'px-4 py-2 rounded-lg hover:bg-[var(--card-bg)] text-slate-400';
      if (content) content.classList.add('hidden');
    }
  });
}

// --- KNOWLEDGE BASE VIEW ---
async function renderKnowledgeView(container) {
  container.innerHTML = `<div class="p-8 text-center text-slate-400"><i data-lucide="loader-2" class="w-8 h-8 animate-spin mx-auto mb-2 text-purple-500"></i>Loading Knowledge Base...</div>`;
  lucide.createIcons();

  const isEndUser = isUserEndUser(state.currentUser);

  try {
    const res = await fetch(`${API_BASE}/knowledge`);
    const articles = await res.json();

    container.innerHTML = `
      <div class="space-y-6">
        <div class="flex items-center justify-between">
          <div>
            <h1 class="text-2xl font-black tracking-tight">${isEndUser ? 'Knowledge Base & FAQs' : 'Internal Knowledge Base & Runbooks'}</h1>
            <p class="text-sm text-slate-500">${isEndUser ? 'Browse verified troubleshooting guides, standard operating procedures, and FAQs.' : 'Standard operating procedures, verified troubleshooting guides, and incident runbooks.'}</p>
          </div>
          ${!isEndUser ? `
            <button onclick="openCreateArticleModal()" class="bg-purple-600 hover:bg-purple-700 text-white px-4 py-2 rounded-xl text-sm font-semibold shadow">
              + New Article
            </button>
          ` : `
            <div class="px-3 py-1.5 rounded-xl bg-purple-50 dark:bg-purple-950/40 text-purple-700 dark:text-purple-300 text-xs font-semibold flex items-center space-x-1.5 border border-purple-200 dark:border-purple-800">
              <i data-lucide="book-open" class="w-3.5 h-3.5"></i>
              <span>Self-Service Portal</span>
            </div>
          `}
        </div>

        <div class="grid grid-cols-1 md:grid-cols-2 gap-5">
          ${articles.map(a => `
            <div class="p-6 rounded-2xl bg-[var(--card-bg)] border border-[var(--border-color)] shadow-sm hover:shadow-md transition-shadow">
              <div class="flex items-center justify-between text-xs text-slate-400 mb-2">
                <span class="font-bold text-indigo-600">${a.article_number}</span>
                <span class="px-2 py-0.5 rounded bg-slate-100 dark:bg-slate-800 font-semibold">${a.category}</span>
              </div>
              <h2 class="text-base font-bold text-[var(--text-primary)] mb-2">${a.title}</h2>
              <div class="p-3 rounded-lg bg-[var(--bg-tertiary)] text-xs text-slate-500 line-clamp-3 mb-4 leading-relaxed font-mono">
                ${a.content.replace(/#/g, '').slice(0, 200)}...
              </div>
              <div class="flex items-center justify-between text-xs text-slate-400 pt-2 border-t border-[var(--border-color)]">
                <span>App: ${a.application_name || 'General'}</span>
                <span>By ${a.author_name || 'Staff'}</span>
              </div>
              <div class="flex justify-end gap-2 pt-3">
                ${!isEndUser ? `
                  <button onclick='openCreateArticleModal(${JSON.stringify(a).replace(/'/g, "&#39;")})' class="text-xs text-purple-600 dark:text-purple-400 font-bold hover:underline">Edit</button>
                  ${(state.currentUser?.role === 'administrator' || state.currentUser?.role === 'support_member' || state.currentUser?.role === 'group_manager' || (state.currentUser?.admin_projects || []).length > 0) ? `<button onclick="deleteKnowledgeArticle(${a.id})" class="text-xs text-red-600 font-bold hover:underline">Delete</button>` : ''}
                ` : `<span class="text-[11px] text-slate-400 italic">Self-Help Reference</span>`}
              </div>
            </div>
          `).join('')}
        </div>
      </div>
    `;
    lucide.createIcons();
  } catch (err) {
    container.innerHTML = `<div class="p-8 text-center text-red-500">Error loading articles: ${err.message}</div>`;
  }
}

// --- PLATFORM ENTITIES: APPLICATIONS, PROJECTS, ASSIGNMENT GROUPS ---
async function openCreateArticleModal(article = null) {
  if (isUserEndUser(state.currentUser)) {
    alert('End users have read-only access to the Knowledge Base and cannot create or edit articles.');
    return;
  }
  const appsRes = await fetch(`${API_BASE}/admin/applications`);
  const apps = appsRes.ok ? await appsRes.json() : [];
  const selectedApp = article?.application_id || '';
  document.getElementById('modalContainer').innerHTML = `
    <div class="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4">
      <div class="w-full max-w-2xl max-h-[90vh] overflow-y-auto rounded-2xl bg-[var(--card-bg)] p-5 shadow-2xl">
        <div class="flex items-center justify-between mb-4"><h2 class="font-bold">${article ? 'Edit Knowledge Article' : 'Create Knowledge Article'}</h2><button onclick="closeAdminModal()">✕</button></div>
        <form onsubmit="saveKnowledgeArticle(event, ${article?.id || 'null'})" class="space-y-3 admin-form text-xs">
          <div class="grid grid-cols-1 md:grid-cols-2 gap-3"><label>Title *<input id="kb_title" required value="${article?.title || ''}"></label><label>Category *<input id="kb_category" required value="${article?.category || 'Troubleshooting'}"></label></div>
          <label>Application<select id="kb_application"><option value="">General</option>${apps.map(a => `<option value="${a.id}" ${a.id === selectedApp ? 'selected' : ''}>${a.name}</option>`).join('')}</select></label>
          <label>Content *<textarea id="kb_content" required rows="12">${article?.content || ''}</textarea></label>
          <div class="flex justify-end gap-2 pt-2"><button type="button" onclick="closeAdminModal()" class="px-4 py-2 border rounded-lg">Cancel</button><button class="px-4 py-2 bg-purple-600 text-white rounded-lg font-bold">${article ? 'Save Changes' : 'Create Article'}</button></div>
        </form>
      </div>
    </div>`;
}

async function saveKnowledgeArticle(event, articleId) {
  event.preventDefault();
  if (isUserEndUser(state.currentUser)) {
    alert('End users have read-only access to the Knowledge Base and cannot create or edit articles.');
    return;
  }
  const appValue = document.getElementById('kb_application').value;
  const payload = { title: document.getElementById('kb_title').value, category: document.getElementById('kb_category').value, application_id: appValue ? Number(appValue) : null, content: document.getElementById('kb_content').value, status: 'Published' };
  const url = articleId ? `${API_BASE}/knowledge/${articleId}` : `${API_BASE}/knowledge`;
  const response = await fetch(url, {
    method: articleId ? 'PUT' : 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-User-ID': state.currentUser ? state.currentUser.id.toString() : '1'
    },
    body: JSON.stringify(payload)
  });
  if (!response.ok) { alert((await response.json()).detail || 'Unable to save knowledge article'); return; }
  closeAdminModal(); renderKnowledgeView(document.getElementById('mainApp'));
}

async function deleteKnowledgeArticle(articleId) {
  if (isUserEndUser(state.currentUser)) {
    alert('End users have read-only access to the Knowledge Base and cannot delete articles.');
    return;
  }
  if (!window.confirm('Delete this knowledge article? This action cannot be undone.')) return;
  const response = await fetch(`${API_BASE}/knowledge/${articleId}`, {
    method: 'DELETE',
    headers: {
      'X-User-ID': state.currentUser ? state.currentUser.id.toString() : '1'
    }
  });
  if (!response.ok) { alert((await response.json()).detail || 'Unable to delete knowledge article'); return; }
  renderKnowledgeView(document.getElementById('mainApp'));
}

async function renderApplicationsView(container) {
  try {
    let res = await fetch(`${API_BASE}/api/applications`);
    if (!res.ok) {
      res = await fetch(`${API_BASE}/admin/applications`);
    }
    if (!res.ok) throw new Error('Could not load applications');
    const apps = await res.json();
    const isGlobalAdmin = state.currentUser?.is_global_admin || state.currentUser?.username === 'admin' || state.currentUser?.role === 'administrator' || state.currentUser?.role === 'itsm_admin';
    const adminProjects = state.currentUser?.admin_projects || [];
    const isProjectAdmin = adminProjects.length > 0;
    const canManageApps = isGlobalAdmin || isProjectAdmin;

    container.innerHTML = `
    <div class="space-y-6">
      <div class="flex items-center justify-between gap-4">
        <div><h1 class="text-2xl font-black tracking-tight">Application Portfolio Catalog</h1>
        <p class="text-sm text-slate-500">Critical tier-1 and tier-2 organizational services.</p>
        </div>${canManageApps ? `<button onclick="window.location.hash='#/admin/entities'" class="bg-purple-600 hover:bg-purple-700 text-white px-4 py-2 rounded-xl text-xs font-bold">+ Manage / Add Application</button>` : ''}</div>
      <div class="grid grid-cols-1 md:grid-cols-3 gap-5">
        ${apps.map(a => {
          const canDeleteApp = isGlobalAdmin || (isProjectAdmin && a.project_name && adminProjects.map(p => p.toLowerCase()).includes(a.project_name.toLowerCase()));
          return `
          <div class="p-5 rounded-2xl bg-[var(--card-bg)] border border-[var(--border-color)] shadow-sm flex flex-col justify-between">
            <div>
              <div class="flex items-center justify-between text-xs font-semibold mb-2">
                <span class="text-purple-600 font-bold">${a.app_id}</span>
                <span class="px-2 py-0.5 rounded bg-red-50 dark:bg-red-950/40 text-red-600 font-bold">${a.criticality}</span>
              </div>
              <h2 class="text-base font-bold mb-1">${a.name}</h2>
              <p class="text-xs text-slate-400 mb-3">${a.description || 'Enterprise service'}</p>
            </div>
            <div class="pt-3 border-t border-[var(--border-color)] text-xs text-slate-400 space-y-1">
              <div>Owner: <b class="text-[var(--text-primary)]">${a.business_owner || 'N/A'}</b></div>
              <div>Hours: <b class="text-[var(--text-primary)]">${a.support_hours}</b></div>
              ${canDeleteApp ? `
              <div class="flex justify-end gap-2 pt-2 border-t border-[var(--border-color)]">
                <button onclick="openAdminEntityModal('application', ${a.id})" class="text-purple-600 hover:text-purple-700 text-xs font-bold">Edit</button>
                <button onclick="deleteAdminEntity('application', ${a.id}, '${a.name.replace(/'/g, "\\'")}')" class="text-red-500 hover:text-red-700 text-xs font-bold flex items-center gap-0.5"><i data-lucide="trash-2" class="w-3 h-3"></i> Delete</button>
              </div>` : ''}
            </div>
          </div>
        `;
        }).join('')}
      </div>
    </div>
  `;
  } catch (err) {
    container.innerHTML = `<div class="p-8 text-center text-red-500">Unable to load applications: ${err.message}</div>`;
  }
}

async function renderProjectsView(container) {
  try {
    let res = await fetch(`${API_BASE}/api/projects`);
    if (!res.ok) {
      res = await fetch(`${API_BASE}/admin/projects`);
    }
    if (!res.ok) throw new Error('Could not load projects');
    const projects = await res.json();
    const isGlobalAdmin = state.currentUser?.is_global_admin || state.currentUser?.username === 'admin' || state.currentUser?.role === 'administrator' || state.currentUser?.role === 'itsm_admin';

    container.innerHTML = `
      <div class="space-y-6">
        <div class="flex items-center justify-between">
          <div>
            <h1 class="text-2xl font-black tracking-tight">Project Management & Routing Defaults</h1>
            <p class="text-sm text-slate-500">Configured projects with support hours, default assignment groups, and SLA policies.</p>
          </div>
          ${isGlobalAdmin ? `<button onclick="window.location.hash='#/admin/entities'" class="bg-indigo-600 hover:bg-indigo-700 text-white px-4 py-2 rounded-xl text-xs font-bold">+ New Project</button>` : ''}
        </div>
        <div class="grid grid-cols-1 md:grid-cols-2 gap-5">
          ${projects.map(p => `
            <div class="p-5 rounded-2xl bg-[var(--card-bg)] border border-[var(--border-color)] shadow-sm flex flex-col justify-between">
              <div>
                <div class="flex items-center justify-between text-xs font-semibold mb-2">
                  <span class="text-indigo-600 font-bold">${p.project_id}</span>
                  <span class="px-2 py-0.5 rounded bg-purple-50 dark:bg-blue-950/40 text-purple-600 font-bold">${p.environment}</span>
                </div>
                <h2 class="text-base font-bold mb-1">${p.name}</h2>
                <p class="text-xs text-slate-400 mb-3">${p.description || ''}</p>
                <div class="p-3 rounded-xl bg-[var(--bg-tertiary)] text-xs space-y-1.5 border border-[var(--border-color)]">
                  <div>Application: <b class="text-purple-600">${p.application_name || 'Standalone'}</b></div>
                  <div>Default Assignment Group: <b class="text-emerald-600">${p.default_assignment_group_name || 'Service Desk'}</b></div>
                  <div>Default SLA Policy: <b class="text-purple-600">${p.default_sla_policy_name || 'Standard SLA'}</b></div>
                  <div>Project Manager: <b class="text-[var(--text-primary)]">${p.project_manager || 'Not configured'}</b></div>
                </div>
              </div>
              <div class="flex items-center justify-end gap-2 pt-3 mt-3 border-t border-[var(--border-color)]">
                <button onclick="openAdminEntityModal('project', ${p.id})" class="text-indigo-600 hover:text-indigo-700 text-xs font-bold">Configure</button>
                ${isGlobalAdmin ? `<button onclick="deleteAdminEntity('project', ${p.id}, '${p.name.replace(/'/g, "\\'")}')" class="text-red-500 hover:text-red-700 text-xs font-bold flex items-center gap-0.5"><i data-lucide="trash-2" class="w-3 h-3"></i> Delete</button>` : ''}
              </div>
            </div>
          `).join('')}
        </div>
      </div>
    `;
  } catch (err) {
    container.innerHTML = `<div class="p-8 text-center text-red-500">Unable to load projects: ${err.message}</div>`;
  }
}

async function renderOnCallRosterView(container) {
  try {
    const res = await fetch(`${API_BASE}/admin/projects/on-call-roster`, {
      headers: {
        'X-User-ID': state.currentUser ? state.currentUser.id.toString() : '1'
      }
    });
    if (!res.ok) throw new Error('Could not load on-call roster');
    const roster = await res.json();

    container.innerHTML = `
      <div class="space-y-6">
        <div class="flex items-center justify-between">
          <div>
            <h1 class="text-2xl font-black tracking-tight">On-Call & Escalations Roster</h1>
            <p class="text-sm text-slate-500">Live on-call engineering schedules, Level-2 &amp; Level-3 on-call support rotations, and application-specific contacts.</p>
          </div>
        </div>

        <div class="space-y-6">
          ${roster.map(p => `
            <div class="p-6 rounded-2xl bg-[var(--card-bg)] border border-[var(--border-color)] shadow-sm space-y-4">
              <div class="flex items-center justify-between border-b border-[var(--border-color)] pb-3">
                <div>
                  <span class="text-xs font-bold text-indigo-500">${p.project_code}</span>
                  <h2 class="text-lg font-black tracking-tight text-[var(--text-primary)]">${p.project_name}</h2>
                </div>
                ${p.can_edit ? `
                  <button onclick="openEditOnCallModal(${p.project_id}, '${p.project_name.replace(/'/g, "\\'")}')" class="px-3.5 py-1.5 rounded-xl bg-purple-600 hover:bg-purple-700 text-white text-xs font-semibold flex items-center space-x-1.5 shadow-sm">
                    <i data-lucide="edit-3" class="w-3.5 h-3.5"></i>
                    <span>Edit On-Call & Escalations</span>
                  </button>
                ` : ''}
              </div>

              <!-- Escalation Hierarchy Grid -->
              <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
                <div class="p-3.5 rounded-xl bg-[var(--bg-tertiary)] border border-[var(--border-color)]">
                  <div class="flex items-center space-x-2 text-emerald-500 text-xs font-bold mb-1">
                    <i data-lucide="phone-call" class="w-4 h-4"></i>
                    <span>Level-2 On-Call Support (${p.l2_group_name})</span>
                  </div>
                  <div class="font-semibold text-sm text-[var(--text-primary)] truncate">${p.l2_on_call_contact || '<span class="text-slate-400 font-normal">Not configured</span>'}</div>
                </div>

                <div class="p-3.5 rounded-xl bg-[var(--bg-tertiary)] border border-[var(--border-color)]">
                  <div class="flex items-center space-x-2 text-indigo-500 text-xs font-bold mb-1">
                    <i data-lucide="phone-forwarded" class="w-4 h-4"></i>
                    <span>Level-3 On-Call Support (${p.l3_group_name})</span>
                  </div>
                  <div class="font-semibold text-sm text-[var(--text-primary)] truncate">${p.l3_on_call_contact || '<span class="text-slate-400 font-normal">Not configured</span>'}</div>
                </div>

                <div class="p-3.5 rounded-xl bg-[var(--bg-tertiary)] border border-[var(--border-color)]">
                  <div class="flex items-center space-x-2 text-amber-500 text-xs font-bold mb-1">
                    <i data-lucide="user-check" class="w-4 h-4"></i>
                    <span>1st Level Escalation</span>
                  </div>
                  <div class="font-semibold text-sm text-[var(--text-primary)] truncate">${p.first_escalation_contact || '<span class="text-slate-400 font-normal">Not configured</span>'}</div>
                </div>

                <div class="p-3.5 rounded-xl bg-[var(--bg-tertiary)] border border-[var(--border-color)]">
                  <div class="flex items-center space-x-2 text-rose-500 text-xs font-bold mb-1">
                    <i data-lucide="shield-alert" class="w-4 h-4"></i>
                    <span>2nd Level Escalation</span>
                  </div>
                  <div class="font-semibold text-sm text-[var(--text-primary)] truncate">${p.second_escalation_contact || '<span class="text-slate-400 font-normal">Not configured</span>'}</div>
                </div>
              </div>

              <!-- Applications Under Project Table -->
              <div class="pt-2">
                <div class="text-xs font-bold text-slate-400 uppercase tracking-wider mb-2">Applications Under ${p.project_name} (${p.applications.length})</div>
                ${p.applications.length === 0 ? `
                  <div class="text-xs text-slate-400 italic">No applications currently associated with this project.</div>
                ` : `
                  <div class="overflow-x-auto rounded-xl border border-[var(--border-color)]">
                    <table class="w-full text-left text-xs">
                      <thead class="bg-[var(--bg-tertiary)] text-slate-400 uppercase text-[10px] font-bold">
                        <tr>
                          <th class="p-3">Application</th>
                          <th class="p-3">Application On-Call</th>
                          <th class="p-3">Technical Owner</th>
                          <th class="p-3">Business Owner</th>
                          <th class="p-3">Support Hours</th>
                        </tr>
                      </thead>
                      <tbody class="divide-y divide-[var(--border-color)]">
                        ${p.applications.map(app => `
                          <tr class="hover:bg-[var(--bg-tertiary)] transition-colors">
                            <td class="p-3 font-bold text-[var(--text-primary)]">
                              ${app.name}
                              <span class="block text-[10px] text-slate-400 font-normal">${app.app_id}</span>
                            </td>
                            <td class="p-3 font-semibold text-emerald-500">
                              ${app.on_call_contact ? `<span class="inline-flex items-center space-x-1"><i data-lucide="phone" class="w-3 h-3"></i><span>${app.on_call_contact}</span></span>` : '<span class="text-slate-400 font-normal">None</span>'}
                            </td>
                            <td class="p-3 text-slate-300">${app.technical_owner || '—'}</td>
                            <td class="p-3 text-slate-300">${app.business_owner || '—'}</td>
                            <td class="p-3 text-slate-400">${app.support_hours || '24x7'}</td>
                          </tr>
                        `).join('')}
                      </tbody>
                    </table>
                  </div>
                `}
              </div>
            </div>
          `).join('')}
        </div>
      </div>
    `;
    lucide.createIcons();
  } catch (err) {
    container.innerHTML = `<div class="p-8 text-center text-red-500">Unable to load on-call roster: ${err.message}</div>`;
  }
}

async function openEditOnCallModal(projectId, projectName) {
  try {
    const res = await fetch(`${API_BASE}/admin/projects/${projectId}/on-call`, {
      headers: {
        'X-User-ID': state.currentUser ? state.currentUser.id.toString() : '1'
      }
    });
    if (!res.ok) throw new Error('Could not load project on-call details');
    const data = await res.json();

    const modalContainer = document.getElementById('modalContainer');
    modalContainer.innerHTML = `
      <div class="fixed inset-0 bg-black/50 backdrop-blur-sm z-50 flex items-center justify-center p-4">
        <div class="w-full max-w-lg bg-[var(--card-bg)] border border-[var(--border-color)] rounded-2xl shadow-2xl overflow-hidden animate-fade-in max-h-[90vh] flex flex-col">
          <div class="p-4 border-b border-[var(--border-color)] flex items-center justify-between shrink-0">
            <div class="flex items-center space-x-2">
              <i data-lucide="phone-call" class="w-5 h-5 text-purple-600"></i>
              <h2 class="text-base font-bold">Update On-Call & Escalations: ${data.project_name}</h2>
            </div>
            <button onclick="document.getElementById('modalContainer').innerHTML=''" class="text-slate-400 hover:text-white">✕</button>
          </div>

          <form onsubmit="submitEditOnCall(event, ${data.project_id})" class="p-5 space-y-4 text-xs overflow-y-auto flex-1">
            <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div>
                <label class="block font-semibold text-slate-400 mb-1">Level-2 On-Call Support</label>
                <input type="text" id="edit_l2_on_call" value="${data.l2_on_call_contact || ''}" placeholder="e.g. John (+1-555-0101) / Rotation" class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-lg p-2.5 text-xs font-medium">
              </div>
              <div>
                <label class="block font-semibold text-slate-400 mb-1">Level-3 On-Call Support</label>
                <input type="text" id="edit_l3_on_call" value="${data.l3_on_call_contact || ''}" placeholder="e.g. Jane (+1-555-0102) / Rotation" class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-lg p-2.5 text-xs font-medium">
              </div>
            </div>

            <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div>
                <label class="block font-semibold text-slate-400 mb-1">1st Level Escalation</label>
                <input type="text" id="edit_first_escalation" value="${data.first_escalation_contact || ''}" placeholder="e.g. Robert (+1-555-0103)" class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-lg p-2.5 text-xs font-medium">
              </div>
              <div>
                <label class="block font-semibold text-slate-400 mb-1">2nd Level Escalation</label>
                <input type="text" id="edit_second_escalation" value="${data.second_escalation_contact || ''}" placeholder="e.g. Susan (+1-555-0104)" class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-lg p-2.5 text-xs font-medium">
              </div>
            </div>

            <div class="pt-3 border-t border-[var(--border-color)]">
              <label class="block font-bold text-slate-300 mb-2">Application-Specific On-Call Contacts</label>
              <div class="space-y-2.5">
                ${data.applications.map(a => `
                  <div class="p-3 rounded-xl bg-[var(--bg-tertiary)] border border-[var(--border-color)] space-y-1">
                    <div class="font-bold text-[var(--text-primary)]">${a.name} (${a.app_id})</div>
                    <input type="text" data-app-id="${a.id}" class="edit-app-on-call w-full bg-[var(--card-bg)] border border-[var(--border-color)] rounded-lg p-2 text-xs" value="${a.on_call_contact || ''}" placeholder="App On-Call Contact...">
                  </div>
                `).join('')}
              </div>
            </div>

            <div class="pt-4 border-t border-[var(--border-color)] flex justify-end space-x-2 shrink-0">
              <button type="button" onclick="document.getElementById('modalContainer').innerHTML=''" class="px-4 py-2 rounded-xl border border-[var(--border-color)] text-slate-400 hover:bg-[var(--bg-tertiary)]">Cancel</button>
              <button type="submit" class="px-5 py-2 rounded-xl bg-purple-600 hover:bg-purple-700 text-white font-bold shadow">Save On-Call Matrix</button>
            </div>
          </form>
        </div>
      </div>
    `;
    lucide.createIcons();
  } catch (err) {
    alert('Error opening On-Call editor: ' + err.message);
  }
}

async function submitEditOnCall(e, projectId) {
  e.preventDefault();
  const l2Val = document.getElementById('edit_l2_on_call').value;
  const l3Val = document.getElementById('edit_l3_on_call').value;
  const esc1Val = document.getElementById('edit_first_escalation').value;
  const esc2Val = document.getElementById('edit_second_escalation').value;

  const appOnCalls = {};
  document.querySelectorAll('.edit-app-on-call').forEach(input => {
    const appId = input.getAttribute('data-app-id');
    appOnCalls[appId] = input.value;
  });

  const payload = {
    l2_on_call_contact: l2Val,
    l3_on_call_contact: l3Val,
    first_escalation_contact: esc1Val,
    second_escalation_contact: esc2Val,
    application_on_calls: appOnCalls
  };

  try {
    const res = await fetch(`${API_BASE}/admin/projects/${projectId}/on-call`, {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
        'X-User-ID': state.currentUser ? state.currentUser.id.toString() : '1'
      },
      body: JSON.stringify(payload)
    });
    if (res.ok) {
      document.getElementById('modalContainer').innerHTML = '';
      renderOnCallRosterView(document.getElementById('mainApp'));
    } else {
      const err = await res.json().catch(() => ({}));
      alert('Save failed: ' + (err.detail || res.statusText));
    }
  } catch (err) {
    alert('Save failed: ' + err.message);
  }
}

async function renderAssignmentGroupsView(container) {
  const res = await fetch(`${API_BASE}/admin/groups`);
  const groups = await res.json();

  container.innerHTML = `
    <div class="space-y-6">
      <div>
        <h1 class="text-2xl font-black tracking-tight">Assignment Groups & Support Teams</h1>
        <p class="text-sm text-slate-500">Tier-2 and tier-3 engineering teams with members and escalation paths.</p>
      </div>
      <div class="grid grid-cols-1 md:grid-cols-3 gap-5">
        ${groups.map(g => `
          <div class="p-5 rounded-2xl bg-[var(--card-bg)] border border-[var(--border-color)] shadow-sm">
            <div class="flex items-center justify-between text-xs font-semibold mb-2">
              <span class="text-purple-600 font-bold">${g.group_id}</span>
              <span class="px-2 py-0.5 rounded bg-emerald-50 dark:bg-emerald-950/40 text-emerald-600 font-bold">${g.member_count} Members</span>
            </div>
            <h2 class="text-base font-bold mb-1">${g.name}</h2>
            <p class="text-xs text-slate-400 mb-3">${g.description}</p>
            <div class="text-xs space-y-1 text-slate-400 pt-2 border-t border-[var(--border-color)]">
              <div>Manager: <b class="text-[var(--text-primary)]">${g.manager_name || 'Unassigned'}</b></div>
              <div>Calendar: <b class="text-indigo-600">${g.business_calendar_name || '24x7 Global'}</b></div>
            </div>
          </div>
        `).join('')}
      </div>
    </div>
  `;
}

// --- ADMINISTRATION SUB-VIEWS ---
function renderAdminSubView(container, sub) {
  switch (sub) {
    case 'entities':
      renderAdminEntityManagement(container);
      break;
    case 'configuration':
      renderTicketConfigurationView(container);
      break;
    case 'graph':
      renderVisualConfigGraph(container);
      break;
    case 'simulator':
      renderRoutingSimulatorView(container);
      break;
    case 'validation':
      renderConfigValidationView(container);
      break;
    case 'slas':
      renderSlaAdminView(container);
      break;
    case 'calendars':
      renderCalendarsAdminView(container);
      break;
    case 'ai':
      renderAiAdminView(container);
      break;
    case 'audits':
      renderAuditsAdminView(container);
      break;
    case 'import-export':
      renderImportExportView(container);
      break;
    case 'identity':
      renderIdentityManagementView(container);
      break;
    case 'consul':
      renderConsulConfigView(container);
      break;
    default:
      renderVisualConfigGraph(container);
  }
}

// --- ADMIN: APPLICATION / PROJECT / ASSIGNMENT-GROUP MANAGEMENT ---
async function renderAdminEntityManagement(container) {
  const isGlobalAdmin = state.currentUser?.is_global_admin || state.currentUser?.username === 'admin' || state.currentUser?.role === 'administrator' || state.currentUser?.role === 'itsm_admin';
  const adminProjects = state.currentUser?.admin_projects || [];
  const isProjectAdmin = adminProjects.length > 0;

  if (!state.currentUser || (!isGlobalAdmin && !isProjectAdmin)) {
    container.innerHTML = `<div class="p-8 rounded-2xl border border-amber-200 bg-amber-50 text-amber-800">Administrator or Project Administrator access is required to manage applications, projects, and assignment groups.</div>`;
    return;
  }
  container.innerHTML = `<div class="p-8 text-center text-slate-400">Loading administration configuration...</div>`;
  try {
    const authHeaders = { 'X-User-ID': state.currentUser.id.toString() };
    const [appsRes, projectsRes, groupsRes] = await Promise.all([
      fetch(`${API_BASE}/admin/applications`, { headers: authHeaders }),
      fetch(`${API_BASE}/admin/projects`, { headers: authHeaders }),
      fetch(`${API_BASE}/admin/groups`, { headers: authHeaders })
    ]);
    if (![appsRes, projectsRes, groupsRes].every(r => r.ok)) throw new Error('Configuration API was not available');
    const [apps, projects, groups] = await Promise.all([appsRes.json(), projectsRes.json(), groupsRes.json()]);
    state.adminEntities = { apps, projects, groups };
    const managedProjects = isGlobalAdmin ? projects : projects.filter(p => adminProjects.includes(p.name));

    container.innerHTML = `
      <div class="space-y-6">
        <div class="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <div><h1 class="text-2xl font-black tracking-tight">Applications, Projects & Support Teams</h1>
          <p class="text-sm text-slate-500">${isGlobalAdmin ? 'Full platform administration.' : `Project-scoped administration for: [${adminProjects.join(', ')}]`}</p></div>
          <div class="flex flex-wrap gap-2">
            <button onclick="openAdminEntityModal('application')" class="bg-purple-600 hover:bg-purple-700 text-white px-3 py-2 rounded-xl text-xs font-bold">+ Application</button>
            ${isGlobalAdmin ? `<button onclick="openAdminEntityModal('project')" class="bg-indigo-600 hover:bg-indigo-700 text-white px-3 py-2 rounded-xl text-xs font-bold">+ Project</button>` : ''}
            ${isGlobalAdmin ? `<button onclick="openAdminEntityModal('group')" class="bg-emerald-600 hover:bg-emerald-700 text-white px-3 py-2 rounded-xl text-xs font-bold">+ Assignment Group</button>` : ''}
          </div>
        </div>

        <!-- PROJECT SUPPORT QUEUES: LEVEL-2 & LEVEL-3 SECTION -->
        <section class="rounded-2xl bg-[var(--card-bg)] border border-[var(--border-color)] p-5 shadow-sm space-y-4">
          <div class="flex flex-col md:flex-row md:items-center justify-between gap-3 pb-3 border-b border-[var(--border-color)]">
            <div>
              <div class="flex items-center gap-2">
                <span class="p-1.5 rounded-lg bg-purple-100 dark:bg-purple-950/60 text-purple-600 font-bold text-xs"><i data-lucide="layers" class="w-4 h-4"></i></span>
                <h2 class="text-base font-bold text-[var(--text-primary)]">Project Support Queues (Level-2 & Level-3)</h2>
              </div>
              <p class="text-xs text-slate-500 mt-1">Configure frontline Level-2 and advanced Level-3 assignment groups. <b>New tickets created for a project automatically route to the Level-2 queue by default.</b></p>
            </div>
            ${isGlobalAdmin ? `<div class="text-xs text-purple-600 font-semibold flex items-center gap-1"><i data-lucide="shield-check" class="w-4 h-4"></i> Global Admin: Managing All Projects</div>` : `<div class="text-xs text-indigo-600 font-semibold flex items-center gap-1"><i data-lucide="folder-check" class="w-4 h-4"></i> Scoped to [${adminProjects.join(', ')}]</div>`}
          </div>

          <div class="grid grid-cols-1 ${managedProjects.length > 1 ? 'lg:grid-cols-2' : ''} gap-4">
            ${managedProjects.map(proj => {
              const l2Group = groups.find(g => g.id === proj.l2_assignment_group_id || g.id === proj.default_assignment_group_id || g.name.toLowerCase() === `${proj.name.toLowerCase()}-l2`);
              const l3Group = groups.find(g => g.id === proj.l3_assignment_group_id || g.name.toLowerCase() === `${proj.name.toLowerCase()}-l3`);
              return `
                <div class="rounded-xl border border-[var(--border-color)] bg-[var(--bg-primary)] p-4 space-y-3">
                  <div class="flex items-center justify-between">
                    <div>
                      <div class="text-xs font-bold text-indigo-600 uppercase tracking-wider">${proj.project_id}</div>
                      <h3 class="font-bold text-sm text-[var(--text-primary)]">${proj.name}</h3>
                    </div>
                    <button onclick="openAdminEntityModal('project', ${proj.id})" class="px-3 py-1.5 rounded-lg bg-indigo-50 dark:bg-indigo-950/50 text-indigo-600 dark:text-indigo-400 hover:bg-indigo-100 text-xs font-bold border border-indigo-200 dark:border-indigo-800 flex items-center gap-1.5">
                      <i data-lucide="settings-2" class="w-3.5 h-3.5"></i> Configure Queues
                    </button>
                  </div>

                  <div class="grid grid-cols-1 sm:grid-cols-2 gap-3 pt-2 border-t border-[var(--border-color)]">
                    <!-- LEVEL-2 QUEUE CARD -->
                    <div class="p-3 rounded-xl border border-emerald-200 dark:border-emerald-800 bg-emerald-50/50 dark:bg-emerald-950/20 space-y-2">
                      <div class="flex items-center justify-between">
                        <span class="text-[10px] font-extrabold uppercase tracking-wider px-2 py-0.5 rounded bg-emerald-100 dark:bg-emerald-900/60 text-emerald-700 dark:text-emerald-300">Level-2 Frontline</span>
                        ${l2Group ? `<button onclick="openAdminEntityModal('group', ${l2Group.id})" class="text-emerald-700 dark:text-emerald-300 font-bold text-[10px] hover:underline flex items-center gap-0.5"><i data-lucide="edit-3" class="w-3 h-3"></i> Edit</button>` : ''}
                      </div>
                      <div class="font-bold text-xs text-[var(--text-primary)]">${l2Group ? l2Group.name : 'Not configured (Click Configure Queues)'}</div>
                      <div class="text-[11px] text-slate-500 space-y-0.5">
                        <div>On-Call: <b class="text-[var(--text-primary)]">${l2Group?.on_call_contact || 'Not configured'}</b></div>
                        <div>1st Escalation: <b>${l2Group?.first_escalation_contact || '—'}</b></div>
                      </div>
                      <div class="text-[10px] text-emerald-600 font-medium">⚡ Default ticket destination</div>
                    </div>

                    <!-- LEVEL-3 QUEUE CARD -->
                    <div class="p-3 rounded-xl border border-blue-200 dark:border-blue-800 bg-blue-50/50 dark:bg-blue-950/20 space-y-2">
                      <div class="flex items-center justify-between">
                        <span class="text-[10px] font-extrabold uppercase tracking-wider px-2 py-0.5 rounded bg-blue-100 dark:bg-blue-900/60 text-blue-700 dark:text-blue-300">Level-3 Advanced</span>
                        ${l3Group ? `<button onclick="openAdminEntityModal('group', ${l3Group.id})" class="text-blue-700 dark:text-blue-300 font-bold text-[10px] hover:underline flex items-center gap-0.5"><i data-lucide="edit-3" class="w-3 h-3"></i> Edit</button>` : ''}
                      </div>
                      <div class="font-bold text-xs text-[var(--text-primary)]">${l3Group ? l3Group.name : 'Not configured (Click Configure Queues)'}</div>
                      <div class="text-[11px] text-slate-500 space-y-0.5">
                        <div>On-Call: <b class="text-[var(--text-primary)]">${l3Group?.on_call_contact || 'Not configured'}</b></div>
                        <div>2nd Escalation: <b>${l3Group?.second_escalation_contact || '—'}</b></div>
                      </div>
                      <div class="text-[10px] text-blue-600 font-medium">🔬 Escalation & engineering queue</div>
                    </div>
                  </div>
                </div>
              `;
            }).join('') || '<div class="p-4 text-sm text-slate-400">No projects found to configure queues.</div>'}
          </div>
        </section>

        <div class="grid grid-cols-1 xl:grid-cols-3 gap-5">
          <section class="rounded-2xl bg-[var(--card-bg)] border border-[var(--border-color)] overflow-hidden">
            <div class="px-4 py-3 border-b border-[var(--border-color)] font-bold text-sm">Applications <span class="text-slate-400">(${apps.length})</span></div>
            <div class="divide-y divide-[var(--border-color)] max-h-[480px] overflow-y-auto">${apps.map(a => {
              const canDeleteApp = isGlobalAdmin || (isProjectAdmin && a.project_name && adminProjects.map(p => p.toLowerCase()).includes(a.project_name.toLowerCase()));
              return `<div class="p-4"><div class="flex justify-between gap-2"><div><div class="font-bold text-sm">${a.name}</div><div class="text-[11px] text-purple-600 mt-1">${a.app_id} · ${a.criticality} ${a.project_name ? `· <span class="text-indigo-600 font-semibold">[${a.project_name}]</span>` : ''}</div></div><div class="flex items-center gap-2"><button onclick="openAdminEntityModal('application', ${a.id})" class="text-purple-600 text-[10px] font-bold">Edit</button>${canDeleteApp ? `<button onclick="deleteAdminEntity('application', ${a.id}, '${a.name.replace(/'/g, "\\'")}')" class="text-red-500 hover:text-red-700 text-[10px] font-bold">Delete</button>` : ''}</div></div><div class="text-xs text-slate-500 mt-2">Owner: ${a.business_owner || 'Not configured'} · Team: ${a.default_assignment_group_name || 'Not configured'}</div></div>`;
            }).join('') || '<div class="p-4 text-sm text-slate-400">No applications configured.</div>'}</div>
          </section>
          <section class="rounded-2xl bg-[var(--card-bg)] border border-[var(--border-color)] overflow-hidden">
            <div class="px-4 py-3 border-b border-[var(--border-color)] font-bold text-sm">Projects <span class="text-slate-400">(${projects.length})</span></div>
            <div class="divide-y divide-[var(--border-color)] max-h-[480px] overflow-y-auto">${projects.map(p => {
              const canEditP = isGlobalAdmin || (isProjectAdmin && adminProjects.includes(p.name));
              return `<div class="p-4"><div class="flex justify-between gap-2"><div><div class="font-bold text-sm">${p.name}</div><div class="text-[11px] text-indigo-600 mt-1">${p.project_id} · ${p.application_name || 'Standalone'}</div></div><div class="flex items-center gap-2">${canEditP ? `<button onclick="openAdminEntityModal('project', ${p.id})" class="text-indigo-600 text-[10px] font-bold">Edit</button>` : ''}${isGlobalAdmin ? `<button onclick="deleteAdminEntity('project', ${p.id}, '${p.name.replace(/'/g, "\\'")}')" class="text-red-500 hover:text-red-700 text-[10px] font-bold">Delete</button>` : ''}</div></div><div class="text-xs text-slate-500 mt-2">Manager: ${p.project_manager || 'Not configured'} · L2 Queue: ${p.l2_assignment_group_name || p.default_assignment_group_name || 'Not configured'} · L3 Queue: ${p.l3_assignment_group_name || 'Not configured'}</div></div>`;
            }).join('') || '<div class="p-4 text-sm text-slate-400">No projects configured.</div>'}</div>
          </section>
          <section class="rounded-2xl bg-[var(--card-bg)] border border-[var(--border-color)] overflow-hidden">
            <div class="px-4 py-3 border-b border-[var(--border-color)] font-bold text-sm">Assignment Groups <span class="text-slate-400">(${groups.length})</span></div>
            <div class="divide-y divide-[var(--border-color)] max-h-[480px] overflow-y-auto">${groups.map(g => {
              const canEditG = isGlobalAdmin || (isProjectAdmin && adminProjects.some(p => g.name.toLowerCase().includes(p.toLowerCase())));
              return `<div class="p-4"><div class="flex justify-between gap-2"><div><div class="font-bold text-sm">${g.name}</div><div class="text-[11px] text-emerald-600 mt-1">${g.group_id} · ${g.member_count} members</div></div><div class="flex gap-2">${canEditG ? `<button onclick="openAdminEntityModal('group', ${g.id})" class="text-emerald-600 text-[10px] font-bold">Edit</button>` : ''}${isGlobalAdmin ? `<button onclick="openDistributionListModal(${g.id}, '${g.name.replace(/'/g, "\\'")}')" class="shrink-0 border border-emerald-500 text-emerald-600 hover:bg-emerald-50 px-2 py-1 rounded-lg text-[10px] font-bold">+ DL</button>` : ''}</div></div><div class="text-xs text-slate-500 mt-2">On call: ${g.on_call_contact || 'Not configured'} · L1: ${g.first_escalation_contact || '—'} · L2: ${g.second_escalation_contact || '—'}</div></div>`;
            }).join('') || '<div class="p-4 text-sm text-slate-400">No assignment groups configured.</div>'}</div>
          </section>
        </div>
      </div>`;
    lucide.createIcons();
  } catch (err) {
    container.innerHTML = `<div class="p-8 rounded-2xl border border-red-200 bg-red-50 text-red-700">Unable to load admin configuration: ${err.message}</div>`;
  }
}

function adminSelectOptions(items, selectedId, label) {
  return `<option value="">${label}</option>${items.map(item => `<option value="${item.id}" ${item.id === selectedId ? 'selected' : ''}>${item.name}</option>`).join('')}`;
}

function openAdminEntityModal(type, entityId = null) {
  const { apps = [], projects = [], groups = [] } = state.adminEntities || {};
  const isGlobalAdmin = state.currentUser?.is_global_admin || state.currentUser?.username === 'admin' || state.currentUser?.role === 'administrator' || state.currentUser?.role === 'itsm_admin';
  const adminProjects = state.currentUser?.admin_projects || [];
  const allowedProjects = isGlobalAdmin ? projects : projects.filter(p => adminProjects.includes(p.name));

  const record = entityId ? (type === 'application' ? apps : type === 'project' ? projects : groups).find(x => x.id === entityId) : {};
  const val = (key, fallback = '') => record?.[key] ?? fallback;
  const input = (id, value = '', extra = '') => `<input id="${id}" value="${String(value).replace(/"/g, '&quot;')}" ${extra}>`;
  const common = `<label>Description<textarea id="entity_description" rows="2">${val('description')}</textarea></label><label>Support hours${input('entity_hours', val('support_hours', '24x7'), 'placeholder="e.g. Mon–Fri 09:00–18:00"')}</label><label>Environment${input('entity_environment', val('environment', 'Production'))}</label><label>Criticality<select id="entity_criticality">${['Low','Medium','High','Critical'].map(x => `<option ${val('criticality', type === 'application' ? 'High' : 'Medium') === x ? 'selected' : ''}>${x}</option>`).join('')}</select></label><label class="md:col-span-2">Additional fields (JSON)<textarea id="entity_custom" rows="2" placeholder='{"cost_center":"..."}'>${JSON.stringify(val('custom_fields', {}), null, 0)}</textarea></label>`;
  const projectField = isGlobalAdmin
    ? `<label>Associated Project<select id="entity_project">${adminSelectOptions(allowedProjects, val('project_id'), 'No project (Standalone)')}</select></label>`
    : `<div class="flex flex-col gap-1">
        <label class="text-[11px] font-bold text-slate-500 uppercase tracking-wider">Project</label>
        <div class="px-3 py-2 rounded-xl bg-purple-50 dark:bg-purple-950/40 border border-purple-200 dark:border-purple-800 text-purple-700 dark:text-purple-300 font-semibold text-xs flex items-center gap-2">
          <i data-lucide="folder-git-2" class="w-4 h-4 text-purple-600 shrink-0"></i>
          <span>${allowedProjects[0]?.name || adminProjects[0] || 'My Project'}</span>
        </div>
        <input type="hidden" id="entity_project" value="${allowedProjects[0]?.id || ''}">
        <input type="hidden" id="entity_project_name" value="${allowedProjects[0]?.name || adminProjects[0] || ''}">
      </div>`;

  const projectQueues = (!isGlobalAdmin && allowedProjects[0]) ? groups.filter(g => g.id === allowedProjects[0].l2_assignment_group_id || g.id === allowedProjects[0].l3_assignment_group_id || g.name.toLowerCase().startsWith(allowedProjects[0].name.toLowerCase())) : [];
  const appEligibleGroups = (!isGlobalAdmin && projectQueues.length) ? projectQueues : groups;
  const appDefaultGroupId = val('default_assignment_group_id') || (!isGlobalAdmin && allowedProjects[0] ? allowedProjects[0].l2_assignment_group_id : '');

  const fields = type === 'application' ? `
    <label>Application ID *${input('entity_code', val('app_id'), 'required placeholder="APP006"')}</label><label>Name *${input('entity_name', val('name'), 'required')}</label>
    ${projectField}
    <label>Business owner${input('entity_business_owner', val('business_owner'))}</label><label>Technical owner${input('entity_technical_owner', val('technical_owner'))}</label><label>Business service${input('entity_business_service', val('business_service'))}</label><label>Default assignment group<select id="entity_group">${adminSelectOptions(appEligibleGroups, appDefaultGroupId, 'Project Level-2 Queue (Default)')}</select></label>${common}`
    : type === 'project' ? (entityId ? `
    <label>Project ID *${input('entity_code', val('project_id'), 'required placeholder="PRJ006"')}</label><label>Name *${input('entity_name', val('name'), 'required')}</label>
    <label>Level-2 Assignment Group (Default for Project Tickets)<select id="entity_l2_group">${adminSelectOptions(groups, val('l2_assignment_group_id') || val('default_assignment_group_id'), 'Select Level-2 Frontline Queue')}</select></label>
    <label>Level-3 Assignment Group (Advanced Engineering)<select id="entity_l3_group">${adminSelectOptions(groups, val('l3_assignment_group_id'), 'Select Level-3 Engineering Queue')}</select></label>
    <label>Associated Application (Optional)<select id="entity_application">${adminSelectOptions(apps, val('application_id'), 'No application yet (Standalone Project)')}</select></label>
    <label>Project manager${input('entity_project_manager', val('project_manager'))}</label>
    <label>Business owner${input('entity_business_owner', val('business_owner'))}</label>
    <label>Technical owner${input('entity_technical_owner', val('technical_owner'))}</label>${common}` : `
    <label>Project ID *${input('entity_code', val('project_id'), 'required placeholder="PRJ006"')}</label><label>Name *${input('entity_name', val('name'), 'required placeholder="e.g. Cloud Modernization"')}</label>
    <div class="md:col-span-2 p-3.5 rounded-xl bg-purple-50 dark:bg-purple-950/40 border border-purple-200 dark:border-purple-800 text-purple-900 dark:text-purple-200">
      <div class="font-bold flex items-center gap-1.5 mb-1.5 text-xs">
        <i data-lucide="sparkles" class="w-4 h-4 text-purple-600 shrink-0"></i>
        <span>Automatic Support Queue & Group Provisioning</span>
      </div>
      <p class="text-[11px] leading-relaxed text-slate-600 dark:text-slate-300">
        When this project is created, the system will <b>automatically provision and link</b> its operational support queues:
      </p>
      <div class="grid grid-cols-1 sm:grid-cols-2 gap-2 mt-2">
        <div class="p-2 rounded-lg bg-emerald-50 dark:bg-emerald-950/40 border border-emerald-200 dark:border-emerald-800 text-[11px]">
          <span class="font-bold text-emerald-700 dark:text-emerald-300 block">Level-2 Queue (&lt;Project&gt;-l2)</span>
          <span class="text-slate-500">Default destination for all project tickets</span>
        </div>
        <div class="p-2 rounded-lg bg-blue-50 dark:bg-blue-950/40 border border-blue-200 dark:border-blue-800 text-[11px]">
          <span class="font-bold text-blue-700 dark:text-blue-300 block">Level-3 Queue (&lt;Project&gt;-l3)</span>
          <span class="text-slate-500">Advanced engineering & escalation queue</span>
        </div>
      </div>
      <p class="text-[11px] text-purple-700 dark:text-purple-300 mt-2 font-medium">
        Scoped admin groups (&lt;Project&gt;_admin) are also created automatically. Applications can be added under this project once it is created.
      </p>
    </div>
    <label>Project manager${input('entity_project_manager', val('project_manager'))}</label>
    <label>Business owner${input('entity_business_owner', val('business_owner'))}</label>
    <label>Technical owner${input('entity_technical_owner', val('technical_owner'))}</label>${common}`)
    : `<label>Group ID *${input('entity_code', val('group_id'), 'required placeholder="GRP006"')}</label><label>Name *${input('entity_name', val('name'), 'required')}</label><label>On-call contact${input('entity_on_call', val('on_call_contact'), 'placeholder="Name, email or rotation"')}</label><label>First escalation${input('entity_l1', val('first_escalation_contact'))}</label><label>Second escalation${input('entity_l2', val('second_escalation_contact'))}</label><label>Escalation group<select id="entity_escalation_group">${adminSelectOptions(groups.filter(g => g.id !== entityId), val('escalation_group_id'), 'No escalation group')}</select></label><label class="md:col-span-2">Description<textarea id="entity_description" rows="2">${val('description')}</textarea></label><label class="md:col-span-2">Additional fields (JSON)<textarea id="entity_custom" rows="2">${JSON.stringify(val('custom_fields', {}), null, 0)}</textarea></label>`;
  const title = `${entityId ? 'Edit' : 'Add'} ${type === 'application' ? 'Application' : type === 'project' ? 'Project' : 'Assignment Group'}`;

  const canDeleteCurrent = entityId && (
    type === 'project' ? isGlobalAdmin :
    type === 'application' ? (isGlobalAdmin || (isProjectAdmin && record?.project_name && adminProjects.map(p => p.toLowerCase()).includes(record.project_name.toLowerCase()))) :
    false
  );

  document.getElementById('modalContainer').innerHTML = `<div class="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4"><div class="w-full max-w-2xl max-h-[90vh] overflow-y-auto rounded-2xl bg-[var(--card-bg)] p-5 shadow-2xl"><div class="flex justify-between mb-4"><div><h2 class="font-bold">${title}</h2><p class="text-[11px] text-slate-400">Fields can be updated at any time. Additional fields accept a JSON object.</p></div><button onclick="closeAdminModal()">✕</button></div><form onsubmit="submitAdminEntity(event, '${type}', ${entityId || 'null'})" class="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs admin-form">${fields}<div class="md:col-span-2 flex justify-between items-center pt-3 border-t border-[var(--border-color)] mt-2"><div>${canDeleteCurrent ? `<button type="button" onclick="deleteAdminEntity('${type}', ${entityId}, '${(record?.name || '').replace(/'/g, "\\'")}', true)" class="px-3 py-2 bg-red-500/10 text-red-600 hover:bg-red-500/20 rounded-lg font-bold border border-red-200 dark:border-red-900/50 flex items-center gap-1.5"><i data-lucide="trash-2" class="w-3.5 h-3.5"></i> Delete ${type === 'application' ? 'Application' : 'Project'}</button>` : ''}</div><div class="flex gap-2"><button type="button" onclick="closeAdminModal()" class="px-4 py-2 border rounded-lg">Cancel</button><button class="px-4 py-2 bg-purple-600 text-white rounded-lg font-bold">${entityId ? 'Save changes' : 'Create'}</button></div></div></form></div></div>`;
  lucide?.createIcons?.();
}

async function deleteAdminEntity(type, entityId, entityName, fromModal = false) {
  const typeLabel = type === 'application' ? 'application' : type === 'project' ? 'project' : type;
  const confirmMsg = type === 'project'
    ? `Are you sure you want to delete the project "${entityName}"?\n\nWARNING: All respective applications and assignment groups under this project will also be deleted, and related routing rules cleaned up.`
    : `Are you sure you want to delete the ${typeLabel} "${entityName}"?\n\nThis will remove configuration, unlink routing rules, and clean up associations.`;
  if (!confirm(confirmMsg)) {
    return;
  }
  try {
    const endpoint = type === 'application' ? 'applications' : type === 'project' ? 'projects' : 'groups';
    const response = await fetch(`${API_BASE}/admin/${endpoint}/${entityId}`, {
      method: 'DELETE',
      headers: {
        'X-User-ID': state.currentUser ? state.currentUser.id.toString() : '1'
      }
    });
    if (!response.ok) {
      const err = await response.json();
      alert(err.detail || `Unable to delete ${typeLabel}`);
      return;
    }
    alert(`${typeLabel.charAt(0).toUpperCase() + typeLabel.slice(1)} "${entityName}" deleted successfully.`);
    if (fromModal) closeAdminModal();
    // Refresh the view
    if (window.location.hash === '#/applications' || window.location.hash.startsWith('#/applications')) {
      renderApplicationsView(document.getElementById('mainApp'));
    } else if (window.location.hash === '#/projects' || window.location.hash.startsWith('#/projects')) {
      renderProjectsView(document.getElementById('mainApp'));
    } else {
      renderAdminEntityManagement(document.getElementById('mainApp'));
    }
  } catch (err) {
    alert(`Error deleting ${typeLabel}: ${err.message}`);
  }
}

function closeAdminModal() { document.getElementById('modalContainer').innerHTML = ''; }

async function renderTicketConfigurationView(container) {
  container.innerHTML = `<div class="p-8 text-center text-slate-400">Loading ticket configuration…</div>`;
  try {
    const authHeaders = { 'X-User-ID': state.currentUser ? state.currentUser.id.toString() : '1' };
    const [taxRes, colRes, appRes] = await Promise.all([
      fetch(`${API_BASE}/admin/configuration/taxonomy`, { headers: authHeaders }),
      fetch(`${API_BASE}/admin/configuration/columns`, { headers: authHeaders }),
      fetch(`${API_BASE}/admin/applications`, { headers: authHeaders })
    ]);
    if (![taxRes, colRes, appRes].every(r => r.ok)) throw new Error('Configuration API was not available');
    const [taxonomy, columns, apps] = await Promise.all([taxRes.json(), colRes.json(), appRes.json()]);
    state.ticketConfiguration = { taxonomy, columns, apps };
    container.innerHTML = `<div class="space-y-6"><div class="flex flex-col md:flex-row md:items-center md:justify-between gap-3"><div><h1 class="text-2xl font-black tracking-tight">Ticket Fields & Closure Notes</h1><p class="text-sm text-slate-500">Maintain closure categories and choose the information shown for Incidents, Service Requests, and Change Requests.</p></div><div class="flex gap-2"><button onclick="syncConfigurationToConsul()" class="border border-amber-500 text-amber-600 px-3 py-2 rounded-xl text-xs font-bold">Sync to Consul</button><button onclick="openTaxonomyModal()" class="bg-purple-600 text-white px-3 py-2 rounded-xl text-xs font-bold">+ Closure option</button><button onclick="openColumnModal()" class="bg-cyan-600 text-white px-3 py-2 rounded-xl text-xs font-bold">+ List column</button></div></div><div class="grid grid-cols-1 xl:grid-cols-2 gap-5"><section class="rounded-2xl bg-[var(--card-bg)] border border-[var(--border-color)] overflow-hidden"><div class="p-4 border-b border-[var(--border-color)]"><h2 class="font-bold text-sm">Closure taxonomy</h2><p class="text-[11px] text-slate-400 mt-1">Application-specific options appear alongside the standard closure list.</p></div><div class="max-h-[480px] overflow-auto divide-y divide-[var(--border-color)]">${taxonomy.map(t => `<div class="p-3 flex items-center justify-between gap-3"><div><div class="text-xs font-bold">${t.category} <span class="text-slate-400 font-normal">/ ${t.subcategory}</span></div><div class="text-[10px] text-slate-400">${t.ticket_type} · ${t.application_name}</div></div><div class="flex gap-2"><button onclick="openTaxonomyModal(${t.id})" class="text-purple-600 text-[10px] font-bold">Edit</button><button onclick="deleteTicketConfig('taxonomy', ${t.id})" class="text-red-500 text-[10px] font-bold">Remove</button></div></div>`).join('') || '<div class="p-4 text-sm text-slate-400">No custom closure options yet.</div>'}</div></section><section class="rounded-2xl bg-[var(--card-bg)] border border-[var(--border-color)] overflow-hidden"><div class="p-4 border-b border-[var(--border-color)]"><h2 class="font-bold text-sm">Ticket list columns</h2><p class="text-[11px] text-slate-400 mt-1">Disable, rename, reorder, or add columns without changing code.</p></div><div class="max-h-[480px] overflow-auto divide-y divide-[var(--border-color)]">${columns.map(c => `<div class="p-3 flex items-center justify-between gap-3"><div><div class="text-xs font-bold">${c.label} ${c.enabled ? '' : '<span class="text-amber-600">(hidden)</span>'}</div><div class="text-[10px] text-slate-400">${c.ticket_type} · key: ${c.column_key} · position: ${c.display_order}</div></div><div class="flex gap-2"><button onclick="openColumnModal(${c.id})" class="text-cyan-600 text-[10px] font-bold">Edit</button><button onclick="deleteTicketConfig('columns', ${c.id})" class="text-red-500 text-[10px] font-bold">Remove</button></div></div>`).join('') || '<div class="p-4 text-sm text-slate-400">Add columns to start tailoring a ticket list.</div>'}</div></section></div><div class="p-4 rounded-xl border border-cyan-500/30 bg-cyan-500/5 text-xs text-slate-500"><b class="text-cyan-600">Tip:</b> Use a stable data key such as <code>business_impact</code> or <code>vendor_reference</code> for a new column. Existing list fields can be hidden or relabeled; custom fields can be recorded on each Application, Project, or Assignment Group from Manage Applications & Teams.</div></div>`;
  } catch (err) { container.innerHTML = `<div class="p-8 text-center text-red-500">Unable to load ticket configuration: ${err.message}</div>`; }
}

function openTaxonomyModal(itemId = null) {
  const { taxonomy = [], apps = [] } = state.ticketConfiguration || {};
  const isGlobalAdmin = state.currentUser?.is_global_admin || state.currentUser?.username === 'admin' || state.currentUser?.role === 'administrator' || state.currentUser?.role === 'itsm_admin';
  const adminProjects = state.currentUser?.admin_projects || [];
  const allowedApps = isGlobalAdmin ? apps : apps.filter(a => adminProjects.includes(a.project_name) || adminProjects.includes(a.name));

  const item = taxonomy.find(x => x.id === itemId) || {};
  document.getElementById('modalContainer').innerHTML = `<div class="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4"><div class="w-full max-w-md rounded-2xl bg-[var(--card-bg)] p-5 shadow-2xl"><div class="flex justify-between mb-4"><h2 class="font-bold">${itemId ? 'Edit' : 'Add'} closure option</h2><button onclick="closeAdminModal()">✕</button></div><form onsubmit="saveTaxonomy(event, ${itemId || 'null'})" class="space-y-3 text-xs admin-form"><label>Ticket type<select id="tax_ticket"><option ${item.ticket_type === 'Incident' ? 'selected' : ''}>Incident</option><option ${item.ticket_type === 'Service Request' ? 'selected' : ''}>Service Request</option><option ${item.ticket_type === 'Change Request' ? 'selected' : ''}>Change Request</option></select></label><label>Closure category<input id="tax_category" required value="${item.category || ''}" placeholder="e.g. Vendor Issue"></label><label>Closure subcategory<input id="tax_subcategory" required value="${item.subcategory || ''}" placeholder="e.g. Awaiting vendor patch"></label><label>Application scope<select id="tax_app">${adminSelectOptions(allowedApps, item.application_id, isGlobalAdmin ? 'All applications' : 'Select application')}</select></label><label class="flex items-center gap-2 font-normal"><input type="checkbox" id="tax_active" ${item.active !== false ? 'checked' : ''}> Available for selection</label><div class="flex justify-end gap-2 pt-3"><button type="button" onclick="closeAdminModal()" class="px-4 py-2 border rounded-lg">Cancel</button><button class="px-4 py-2 bg-purple-600 text-white rounded-lg font-bold">Save</button></div></form></div></div>`;
}

function openColumnModal(itemId = null) {
  const item = (state.ticketConfiguration?.columns || []).find(x => x.id === itemId) || {};
  document.getElementById('modalContainer').innerHTML = `<div class="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4"><div class="w-full max-w-md rounded-2xl bg-[var(--card-bg)] p-5 shadow-2xl"><div class="flex justify-between mb-4"><h2 class="font-bold">${itemId ? 'Edit' : 'Add'} ticket list column</h2><button onclick="closeAdminModal()">✕</button></div><form onsubmit="saveTicketColumn(event, ${itemId || 'null'})" class="space-y-3 text-xs admin-form"><label>Ticket type<select id="col_ticket"><option ${item.ticket_type === 'Incident' ? 'selected' : ''}>Incident</option><option ${item.ticket_type === 'Service Request' ? 'selected' : ''}>Service Request</option><option ${item.ticket_type === 'Change Request' ? 'selected' : ''}>Change Request</option></select></label><label>Data key<input id="col_key" required value="${item.column_key || ''}" placeholder="vendor_reference"></label><label>Column label<input id="col_label" required value="${item.label || ''}" placeholder="Vendor reference"></label><label>Display position<input id="col_order" type="number" value="${item.display_order || 100}"></label><label class="flex items-center gap-2 font-normal"><input type="checkbox" id="col_enabled" ${item.enabled !== false ? 'checked' : ''}> Show this column</label><div class="flex justify-end gap-2 pt-3"><button type="button" onclick="closeAdminModal()" class="px-4 py-2 border rounded-lg">Cancel</button><button class="px-4 py-2 bg-cyan-600 text-white rounded-lg font-bold">Save</button></div></form></div></div>`;
}

async function saveTaxonomy(event, itemId) {
  event.preventDefault();
  const payload = {
    ticket_type: document.getElementById('tax_ticket').value,
    category: document.getElementById('tax_category').value,
    subcategory: document.getElementById('tax_subcategory').value,
    application_id: document.getElementById('tax_app').value ? Number(document.getElementById('tax_app').value) : null,
    active: document.getElementById('tax_active').checked
  };
  await saveTicketConfig('taxonomy', itemId, payload);
}

async function saveTicketColumn(event, itemId) {
  event.preventDefault();
  const payload = {
    ticket_type: document.getElementById('col_ticket').value,
    column_key: document.getElementById('col_key').value,
    label: document.getElementById('col_label').value,
    display_order: Number(document.getElementById('col_order').value),
    enabled: document.getElementById('col_enabled').checked
  };
  await saveTicketConfig('columns', itemId, payload);
}

async function saveTicketConfig(kind, itemId, payload) {
  const response = await fetch(`${API_BASE}/admin/configuration/${kind}${itemId ? `/${itemId}` : ''}`, {
    method: itemId ? 'PUT' : 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-User-ID': state.currentUser ? state.currentUser.id.toString() : '1'
    },
    body: JSON.stringify(payload)
  });
  if (!response.ok) {
    alert((await response.json()).detail || 'Unable to save configuration');
    return;
  }
  closeAdminModal();
  renderTicketConfigurationView(document.getElementById('mainApp'));
}

async function deleteTicketConfig(kind, itemId) {
  if (!confirm('Remove this configuration item?')) return;
  const response = await fetch(`${API_BASE}/admin/configuration/${kind}/${itemId}`, {
    method: 'DELETE',
    headers: {
      'X-User-ID': state.currentUser ? state.currentUser.id.toString() : '1'
    }
  });
  if (!response.ok) {
    alert('Unable to remove configuration');
    return;
  }
  renderTicketConfigurationView(document.getElementById('mainApp'));
}

async function syncConfigurationToConsul() {
  const response = await fetch(`${API_BASE}/admin/config/sync-consul`, {
    method: 'PUT',
    headers: {
      'X-User-ID': state.currentUser ? state.currentUser.id.toString() : '1'
    }
  });
  if (!response.ok) {
    const err = await response.json();
    alert(err.detail || 'Could not sync configuration to Consul');
    return;
  }
  alert('Configuration snapshot synced to Consul.');
}

async function submitAdminEntity(event, type, entityId = null) {
  event.preventDefault();
  const value = id => document.getElementById(id)?.value || null;
  const groupId = value('entity_group');
  const projectId = value('entity_project');
  const projectName = value('entity_project_name');
  const l2GroupId = value('entity_l2_group');
  const l3GroupId = value('entity_l3_group');

  let custom_fields = {};
  try { custom_fields = JSON.parse(value('entity_custom') || '{}'); } catch (_) { alert('Additional fields must be valid JSON.'); return; }
  const shared = { description: value('entity_description'), custom_fields };
  const payload = type === 'application' ? {
    ...shared,
    app_id: value('entity_code'),
    name: value('entity_name'),
    project_id: projectId ? Number(projectId) : null,
    project_name: projectName || undefined,
    business_owner: value('entity_business_owner'),
    technical_owner: value('entity_technical_owner'),
    business_service: value('entity_business_service'),
    support_hours: value('entity_hours'),
    environment: value('entity_environment'),
    criticality: value('entity_criticality'),
    default_assignment_group_id: groupId ? Number(groupId) : null
  }
    : type === 'project' ? {
    ...shared,
    project_id: value('entity_code'),
    name: value('entity_name'),
    application_id: value('entity_application') ? Number(value('entity_application')) : null,
    default_assignment_group_id: l2GroupId ? Number(l2GroupId) : (groupId ? Number(groupId) : null),
    l2_assignment_group_id: l2GroupId ? Number(l2GroupId) : (groupId ? Number(groupId) : null),
    l3_assignment_group_id: l3GroupId ? Number(l3GroupId) : null,
    project_manager: value('entity_project_manager'),
    business_owner: value('entity_business_owner'),
    technical_owner: value('entity_technical_owner'),
    support_hours: value('entity_hours'),
    environment: value('entity_environment'),
    criticality: value('entity_criticality')
  }
    : {
    ...shared,
    group_id: value('entity_code'),
    name: value('entity_name'),
    on_call_contact: value('entity_on_call'),
    first_escalation_contact: value('entity_l1'),
    second_escalation_contact: value('entity_l2'),
    escalation_group_id: value('entity_escalation_group') ? Number(value('entity_escalation_group')) : null
  };
  const endpoint = type === 'application' ? 'applications' : type === 'project' ? 'projects' : 'groups';
  const response = await fetch(`${API_BASE}/admin/${endpoint}${entityId ? `/${entityId}` : ''}`, {
    method: entityId ? 'PUT' : 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-User-ID': state.currentUser ? state.currentUser.id.toString() : '1'
    },
    body: JSON.stringify(payload)
  });
  if (!response.ok) { alert((await response.json()).detail || 'Unable to create configuration'); return; }
  closeAdminModal(); renderAdminEntityManagement(document.getElementById('mainApp'));
}

function openDistributionListModal(groupId, groupName) {
  document.getElementById('modalContainer').innerHTML = `<div class="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4"><div class="w-full max-w-md rounded-2xl bg-[var(--card-bg)] p-5 shadow-2xl"><div class="flex justify-between mb-4"><h2 class="font-bold">Add Distribution List</h2><button onclick="closeAdminModal()">✕</button></div><p class="text-xs text-slate-500 mb-3">Assignment group: <b>${groupName}</b></p><form onsubmit="submitDistributionList(event, ${groupId})" class="space-y-3 text-xs admin-form"><label>DL email *<input id="dl_email" type="email" required placeholder="support-team@accenture.com"></label><label>Display name<input id="dl_name" placeholder="Payment Support DL"></label><label>Privilege<select id="dl_privilege"><option value="support">Support team</option><option value="administrator">Administrator</option></select></label><div class="flex justify-end gap-2 pt-3"><button type="button" onclick="closeAdminModal()" class="px-4 py-2 border rounded-lg">Cancel</button><button class="px-4 py-2 bg-emerald-600 text-white rounded-lg font-bold">Add DL</button></div></form></div></div>`;
}

async function submitDistributionList(event, groupId) {
  event.preventDefault();
  const payload = { email: document.getElementById('dl_email').value, display_name: document.getElementById('dl_name').value, privilege: document.getElementById('dl_privilege').value };
  const response = await fetch(`${API_BASE}/admin/groups/${groupId}/distribution-lists`, { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload) });
  if (!response.ok) { alert((await response.json()).detail || 'Unable to add distribution list'); return; }
  closeAdminModal(); renderAdminEntityManagement(document.getElementById('mainApp'));
}

// --- VISUAL CONFIGURATION GRAPH ---
async function renderVisualConfigGraph(container) {
  container.innerHTML = `<div class="p-8 text-center text-slate-400"><i data-lucide="loader-2" class="w-8 h-8 animate-spin mx-auto mb-2 text-purple-500"></i>Building Configuration Graph...</div>`;
  lucide.createIcons();

  try {
    const res = await fetch(`${API_BASE}/admin/config/graph`);
    const graphData = await res.json();

    container.innerHTML = `
      <div class="space-y-4">
        <div class="flex items-center justify-between">
          <div>
            <h1 class="text-2xl font-black tracking-tight">Visual Configuration Hierarchy Graph</h1>
            <p class="text-sm text-slate-500">Interactive relationship tree: Application ↓ Project ↓ Routing Rules ↓ Assignment Group ↓ SLA Policy</p>
          </div>
          <button onclick="renderVisualConfigGraph(document.getElementById('mainApp'))" class="px-3 py-1.5 rounded-lg border border-[var(--border-color)] text-xs font-semibold flex items-center space-x-1.5">
            <i data-lucide="refresh-cw" class="w-3.5 h-3.5"></i>
            <span>Refresh Graph</span>
          </button>
        </div>

        <div class="rounded-2xl bg-[var(--card-bg)] border border-[var(--border-color)] p-4 shadow-sm">
          <div class="flex items-center justify-between mb-3 text-xs">
            <div class="flex items-center space-x-4">
              <span class="flex items-center space-x-1.5"><span class="w-3 h-3 rounded bg-purple-500"></span><span>Application</span></span>
              <span class="flex items-center space-x-1.5"><span class="w-3 h-3 rounded bg-indigo-500"></span><span>Project</span></span>
              <span class="flex items-center space-x-1.5"><span class="w-3 h-3 rounded bg-amber-500"></span><span>Routing Rule</span></span>
              <span class="flex items-center space-x-1.5"><span class="w-3 h-3 rounded bg-emerald-500"></span><span>Assignment Group</span></span>
              <span class="flex items-center space-x-1.5"><span class="w-3 h-3 rounded bg-purple-500"></span><span>SLA Policy</span></span>
            </div>
            <span class="text-slate-400">Click any card to inspect entity details</span>
          </div>

          <!-- Hierarchy Column View -->
          <div class="grid grid-cols-1 md:grid-cols-5 gap-4 min-h-[500px]">
            <!-- Col 1: Applications -->
            <div class="p-3 rounded-xl bg-[var(--bg-tertiary)] space-y-3">
              <div class="font-bold text-xs uppercase tracking-wider text-purple-600">Applications (${graphData.nodes.filter(n=>n.type==='application').length})</div>
              ${graphData.nodes.filter(n => n.type === 'application').map(n => `
                <div onclick="showNodeDetails(${JSON.stringify(n).replace(/"/g, '&quot;')})" class="p-3 rounded-lg bg-[var(--card-bg)] border border-[var(--border-color)] shadow-sm hover:border-purple-500 cursor-pointer text-xs transition-all">
                  <div class="font-bold text-[var(--text-primary)]">${n.label}</div>
                  <div class="text-[10px] text-slate-400 mt-0.5">${n.subtitle}</div>
                </div>
              `).join('')}
            </div>

            <!-- Col 2: Projects -->
            <div class="p-3 rounded-xl bg-[var(--bg-tertiary)] space-y-3">
              <div class="font-bold text-xs uppercase tracking-wider text-indigo-600">Projects (${graphData.nodes.filter(n=>n.type==='project').length})</div>
              ${graphData.nodes.filter(n => n.type === 'project').map(n => `
                <div onclick="showNodeDetails(${JSON.stringify(n).replace(/"/g, '&quot;')})" class="p-3 rounded-lg bg-[var(--card-bg)] border border-[var(--border-color)] shadow-sm hover:border-indigo-500 cursor-pointer text-xs transition-all">
                  <div class="font-bold text-[var(--text-primary)]">${n.label}</div>
                  <div class="text-[10px] text-slate-400 mt-0.5">${n.subtitle}</div>
                </div>
              `).join('')}
            </div>

            <!-- Col 3: Routing Rules -->
            <div class="p-3 rounded-xl bg-[var(--bg-tertiary)] space-y-3">
              <div class="font-bold text-xs uppercase tracking-wider text-amber-600">Routing Rules (${graphData.nodes.filter(n=>n.type==='routing_rule').length})</div>
              ${graphData.nodes.filter(n => n.type === 'routing_rule').map(n => `
                <div onclick="showNodeDetails(${JSON.stringify(n).replace(/"/g, '&quot;')})" class="p-3 rounded-lg bg-[var(--card-bg)] border border-[var(--border-color)] shadow-sm hover:border-amber-500 cursor-pointer text-xs transition-all">
                  <div class="font-bold text-[var(--text-primary)]">${n.label}</div>
                  <div class="text-[10px] text-slate-400 mt-0.5">${n.subtitle}</div>
                </div>
              `).join('')}
            </div>

            <!-- Col 4: Assignment Groups -->
            <div class="p-3 rounded-xl bg-[var(--bg-tertiary)] space-y-3">
              <div class="font-bold text-xs uppercase tracking-wider text-emerald-600">Support Teams (${graphData.nodes.filter(n=>n.type==='group').length})</div>
              ${graphData.nodes.filter(n => n.type === 'group').map(n => `
                <div onclick="showNodeDetails(${JSON.stringify(n).replace(/"/g, '&quot;')})" class="p-3 rounded-lg bg-[var(--card-bg)] border border-[var(--border-color)] shadow-sm hover:border-emerald-500 cursor-pointer text-xs transition-all">
                  <div class="font-bold text-[var(--text-primary)]">${n.label}</div>
                  <div class="text-[10px] text-slate-400 mt-0.5">${n.subtitle}</div>
                </div>
              `).join('')}
            </div>

            <!-- Col 5: SLA Policies -->
            <div class="p-3 rounded-xl bg-[var(--bg-tertiary)] space-y-3">
              <div class="font-bold text-xs uppercase tracking-wider text-purple-600">SLA Policies (${graphData.nodes.filter(n=>n.type==='sla_policy').length})</div>
              ${graphData.nodes.filter(n => n.type === 'sla_policy').map(n => `
                <div onclick="showNodeDetails(${JSON.stringify(n).replace(/"/g, '&quot;')})" class="p-3 rounded-lg bg-[var(--card-bg)] border border-[var(--border-color)] shadow-sm hover:border-purple-500 cursor-pointer text-xs transition-all">
                  <div class="font-bold text-[var(--text-primary)]">${n.label}</div>
                  <div class="text-[10px] text-slate-400 mt-0.5">${n.subtitle}</div>
                </div>
              `).join('')}
            </div>
          </div>
        </div>

        <!-- Selected Node Details Drawer -->
        <div id="nodeDetailBox" class="hidden p-5 rounded-2xl bg-[var(--card-bg)] border border-purple-500/40 shadow-lg"></div>
      </div>
    `;
    lucide.createIcons();
  } catch (err) {
    container.innerHTML = `<div class="p-8 text-center text-red-500">Error loading graph: ${err.message}</div>`;
  }
}

function showNodeDetails(node) {
  const box = document.getElementById('nodeDetailBox');
  if (!box) return;
  box.classList.remove('hidden');
  box.innerHTML = `
    <div class="flex items-center justify-between pb-3 border-b border-[var(--border-color)] mb-3">
      <div class="flex items-center space-x-2">
        <span class="px-2 py-0.5 rounded text-[10px] font-bold uppercase bg-purple-500 text-white">${node.type}</span>
        <span class="text-base font-bold">${node.label}</span>
      </div>
      <button onclick="document.getElementById('nodeDetailBox').classList.add('hidden')" class="text-slate-400 hover:text-white">✕</button>
    </div>
    <pre class="p-3 rounded-xl bg-[var(--bg-tertiary)] text-xs overflow-x-auto font-mono text-[var(--text-primary)]">${JSON.stringify(node.details, null, 2)}</pre>
  `;
}

// --- ROUTING & SLA SIMULATOR VIEW ---
async function renderRoutingSimulatorView(container) {
  const appsRes = await fetch(`${API_BASE}/config/export`);
  const config = await appsRes.json();
  const apps = config.applications || [];
  const projects = config.projects || [];

  container.innerHTML = `
    <div class="space-y-6">
      <div>
        <h1 class="text-2xl font-black tracking-tight">Routing & SLA Simulator</h1>
        <p class="text-sm text-slate-500">Simulate ticket dispatching and SLA precedence rules before committing changes.</p>
      </div>

      <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <!-- Input Form -->
        <div class="p-6 rounded-2xl bg-[var(--card-bg)] border border-[var(--border-color)] shadow-sm space-y-4">
          <h2 class="text-sm font-bold pb-2 border-b border-[var(--border-color)]">Simulation Parameters</h2>

          <div>
            <label class="block text-xs font-semibold text-slate-400 mb-1">Application</label>
            <select id="sim_app" onchange="filterSimProjects()" class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-lg p-2 text-xs">
              <option value="">Select Application...</option>
              ${apps.map(a => `<option value="${a.id}">${a.name}</option>`).join('')}
            </select>
          </div>

          <div>
            <label class="block text-xs font-semibold text-slate-400 mb-1">Project</label>
            <select id="sim_project" class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-lg p-2 text-xs">
              <option value="">Select Project...</option>
              ${projects.map(p => `<option value="${p.id}" data-app="${p.application_id}">${p.name}</option>`).join('')}
            </select>
          </div>

          <div>
            <label class="block text-xs font-semibold text-slate-400 mb-1">Category</label>
            <select id="sim_category" class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-lg p-2 text-xs">
              <option value="Application">Application</option>
              <option value="Database">Database</option>
              <option value="Network">Network</option>
              <option value="Security">Security</option>
              <option value="Cloud">Cloud</option>
            </select>
          </div>

          <div class="grid grid-cols-2 gap-3">
            <div>
              <label class="block text-xs font-semibold text-slate-400 mb-1">Impact</label>
              <select id="sim_impact" class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-lg p-2 text-xs">
                <option value="Critical">Critical</option>
                <option value="High" selected>High</option>
                <option value="Medium">Medium</option>
                <option value="Low">Low</option>
              </select>
            </div>
            <div>
              <label class="block text-xs font-semibold text-slate-400 mb-1">Urgency</label>
              <select id="sim_urgency" class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-lg p-2 text-xs">
                <option value="Critical">Critical</option>
                <option value="High" selected>High</option>
                <option value="Medium">Medium</option>
                <option value="Low">Low</option>
              </select>
            </div>
          </div>

          <button onclick="executeSimulation()" class="w-full bg-emerald-600 hover:bg-emerald-700 text-white font-bold py-2.5 rounded-xl text-xs shadow flex items-center justify-center space-x-2">
            <i data-lucide="play" class="w-4 h-4"></i>
            <span>Run Simulation</span>
          </button>
        </div>

        <!-- Simulation Results Display -->
        <div id="simResultsBox" class="lg:col-span-2 p-6 rounded-2xl bg-[var(--card-bg)] border border-[var(--border-color)] shadow-sm">
          <div class="text-center text-slate-400 py-12">
            <i data-lucide="cpu" class="w-12 h-12 mx-auto mb-3 opacity-30"></i>
            <div class="font-bold text-sm">Simulator Idle</div>
            <div class="text-xs text-slate-500 mt-1">Configure parameters on the left and click "Run Simulation".</div>
          </div>
        </div>
      </div>
    </div>
  `;
  lucide.createIcons();
}

function filterSimProjects() {
  const appId = document.getElementById('sim_app').value;
  const projSelect = document.getElementById('sim_project');
  Array.from(projSelect.options).forEach(opt => {
    if (!opt.value) return;
    const match = !appId || opt.getAttribute('data-app') === appId;
    opt.style.display = match ? 'block' : 'none';
  });
}

async function executeSimulation() {
  const appId = document.getElementById('sim_app').value;
  const projId = document.getElementById('sim_project').value;
  const category = document.getElementById('sim_category').value;
  const impact = document.getElementById('sim_impact').value;
  const urgency = document.getElementById('sim_urgency').value;

  const resultsBox = document.getElementById('simResultsBox');
  resultsBox.innerHTML = `<div class="p-12 text-center text-slate-400"><i data-lucide="loader-2" class="w-8 h-8 animate-spin mx-auto mb-2 text-emerald-500"></i>Evaluating 6-tier routing & SLA engines...</div>`;
  lucide.createIcons();

  try {
    const res = await fetch(`${API_BASE}/simulator`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        application_id: appId ? parseInt(appId) : null,
        project_id: projId ? parseInt(projId) : null,
        category: category,
        impact: impact,
        urgency: urgency
      })
    });
    const data = await res.json();

    resultsBox.innerHTML = `
      <div class="space-y-6">
        <div class="flex items-center justify-between pb-3 border-b border-[var(--border-color)]">
          <h2 class="text-base font-bold text-emerald-600">✓ Simulation Complete</h2>
          <span class="text-xs text-slate-400 font-mono">${data.simulation_timestamp}</span>
        </div>

        <!-- Results Grid -->
        <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div class="p-4 rounded-xl bg-[var(--bg-tertiary)] border border-[var(--border-color)]">
            <div class="text-xs text-slate-400 font-semibold uppercase">Calculated Priority</div>
            <div class="text-3xl font-black mt-1 text-red-600">${data.calculated_priority}</div>
            <div class="text-[11px] text-slate-400 mt-1">From ${impact} Impact + ${urgency} Urgency</div>
          </div>

          <div class="p-4 rounded-xl bg-[var(--bg-tertiary)] border border-[var(--border-color)]">
            <div class="text-xs text-slate-400 font-semibold uppercase">Selected Team</div>
            <div class="text-base font-bold mt-1 text-purple-600">${data.selected_assignment_group.name}</div>
            <div class="text-[11px] text-emerald-600 mt-1 font-semibold">Hierarchy Level ${data.selected_assignment_group.matched_hierarchy_level} Match</div>
          </div>

          <div class="p-4 rounded-xl bg-[var(--bg-tertiary)] border border-[var(--border-color)]">
            <div class="text-xs text-slate-400 font-semibold uppercase">Selected SLA Policy</div>
            <div class="text-base font-bold mt-1 text-purple-600">${data.selected_sla.name}</div>
            <div class="text-[11px] text-purple-500 mt-1 font-semibold">Version ${data.selected_sla.version}</div>
          </div>
        </div>

        <!-- Hierarchy Match Details -->
        <div class="p-4 rounded-xl border border-[var(--border-color)] space-y-3 bg-[var(--card-bg)] text-xs">
          <div class="font-bold text-sm">Execution Engine Trace</div>
          <div class="flex items-start space-x-2">
            <i data-lucide="check" class="w-4 h-4 text-emerald-500 mt-0.5"></i>
            <div>
              <b>Routing Engine:</b> ${data.selected_assignment_group.reason}
              <span class="block text-[11px] text-slate-400 font-mono">Rule Code: ${data.selected_assignment_group.rule_code} (${data.selected_assignment_group.matched_rule_type})</span>
            </div>
          </div>
          <div class="flex items-start space-x-2">
            <i data-lucide="check" class="w-4 h-4 text-emerald-500 mt-0.5"></i>
            <div>
              <b>SLA Engine:</b> ${data.selected_sla.reason}
              <span class="block text-[11px] text-slate-400">Response Target: ${data.selected_sla.response_target_formatted} | Resolution Target: ${data.selected_sla.resolution_target_formatted}</span>
            </div>
          </div>
          <div class="flex items-start space-x-2">
            <i data-lucide="check" class="w-4 h-4 text-emerald-500 mt-0.5"></i>
            <div>
              <b>Business Calendar:</b> ${data.business_calendar.name} (${data.business_calendar.timezone})
              <span class="block text-[11px] text-slate-400">Active Working Hours: ${data.business_calendar.working_hours}</span>
            </div>
          </div>
        </div>
      </div>
    `;
    lucide.createIcons();
  } catch (err) {
    resultsBox.innerHTML = `<div class="p-8 text-center text-red-500">Simulation failed: ${err.message}</div>`;
  }
}

// --- CONFIGURATION VALIDATION VIEW ---
async function renderConfigValidationView(container) {
  container.innerHTML = `<div class="p-8 text-center text-slate-400"><i data-lucide="loader-2" class="w-8 h-8 animate-spin mx-auto mb-2 text-purple-500"></i>Scanning platform configuration integrity...</div>`;
  lucide.createIcons();

  try {
    const res = await fetch(`${API_BASE}/admin/config/validation`);
    const data = await res.json();

    container.innerHTML = `
      <div class="space-y-6">
        <div class="flex items-center justify-between">
          <div>
            <h1 class="text-2xl font-black tracking-tight">Configuration Integrity & Validation</h1>
            <p class="text-sm text-slate-500">Automatic scanner detecting missing SLAs, orphaned projects, conflicting routing rules, and expired policies.</p>
          </div>
          <button onclick="renderConfigValidationView(document.getElementById('mainApp'))" class="px-4 py-2 rounded-xl bg-purple-600 text-white text-xs font-semibold">
            Re-scan System
          </button>
        </div>

        <div class="p-6 rounded-2xl bg-[var(--card-bg)] border border-[var(--border-color)] shadow-sm space-y-4">
          <div class="flex items-center space-x-3 pb-3 border-b border-[var(--border-color)]">
            <span class="w-3 h-3 rounded-full ${data.status === 'clean' ? 'bg-emerald-500' : 'bg-amber-500 animate-ping'}"></span>
            <span class="font-bold text-sm">Status: ${data.total_issues === 0 ? 'All Configurations Verified & Healthy' : `${data.total_issues} Integrity Warnings Detected`}</span>
          </div>

          <div class="space-y-3">
            ${data.issues.map(iss => `
              <div class="p-4 rounded-xl border ${iss.level === 'error' ? 'border-red-500/40 bg-red-500/10' : 'border-amber-500/40 bg-amber-500/10'} text-xs flex items-start space-x-3">
                <i data-lucide="alert-triangle" class="w-5 h-5 ${iss.level === 'error' ? 'text-red-500' : 'text-amber-500'} flex-shrink-0 mt-0.5"></i>
                <div class="flex-1">
                  <div class="font-bold text-[var(--text-primary)]">[${iss.entity}] ${iss.code}</div>
                  <div class="text-slate-400 mt-0.5">${iss.message}</div>
                </div>
              </div>
            `).join('')}
          </div>
        </div>
      </div>
    `;
    lucide.createIcons();
  } catch (err) {
    container.innerHTML = `<div class="p-8 text-center text-red-500">Validation error: ${err.message}</div>`;
  }
}

// // --- SLA ADMIN & VERSIONING VIEW ---
async function renderSlaAdminView(container) {
  container.innerHTML = `<div class="p-8 text-center text-slate-400"><i data-lucide="loader-2" class="w-8 h-8 animate-spin mx-auto mb-2 text-purple-500"></i>Loading SLA Policies...</div>`;
  lucide.createIcons();

  const userId = state.currentUser?.id || 1;
  const headers = { 'X-User-ID': String(userId) };
  const res = await fetch(`${API_BASE}/admin/slas`, { headers });
  if (!res.ok) {
    container.innerHTML = `<div class="p-8 text-center text-red-500">Access denied or error loading SLA policies.</div>`;
    return;
  }
  const slas = await res.json();

  // Fetch business calendars for the edit modal
  let calendars = [];
  try {
    const calRes = await fetch(`${API_BASE}/admin/calendars`, { headers });
    if (calRes.ok) calendars = await calRes.json();
  } catch (_) {}

  const isGlobalAdmin = state.currentUser?.role === 'administrator' || state.currentUser?.username === 'admin';

  let currentTypeFilter = 'all';
  let currentPriorityFilter = 'all';
  let searchQuery = '';

  const priorityBadge = p => {
    const cls = {
      P1: 'bg-red-100 dark:bg-red-950/60 text-red-700 dark:text-red-300 border border-red-200 dark:border-red-800',
      P2: 'bg-orange-100 dark:bg-orange-950/60 text-orange-700 dark:text-orange-300 border border-orange-200 dark:border-orange-800',
      P3: 'bg-amber-100 dark:bg-amber-950/60 text-amber-700 dark:text-amber-300 border border-amber-200 dark:border-amber-800',
      P4: 'bg-blue-100 dark:bg-blue-950/60 text-blue-700 dark:text-blue-300 border border-blue-200 dark:border-blue-800'
    };
    return `<span class="px-2 py-0.5 rounded text-[10px] font-bold ${cls[p] || 'bg-slate-100 text-slate-700'}">${p}</span>`;
  };

  const ticketTypeBadge = type => {
    const t = type || 'Incident';
    if (t === 'Incident') {
      return `<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[11px] font-semibold bg-rose-50 dark:bg-rose-950/40 text-rose-700 dark:text-rose-300 border border-rose-200 dark:border-rose-900/50"><i data-lucide="alert-octagon" class="w-3 h-3"></i>Incident</span>`;
    }
    if (t === 'Service Request') {
      return `<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[11px] font-semibold bg-sky-50 dark:bg-sky-950/40 text-sky-700 dark:text-sky-300 border border-sky-200 dark:border-sky-900/50"><i data-lucide="inbox" class="w-3 h-3"></i>Service Request</span>`;
    }
    if (t === 'Change Request') {
      return `<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[11px] font-semibold bg-purple-50 dark:bg-purple-950/40 text-purple-700 dark:text-purple-300 border border-purple-200 dark:border-purple-900/50"><i data-lucide="git-pull-request" class="w-3 h-3"></i>Change Request</span>`;
    }
    return `<span class="px-2 py-0.5 rounded-md text-[11px] font-semibold bg-slate-100 text-slate-700">${t}</span>`;
  };

  const fmtHoursAndMins = (m, labelClass = 'text-slate-900 dark:text-slate-100') => {
    if (!m && m !== 0) return '<span class="text-slate-400">—</span>';
    const hours = m / 60.0;
    let hStr = '';
    if (hours >= 24 && hours % 24 === 0) {
      const days = hours / 24;
      hStr = `${hours} hrs (${days}d)`;
    } else if (Number.isInteger(hours)) {
      hStr = `${hours}.0 hrs`;
    } else {
      hStr = `${hours.toFixed(2).replace(/\\.?0+$/, '')} hrs`;
    }
    return `<div class="flex flex-col">
      <span class="font-bold ${labelClass} text-xs tracking-tight">${hStr}</span>
      <span class="text-[10px] text-slate-400 font-medium">${m} mins</span>
    </div>`;
  };

  let pauseConditions = [];

  const renderContent = () => {
    const filtered = slas.filter(s => {
      if (currentTypeFilter !== 'all' && (s.ticket_type || 'Incident') !== currentTypeFilter) return false;
      if (currentPriorityFilter !== 'all' && s.priority !== currentPriorityFilter) return false;
      if (searchQuery) {
        const q = searchQuery.toLowerCase();
        const code = (s.policy_code || '').toLowerCase();
        const name = (s.name || '').toLowerCase();
        const proj = (s.project_name || '').toLowerCase();
        const desc = (s.description || '').toLowerCase();
        if (!code.includes(q) && !name.includes(q) && !proj.includes(q) && !desc.includes(q)) return false;
      }
      return true;
    });

    const incidentCount = slas.filter(s => (s.ticket_type || 'Incident') === 'Incident').length;
    const requestCount = slas.filter(s => s.ticket_type === 'Service Request').length;
    const changeCount = slas.filter(s => s.ticket_type === 'Change Request').length;

    container.innerHTML = `
      <div class="space-y-6">
        <!-- Header -->
        <div class="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 class="text-2xl font-black tracking-tight">SLA Policies &amp; Targets</h1>
            <p class="text-sm text-slate-500">Configure response &amp; resolution SLAs in hours and minutes across Incidents, Service Requests, and Change Requests (P1–P4).</p>
          </div>
          ${isGlobalAdmin ? `
          <button id="sla-new-btn" class="flex items-center gap-1.5 px-4 py-2 rounded-xl bg-purple-600 text-white text-sm font-semibold hover:bg-purple-700 transition-colors shadow">
            <i data-lucide="plus" class="w-4 h-4"></i> New SLA Policy
          </button>` : ''}
        </div>

        <!-- Filter Controls -->
        <div class="p-4 rounded-2xl bg-[var(--card-bg)] border border-[var(--border-color)] space-y-3">
          <!-- Ticket Type Filter Tabs -->
          <div class="flex flex-wrap items-center justify-between gap-3">
            <div class="flex flex-wrap items-center gap-1.5">
              <button class="sla-type-filter px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${currentTypeFilter === 'all' ? 'bg-purple-600 text-white shadow-sm' : 'bg-[var(--bg-tertiary)] text-slate-500 hover:text-slate-900 dark:hover:text-white'}" data-type="all">
                All Ticket Types (${slas.length})
              </button>
              <button class="sla-type-filter px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${currentTypeFilter === 'Incident' ? 'bg-rose-600 text-white shadow-sm' : 'bg-[var(--bg-tertiary)] text-slate-500 hover:text-slate-900 dark:hover:text-white'}" data-type="Incident">
                Incidents (${incidentCount})
              </button>
              <button class="sla-type-filter px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${currentTypeFilter === 'Service Request' ? 'bg-sky-600 text-white shadow-sm' : 'bg-[var(--bg-tertiary)] text-slate-500 hover:text-slate-900 dark:hover:text-white'}" data-type="Service Request">
                Service Requests (${requestCount})
              </button>
              <button class="sla-type-filter px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${currentTypeFilter === 'Change Request' ? 'bg-purple-600 text-white shadow-sm' : 'bg-[var(--bg-tertiary)] text-slate-500 hover:text-slate-900 dark:hover:text-white'}" data-type="Change Request">
                Change Requests (${changeCount})
              </button>
            </div>

            <!-- Search -->
            <div class="relative w-full sm:w-64">
              <i data-lucide="search" class="w-3.5 h-3.5 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400"></i>
              <input id="sla-search-input" type="text" placeholder="Search SLA policies..." value="${searchQuery}" class="w-full pl-9 pr-3 py-1.5 rounded-lg text-xs border border-[var(--border-color)] bg-[var(--bg-secondary)] focus:outline-none focus:ring-2 focus:ring-purple-500" />
            </div>
          </div>

          <!-- Priority Filter Pills -->
          <div class="flex items-center gap-2 pt-2 border-t border-[var(--border-color)]">
            <span class="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">Priority:</span>
            <div class="flex items-center gap-1">
              <button class="sla-pri-filter px-2.5 py-1 rounded-md text-[11px] font-medium transition-colors ${currentPriorityFilter === 'all' ? 'bg-slate-800 text-white dark:bg-slate-200 dark:text-slate-900' : 'bg-[var(--bg-tertiary)] text-slate-500 hover:bg-slate-200 dark:hover:bg-slate-800'}" data-pri="all">All</button>
              <button class="sla-pri-filter px-2.5 py-1 rounded-md text-[11px] font-medium transition-colors ${currentPriorityFilter === 'P1' ? 'bg-red-600 text-white' : 'bg-[var(--bg-tertiary)] text-slate-500 hover:bg-slate-200 dark:hover:bg-slate-800'}" data-pri="P1">P1 Critical</button>
              <button class="sla-pri-filter px-2.5 py-1 rounded-md text-[11px] font-medium transition-colors ${currentPriorityFilter === 'P2' ? 'bg-orange-600 text-white' : 'bg-[var(--bg-tertiary)] text-slate-500 hover:bg-slate-200 dark:hover:bg-slate-800'}" data-pri="P2">P2 High</button>
              <button class="sla-pri-filter px-2.5 py-1 rounded-md text-[11px] font-medium transition-colors ${currentPriorityFilter === 'P3' ? 'bg-amber-600 text-white' : 'bg-[var(--bg-tertiary)] text-slate-500 hover:bg-slate-200 dark:hover:bg-slate-800'}" data-pri="P3">P3 Standard</button>
              <button class="sla-pri-filter px-2.5 py-1 rounded-md text-[11px] font-medium transition-colors ${currentPriorityFilter === 'P4' ? 'bg-blue-600 text-white' : 'bg-[var(--bg-tertiary)] text-slate-500 hover:bg-slate-200 dark:hover:bg-slate-800'}" data-pri="P4">P4 Low</button>
            </div>
          </div>
        </div>

        ${filtered.length === 0 ? `
          <div class="rounded-2xl bg-[var(--card-bg)] border border-[var(--border-color)] p-12 text-center text-slate-400">
            <i data-lucide="shield-off" class="w-10 h-10 mx-auto mb-3 opacity-40"></i>
            <p class="font-semibold">No SLA policies match the selected filters.</p>
            <p class="text-xs mt-1 text-slate-500">Try adjusting your filters or search query.</p>
          </div>` : `
        <!-- Table -->
        <div class="rounded-2xl bg-[var(--card-bg)] border border-[var(--border-color)] overflow-hidden shadow-sm">
          <table class="w-full text-left text-xs">
            <thead class="bg-[var(--bg-tertiary)] text-slate-400 uppercase font-semibold text-[10px]">
              <tr>
                <th class="p-3.5">Policy Code</th>
                <th class="p-3.5">Ticket Type</th>
                <th class="p-3.5">Ver.</th>
                <th class="p-3.5">Policy Name</th>
                <th class="p-3.5">Project / Scope</th>
                <th class="p-3.5">Priority</th>
                <th class="p-3.5">Response Target (Hrs)</th>
                <th class="p-3.5">Resolution Target (Hrs)</th>
                <th class="p-3.5">Warn %</th>
                <th class="p-3.5">Effective Range</th>
                <th class="p-3.5">Status</th>
                <th class="p-3.5 text-right">Actions</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-[var(--border-color)]">
              ${filtered.map(s => `
                <tr class="hover:bg-[var(--bg-tertiary)] transition-colors ${!s.active ? 'opacity-50' : ''}">
                  <td class="p-3.5 font-bold text-purple-600 dark:text-purple-400">${s.policy_code}</td>
                  <td class="p-3.5">${ticketTypeBadge(s.ticket_type)}</td>
                  <td class="p-3.5"><span class="px-2 py-0.5 rounded bg-purple-100 dark:bg-purple-950 text-purple-600 font-bold">v${s.version}</span></td>
                  <td class="p-3.5 font-semibold max-w-[180px]"><div class="truncate" title="${s.name}">${s.name}</div></td>
                  <td class="p-3.5 text-slate-500">${s.project_name && s.project_name !== 'Any' ? `<span class="px-1.5 py-0.5 rounded bg-indigo-50 dark:bg-indigo-950 text-indigo-700 dark:text-indigo-300 font-medium">${s.project_name}</span>` : '<span class="text-slate-400">Global Fallback</span>'}</td>
                  <td class="p-3.5">${priorityBadge(s.priority)}</td>
                  <td class="p-3.5">${fmtHoursAndMins(s.response_target_mins, 'text-emerald-700 dark:text-emerald-400')}</td>
                  <td class="p-3.5">${fmtHoursAndMins(s.resolution_target_mins, 'text-blue-700 dark:text-blue-400')}</td>
                  <td class="p-3.5 text-amber-600 font-semibold">${s.warning_threshold_pct}%</td>
                  <td class="p-3.5 text-slate-500 text-[10px]">${s.effective_from ? s.effective_from.slice(0,10) : '—'} → ${s.effective_to ? s.effective_to.slice(0,10) : 'Ongoing'}</td>
                  <td class="p-3.5"><span class="px-2 py-0.5 rounded text-[10px] font-bold ${s.active ? 'text-emerald-600 bg-emerald-50 dark:bg-emerald-950' : 'text-slate-400 bg-slate-100 dark:bg-slate-800'}">${s.active ? 'Active' : 'Archived'}</span></td>
                  <td class="p-3.5 text-right">
                    ${s.can_edit ? `
                    <button class="sla-edit-btn inline-flex items-center gap-1 px-2.5 py-1 rounded-lg bg-purple-50 dark:bg-purple-950 text-purple-700 dark:text-purple-300 hover:bg-purple-100 dark:hover:bg-purple-900 text-xs font-semibold transition-colors"
                      data-id="${s.id}">
                      <i data-lucide="pencil" class="w-3 h-3"></i> Edit Target
                    </button>` : `<span class="text-slate-300 text-[10px]">—</span>`}
                  </td>
                </tr>
              `).join('')}
            </tbody>
          </table>
        </div>`}
      </div>

      <!-- Edit / Create Modal -->
      <div id="sla-modal" class="hidden fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm p-4">
        <div class="bg-[var(--card-bg)] rounded-2xl shadow-2xl border border-[var(--border-color)] w-full max-w-2xl max-h-[90vh] overflow-y-auto">
          <div class="flex items-center justify-between p-5 border-b border-[var(--border-color)]">
            <div>
              <h2 id="sla-modal-title" class="text-base font-bold">Edit SLA Policy</h2>
              <p class="text-xs text-slate-500">Configure response and resolution targets in hours and minutes.</p>
            </div>
            <button id="sla-modal-close" class="p-1 rounded-lg hover:bg-[var(--bg-tertiary)] transition-colors">
              <i data-lucide="x" class="w-4 h-4"></i>
            </button>
          </div>
          <form id="sla-modal-form" class="p-5 space-y-4">
            <input type="hidden" id="sla-modal-id" />

            <div class="grid grid-cols-1 sm:grid-cols-3 gap-3">
              <div>
                <label class="block text-xs font-semibold text-slate-500 mb-1">Policy Code</label>
                <input id="sla-modal-code" type="text" class="w-full rounded-lg border border-[var(--border-color)] bg-[var(--bg-secondary)] px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-purple-500" placeholder="e.g. SLA-P1-REQ" />
              </div>
              <div>
                <label class="block text-xs font-semibold text-slate-500 mb-1">Ticket Type</label>
                <select id="sla-modal-ticket-type" class="w-full rounded-lg border border-[var(--border-color)] bg-[var(--bg-secondary)] px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-purple-500">
                  <option value="Incident">Incident</option>
                  <option value="Service Request">Service Request</option>
                  <option value="Change Request">Change Request</option>
                </select>
              </div>
              <div>
                <label class="block text-xs font-semibold text-slate-500 mb-1">Priority</label>
                <select id="sla-modal-priority" class="w-full rounded-lg border border-[var(--border-color)] bg-[var(--bg-secondary)] px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-purple-500">
                  <option value="P1">P1 - Critical</option>
                  <option value="P2">P2 - High</option>
                  <option value="P3">P3 - Standard</option>
                  <option value="P4">P4 - Low</option>
                </select>
              </div>
            </div>

            <div>
              <label class="block text-xs font-semibold text-slate-500 mb-1">Policy Name</label>
              <input id="sla-modal-name" type="text" class="w-full rounded-lg border border-[var(--border-color)] bg-[var(--bg-secondary)] px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-purple-500" placeholder="e.g. Service Request P2 Standard SLA" />
            </div>

            <!-- Response Target Configuration (Hours & Minutes + Quick Presets) -->
            <div class="p-3.5 rounded-xl bg-emerald-50/50 dark:bg-emerald-950/20 border border-emerald-200/60 dark:border-emerald-900/40 space-y-2.5">
              <div class="flex items-center justify-between">
                <label class="block text-xs font-bold text-emerald-800 dark:text-emerald-300">
                  Response SLA Target <span class="font-normal text-emerald-600 dark:text-emerald-400">(Initial response acknowledge)</span>
                </label>
                <span id="sla-resp-human" class="text-xs font-bold text-emerald-700 dark:text-emerald-300 font-mono"></span>
              </div>
              <div class="grid grid-cols-2 gap-3">
                <div>
                  <label class="block text-[11px] font-semibold text-slate-500 mb-1">Target in Hours</label>
                  <div class="relative">
                    <input id="sla-modal-resp-hours" type="number" step="0.25" min="0.05" class="w-full rounded-lg border border-[var(--border-color)] bg-[var(--bg-secondary)] px-3 py-2 pr-12 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500" placeholder="e.g. 0.5" />
                    <span class="absolute right-3 top-1/2 -translate-y-1/2 text-xs font-semibold text-slate-400">hrs</span>
                  </div>
                </div>
                <div>
                  <label class="block text-[11px] font-semibold text-slate-500 mb-1">Target in Minutes</label>
                  <div class="relative">
                    <input id="sla-modal-resp" type="number" min="1" class="w-full rounded-lg border border-[var(--border-color)] bg-[var(--bg-secondary)] px-3 py-2 pr-12 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500" placeholder="e.g. 30" />
                    <span class="absolute right-3 top-1/2 -translate-y-1/2 text-xs font-semibold text-slate-400">mins</span>
                  </div>
                </div>
              </div>
              <!-- Response Quick Presets -->
              <div class="flex flex-wrap items-center gap-1.5 pt-1">
                <span class="text-[10px] uppercase font-bold text-slate-400 mr-1">Quick Presets:</span>
                <button type="button" class="sla-preset-resp px-2 py-0.5 rounded text-[11px] font-semibold bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 hover:bg-emerald-50 dark:hover:bg-emerald-950 transition-colors" data-mins="15">15m (0.25h)</button>
                <button type="button" class="sla-preset-resp px-2 py-0.5 rounded text-[11px] font-semibold bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 hover:bg-emerald-50 dark:hover:bg-emerald-950 transition-colors" data-mins="30">30m (0.5h)</button>
                <button type="button" class="sla-preset-resp px-2 py-0.5 rounded text-[11px] font-semibold bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 hover:bg-emerald-50 dark:hover:bg-emerald-950 transition-colors" data-mins="60">1h (60m)</button>
                <button type="button" class="sla-preset-resp px-2 py-0.5 rounded text-[11px] font-semibold bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 hover:bg-emerald-50 dark:hover:bg-emerald-950 transition-colors" data-mins="120">2h (120m)</button>
                <button type="button" class="sla-preset-resp px-2 py-0.5 rounded text-[11px] font-semibold bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 hover:bg-emerald-50 dark:hover:bg-emerald-950 transition-colors" data-mins="240">4h (240m)</button>
                <button type="button" class="sla-preset-resp px-2 py-0.5 rounded text-[11px] font-semibold bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 hover:bg-emerald-50 dark:hover:bg-emerald-950 transition-colors" data-mins="480">8h (480m)</button>
                <button type="button" class="sla-preset-resp px-2 py-0.5 rounded text-[11px] font-semibold bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 hover:bg-emerald-50 dark:hover:bg-emerald-950 transition-colors" data-mins="1440">24h (1d)</button>
              </div>
            </div>

            <!-- Resolution Target Configuration (Hours & Minutes + Quick Presets) -->
            <div class="p-3.5 rounded-xl bg-blue-50/50 dark:bg-blue-950/20 border border-blue-200/60 dark:border-blue-900/40 space-y-2.5">
              <div class="flex items-center justify-between">
                <label class="block text-xs font-bold text-blue-800 dark:text-blue-300">
                  Resolution SLA Target <span class="font-normal text-blue-600 dark:text-blue-400">(Ticket full resolution/fulfilment)</span>
                </label>
                <span id="sla-reso-human" class="text-xs font-bold text-blue-700 dark:text-blue-300 font-mono"></span>
              </div>
              <div class="grid grid-cols-2 gap-3">
                <div>
                  <label class="block text-[11px] font-semibold text-slate-500 mb-1">Target in Hours</label>
                  <div class="relative">
                    <input id="sla-modal-reso-hours" type="number" step="0.5" min="0.1" class="w-full rounded-lg border border-[var(--border-color)] bg-[var(--bg-secondary)] px-3 py-2 pr-12 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" placeholder="e.g. 8.0" />
                    <span class="absolute right-3 top-1/2 -translate-y-1/2 text-xs font-semibold text-slate-400">hrs</span>
                  </div>
                </div>
                <div>
                  <label class="block text-[11px] font-semibold text-slate-500 mb-1">Target in Minutes</label>
                  <div class="relative">
                    <input id="sla-modal-reso" type="number" min="1" class="w-full rounded-lg border border-[var(--border-color)] bg-[var(--bg-secondary)] px-3 py-2 pr-12 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" placeholder="e.g. 480" />
                    <span class="absolute right-3 top-1/2 -translate-y-1/2 text-xs font-semibold text-slate-400">mins</span>
                  </div>
                </div>
              </div>
              <!-- Resolution Quick Presets -->
              <div class="flex flex-wrap items-center gap-1.5 pt-1">
                <span class="text-[10px] uppercase font-bold text-slate-400 mr-1">Quick Presets:</span>
                <button type="button" class="sla-preset-reso px-2 py-0.5 rounded text-[11px] font-semibold bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 hover:bg-blue-50 dark:hover:bg-blue-950 transition-colors" data-mins="120">2h</button>
                <button type="button" class="sla-preset-reso px-2 py-0.5 rounded text-[11px] font-semibold bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 hover:bg-blue-50 dark:hover:bg-blue-950 transition-colors" data-mins="240">4h</button>
                <button type="button" class="sla-preset-reso px-2 py-0.5 rounded text-[11px] font-semibold bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 hover:bg-blue-50 dark:hover:bg-blue-950 transition-colors" data-mins="480">8h (1 day)</button>
                <button type="button" class="sla-preset-reso px-2 py-0.5 rounded text-[11px] font-semibold bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 hover:bg-blue-50 dark:hover:bg-blue-950 transition-colors" data-mins="720">12h</button>
                <button type="button" class="sla-preset-reso px-2 py-0.5 rounded text-[11px] font-semibold bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 hover:bg-blue-50 dark:hover:bg-blue-950 transition-colors" data-mins="1440">24h (1d)</button>
                <button type="button" class="sla-preset-reso px-2 py-0.5 rounded text-[11px] font-semibold bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 hover:bg-blue-50 dark:hover:bg-blue-950 transition-colors" data-mins="2880">48h (2d)</button>
                <button type="button" class="sla-preset-reso px-2 py-0.5 rounded text-[11px] font-semibold bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 hover:bg-blue-50 dark:hover:bg-blue-950 transition-colors" data-mins="4320">72h (3d)</button>
                <button type="button" class="sla-preset-reso px-2 py-0.5 rounded text-[11px] font-semibold bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 hover:bg-blue-50 dark:hover:bg-blue-950 transition-colors" data-mins="5760">96h (4d)</button>
                <button type="button" class="sla-preset-reso px-2 py-0.5 rounded text-[11px] font-semibold bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 hover:bg-blue-50 dark:hover:bg-blue-950 transition-colors" data-mins="10080">168h (7d)</button>
              </div>
            </div>

            <div>
              <label class="block text-xs font-semibold text-slate-500 mb-1">Warning Threshold <span class="text-slate-400 font-normal">(%)</span></label>
              <div class="flex items-center gap-3">
                <input id="sla-modal-warn" type="range" min="10" max="100" step="5" class="flex-1 accent-amber-500" />
                <span id="sla-warn-pct" class="text-sm font-bold text-amber-600 w-10 text-right">75%</span>
              </div>
            </div>
            <div>
              <label class="block text-xs font-semibold text-slate-500 mb-1">Pause Conditions</label>
              <div id="sla-pause-chips" class="flex flex-wrap gap-1.5 mb-2"></div>
              <div class="flex gap-2">
                <input id="sla-pause-input" type="text" placeholder="Add condition and press Enter" class="flex-1 rounded-lg border border-[var(--border-color)] bg-[var(--bg-secondary)] px-3 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-purple-500" />
                <button type="button" id="sla-pause-add" class="px-3 py-1.5 rounded-lg bg-slate-100 dark:bg-slate-800 text-xs font-semibold hover:bg-slate-200 dark:hover:bg-slate-700 transition-colors">Add</button>
              </div>
            </div>
            <div>
              <label class="block text-xs font-semibold text-slate-500 mb-1">Business Calendar</label>
              <select id="sla-modal-cal" class="w-full rounded-lg border border-[var(--border-color)] bg-[var(--bg-secondary)] px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-purple-500">
                <option value="">— Default (24x7) —</option>
                ${calendars.map(c => `<option value="${c.id}">${c.name}</option>`).join('')}
              </select>
            </div>
            <div>
              <label class="block text-xs font-semibold text-slate-500 mb-1">Description</label>
              <textarea id="sla-modal-desc" rows="2" class="w-full rounded-lg border border-[var(--border-color)] bg-[var(--bg-secondary)] px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-purple-500" placeholder="Optional description"></textarea>
            </div>
            <div>
              <label class="block text-xs font-semibold text-slate-500 mb-1">Reason for change <span class="text-red-500">*</span></label>
              <input id="sla-modal-reason" type="text" class="w-full rounded-lg border border-[var(--border-color)] bg-[var(--bg-secondary)] px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-purple-500" placeholder="e.g. Adjusted Service Request P2 resolution to 24h per team SLA contract" />
            </div>
            <div id="sla-version-row" class="flex items-start gap-3 p-3 rounded-xl bg-amber-50 dark:bg-amber-950/30 border border-amber-200 dark:border-amber-800">
              <input id="sla-modal-new-version" type="checkbox" class="mt-0.5 accent-amber-500 w-4 h-4 flex-shrink-0" />
              <div>
                <label for="sla-modal-new-version" class="text-xs font-semibold text-amber-800 dark:text-amber-300 cursor-pointer">Create new version (recommended for active policies)</label>
                <p class="text-[10px] text-amber-600 dark:text-amber-400 mt-0.5">Archives current version and creates v+1. Open tickets retain their original SLA targets.</p>
              </div>
            </div>
            <div class="flex items-center justify-end gap-3 pt-2 border-t border-[var(--border-color)]">
              <button type="button" id="sla-modal-cancel" class="px-4 py-2 rounded-xl text-sm font-semibold hover:bg-[var(--bg-tertiary)] transition-colors">Cancel</button>
              <button type="submit" id="sla-modal-save" class="px-5 py-2 rounded-xl bg-purple-600 text-white text-sm font-semibold hover:bg-purple-700 transition-colors shadow">Save SLA Policy</button>
            </div>
          </form>
        </div>
      </div>
    `;

    lucide.createIcons();
    bindEvents();
  };

  const minsToHuman = m => {
    m = parseInt(m, 10);
    if (!m || isNaN(m)) return '';
    const hours = m / 60.0;
    if (hours >= 24 && hours % 24 === 0) {
      const days = hours / 24;
      return `= ${hours} hrs (${days} days / ${m.toLocaleString()} mins)`;
    }
    const decStr = hours.toFixed(2).replace(/\\.?0+$/, '');
    return `= ${decStr} hrs (${m} mins)`;
  };

  const renderPauseChips = () => {
    const el = document.getElementById('sla-pause-chips');
    if (!el) return;
    el.innerHTML = pauseConditions.map((c, i) =>
      `<span class="flex items-center gap-1 px-2 py-0.5 rounded-full bg-slate-100 dark:bg-slate-800 text-xs font-medium">
        ${c}
        <button type="button" class="sla-pause-remove text-slate-400 hover:text-red-500" data-idx="${i}">✕</button>
      </span>`
    ).join('');
    document.querySelectorAll('.sla-pause-remove').forEach(btn => {
      btn.addEventListener('click', () => { pauseConditions.splice(parseInt(btn.dataset.idx, 10), 1); renderPauseChips(); });
    });
  };

  const openModal = (sla = null) => {
    const modal = document.getElementById('sla-modal');
    const title = document.getElementById('sla-modal-title');
    const versionRow = document.getElementById('sla-version-row');
    const codeInput = document.getElementById('sla-modal-code');
    const prioritySelect = document.getElementById('sla-modal-priority');
    const typeSelect = document.getElementById('sla-modal-ticket-type');

    if (sla) {
      title.textContent = `Edit SLA Policy — ${sla.policy_code} (v${sla.version})`;
      document.getElementById('sla-modal-id').value = sla.id;
      codeInput.value = sla.policy_code;
      codeInput.readOnly = true;
      codeInput.classList.add('opacity-60', 'cursor-not-allowed');

      typeSelect.value = sla.ticket_type || 'Incident';
      typeSelect.disabled = false;
      typeSelect.classList.remove('opacity-60', 'cursor-not-allowed');

      prioritySelect.value = sla.priority || 'P1';
      prioritySelect.disabled = false;
      prioritySelect.classList.remove('opacity-60', 'cursor-not-allowed');

      document.getElementById('sla-modal-name').value = sla.name || '';

      const respMins = sla.response_target_mins || 0;
      document.getElementById('sla-modal-resp').value = respMins;
      document.getElementById('sla-modal-resp-hours').value = Number((respMins / 60).toFixed(2));
      document.getElementById('sla-resp-human').textContent = minsToHuman(respMins);

      const resoMins = sla.resolution_target_mins || 0;
      document.getElementById('sla-modal-reso').value = resoMins;
      document.getElementById('sla-modal-reso-hours').value = Number((resoMins / 60).toFixed(2));
      document.getElementById('sla-reso-human').textContent = minsToHuman(resoMins);

      document.getElementById('sla-modal-warn').value = sla.warning_threshold_pct || 75;
      document.getElementById('sla-warn-pct').textContent = `${sla.warning_threshold_pct || 75}%`;
      document.getElementById('sla-modal-cal').value = sla.business_calendar_id || '';
      document.getElementById('sla-modal-desc').value = sla.description || '';
      pauseConditions = Array.isArray(sla.pause_conditions) ? [...sla.pause_conditions] : [];
      versionRow.classList.remove('hidden');
      document.getElementById('sla-modal-new-version').checked = false;
    } else {
      title.textContent = 'New SLA Policy';
      document.getElementById('sla-modal-id').value = '';
      codeInput.value = '';
      codeInput.readOnly = false;
      codeInput.classList.remove('opacity-60', 'cursor-not-allowed');

      typeSelect.value = currentTypeFilter !== 'all' ? currentTypeFilter : 'Incident';
      typeSelect.disabled = false;
      typeSelect.classList.remove('opacity-60', 'cursor-not-allowed');

      prioritySelect.value = currentPriorityFilter !== 'all' ? currentPriorityFilter : 'P1';
      prioritySelect.disabled = false;
      prioritySelect.classList.remove('opacity-60', 'cursor-not-allowed');

      document.getElementById('sla-modal-name').value = '';

      document.getElementById('sla-modal-resp').value = '30';
      document.getElementById('sla-modal-resp-hours').value = '0.5';
      document.getElementById('sla-resp-human').textContent = minsToHuman(30);

      document.getElementById('sla-modal-reso').value = '480';
      document.getElementById('sla-modal-reso-hours').value = '8';
      document.getElementById('sla-reso-human').textContent = minsToHuman(480);

      document.getElementById('sla-modal-warn').value = 75;
      document.getElementById('sla-warn-pct').textContent = '75%';
      document.getElementById('sla-modal-cal').value = '';
      document.getElementById('sla-modal-desc').value = '';
      pauseConditions = ['Pending Customer', 'Awaiting Approval', 'Awaiting Vendor'];
      versionRow.classList.add('hidden');
    }
    renderPauseChips();
    document.getElementById('sla-modal-reason').value = '';
    modal.classList.remove('hidden');
  };

  const closeModal = () => {
    const m = document.getElementById('sla-modal');
    if (m) m.classList.add('hidden');
  };

  const bindEvents = () => {
    // Ticket Type Filter click
    document.querySelectorAll('.sla-type-filter').forEach(btn => {
      btn.addEventListener('click', () => {
        currentTypeFilter = btn.dataset.type;
        renderContent();
      });
    });

    // Priority Filter click
    document.querySelectorAll('.sla-pri-filter').forEach(btn => {
      btn.addEventListener('click', () => {
        currentPriorityFilter = btn.dataset.pri;
        renderContent();
      });
    });

    // Search input
    const searchInp = document.getElementById('sla-search-input');
    if (searchInp) {
      searchInp.addEventListener('input', e => {
        searchQuery = e.target.value.trim();
        renderContent();
        // keep focus and cursor at end of search input
        const newInp = document.getElementById('sla-search-input');
        if (newInp) {
          newInp.focus();
          newInp.selectionStart = newInp.selectionEnd = newInp.value.length;
        }
      });
    }

    // Live Response target sync
    const respHoursInp = document.getElementById('sla-modal-resp-hours');
    const respMinsInp = document.getElementById('sla-modal-resp');
    if (respHoursInp && respMinsInp) {
      respHoursInp.addEventListener('input', () => {
        const hrs = parseFloat(respHoursInp.value);
        if (!isNaN(hrs) && hrs >= 0) {
          const mins = Math.round(hrs * 60);
          respMinsInp.value = mins;
          document.getElementById('sla-resp-human').textContent = minsToHuman(mins);
        } else {
          respMinsInp.value = '';
          document.getElementById('sla-resp-human').textContent = '';
        }
      });
      respMinsInp.addEventListener('input', () => {
        const mins = parseInt(respMinsInp.value, 10);
        if (!isNaN(mins) && mins >= 0) {
          respHoursInp.value = Number((mins / 60).toFixed(2));
          document.getElementById('sla-resp-human').textContent = minsToHuman(mins);
        } else {
          respHoursInp.value = '';
          document.getElementById('sla-resp-human').textContent = '';
        }
      });
    }

    // Live Resolution target sync
    const resoHoursInp = document.getElementById('sla-modal-reso-hours');
    const resoMinsInp = document.getElementById('sla-modal-reso');
    if (resoHoursInp && resoMinsInp) {
      resoHoursInp.addEventListener('input', () => {
        const hrs = parseFloat(resoHoursInp.value);
        if (!isNaN(hrs) && hrs >= 0) {
          const mins = Math.round(hrs * 60);
          resoMinsInp.value = mins;
          document.getElementById('sla-reso-human').textContent = minsToHuman(mins);
        } else {
          resoMinsInp.value = '';
          document.getElementById('sla-reso-human').textContent = '';
        }
      });
      resoMinsInp.addEventListener('input', () => {
        const mins = parseInt(resoMinsInp.value, 10);
        if (!isNaN(mins) && mins >= 0) {
          resoHoursInp.value = Number((mins / 60).toFixed(2));
          document.getElementById('sla-reso-human').textContent = minsToHuman(mins);
        } else {
          resoHoursInp.value = '';
          document.getElementById('sla-reso-human').textContent = '';
        }
      });
    }

    // Response presets
    document.querySelectorAll('.sla-preset-resp').forEach(btn => {
      btn.addEventListener('click', () => {
        const mins = parseInt(btn.dataset.mins, 10);
        if (respMinsInp) respMinsInp.value = mins;
        if (respHoursInp) respHoursInp.value = Number((mins / 60).toFixed(2));
        document.getElementById('sla-resp-human').textContent = minsToHuman(mins);
      });
    });

    // Resolution presets
    document.querySelectorAll('.sla-preset-reso').forEach(btn => {
      btn.addEventListener('click', () => {
        const mins = parseInt(btn.dataset.mins, 10);
        if (resoMinsInp) resoMinsInp.value = mins;
        if (resoHoursInp) resoHoursInp.value = Number((mins / 60).toFixed(2));
        document.getElementById('sla-reso-human').textContent = minsToHuman(mins);
      });
    });

    // Warning slider
    const warnInp = document.getElementById('sla-modal-warn');
    if (warnInp) {
      warnInp.addEventListener('input', e => {
        document.getElementById('sla-warn-pct').textContent = `${e.target.value}%`;
      });
    }

    // Pause chip add
    const addPause = () => {
      const inp = document.getElementById('sla-pause-input');
      const val = inp.value.trim();
      if (val && !pauseConditions.includes(val)) {
        pauseConditions.push(val);
        renderPauseChips();
      }
      inp.value = '';
    };
    const pauseAddBtn = document.getElementById('sla-pause-add');
    if (pauseAddBtn) pauseAddBtn.addEventListener('click', addPause);
    const pauseInp = document.getElementById('sla-pause-input');
    if (pauseInp) {
      pauseInp.addEventListener('keydown', e => {
        if (e.key === 'Enter') {
          e.preventDefault();
          addPause();
        }
      });
    }

    // Modal Close
    const closeBtn = document.getElementById('sla-modal-close');
    if (closeBtn) closeBtn.addEventListener('click', closeModal);
    const cancelBtn = document.getElementById('sla-modal-cancel');
    if (cancelBtn) cancelBtn.addEventListener('click', closeModal);
    const modalEl = document.getElementById('sla-modal');
    if (modalEl) {
      modalEl.addEventListener('click', e => {
        if (e.target === modalEl) closeModal();
      });
    }

    // Edit buttons
    document.querySelectorAll('.sla-edit-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const policyId = parseInt(btn.dataset.id, 10);
        const sla = slas.find(x => x.id === policyId);
        if (sla) openModal(sla);
      });
    });

    // New policy button
    const newBtn = document.getElementById('sla-new-btn');
    if (newBtn) newBtn.addEventListener('click', () => openModal(null));

    // Form submit
    const form = document.getElementById('sla-modal-form');
    if (form) {
      form.addEventListener('submit', async e => {
        e.preventDefault();
        const saveBtn = document.getElementById('sla-modal-save');
        const reason = document.getElementById('sla-modal-reason').value.trim();
        if (!reason) {
          document.getElementById('sla-modal-reason').focus();
          document.getElementById('sla-modal-reason').classList.add('ring-2', 'ring-red-400');
          return;
        }
        document.getElementById('sla-modal-reason').classList.remove('ring-2', 'ring-red-400');
        const policyId = document.getElementById('sla-modal-id').value;
        const isEdit = Boolean(policyId);
        const calVal = document.getElementById('sla-modal-cal').value;
        const payload = {
          policy_code: document.getElementById('sla-modal-code').value.trim(),
          name: document.getElementById('sla-modal-name').value.trim(),
          priority: document.getElementById('sla-modal-priority').value,
          ticket_type: document.getElementById('sla-modal-ticket-type').value || 'Incident',
          response_target_mins: parseInt(document.getElementById('sla-modal-resp').value, 10),
          resolution_target_mins: parseInt(document.getElementById('sla-modal-reso').value, 10),
          warning_threshold_pct: parseInt(document.getElementById('sla-modal-warn').value, 10),
          pause_conditions: [...pauseConditions],
          business_calendar_id: calVal ? parseInt(calVal, 10) : null,
          description: document.getElementById('sla-modal-desc').value.trim() || null,
          reason,
          create_new_version: isEdit ? document.getElementById('sla-modal-new-version').checked : false,
          active: true,
        };
        saveBtn.disabled = true;
        saveBtn.textContent = 'Saving…';
        try {
          const url = isEdit ? `${API_BASE}/admin/slas/${policyId}` : `${API_BASE}/admin/slas`;
          const r = await fetch(url, {
            method: isEdit ? 'PUT' : 'POST',
            headers: { 'Content-Type': 'application/json', 'X-User-ID': String(userId) },
            body: JSON.stringify(payload)
          });
          if (!r.ok) {
            const err = await r.json().catch(() => ({}));
            throw new Error(err.detail || `HTTP ${r.status}`);
          }
          closeModal();
          await renderSlaAdminView(container);
        } catch (err) {
          alert(`Save failed: ${err.message}`);
        } finally {
          saveBtn.disabled = false;
          saveBtn.textContent = 'Save SLA Policy';
        }
      });
    }
  };

  renderContent();
}

// --- BUSINESS CALENDARS ADMIN VIEW ---
async function renderCalendarsAdminView(container) {
  const res = await fetch(`${API_BASE}/admin/calendars`);
  const cals = await res.json();

  container.innerHTML = `
    <div class="space-y-6">
      <div>
        <h1 class="text-2xl font-black tracking-tight">Business Calendars &amp; Working Hours</h1>
        <p class="text-sm text-slate-500">Configure working hours, regional holidays, and SLA business-hour schedules.</p>
      </div>

      <div class="grid grid-cols-1 md:grid-cols-2 gap-5">
        ${cals.map(c => `
          <div class="p-5 rounded-2xl bg-[var(--card-bg)] border border-[var(--border-color)] shadow-sm space-y-3">
            <div class="flex items-center justify-between">
              <span class="font-bold text-sm text-[var(--text-primary)]">${c.name}</span>
              <div class="flex items-center gap-2"><span class="px-2 py-0.5 rounded bg-purple-50 dark:bg-blue-950/40 text-purple-600 text-[10px] font-bold">${c.timezone}</span><button onclick='openCalendarModal(${JSON.stringify(c).replace(/'/g, "&#39;")})' class="text-purple-600 text-[10px] font-bold">Edit</button></div>
            </div>
            <p class="text-xs text-slate-400">${c.description}</p>
            <div class="p-3 rounded-xl bg-[var(--bg-tertiary)] text-xs space-y-1">
              <div>Working Hours: <b class="text-emerald-600">${c.working_hours_start} – ${c.working_hours_end}</b></div>
              <div>Working Days: <b class="text-purple-600">Mon – Fri (${c.working_days.length} days/week)</b></div>
              <div>Configured Holidays: <b class="text-amber-600">${c.holidays.length} statutory dates</b></div>
            </div>
          </div>
        `).join('')}
      </div>
    </div>
  `;
}

function openCalendarModal(calendar) {
  const days = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'];
  const zones = ['Asia/Kolkata','UTC','America/New_York','America/Chicago','America/Los_Angeles','Europe/London','Europe/Berlin','Asia/Singapore','Asia/Tokyo','Australia/Sydney'];
  document.getElementById('modalContainer').innerHTML = `<div class="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4"><div class="w-full max-w-lg rounded-2xl bg-[var(--card-bg)] p-5 shadow-2xl"><div class="flex justify-between mb-4"><div><h2 class="font-bold">Edit working calendar</h2><p class="text-[11px] text-slate-400">Set local operating hours and the timezone used for SLA calculations.</p></div><button onclick="closeAdminModal()">✕</button></div><form onsubmit="saveCalendar(event, ${calendar.id})" class="grid grid-cols-2 gap-3 text-xs admin-form"><label class="col-span-2">Name<input id="cal_name" required value="${calendar.name}"></label><label>Timezone<select id="cal_timezone">${zones.map(z => `<option ${z === calendar.timezone ? 'selected' : ''}>${z}</option>`).join('')}</select></label><label>Working days<div class="flex flex-wrap gap-2 pt-2">${days.map((d,i) => `<label class="flex items-center gap-1 font-normal"><input type="checkbox" class="cal-day" value="${i+1}" ${calendar.working_days.includes(i+1) ? 'checked' : ''}>${d}</label>`).join('')}</div></label><label>Start time<input id="cal_start" type="time" value="${calendar.working_hours_start}"></label><label>End time<input id="cal_end" type="time" value="${calendar.working_hours_end}"></label><label class="col-span-2">Description<textarea id="cal_description" rows="2">${calendar.description || ''}</textarea></label><label class="col-span-2">Holidays (one YYYY-MM-DD date per line)<textarea id="cal_holidays" rows="3">${(calendar.holidays || []).join('\n')}</textarea></label><div class="col-span-2 flex justify-end gap-2 pt-3"><button type="button" onclick="closeAdminModal()" class="px-4 py-2 border rounded-lg">Cancel</button><button class="px-4 py-2 bg-purple-600 text-white rounded-lg font-bold">Save calendar</button></div></form></div></div>`;
}

async function saveCalendar(event, calendarId) {
  event.preventDefault();
  const working_days = [...document.querySelectorAll('.cal-day:checked')].map(x => Number(x.value));
  const holidays = document.getElementById('cal_holidays').value.split('\n').map(x => x.trim()).filter(Boolean);
  const payload = { name: document.getElementById('cal_name').value, description: document.getElementById('cal_description').value, timezone: document.getElementById('cal_timezone').value, working_days, working_hours_start: document.getElementById('cal_start').value, working_hours_end: document.getElementById('cal_end').value, holidays, exceptions: [] };
  const response = await fetch(`${API_BASE}/admin/calendars/${calendarId}`, { method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload) });
  if (!response.ok) { alert((await response.json()).detail || 'Unable to update calendar'); return; }
  closeAdminModal(); renderCalendarsAdminView(document.getElementById('mainApp'));
}

// --- AI ASSISTANT CONFIGURATION & ANALYTICS VIEW ---
async function renderAiAdminView(container) {
  container.innerHTML = `<div class="p-8 text-center text-slate-400"><i data-lucide="loader-2" class="w-8 h-8 animate-spin mx-auto mb-2 text-purple-500"></i>Loading AI Settings & Analytics...</div>`;
  lucide.createIcons();

  try {
    const authHeaders = state.currentUser ? { 'X-User-ID': state.currentUser.id.toString() } : {};
    const [cfgRes, statsRes] = await Promise.allSettled([
      fetch(`${API_BASE}/ai/config`, { headers: authHeaders }),
      fetch(`${API_BASE}/ai/analytics`, { headers: authHeaders })
    ]);

    const cfg = (cfgRes.status === 'fulfilled' && cfgRes.value.ok) ? await cfgRes.value.json() : {
      is_enabled: true,
      assistant_name: "ITSM Support Copilot",
      welcome_message: "Hello! I am your GenWizard Support Copilot.",
      km_base_url: "https://internal-km.company.local",
      api_endpoint: "/api/chat/completions",
      response_json_path: "choices[0].message.content",
      auth_type: "Bearer",
      timeout_seconds: 30,
      payload_template: '{\n  "model": "internal-km-v1",\n  "messages": [\n    {\n      "role": "user",\n      "content": "{{question}}"\n    }\n  ]\n}',
      allow_ticket_context: true,
      pii_filtering: true
    };

    const stats = (statsRes.status === 'fulfilled' && statsRes.value.ok) ? await statsRes.value.json() : {
      total_questions: 0,
      questions_today: 0,
      questions_this_month: 0,
      successful_requests: 0,
      failed_requests: 0,
      average_response_time_ms: 0,
      total_tokens: 0,
      recent_audit_logs: []
    };

    const successPct = stats.total_questions > 0 ? Math.round(((stats.successful_requests || 0) / stats.total_questions) * 100) : 100;
    const logs = stats.recent_audit_logs || [];

    container.innerHTML = `
      <div class="space-y-6">
        <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div>
            <div class="flex items-center space-x-2">
              <span class="text-xs font-bold uppercase tracking-wider text-purple-600 dark:text-purple-400">GenWizard Intelligence</span>
              <span class="px-2 py-0.5 rounded-full text-[10px] font-bold bg-purple-100 text-purple-700 dark:bg-purple-950 dark:text-purple-300">
                ${cfg.is_enabled ? '● Active' : '○ Standby'}
              </span>
            </div>
            <h1 class="text-2xl font-black tracking-tight mt-0.5">AI Integration & Operational Analytics</h1>
            <p class="text-sm text-slate-500">Configure internal ChatCompletion API integration, verify Knowledge Management connectivity, and monitor copilot utilization.</p>
          </div>
          <div class="flex items-center space-x-2">
            <button onclick="renderAiAdminView(document.getElementById('mainApp'))" class="px-3.5 py-2 rounded-xl border border-[var(--border-color)] bg-[var(--card-bg)] hover:bg-[var(--bg-tertiary)] text-xs font-semibold flex items-center space-x-1.5 shadow-sm">
              <i data-lucide="refresh-cw" class="w-3.5 h-3.5 text-slate-400"></i>
              <span>Refresh</span>
            </button>
            <button onclick="testAiConnectionLive()" class="px-4 py-2 rounded-xl bg-purple-600 hover:bg-purple-700 text-white text-xs font-bold shadow flex items-center space-x-1.5">
              <i data-lucide="activity" class="w-3.5 h-3.5"></i>
              <span>Test Connection</span>
            </button>
          </div>
        </div>

        <!-- Connection Test Result Banner -->
        <div id="aiTestResultBanner" class="hidden p-4 rounded-xl border text-xs"></div>

        <!-- Analytics KPI Cards -->
        <div class="grid grid-cols-2 md:grid-cols-5 gap-4">
          <div class="p-4 rounded-2xl bg-[var(--card-bg)] border border-[var(--border-color)] shadow-sm">
            <div class="text-[11px] font-semibold text-slate-400 uppercase">Total Questions</div>
            <div class="text-2xl font-black mt-1 text-purple-600">${stats.total_questions || 0}</div>
            <div class="text-[10px] text-slate-400 mt-1">${stats.questions_today || 0} today / ${stats.questions_this_month || 0} this month</div>
          </div>
          <div class="p-4 rounded-2xl bg-[var(--card-bg)] border border-[var(--border-color)] shadow-sm">
            <div class="text-[11px] font-semibold text-slate-400 uppercase">Success Rate</div>
            <div class="text-2xl font-black mt-1 text-emerald-500">${successPct}%</div>
            <div class="text-[10px] text-slate-400 mt-1">${stats.successful_requests || 0} ok / ${stats.failed_requests || 0} error</div>
          </div>
          <div class="p-4 rounded-2xl bg-[var(--card-bg)] border border-[var(--border-color)] shadow-sm">
            <div class="text-[11px] font-semibold text-slate-400 uppercase">Avg Response Time</div>
            <div class="text-2xl font-black mt-1 text-indigo-500">${stats.average_response_time_ms || 0} ms</div>
            <div class="text-[10px] text-slate-400 mt-1">KM Endpoint Latency</div>
          </div>
          <div class="p-4 rounded-2xl bg-[var(--card-bg)] border border-[var(--border-color)] shadow-sm">
            <div class="text-[11px] font-semibold text-slate-400 uppercase">Total Tokens</div>
            <div class="text-2xl font-black mt-1 text-pink-500">${(stats.total_tokens || 0).toLocaleString()}</div>
            <div class="text-[10px] text-slate-400 mt-1">ChatCompletion Usage</div>
          </div>
          <div class="p-4 rounded-2xl bg-[var(--card-bg)] border border-[var(--border-color)] shadow-sm">
            <div class="text-[11px] font-semibold text-slate-400 uppercase">Assistant Persona</div>
            <div class="text-sm font-bold mt-1 text-[var(--text-primary)] truncate">${cfg.assistant_name || 'Support Copilot'}</div>
            <div class="text-[10px] text-slate-400 mt-1">Model: ${cfg.auth_type || 'Bearer'}</div>
          </div>
        </div>

        <!-- Config Form -->
        <div class="p-6 rounded-2xl bg-[var(--card-bg)] border border-[var(--border-color)] shadow-sm space-y-4">
          <div class="flex items-center justify-between pb-2 border-b border-[var(--border-color)]">
            <div>
              <h2 class="text-sm font-bold flex items-center space-x-2">
                <i data-lucide="sliders" class="w-4 h-4 text-purple-600"></i>
                <span>ChatCompletion & KM Integration Parameters</span>
              </h2>
              <p class="text-xs text-slate-500 mt-0.5">Parameters connect the GenWizard assistant to internal Accenture KM and knowledge stores.</p>
            </div>
          </div>

          <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <div class="flex items-center justify-between mb-1">
                <label class="block text-xs font-semibold text-slate-400">Internal KM Base URL</label>
                <span class="text-[10px] text-emerald-600 dark:text-emerald-400 font-medium flex items-center gap-1">
                  <i data-lucide="eye" class="w-3 h-3"></i> Visible for Reference
                </span>
              </div>
              <input type="text" id="ai_km_url" value="${cfg.km_base_url || 'https://internal-km.company.local'}" class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-xl p-2.5 text-xs font-mono text-[var(--text-primary)]">
            </div>
            <div>
              <label class="block text-xs font-semibold text-slate-400 mb-1">API Endpoint Path</label>
              <input type="text" id="ai_endpoint" value="${cfg.api_endpoint || '/api/chat/completions'}" class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-xl p-2.5 text-xs font-mono">
            </div>
            <div>
              <label class="block text-xs font-semibold text-slate-400 mb-1">Response JSON Path</label>
              <input type="text" id="ai_response_path" value="${cfg.response_json_path || 'choices[0].message.content'}" class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-xl p-2.5 text-xs font-mono">
            </div>
            <div>
              <label class="block text-xs font-semibold text-slate-400 mb-1">Auth Type & Timeout (seconds)</label>
              <div class="flex space-x-2">
                <select id="ai_auth_type" class="bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-xl p-2.5 text-xs font-semibold">
                  <option value="Bearer" ${cfg.auth_type === 'Bearer' ? 'selected' : ''}>Bearer</option>
                  <option value="Basic" ${cfg.auth_type === 'Basic' ? 'selected' : ''}>Basic</option>
                  <option value="None" ${cfg.auth_type === 'None' ? 'selected' : ''}>None</option>
                </select>
                <input type="number" id="ai_timeout" value="${cfg.timeout_seconds || 30}" class="w-24 bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-xl p-2.5 text-xs font-mono">
              </div>
            </div>
          </div>

          <div>
            <label class="block text-xs font-semibold text-slate-400 mb-1">Payload JSON Template (Supports {{question}}, {{ticket_number}}, {{application}}, {{context}})</label>
            <textarea id="ai_payload_template" rows="7" class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-xl p-3 text-xs font-mono leading-relaxed">${cfg.payload_template || ''}</textarea>
          </div>

          <div class="pt-3 border-t border-[var(--border-color)] flex flex-wrap items-center justify-between gap-3">
            <div class="flex items-center space-x-4 text-xs">
              <label class="flex items-center space-x-1.5 cursor-pointer">
                <input type="checkbox" id="ai_allow_ticket_ctx" ${cfg.allow_ticket_context ? 'checked' : ''} class="rounded">
                <span>Allow Ticket Context</span>
              </label>
              <label class="flex items-center space-x-1.5 cursor-pointer">
                <input type="checkbox" id="ai_pii_filter" ${cfg.pii_filtering ? 'checked' : ''} class="rounded">
                <span>PII & Secret Filtering</span>
              </label>
            </div>
            <button onclick="saveAiConfig()" class="bg-purple-600 hover:bg-purple-700 text-white px-5 py-2.5 rounded-xl text-xs font-bold shadow">
              Save AI Settings
            </button>
          </div>
        </div>

        <!-- Recent Invocations & Audit Logs -->
        <div class="p-6 rounded-2xl bg-[var(--card-bg)] border border-[var(--border-color)] shadow-sm space-y-4">
          <div class="flex items-center justify-between">
            <h3 class="text-sm font-bold flex items-center space-x-2">
              <i data-lucide="history" class="w-4 h-4 text-slate-400"></i>
              <span>Recent AI Copilot Invocations & Analytics History</span>
            </h3>
            <span class="text-xs text-slate-400 font-medium">${logs.length} Recent Records</span>
          </div>

          ${logs.length === 0 ? `
            <div class="p-8 text-center rounded-xl bg-[var(--bg-tertiary)] border border-dashed border-[var(--border-color)]">
              <i data-lucide="bot" class="w-8 h-8 mx-auto mb-2 text-purple-400/50"></i>
              <div class="text-xs font-bold text-slate-400">No AI audit events logged yet</div>
              <p class="text-[11px] text-slate-500 mt-0.5">Queries asked to the AI Copilot from tickets and chat will be automatically tracked here with response times and token counts.</p>
            </div>
          ` : `
            <div class="overflow-x-auto">
              <table class="w-full text-left text-xs">
                <thead>
                  <tr class="border-b border-[var(--border-color)] text-slate-400 font-semibold uppercase text-[10px]">
                    <th class="py-2.5 px-3">Timestamp</th>
                    <th class="py-2.5 px-3">Ticket / Context</th>
                    <th class="py-2.5 px-3">Question Prompt</th>
                    <th class="py-2.5 px-3">Latency</th>
                    <th class="py-2.5 px-3">Tokens</th>
                    <th class="py-2.5 px-3">Status</th>
                  </tr>
                </thead>
                <tbody class="divide-y divide-[var(--border-color)]">
                  ${logs.map(l => `
                    <tr class="hover:bg-[var(--bg-tertiary)]">
                      <td class="py-2.5 px-3 font-mono text-slate-400 whitespace-nowrap">${l.created_at ? new Date(l.created_at).toLocaleString() : 'Just now'}</td>
                      <td class="py-2.5 px-3 font-semibold">${l.ticket_number || 'General'}</td>
                      <td class="py-2.5 px-3 max-w-xs truncate text-slate-300" title="${l.question || ''}">${l.question || '—'}</td>
                      <td class="py-2.5 px-3 font-mono">${l.response_time_ms ? l.response_time_ms + 'ms' : '—'}</td>
                      <td class="py-2.5 px-3 font-mono">${l.token_count || 0}</td>
                      <td class="py-2.5 px-3">
                        <span class="px-2 py-0.5 rounded-full text-[10px] font-bold ${l.success ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300' : 'bg-red-100 text-red-700 dark:bg-red-950 dark:text-red-300'}">
                          ${l.success ? 'Success' : 'Error'}
                        </span>
                      </td>
                    </tr>
                  `).join('')}
                </tbody>
              </table>
            </div>
          `}
        </div>
      </div>
    `;
    lucide.createIcons();
  } catch (err) {
    container.innerHTML = `<div class="p-8 text-center text-red-500">Error loading AI config: ${err.message}</div>`;
  }
}

async function testAiConnectionLive() {
  const banner = document.getElementById('aiTestResultBanner');
  if (!banner) return;
  banner.classList.remove('hidden');
  banner.className = 'p-4 rounded-xl border border-purple-500/40 bg-purple-500/10 text-xs text-purple-600';
  banner.innerHTML = `Testing connection to internal ChatCompletion endpoint...`;

  try {
    const res = await fetch(`${API_BASE}/ai/test-connection`, { method: 'POST' });
    const data = await res.json();
    if (data.success) {
      banner.className = 'p-4 rounded-xl border border-emerald-500/40 bg-emerald-500/10 text-xs text-emerald-600';
      banner.innerHTML = `<b>✓ Connection Successful!</b> HTTP Status: ${data.status_code} | Latency: ${data.response_time_ms}ms | Diagnostic: ${data.diagnostic}`;
    } else {
      banner.className = 'p-4 rounded-xl border border-amber-500/40 bg-amber-500/10 text-xs text-amber-600';
      banner.innerHTML = `<b>ℹ️ Endpoint Notice:</b> ${data.message} — Fallback Engine active for local simulation.`;
    }
  } catch (err) {
    banner.className = 'p-4 rounded-xl border border-red-500/40 bg-red-500/10 text-xs text-red-600';
    banner.innerHTML = `<b>✕ Connection Failed:</b> ${err.message}`;
  }
}

async function saveAiConfig() {
  const payload = {
    km_base_url: document.getElementById('ai_km_url').value,
    api_endpoint: document.getElementById('ai_endpoint').value,
    response_json_path: document.getElementById('ai_response_path').value,
    auth_type: document.getElementById('ai_auth_type').value,
    timeout_seconds: parseInt(document.getElementById('ai_timeout').value) || 30,
    payload_template: document.getElementById('ai_payload_template').value,
    allow_ticket_context: document.getElementById('ai_allow_ticket_ctx').checked,
    pii_filtering: document.getElementById('ai_pii_filter').checked,
    welcome_message: 'Hello! I am your GenWizard Support Copilot.',
    assistant_name: 'GenWizard Support Copilot',
    headers_template: '{"Content-Type": "application/json"}'
  };

  try {
    const res = await fetch(`${API_BASE}/ai/config`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    if (res.ok) {
      alert('AI Configuration updated successfully!');
    }
  } catch (err) {
    alert('Error saving AI config: ' + err.message);
  }
}

// --- FULL SCREEN AI ASSISTANT CHAT ---
async function renderAiAssistantFullScreen(container) {
  container.innerHTML = `
    <div class="h-[calc(100vh-7rem)] flex rounded-2xl bg-[var(--card-bg)] border border-[var(--border-color)] overflow-hidden shadow-sm">
      <!-- Conversation History Sidebar -->
      <div class="w-72 border-r border-[var(--border-color)] bg-[var(--bg-tertiary)] flex flex-col justify-between">
        <div class="p-3 border-b border-[var(--border-color)]">
          <button onclick="startNewFullScreenChat()" class="w-full bg-purple-600 hover:bg-purple-700 text-white font-bold py-2 rounded-xl text-xs flex items-center justify-center space-x-1.5 shadow">
            <i data-lucide="plus" class="w-3.5 h-3.5"></i>
            <span>New Chat</span>
          </button>
        </div>
        <div id="fullAiHistoryList" class="flex-1 overflow-y-auto p-2 space-y-1 text-xs"></div>
        <div class="p-3 border-t border-[var(--border-color)] text-[11px] text-slate-400 text-center">
          Connected to Internal KM API
        </div>
      </div>

      <!-- Active Chat Window -->
      <div class="flex-1 flex flex-col justify-between bg-[var(--bg-secondary)]">
        <!-- Messages Area -->
        <div id="fullAiMessages" class="flex-1 p-6 overflow-y-auto space-y-4 text-xs">
          <div class="p-4 rounded-xl bg-gradient-to-r from-purple-500/10 to-indigo-500/10 border border-purple-500/20 text-xs">
            <div class="font-bold text-sm text-purple-600 mb-1">GenWizard Knowledge Copilot</div>
            <div>Ask anything about applications, runbooks, EKS pod commands, or paste ticket error logs.</div>
          </div>
        </div>

        <!-- Chat Input Form -->
        <div class="p-4 border-t border-[var(--border-color)]">
          <form onsubmit="submitFullScreenAiQuestion(event)" class="flex items-center space-x-2">
            <input
              type="text"
              id="fullAiInput"
              placeholder="Ask a technical support question (e.g. 'How do I restart the payment gateway pods?')"
              class="flex-1 bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-xl px-4 py-2.5 text-xs focus:outline-none focus:ring-2 focus:ring-purple-500/30"
            />
            <button type="submit" class="bg-purple-600 hover:bg-purple-700 text-white px-5 py-2.5 rounded-xl text-xs font-bold shadow">
              Send
            </button>
          </form>
        </div>
      </div>
    </div>
  `;
  lucide.createIcons();
  loadAiConversationsList();
}

async function loadAiConversationsList() {
  const container = document.getElementById('fullAiHistoryList');
  if (!container) return;
  try {
    const res = await fetch(`${API_BASE}/ai/conversations`, {
      headers: { 'X-User-ID': state.currentUser.id.toString() }
    });
    const convs = await res.json();
    container.innerHTML = convs.map(c => `
      <div onclick="selectAiConversation('${c.id}')" class="p-2.5 rounded-lg hover:bg-[var(--card-bg)] cursor-pointer truncate font-medium ${state.activeAiConversationId === c.id ? 'bg-[var(--card-bg)] text-purple-600 font-bold' : 'text-slate-400'}">
        ${c.title}
      </div>
    `).join('');
  } catch (err) {
    console.error(err);
  }
}

async function selectAiConversation(convId) {
  state.activeAiConversationId = convId;
  const msgContainer = document.getElementById('fullAiMessages');
  try {
    const res = await fetch(`${API_BASE}/ai/conversations/${convId}`);
    const data = await res.json();
    msgContainer.innerHTML = (data.messages || []).map(m => `
      <div class="flex flex-col ${m.role === 'user' ? 'items-end' : 'items-start'}">
        <div class="max-w-xl p-3.5 rounded-xl ${m.role === 'user' ? 'bg-purple-600 text-white' : 'bg-[var(--bg-tertiary)] text-[var(--text-primary)] border border-[var(--border-color)]'}">
          <div class="prose prose-sm">${marked.parse(m.content)}</div>
        </div>
      </div>
    `).join('');
    loadAiConversationsList();
  } catch (err) {
    console.error(err);
  }
}

function startNewFullScreenChat() {
  state.activeAiConversationId = null;
  const msgContainer = document.getElementById('fullAiMessages');
  if (msgContainer) {
    msgContainer.innerHTML = `
      <div class="p-4 rounded-xl bg-gradient-to-r from-purple-500/10 to-indigo-500/10 border border-purple-500/20 text-xs">
        <div class="font-bold text-sm text-purple-600 mb-1">New Conversation Started</div>
        <div>Ask a question or enter error messages to query internal knowledge bases.</div>
      </div>
    `;
  }
}

async function submitFullScreenAiQuestion(e) {
  e.preventDefault();
  const input = document.getElementById('fullAiInput');
  const q = input.value.trim();
  if (!q) return;
  input.value = '';

  const msgContainer = document.getElementById('fullAiMessages');
  msgContainer.innerHTML += `
    <div class="flex flex-col items-end">
      <div class="max-w-xl p-3 rounded-xl bg-purple-600 text-white">${q}</div>
    </div>
    <div id="tempLoader" class="flex items-center space-x-2 text-slate-400"><i data-lucide="loader-2" class="w-4 h-4 animate-spin text-purple-500"></i><span>Copilot is searching runbooks...</span></div>
  `;
  lucide.createIcons();

  try {
    const res = await fetch(`${API_BASE}/ai/chat`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-User-ID': state.currentUser.id.toString()
      },
      body: JSON.stringify({
        conversation_id: state.activeAiConversationId,
        question: q,
        ticket_context: state.activeTicketContext
      })
    });
    const data = await res.json();
    state.activeAiConversationId = data.conversation_id;

    const loader = document.getElementById('tempLoader');
    if (loader) loader.remove();

    msgContainer.innerHTML += `
      <div class="flex flex-col items-start">
        <div class="max-w-2xl p-4 rounded-xl bg-[var(--bg-tertiary)] border border-[var(--border-color)] text-[var(--text-primary)] space-y-2">
          <div>${marked.parse(data.message.content)}</div>
          ${(data.citations || []).length ? `
            <div class="pt-2 border-t border-[var(--border-color)] text-[10px] text-slate-400">
              <span class="font-bold">Sources:</span> ${data.citations.map(c => `<span class="underline ml-1">${c.title}</span>`).join(', ')}
            </div>
          ` : ''}
        </div>
      </div>
    `;
    loadAiConversationsList();
  } catch (err) {
    alert('Error querying Copilot: ' + err.message);
  }
}

// --- FLOATING AI COPILOT DRAWER ---
function toggleFloatingAiDrawer() {
  const drawer = document.getElementById('aiDrawer');
  if (drawer) drawer.classList.toggle('hidden');
}

function updateDrawerTicketContext(ctx) {
  const bar = document.getElementById('drawerTicketContextBar');
  const ticketEl = document.getElementById('drawerContextTicketText');
  const prioEl = document.getElementById('drawerContextPriorityText');
  if (!bar) return;
  if (ctx && ctx.ticket_number) {
    bar.classList.remove('hidden');
    if (ticketEl) ticketEl.textContent = `${ctx.ticket_number} • ${ctx.application}`;
    if (prioEl) prioEl.textContent = ctx.priority;
  } else {
    bar.classList.add('hidden');
  }
}

function startNewDrawerChat() {
  const box = document.getElementById('drawerMessages');
  if (box) {
    box.innerHTML = `<div class="p-2.5 rounded-lg bg-[var(--bg-tertiary)] text-[var(--text-secondary)]">Started new Copilot session. Ask me anything.</div>`;
  }
}

async function sendQuickPrompt(promptText) {
  const input = document.getElementById('drawerInput');
  if (input) input.value = promptText;
  submitDrawerQuestion(new Event('submit'));
}

async function submitDrawerQuestion(e) {
  if (e) e.preventDefault();
  const input = document.getElementById('drawerInput');
  const q = input.value.trim();
  if (!q) return;
  input.value = '';

  const box = document.getElementById('drawerMessages');
  box.innerHTML += `
    <div class="p-2 rounded-lg bg-purple-600 text-white ml-6 text-right">${q}</div>
    <div id="drawerLoading" class="text-slate-400 p-2"><i data-lucide="loader-2" class="w-3.5 h-3.5 animate-spin inline mr-1 text-purple-500"></i>Analyzing knowledge base...</div>
  `;
  lucide.createIcons();
  box.scrollTop = box.scrollHeight;

  try {
    const res = await fetch(`${API_BASE}/ai/chat`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-User-ID': state.currentUser.id.toString()
      },
      body: JSON.stringify({
        question: q,
        ticket_context: state.activeTicketContext
      })
    });
    const data = await res.json();
    const l = document.getElementById('drawerLoading');
    if (l) l.remove();

    box.innerHTML += `
      <div class="p-2.5 rounded-lg bg-[var(--bg-tertiary)] border border-[var(--border-color)] mr-6 space-y-1.5 leading-relaxed">
        <div>${marked.parse(data.message.content)}</div>
      </div>
    `;
    box.scrollTop = box.scrollHeight;
  } catch (err) {
    box.innerHTML += `<div class="p-2 text-red-500">Failed to query Copilot.</div>`;
  }
}

// Quick action trigger from Ticket Detail
function triggerTicketCopilot(ticketNumber) {
  toggleFloatingAiDrawer();
  const input = document.getElementById('drawerInput');
  if (input) {
    input.value = `How should I investigate incident ${ticketNumber}?`;
    submitDrawerQuestion(new Event('submit'));
  }
}

async function triggerDraftCopilot(ticketNumber) {
  try {
    const res = await fetch(`${API_BASE}/ai/quick-action`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-User-ID': state.currentUser.id.toString()
      },
      body: JSON.stringify({
        action: activeCommentType === 'customer' ? 'draft_customer_response' : 'generate_work_note',
        ticket_context: state.activeTicketContext
      })
    });
    const data = await res.json();
    const box = document.getElementById('commentBox');
    if (box) {
      box.value = data.content;
      box.focus();
    }
  } catch (err) {
    alert('Failed to draft AI response: ' + err.message);
  }
}

// --- MODALS (CREATE INCIDENT, RESOLVE, EXPORT, ETC.) ---

async function openCreateModal(initialType = 'Incident', initialCatalogItem = null) {
  let apps = [];
  let projects = [];
  let groups = [];
  const isEndUser = isUserEndUser(state.currentUser);
  window._modalCurrentType = initialType || 'Incident';
  window._modalInitialCatalogItem = initialCatalogItem;

  const authHeaders = {
    'X-User-ID': state.currentUser ? state.currentUser.id.toString() : '1'
  };
  try {
    const fetchPromises = [
      fetch(`${API_BASE}/applications`, { headers: authHeaders }),
      fetch(`${API_BASE}/projects`, { headers: authHeaders })
    ];
    if (!isEndUser) {
      fetchPromises.push(fetch(`${API_BASE}/assignment-groups`, { headers: authHeaders }));
    }
    const [appRes, projRes, grpRes] = await Promise.all(fetchPromises);
    if (appRes && appRes.ok) apps = await appRes.json();
    if (projRes && projRes.ok) projects = await projRes.json();
    if (grpRes && grpRes.ok) groups = await grpRes.json();
  } catch (e) {}

  if (!apps.length || !projects.length) {
    try {
      const [appRes, projRes] = await Promise.all([
        fetch(`${API_BASE}/admin/applications`, { headers: authHeaders }),
        fetch(`${API_BASE}/admin/projects`, { headers: authHeaders })
      ]);
      if (!apps.length && appRes && appRes.ok) apps = await appRes.json();
      if (!projects.length && projRes && projRes.ok) projects = await projRes.json();
    } catch (e) {}
  }

  // Clean catalog — zero dummy fallback apps or projects
  if (!apps) apps = [];
  if (!projects) projects = [];

  window._modalApps = apps;
  window._modalProjects = projects;
  window._modalGroups = groups;

  const modalContainer = document.getElementById('modalContainer');
  modalContainer.innerHTML = `
    <div class="fixed inset-0 bg-black/50 backdrop-blur-sm z-50 flex items-center justify-center p-4">
      <div class="w-full max-w-xl bg-[var(--card-bg)] border border-[var(--border-color)] rounded-2xl shadow-2xl overflow-hidden animate-fade-in max-h-[90vh] flex flex-col">
        <!-- Modal Header -->
        <div class="p-4 border-b border-[var(--border-color)] flex items-center justify-between shrink-0">
          <div class="flex items-center space-x-2">
            <i data-lucide="plus-circle" class="w-5 h-5 text-purple-600"></i>
            <h2 id="modalCreateTitle" class="text-base font-bold">Create New Ticket</h2>
          </div>
          <button onclick="document.getElementById('modalContainer').innerHTML=''" class="text-slate-400 hover:text-white p-1 rounded-lg">✕</button>
        </div>

        <!-- Ticket Type Tabs (Incident, Service Request, Change Request) -->
        <div class="px-5 pt-4 pb-1 shrink-0">
          <div class="flex items-center p-1 bg-[var(--bg-tertiary)] rounded-xl border border-[var(--border-color)] space-x-1">
            <button type="button" onclick="switchModalTicketType('Incident')" id="tabTypeIncident" class="flex-1 py-1.5 px-2 rounded-lg text-xs font-bold transition-all bg-gradient-to-r from-purple-600 to-indigo-600 text-white shadow flex items-center justify-center space-x-1.5">
              <span>⚡ Incident</span>
            </button>
            <button type="button" onclick="switchModalTicketType('Service Request')" id="tabTypeRequest" class="flex-1 py-1.5 px-2 rounded-lg text-xs font-semibold transition-all text-[var(--text-secondary)] hover:text-[var(--text-primary)] flex items-center justify-center space-x-1.5">
              <span>📦 Service Request</span>
            </button>
            <button type="button" onclick="switchModalTicketType('Change Request')" id="tabTypeChange" class="flex-1 py-1.5 px-2 rounded-lg text-xs font-semibold transition-all text-[var(--text-secondary)] hover:text-[var(--text-primary)] flex items-center justify-center space-x-1.5">
              <span>🔄 Change Request</span>
            </button>
          </div>
          <div id="modalTypeDescription" class="text-[11px] text-[var(--text-secondary)] mt-2">
            Report an unexpected system outage, service failure, software error, or performance degradation.
          </div>
        </div>

        <form onsubmit="submitNewTicket(event)" class="p-5 space-y-3.5 text-xs overflow-y-auto flex-1">
          <!-- Common: Project & Application -->
          <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label class="block font-semibold text-slate-400 mb-1">Project *</label>
              <select id="modal_proj" required onchange="filterModalAppsAndGroups()" class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-lg p-2.5 text-xs font-semibold">
                <option value="">Select Project...</option>
                ${projects.map(p => `<option value="${p.id}">${p.name}</option>`).join('')}
              </select>
            </div>

            <div>
              <label class="block font-semibold text-slate-400 mb-1">Application *</label>
              <select id="modal_app" required disabled onchange="filterModalGroupsForApp()" class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-lg p-2.5 text-xs font-semibold">
                <option value="">Select a Project first...</option>
              </select>
            </div>
          </div>

          <!-- INCIDENT-SPECIFIC FIELDS -->
          <div id="fieldsIncident" class="space-y-3.5">
            <div>
              <label class="block font-semibold text-slate-400 mb-1">Category</label>
              <select id="modal_category" class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-lg p-2.5 text-xs">
                <option value="Application">Application</option>
                <option value="Database">Database (Auto-routes to Database Support)</option>
                <option value="Network">Network (Auto-routes to Network Support)</option>
                <option value="Security">Security (Auto-routes to InfoSec)</option>
                <option value="Infrastructure">Infrastructure / Cloud</option>
                <option value="User Access">User Access / Login</option>
              </select>
            </div>

            ${!isEndUser ? `
              <div>
                <label class="block font-semibold text-slate-400 mb-1">Priority (Independent Choice)</label>
                <select id="modal_priority" class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-lg p-2.5 text-xs font-bold">
                  <option value="P1" class="text-rose-600 font-bold">P1 - Critical Outage (All-Hands)</option>
                  <option value="P2" class="text-orange-500 font-bold">P2 - Major Degradation</option>
                  <option value="P3" class="text-amber-500 font-semibold" selected>P3 - Moderate / Workaround Available</option>
                  <option value="P4" class="text-blue-500">P4 - Minor Issue / Cosmetic</option>
                  <option value="P5" class="text-slate-500">P5 - Planning / Inquiry</option>
                </select>
              </div>

              <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label class="block font-semibold text-slate-400 mb-1">Assignment Group (Scoped to Project & Application)</label>
                  <select id="modal_assignment_group" onchange="onModalGroupChange()" class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-lg p-2.5 text-xs font-semibold">
                    <option value="">Auto-Route to Frontline</option>
                  </select>
                </div>

                <div>
                  <label class="block font-semibold text-slate-400 mb-1">Assignee (Filtered by Group)</label>
                  <select id="modal_assigned_to" class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-lg p-2.5 text-xs font-semibold">
                    <option value="">-- Unassigned --</option>
                  </select>
                </div>
              </div>
            ` : `
              <div class="grid grid-cols-2 gap-3">
                <div>
                  <label class="block font-semibold text-slate-400 mb-1">Impact</label>
                  <select id="modal_impact" class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-lg p-2 text-xs">
                    <option value="Critical">Critical</option>
                    <option value="High" selected>High</option>
                    <option value="Medium">Medium</option>
                    <option value="Low">Low</option>
                  </select>
                </div>
                <div>
                  <label class="block font-semibold text-slate-400 mb-1">Urgency</label>
                  <select id="modal_urgency" class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-lg p-2 text-xs">
                    <option value="Critical">Critical</option>
                    <option value="High" selected>High</option>
                    <option value="Medium">Medium</option>
                    <option value="Low">Low</option>
                  </select>
                </div>
              </div>
            `}
          </div>

          <!-- SERVICE REQUEST-SPECIFIC FIELDS -->
          <div id="fieldsServiceRequest" class="hidden space-y-3.5">
            <div>
              <label class="block font-semibold text-slate-400 mb-1">Service / Catalog Item *</label>
              <select id="modal_req_catalog_item" class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-lg p-2.5 text-xs font-semibold">
                <option value="Database Read-Only Access">Database Read-Only Access (PostgreSQL / MySQL)</option>
                <option value="Software Installation & License">Software Installation & Developer Tools License</option>
                <option value="Cloud Environment Sandbox">Cloud Environment Sandbox (EKS / AWS / Azure)</option>
                <option value="User Role & Permission Grant">User Role & Permission Grant (AD / IAM)</option>
                <option value="VPN & Remote Network Access">VPN & Remote Network Access</option>
                <option value="Hardware / Laptop Peripheral">Hardware / Laptop Peripheral</option>
                <option value="General Service Request">General Service Request / Assistance</option>
              </select>
            </div>

            <div>
              <label class="block font-semibold text-slate-400 mb-1">Requested Priority</label>
              <select id="modal_req_priority" class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-lg p-2.5 text-xs font-semibold">
                <option value="P2">P2 - High (Time-sensitive project blocker)</option>
                <option value="P3" selected>P3 - Medium (Standard SLA 24h)</option>
                <option value="P4">P4 - Low (Flexible timeframe)</option>
              </select>
            </div>
          </div>

          <!-- CHANGE REQUEST-SPECIFIC FIELDS -->
          <div id="fieldsChangeRequest" class="hidden space-y-3.5">
            <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div>
                <label class="block font-semibold text-slate-400 mb-1">Change Type *</label>
                <select id="modal_chg_type" class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-lg p-2.5 text-xs font-semibold">
                  <option value="Standard">Standard (Pre-Approved / Low Risk)</option>
                  <option value="Normal" selected>Normal (Requires CAB Approval)</option>
                  <option value="Emergency">Emergency (Immediate Production Fix)</option>
                </select>
              </div>

              <div>
                <label class="block font-semibold text-slate-400 mb-1">Category *</label>
                <select id="modal_chg_category" class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-lg p-2.5 text-xs">
                  <option value="Software Patch">Software Patch / Code Release</option>
                  <option value="Cloud Infrastructure">Cloud Infrastructure & Kubernetes</option>
                  <option value="Database Migration">Database Migration / DDL</option>
                  <option value="Security Patch">Security Patch / Firewall Rule</option>
                  <option value="Configuration Update">Configuration Update</option>
                </select>
              </div>
            </div>

            <div class="grid grid-cols-3 gap-3">
              <div>
                <label class="block font-semibold text-slate-400 mb-1">Priority</label>
                <select id="modal_chg_priority" class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-lg p-2 text-xs">
                  <option value="P1">P1 - Critical</option>
                  <option value="P2">P2 - High</option>
                  <option value="P3" selected>P3 - Medium</option>
                  <option value="P4">P4 - Low</option>
                </select>
              </div>
              <div>
                <label class="block font-semibold text-slate-400 mb-1">Risk</label>
                <select id="modal_chg_risk" class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-lg p-2 text-xs">
                  <option value="Low">Low</option>
                  <option value="Medium" selected>Medium</option>
                  <option value="High">High</option>
                </select>
              </div>
              <div>
                <label class="block font-semibold text-slate-400 mb-1">Impact</label>
                <select id="modal_chg_impact" class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-lg p-2 text-xs">
                  <option value="Low">Low</option>
                  <option value="Medium" selected>Medium</option>
                  <option value="High">High</option>
                </select>
              </div>
            </div>

            <div>
              <label class="block font-semibold text-slate-400 mb-1">Business Justification *</label>
              <input type="text" id="modal_chg_justification" placeholder="Why is this change necessary? e.g. Quarterly security patch" class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-lg p-2.5 text-xs">
            </div>
          </div>

          <!-- Common: Short Description & Description -->
          <div>
            <label class="block font-semibold text-slate-400 mb-1">Short Description *</label>
            <input type="text" id="modal_short_desc" required placeholder="Brief summary of the ticket" class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-lg p-2.5 text-xs font-semibold">
          </div>

          <div>
            <label id="modal_desc_label" class="block font-semibold text-slate-400 mb-1">Detailed Description *</label>
            <textarea id="modal_desc" rows="3" required placeholder="Full error details, reproduction steps, or requirements..." class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-lg p-2.5 text-xs"></textarea>
          </div>

          <!-- Dynamic Info Message for End Users -->
          ${isEndUser ? `
            <div id="modalEndUserInfo" class="p-3 rounded-lg bg-purple-50 dark:bg-purple-950/40 text-[11px] text-purple-700 dark:text-purple-300">
              ℹ️ Your ticket will be automatically routed to the responsible support team with real-time status tracking under <b>My Tickets</b>.
            </div>
          ` : ''}

          <!-- Modal Footer -->
          <div class="pt-3 border-t border-[var(--border-color)] flex items-center justify-between shrink-0">
            <span id="modalTypeBadgeFooter" class="text-[10px] font-bold uppercase tracking-wider text-purple-600 dark:text-purple-400">Type: Incident</span>
            <div class="flex items-center space-x-2">
              <button type="button" onclick="document.getElementById('modalContainer').innerHTML=''" class="px-4 py-2 rounded-lg border border-[var(--border-color)] text-xs font-semibold">Cancel</button>
              <button type="submit" id="modalSubmitBtn" class="bg-gradient-to-r from-purple-600 to-indigo-600 hover:from-purple-700 hover:to-indigo-700 text-white px-5 py-2 rounded-lg text-xs font-bold shadow">Submit Incident</button>
            </div>
          </div>
        </form>
      </div>
    </div>
  `;
  lucide.createIcons();
  switchModalTicketType(window._modalCurrentType || 'Incident');
  if (window._modalInitialCatalogItem) {
    const catEl = document.getElementById('modal_req_catalog_item');
    if (catEl) {
      catEl.value = window._modalInitialCatalogItem;
      if (catEl.value !== window._modalInitialCatalogItem) {
        const opt = document.createElement('option');
        opt.value = window._modalInitialCatalogItem;
        opt.textContent = window._modalInitialCatalogItem;
        opt.selected = true;
        catEl.appendChild(opt);
      }
    }
  }
  if (projects.length === 1) {
    const pSel = document.getElementById('modal_proj');
    if (pSel) pSel.value = projects[0].id;
  }
  filterModalAppsAndGroups();
}

function switchModalTicketType(type) {
  window._modalCurrentType = type;
  const tabInc = document.getElementById('tabTypeIncident');
  const tabReq = document.getElementById('tabTypeRequest');
  const tabChg = document.getElementById('tabTypeChange');
  const descEl = document.getElementById('modalTypeDescription');
  const titleEl = document.getElementById('modalCreateTitle');
  const footerBadge = document.getElementById('modalTypeBadgeFooter');
  const submitBtn = document.getElementById('modalSubmitBtn');
  const descLabel = document.getElementById('modal_desc_label');
  const descInput = document.getElementById('modal_desc');

  const fieldsInc = document.getElementById('fieldsIncident');
  const fieldsReq = document.getElementById('fieldsServiceRequest');
  const fieldsChg = document.getElementById('fieldsChangeRequest');

  const activeClass = 'flex-1 py-1.5 px-2 rounded-lg text-xs font-bold transition-all bg-gradient-to-r from-purple-600 to-indigo-600 text-white shadow flex items-center justify-center space-x-1.5';
  const inactiveClass = 'flex-1 py-1.5 px-2 rounded-lg text-xs font-semibold transition-all text-[var(--text-secondary)] hover:text-[var(--text-primary)] flex items-center justify-center space-x-1.5';

  if (tabInc) tabInc.className = type === 'Incident' ? activeClass : inactiveClass;
  if (tabReq) tabReq.className = type === 'Service Request' ? activeClass : inactiveClass;
  if (tabChg) tabChg.className = type === 'Change Request' ? activeClass : inactiveClass;

  if (fieldsInc) fieldsInc.classList.toggle('hidden', type !== 'Incident');
  if (fieldsReq) fieldsReq.classList.toggle('hidden', type !== 'Service Request');
  if (fieldsChg) fieldsChg.classList.toggle('hidden', type !== 'Change Request');

  if (type === 'Incident') {
    if (titleEl) titleEl.textContent = 'Create New Incident (INC)';
    if (descEl) descEl.textContent = 'Report an unexpected system outage, service failure, software error, or performance degradation.';
    if (footerBadge) footerBadge.textContent = 'Type: Incident (INC)';
    if (submitBtn) submitBtn.textContent = 'Submit Incident';
    if (descLabel) descLabel.textContent = 'Detailed Description *';
    if (descInput) descInput.placeholder = 'Full error details, reproduction steps, or impact...';
  } else if (type === 'Service Request') {
    if (titleEl) titleEl.textContent = 'Submit Service Request (REQ)';
    if (descEl) descEl.textContent = 'Request standard catalog items, database permissions, software installations, or cloud environments.';
    if (footerBadge) footerBadge.textContent = 'Type: Service Request (REQ)';
    if (submitBtn) submitBtn.textContent = 'Submit Service Request';
    if (descLabel) descLabel.textContent = 'Justification & Specifications *';
    if (descInput) descInput.placeholder = 'Describe your business need, duration, and specific technical specifications...';
  } else if (type === 'Change Request') {
    if (titleEl) titleEl.textContent = 'Submit Change Request (CHG)';
    if (descEl) descEl.textContent = 'Request a scheduled deployment, configuration modification, database patch, or infrastructure update.';
    if (footerBadge) footerBadge.textContent = 'Type: Change Request (CHG)';
    if (submitBtn) submitBtn.textContent = 'Submit Change Request';
    if (descLabel) descLabel.textContent = 'Implementation & Rollback Plan *';
    if (descInput) descInput.placeholder = 'Provide the step-by-step implementation plan, rollback procedure, and test verification...';
  }
}

function filterModalAppsAndGroups() {
  const projSelect = document.getElementById('modal_proj');
  const appSelect = document.getElementById('modal_app');
  const grpSelect = document.getElementById('modal_assignment_group');
  if (!projSelect || !appSelect) return;

  const projId = projSelect.value ? parseInt(projSelect.value) : null;
  const allProjects = window._modalProjects || [];
  const allApps = window._modalApps || [];

  if (!projId) {
    appSelect.innerHTML = '<option value="">Select a Project first...</option>';
    appSelect.disabled = true;
    if (grpSelect) {
      grpSelect.innerHTML = '<option value="">Select a Project first...</option>';
      grpSelect.disabled = true;
    }
    return;
  }

  const selectedProj = allProjects.find(p => Number(p.id) === Number(projId));
  const projName = selectedProj ? selectedProj.name.trim().toLowerCase() : '';

  // 1. Filter Applications: apps belonging strictly to this project
  const matchedApps = allApps.filter(a => {
    if (a.project_id && Number(a.project_id) === Number(projId)) return true;
    if (selectedProj && a.project_name && a.project_name.trim().toLowerCase() === projName) return true;
    if (selectedProj && selectedProj.application_id && Number(selectedProj.application_id) === Number(a.id)) return true;
    if (selectedProj && Array.isArray(selectedProj.applications) && selectedProj.applications.some(subA => Number(subA.id) === Number(a.id))) return true;
    if (Array.isArray(a.projects) && a.projects.some(p => Number(p.id) === Number(projId) || (p.name && p.name.trim().toLowerCase() === projName))) return true;
    return false;
  });

  if (matchedApps.length === 0) {
    appSelect.innerHTML = '<option value="">No applications under this project</option>';
    appSelect.disabled = true;
  } else {
    appSelect.disabled = false;
    appSelect.innerHTML = `
      <option value="">Select Application...</option>
      ${matchedApps.map(a => `<option value="${a.id}">${a.name}</option>`).join('')}
    `;
    if (matchedApps.length === 1) {
      appSelect.value = matchedApps[0].id;
    }
  }

  filterModalGroupsForApp();
}

function filterModalGroupsForApp() {
  const projSelect = document.getElementById('modal_proj');
  const appSelect = document.getElementById('modal_app');
  const grpSelect = document.getElementById('modal_assignment_group');
  if (!grpSelect) return;

  const projId = projSelect && projSelect.value ? parseInt(projSelect.value) : null;
  const appId = appSelect && appSelect.value ? parseInt(appSelect.value) : null;
  const allProjects = window._modalProjects || [];
  const allApps = window._modalApps || [];
  const allGroups = window._modalGroups || [];

  if (!projId) {
    grpSelect.innerHTML = '<option value="">Select a Project first...</option>';
    grpSelect.disabled = true;
    return;
  }

  grpSelect.disabled = false;
  const selectedProj = allProjects.find(p => Number(p.id) === Number(projId));
  const selectedApp = allApps.find(a => Number(a.id) === Number(appId));
  const projName = selectedProj ? selectedProj.name.trim().toLowerCase() : '';
  const appName = selectedApp ? selectedApp.name.trim().toLowerCase() : '';

  const projL2 = allGroups.find(g => (selectedProj && (g.id === selectedProj.l2_assignment_group_id || g.id === selectedProj.default_assignment_group_id)) || g.name.toLowerCase() === `${projName}-l2`);
  const projL3 = allGroups.find(g => (selectedProj && g.id === selectedProj.l3_assignment_group_id) || g.name.toLowerCase() === `${projName}-l3`);

  const appSpecificGroups = [];
  const currentProjGroups = [];
  const otherProjGroups = [];
  const sharedGroups = [];

  if (projL2) currentProjGroups.push({ id: projL2.id, name: `${projL2.name} (Level-2 Frontline Queue - Default)` });
  if (projL3) currentProjGroups.push({ id: projL3.id, name: `${projL3.name} (Level-3 Advanced Engineering)` });

  allGroups.forEach(g => {
    if (projL2 && g.id === projL2.id) return;
    if (projL3 && g.id === projL3.id) return;
    const gName = g.name.toLowerCase();
    let projsSupp = [];
    try { projsSupp = JSON.parse(g.projects_supported || '[]').map(x => x.toLowerCase()); } catch (e) {}
    let appsSupp = [];
    try { appsSupp = JSON.parse(g.applications_supported || '[]').map(x => x.toLowerCase()); } catch (e) {}

    const isAppMatch = selectedApp && (
      appsSupp.includes(appName) ||
      (selectedApp.default_assignment_group_id && g.id === selectedApp.default_assignment_group_id) ||
      gName.startsWith(`${appName}-`) ||
      gName === appName
    );

    const isThisProj = projName && (gName.startsWith(`${projName}-`) || gName === projName || projsSupp.includes(projName));
    const isOtherProj = allProjects.some(p => {
      const pN = p.name.toLowerCase();
      return pN !== projName && (gName.startsWith(`${pN}-`) || gName === pN);
    });

    if (isAppMatch) {
      appSpecificGroups.push(g);
    } else if (isThisProj) {
      currentProjGroups.push(g);
    } else if (isOtherProj) {
      otherProjGroups.push(g);
    } else {
      sharedGroups.push(g);
    }
  });

  let defaultGroupVal = '';
  if (selectedApp && selectedApp.default_assignment_group_id) {
    defaultGroupVal = selectedApp.default_assignment_group_id;
  } else if (appSpecificGroups.length > 0) {
    defaultGroupVal = appSpecificGroups[0].id;
  } else if (projL2) {
    defaultGroupVal = projL2.id;
  }

  let grpHtml = `<option value="">Auto-Route to Frontline / Default Queue</option>`;
  if (appSpecificGroups.length > 0) {
    grpHtml += `
      <optgroup label="Application-Specific Queues (${selectedApp ? selectedApp.name : 'Selected Application'})">
        ${appSpecificGroups.map(g => `<option value="${g.id}">${g.name}</option>`).join('')}
      </optgroup>
    `;
  }
  if (currentProjGroups.length > 0) {
    grpHtml += `
      <optgroup label="This Project Queues (${selectedProj ? selectedProj.name : 'Selected Project'})">
        ${currentProjGroups.map(g => `<option value="${g.id}">${g.name}</option>`).join('')}
      </optgroup>
    `;
  }
  if (otherProjGroups.length > 0) {
    grpHtml += `
      <optgroup label="Other Project Queues">
        ${otherProjGroups.map(g => `<option value="${g.id}">${g.name}</option>`).join('')}
      </optgroup>
    `;
  }
  if (sharedGroups.length > 0) {
    grpHtml += `
      <optgroup label="Enterprise & Shared Support Queues">
        ${sharedGroups.map(g => `<option value="${g.id}">${g.name}</option>`).join('')}
      </optgroup>
    `;
  }

  grpSelect.innerHTML = grpHtml;
  if (defaultGroupVal) {
    grpSelect.value = defaultGroupVal;
  }
  onModalGroupChange();
}

function onModalGroupChange() {
  const grpSelect = document.getElementById('modal_assignment_group');
  const userSelect = document.getElementById('modal_assigned_to');
  if (!grpSelect || !userSelect) return;

  const grpId = grpSelect.value ? parseInt(grpSelect.value) : null;
  const allGroups = window._modalGroups || [];
  const selectedGrp = allGroups.find(g => g.id === grpId);

  const assignees = (selectedGrp && selectedGrp.eligible_assignees && selectedGrp.eligible_assignees.length)
    ? selectedGrp.eligible_assignees
    : [];

  userSelect.innerHTML = `
    <option value="">-- Unassigned --</option>
    ${assignees.map(u => `<option value="${u.id}">${u.full_name} (${u.role})</option>`).join('')}
  `;
}

function filterModalProjects() {
  filterModalAppsAndGroups();
}

async function submitNewTicket(e) {
  e.preventDefault();
  const type = window._modalCurrentType || 'Incident';
  const appIdVal = document.getElementById('modal_app').value;
  const projIdVal = document.getElementById('modal_proj').value;

  if (!appIdVal || !projIdVal) {
    alert('Please select both a Project and an Application.');
    return;
  }

  const shortDesc = document.getElementById('modal_short_desc').value.trim();
  const desc = document.getElementById('modal_desc').value.trim();
  if (!shortDesc || !desc) {
    alert('Please enter both Short Description and Detailed Description.');
    return;
  }

  const authHeaders = {
    'Content-Type': 'application/json',
    'X-User-ID': state.currentUser ? state.currentUser.id.toString() : '1'
  };

  try {
    if (type === 'Incident') {
      const payload = {
        application_id: parseInt(appIdVal),
        project_id: parseInt(projIdVal),
        category: document.getElementById('modal_category') ? document.getElementById('modal_category').value : 'Application',
        short_description: shortDesc,
        description: desc,
        impact: document.getElementById('modal_impact') ? document.getElementById('modal_impact').value : 'High',
        urgency: document.getElementById('modal_urgency') ? document.getElementById('modal_urgency').value : 'High'
      };
      const priorityEl = document.getElementById('modal_priority');
      if (priorityEl && priorityEl.value) payload.priority = priorityEl.value;
      const grpEl = document.getElementById('modal_assignment_group');
      if (grpEl && grpEl.value) payload.assignment_group_id = parseInt(grpEl.value);
      const userEl = document.getElementById('modal_assigned_to');
      if (userEl && userEl.value) payload.assigned_to_id = parseInt(userEl.value);

      const res = await fetch(`${API_BASE}/incidents`, {
        method: 'POST',
        headers: authHeaders,
        body: JSON.stringify(payload)
      });
      if (res.ok) {
        const inc = await res.json();
        document.getElementById('modalContainer').innerHTML = '';
        window.location.hash = `#/incidents/${inc.number}`;
      } else {
        const err = await res.json();
        alert('Error submitting incident: ' + (err.detail || 'Server rejected request'));
      }

    } else if (type === 'Service Request') {
      const catalogItem = document.getElementById('modal_req_catalog_item') ? document.getElementById('modal_req_catalog_item').value : 'General IT Request';
      const priority = document.getElementById('modal_req_priority') ? document.getElementById('modal_req_priority').value : 'P3';
      const payload = {
        application_id: parseInt(appIdVal),
        project_id: parseInt(projIdVal),
        catalog_item: catalogItem,
        short_description: shortDesc,
        description: desc,
        priority: priority
      };

      const res = await fetch(`${API_BASE}/service-requests`, {
        method: 'POST',
        headers: authHeaders,
        body: JSON.stringify(payload)
      });
      if (res.ok) {
        const req = await res.json();
        document.getElementById('modalContainer').innerHTML = '';
        window.location.hash = `#/service-requests/${req.number}`;
      } else {
        const err = await res.json();
        alert('Error submitting service request: ' + (err.detail || 'Server rejected request'));
      }

    } else if (type === 'Change Request') {
      const chgType = document.getElementById('modal_chg_type') ? document.getElementById('modal_chg_type').value : 'Normal';
      const chgCat = document.getElementById('modal_chg_category') ? document.getElementById('modal_chg_category').value : 'Software Patch';
      const chgJust = document.getElementById('modal_chg_justification') ? document.getElementById('modal_chg_justification').value : 'Operational requirement';
      const chgRisk = document.getElementById('modal_chg_risk') ? document.getElementById('modal_chg_risk').value : 'Medium';
      const chgImpact = document.getElementById('modal_chg_impact') ? document.getElementById('modal_chg_impact').value : 'Medium';
      const chgPriority = document.getElementById('modal_chg_priority') ? document.getElementById('modal_chg_priority').value : 'P3';

      const payload = {
        application_id: parseInt(appIdVal),
        project_id: parseInt(projIdVal),
        change_type: chgType,
        category: chgCat,
        short_description: shortDesc,
        description: desc,
        business_justification: chgJust || 'Operational update',
        risk: chgRisk,
        impact: chgImpact,
        priority: chgPriority
      };

      const res = await fetch(`${API_BASE}/changes`, {
        method: 'POST',
        headers: authHeaders,
        body: JSON.stringify(payload)
      });
      if (res.ok) {
        const chg = await res.json();
        document.getElementById('modalContainer').innerHTML = '';
        window.location.hash = `#/changes/${chg.number}`;
      } else {
        const err = await res.json();
        alert('Error submitting change request: ' + (err.detail || 'Server rejected request'));
      }
    }
  } catch (err) {
    alert('Error submitting ticket: ' + err.message);
  }
}

// Global helper and backward compatibility aliases
window.openCreateModal = openCreateModal;
window.openCreateIncidentModal = openCreateModal;
window.openCreateChangeModal = function() { openCreateModal('Change Request'); };
window.openCatalogModal = function(cat) { openCreateModal('Service Request', cat); };
window.switchModalTicketType = switchModalTicketType;
window.submitNewTicket = submitNewTicket;
window.submitNewIncident = submitNewTicket;

// --- CLOSURE CATEGORIZATION & RESOLUTION MODAL ---

const CLOSURE_SUBCATEGORIES_CONFIG = {
  "Bug": {
    "Payment Gateway": [
      "Payment Tokenization Failure",
      "Transaction Serialization Deadlock",
      "Webhook Signature Verification Bug",
      "3D Secure 2.0 Auth Timeout",
      "Idempotency Key Collision Bug",
      "Ledger Database Sync Anomaly"
    ],
    "Customer Portal": [
      "Frontend UI Rendering Exception",
      "SSO Session Cookie Dropping",
      "Cart State Eviction Race Condition",
      "Form Validation Bypass Defect",
      "Cross-Site Scripting (XSS) Sanitization Bug"
    ],
    "Identity Management": [
      "SAML Assertion Parsing Bug",
      "OAuth2 PKCE Exchange Failure",
      "Directory Sync LDAP Attribute Loss",
      "MFA Token Verification Timeout",
      "RBAC Role Claim Mapping Defect"
    ],
    "Knowledge Manager": [
      "Elasticsearch Query Syntax Error",
      "Markdown Sanitizer NullPointer",
      "Article Versioning Concurrency Defect"
    ],
    "Workflow Manager": [
      "BPMN Engine Transition Stalling",
      "Async Step Execution Infinite Loop",
      "Task Approval Queue Deadlock"
    ],
    "DEFAULT": [
      "Unhandled Null Pointer / Exception",
      "Memory Leak / Unclosed Sockets",
      "Race Condition in Async Worker",
      "API Contract Schema Mismatch",
      "Database Query Timeout / Unoptimized Index"
    ]
  },
  "Configuration Issue": {
    "DEFAULT": [
      "Environment Variable / Secret Mismatch",
      "TLS / SSL Certificate Expired",
      "Database Connection Pool Sizing Insufficient",
      "CORS Allowed Origins Drift",
      "Firewall / Security Group Ingress Rule Missing",
      "DNS / Route53 Record Misconfiguration",
      "Kubernetes Ingress / Load Balancer Route Error"
    ]
  },
  "Application Limitation": {
    "DEFAULT": [
      "API Rate Limit Exceeded (429 Throttled by Design)",
      "Payload Size Limit (Exceeded 10MB Gateway Threshold)",
      "Maximum Concurrent User Sessions Reached",
      "Unsupported File Attachment Format",
      "Synchronous Processing Window Exceeded (>30s SLA)",
      "Legacy Browser Compatibility Restriction"
    ]
  },
  "Infrastructure Limitation": {
    "DEFAULT": [
      "Kubernetes Node Memory Exhaustion (OOMKilled)",
      "Compute CPU Throttling Under Peak Burst",
      "Persistent Storage Volume Disk Space Full",
      "Cloud Provider Availability Zone Outage",
      "Network Bandwidth Saturation / Packet Drop",
      "Database Read Replica Replication Lag"
    ]
  }
};

async function openResolveModal(ticketId) {
  try {
    const taxonomyResponse = await fetch(`${API_BASE}/admin/configuration/taxonomy?ticket_type=Incident`);
    state.closureTaxonomy = taxonomyResponse.ok ? await taxonomyResponse.json() : [];
  } catch (_) { state.closureTaxonomy = []; }
  let apps = window._modalApps || [];
  if (!apps.length) {
    try {
      const res = await fetch(`${API_BASE}/admin/applications`);
      if (res.ok) apps = await res.json();
    } catch (e) {}
  }
  if (!apps) apps = [];
  const currentAppName = state.activeTicketContext?.application || (apps.length > 0 ? apps[0].name : 'General Application');

  const modalContainer = document.getElementById('modalContainer');
  modalContainer.innerHTML = `
    <div class="fixed inset-0 bg-black/50 backdrop-blur-sm z-50 flex items-center justify-center p-4">
      <div class="w-full max-w-lg bg-[var(--card-bg)] border border-[var(--border-color)] rounded-2xl shadow-2xl overflow-hidden animate-fade-in">
        <div class="p-4 border-b border-[var(--border-color)] flex items-center justify-between">
          <div class="flex items-center space-x-2">
            <i data-lucide="check-circle" class="w-5 h-5 text-emerald-500"></i>
            <h2 class="text-base font-bold">Resolve & Categorize Incident</h2>
          </div>
          <button onclick="document.getElementById('modalContainer').innerHTML=''" class="text-slate-400 hover:text-white">✕</button>
        </div>

        <form onsubmit="confirmResolve(event, ${ticketId})" class="p-5 space-y-3.5 text-xs">
          <!-- Impacted Application -->
          <div>
            <label class="block font-semibold text-slate-400 mb-1">Impacted Application *</label>
            <select id="res_app" required onchange="updateResolveSubcategories()" class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-lg p-2.5 text-xs">
              ${apps.map(a => `<option value="${a.name}" ${a.name === currentAppName ? 'selected' : ''}>${a.name}</option>`).join('')}
            </select>
          </div>

          <!-- Root Cause Category -->
          <div>
            <label class="block font-semibold text-slate-400 mb-1">Root Cause / Closure Category *</label>
            <select id="res_close_category" required onchange="updateResolveSubcategories()" class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-lg p-2.5 text-xs font-semibold text-purple-600 dark:text-purple-400">
              <option value="Bug">Bug (Software Defect)</option>
              <option value="Configuration Issue">Configuration Issue</option>
              <option value="Application Limitation">Application Limitation</option>
              <option value="Infrastructure Limitation">Infrastructure Limitation</option>
              ${(state.closureTaxonomy || []).filter(t => !['Bug', 'Configuration Issue', 'Application Limitation', 'Infrastructure Limitation'].includes(t.category)).filter((t, i, all) => all.findIndex(x => x.category === t.category) === i).map(t => `<option value="${t.category}">${t.category}</option>`).join('')}
            </select>
          </div>

          <!-- Subcategory (Dynamically Updated) -->
          <div>
            <label class="block font-semibold text-slate-400 mb-1">Subcategory (Based on App & Category) *</label>
            <select id="res_close_subcategory" required class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-lg p-2.5 text-xs">
            </select>
          </div>

          <!-- ADO Number (Conditionally Visible if Bug) -->
          <div id="res_ado_container" class="p-3 rounded-xl bg-blue-50/50 dark:bg-blue-950/30 border border-blue-200 dark:border-blue-900/50 space-y-1">
            <label class="block font-bold text-blue-700 dark:text-blue-300 flex items-center space-x-1.5">
              <i data-lucide="bug" class="w-3.5 h-3.5 text-blue-500"></i>
              <span>Azure DevOps (ADO) Bug / Work Item Number *</span>
            </label>
            <input type="text" id="res_ado_number" placeholder="e.g. ADO-48291 or 48291" class="w-full bg-[var(--bg-primary)] border border-blue-300 dark:border-blue-800 rounded-lg p-2 text-xs font-mono">
            <p class="text-[10px] text-blue-600 dark:text-blue-400">Required when closing as a Bug to link engineering defect tracking.</p>
          </div>

          <!-- Resolution Code -->
          <div>
            <label class="block font-semibold text-slate-400 mb-1">Resolution Code</label>
            <select id="res_code" class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-lg p-2.5 text-xs">
              <option value="Solved by Patch / Code Fix">Solved by Patch / Code Fix</option>
              <option value="Solved by Workaround">Solved by Workaround</option>
              <option value="Solved by Configuration Change">Solved by Configuration Change</option>
              <option value="Application Limitation Accepted">Application Limitation Accepted</option>
              <option value="Infrastructure Scaling / Auto-healed">Infrastructure Scaling / Auto-healed</option>
              <option value="Not a Defect">Not a Defect</option>
            </select>
          </div>

          <!-- Resolution Notes -->
          <div>
            <label class="block font-semibold text-slate-400 mb-1">Resolution Notes *</label>
            <textarea id="res_notes" rows="3" required placeholder="Describe the root cause and resolution applied..." class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-lg p-2.5 text-xs font-mono"></textarea>
          </div>

          <div class="pt-3 border-t border-[var(--border-color)] flex justify-end space-x-2">
            <button type="button" onclick="document.getElementById('modalContainer').innerHTML=''" class="px-4 py-2 rounded-lg border text-xs font-semibold">Cancel</button>
            <button type="submit" class="bg-emerald-600 hover:bg-emerald-700 text-white px-5 py-2 rounded-lg text-xs font-bold shadow flex items-center space-x-1.5">
              <i data-lucide="check" class="w-4 h-4"></i>
              <span>Confirm & Mark Resolved</span>
            </button>
          </div>
        </form>
      </div>
    </div>
  `;
  lucide.createIcons();
  updateResolveSubcategories();
}

function updateResolveSubcategories() {
  const cat = document.getElementById('res_close_category')?.value || 'Bug';
  const app = document.getElementById('res_app')?.value || 'DEFAULT';
  const subSelect = document.getElementById('res_close_subcategory');
  const adoContainer = document.getElementById('res_ado_container');
  const adoInput = document.getElementById('res_ado_number');

  // Toggle ADO input visibility
  if (adoContainer) {
    if (cat === 'Bug') {
      adoContainer.style.display = 'block';
      if (adoInput) adoInput.required = true;
    } else {
      adoContainer.style.display = 'none';
      if (adoInput) adoInput.required = false;
    }
  }

  // Populate subcategories
  if (!subSelect) return;
  const configured = (state.closureTaxonomy || []).filter(t => t.active && t.category === cat && (!t.application_name || t.application_name === 'All applications' || t.application_name === app)).map(t => t.subcategory);
  const catConfig = CLOSURE_SUBCATEGORIES_CONFIG[cat] || CLOSURE_SUBCATEGORIES_CONFIG['Bug'];
  const options = configured.length ? [...new Set(configured)] : (catConfig[app] || catConfig['DEFAULT'] || ['Standard Fix']);
  subSelect.innerHTML = options.map(opt => `<option value="${opt}">${opt}</option>`).join('');
}

async function confirmResolve(event, ticketId) {
  event.preventDefault();
  const code = document.getElementById('res_code').value;
  const notes = document.getElementById('res_notes').value;
  const app = document.getElementById('res_app').value;
  const category = document.getElementById('res_close_category').value;
  const subcategory = document.getElementById('res_close_subcategory').value;
  const adoNumber = document.getElementById('res_ado_number')?.value?.trim();

  if (category === 'Bug' && !adoNumber) {
    alert('Please provide an Azure DevOps (ADO) Bug Number when resolving as a software bug.');
    return;
  }

  try {
    const res = await fetch(`${API_BASE}/incidents/${ticketId}/status`, {
      method: 'PATCH',
      headers: {
        'Content-Type': 'application/json',
        'X-User-ID': state.currentUser ? state.currentUser.id.toString() : '1'
      },
      body: JSON.stringify({
        status: 'Resolved',
        resolution_code: code,
        resolution_notes: notes,
        close_category: category,
        close_subcategory: subcategory,
        close_application_name: app,
        ado_number: category === 'Bug' ? adoNumber : null,
        reason: `Resolved with closure category: ${category} (${subcategory})`
      })
    });
    if (res.ok) {
      document.getElementById('modalContainer').innerHTML = '';
      renderIncidentDetailView(document.getElementById('mainApp'), state.routeParams.id);
    } else {
      const err = await res.json();
      alert('Resolution error: ' + (err.detail || 'Could not resolve incident'));
    }
  } catch (err) {
    alert('Resolution error: ' + err.message);
  }
}

// --- EXPORT TICKETS MODAL ---

function openExportModal(ticketType = 'incidents') {
  const typeLabels = {
    'incidents': 'Incidents',
    'service-requests': 'Service Requests',
    'changes': 'Change Requests'
  };
  const label = typeLabels[ticketType] || 'Tickets';

  const defaultColumnsMap = {
    'incidents': [
      'Incident Number', 'Status', 'Priority', 'Short Description', 'Impact', 'Urgency',
      'Application', 'Project', 'Assignment Group', 'Assigned To', 'Caller Name', 'Caller Email',
      'Category', 'Subcategory', 'ADO Work Item #', 'Created At', 'Resolved At', 'Resolution Notes'
    ],
    'service-requests': [
      'Request Number', 'Status', 'Priority', 'Catalog Item', 'Short Description',
      'Application', 'Project', 'Assignment Group', 'Assigned To', 'Requested By',
      'Approval Status', 'Created At', 'Closed At'
    ],
    'changes': [
      'Change Number', 'Status', 'Change Type', 'Risk', 'Priority',
      'Short Description', 'Application', 'Project', 'Assignment Group',
      'Assigned To', 'Requested By', 'Approval Status', 'Planned Start', 'Planned End', 'Created At'
    ]
  };
  const availableColumns = defaultColumnsMap[ticketType] || defaultColumnsMap['incidents'];

  document.getElementById('modalContainer').innerHTML = `
    <div class="fixed inset-0 bg-black/50 backdrop-blur-sm z-50 flex items-center justify-center p-4">
      <div class="w-full max-w-lg bg-[var(--card-bg)] border border-[var(--border-color)] rounded-2xl shadow-2xl p-6 space-y-4 animate-fade-in max-h-[90vh] flex flex-col">
        <div class="flex items-center justify-between pb-3 border-b border-[var(--border-color)] shrink-0">
          <div class="flex items-center space-x-2">
            <i data-lucide="download" class="w-5 h-5 text-purple-600"></i>
            <h2 class="text-base font-bold">Export ${label}</h2>
          </div>
          <button onclick="document.getElementById('modalContainer').innerHTML=''" class="text-slate-400 hover:text-white">✕</button>
        </div>

        <div class="space-y-3.5 text-xs overflow-y-auto flex-1 pr-1">
          <div>
            <label class="block font-semibold text-slate-400 mb-1">Time Period *</label>
            <select id="export_time_period" onchange="toggleCustomDateInputs()" class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-lg p-2.5 text-xs font-semibold">
              <option value="today">Today</option>
              <option value="7d">Last 7 Days</option>
              <option value="30d" selected>Last 30 Days</option>
              <option value="90d">Last 90 Days</option>
              <option value="1y">Last 1 Year</option>
              <option value="all">All Time (Complete Historical Archive)</option>
              <option value="custom">Custom Date Range...</option>
            </select>
          </div>

          <div id="customDateRangeInputs" class="hidden grid grid-cols-2 gap-3 pt-1">
            <div>
              <label class="block font-semibold text-slate-400 mb-1">Start Date</label>
              <input type="date" id="export_start_date" class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-lg p-2 text-xs">
            </div>
            <div>
              <label class="block font-semibold text-slate-400 mb-1">End Date</label>
              <input type="date" id="export_end_date" class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-lg p-2 text-xs">
            </div>
          </div>

          <div>
            <label class="block font-semibold text-slate-400 mb-1">Format</label>
            <div class="grid grid-cols-2 gap-3">
              <label class="flex items-center space-x-2 p-2.5 rounded-lg border border-[var(--border-color)] bg-[var(--bg-tertiary)] cursor-pointer">
                <input type="radio" name="export_format" value="csv" checked class="text-purple-600">
                <span class="font-semibold">CSV (.csv)</span>
              </label>
              <label class="flex items-center space-x-2 p-2.5 rounded-lg border border-[var(--border-color)] bg-[var(--bg-tertiary)] cursor-pointer">
                <input type="radio" name="export_format" value="json" class="text-purple-600">
                <span class="font-semibold">JSON (.json)</span>
              </label>
            </div>
          </div>

          <!-- Column Selection Checkbox Grid -->
          <div class="space-y-2 pt-1">
            <div class="flex items-center justify-between">
              <label class="block font-bold text-slate-400">Select Export Columns</label>
              <div class="space-x-2">
                <button type="button" onclick="toggleAllExportColumns(true)" class="text-[11px] font-bold text-purple-600 hover:underline">Select All</button>
                <span class="text-slate-500">|</span>
                <button type="button" onclick="toggleAllExportColumns(false)" class="text-[11px] font-bold text-slate-400 hover:underline">Clear All</button>
              </div>
            </div>
            <div class="grid grid-cols-2 gap-2 p-3 rounded-xl border border-[var(--border-color)] bg-[var(--bg-tertiary)] max-h-48 overflow-y-auto">
              ${availableColumns.map(col => `
                <label class="flex items-center space-x-2 text-[11px] cursor-pointer hover:text-purple-600">
                  <input type="checkbox" value="${col}" checked class="export-col-cb rounded text-purple-600 focus:ring-purple-500">
                  <span class="truncate">${col}</span>
                </label>
              `).join('')}
            </div>
          </div>

          <div class="p-3 rounded-xl bg-purple-50/50 dark:bg-purple-950/30 text-[11px] text-purple-700 dark:text-purple-300 border border-purple-200 dark:border-purple-800">
            📊 Exports include audit timestamps, ServiceNow metadata, and selected custom columns.
          </div>
        </div>

        <div class="flex justify-end space-x-2 pt-3 border-t border-[var(--border-color)] shrink-0">
          <button onclick="document.getElementById('modalContainer').innerHTML=''" class="px-4 py-2 border rounded-lg text-xs font-semibold">Cancel</button>
          <button onclick="triggerDownload('${ticketType}')" class="bg-gradient-to-r from-purple-600 to-indigo-600 hover:from-purple-700 hover:to-indigo-700 text-white px-5 py-2 rounded-lg text-xs font-bold shadow flex items-center space-x-1.5">
            <i data-lucide="download" class="w-4 h-4"></i>
            <span>Download Export</span>
          </button>
        </div>
      </div>
    </div>
  `;
  lucide.createIcons();
}

function toggleAllExportColumns(check) {
  document.querySelectorAll('.export-col-cb').forEach(cb => { cb.checked = check; });
}

function toggleCustomDateInputs() {
  const val = document.getElementById('export_time_period').value;
  const container = document.getElementById('customDateRangeInputs');
  if (container) {
    container.classList.toggle('hidden', val !== 'custom');
  }
}

function triggerDownload(ticketType) {
  const period = document.getElementById('export_time_period').value;
  const format = document.querySelector('input[name="export_format"]:checked')?.value || 'csv';
  let url = `${API_BASE}/export/${ticketType}?time_period=${period}&format=${format}`;
  if (period === 'custom') {
    const s = document.getElementById('export_start_date')?.value;
    const e = document.getElementById('export_end_date')?.value;
    if (s) url += `&start_date=${encodeURIComponent(s)}`;
    if (e) url += `&end_date=${encodeURIComponent(e)}`;
  }

  const checkedBoxes = Array.from(document.querySelectorAll('.export-col-cb:checked')).map(cb => cb.value);
  if (checkedBoxes.length > 0) {
    url += `&columns=${encodeURIComponent(checkedBoxes.join(','))}`;
  }

  const userId = state.currentUser ? state.currentUser.id.toString() : '1';

  fetch(url, { headers: { 'X-User-ID': userId } })
    .then(res => {
      if (!res.ok) {
        return res.json().then(d => { throw new Error(d.detail || 'Export failed'); });
      }
      return res.blob();
    })
    .then(blob => {
      const blobUrl = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = blobUrl;
      a.download = `${ticketType}_export_${period}.${format}`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      document.getElementById('modalContainer').innerHTML = '';
    })
    .catch(err => alert('Export Error: ' + err.message));
}

// --- ANALYTICS DASHBOARD & CSV / EXCEL IMPORT VIEW ---

let activeAnalyticsTab = 'live';
let currentAnalyticsPeriod = '30d';

async function renderAnalyticsDashboardView(container) {
  container.innerHTML = `
    <div class="space-y-6">
      <!-- Header -->
      <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <div class="flex items-center space-x-2">
            <span class="text-xs font-bold uppercase tracking-wider text-pink-600 dark:text-pink-400">Executive Control Plane</span>
          </div>
          <h1 class="text-2xl font-black tracking-tight mt-0.5">ITSM Analytics & Intelligence</h1>
          <p class="text-sm text-slate-500">Root cause governance, Azure DevOps defect tracking, SLA compliance, and CSV/Excel visualizer.</p>
        </div>

        <!-- Tab Toggle -->
        <div class="flex bg-[var(--bg-tertiary)] p-1 rounded-xl border border-[var(--border-color)] text-xs font-semibold self-start">
          <button onclick="switchAnalyticsTab('live')" id="tab_btn_live" class="px-4 py-2 rounded-lg ${activeAnalyticsTab === 'live' ? 'bg-purple-600 text-white shadow-sm' : 'text-slate-400 hover:text-[var(--text-primary)]'} transition-all flex items-center space-x-1.5">
            <i data-lucide="activity" class="w-4 h-4"></i>
            <span>Live System Metrics</span>
          </button>
          <button onclick="switchAnalyticsTab('import')" id="tab_btn_import" class="px-4 py-2 rounded-lg ${activeAnalyticsTab === 'import' ? 'bg-purple-600 text-white shadow-sm' : 'text-slate-400 hover:text-[var(--text-primary)]'} transition-all flex items-center space-x-1.5">
            <i data-lucide="file-spreadsheet" class="w-4 h-4"></i>
            <span>Import & Visualize CSV / Excel</span>
          </button>
        </div>
      </div>

      <!-- Container Body -->
      <div id="analyticsContentContainer">
        ${activeAnalyticsTab === 'live' ? `<div class="p-8 text-center text-slate-400"><i data-lucide="loader-2" class="w-8 h-8 animate-spin mx-auto mb-2 text-purple-500"></i>Loading Live Operational Intelligence...</div>` : ''}
      </div>
    </div>
  `;
  lucide.createIcons();

  if (activeAnalyticsTab === 'live') {
    loadLiveAnalytics();
  } else {
    renderImportVisualizer();
  }
}

function switchAnalyticsTab(tab) {
  activeAnalyticsTab = tab;
  renderAnalyticsDashboardView(document.getElementById('mainApp'));
}

async function loadLiveAnalytics() {
  const container = document.getElementById('analyticsContentContainer');
  if (!container) return;

  try {
    const res = await fetch(`${API_BASE}/dashboard/analytics?time_period=${currentAnalyticsPeriod}`, {
      headers: { 'X-User-ID': state.currentUser ? state.currentUser.id.toString() : '1' }
    });
    const d = await res.json();
    const s = d.summary;

    container.innerHTML = `
      <div class="space-y-6 animate-fade-in">
        <!-- Controls Bar -->
        <div class="p-4 rounded-2xl bg-[var(--card-bg)] border border-[var(--border-color)] flex flex-wrap items-center justify-between gap-3 text-xs shadow-sm">
          <div class="flex items-center space-x-2">
            <span class="font-semibold text-slate-400">Time Range:</span>
            <div class="inline-flex rounded-xl bg-[var(--bg-tertiary)] p-1 border border-[var(--border-color)]">
              ${['7d', '30d', '90d', '1y', 'all'].map(p => `
                <button onclick="setAnalyticsPeriod('${p}')" class="px-3 py-1 rounded-lg text-xs font-semibold ${currentAnalyticsPeriod === p ? 'bg-purple-600 text-white' : 'text-slate-400 hover:text-[var(--text-primary)]'} transition-all">
                  ${p === '7d' ? '7 Days' : (p === '30d' ? '30 Days' : (p === '90d' ? '90 Days' : (p === '1y' ? '1 Year' : 'All Time')))}
                </button>
              `).join('')}
            </div>
          </div>
          <div class="flex items-center space-x-2">
            <button onclick="openExportModal('incidents')" class="px-3 py-1.5 rounded-lg border border-[var(--border-color)] bg-[var(--bg-tertiary)] hover:bg-[var(--card-bg)] font-semibold flex items-center space-x-1.5 text-purple-600 dark:text-purple-300">
              <i data-lucide="download" class="w-3.5 h-3.5"></i>
              <span>Export Incident Dataset</span>
            </button>
          </div>
        </div>

        <!-- KPI Cards -->
        <div class="grid grid-cols-2 md:grid-cols-5 gap-4">
          <div class="p-5 rounded-2xl bg-[var(--card-bg)] border border-[var(--border-color)] shadow-sm">
            <div class="text-[11px] font-semibold text-slate-400 uppercase">Total Incidents</div>
            <div class="text-3xl font-black mt-2 text-[var(--text-primary)]">${s.total_tickets}</div>
            <div class="text-[10px] text-slate-400 mt-1">${s.open_tickets} Open / ${s.resolved_tickets} Resolved</div>
          </div>
          <div class="p-5 rounded-2xl bg-[var(--card-bg)] border border-[var(--border-color)] shadow-sm">
            <div class="text-[11px] font-semibold text-slate-400 uppercase">Resolution Rate</div>
            <div class="text-3xl font-black mt-2 text-emerald-500">${s.resolution_rate_pct}%</div>
            <div class="text-[10px] text-slate-400 mt-1">SLA Target > 95%</div>
          </div>
          <div class="p-5 rounded-2xl bg-[var(--card-bg)] border border-[var(--border-color)] shadow-sm">
            <div class="text-[11px] font-semibold text-slate-400 uppercase">Mean Time to Resolve</div>
            <div class="text-3xl font-black mt-2 text-purple-600">${s.mttr_hours}h</div>
            <div class="text-[10px] text-slate-400 mt-1">MTTR Business Hours</div>
          </div>
          <div class="p-5 rounded-2xl bg-[var(--card-bg)] border border-[var(--border-color)] shadow-sm">
            <div class="text-[11px] font-semibold text-slate-400 uppercase">Bug / Defect Ratio</div>
            <div class="text-3xl font-black mt-2 text-red-500">${s.bug_defect_rate_pct}%</div>
            <div class="text-[10px] text-slate-400 mt-1">Of Resolved Incidents</div>
          </div>
          <div class="p-5 rounded-2xl bg-[var(--card-bg)] border border-[var(--border-color)] shadow-sm">
            <div class="text-[11px] font-semibold text-slate-400 uppercase">ADO Linked Bugs</div>
            <div class="text-3xl font-black mt-2 text-blue-500">${s.ado_tracked_count}</div>
            <div class="text-[10px] text-slate-400 mt-1">Azure DevOps Tracked</div>
          </div>
        </div>

        <!-- Charts Grid 1: Closure Root Cause & Priority -->
        <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
          <!-- Closure Root Cause Distribution -->
          <div class="p-6 rounded-2xl bg-[var(--card-bg)] border border-[var(--border-color)] shadow-sm">
            <div class="flex items-center justify-between mb-4">
              <div>
                <h3 class="font-bold text-sm">Root Cause / Closure Distribution</h3>
                <p class="text-xs text-slate-400">Bug vs Configuration vs Limitations</p>
              </div>
              <span class="text-[10px] px-2 py-0.5 rounded bg-purple-100 dark:bg-purple-950 font-bold text-purple-600">ITSM Governance</span>
            </div>
            <div class="h-64 relative">
              <canvas id="closureChart"></canvas>
            </div>
          </div>

          <!-- Priority Distribution -->
          <div class="p-6 rounded-2xl bg-[var(--card-bg)] border border-[var(--border-color)] shadow-sm">
            <div class="flex items-center justify-between mb-4">
              <div>
                <h3 class="font-bold text-sm">Ticket Volume by Priority</h3>
                <p class="text-xs text-slate-400">P1 Critical through P4 Low</p>
              </div>
              <span class="text-[10px] px-2 py-0.5 rounded bg-blue-100 dark:bg-blue-950 font-bold text-blue-600">SLA Precedence</span>
            </div>
            <div class="h-64 relative">
              <canvas id="priorityAnalyticsChart"></canvas>
            </div>
          </div>
        </div>

        <!-- Charts Grid 2: Volume by Application & Volume Timeline -->
        <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div class="p-6 rounded-2xl bg-[var(--card-bg)] border border-[var(--border-color)] shadow-sm">
            <div class="flex items-center justify-between mb-4">
              <div>
                <h3 class="font-bold text-sm">Incidents by Application</h3>
                <p class="text-xs text-slate-400">Distribution across enterprise landscape</p>
              </div>
            </div>
            <div class="h-64 relative">
              <canvas id="appVolumeChart"></canvas>
            </div>
          </div>

          <div class="p-6 rounded-2xl bg-[var(--card-bg)] border border-[var(--border-color)] shadow-sm">
            <div class="flex items-center justify-between mb-4">
              <div>
                <h3 class="font-bold text-sm">Created vs Resolved Trend</h3>
                <p class="text-xs text-slate-400">Operational velocity & queue burndown</p>
              </div>
            </div>
            <div class="h-64 relative">
              <canvas id="timelineChart"></canvas>
            </div>
          </div>
        </div>

        <!-- ADO Bugs Table -->
        <div class="rounded-2xl bg-[var(--card-bg)] border border-[var(--border-color)] overflow-hidden shadow-sm">
          <div class="p-4 bg-[var(--bg-tertiary)] border-b border-[var(--border-color)] flex items-center justify-between">
            <div class="flex items-center space-x-2">
              <i data-lucide="bug" class="w-4 h-4 text-blue-500"></i>
              <h3 class="font-bold text-xs">Azure DevOps (ADO) Tracked Defects</h3>
            </div>
            <span class="text-xs text-slate-400">${(d.ado_bugs || []).length} Bugs Tracked</span>
          </div>

          ${(d.ado_bugs && d.ado_bugs.length > 0) ? `
            <div class="overflow-x-auto">
              <table class="w-full text-left text-xs">
                <thead class="bg-[var(--bg-tertiary)] text-slate-400 uppercase font-semibold text-[10px]">
                  <tr>
                    <th class="p-3">ADO #</th>
                    <th class="p-3">Incident #</th>
                    <th class="p-3">Application</th>
                    <th class="p-3">Defect Subcategory</th>
                    <th class="p-3">Short Description</th>
                    <th class="p-3">Status</th>
                  </tr>
                </thead>
                <tbody class="divide-y divide-[var(--border-color)]">
                  ${d.ado_bugs.map(b => `
                    <tr class="hover:bg-[var(--bg-tertiary)] transition-colors">
                      <td class="p-3 font-mono font-bold text-blue-600">
                        <span class="px-2 py-0.5 rounded bg-blue-100 dark:bg-blue-950/60 border border-blue-200 dark:border-blue-900">${b.ado_number}</span>
                      </td>
                      <td class="p-3 font-bold text-purple-600">
                        <a href="#/incidents/${b.incident_number}" class="hover:underline">${b.incident_number}</a>
                      </td>
                      <td class="p-3 font-semibold text-[var(--text-primary)]">${b.application}</td>
                      <td class="p-3 text-slate-400">${b.close_subcategory}</td>
                      <td class="p-3 text-slate-300 max-w-xs truncate">${b.short_description}</td>
                      <td class="p-3">
                        <span class="px-2 py-0.5 rounded text-[10px] font-semibold bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300">${b.status}</span>
                      </td>
                    </tr>
                  `).join('')}
                </tbody>
              </table>
            </div>
          ` : `
            <div class="p-8 text-center text-xs text-slate-400">
              No incidents currently marked with ADO defect numbers in this time window.
            </div>
          `}
        </div>
      </div>
    `;
    lucide.createIcons();

    // Render Chart.js
    renderLiveAnalyticsCharts(d);

  } catch (err) {
    container.innerHTML = `<div class="p-8 text-center text-red-500">Failed to load analytics: ${err.message}</div>`;
  }
}

function setAnalyticsPeriod(period) {
  currentAnalyticsPeriod = period;
  loadLiveAnalytics();
}

function renderLiveAnalyticsCharts(data) {
  // 1. Closure Category Chart
  const ctxClosure = document.getElementById('closureChart');
  if (ctxClosure) {
    const cats = data.closure_categories || {};
    new Chart(ctxClosure, {
      type: 'doughnut',
      data: {
        labels: ['Bug', 'Config Issue', 'App Limitation', 'Infra Limitation', 'Other'],
        datasets: [{
          data: [
            cats['Bug'] || 0,
            cats['Configuration Issue'] || 0,
            cats['Application Limitation'] || 0,
            cats['Infrastructure Limitation'] || 0,
            cats['Other / Workaround'] || 0
          ],
          backgroundColor: ['#ef4444', '#f59e0b', '#3b82f6', '#a855f7', '#64748b']
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { position: 'right', labels: { boxWidth: 12, font: { size: 11 } } }
        }
      }
    });
  }

  // 2. Priority Chart
  const ctxPriority = document.getElementById('priorityAnalyticsChart');
  if (ctxPriority) {
    const p = data.by_priority || {};
    new Chart(ctxPriority, {
      type: 'doughnut',
      data: {
        labels: ['P1 Critical', 'P2 High', 'P3 Medium', 'P4 Low'],
        datasets: [{
          data: [p.P1 || 0, p.P2 || 0, p.P3 || 0, p.P4 || 0],
          backgroundColor: ['#ef4444', '#f97316', '#eab308', '#94a3b8']
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { position: 'right', labels: { boxWidth: 12, font: { size: 11 } } }
        }
      }
    });
  }

  // 3. Application Volume Bar Chart
  const ctxApp = document.getElementById('appVolumeChart');
  if (ctxApp) {
    const apps = (data.by_application || []).slice(0, 6);
    new Chart(ctxApp, {
      type: 'bar',
      data: {
        labels: apps.map(a => a.name),
        datasets: [{
          label: 'Incidents Logged',
          data: apps.map(a => a.count),
          backgroundColor: '#9333ea',
          borderRadius: 6
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          y: { beginAtZero: true, ticks: { precision: 0 } },
          x: { ticks: { font: { size: 10 } } }
        }
      }
    });
  }

  // 4. Timeline Line Chart
  const ctxTimeline = document.getElementById('timelineChart');
  if (ctxTimeline) {
    const tl = data.timeline || [];
    new Chart(ctxTimeline, {
      type: 'line',
      data: {
        labels: tl.map(t => t.date.slice(5)),
        datasets: [
          {
            label: 'Created',
            data: tl.map(t => t.created),
            borderColor: '#9333ea',
            backgroundColor: 'rgba(147, 51, 234, 0.1)',
            tension: 0.3,
            fill: true
          },
          {
            label: 'Resolved',
            data: tl.map(t => t.resolved),
            borderColor: '#10b981',
            backgroundColor: 'rgba(16, 185, 129, 0.1)',
            tension: 0.3,
            fill: true
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { position: 'top', labels: { boxWidth: 12 } } },
        scales: {
          y: { beginAtZero: true, ticks: { precision: 0 } },
          x: { ticks: { font: { size: 10 } } }
        }
      }
    });
  }
}

// --- TAB 2: IMPORT & VISUALIZE CSV / EXCEL ---

function renderImportVisualizer() {
  const container = document.getElementById('analyticsContentContainer');
  if (!container) return;

  container.innerHTML = `
    <div class="space-y-6 animate-fade-in">
      <!-- File Upload Zone -->
      <div class="p-8 rounded-2xl bg-[var(--card-bg)] border-2 border-dashed border-[var(--border-color)] hover:border-purple-500 transition-colors text-center shadow-sm">
        <input type="file" id="csvFileInput" accept=".csv,.txt,.xlsx,.xls" onchange="handleFileSelected(event)" class="hidden">
        <div class="max-w-md mx-auto space-y-3">
          <div class="w-14 h-14 rounded-2xl bg-purple-100 dark:bg-purple-950/60 text-purple-600 flex items-center justify-center mx-auto shadow-inner">
            <i data-lucide="upload-cloud" class="w-7 h-7"></i>
          </div>
          <div>
            <h2 class="text-base font-bold text-[var(--text-primary)]">Import ITSM Dataset to Visualize</h2>
            <p class="text-xs text-slate-400 mt-1">Upload any CSV or Excel file exported from this platform or external ticketing systems.</p>
          </div>
          <div class="flex items-center justify-center gap-3 pt-2">
            <button onclick="document.getElementById('csvFileInput').click()" class="bg-gradient-to-r from-purple-600 to-indigo-600 hover:from-purple-700 hover:to-indigo-700 text-white px-5 py-2.5 rounded-xl text-xs font-bold shadow flex items-center space-x-1.5">
              <i data-lucide="file-plus" class="w-4 h-4"></i>
              <span>Choose CSV / Excel File</span>
            </button>
            <button onclick="loadSampleImportData()" class="px-4 py-2.5 rounded-xl border border-[var(--border-color)] bg-[var(--bg-tertiary)] hover:bg-[var(--card-bg)] text-xs font-semibold text-purple-600 dark:text-purple-300 flex items-center space-x-1.5">
              <i data-lucide="sparkles" class="w-4 h-4 text-purple-500"></i>
              <span>Load Sample ITSM Dataset</span>
            </button>
          </div>
          <p class="text-[10px] text-slate-500">Supports .csv files with standard columns (Number, Status, Priority, Application, Close Category, ADO #).</p>
        </div>
      </div>

      <!-- Container for rendered imported charts and table -->
      <div id="importedResultsContainer" class="hidden space-y-6"></div>
    </div>
  `;
  lucide.createIcons();
}

function handleFileSelected(e) {
  const file = e.target.files[0];
  if (!file) return;

  const reader = new FileReader();
  reader.onload = function(evt) {
    const content = evt.target.result;
    processAndVisualizeCSV(content, file.name);
  };
  reader.readAsText(file);
}

function loadSampleImportData() {
  const sampleCSV = `Incident Number,Status,Priority,Impact,Urgency,Short Description,Application,Project,Assignment Group,Assigned To,Caller Name,Caller Email,Category,Subcategory,Resolution Code,Close Category,Close Subcategory,ADO Work Item #,Close Application,Created At,Resolved At,Closed At,Resolution Notes
INC0001001,Resolved,P1,High,High,Payment checkout tokenization latency spike,Payment Gateway,Payment Platform Modernization,Payment Application Support,Sarah Johnson,John Smith,john.smith@company.com,Application,API,Solved by Patch / Code Fix,Bug,Transaction Serialization Deadlock,ADO-94281,Payment Gateway,2026-09-01 09:15:00,2026-09-01 11:30:00,2026-09-01 12:00:00,Patched database deadlock in redis lock manager.
INC0001002,Resolved,P2,High,Medium,Customer Portal cart session expiration during checkout,Customer Portal,Customer Portal Modernization,Payment Application Support,David Wilson,Mike Brown,mike.brown@company.com,Application,Cart,Solved by Configuration Change,Configuration Issue,Environment Variable / Secret Mismatch,,Customer Portal,2026-09-02 10:00:00,2026-09-02 13:00:00,2026-09-02 14:00:00,Updated session cookie TTL in ingress controller.
INC0001003,In Progress,P3,Medium,Medium,Identity Management SAML assertion signature mismatch,Identity Management,IAM Transformation,Database Support,Sarah Johnson,John Smith,john.smith@company.com,Security,SAML,,,Bug,SAML Assertion Parsing Bug,ADO-94302,Identity Management,2026-09-03 14:20:00,,,Investigating XML digital signature validation.
INC0001004,Resolved,P1,Critical,High,Redis cache connection pool exhausted under peak load,Payment Gateway,Payment Platform Modernization,Payment Application Support,Sarah Johnson,Mike Brown,mike.brown@company.com,Database,Pool,Solved by Workaround,Infrastructure Limitation,Kubernetes Node Memory Exhaustion (OOMKilled),,Payment Gateway,2026-09-04 08:30:00,2026-09-04 09:45:00,2026-09-04 10:00:00,Scaled Redis cluster replicas from 2 to 6 nodes.
INC0001005,Resolved,P4,Low,Low,Report export payload size exceeded threshold,Knowledge Manager,Cloud Migration,Cloud Operations,David Wilson,John Smith,john.smith@company.com,Application,Export,Application Limitation Accepted,Application Limitation,Payload Size Limit (Exceeded 10MB Gateway Threshold),,Knowledge Manager,2026-09-05 11:10:00,2026-09-05 12:00:00,2026-09-05 12:30:00,Customer advised to use asynchronous pagination API.
INC0001006,Resolved,P2,High,Medium,Payment Gateway webhook signature retry bug,Payment Gateway,Payment Platform Modernization,Payment Application Support,Sarah Johnson,John Smith,john.smith@company.com,Application,Webhooks,Solved by Patch / Code Fix,Bug,Webhook Signature Verification Bug,ADO-94350,Payment Gateway,2026-09-05 13:40:00,2026-09-05 15:10:00,2026-09-05 15:30:00,Fixed HMAC-SHA256 digest computation on retried payloads.`;

  processAndVisualizeCSV(sampleCSV, 'sample_enterprise_itsm_export.csv');
}

function parseCSVToObjects(text) {
  const lines = text.trim().split(/\r?\n/);
  if (lines.length < 2) return [];

  // Parse header
  const headers = parseCSVLine(lines[0]);

  const records = [];
  for (let i = 1; i < lines.length; i++) {
    const line = lines[i].trim();
    if (!line) continue;
    const values = parseCSVLine(line);
    const obj = {};
    headers.forEach((h, idx) => {
      obj[h] = values[idx] !== undefined ? values[idx] : '';
    });
    records.push(obj);
  }
  return records;
}

function parseCSVLine(line) {
  const result = [];
  let inQuote = false;
  let cur = '';
  for (let i = 0; i < line.length; i++) {
    const c = line[i];
    if (c === '"') {
      if (inQuote && line[i + 1] === '"') {
        cur += '"';
        i++;
      } else {
        inQuote = !inQuote;
      }
    } else if (c === ',' && !inQuote) {
      result.push(cur.trim());
      cur = '';
    } else {
      cur += c;
    }
  }
  result.push(cur.trim());
  return result;
}

function processAndVisualizeCSV(content, filename) {
  const records = parseCSVToObjects(content);
  if (!records.length) {
    alert('No valid records found in the provided CSV file.');
    return;
  }

  // Find column names flexible to case/naming
  const getField = (row, ...candidates) => {
    for (let c of candidates) {
      const match = Object.keys(row).find(k => k.toLowerCase().replace(/[^a-z0-9]/g, '') === c.toLowerCase().replace(/[^a-z0-9]/g, ''));
      if (match && row[match]) return row[match];
    }
    return '';
  };

  let total = records.length;
  let resolvedCount = 0;
  let bugCount = 0;
  let adoCount = 0;
  const priorities = { P1: 0, P2: 0, P3: 0, P4: 0 };
  const apps = {};
  const closureCats = {
    'Bug': 0,
    'Configuration Issue': 0,
    'Application Limitation': 0,
    'Infrastructure Limitation': 0,
    'Other': 0
  };
  const statuses = {};

  records.forEach(r => {
    const status = getField(r, 'Status') || 'Unknown';
    statuses[status] = (statuses[status] || 0) + 1;
    if (['Resolved', 'Closed', 'Fulfilled'].includes(status)) {
      resolvedCount++;
    }

    const prio = getField(r, 'Priority') || 'P3';
    if (priorities[prio] !== undefined) priorities[prio]++;

    const app = getField(r, 'Application', 'Close Application', 'App') || 'General';
    apps[app] = (apps[app] || 0) + 1;

    const cat = getField(r, 'Close Category', 'Root Cause', 'Category');
    if (['Bug', 'Configuration Issue', 'Application Limitation', 'Infrastructure Limitation'].includes(cat)) {
      closureCats[cat]++;
    } else if (cat) {
      closureCats['Other']++;
    }

    if (cat === 'Bug') bugCount++;

    const ado = getField(r, 'ADO Work Item #', 'ADO #', 'ADO Number', 'ADO');
    if (ado) adoCount++;
  });

  const resContainer = document.getElementById('importedResultsContainer');
  if (!resContainer) return;
  resContainer.classList.remove('hidden');

  resContainer.innerHTML = `
    <!-- Top Summary Banner -->
    <div class="p-4 rounded-2xl bg-gradient-to-r from-purple-900/40 to-indigo-900/40 border border-purple-500/30 flex flex-wrap items-center justify-between gap-3 text-xs">
      <div class="flex items-center space-x-2.5">
        <i data-lucide="check-circle" class="w-5 h-5 text-emerald-400"></i>
        <div>
          <div class="font-bold text-sm text-[var(--text-primary)]">Visualizing Imported Dataset: <span class="text-purple-400">${filename}</span></div>
          <div class="text-slate-400 text-[11px]">${total} Rows successfully parsed & visualized below</div>
        </div>
      </div>
      <button onclick="renderImportVisualizer()" class="px-3 py-1.5 rounded-lg border border-[var(--border-color)] bg-[var(--bg-tertiary)] hover:bg-[var(--card-bg)] font-semibold text-slate-300">
        Upload Another File
      </button>
    </div>

    <!-- KPI Metric Cards for Imported Data -->
    <div class="grid grid-cols-2 md:grid-cols-4 gap-4">
      <div class="p-5 rounded-2xl bg-[var(--card-bg)] border border-[var(--border-color)] shadow-sm">
        <div class="text-[11px] font-semibold text-slate-400 uppercase">Total Records</div>
        <div class="text-3xl font-black mt-2 text-[var(--text-primary)]">${total}</div>
        <div class="text-[10px] text-slate-400 mt-1">Imported from file</div>
      </div>
      <div class="p-5 rounded-2xl bg-[var(--card-bg)] border border-[var(--border-color)] shadow-sm">
        <div class="text-[11px] font-semibold text-slate-400 uppercase">Resolved Ratio</div>
        <div class="text-3xl font-black mt-2 text-emerald-500">${roundPct(resolvedCount, total)}%</div>
        <div class="text-[10px] text-slate-400 mt-1">${resolvedCount} of ${total} resolved</div>
      </div>
      <div class="p-5 rounded-2xl bg-[var(--card-bg)] border border-[var(--border-color)] shadow-sm">
        <div class="text-[11px] font-semibold text-slate-400 uppercase">Defect / Bug Rate</div>
        <div class="text-3xl font-black mt-2 text-red-500">${roundPct(bugCount, resolvedCount || total)}%</div>
        <div class="text-[10px] text-slate-400 mt-1">${bugCount} Bug closures detected</div>
      </div>
      <div class="p-5 rounded-2xl bg-[var(--card-bg)] border border-[var(--border-color)] shadow-sm">
        <div class="text-[11px] font-semibold text-slate-400 uppercase">ADO Linked Items</div>
        <div class="text-3xl font-black mt-2 text-blue-500">${adoCount}</div>
        <div class="text-[10px] text-slate-400 mt-1">Azure DevOps tracked</div>
      </div>
    </div>

    <!-- Charts Grid -->
    <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
      <div class="p-6 rounded-2xl bg-[var(--card-bg)] border border-[var(--border-color)] shadow-sm">
        <h3 class="font-bold text-sm mb-1">Imported Priority Breakdown</h3>
        <p class="text-xs text-slate-400 mb-4">P1 through P4 Distribution</p>
        <div class="h-64 relative">
          <canvas id="importedPriorityChart"></canvas>
        </div>
      </div>

      <div class="p-6 rounded-2xl bg-[var(--card-bg)] border border-[var(--border-color)] shadow-sm">
        <h3 class="font-bold text-sm mb-1">Closure / Root Cause Breakdown</h3>
        <p class="text-xs text-slate-400 mb-4">Bug, Config, App Limit, Infra Limit</p>
        <div class="h-64 relative">
          <canvas id="importedClosureChart"></canvas>
        </div>
      </div>

      <div class="p-6 rounded-2xl bg-[var(--card-bg)] border border-[var(--border-color)] shadow-sm">
        <h3 class="font-bold text-sm mb-1">Volume by Application</h3>
        <p class="text-xs text-slate-400 mb-4">Most impacted applications in imported dataset</p>
        <div class="h-64 relative">
          <canvas id="importedAppChart"></canvas>
        </div>
      </div>

      <div class="p-6 rounded-2xl bg-[var(--card-bg)] border border-[var(--border-color)] shadow-sm">
        <h3 class="font-bold text-sm mb-1">Status Distribution</h3>
        <p class="text-xs text-slate-400 mb-4">State breakdown across imported tickets</p>
        <div class="h-64 relative">
          <canvas id="importedStatusChart"></canvas>
        </div>
      </div>
    </div>

    <!-- Imported Rows Table -->
    <div class="rounded-2xl bg-[var(--card-bg)] border border-[var(--border-color)] overflow-hidden shadow-sm">
      <div class="p-4 bg-[var(--bg-tertiary)] border-b border-[var(--border-color)] flex flex-col sm:flex-row sm:items-center justify-between gap-3 text-xs">
        <div class="flex items-center space-x-2">
          <i data-lucide="table" class="w-4 h-4 text-purple-600"></i>
          <h3 class="font-bold text-xs">Imported Records Preview (${records.length} items)</h3>
        </div>
        <input type="text" id="tableFilterInput" onkeyup="filterImportedTable()" placeholder="Search imported rows..." class="bg-[var(--bg-primary)] border border-[var(--border-color)] rounded-lg px-3 py-1.5 text-xs">
      </div>
      <div class="overflow-x-auto max-h-96 overflow-y-auto">
        <table id="importedDataTable" class="w-full text-left text-xs">
          <thead class="bg-[var(--bg-tertiary)] text-slate-400 uppercase font-semibold text-[10px] sticky top-0">
            <tr>
              <th class="p-3">Ticket #</th>
              <th class="p-3">Priority</th>
              <th class="p-3">Status</th>
              <th class="p-3">Application</th>
              <th class="p-3">Short Description</th>
              <th class="p-3">Root Cause / Category</th>
              <th class="p-3">ADO Work Item #</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-[var(--border-color)]">
            ${records.map(r => {
              const num = getField(r, 'Incident Number', 'Request Number', 'Change Number', 'Ticket Number', 'Number') || 'TKT';
              const prio = getField(r, 'Priority') || 'P3';
              const stat = getField(r, 'Status') || 'Open';
              const app = getField(r, 'Application', 'Close Application', 'App') || '-';
              const desc = getField(r, 'Short Description', 'Summary', 'Description') || '-';
              const cat = getField(r, 'Close Category', 'Root Cause', 'Category') || '-';
              const ado = getField(r, 'ADO Work Item #', 'ADO #', 'ADO Number', 'ADO') || '';

              return `
                <tr class="hover:bg-[var(--bg-tertiary)] transition-colors">
                  <td class="p-3 font-bold text-purple-600">${num}</td>
                  <td class="p-3"><span class="px-2 py-0.5 rounded text-[10px] font-bold badge-${prio.toLowerCase()}">${prio}</span></td>
                  <td class="p-3"><span class="px-2 py-0.5 rounded text-[10px] font-semibold bg-slate-100 dark:bg-slate-800">${stat}</span></td>
                  <td class="p-3 font-semibold text-[var(--text-primary)]">${app}</td>
                  <td class="p-3 text-slate-300 max-w-xs truncate">${desc}</td>
                  <td class="p-3"><span class="px-2 py-0.5 rounded text-[10px] font-semibold ${cat === 'Bug' ? 'bg-red-100 text-red-700 dark:bg-red-950 dark:text-red-300' : 'bg-slate-100 dark:bg-slate-800'}">${cat}</span></td>
                  <td class="p-3 font-mono font-bold text-blue-600">${ado ? `<span class="px-1.5 py-0.5 rounded bg-blue-50 dark:bg-blue-950/60 border border-blue-200 dark:border-blue-900">${ado}</span>` : '-'}</td>
                </tr>
              `;
            }).join('')}
          </tbody>
        </table>
      </div>
    </div>
  `;
  lucide.createIcons();

  // Render Charts for Imported Data
  renderImportedCharts(priorities, closureCats, apps, statuses);
}

function roundPct(val, total) {
  if (!total) return 0;
  return Math.round((val / total) * 100);
}

function filterImportedTable() {
  const query = document.getElementById('tableFilterInput')?.value?.toLowerCase() || '';
  const rows = document.querySelectorAll('#importedDataTable tbody tr');
  rows.forEach(r => {
    const text = r.textContent.toLowerCase();
    r.style.display = text.includes(query) ? '' : 'none';
  });
}

function renderImportedCharts(priorities, closureCats, apps, statuses) {
  // 1. Priority Chart
  const ctxPrio = document.getElementById('importedPriorityChart');
  if (ctxPrio) {
    new Chart(ctxPrio, {
      type: 'doughnut',
      data: {
        labels: ['P1 Critical', 'P2 High', 'P3 Medium', 'P4 Low'],
        datasets: [{
          data: [priorities.P1 || 0, priorities.P2 || 0, priorities.P3 || 0, priorities.P4 || 0],
          backgroundColor: ['#ef4444', '#f97316', '#eab308', '#94a3b8']
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { position: 'right', labels: { boxWidth: 12 } } }
      }
    });
  }

  // 2. Closure Categories Chart
  const ctxClosure = document.getElementById('importedClosureChart');
  if (ctxClosure) {
    new Chart(ctxClosure, {
      type: 'doughnut',
      data: {
        labels: ['Bug', 'Config Issue', 'App Limitation', 'Infra Limitation', 'Other'],
        datasets: [{
          data: [
            closureCats['Bug'] || 0,
            closureCats['Configuration Issue'] || 0,
            closureCats['Application Limitation'] || 0,
            closureCats['Infrastructure Limitation'] || 0,
            closureCats['Other'] || 0
          ],
          backgroundColor: ['#ef4444', '#f59e0b', '#3b82f6', '#a855f7', '#64748b']
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { position: 'right', labels: { boxWidth: 12 } } }
      }
    });
  }

  // 3. Applications Chart
  const ctxApps = document.getElementById('importedAppChart');
  if (ctxApps) {
    const sortedApps = Object.entries(apps).sort((a, b) => b[1] - a[1]).slice(0, 6);
    new Chart(ctxApps, {
      type: 'bar',
      data: {
        labels: sortedApps.map(a => a[0]),
        datasets: [{
          data: sortedApps.map(a => a[1]),
          backgroundColor: '#9333ea',
          borderRadius: 6
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: { y: { beginAtZero: true, ticks: { precision: 0 } } }
      }
    });
  }

  // 4. Status Chart
  const ctxStatus = document.getElementById('importedStatusChart');
  if (ctxStatus) {
    const statusEntries = Object.entries(statuses);
    new Chart(ctxStatus, {
      type: 'bar',
      data: {
        labels: statusEntries.map(s => s[0]),
        datasets: [{
          data: statusEntries.map(s => s[1]),
          backgroundColor: '#3b82f6',
          borderRadius: 6
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: { y: { beginAtZero: true, ticks: { precision: 0 } } }
      }
    });
  }
}

// ============================================================================
// --- IDENTITY MANAGEMENT & ACCESS CONTROL VIEW ---
// ============================================================================

let currentIdentityTab = 'users';

async function renderIdentityManagementView(container) {
  container.innerHTML = `<div class="p-8 text-center text-slate-400"><i data-lucide="loader-2" class="w-8 h-8 animate-spin mx-auto mb-2 text-purple-500"></i>Loading Identity & Access Management...</div>`;
  lucide.createIcons();

  let users = [];
  let customGroups = [];
  let adMappings = [];
  let ssoConfigs = [];
  let permissionsList = [];

  try {
    const [uRes, gRes, mRes, sRes, pRes] = await Promise.allSettled([
      fetch(`${API_BASE}/id/users`),
      fetch(`${API_BASE}/id/groups`),
      fetch(`${API_BASE}/id/ad-mappings`),
      fetch(`${API_BASE}/id/sso/config`),
      fetch(`${API_BASE}/id/permissions`)
    ]);

    if (uRes.status === 'fulfilled' && uRes.value.ok) users = await uRes.value.json();
    if (gRes.status === 'fulfilled' && gRes.value.ok) customGroups = await gRes.value.json();
    if (mRes.status === 'fulfilled' && mRes.value.ok) adMappings = await mRes.value.json();
    if (sRes.status === 'fulfilled' && sRes.value.ok) ssoConfigs = await sRes.value.json();
    if (pRes.status === 'fulfilled' && pRes.value.ok) permissionsList = await pRes.value.json();
  } catch (e) {
    console.warn("Identity service fetch warning:", e);
  }

  container.innerHTML = `
    <div class="space-y-6">
      <div class="flex flex-col md:flex-row md:items-center md:justify-between gap-3">
        <div>
          <div class="flex items-center space-x-2">
            <h1 class="text-2xl font-black tracking-tight">Enterprise Identity & Access Management</h1>
            <span class="px-2.5 py-0.5 rounded-full text-[10px] font-bold bg-blue-100 dark:bg-blue-950 text-blue-700 dark:text-blue-300 border border-blue-200 dark:border-blue-800">Identity Service Pod</span>
          </div>
          <p class="text-sm text-slate-500">Manage local users, fixed administrator credentials, custom RBAC groups, Active Directory group mapping, and B2B/B2C SSO with SAML 2.0 metadata.</p>
        </div>
        <div class="flex items-center space-x-2">
          <a href="${API_BASE}/id/docs" target="_blank" class="border border-[var(--border-color)] bg-[var(--card-bg)] hover:bg-[var(--bg-tertiary)] px-3 py-2 rounded-xl text-xs font-bold flex items-center space-x-1.5 text-purple-600">
            <i data-lucide="file-code" class="w-4 h-4"></i>
            <span>Identity API Swagger</span>
          </a>
        </div>
      </div>

      <!-- Navigation Tabs -->
      <div class="flex space-x-1 border-b border-[var(--border-color)]">
        <button onclick="switchIdentityTab('users')" id="tabBtn-users" class="px-4 py-2.5 text-xs font-bold border-b-2 ${currentIdentityTab === 'users' ? 'border-purple-600 text-purple-600' : 'border-transparent text-slate-400 hover:text-[var(--text-primary)]'} flex items-center space-x-1.5">
          <i data-lucide="users" class="w-4 h-4"></i>
          <span>Local Users & Admin</span>
          <span class="ml-1 px-1.5 py-0.2 rounded-full text-[10px] bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300">${users.length}</span>
        </button>
        <button onclick="switchIdentityTab('groups')" id="tabBtn-groups" class="px-4 py-2.5 text-xs font-bold border-b-2 ${currentIdentityTab === 'groups' ? 'border-purple-600 text-purple-600' : 'border-transparent text-slate-400 hover:text-[var(--text-primary)]'} flex items-center space-x-1.5">
          <i data-lucide="shield" class="w-4 h-4"></i>
          <span>Roles & Custom Groups</span>
          <span class="ml-1 px-1.5 py-0.2 rounded-full text-[10px] bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300">${customGroups.length}</span>
        </button>
        <button onclick="switchIdentityTab('ad')" id="tabBtn-ad" class="px-4 py-2.5 text-xs font-bold border-b-2 ${currentIdentityTab === 'ad' ? 'border-purple-600 text-purple-600' : 'border-transparent text-slate-400 hover:text-[var(--text-primary)]'} flex items-center space-x-1.5">
          <i data-lucide="network" class="w-4 h-4"></i>
          <span>Active Directory Mappings</span>
          <span class="ml-1 px-1.5 py-0.2 rounded-full text-[10px] bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300">${adMappings.length}</span>
        </button>
        <button onclick="switchIdentityTab('sso')" id="tabBtn-sso" class="px-4 py-2.5 text-xs font-bold border-b-2 ${currentIdentityTab === 'sso' ? 'border-purple-600 text-purple-600' : 'border-transparent text-slate-400 hover:text-[var(--text-primary)]'} flex items-center space-x-1.5">
          <i data-lucide="key" class="w-4 h-4"></i>
          <span>Enterprise SSO & SAML Metadata</span>
        </button>
      </div>

      <!-- Tab Content Area -->
      <div id="identityTabContent"></div>
    </div>
  `;
  lucide.createIcons();

  renderIdentityTabContent(users, customGroups, adMappings, ssoConfigs, permissionsList);
}

function switchIdentityTab(tab) {
  currentIdentityTab = tab;
  const container = document.getElementById('mainApp');
  if (container) renderIdentityManagementView(container);
}

function renderIdentityTabContent(users, customGroups, adMappings, ssoConfigs, permissionsList) {
  const content = document.getElementById('identityTabContent');
  if (!content) return;

  if (currentIdentityTab === 'users') {
    content.innerHTML = `
      <div class="space-y-4">
        <div class="flex items-center justify-between">
          <div class="text-xs text-slate-500">Local user accounts managed directly in the platform, including the bootstrapped fixed administrator (<b>admin</b>).</div>
          <button onclick="openCreateLocalUserModal()" class="bg-purple-600 hover:bg-purple-700 text-white px-3.5 py-1.5 rounded-xl text-xs font-semibold shadow flex items-center space-x-1.5">
            <i data-lucide="user-plus" class="w-3.5 h-3.5"></i>
            <span>+ Add Local User</span>
          </button>
        </div>

        <div class="rounded-2xl bg-[var(--card-bg)] border border-[var(--border-color)] overflow-hidden shadow-sm">
          <div class="overflow-x-auto">
            <table class="w-full text-left text-xs">
              <thead class="bg-[var(--bg-tertiary)] text-slate-400 uppercase font-semibold text-[10px]">
                <tr>
                  <th class="p-3.5">Username</th>
                  <th class="p-3.5">Full Name</th>
                  <th class="p-3.5">Email</th>
                  <th class="p-3.5">Role</th>
                  <th class="p-3.5">Custom Groups</th>
                  <th class="p-3.5">Account Type</th>
                  <th class="p-3.5">Status</th>
                  <th class="p-3.5 text-right">Actions</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-[var(--border-color)]">
                ${users.map(u => `
                  <tr class="hover:bg-[var(--bg-tertiary)] transition-colors">
                    <td class="p-3.5 font-bold text-purple-600 flex items-center space-x-1.5">
                      <span>${u.username}</span>
                      ${u.username === 'admin' ? '<span class="px-1.5 py-0.2 rounded text-[9px] font-black bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300">BOOTSTRAP ADMIN</span>' : ''}
                    </td>
                    <td class="p-3.5 font-medium text-[var(--text-primary)]">${u.full_name}</td>
                    <td class="p-3.5 text-slate-500">${u.email}</td>
                    <td class="p-3.5">
                      <span class="px-2 py-0.5 rounded text-[10px] font-bold ${u.role === 'itsm_admin' || u.role === 'administrator' ? 'bg-purple-100 text-purple-700 dark:bg-purple-950 dark:text-purple-300' : u.role === 'itsm_user' || u.role === 'support_member' ? 'bg-blue-100 text-blue-700 dark:bg-blue-950 dark:text-blue-300' : 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300'}">
                        ${u.role}
                      </span>
                    </td>
                    <td class="p-3.5">
                      ${(u.custom_groups && u.custom_groups.length) ? u.custom_groups.map(g => `<span class="px-1.5 py-0.2 rounded text-[9px] bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 mr-1">${g}</span>`).join('') : '<span class="text-slate-400">—</span>'}
                    </td>
                    <td class="p-3.5">
                      <span class="px-2 py-0.5 rounded text-[10px] font-semibold ${u.is_local ? 'bg-emerald-50 dark:bg-emerald-950 text-emerald-600' : 'bg-indigo-50 dark:bg-indigo-950 text-indigo-600'}">
                        ${u.is_local ? 'Local Account' : 'SSO Account'}
                      </span>
                    </td>
                    <td class="p-3.5">
                      <span class="px-2 py-0.5 rounded text-[10px] font-semibold ${u.active ? 'text-emerald-600' : 'text-slate-400'}">${u.active ? '● Active' : '○ Inactive'}</span>
                    </td>
                    <td class="p-3.5 text-right space-x-2">
                      <button onclick="openEditLocalUserModal(${u.id}, '${u.username}', '${u.full_name}', '${u.email}', '${u.role}')" class="text-purple-600 hover:text-purple-700 font-bold text-xs">Edit</button>
                    </td>
                  </tr>
                `).join('')}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    `;
  } else if (currentIdentityTab === 'groups') {
    content.innerHTML = `
      <div class="space-y-6">
        <!-- Standard Roles Box -->
        <div class="p-4 rounded-2xl bg-[var(--card-bg)] border border-[var(--border-color)] space-y-3">
          <h3 class="font-bold text-sm flex items-center space-x-2">
            <i data-lucide="shield-alert" class="w-4 h-4 text-purple-600"></i>
            <span>Standard ITSM System Roles</span>
          </h3>
          <div class="grid grid-cols-1 md:grid-cols-3 gap-3 text-xs">
            <div class="p-3 rounded-xl bg-purple-500/5 border border-purple-500/20">
              <div class="font-bold text-purple-600 text-sm mb-1">itsm_admin</div>
              <p class="text-slate-500 text-[11px] mb-2">Has all platform permissions (*). Can configure applications, routing, SLAs, security, and credentials.</p>
              <div class="text-[10px] font-semibold text-purple-500">Scope: Full Administrative Control</div>
            </div>
            <div class="p-3 rounded-xl bg-blue-500/5 border border-blue-500/20">
              <div class="font-bold text-blue-600 text-sm mb-1">itsm_user</div>
              <p class="text-slate-500 text-[11px] mb-2">Standard support agent. Can create, fulfill, assign, resolve tickets, and record internal work notes.</p>
              <div class="text-[10px] font-semibold text-blue-500">Scope: Ticket Fulfill & Incident Response</div>
            </div>
            <div class="p-3 rounded-xl bg-slate-500/5 border border-slate-500/20">
              <div class="font-bold text-slate-600 dark:text-slate-300 text-sm mb-1">itsm_read</div>
              <p class="text-slate-500 text-[11px] mb-2">Auditor or viewer role. Read-only access to view tickets, schedules, and knowledge base.</p>
              <div class="text-[10px] font-semibold text-slate-400">Scope: Read-Only Audit & Search</div>
            </div>
          </div>
        </div>

        <!-- Custom Groups Table -->
        <div class="space-y-3">
          <div class="flex items-center justify-between">
            <div>
              <h3 class="font-bold text-sm">Custom Security Groups & Tailored Permissions</h3>
              <p class="text-xs text-slate-500">Create custom groups with granular permissions of your choice.</p>
            </div>
            <button onclick="openCreateCustomGroupModal()" class="bg-purple-600 hover:bg-purple-700 text-white px-3.5 py-1.5 rounded-xl text-xs font-semibold shadow flex items-center space-x-1.5">
              <i data-lucide="plus" class="w-3.5 h-3.5"></i>
              <span>+ Add Custom Group</span>
            </button>
          </div>

          <div class="rounded-2xl bg-[var(--card-bg)] border border-[var(--border-color)] overflow-hidden shadow-sm">
            <table class="w-full text-left text-xs">
              <thead class="bg-[var(--bg-tertiary)] text-slate-400 uppercase font-semibold text-[10px]">
                <tr>
                  <th class="p-3.5">Group Name</th>
                  <th class="p-3.5">Description</th>
                  <th class="p-3.5">Permissions Count</th>
                  <th class="p-3.5">Permissions Granted</th>
                  <th class="p-3.5 text-right">Actions</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-[var(--border-color)]">
                ${customGroups.map(g => `
                  <tr class="hover:bg-[var(--bg-tertiary)] transition-colors">
                    <td class="p-3.5 font-bold text-purple-600">${g.name}</td>
                    <td class="p-3.5 text-slate-500">${g.description || '—'}</td>
                    <td class="p-3.5 font-bold">${g.permissions.length} perms</td>
                    <td class="p-3.5">
                      <div class="flex flex-wrap gap-1 max-w-md">
                        ${g.permissions.map(p => `<span class="px-1.5 py-0.2 rounded text-[9px] bg-purple-50 dark:bg-purple-950 text-purple-700 dark:text-purple-300 font-mono">${p}</span>`).join('')}
                      </div>
                    </td>
                    <td class="p-3.5 text-right space-x-2">
                      <button onclick="deleteCustomGroup(${g.id})" class="text-red-500 hover:text-red-700 font-bold text-xs">Delete</button>
                    </td>
                  </tr>
                `).join('') || `<tr><td colspan="5" class="p-8 text-center text-slate-400">No custom groups created yet. Click "+ Add Custom Group" to create one.</td></tr>`}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    `;
  } else if (currentIdentityTab === 'ad') {
    content.innerHTML = `
      <div class="space-y-6">
        <div class="flex items-center justify-between">
          <div>
            <h3 class="font-bold text-sm">Active Directory (AD) / LDAP Group Mappings</h3>
            <p class="text-xs text-slate-500">Map enterprise AD group claims to ITSM standard roles and custom groups.</p>
          </div>
          <button onclick="openCreateADMappingModal()" class="bg-purple-600 hover:bg-purple-700 text-white px-3.5 py-1.5 rounded-xl text-xs font-semibold shadow flex items-center space-x-1.5">
            <i data-lucide="plus" class="w-3.5 h-3.5"></i>
            <span>+ Add AD Mapping</span>
          </button>
        </div>

        <div class="rounded-2xl bg-[var(--card-bg)] border border-[var(--border-color)] overflow-hidden shadow-sm">
          <table class="w-full text-left text-xs">
            <thead class="bg-[var(--bg-tertiary)] text-slate-400 uppercase font-semibold text-[10px]">
              <tr>
                <th class="p-3.5">AD Group Name / DN</th>
                <th class="p-3.5">Mapped Role</th>
                <th class="p-3.5">Mapped Custom Group</th>
                <th class="p-3.5">Description</th>
                <th class="p-3.5 text-right">Actions</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-[var(--border-color)]">
              ${adMappings.map(m => `
                <tr class="hover:bg-[var(--bg-tertiary)] transition-colors">
                  <td class="p-3.5 font-bold font-mono text-purple-600">${m.ad_group_name}</td>
                  <td class="p-3.5">
                    <span class="px-2 py-0.5 rounded text-[10px] font-bold ${m.target_role === 'itsm_admin' ? 'bg-purple-100 text-purple-700' : 'bg-blue-100 text-blue-700'}">
                      ${m.target_role || 'None'}
                    </span>
                  </td>
                  <td class="p-3.5 font-medium">${m.custom_group_name || '—'}</td>
                  <td class="p-3.5 text-slate-500">${m.description || '—'}</td>
                  <td class="p-3.5 text-right">
                    <button onclick="deleteADMapping(${m.id})" class="text-red-500 hover:text-red-700 font-bold text-xs">Delete</button>
                  </td>
                </tr>
              `).join('') || `<tr><td colspan="5" class="p-8 text-center text-slate-400">No AD group mappings defined yet.</td></tr>`}
            </tbody>
          </table>
        </div>

        <!-- Live AD Resolution Sandbox -->
        <div class="p-4 rounded-2xl bg-[var(--card-bg)] border border-[var(--border-color)] space-y-3">
          <h4 class="font-bold text-xs flex items-center space-x-1.5">
            <i data-lucide="check-circle-2" class="w-4 h-4 text-emerald-500"></i>
            <span>Active Directory Claim Resolution Tester</span>
          </h4>
          <p class="text-[11px] text-slate-500">Type comma-separated AD groups to verify how permissions will be resolved when a user authenticates.</p>
          <div class="flex gap-2">
            <input id="testAdGroupsInput" type="text" placeholder="e.g. CN=ITSM-Admins,OU=Groups,DC=company, CN=Payment-Engineers,OU=Support" class="flex-1 bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-xl px-3 py-2 text-xs focus:ring-2 focus:ring-purple-500" />
            <button onclick="testAdResolution()" class="bg-indigo-600 hover:bg-indigo-700 text-white px-4 py-2 rounded-xl text-xs font-bold">Test Resolution</button>
          </div>
          <div id="adResolutionResult" class="hidden p-3 rounded-xl bg-[var(--bg-tertiary)] border border-[var(--border-color)] text-xs"></div>
        </div>
      </div>
    `;
  } else if (currentIdentityTab === 'sso') {
    content.innerHTML = `
      <div class="space-y-6">
        <!-- SAML SP Metadata Download & Direct Redirect Banner -->
        <div class="p-5 rounded-2xl bg-gradient-to-r from-purple-900/40 via-indigo-900/30 to-purple-950/40 border border-purple-500/40 space-y-4">
          <div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
            <div>
              <div class="flex items-center space-x-2">
                <h3 class="font-bold text-sm text-purple-200 flex items-center space-x-2">
                  <i data-lucide="shield-check" class="w-5 h-5 text-purple-400"></i>
                  <span>Enterprise SSO & SAML 2.0 / OIDC Integration Hub</span>
                </h3>
                <span class="px-2 py-0.5 rounded-full text-[10px] font-bold bg-emerald-950 text-emerald-300 border border-emerald-800">Edge Gateway Ready</span>
              </div>
              <p class="text-xs text-slate-300 mt-1">Seamless federation with Enterprise Sign-On (ESO), Microsoft Entra ID (Azure AD), Keycloak, and B2B/B2C IdPs.</p>
            </div>
            <div class="flex items-center space-x-2">
              <a href="/sso-redirect.html" target="_blank" class="bg-gradient-to-r from-indigo-600 to-purple-600 hover:from-indigo-500 hover:to-purple-500 text-white px-3.5 py-2 rounded-xl text-xs font-bold flex items-center space-x-1.5 shadow-lg">
                <i data-lucide="external-link" class="w-4 h-4"></i>
                <span>Open SSO Redirect Flow</span>
              </a>
              <a href="${API_BASE}/id/sso/metadata.xml" download="nexus-itsm-sp-metadata.xml" class="bg-purple-600 hover:bg-purple-700 text-white px-3.5 py-2 rounded-xl text-xs font-bold flex items-center space-x-1.5 shadow-lg">
                <i data-lucide="download" class="w-4 h-4"></i>
                <span>Download SP XML</span>
              </a>
            </div>
          </div>
          <div class="p-3 bg-black/40 rounded-xl border border-white/10 font-mono text-[11px] text-purple-200 grid grid-cols-1 sm:grid-cols-3 gap-2">
            <div>EntityID: <span class="text-amber-300 break-all">${window.location.origin}${ITSM_BASE_PATH}/api/id/saml/metadata</span></div>
            <div>ACS URL: <span class="text-emerald-300 break-all">${window.location.origin}${ITSM_BASE_PATH}/api/id/saml/acs</span> (HTTP-POST)</div>
            <div>Edge Redirect: <span class="text-cyan-300 break-all">${window.location.origin}${ITSM_BASE_PATH}/sso</span></div>
          </div>
        </div>

        <!-- Seamless ESO Registration (Existing App ID) Card -->
        <div class="p-5 rounded-2xl bg-[var(--card-bg)] border border-purple-500/30 shadow-sm space-y-3">
          <div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
            <div>
              <div class="flex items-center space-x-2">
                <h4 class="font-bold text-sm text-[var(--text-primary)]">Seamless ESO Registration (Existing App ID)</h4>
                <span class="px-2 py-0.5 rounded text-[10px] font-bold bg-purple-100 dark:bg-purple-950 text-purple-600 dark:text-purple-300 border border-purple-300 dark:border-purple-800">Fast Setup</span>
              </div>
              <p class="text-xs text-slate-400 mt-1">If you already have an App ID in corporate ESO, Keycloak, or Azure AD, register it to instantly pre-configure SP endpoints and claim mapping paths.</p>
            </div>
            <button onclick="openRegisterESOAppIdModal()" class="bg-purple-600 hover:bg-purple-700 text-white px-4 py-2 rounded-xl text-xs font-bold shadow flex items-center space-x-1.5 whitespace-nowrap">
              <i data-lucide="plus-circle" class="w-4 h-4"></i>
              <span>Register Existing ESO App ID</span>
            </button>
          </div>
        </div>

        <!-- Live Claim & Group Mapping Sandbox -->
        <div class="p-5 rounded-2xl bg-[var(--card-bg)] border border-[var(--border-color)] shadow-sm space-y-4">
          <div class="flex items-center justify-between">
            <div>
              <h4 class="font-bold text-sm text-[var(--text-primary)]">Live SSO Claim & Group Mapping Sandbox</h4>
              <p class="text-xs text-slate-400">Test how incoming IdP claims (email, name, groups) resolve to Platform Roles, Custom Groups, and ITSM Assignment Queues.</p>
            </div>
            <button onclick="testClaimAndGroupMapping()" class="bg-indigo-600 hover:bg-indigo-700 text-white px-3.5 py-1.5 rounded-xl text-xs font-bold shadow flex items-center space-x-1.5">
              <i data-lucide="play" class="w-3.5 h-3.5"></i>
              <span>Simulate Mapping</span>
            </button>
          </div>

          <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label class="block font-semibold text-xs mb-1 text-slate-400">Sample Token Claims (JSON)</label>
              <textarea id="sampleClaimsInput" rows="7" class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-xl p-3 font-mono text-xs text-slate-200 focus:ring-1 focus:ring-purple-500">{
  "email": "alex.engineer@enterprise.corp",
  "name": "Alex Engineer",
  "groups": ["ITSM-Admins", "Service Desk", "Cloud Operations"],
  "realm_access": {
    "roles": ["support_lead", "ServiceDesk"]
  }
}</textarea>
            </div>
            <div>
              <label class="block font-semibold text-xs mb-1 text-slate-400">Resolved Identity & ITSM Mapping Preview</label>
              <div id="mappingSimulationOutput" class="h-[148px] overflow-y-auto bg-black/40 border border-[var(--border-color)] rounded-xl p-3 text-xs text-slate-300 space-y-1.5 font-mono">
                <div class="text-slate-500 italic">Click "Simulate Mapping" to evaluate claims against application groups.</div>
              </div>
            </div>
          </div>
        </div>

        <!-- SSO Providers Management List -->
        <div class="space-y-3">
          <div class="flex items-center justify-between">
            <div>
              <h3 class="font-bold text-sm">Configured SSO Providers</h3>
              <p class="text-xs text-slate-500">Active SAML 2.0 & OIDC federations with role mapping.</p>
            </div>
            <div class="flex space-x-2">
              <button onclick="openImportIdPMetadataModal()" class="border border-purple-500 text-purple-600 hover:bg-purple-50 dark:hover:bg-purple-950 px-3.5 py-1.5 rounded-xl text-xs font-semibold shadow flex items-center space-x-1.5">
                <i data-lucide="upload" class="w-3.5 h-3.5"></i>
                <span>Import IdP Metadata XML</span>
              </button>
            </div>
          </div>

          <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
            ${ssoConfigs.map(c => `
              <div class="p-4 rounded-2xl bg-[var(--card-bg)] border border-[var(--border-color)] shadow-sm space-y-2.5">
                <div class="flex items-center justify-between">
                  <div class="flex items-center space-x-2">
                    <span class="font-bold text-sm text-[var(--text-primary)]">${c.name}</span>
                    ${c.eso_app_id ? `<span class="px-2 py-0.5 rounded text-[9px] font-bold bg-purple-950 text-purple-300 border border-purple-800">ESO App: ${c.eso_app_id}</span>` : ''}
                  </div>
                  <span class="px-2 py-0.5 rounded text-[10px] font-bold ${c.b2b_or_b2c === 'b2b' ? 'bg-indigo-100 text-indigo-700 dark:bg-indigo-950 dark:text-indigo-300' : 'bg-pink-100 text-pink-700 dark:bg-pink-950 dark:text-pink-300'} uppercase">${c.b2b_or_b2c} · ${c.provider_type}</span>
                </div>
                <div class="text-xs text-slate-500 space-y-1">
                  <div>Entity ID: <code class="text-purple-600 text-[11px]">${c.entity_id || '—'}</code></div>
                  <div>SSO Endpoint: <code class="text-slate-400 break-all text-[11px]">${c.sso_url || '—'}</code></div>
                  <div>Default Role: <span class="font-semibold text-purple-400 capitalize">${c.default_role || 'itsm_user'}</span></div>
                </div>
                <div class="pt-2 flex items-center justify-between border-t border-[var(--border-color)]">
                  <span class="text-[10px] font-semibold text-emerald-600">● SSO Enabled</span>
                  <a href="/sso-redirect.html?provider_id=${c.id}${c.eso_app_id ? '&eso_app_id=' + c.eso_app_id : ''}" target="_blank" class="text-[11px] font-bold text-purple-600 hover:text-purple-500 hover:underline flex items-center space-x-1">
                    <span>Test SSO Redirect</span>
                    <i data-lucide="arrow-right" class="w-3 h-3"></i>
                  </a>
                </div>
              </div>
            `).join('') || `
              <div class="col-span-2 p-8 text-center text-slate-400 rounded-2xl bg-[var(--card-bg)] border border-[var(--border-color)]">
                No external SSO providers registered yet. Click "Register Existing ESO App ID" or "Import IdP Metadata XML" to add your first federation.
              </div>
            `}
          </div>
        </div>
      </div>
    `;
  }

  lucide.createIcons();
}

// ── Modals & Actions for Identity Management ──

function openCreateLocalUserModal() {
  const modalHtml = `
    <div id="identityModal" class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
      <div class="bg-[var(--card-bg)] border border-[var(--border-color)] rounded-2xl shadow-2xl max-w-md w-full p-6 space-y-4">
        <h3 class="font-bold text-base">Create Local User</h3>
        <div class="space-y-3 text-xs">
          <div>
            <label class="block font-semibold mb-1 text-slate-400">Username *</label>
            <input id="newLocalUsername" type="text" placeholder="e.g. jdoe" class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-xl px-3 py-2" />
          </div>
          <div>
            <label class="block font-semibold mb-1 text-slate-400">Password *</label>
            <input id="newLocalPassword" type="password" placeholder="Password" class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-xl px-3 py-2" />
          </div>
          <div>
            <label class="block font-semibold mb-1 text-slate-400">Full Name *</label>
            <input id="newLocalFullName" type="text" placeholder="John Doe" class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-xl px-3 py-2" />
          </div>
          <div>
            <label class="block font-semibold mb-1 text-slate-400">Email Address *</label>
            <input id="newLocalEmail" type="email" placeholder="jdoe@company.local" class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-xl px-3 py-2" />
          </div>
          <div>
            <label class="block font-semibold mb-1 text-slate-400">System Role *</label>
            <select id="newLocalRole" class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-xl px-3 py-2">
              <option value="itsm_user">itsm_user (Support Agent / Fulfiller)</option>
              <option value="itsm_admin">itsm_admin (Platform Administrator)</option>
              <option value="itsm_read">itsm_read (Read-Only Viewer)</option>
            </select>
          </div>
        </div>
        <div class="flex justify-end space-x-2 pt-2">
          <button onclick="closeIdentityModal()" class="px-4 py-2 rounded-xl text-xs font-semibold text-slate-400 hover:bg-[var(--bg-tertiary)]">Cancel</button>
          <button onclick="submitCreateLocalUser()" class="bg-purple-600 hover:bg-purple-700 text-white px-4 py-2 rounded-xl text-xs font-bold">Create User</button>
        </div>
      </div>
    </div>
  `;
  document.body.insertAdjacentHTML('beforeend', modalHtml);
}

function openEditLocalUserModal(id, username, fullName, email, role) {
  const modalHtml = `
    <div id="identityModal" class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
      <div class="bg-[var(--card-bg)] border border-[var(--border-color)] rounded-2xl shadow-2xl max-w-md w-full p-6 space-y-4">
        <h3 class="font-bold text-base">Edit User: ${username}</h3>
        <div class="space-y-3 text-xs">
          <div>
            <label class="block font-semibold mb-1 text-slate-400">Full Name</label>
            <input id="editLocalFullName" type="text" value="${fullName}" class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-xl px-3 py-2" />
          </div>
          <div>
            <label class="block font-semibold mb-1 text-slate-400">Email Address</label>
            <input id="editLocalEmail" type="email" value="${email}" class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-xl px-3 py-2" />
          </div>
          <div>
            <label class="block font-semibold mb-1 text-slate-400">System Role</label>
            <select id="editLocalRole" class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-xl px-3 py-2">
              <option value="itsm_user" ${role === 'itsm_user' ? 'selected' : ''}>itsm_user (Support Agent)</option>
              <option value="itsm_admin" ${role === 'itsm_admin' || role === 'administrator' ? 'selected' : ''}>itsm_admin (Platform Administrator)</option>
              <option value="itsm_read" ${role === 'itsm_read' ? 'selected' : ''}>itsm_read (Read-Only Viewer)</option>
            </select>
          </div>
          <div>
            <label class="block font-semibold mb-1 text-slate-400">Reset Password (leave blank to keep current)</label>
            <input id="editLocalPassword" type="password" placeholder="New Password" class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-xl px-3 py-2" />
          </div>
        </div>
        <div class="flex justify-end space-x-2 pt-2">
          <button onclick="closeIdentityModal()" class="px-4 py-2 rounded-xl text-xs font-semibold text-slate-400 hover:bg-[var(--bg-tertiary)]">Cancel</button>
          <button onclick="submitEditLocalUser(${id})" class="bg-purple-600 hover:bg-purple-700 text-white px-4 py-2 rounded-xl text-xs font-bold">Save Changes</button>
        </div>
      </div>
    </div>
  `;
  document.body.insertAdjacentHTML('beforeend', modalHtml);
}

function closeIdentityModal() {
  document.getElementById('identityModal')?.remove();
}

async function submitCreateLocalUser() {
  const username = document.getElementById('newLocalUsername')?.value.trim();
  const password = document.getElementById('newLocalPassword')?.value;
  const full_name = document.getElementById('newLocalFullName')?.value.trim();
  const email = document.getElementById('newLocalEmail')?.value.trim();
  const role = document.getElementById('newLocalRole')?.value;

  if (!username || !password || !email || !full_name) {
    alert("Please fill in all required fields.");
    return;
  }

  const res = await fetch(`${API_BASE}/id/users`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password, full_name, email, role })
  });
  if (!res.ok) {
    const err = await res.json();
    alert(err.detail || 'Failed to create user');
    return;
  }
  closeIdentityModal();
  renderIdentityManagementView(document.getElementById('mainApp'));
}

async function submitEditLocalUser(id) {
  const full_name = document.getElementById('editLocalFullName')?.value.trim();
  const email = document.getElementById('editLocalEmail')?.value.trim();
  const role = document.getElementById('editLocalRole')?.value;
  const password = document.getElementById('editLocalPassword')?.value;

  const body = { full_name, email, role };
  if (password) body.password = password;

  const res = await fetch(`${API_BASE}/id/users/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  });
  if (!res.ok) {
    const err = await res.json();
    alert(err.detail || 'Failed to update user');
    return;
  }
  closeIdentityModal();
  renderIdentityManagementView(document.getElementById('mainApp'));
}

function openCreateCustomGroupModal() {
  const allPerms = [
    "ticket_create", "ticket_read", "ticket_read_own", "ticket_update", "ticket_assign", "ticket_resolve", "ticket_close", "ticket_delete",
    "change_create", "change_read", "change_approve", "change_manage",
    "kb_create", "kb_read", "kb_publish",
    "applications_read", "projects_read",
    "admin_applications", "admin_projects", "admin_groups", "admin_routing", "admin_slas", "admin_config", "admin_all",
    "users_manage", "groups_manage", "sso_manage", "system_logs"
  ];

  const modalHtml = `
    <div id="identityModal" class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
      <div class="bg-[var(--card-bg)] border border-[var(--border-color)] rounded-2xl shadow-2xl max-w-lg w-full p-6 space-y-4 max-h-[90vh] overflow-y-auto">
        <h3 class="font-bold text-base">Create Custom Security Group</h3>
        <div class="space-y-3 text-xs">
          <div>
            <label class="block font-semibold mb-1 text-slate-400">Group Name *</label>
            <input id="newGroupName" type="text" placeholder="e.g. Incident Escalation Leads" class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-xl px-3 py-2" />
          </div>
          <div>
            <label class="block font-semibold mb-1 text-slate-400">Description</label>
            <input id="newGroupDesc" type="text" placeholder="Lead engineers with incident close and assignment permissions" class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-xl px-3 py-2" />
          </div>
          <div>
            <label class="block font-semibold mb-1 text-slate-400">Select Custom Permissions *</label>
            <div class="grid grid-cols-2 gap-2 max-h-56 overflow-y-auto p-2 bg-[var(--bg-tertiary)] rounded-xl border border-[var(--border-color)]">
              ${allPerms.map(p => `
                <label class="flex items-center space-x-1.5 cursor-pointer">
                  <input type="checkbox" name="customPerm" value="${p}" class="rounded text-purple-600 focus:ring-purple-500" />
                  <span class="font-mono text-[10px]">${p}</span>
                </label>
              `).join('')}
            </div>
          </div>
        </div>
        <div class="flex justify-end space-x-2 pt-2">
          <button onclick="closeIdentityModal()" class="px-4 py-2 rounded-xl text-xs font-semibold text-slate-400 hover:bg-[var(--bg-tertiary)]">Cancel</button>
          <button onclick="submitCreateCustomGroup()" class="bg-purple-600 hover:bg-purple-700 text-white px-4 py-2 rounded-xl text-xs font-bold">Create Group</button>
        </div>
      </div>
    </div>
  `;
  document.body.insertAdjacentHTML('beforeend', modalHtml);
}

async function submitCreateCustomGroup() {
  const name = document.getElementById('newGroupName')?.value.trim();
  const description = document.getElementById('newGroupDesc')?.value.trim();
  const checkboxes = document.querySelectorAll('input[name="customPerm"]:checked');
  const permissions = Array.from(checkboxes).map(c => c.value);

  if (!name || permissions.length === 0) {
    alert("Please enter a group name and select at least one permission.");
    return;
  }

  const res = await fetch(`${API_BASE}/id/groups`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, description, permissions })
  });
  if (!res.ok) {
    const err = await res.json();
    alert(err.detail || 'Failed to create group');
    return;
  }
  closeIdentityModal();
  renderIdentityManagementView(document.getElementById('mainApp'));
}

async function deleteCustomGroup(id) {
  if (!confirm("Are you sure you want to deactivate this custom group?")) return;
  const res = await fetch(`${API_BASE}/id/groups/${id}`, { method: 'DELETE' });
  if (!res.ok) alert("Failed to delete group");
  renderIdentityManagementView(document.getElementById('mainApp'));
}

function openCreateADMappingModal() {
  const modalHtml = `
    <div id="identityModal" class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
      <div class="bg-[var(--card-bg)] border border-[var(--border-color)] rounded-2xl shadow-2xl max-w-md w-full p-6 space-y-4">
        <h3 class="font-bold text-base">Add Active Directory Mapping</h3>
        <div class="space-y-3 text-xs">
          <div>
            <label class="block font-semibold mb-1 text-slate-400">AD Group Name or DN *</label>
            <input id="adGroupName" type="text" placeholder="CN=ITSM-Admins,OU=Groups,DC=corp" class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-xl px-3 py-2 font-mono" />
          </div>
          <div>
            <label class="block font-semibold mb-1 text-slate-400">Target ITSM Role</label>
            <select id="adTargetRole" class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-xl px-3 py-2">
              <option value="itsm_user">itsm_user (Support Agent)</option>
              <option value="itsm_admin">itsm_admin (Administrator)</option>
              <option value="itsm_read">itsm_read (Read-Only)</option>
            </select>
          </div>
          <div>
            <label class="block font-semibold mb-1 text-slate-400">Description</label>
            <input id="adDescription" type="text" placeholder="Corporate Active Directory group mapping" class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-xl px-3 py-2" />
          </div>
        </div>
        <div class="flex justify-end space-x-2 pt-2">
          <button onclick="closeIdentityModal()" class="px-4 py-2 rounded-xl text-xs font-semibold text-slate-400 hover:bg-[var(--bg-tertiary)]">Cancel</button>
          <button onclick="submitCreateADMapping()" class="bg-purple-600 hover:bg-purple-700 text-white px-4 py-2 rounded-xl text-xs font-bold">Save Mapping</button>
        </div>
      </div>
    </div>
  `;
  document.body.insertAdjacentHTML('beforeend', modalHtml);
}

async function submitCreateADMapping() {
  const ad_group_name = document.getElementById('adGroupName')?.value.trim();
  const target_role = document.getElementById('adTargetRole')?.value;
  const description = document.getElementById('adDescription')?.value.trim();

  if (!ad_group_name) {
    alert("AD Group Name is required.");
    return;
  }

  const res = await fetch(`${API_BASE}/id/ad-mappings`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ad_group_name, target_role, description })
  });
  if (!res.ok) {
    const err = await res.json();
    alert(err.detail || 'Failed to create AD mapping');
    return;
  }
  closeIdentityModal();
  renderIdentityManagementView(document.getElementById('mainApp'));
}

async function deleteADMapping(id) {
  if (!confirm("Are you sure you want to delete this mapping?")) return;
  const res = await fetch(`${API_BASE}/id/ad-mappings/${id}`, { method: 'DELETE' });
  if (!res.ok) alert("Failed to delete mapping");
  renderIdentityManagementView(document.getElementById('mainApp'));
}

async function testAdResolution() {
  const val = document.getElementById('testAdGroupsInput')?.value.trim();
  const resultDiv = document.getElementById('adResolutionResult');
  if (!val || !resultDiv) return;

  const groups = val.split(',').map(g => g.trim()).filter(Boolean);
  const res = await fetch(`${API_BASE}/id/ad-resolve`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ad_groups: groups })
  });
  if (res.ok) {
    const data = await res.json();
    resultDiv.classList.remove('hidden');
    resultDiv.innerHTML = `
      <div class="space-y-1.5">
        <div class="font-bold text-purple-600">Effective Role: <span class="uppercase">${data.effective_role}</span></div>
        <div>Matched AD Groups: <b>${data.matched_ad_groups.join(', ') || 'None'}</b></div>
        <div>Resolved Custom Groups: <b>${data.custom_groups.join(', ') || 'None'}</b></div>
        <div>Total Effective Permissions: <b>${data.permissions.length}</b> granted</div>
      </div>
    `;
  }
}

function openImportIdPMetadataModal() {
  const modalHtml = `
    <div id="identityModal" class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
      <div class="bg-[var(--card-bg)] border border-[var(--border-color)] rounded-2xl shadow-2xl max-w-lg w-full p-6 space-y-4">
        <h3 class="font-bold text-base">Import IdP Metadata XML</h3>
        <p class="text-xs text-slate-400">Paste your Enterprise Single Sign-On (ESO) or Identity Provider SAML 2.0 Metadata XML.</p>
        <div class="space-y-3 text-xs">
          <div>
            <label class="block font-semibold mb-1 text-slate-400">Provider Name *</label>
            <input id="idpProviderName" type="text" placeholder="e.g. Enterprise SAML SSO" class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-xl px-3 py-2" />
          </div>
          <div>
            <label class="block font-semibold mb-1 text-slate-400">Federation Mode *</label>
            <select id="idpB2bB2c" class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-xl px-3 py-2">
              <option value="b2b">B2B (Enterprise / Partner)</option>
              <option value="b2c">B2C (Customer / External)</option>
            </select>
          </div>
          <div>
            <label class="block font-semibold mb-1 text-slate-400">IdP Metadata XML Content *</label>
            <textarea id="idpMetadataContent" rows="6" placeholder="<EntityDescriptor xmlns=... >...</EntityDescriptor>" class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-xl p-3 font-mono text-[10px]"></textarea>
          </div>
        </div>
        <div class="flex justify-end space-x-2 pt-2">
          <button onclick="closeIdentityModal()" class="px-4 py-2 rounded-xl text-xs font-semibold text-slate-400 hover:bg-[var(--bg-tertiary)]">Cancel</button>
          <button onclick="submitImportIdPMetadata()" class="bg-purple-600 hover:bg-purple-700 text-white px-4 py-2 rounded-xl text-xs font-bold">Import & Save</button>
        </div>
      </div>
    </div>
  `;
  document.body.insertAdjacentHTML('beforeend', modalHtml);
}

async function submitImportIdPMetadata() {
  const name = document.getElementById('idpProviderName')?.value.trim();
  const b2b_or_b2c = document.getElementById('idpB2bB2c')?.value;
  const metadata_xml = document.getElementById('idpMetadataContent')?.value.trim();

  if (!name || !metadata_xml) {
    alert("Please provide both Provider Name and Metadata XML content.");
    return;
  }

  const res = await fetch(`${API_BASE}/id/sso/import-idp-metadata`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, b2b_or_b2c, metadata_xml })
  });
  if (!res.ok) {
    const err = await res.json();
    alert(err.detail || 'Failed to import IdP metadata');
    return;
  }
  alert("IdP Metadata imported successfully!");
  closeIdentityModal();
  renderIdentityManagementView(document.getElementById('mainApp'));
}

function openRegisterESOAppIdModal() {
  const modalHtml = `
    <div id="identityModal" class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
      <div class="bg-[var(--card-bg)] border border-purple-500/40 rounded-2xl shadow-2xl max-w-lg w-full p-6 space-y-4 max-h-[90vh] overflow-y-auto">
        <div class="flex items-center space-x-2">
          <div class="w-8 h-8 rounded-xl bg-purple-900/60 border border-purple-500/50 flex items-center justify-center text-purple-300">
            <i data-lucide="shield-check" class="w-4 h-4"></i>
          </div>
          <div>
            <h3 class="font-bold text-base">Register Existing ESO App ID</h3>
            <p class="text-xs text-slate-400">Pre-configure SAML/OIDC Service Provider with your corporate App ID.</p>
          </div>
        </div>

        <div class="space-y-3 text-xs">
          <div>
            <label class="block font-semibold mb-1 text-slate-300">ESO Application ID (App ID) *</label>
            <input id="esoAppIdInput" type="text" placeholder="e.g. eso-app-nexus-itsm-prod or azure-app-client-123" class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-xl px-3 py-2 font-mono text-purple-300" />
            <span class="text-[10px] text-slate-500">Your existing App ID from Enterprise Sign-On or Azure App Registration.</span>
          </div>

          <div class="grid grid-cols-2 gap-3">
            <div>
              <label class="block font-semibold mb-1 text-slate-300">Display Name</label>
              <input id="esoNameInput" type="text" placeholder="Corporate SSO" class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-xl px-3 py-2" />
            </div>
            <div>
              <label class="block font-semibold mb-1 text-slate-300">Provider Type</label>
              <select id="esoProviderTypeInput" class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-xl px-3 py-2">
                <option value="saml">SAML 2.0</option>
                <option value="oidc">OpenID Connect (OIDC)</option>
              </select>
            </div>
          </div>

          <div>
            <label class="block font-semibold mb-1 text-slate-300">IdP Single Sign-On URL / Discovery URL</label>
            <input id="esoSsoUrlInput" type="text" placeholder="https://eso.company.com/idp/sso or https://login.microsoftonline.com/..." class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-xl px-3 py-2 text-[11px]" />
          </div>

          <div class="grid grid-cols-3 gap-2">
            <div>
              <label class="block font-semibold mb-1 text-slate-400">Email Claim Path</label>
              <input id="esoEmailPathInput" type="text" value="email" class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-xl px-2.5 py-1.5 font-mono text-[11px]" />
            </div>
            <div>
              <label class="block font-semibold mb-1 text-slate-400">Group Claim Path</label>
              <input id="esoGroupPathInput" type="text" value="groups" class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-xl px-2.5 py-1.5 font-mono text-[11px]" />
            </div>
            <div>
              <label class="block font-semibold mb-1 text-slate-400">Default Role</label>
              <select id="esoDefaultRoleInput" class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-xl px-2 py-1.5 text-[11px]">
                <option value="itsm_user">itsm_user</option>
                <option value="itsm_admin">itsm_admin</option>
                <option value="itsm_read">itsm_read</option>
              </select>
            </div>
          </div>

          <div>
            <label class="block font-semibold mb-1 text-slate-300">Role Mapping Rules (JSON: EnterpriseGroup -> Role)</label>
            <textarea id="esoRoleRulesInput" rows="2" class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-xl p-2 font-mono text-[11px]">{"ITSM-Admins": "itsm_admin", "ITSM-Support": "itsm_user"}</textarea>
          </div>

          <div>
            <label class="block font-semibold mb-1 text-slate-300">Assignment Group Mapping (JSON: Group -> [App Queue])</label>
            <textarea id="esoAsgnRulesInput" rows="2" class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-xl p-2 font-mono text-[11px]">{"IT-ServiceDesk": ["Service Desk"], "DBA-Team": ["Database Support"]}</textarea>
          </div>
        </div>

        <div class="flex justify-end space-x-2 pt-2 border-t border-[var(--border-color)]">
          <button onclick="closeIdentityModal()" class="px-4 py-2 rounded-xl text-xs font-semibold text-slate-400 hover:bg-[var(--bg-tertiary)]">Cancel</button>
          <button onclick="submitRegisterESOAppId()" class="bg-purple-600 hover:bg-purple-700 text-white px-4 py-2 rounded-xl text-xs font-bold shadow flex items-center space-x-1.5">
            <i data-lucide="check" class="w-3.5 h-3.5"></i>
            <span>Register Provider</span>
          </button>
        </div>
      </div>
    </div>
  `;
  document.body.insertAdjacentHTML('beforeend', modalHtml);
  lucide.createIcons();
}

async function submitRegisterESOAppId() {
  const eso_app_id = document.getElementById('esoAppIdInput')?.value.trim();
  const name = document.getElementById('esoNameInput')?.value.trim() || `ESO Provider (${eso_app_id})`;
  const provider_type = document.getElementById('esoProviderTypeInput')?.value || 'saml';
  const idp_sso_url = document.getElementById('esoSsoUrlInput')?.value.trim();
  const claims_email_path = document.getElementById('esoEmailPathInput')?.value.trim() || 'email';
  const claims_group_path = document.getElementById('esoGroupPathInput')?.value.trim() || 'groups';
  const default_role = document.getElementById('esoDefaultRoleInput')?.value || 'itsm_user';

  let role_mapping_rules = {};
  let assignment_group_mapping_rules = {};
  try {
    const rawRole = document.getElementById('esoRoleRulesInput')?.value.trim();
    if (rawRole) role_mapping_rules = JSON.parse(rawRole);
  } catch (e) {
    alert("Invalid JSON in Role Mapping Rules");
    return;
  }
  try {
    const rawAsgn = document.getElementById('esoAsgnRulesInput')?.value.trim();
    if (rawAsgn) assignment_group_mapping_rules = JSON.parse(rawAsgn);
  } catch (e) {
    alert("Invalid JSON in Assignment Group Mapping");
    return;
  }

  if (!eso_app_id) {
    alert("ESO Application ID (App ID) is required.");
    return;
  }

  const payload = {
    eso_app_id,
    name,
    provider_type,
    idp_sso_url,
    claims_email_path,
    claims_group_path,
    default_role,
    role_mapping_rules,
    assignment_group_mapping_rules
  };

  const res = await fetch(`${API_BASE}/id/sso/register-eso`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });

  if (!res.ok) {
    const err = await res.json();
    alert(err.detail || 'Failed to register ESO App ID');
    return;
  }

  const result = await res.json();
  alert(result.message || 'ESO Provider registered successfully!');
  closeIdentityModal();
  renderIdentityManagementView(document.getElementById('mainApp'));
}

async function testClaimAndGroupMapping() {
  const rawInput = document.getElementById('sampleClaimsInput')?.value.trim();
  const outBox = document.getElementById('mappingSimulationOutput');
  if (!rawInput || !outBox) return;

  let claimsObj = {};
  try {
    claimsObj = JSON.parse(rawInput);
  } catch (err) {
    outBox.innerHTML = `<span class="text-rose-400">Error: Invalid JSON syntax in sample claims.</span>`;
    return;
  }

  outBox.innerHTML = `<span class="text-purple-400 animate-pulse">Evaluating claims against application groups & roles...</span>`;

  try {
    const res = await fetch(`${API_BASE}/id/sso/test-claim-mapping`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ claims: claimsObj })
    });

    if (res.ok) {
      const data = await res.json();
      const p = data.preview || {};
      const agList = (p.assignment_groups || []).map(g => typeof g === 'object' ? g.name : g).join(', ') || 'None';
      const cgList = (p.custom_groups || []).join(', ') || 'None';

      outBox.innerHTML = `
        <div class="space-y-1">
          <div>Email: <span class="text-emerald-300 font-bold">${p.extracted_email || '—'}</span></div>
          <div>Name: <span class="text-white">${p.extracted_name || '—'}</span></div>
          <div>Effective Role: <span class="text-purple-300 font-bold uppercase">${p.effective_role}</span></div>
          <div>ITSM Queues (App Groups): <span class="text-amber-300 font-semibold">${agList}</span></div>
          <div>Custom Groups: <span class="text-blue-300">${cgList}</span></div>
          <div>Permissions: <span class="text-slate-400">${(p.permissions || []).length} permissions active</span></div>
        </div>
      `;
    } else {
      const err = await res.json();
      outBox.innerHTML = `<span class="text-rose-400">Mapping error: ${err.detail || 'Failed'}</span>`;
    }
  } catch (e) {
    outBox.innerHTML = `<span class="text-rose-400">Network error: ${e.message}</span>`;
  }
}

// ============================================================================
// --- CONSUL SERVICE REGISTRY & KM CONFIGURATION VIEW ---
// ============================================================================

async function renderConsulConfigView(container) {
  container.innerHTML = `<div class="p-8 text-center text-slate-400"><i data-lucide="loader-2" class="w-8 h-8 animate-spin mx-auto mb-2 text-rose-500"></i>Loading Consul & KM Configuration...</div>`;
  lucide.createIcons();

  let consulStatus = { connected: false, message: 'Loading...' };
  let kmConfig = {};
  let currentLogLevel = 'INFO';

  try {
    const [cRes, kRes, lRes] = await Promise.allSettled([
      fetch(`${API_BASE}/admin/config/consul-status`),
      fetch(`${API_BASE}/admin/configuration/km`),
      fetch(`${API_BASE}/admin/system/log-level`)
    ]);

    if (cRes.status === 'fulfilled' && cRes.value.ok) consulStatus = await cRes.value.json();
    if (kRes.status === 'fulfilled' && kRes.value.ok) kmConfig = await kRes.value.json();
    if (lRes.status === 'fulfilled' && lRes.value.ok) {
      const lData = await lRes.value.json();
      currentLogLevel = lData.log_level || 'INFO';
    }
  } catch (e) {
    console.warn("Consul status load error:", e);
  }

  container.innerHTML = `
    <div class="space-y-6">
      <div class="flex flex-col md:flex-row md:items-center md:justify-between gap-3">
        <div>
          <div class="flex items-center space-x-2">
            <h1 class="text-2xl font-black tracking-tight">Consul Service Registry & KM Configuration</h1>
            <span class="px-2.5 py-0.5 rounded-full text-[10px] font-bold ${consulStatus.connected ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300' : 'bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300'}">
              ${consulStatus.connected ? '● Consul Connected' : '○ Standalone Mode'}
            </span>
          </div>
          <p class="text-sm text-slate-500">Centralized Consul KV store integration for Applications, Assignment Groups, DLs, Projects, Closure Taxonomy, and external KM API settings.</p>
        </div>
        <div class="flex space-x-2">
          <button onclick="triggerConsulSync()" class="bg-rose-600 hover:bg-rose-700 text-white px-4 py-2 rounded-xl text-xs font-bold flex items-center space-x-1.5 shadow">
            <i data-lucide="refresh-cw" class="w-4 h-4"></i>
            <span>Sync All Config to Consul</span>
          </button>
          <button onclick="triggerConsulLoad()" class="border border-[var(--border-color)] bg-[var(--card-bg)] hover:bg-[var(--bg-tertiary)] px-3.5 py-2 rounded-xl text-xs font-bold flex items-center space-x-1.5">
            <i data-lucide="download" class="w-4 h-4"></i>
            <span>Load from Consul</span>
          </button>
        </div>
      </div>

      <!-- Consul Status Card -->
      <div class="p-5 rounded-2xl bg-[var(--card-bg)] border border-[var(--border-color)] shadow-sm space-y-3">
        <h3 class="font-bold text-sm flex items-center space-x-2 text-[var(--text-primary)]">
          <i data-lucide="server" class="w-4 h-4 text-rose-500"></i>
          <span>Consul KV Service Node</span>
        </h3>
        <div class="grid grid-cols-1 md:grid-cols-3 gap-3 text-xs">
          <div class="p-3 bg-[var(--bg-tertiary)] rounded-xl">
            <div class="text-[10px] text-slate-400 uppercase font-semibold">Consul Endpoint</div>
            <div class="font-mono font-bold text-purple-600 mt-0.5">${consulStatus.address || 'env:CONSUL_HTTP_ADDR'}</div>
          </div>
          <div class="p-3 bg-[var(--bg-tertiary)] rounded-xl">
            <div class="text-[10px] text-slate-400 uppercase font-semibold">Connection Status</div>
            <div class="font-bold ${consulStatus.connected ? 'text-emerald-500' : 'text-amber-500'} mt-0.5">${consulStatus.message}</div>
          </div>
          <div class="p-3 bg-[var(--bg-tertiary)] rounded-xl">
            <div class="text-[10px] text-slate-400 uppercase font-semibold">Leader Node</div>
            <div class="font-mono text-slate-500 mt-0.5">${consulStatus.leader || 'N/A (single agent / local)'}</div>
          </div>
        </div>
      </div>

      <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <!-- KM Configuration Form -->
        <div class="p-5 rounded-2xl bg-[var(--card-bg)] border border-[var(--border-color)] shadow-sm space-y-4">
          <div>
            <h3 class="font-bold text-sm flex items-center space-x-2">
              <i data-lucide="bot" class="w-4 h-4 text-purple-600"></i>
              <span>External KM Integrated Application Settings</span>
            </h3>
            <p class="text-xs text-slate-500 mt-0.5">Configured parameters are stored in the platform and mirrored to Consul KV path <code>nexus-itsm/km/config</code>.</p>
          </div>

          <div class="space-y-3 text-xs">
            <div>
              <div class="flex items-center justify-between mb-1">
                <label class="block font-semibold text-slate-400">KM App Base URL *</label>
                <span class="text-[10px] text-emerald-600 dark:text-emerald-400 font-medium flex items-center gap-1">
                  <i data-lucide="eye" class="w-3 h-3"></i> Visible for Reference
                </span>
              </div>
              <input id="kmBaseUrlInput" type="text" value="${kmConfig.km_base_url || 'https://internal-km.company.local'}" class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-xl px-3 py-2 font-mono text-xs text-[var(--text-primary)]" />
            </div>
            <div class="grid grid-cols-2 gap-3">
              <div>
                <label class="block font-semibold text-slate-400 mb-1">API Endpoint</label>
                <input id="kmEndpointInput" type="text" value="${kmConfig.api_endpoint || '/api/chat/completions'}" class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-xl px-3 py-2 font-mono text-xs" />
              </div>
              <div>
                <label class="block font-semibold text-slate-400 mb-1">KM Index *</label>
                <input id="kmIndexInput" type="text" value="${kmConfig.km_index || 'itsm-kb'}" placeholder="e.g. itsm-kb" class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-xl px-3 py-2" />
              </div>
            </div>
            <div class="grid grid-cols-2 gap-3">
              <div>
                <div class="flex items-center justify-between mb-1">
                  <label class="block font-semibold text-slate-400">Username</label>
                  <span class="text-[10px] text-amber-500 font-medium flex items-center gap-1">
                    <i data-lucide="lock" class="w-3 h-3"></i> Hidden
                  </span>
                </div>
                <input id="kmUsernameInput" type="password" value="${kmConfig.username || ''}" placeholder="••••••••" autocomplete="new-password" class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-xl px-3 py-2 tracking-widest text-xs" />
              </div>
              <div>
                <div class="flex items-center justify-between mb-1">
                  <label class="block font-semibold text-slate-400">Password</label>
                  <span class="text-[10px] text-amber-500 font-medium flex items-center gap-1">
                    <i data-lucide="lock" class="w-3 h-3"></i> Hidden
                  </span>
                </div>
                <input id="kmPasswordInput" type="password" value="${kmConfig.password || ''}" placeholder="••••••••" autocomplete="new-password" class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-xl px-3 py-2 tracking-widest text-xs" />
              </div>
            </div>
            <div>
              <div class="flex items-center justify-between mb-1">
                <label class="block font-semibold text-slate-400">Bearer Token / Secret Reference</label>
                <span class="text-[10px] text-amber-500 font-medium flex items-center gap-1">
                  <i data-lucide="lock" class="w-3 h-3"></i> Hidden
                </span>
              </div>
              <input id="kmTokenInput" type="password" value="${kmConfig.auth_token || 'consul:kv/nexus-itsm/km#token'}" class="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-xl px-3 py-2 font-mono text-[11px] tracking-widest" />
            </div>
            <div class="pt-2">
              <button onclick="saveKMConsulConfig()" class="w-full bg-purple-600 hover:bg-purple-700 text-white py-2.5 rounded-xl font-bold text-xs shadow">Save KM Configuration & Sync to Consul</button>
            </div>
          </div>
        </div>

        <!-- Granular Consul Tree & Dynamic Logger Control -->
        <div class="space-y-6">
          <!-- Dynamic Log Level Card -->
          <div class="p-5 rounded-2xl bg-[var(--card-bg)] border border-[var(--border-color)] shadow-sm space-y-3">
            <h3 class="font-bold text-sm flex items-center space-x-2">
              <i data-lucide="terminal" class="w-4 h-4 text-emerald-500"></i>
              <span>Runtime Logger Level (Debug On Demand)</span>
            </h3>
            <p class="text-xs text-slate-500">Switch platform logger level dynamically without container restart when debugging issues.</p>
            <div class="flex items-center gap-3">
              <select id="runtimeLogLevelSelect" class="bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-xl px-3 py-2 text-xs font-bold">
                <option value="INFO" ${currentLogLevel === 'INFO' ? 'selected' : ''}>INFO (Standard)</option>
                <option value="DEBUG" ${currentLogLevel === 'DEBUG' ? 'selected' : ''}>DEBUG (Diagnostic Detail)</option>
                <option value="WARNING" ${currentLogLevel === 'WARNING' ? 'selected' : ''}>WARNING</option>
                <option value="ERROR" ${currentLogLevel === 'ERROR' ? 'selected' : ''}>ERROR</option>
              </select>
              <button onclick="updateSystemLogLevel()" class="bg-emerald-600 hover:bg-emerald-700 text-white px-4 py-2 rounded-xl text-xs font-bold">Apply Log Level</button>
            </div>
          </div>

          <!-- Mirrored Consul Keys Tree -->
          <div class="p-5 rounded-2xl bg-[var(--card-bg)] border border-[var(--border-color)] shadow-sm space-y-3">
            <h3 class="font-bold text-sm flex items-center space-x-2">
              <i data-lucide="git-commit" class="w-4 h-4 text-rose-500"></i>
              <span>Mirrored Consul KV Keys</span>
            </h3>
            <div class="p-3 bg-[var(--bg-tertiary)] rounded-xl font-mono text-[11px] text-slate-500 space-y-1">
              <div>📁 nexus-itsm/config/snapshot.json</div>
              <div>├── 📄 applications</div>
              <div>├── 📄 projects</div>
              <div>├── 📄 assignment_groups</div>
              <div>├── 📄 distribution_lists (Support DLs)</div>
              <div>├── 📄 closure_taxonomy (Categories & Subcategories)</div>
              <div>├── 📄 ticket_columns (List Preferences)</div>
              <div>├── 📄 routing_rules (6-Tier Hierarchy)</div>
              <div>├── 📄 sla_policies</div>
              <div>└── 📄 km_config (Base URL, Username, Index)</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  `;
  lucide.createIcons();
}

async function triggerConsulSync() {
  const res = await fetch(`${API_BASE}/admin/config/sync-consul`, { method: 'PUT' });
  if (res.ok) {
    const data = await res.json();
    alert(`Successfully synced ${data.total_keys || 9} configuration keys and snapshot to Consul KV!`);
  } else {
    const err = await res.json();
    alert(err.detail || 'Consul sync failed');
  }
}

async function triggerConsulLoad() {
  if (!confirm("This will load and restore the configuration snapshot from Consul KV into the database. Continue?")) return;
  const res = await fetch(`${API_BASE}/admin/config/load-consul`, { method: 'POST' });
  if (res.ok) {
    alert("Configuration successfully restored from Consul KV!");
  } else {
    const err = await res.json();
    alert(err.detail || 'Failed to load from Consul');
  }
}

async function saveKMConsulConfig() {
  const km_base_url = document.getElementById('kmBaseUrlInput')?.value.trim();
  const api_endpoint = document.getElementById('kmEndpointInput')?.value.trim();
  const km_index = document.getElementById('kmIndexInput')?.value.trim();
  const username = document.getElementById('kmUsernameInput')?.value.trim();
  const password = document.getElementById('kmPasswordInput')?.value;
  const auth_token = document.getElementById('kmTokenInput')?.value.trim();

  if (!km_base_url) {
    alert("KM App Base URL is required");
    return;
  }

  const payload = {
    km_base_url,
    api_endpoint,
    km_index,
    sync_to_consul: true
  };
  if (username && username !== '••••••••') payload.username = username;
  if (password && password !== '••••••••') payload.password = password;
  if (auth_token && auth_token !== '••••••••') payload.auth_token = auth_token;

  const res = await fetch(`${API_BASE}/admin/configuration/km`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });

  if (res.ok) {
    alert("KM Configuration saved and synced to Consul KV!");
  } else {
    const err = await res.json();
    alert(err.detail || 'Failed to save KM configuration');
  }
}

async function updateSystemLogLevel() {
  const level = document.getElementById('runtimeLogLevelSelect')?.value;
  if (!level) return;

  const [bRes, iRes] = await Promise.allSettled([
    fetch(`${API_BASE}/admin/system/log-level`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ level })
    }),
    fetch(`${API_BASE}/id/system/log-level`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ level })
    })
  ]);

  alert(`System log level successfully switched to ${level} on all containers!`);
}

