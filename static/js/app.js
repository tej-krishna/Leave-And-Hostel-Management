/*
  Application shell behavior: sidebar collapse/drawer, toast rendering,
  modal open/close, and a small helper to prevent duplicate form submits.
  Kept dependency-free and modular by concern (see sections below) rather
  than one monolithic script.
*/

/* ---------------- Sidebar ---------------- */
(function sidebarModule() {
  var COLLAPSE_KEY = 'hms-sidebar-collapsed';

  document.addEventListener('DOMContentLoaded', function () {
    var sidebar = document.getElementById('appSidebar');
    var backdrop = document.getElementById('sidebarBackdrop');
    if (!sidebar) return;

    var collapseBtn = document.getElementById('sidebarCollapseBtn');
    var hamburger = document.getElementById('hamburgerBtn');

    if (window.innerWidth > 1024) {
      try {
        if (localStorage.getItem(COLLAPSE_KEY) === 'true') sidebar.classList.add('is-collapsed');
      } catch (e) {}
    }

    if (collapseBtn) {
      collapseBtn.addEventListener('click', function () {
        sidebar.classList.toggle('is-collapsed');
        try { localStorage.setItem(COLLAPSE_KEY, sidebar.classList.contains('is-collapsed')); } catch (e) {}
      });
    }

    function openDrawer() {
      sidebar.classList.add('is-mobile-open');
      if (backdrop) backdrop.classList.add('is-visible');
      document.body.style.overflow = 'hidden';
    }
    function closeDrawer() {
      sidebar.classList.remove('is-mobile-open');
      if (backdrop) backdrop.classList.remove('is-visible');
      document.body.style.overflow = '';
    }

    if (hamburger) hamburger.addEventListener('click', openDrawer);
    if (backdrop) backdrop.addEventListener('click', closeDrawer);
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') closeDrawer();
    });
    sidebar.querySelectorAll('.nav-item').forEach(function (link) {
      link.addEventListener('click', closeDrawer);
    });
  });
})();

/* ---------------- Toasts ---------------- */
window.HMSToast = (function toastModule() {
  function ensureStack() {
    var stack = document.querySelector('.toast-stack');
    if (!stack) {
      stack = document.createElement('div');
      stack.className = 'toast-stack';
      stack.setAttribute('role', 'status');
      stack.setAttribute('aria-live', 'polite');
      document.body.appendChild(stack);
    }
    return stack;
  }

  var ICONS = {
    success: '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 10.5l4 4 8-9"/></svg>',
    error: '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="2"><circle cx="10" cy="10" r="8"/><path d="M7 7l6 6M13 7l-6 6"/></svg>',
    warning: '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="2"><path d="M10 2l9 16H1L10 2z"/><path d="M10 8v4M10 14h.01"/></svg>',
    info: '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="2"><circle cx="10" cy="10" r="8"/><path d="M10 9v5M10 6h.01"/></svg>'
  };

  function show(message, type) {
    type = type && ICONS[type] ? type : 'info';
    var stack = ensureStack();
    var toast = document.createElement('div');
    toast.className = 'toast toast-' + type;
    toast.innerHTML = '<span style="width:16px;height:16px;flex-shrink:0;">' + ICONS[type] + '</span>' +
      '<span>' + message + '</span>' +
      '<button class="toast-close" aria-label="Dismiss">&times;</button>';
    toast.querySelector('.toast-close').addEventListener('click', function () { remove(toast); });
    stack.appendChild(toast);
    var timer = setTimeout(function () { remove(toast); }, 5000);
    toast.addEventListener('mouseenter', function () { clearTimeout(timer); });
    return toast;
  }

  function remove(toast) {
    toast.style.opacity = '0';
    toast.style.transform = 'translateX(12px)';
    setTimeout(function () { toast.remove(); }, 150);
  }

  return { show: show };
})();

/* Render Django messages (dropped into the page as a JSON script tag by
   base.html) as toasts on load, so every page gets consistent, dismissible
   notifications instead of a static colored banner. */
document.addEventListener('DOMContentLoaded', function () {
  var el = document.getElementById('django-messages-data');
  if (!el) return;
  try {
    var messages = JSON.parse(el.textContent);
    messages.forEach(function (m) {
      var type = { success: 'success', error: 'error', warning: 'warning', info: 'info', debug: 'info' }[m.tags] || 'info';
      window.HMSToast.show(m.text, type);
    });
  } catch (e) { /* malformed/empty - nothing to show */ }
});

/* ---------------- Modals ---------------- */
window.HMSModal = (function modalModule() {
  function open(id) {
    var overlay = document.getElementById(id);
    if (overlay) overlay.classList.add('is-open');
  }
  function close(overlay) {
    overlay.classList.remove('is-open');
  }
  document.addEventListener('click', function (e) {
    var opener = e.target.closest('[data-modal-open]');
    if (opener) { open(opener.getAttribute('data-modal-open')); return; }
    var closer = e.target.closest('[data-modal-close]');
    if (closer) { close(closer.closest('.modal-overlay')); return; }
    if (e.target.classList.contains('modal-overlay')) close(e.target);
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') {
      document.querySelectorAll('.modal-overlay.is-open').forEach(close);
    }
  });
  return { open: open, close: close };
})();

/* ---------------- Theme-aware chart colors ----------------
   Chart.js (and any other canvas-based chart) can't read CSS custom
   properties on its own, so this reads the current computed values once
   and hands back a plain object. Call it again inside an
   'hms:themechange' listener to redraw charts after a theme switch. */
window.HMSChartColors = function () {
  var s = getComputedStyle(document.documentElement);
  var get = function (name) { return s.getPropertyValue(name).trim(); };
  return {
    text: get('--text-secondary'),
    muted: get('--text-muted'),
    border: get('--border'),
    grid: get('--border-subtle'),
    primary: get('--primary'),
    success: get('--status-success'),
    warning: get('--status-warning'),
    danger: get('--status-danger'),
    info: get('--status-info'),
    surface: get('--surface')
  };
};

/* ---------------- Prevent duplicate submissions ---------------- */
document.addEventListener('submit', function (e) {
  var form = e.target;
  if (form.dataset.noLoadingState) return;
  var submitBtn = form.querySelector('button[type="submit"]');
  if (!submitBtn || submitBtn.classList.contains('is-loading')) return;
  submitBtn.classList.add('is-loading');
  submitBtn.disabled = true;
}, true);
