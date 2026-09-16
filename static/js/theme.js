/*
  Theme switching (light / dark / system), persisted to localStorage.
  The actual FIRST paint is handled by a tiny inline script in base.html's
  <head> (must run synchronously before CSS renders to avoid a flash of the
  wrong theme) - this file only wires up the visible toggle control and
  keeps it in sync afterwards.
*/
(function () {
  var STORAGE_KEY = 'hms-theme';

  function resolvedTheme(pref) {
    if (pref === 'light' || pref === 'dark') return pref;
    return (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) ? 'dark' : 'light';
  }

  function apply(pref) {
    var root = document.documentElement;
    if (pref === 'light' || pref === 'dark') {
      root.setAttribute('data-theme', pref);
    } else {
      root.removeAttribute('data-theme'); // 'system' -> let prefers-color-scheme decide
    }
    updateToggleUI(pref);
    // Let chart/canvas-based widgets on the page redraw with theme-correct
    // colors (Chart.js etc. can't read CSS variables on their own).
    document.dispatchEvent(new CustomEvent('hms:themechange', {
      detail: { preference: pref, resolved: resolvedTheme(pref) }
    }));
  }

  function updateToggleUI(pref) {
    document.querySelectorAll('.theme-toggle [data-theme-choice]').forEach(function (btn) {
      var isActive = btn.getAttribute('data-theme-choice') === pref;
      btn.classList.toggle('is-active', isActive);
      btn.setAttribute('aria-pressed', isActive ? 'true' : 'false');
    });
  }

  function currentPreference() {
    try {
      return localStorage.getItem(STORAGE_KEY) || 'system';
    } catch (e) {
      return 'system';
    }
  }

  function setPreference(pref) {
    try {
      localStorage.setItem(STORAGE_KEY, pref);
    } catch (e) { /* private browsing / storage disabled - theme just won't persist */ }
    apply(pref);
  }

  document.addEventListener('DOMContentLoaded', function () {
    apply(currentPreference());
    document.querySelectorAll('.theme-toggle [data-theme-choice]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        setPreference(btn.getAttribute('data-theme-choice'));
      });
    });
  });

  window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', function () {
    if (currentPreference() === 'system') apply('system');
  });
})();
